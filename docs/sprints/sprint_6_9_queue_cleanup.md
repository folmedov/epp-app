# Sprint 6.9 — Queue Cleanup Script

## Context

The `notification_queue` table accumulates rows over time as the notification
pipeline runs. Rows with `status = 'sent'` are no longer operationally needed
after a reasonable retention period, and `pending` rows that are very old
indicate orphaned work from script crashes or configuration errors.

Without periodic cleanup, the table grows unboundedly and the idempotency
queries in `notify_new_offers.py` and `weekly_digest.py` get slower.

## Design

### Cleanup policy

| Condition | Action | Rationale |
|---|---|---|
| `status = 'sent'` AND `sent_at < NOW() - 30 days` | DELETE | Audit window expired; no longer needed |
| `status = 'pending'` AND `created_at < NOW() - 7 days` | DELETE | Orphaned by crash; will never be sent |

`sent` rows are retained for 30 days to allow short-term troubleshooting
(e.g. "did this subscriber receive a notification last week?"). `pending` rows
older than 7 days are safe to remove: the next run of `notify_new_offers.py`
or `weekly_digest.py` will re-queue them if still relevant.

### Standalone script

`scripts/cleanup_notification_queue.py` is a standalone script called by the
`eepp-worker-queue-cleanup` cron (daily 02:00). It does not hook into
`ingest_all.py` — cleanup is an independent maintenance operation.

### Non-fatal in production

The script always exits 0. DB errors propagate naturally as unhandled
exceptions and exit non-zero.

## Implementation

### `scripts/cleanup_notification_queue.py`

**CLI interface:**

```
PYTHONPATH=. python scripts/cleanup_notification_queue.py [--dry-run]
          [--sent-days DAYS] [--pending-days DAYS]
```

- `--dry-run`: counts rows that would be deleted but does not delete them.
- `--sent-days DAYS`: override retention window for `sent` rows (default 30).
- `--pending-days DAYS`: override retention window for `pending` rows (default 7).

**Flow:**

1. Delete `sent` rows outside the retention window; capture row count.
2. Delete old `pending` rows; capture row count.
3. Commit and log summary.

### DB queries

```python
_DELETE_SENT_SQL = text("""
    DELETE FROM notification_queue
    WHERE  status = 'sent'
      AND  sent_at < NOW() - CAST(:days || ' days' AS INTERVAL)
""")

_DELETE_PENDING_SQL = text("""
    DELETE FROM notification_queue
    WHERE  status = 'pending'
      AND  created_at < NOW() - CAST(:days || ' days' AS INTERVAL)
""")

# dry-run variants (COUNT only)
_COUNT_SENT_SQL = text("""
    SELECT COUNT(*) AS cnt
    FROM   notification_queue
    WHERE  status = 'sent'
      AND  sent_at < NOW() - CAST(:days || ' days' AS INTERVAL)
""")

_COUNT_PENDING_SQL = text("""
    SELECT COUNT(*) AS cnt
    FROM   notification_queue
    WHERE  status = 'pending'
      AND  created_at < NOW() - CAST(:days || ' days' AS INTERVAL)
""")
```

### Imports and structure

```python
import argparse
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_engine
```

Session pattern mirrors `notify_new_offers.py`:

```python
engine = get_engine()
async with AsyncSession(engine) as session:
    async with session.begin():
        ...
await engine.dispose()
```

## Files changed

| File | Change |
|---|---|
| `scripts/cleanup_notification_queue.py` | New script |

No other files are modified in this sprint. The Dokploy cron configuration
is handled in Sprint 6.10.

## Acceptance criteria

- [ ] Running with no rows to clean exits 0 and logs "Nothing to clean up".
- [ ] `sent` rows older than 30 days are deleted; newer rows are kept.
- [ ] `pending` rows older than 7 days are deleted; newer rows are kept.
- [ ] `--dry-run` logs the count of rows that would be deleted without deleting them.
- [ ] `--sent-days 60` overrides the `sent` retention window to 60 days.
- [ ] `--pending-days 14` overrides the `pending` retention window to 14 days.
- [ ] Script exits 0 always (DB errors exit non-zero naturally).
