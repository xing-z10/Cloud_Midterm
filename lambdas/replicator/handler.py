"""
Replicator Lambda
─────────────────
Triggered by EventBridge events from Bucket Src.

PUT  → copy object to Bucket Dst, enforce ≤ MAX_COPIES, update Table T
DELETE → mark all copies of the deleted object as "disowned" in Table T
"""

import os
import uuid
import time
import logging
import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3  = boto3.client("s3")
ddb = boto3.resource("dynamodb")

BUCKET_SRC  = os.environ["BUCKET_SRC"]
BUCKET_DST  = os.environ["BUCKET_DST"]
TABLE_NAME  = os.environ["TABLE_NAME"]
MAX_COPIES  = int(os.environ.get("MAX_COPIES", "3"))

table = ddb.Table(TABLE_NAME)


# ── helpers ──────────────────────────────────────────────────────────────────

def now_ms() -> int:
    return int(time.time() * 1000)


def query_copies(src_key: str) -> list[dict]:
    """Return all Table T items for src_key, sorted by createdAt ascending."""
    resp = table.query(
        KeyConditionExpression=Key("srcKey").eq(src_key)
    )
    items = resp.get("Items", [])
    # Handle DynamoDB pagination (unlikely for ≤3 copies but correct practice)
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression=Key("srcKey").eq(src_key),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return sorted(items, key=lambda x: int(x["createdAt"]))


# ── event handlers ────────────────────────────────────────────────────────────

def handle_put(src_key: str) -> None:
    """Copy object, enforce copy cap, record in Table T."""
    ts = now_ms()
    copy_name = f"{src_key}/{ts}_{uuid.uuid4().hex}"

    # 1. Copy object to Bucket Dst
    s3.copy_object(
        CopySource={"Bucket": BUCKET_SRC, "Key": src_key},
        Bucket=BUCKET_DST,
        Key=copy_name,
    )
    logger.info("Copied %s → %s", src_key, copy_name)

    # 2. Record the new copy in Table T
    table.put_item(Item={
        "srcKey":    src_key,
        "copyName":  copy_name,
        "status":    "active",
        "createdAt": ts,
    })

    # 3. Enforce MAX_COPIES: delete the oldest copy if we now exceed the limit
    #    (query before the write above so the new copy is already counted)
    copies = query_copies(src_key)
    # Filter to only active copies (disowned ones will be cleaned by Cleaner)
    active_copies = [c for c in copies if c.get("status") == "active"]

    if len(active_copies) > MAX_COPIES:
        oldest = active_copies[0]   # sorted ascending by createdAt
        oldest_copy_name = oldest["copyName"]

        # Delete from Bucket Dst
        s3.delete_object(Bucket=BUCKET_DST, Key=oldest_copy_name)
        logger.info("Evicted oldest copy %s", oldest_copy_name)

        # Remove from Table T
        table.delete_item(Key={
            "srcKey":   src_key,
            "copyName": oldest_copy_name,
        })


def handle_delete(src_key: str) -> None:
    """Mark all copies of src_key as disowned."""
    copies = query_copies(src_key)
    if not copies:
        logger.info("No copies found for deleted object %s", src_key)
        return

    ts = now_ms()
    with table.batch_writer() as batch:
        for item in copies:
            # batch_writer only supports put_item / delete_item.
            # We re-put the full item with updated fields.
            batch.put_item(Item={
                **item,
                "status":     "disowned",
                "disownedAt": ts,
            })

    logger.info("Marked %d copy/copies as disowned for %s", len(copies), src_key)


# ── main handler ──────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    EventBridge event shape (S3 notification):
    {
      "detail-type": "Object Created" | "Object Deleted",
      "detail": {
        "bucket": {"name": "..."},
        "object": {"key": "..."}
      }
    }
    """
    detail_type = event.get("detail-type", "")
    detail      = event.get("detail", {})
    bucket_name = detail.get("bucket", {}).get("name", "")
    src_key     = detail.get("object", {}).get("key", "")

    if bucket_name != BUCKET_SRC:
        logger.warning("Unexpected bucket %s – ignoring", bucket_name)
        return

    if not src_key:
        logger.error("Missing object key in event: %s", event)
        return

    if detail_type == "Object Created":
        handle_put(src_key)
    elif detail_type == "Object Deleted":
        handle_delete(src_key)
    else:
        logger.warning("Unhandled event type: %s", detail_type)