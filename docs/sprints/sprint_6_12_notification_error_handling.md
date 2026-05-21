# Sprint 6.12 — Notification Error Handling & Diagnostics

## Context

The notification pipeline has two bugs that together cause silent notification loss and permanently stuck rows in `notification_queue`:

**Bug 1 — Queue rows orphaned in `pending` on SMTP failure**

In `scripts/notify_new_offers.py`, the flow inserts a `notification_queue` row with `status = 'pending'` **before** attempting the SMTP send. If the send fails, the row is left as `pending` forever — there is no retry logic and no mechanism to mark it as `failed`. The `cleanup_notification_queue.py` script (Sprint 6.9) eventually deletes `pending` rows older than 7 days, but a recent failure leaves a row that sits for up to 7 days with no indication of what went wrong.

**Bug 2 — `notified_at` stamped regardless of send success**

After processing all subscriptions, the script stamps `notified_at = NOW()` on **all** offers from the current batch, including those whose notification email failed for every matched subscriber. On the next run those offers are skipped (`notified_at IS NOT NULL`), so the affected subscribers **never** receive the notification for those offers — the failure is permanent.

### Observed symptoms

- `notification_queue` contains rows with `status = 'pending'` that never transition.
- No SMTP error is surfaced to the operator beyond an INFO-level log line.
- Offers are stamped as notified even when delivery failed for all subscribers.

### Diagnostic gap

There is currently **no way to test SMTP connectivity** without triggering a real ingestion+notification run. The operator cannot distinguish between SMTP misconfiguration, network-level issues, or a genuine lack of keyword matches.

## Design

### Fix A — Error-robust notification flow

**1. Mark failed sends as `failed`, not `pending`**

When `send_notification_email()` raises `NotificationError`, the corresponding queue row should be updated to `status = 'failed'` and `attempts = attempts + 1`. This makes failures visible via a simple DB query and distinguishes them from genuinely pending work.

**2. Only stamp `notified_at` on successfully notified offers**

Track which offer IDs were sent to at least one subscriber with a successful SMTP send. Only those offers receive `notified_at`. Offers whose notification failed for **all** matched subscribers retain `notified_at IS NULL` and are picked up by the next run.

This means an offer may be processed multiple times if it keeps failing for some subscribers. That is acceptable because:
- The matcher is idempotent (same subscription × same offer → same match).
- The `uq_notification_queue_dedup` constraint prevents duplicate queue rows.
- The next run will see the existing `failed` row and attempt to send again.
- Failed sends are expected to be rare (misconfiguration should be fixed, not worked around).

**Retry limit:** To prevent infinite retries on permanently failing subscribers, use the existing `attempts` column (default 0). After 3 failed attempts for the same subscription+offer pair, the row stays `failed` permanently and a `WARNING` is logged for manual inspection.

**3. `_MARK_SENT_SQL` and `_MARK_FAILED_SQL` must also match `failed` status**

Both UPDATE statements originally filtered on `status = 'pending'`. When retrying a previously failed notification, the `INSERT ... ON CONFLICT DO NOTHING` leaves the existing `failed` row unchanged, so neither `_MARK_SENT_SQL` nor `_MARK_FAILED_SQL` could act on it. Changed to `status IN ('pending', 'failed')` so on retry:
- Success transitions the row from `failed` → `sent`
- Failure increments `attempts` on the existing `failed` row

### Fix C — Recover stuck notifications from before the fix

The `_UNNOTIFIED_SQL` query originally filtered solely on `notified_at IS NULL`. Offers that were stamped by the old buggy code (notified_at set despite failed sends) were permanently excluded from future runs, even though they had non-sent `notification_queue` rows.

**Fix:** Extended `_UNNOTIFIED_SQL` to also include offers that have at least one `notification_queue` row with `status IN ('pending', 'failed')` and `attempts < 3`, even if `notified_at` is already set. Uses an `EXISTS` subquery so existing unmatched offers (notified_at IS NULL) are still picked up normally.

This is a permanent change: if any future notification fails and `notified_at` gets set (e.g. partial success for some subscribers), the offer will be re-processed on the next run as long as there is at least one recoverable failed queue row.

### Fix B — SMTP diagnostic script

A standalone script `scripts/test_email.py` that:
1. Validates all `SMTP_*` env vars are set.
2. Attempts to connect to the SMTP server with the configured credentials.
3. Sends a test email to a given address (CLI argument).
4. Reports success or a detailed error message.

This decouples "is SMTP working?" from "are there matching offers?".

## Files changed

| File | Change |
|---|---|---|
| `scripts/notify_new_offers.py` | Fix error handling: mark fails as `failed`, only stamp `notified_at` on offers sent successfully; `_MARK_SENT_SQL` and `_MARK_FAILED_SQL` match both `pending` and `failed` statuses for retry support; `_UNNOTIFIED_SQL` includes offers with recoverable queue rows via `EXISTS` subquery |
| `scripts/test_email.py` | New file: SMTP diagnostic script |
| `src/notifications/email.py` | Expose a public `check_smtp_config()` wrapper for use by the diagnostic script |

## Acceptance criteria

### Fix A — Error handling

- [ ] SMTP failure for a subscriber sets `notification_queue.status = 'failed'` and increments `attempts`.
- [ ] SMTP failure does **not** prevent other subscribers from receiving notifications for the same offer.
- [ ] If at least one subscriber received the offer email, `notified_at` is stamped on that offer.
- [ ] If **no** subscriber received the offer email (all failed), `notified_at` is **not** stamped.
- [ ] After 3 failed attempts for the same subscription+offer pair, the row stays `failed` permanently and a `WARNING` is logged.
- [ ] Offers with `failed` queue rows and `notified_at IS NULL` are retried on the next ingestion run.
- [ ] Offers with `failed` queue rows and `notified_at IS NOT NULL` (pre-existing stuck data) are also retried on the next ingestion run.
- [ ] `_MARK_SENT_SQL` transitions a `failed` row to `sent` on successful retry.
- [ ] `_MARK_FAILED_SQL` increments `attempts` on a `failed` row on failed retry.
- [ ] `--dry-run` still skips all sends and stamps.

### Fix B — Diagnostic script

- [ ] `python scripts/test_email.py` without `--to` prints usage and exits 1.
- [ ] `python scripts/test_email.py --to me@example.com` with missing SMTP env vars logs an error and exits 1.
- [ ] `python scripts/test_email.py --to me@example.com` with valid SMTP config sends the email and exits 0.
- [ ] `python scripts/test_email.py --to me@example.com --dry-run` checks config and logs intent without sending.
- [ ] `--subject` and `--message` override default values.
