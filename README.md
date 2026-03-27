# Cloud_Midterm — Object Backup System

## Overview

This system maintains backup copies in **Bucket Dst** for every object uploaded to **Bucket Src**. All source-to-copy mappings are tracked in **Table T**. Two Lambda functions handle replication and garbage collection.

---

## Architecture

```
Bucket Src  ──(EventBridge)──►  Replicator Lambda  ──►  Bucket Dst
                                        │                    ▲
                                        ▼                    │
                                     Table T  ◄──  Cleaner Lambda
                                                  (every 1 min)
```

### Stacks

| Stack | Resources |
|---|---|
| `StorageStack` | Bucket Src, Bucket Dst, Table T (with DisownedIndex GSI) |
| `ReplicatorStack` | Replicator Lambda, EventBridge rule for S3 events |
| `CleanerStack` | Cleaner Lambda, EventBridge scheduled rule (1 min) |

### Configuration

All tunable parameters are defined at the top of `cdk/app.py` — no hardcoded values anywhere else:

| Parameter | Default | Description |
|---|---|---|
| `MAX_COPIES` | `3` | Maximum active copies per source object |
| `DISOWNED_TTL_SEC` | `10` | Seconds after disowning before deletion |
| `REPLICATOR_TIMEOUT_SEC` | `60` | Replicator Lambda timeout (seconds) |
| `CLEANER_TIMEOUT_SEC` | `55` | Cleaner Lambda timeout (seconds) |

---

## Table T Design

| Attribute | Role | Type |
|---|---|---|
| `srcKey` | Partition Key | String |
| `copyName` | Sort Key | String (`<srcKey>/<createdAt_ms>_<uuid>`) |
| `status` | `"active"` or `"disowned"` | String |
| `createdAt` | Creation timestamp (Unix ms) | Number |
| `disownedAt` | Disowned timestamp (Unix ms); absent if active | Number |

### GSI — `DisownedIndex`

| Attribute | Role |
|---|---|
| `status` | GSI Partition Key |
| `disownedAt` | GSI Sort Key |

### Why no scan is needed

| Operation | Index used | Query type |
|---|---|---|
| PUT — list existing copies | Main table PK `srcKey` | Query |
| DELETE — find all copies to disown | Main table PK `srcKey` | Query |
| Cleaner — find expired disowned copies | GSI `DisownedIndex` | Query |

All three operations are targeted Queries. The `DisownedIndex` GSI allows the Cleaner to query `status = "disowned" AND disownedAt < threshold` directly without a full table scan.

---

## Lambda Behavior

### Replicator

**PUT event:**
1. Copy object from Bucket Src → Bucket Dst with key `<srcKey>/<ts>_<uuid>`.
2. Write a new `"active"` item to Table T.
3. Query Table T for all active copies of `srcKey`. If count > `MAX_COPIES`, delete the oldest copy from Bucket Dst and remove its Table T record.

**DELETE event:**
1. Query Table T for all items with `srcKey = <deleted key>`.
2. Re-put each item with `status = "disowned"` and `disownedAt = now_ms()`.
3. Does **not** delete any S3 objects — that is the Cleaner's job.

### Cleaner (runs every 1 minute)

1. Query `DisownedIndex` for all items where `status = "disowned"` AND `disownedAt < (now - DISOWNED_TTL_SEC)`.
2. Batch-delete matching objects from Bucket Dst.
3. Batch-delete matching records from Table T.

---

## Deployment

### Prerequisites

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r cdk/requirements.txt
npm install -g aws-cdk
cdk bootstrap   # once per account/region
```

### Deploy all stacks

```bash
cd cdk
cdk deploy --all
```

Or deploy individually (StorageStack must come first):

```bash
cdk deploy StorageStack
cdk deploy ReplicatorStack
cdk deploy CleanerStack
```

### Destroy

```bash
cdk destroy --all
```

---

## Manually Created Resources

**None.** All AWS resources are created via CDK. No manual steps in the AWS Console are required.


