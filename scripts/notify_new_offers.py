"""Send immediate email notifications for new (unnotified) job offers.

Queries all active offers where notified_at IS NULL, matches them against
confirmed subscriptions using the keyword matcher, sends one email per
subscriber with the list of matching offers, and stamps notified_at on
every processed offer.

Usage:
    PYTHONPATH=. python scripts/notify_new_offers.py [--dry-run]

Exit codes:
    0   Always (SMTP failures are non-fatal; DB errors exit non-zero naturally).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
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

_UNNOTIFIED_SQL = text("""
    SELECT id, title, institution, region, close_date, url
    FROM   job_offers
    WHERE  notified_at IS NULL
      AND  is_active = TRUE
""")

_QUEUE_INSERT_SQL = text("""
    INSERT INTO notification_queue
        (id, subscription_id, job_offer_id, notification_type, status)
    VALUES
        (:id, :subscription_id, :job_offer_id, 'immediate', 'pending')
    ON CONFLICT ON CONSTRAINT uq_notification_queue_dedup DO NOTHING
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
      AND  notification_type = 'immediate'
      AND  status = 'pending'
""")

_STAMP_NOTIFIED_SQL = text("""
    UPDATE job_offers
    SET    notified_at = NOW()
    WHERE  id = ANY(:offer_ids)
""")


# ── Main logic ────────────────────────────────────────────────────────────────

async def run(dry_run: bool) -> None:
    engine = get_engine()
    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                await _process(session, dry_run)
    finally:
        await engine.dispose()


async def _process(session: AsyncSession, dry_run: bool) -> None:
    # Step 1: fetch unnotified active offers
    result = await session.execute(_UNNOTIFIED_SQL)
    offer_rows = result.fetchall()

    if not offer_rows:
        LOGGER.info("No new offers to notify.")
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

    LOGGER.info("Found %d unnotified offer(s).", len(offer_ids))

    # Step 2: match against confirmed subscriptions
    matches: dict[UUID, list[UUID]] = await find_matches(session, offer_ids)

    if not matches:
        LOGGER.info("No subscriptions matched — stamping notified_at and exiting.")
        if not dry_run:
            await session.execute(
                _STAMP_NOTIFIED_SQL,
                {"offer_ids": [str(oid) for oid in offer_ids]},
            )
        return

    notified_count = 0
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

        # 3b: load subscription email + unsubscribe token
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

        # 3c: build OfferRow list for this subscriber
        offer_list: list[OfferRow] = [
            offers_by_id[oid] for oid in matched_offer_ids if oid in offers_by_id
        ]

        if dry_run:
            LOGGER.info(
                "[dry-run] Would send %d offer(s) to %s",
                len(offer_list),
                email,
            )
            notified_count += 1
            continue

        # 3d: send email
        try:
            await send_notification_email(
                email=email,
                offers=offer_list,
                unsubscribe_token=unsubscribe_token,
                notification_type="immediate",
            )
        except NotificationError as exc:
            LOGGER.warning("Failed to send notification to %s: %s", email, exc)
            error_count += 1
            continue

        # 3e: mark queue rows as sent
        await session.execute(
            _MARK_SENT_SQL,
            {
                "subscription_id": str(sub_id),
                "offer_ids": [str(oid) for oid in matched_offer_ids],
            },
        )
        notified_count += 1

    # Step 4: stamp notified_at on all processed offers
    if not dry_run:
        await session.execute(
            _STAMP_NOTIFIED_SQL,
            {"offer_ids": [str(oid) for oid in offer_ids]},
        )
        LOGGER.info("Stamped notified_at on %d offer(s).", len(offer_ids))
    else:
        LOGGER.info("[dry-run] Would stamp notified_at on %d offer(s).", len(offer_ids))

    LOGGER.info(
        "Done. Offers processed: %d | Subscribers notified: %d | Errors: %d",
        len(offer_ids),
        notified_count,
        error_count,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send immediate notifications for new job offers.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Run all DB reads and matcher logic but skip SMTP sends and notified_at stamps.",
    )
    args = parser.parse_args()

    if args.dry_run:
        LOGGER.info("Running in DRY-RUN mode — no emails will be sent.")

    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
