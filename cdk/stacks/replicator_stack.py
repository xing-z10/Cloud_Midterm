import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct


class ReplicatorStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        bucket_src: s3.Bucket,
        bucket_dst: s3.Bucket,
        table: dynamodb.Table,
        max_copies: int,
        timeout_sec: int,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        replicator_fn = _lambda.Function(
            self, "ReplicatorFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("../lambdas/replicator"),
            timeout=Duration.seconds(timeout_sec),
            environment={
                "BUCKET_SRC": bucket_src.bucket_name,
                "BUCKET_DST": bucket_dst.bucket_name,
                "TABLE_NAME": table.table_name,
                "MAX_COPIES": str(max_copies),
            },
        )

        bucket_src.grant_read(replicator_fn)
        bucket_dst.grant_read_write(replicator_fn)
        table.grant_read_write_data(replicator_fn)

        rule = events.Rule(
            self, "SrcBucketRule",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=[
                    "Object Created",
                    "Object Deleted",
                ],
                detail={
                    "bucket": {"name": [bucket_src.bucket_name]},
                },
            ),
        )
        rule.add_target(targets.LambdaFunction(replicator_fn))

        cdk.CfnOutput(self, "ReplicatorFnArn", value=replicator_fn.function_arn)