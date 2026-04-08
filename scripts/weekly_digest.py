"""Send weekly digest email notifications for recent job offers.

Queries all active offers published in the last N days, matches them against
confirmed subscriptions using the keyword matcher, and sends one grouped
digest email per subscriber with all matching offers.

Unlike notify_new_offers.py, this script is independent of notified_at —
the digest is a weekly recap and can overlap with immediate notifications.

Usage:
    PYTHONPATH=. python scripts/weekly_digest.py [--dry-run] [--since DAYS]

Exit codes:
    0   Always (SMTP failures are non-fatal; DB errors exit non-zero naturally).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_engine
from src.notifications.email import NotificationError, OfferRow, send_notification_email
from src.notifications.matcher import find_matches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

# ── SQL statements ────────────────────────────────────────────────────────────

_RECENT_OFFERS_SQL = text("""
    SELECT id, title, institution, region, close_date, url
    FROM   job_offers
    WHERE  is_active = TRUE
      AND  created_at >= NOW() - CAST(:days || ' days' AS INTERVAL)
""")

_QUEUE_INSERT_SQL = text("""
    INSERT INTO notification_queue
        (id, subscription_id, job_offer_id, notification_type, status)
    VALUES
        (:id, :subscription_id, :job_offer_id, 'digest', 'pending')
    ON CONFLICT ON CONSTRAINT uq_notification_queue_dedup DO NOTHING
""")

_ALREADY_SENT_SQL = text("""
    SELECT COUNT(*) AS cnt
    FROM   notification_queue
    WHERE  subscription_id = :subscription_id
      AND  job_offer_id = ANY(:offer_ids)
      AND  notification_type = 'digest'
      AND  status = 'sent'
""")

_SUBSCRIPTION_SQL = text("""
    SELECT email, unsubscribe_token
    FROM   subscriptions
    WHERE  id = :subscription_id
""")

_MARK_SENT_SQL = text("""
    UPDATE notification_queue
    SET    status = 'sent', sent_at = NOW()
    WHERE  subscription_id = :subscription_id
      AND  job_offer_id = ANY(:offer_ids)
      AND  notification_type = 'digest'
      AND  status = 'pending'
""")


# ── Main logic ────────────────────────────────────────────────────────────────

async def run(dry_run: bool, since_days: int) -> None:
    engine = get_engine()
    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                await _process(session, dry_run, since_days)
    finally:
        await engine.dispose()


async def _process(session: AsyncSession, dry_run: bool, since_days: int) -> None:
    # Step 1: fetch recent active offers within the lookback window
    result = await session.execute(_RECENT_OFFERS_SQL, {"days": since_days})
    offer_rows = result.fetchall()

    if not offer_rows:
        LOGGER.info("No recent offers found in the last %d day(s).", since_days)
        return

    offer_ids: list[UUID] = [UUID(str(row.id)) for row in offer_rows]
    offers_by_id: dict[UUID, OfferRow] = {
        UUID(str(row.id)): OfferRow(
            title=row.title,
            institution=row.institution,
            region=row.region or "",
            close_date=row.close_date,
            url=row.url or "",
        )
        for row in offer_rows
    }

    LOGGER.info(
        "Found %d offer(s) in the last %d day(s).", len(offer_ids), since_days
    )

    # Step 2: match against confirmed subscriptions
    matches: dict[UUID, list[UUID]] = await find_matches(session, offer_ids)

    if not matches:
        LOGGER.info("No subscriptions matched — nothing to send.")
        return

    notified_count = 0
    skipped_count = 0
    error_count = 0

    # Step 3: process each matched subscription
    for sub_id, matched_offer_ids in matches.items():
        # 3a: insert queue rows (idempotent)
        for offer_id in matched_offer_ids:
            await session.execute(
                _QUEUE_INSERT_SQL,
                {
                    "id": str(uuid4()),
                    "subscription_id": str(sub_id),
                    "job_offer_id": str(offer_id),
                },
            )

        # 3b: check if all matched offers already have a sent digest entry
        sent_result = await session.execute(
            _ALREADY_SENT_SQL,
            {
                "subscription_id": str(sub_id),
                "offer_ids": [str(oid) for oid in matched_offer_ids],
            },
        )
        sent_row = sent_result.fetchone()
        already_sent_count: int = sent_row.cnt if sent_row else 0

        if already_sent_count >= len(matched_offer_ids):
            LOGGER.info(
                "Subscription %s already received digest for all %d offer(s) — skipping.",
                sub_id,
                len(matched_offer_ids),
            )
            skipped_count += 1
            continue

        # 3c: load subscription email + unsubscribe token
        sub_result = await session.execute(
            _SUBSCRIPTION_SQL,
            {"subscription_id": str(sub_id)},
        )
        sub_row = sub_result.fetchone()
        if sub_row is None:
            LOGGER.warning("Subscription %s not found — skipping.", sub_id)
            continue

        email: str = sub_row.email
        unsubscribe_token: str = str(sub_row.unsubscribe_token)

        # 3d: build OfferRow list for this subscriber
        offer_list: list[OfferRow] = [
            offers_by_id[oid] for oid in matched_offer_ids if oid in offers_by_id
        ]

        if dry_run:
            LOGGER.info(
                "[dry-run] Would send digest with %d offer(s) to %s",
                len(offer_list),
                email,
            )
            notified_count += 1
            continue

        # 3e: send digest email
        try:
            await send_notification_email(
                email=email,
                offers=offer_list,
                unsubscribe_token=unsubscribe_token,
                notification_type="digest",
            )
        except NotificationError as exc:
            LOGGER.warning("Failed to send digest to %s: %s", email, exc)
            error_count += 1
            continue

        # 3f: mark queue rows as sent
        await session.execute(
            _MARK_SENT_SQL,
            {
                "subscription_id": str(sub_id),
                "offer_ids": [str(oid) for oid in matched_offer_ids],
            },
        )
        notified_count += 1

    LOGGER.info(
        "Done. Offers in window: %d | Subscribers notified: %d | Skipped: %d | Errors: %d",
        len(offer_ids),
        notified_count,
        skipped_count,
        error_count,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send weekly digest notifications for recent job offers.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Run all DB reads and inserts but skip SMTP sends and queue updates.",
    )
    parser.add_argument(
        "--since",
        dest="since_days",
        type=int,
        default=7,
        metavar="DAYS",
        help="Lookback window in days (default: 7).",
    )
    args = parser.parse_args()

    if args.dry_run:
        LOGGER.info("Running in DRY-RUN mode — no emails will be sent.")

    LOGGER.info("Digest window: last %d day(s).", args.since_days)
    asyncio.run(run(args.dry_run, args.since_days))


if __name__ == "__main__":
    main()
