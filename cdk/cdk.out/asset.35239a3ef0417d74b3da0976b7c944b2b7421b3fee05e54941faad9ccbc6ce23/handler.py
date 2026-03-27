"""
Cleaner Lambda
──────────────
Triggered every 1 minute by an EventBridge scheduled rule.

Queries DisownedIndex for copies with:
    status = "disowned"  AND  disownedAt < (now - DISOWNED_TTL_SEC * 1000)

Deletes matching copies from Bucket Dst and removes their records from Table T.
No table scan is needed – the GSI supports a direct range query.
"""

import os
import time
import logging
import boto3
from boto3.dynamodb.conditions import Key, Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3  = boto3.client("s3")
ddb = boto3.resource("dynamodb")

BUCKET_DST       = os.environ["BUCKET_DST"]
TABLE_NAME       = os.environ["TABLE_NAME"]
DISOWNED_TTL_SEC = int(os.environ["DISOWNED_TTL_SEC"])

table = ddb.Table(TABLE_NAME)


def lambda_handler(event, context):
    threshold_ms = int((time.time() - DISOWNED_TTL_SEC) * 1000)
    logger.info("Cleaning disowned copies older than %d ms epoch", threshold_ms)

    # ── Query DisownedIndex (no scan) ─────────────────────────────────────
    # PK = "disowned", SK < threshold_ms
    items = []
    query_kwargs = {
        "IndexName": "DisownedIndex",
        "KeyConditionExpression": (
            Key("status").eq("disowned") &
            Key("disownedAt").lt(threshold_ms)
        ),
    }

    resp = table.query(**query_kwargs)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.query(**query_kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))

    if not items:
        logger.info("Nothing to clean.")
        return

    logger.info("Found %d disowned copy/copies to delete.", len(items))

    # ── Delete from S3 in batches of 1000 (S3 delete_objects limit) ──────
    copy_names = [item["copyName"] for item in items]
    for i in range(0, len(copy_names), 1000):
        batch = copy_names[i : i + 1000]
        s3.delete_objects(
            Bucket=BUCKET_DST,
            Delete={"Objects": [{"Key": k} for k in batch]},
        )
        logger.info("Deleted S3 objects: %s", batch)

    # ── Remove records from Table T ───────────────────────────────────────
    # batch_writer de-duplicates and retries unprocessed items automatically.
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={
                "srcKey":   item["srcKey"],
                "copyName": item["copyName"],
            })

    logger.info("Removed %d record(s) from Table T.", len(items))