# Sprint 6.7 — Weekly Digest Script

## Context

`notify_new_offers.py` (Sprint 6.6) sends immediate per-offer notifications
each time the ingestion pipeline runs. However, subscribers who receive many
individual emails may prefer a single weekly summary.

This sprint adds `scripts/weekly_digest.py`, a standalone cron script that
sends one grouped `digest` email per subscriber listing all matching offers
published in the past 7 days.

## Design

### Offer window

The digest covers offers created in the last 7 days, regardless of
`notified_at`. This is intentional: the immediate notifier and the weekly
digest are independent channels. A subscriber may receive both; the digest
acts as a recap.

```sql
WHERE  is_active = TRUE
  AND  created_at >= NOW() - INTERVAL '7 days'
```

`close_date`-based filtering is not applied here — the digest is a summary
of what was published recently, not necessarily still open.

### `notification_queue` usage

Same idempotency pattern as Sprint 6.6, using `notification_type = 'digest'`.
The unique constraint `uq_notification_queue_dedup` on
`(subscription_id, job_offer_id, notification_type)` prevents duplicate rows
if the script is run more than once in a week.

A re-run within the same 7-day window will insert queue rows with
`ON CONFLICT DO NOTHING` for already-queued pairs, and will not re-send
emails for subscriptions that already have `status = 'sent'` queue rows from
this digest type.

### De-duplication guard

Before sending, the script checks whether the subscription already has a
`sent` digest entry for the given offer set. Specifically: if **all** matched
offers already appear in `notification_queue` with
`notification_type = 'digest'` AND `status = 'sent'`, the subscriber is
skipped (already received this week's digest).

This avoids re-sending if the cron fires twice accidentally.

### Email template

Uses `notification_type = "digest"` → `send_notification_email` selects
`notification_digest.html` / `.txt` and the subject:
`"Resumen semanal — N ofertas nuevas"`.

### `--since` flag (optional override)

For operational flexibility (e.g. re-sending a missed digest), the script
accepts an optional `--since DAYS` argument (default `7`) to override the
lookback window.

## Implementation

### `scripts/weekly_digest.py`

**CLI interface:**

```
PYTHONPATH=. python scripts/weekly_digest.py [--dry-run] [--since DAYS]
```

- `--dry-run`: executes all DB reads and inserts but skips actual SMTP sends
  and does not update queue rows to `sent`.
- `--since DAYS`: override the lookback window (default 7).

**Flow:**

1. Query `job_offers` for recent active offers within the window:
   ```sql
   SELECT id, title, institution, region, close_date, url
   FROM   job_offers
   WHERE  is_active = TRUE
     AND  created_at >= NOW() - INTERVAL ':days days'
   ```
   Returns early (exit 0) if no rows found.

2. Call `find_matches(session, offer_ids)` from `src/notifications/matcher.py`.
   Returns early if no subscriptions matched.

3. For each matched subscription:
   a. Insert `notification_queue` rows for each offer pair
      (`notification_type = 'digest'`, `status = 'pending'`), using
      `ON CONFLICT DO NOTHING`.
   b. Check if this subscription already has `status = 'sent'` digest rows
      covering **all** matched offers — if so, skip (already sent this cycle).
   c. Load `email` and `unsubscribe_token` from `subscriptions`.
   d. Build `list[OfferRow]` from matched offer IDs.
   e. Call `send_notification_email(email, offers, unsubscribe_token, "digest")`.
   f. On success: update queue rows to `status = 'sent'`, `sent_at = NOW()`.
   g. On `NotificationError`: log warning, leave queue rows as `pending`.

4. Log summary: N offers in window, M subscribers notified, K errors.

**Exit codes:** `0` always (SMTP failures are non-fatal).

### DB queries (inline in the script)

```python
# Step 1 — recent active offers
_RECENT_OFFERS_SQL = text("""
    SELECT id, title, institution, region, close_date, url
    FROM   job_offers
    WHERE  is_active = TRUE
      AND  created_at >= NOW() - CAST(:days || ' days' AS INTERVAL)
""")

# Step 3a — queue insert (idempotent)
_QUEUE_INSERT_SQL = text("""
    INSERT INTO notification_queue
        (id, subscription_id, job_offer_id, notification_type, status)
    VALUES
        (:id, :subscription_id, :job_offer_id, 'digest', 'pending')
    ON CONFLICT ON CONSTRAINT uq_notification_queue_dedup DO NOTHING
""")

# Step 3b — check already sent
_ALREADY_SENT_SQL = text("""
    SELECT COUNT(*) AS cnt
    FROM   notification_queue
    WHERE  subscription_id = :subscription_id
      AND  job_offer_id = ANY(:offer_ids)
      AND  notification_type = 'digest'
      AND  status = 'sent'
""")

# Step 3c — load subscription
_SUBSCRIPTION_SQL = text("""
    SELECT email, unsubscribe_token
    FROM   subscriptions
    WHERE  id = :subscription_id
""")

# Step 3f — mark sent
_MARK_SENT_SQL = text("""
    UPDATE notification_queue
    SET    status = 'sent', sent_at = NOW()
    WHERE  subscription_id = :subscription_id
      AND  job_offer_id = ANY(:offer_ids)
      AND  notification_type = 'digest'
      AND  status = 'pending'
""")
```

### Imports and structure

Mirrors `notify_new_offers.py`:

```python
import argparse
import asyncio
import logging
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_engine
from src.notifications.email import NotificationError, OfferRow, send_notification_email
from src.notifications.matcher import find_matches
```

## Files changed

| File | Change |
|---|---|
| `scripts/weekly_digest.py` | New script |

No other files are modified in this sprint.

## Acceptance criteria

- [ ] Running with no offers in the 7-day window exits 0 and logs "No recent offers found".
- [ ] Running with offers but no confirmed subscription matches exits 0 without sending emails.
- [ ] For a confirmed subscriber whose keyword matches offers in the window, one digest email is sent with all matching offers grouped.
- [ ] Re-running immediately after a successful run skips subscribers that already received the digest (`status = 'sent'` guard).
- [ ] `--dry-run` logs intended actions, skips SMTP, and does not update queue rows to `sent`.
- [ ] `--since 14` sends a digest covering the past 14 days instead of 7.
- [ ] An SMTP failure for one subscriber does not prevent processing of other subscribers.
