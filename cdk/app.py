#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.storage_stack import StorageStack
from stacks.replicator_stack import ReplicatorStack
from stacks.cleaner_stack import CleanerStack

# ── All Settings ─────────────────────────────────────────
MAX_COPIES        = 3    
DISOWNED_TTL_SEC  = 10   
REPLICATOR_TIMEOUT_SEC = 60   
CLEANER_TIMEOUT_SEC    = 55 
# ──────────────────────────────────────────────────────────────────────

app = cdk.App()

storage = StorageStack(app, "StorageStack")

ReplicatorStack(
    app, "ReplicatorStack",
    bucket_src=storage.bucket_src,
    bucket_dst=storage.bucket_dst,
    table=storage.table,
    max_copies=MAX_COPIES,
    timeout_sec=REPLICATOR_TIMEOUT_SEC,
)

CleanerStack(
    app, "CleanerStack",
    bucket_dst=storage.bucket_dst,
    table=storage.table,
    disowned_ttl_sec=DISOWNED_TTL_SEC,
    timeout_sec=CLEANER_TIMEOUT_SEC,
)

app.synth()