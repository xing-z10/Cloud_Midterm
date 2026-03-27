import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    RemovalPolicy,
)
from constructs import Construct


class StorageStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── Bucket Src ──────────────────────────────────────────────────────
        # EventBridge notifications are enabled so the Replicator lambda
        # can be triggered by S3 event rules (supports both PUT and DELETE).
        self.bucket_src = s3.Bucket(
            self, "BucketSrc",
            bucket_name=None,               # let CDK generate a unique name
            versioned=False,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            event_bridge_enabled=True,      # required for EventBridge-based triggers
        )

        # ── Bucket Dst ──────────────────────────────────────────────────────
        self.bucket_dst = s3.Bucket(
            self, "BucketDst",
            bucket_name=None,
            versioned=False,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── Table T ─────────────────────────────────────────────────────────
        #
        # Schema
        # ──────
        # PK  srcKey    (String)  – original object key in Bucket Src
        # SK  copyName  (String)  – copy object key in Bucket Dst
        #                           format: "<srcKey>/<createdAt_ms>_<uuid4>"
        #
        # Additional attributes (not declared in key schema but used by code)
        #   status      (String)  – "active" | "disowned"
        #   createdAt   (Number)  – Unix ms when the copy was created
        #   disownedAt  (Number)  – Unix ms when marked disowned (absent if active)
        #
        # Access patterns
        # ───────────────
        # 1. Replicator – PUT: list all copies for srcKey
        #      → Query on PK=srcKey  (main table)
        #
        # 2. Replicator – DELETE: mark all copies for srcKey as disowned
        #      → Query on PK=srcKey, then batch-write updates  (main table)
        #
        # 3. Cleaner: find all disowned copies older than 10 s
        #      → Query on GSI: status="disowned" AND disownedAt < threshold
        #
        # GSI – DisownedIndex
        # ───────────────────
        # PK  status      (String)
        # SK  disownedAt  (Number)
        # Projects all attributes (COPY_ALL) so the Cleaner has copyName and
        # srcKey available without a second lookup.

        self.table = dynamodb.Table(
            self, "TableT",
            partition_key=dynamodb.Attribute(
                name="srcKey", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="copyName", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.table.add_global_secondary_index(
            index_name="DisownedIndex",
            partition_key=dynamodb.Attribute(
                name="status", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="disownedAt", type=dynamodb.AttributeType.NUMBER
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ── Outputs ─────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "BucketSrcName", value=self.bucket_src.bucket_name)
        cdk.CfnOutput(self, "BucketDstName", value=self.bucket_dst.bucket_name)
        cdk.CfnOutput(self, "TableName",     value=self.table.table_name)