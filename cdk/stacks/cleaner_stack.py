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


class CleanerStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        bucket_dst: s3.Bucket,
        table: dynamodb.Table,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ── Lambda ───────────────────────────────────────────────────────────
        cleaner_fn = _lambda.Function(
            self, "CleanerFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("../lambdas/cleaner"),
            timeout=Duration.seconds(55),   # stay safely under 1-min schedule
            environment={
                "BUCKET_DST":         bucket_dst.bucket_name,
                "TABLE_NAME":         table.table_name,
                "DISOWNED_TTL_SEC":   "10",
            },
        )

        # ── IAM permissions ──────────────────────────────────────────────────
        bucket_dst.grant_read_write(cleaner_fn)
        table.grant_read_write_data(cleaner_fn)

        # ── EventBridge scheduled rule (every 1 minute) ──────────────────────
        schedule_rule = events.Rule(
            self, "CleanerSchedule",
            schedule=events.Schedule.rate(Duration.minutes(1)),
        )
        schedule_rule.add_target(targets.LambdaFunction(cleaner_fn))

        # ── Outputs ──────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "CleanerFnArn", value=cleaner_fn.function_arn)