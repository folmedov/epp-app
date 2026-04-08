# Sprint 6.6 — Immediate Notification Script

## Context

With the keyword matcher ready (Sprint 6.5) and the email sender in place
(Sprint 6.2), this sprint wires them together into a runnable script that
is called by `ingest_all.py` after each ingestion run.

The script answers the question: *"which confirmed subscribers should receive
an email right now, about which new offers?"*

## Design

### New-offer marker

`job_offers.notified_at IS NULL` is the sole marker for "not yet notified".
The script queries all active offers where `notified_at IS NULL`, runs them
through the matcher, sends one email per matched subscriber, and then stamps
`notified_at = NOW()` on every processed offer — regardless of whether any
subscriber matched.

This ensures offers are never processed twice even if the script is re-run.

### Notification type

All emails sent by this script use `notification_type = "immediate"` (one
email per subscriber per run, listing all matching new offers). The subject
line uses the `send_notification_email` logic from Sprint 6.2 which already
handles the immediate template.

### `notification_queue` usage

Before sending, one row per `(subscription_id, job_offer_id)` pair is
inserted into `notification_queue` with `status = 'pending'`. The
`uq_notification_queue_dedup` unique constraint (`subscription_id`,
`job_offer_id`, `notification_type`) acts as an idempotency guard — if the
script crashes after some inserts, a re-run will skip already-queued pairs
via `INSERT … ON CONFLICT DO NOTHING`.

After a successful send the row is updated to `status = 'sent'` and
`sent_at = NOW()`. On SMTP failure the row is left as `pending` and the
error is logged (non-fatal for the run as a whole).

### `ingest_all.py` hook (Sprint 6.8)

The hook is documented here for completeness but is **not implemented in
this sprint** — it is the scope of Sprint 6.8. After `close_stale_offers.py`:

```python
rc_notify = _run_loader("notify", _SCRIPTS_DIR / "notify_new_offers.py", common)
if rc_notify != 0:
    LOGGER.warning("notify_new_offers completed with errors (non-fatal)")
```

## Implementation

### `scripts/notify_new_offers.py`

**CLI interface:**

```
PYTHONPATH=. python scripts/notify_new_offers.py [--dry-run]
```

- `--dry-run`: executes all DB reads, matcher, and queue inserts, but skips
  actual SMTP sends and rolls back `notified_at` stamps. Useful for testing
  the pipeline end-to-end without sending real emails.

**Flow:**

1. Query `job_offers` for active, unnotified rows:
   ```sql
   SELECT id, title, institution, region, close_date, url
   FROM job_offers
   WHERE notified_at IS NULL
     AND is_active = TRUE
   ```
   Returns early (exit 0) if no rows found.

2. Call `find_matches(session, offer_ids)` from `src/notifications/matcher.py`.
   Returns early if no subscriptions matched.

3. For each matched subscription:
   a. Insert `notification_queue` rows for each offer (one per pair), using
      `ON CONFLICT DO NOTHING` to skip already-queued pairs.
   b. Load the `Subscription` row to get `email` and `unsubscribe_token`.
   c. Build `list[OfferRow]` from the matched offer IDs.
   d. Call `send_notification_email(email, offers, unsubscribe_token, "immediate")`.
   e. On success: update queue rows to `status='sent'`, `sent_at=NOW()`.
   f. On `NotificationError`: log warning, leave queue rows as `pending`.

4. Stamp `notified_at = NOW()` on **all** offers from step 1 (not just those
   with matches), so they are never re-processed.

5. Commit. Log summary: N offers processed, M subscribers notified, K errors.

**Exit codes:** `0` always (SMTP failures are non-fatal; DB errors propagate
as unhandled exceptions and exit non-zero naturally).

### DB queries (inline in the script)

```python
# Step 1 — fetch unnotified offers
_UNNOTIFIED_SQL = text("""
    SELECT id, title, institution, region, close_date, url
    FROM   job_offers
    WHERE  notified_at IS NULL
      AND  is_active = TRUE
""")

# Step 3a — queue insert (idempotent)
_QUEUE_INSERT_SQL = text("""
    INSERT INTO notification_queue
        (id, subscription_id, job_offer_id, notification_type, status)
    VALUES
        (:id, :subscription_id, :job_offer_id, 'immediate', 'pending')
    ON CONFLICT ON CONSTRAINT uq_notification_queue_dedup DO NOTHING
""")

# Step 3b — load subscription
_SUBSCRIPTION_SQL = text("""
    SELECT email, unsubscribe_token
    FROM   subscriptions
    WHERE  id = :subscription_id
""")

# Step 3e — mark sent
_MARK_SENT_SQL = text("""
    UPDATE notification_queue
    SET    status = 'sent', sent_at = NOW()
    WHERE  subscription_id = :subscription_id
      AND  job_offer_id = ANY(:offer_ids)
      AND  notification_type = 'immediate'
      AND  status = 'pending'
""")

# Step 4 — stamp notified_at
_STAMP_NOTIFIED_SQL = text("""
    UPDATE job_offers
    SET    notified_at = NOW()
    WHERE  id = ANY(:offer_ids)
""")
```

### Imports and structure

```python
import argparse
import asyncio
import logging
import sys
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings          # noqa: F401 — triggers DB URL validation
from src.database.connection import get_engine
from src.notifications.email import NotificationError, OfferRow, send_notification_email
from src.notifications.matcher import find_matches
```

Session is managed manually (not via FastAPI `Depends`):
```python
engine = get_engine()
async with AsyncSession(engine) as session:
    async with session.begin():
        ...
```

## Files changed

| File | Change |
|---|---|
| `scripts/notify_new_offers.py` | New script |

`ingest_all.py` is **not modified** in this sprint (that is Sprint 6.8).

## Acceptance criteria

- [ ] Running the script with no unnotified offers exits 0 and logs "No new offers to notify".
- [ ] Running with offers but no confirmed subscriptions exits 0 without sending emails.
- [ ] For a confirmed subscriber whose keyword matches a new offer, one email is sent and `notification_queue` row transitions to `sent`.
- [ ] `notified_at` is stamped on all processed offers, including those with no subscriber matches.
- [ ] Re-running the script immediately after a successful run processes 0 offers (all already stamped).
- [ ] `--dry-run` logs intended actions, skips SMTP, and does not stamp `notified_at`.
- [ ] An SMTP failure for one subscriber does not prevent processing of other subscribers or stamping `notified_at`.
