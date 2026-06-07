"""Match newly-ingested offers against active search subscriptions.

Runs after ingestion. For each active search subscription, finds offers
whose title contains the search term (case-insensitive) that haven't been
notified yet. Queues them in notification_queue and sends immediate emails.

Usage:
    PYTHONPATH=. python scripts/match_search_subscriptions.py [--dry-run]

Exit codes:
    0   Success (or dry-run).
    1   One or more email sends failed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import JobOffer, Subscription, SearchSubscription, NotificationQueue
from src.database.session import SessionFactory
from src.notifications.email import OfferRow, NotificationError, send_search_match_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)


async def get_pending_matches(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Get all pending matches by iterating search subscriptions."""
    # First get all active search subscriptions
    ss_rows = await session.execute(
        select(
            SearchSubscription.id,
            SearchSubscription.subscription_id,
            SearchSubscription.term,
            Subscription.email,
            Subscription.unsubscribe_token,
        )
        .join(Subscription, Subscription.id == SearchSubscription.subscription_id)
        .where(
            SearchSubscription.active.is_(True),
            Subscription.confirmed.is_(True),
            Subscription.unsubscribe_token.isnot(None),
        )
    )
    subscriptions = ss_rows.all()

    # For each, count pending matches using a simple NOT EXISTS
    pending: list[dict[str, Any]] = []
    for ss in subscriptions:
        # Build the ILIKE pattern
        pattern = f"%{ss.term}%"
        # Subquery: already-notified offer_ids for this search_subscription
        notified_subq = (
            select(NotificationQueue.job_offer_id)
            .where(
                NotificationQueue.notification_type == "search_match",
                NotificationQueue.subscription_id == ss.subscription_id,
            )
            .correlate(JobOffer)
        )
        rows = await session.execute(
            select(
                JobOffer.id,
                JobOffer.title,
                JobOffer.institution,
                JobOffer.region,
                JobOffer.close_date,
                JobOffer.url,
            )
            .where(
                func.unaccent(JobOffer.title).ilike(func.unaccent(pattern)),
                JobOffer.is_active.is_(True),
                ~notified_subq.exists(),
            )
        )
        for row in rows:
            pending.append({
                "email": ss.email,
                "unsubscribe_token": ss.unsubscribe_token,
                "term": ss.term,
                "search_subscription_id": ss.id,
                "subscription_id": ss.subscription_id,
                "offer_id": row.id,
                "title": row.title,
                "institution": row.institution,
                "region": row.region,
                "close_date": row.close_date,
                "url": row.url,
            })

    return pending


async def _enqueue_and_send(
    session: AsyncSession,
    match: dict[str, Any],
    dry_run: bool,
) -> bool:
    """Insert notification_queue row and send email. Returns True on success."""
    if dry_run:
        LOGGER.info(
            "[DRY-RUN] Would notify %s about '%s' matching term '%s'",
            match["email"], match["title"], match["term"],
        )
        return True

    # Insert queue row
    nq = NotificationQueue(
        subscription_id=match["subscription_id"],
        job_offer_id=match["offer_id"],
        notification_type="search_match",
    )
    session.add(nq)

    offer = OfferRow(
        title=match["title"],
        institution=match["institution"],
        region=match["region"] or "",
        close_date=match["close_date"],
        url=match["url"] or "",
    )

    try:
        await send_search_match_email(
            email=match["email"],
            offer=offer,
            term=match["term"],
            unsubscribe_token=str(match["unsubscribe_token"]),
        )
        nq.status = "sent"
        nq.sent_at = func.now()
        LOGGER.info(
            "Notified %s about '%s' matching term '%s'",
            match["email"], match["title"], match["term"],
        )
        return True
    except NotificationError as exc:
        LOGGER.error(
            "Failed to notify %s about '%s': %s",
            match["email"], match["title"], exc,
        )
        nq.status = "failed"
        return False


async def main(dry_run: bool = False) -> int:
    """Run the matching loop. Returns 0 on success, 1 on partial failure."""
    if dry_run:
        LOGGER.info("DRY-RUN mode — no emails will be sent, no DB writes")

    async with SessionFactory() as session:
        matches = await get_pending_matches(session)

        if not matches:
            LOGGER.info("No pending search-subscription matches found")
            return 0

        LOGGER.info("Found %d pending match(es)", len(matches))

        fail_count = 0
        for match in matches:
            ok = await _enqueue_and_send(session, match, dry_run)
            if not ok:
                fail_count += 1

        if not dry_run:
            await session.commit()

    if fail_count:
        LOGGER.warning("%d / %d match notification(s) failed", fail_count, len(matches))
        return 1

    LOGGER.info("All %d match notification(s) sent successfully", len(matches))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Match offers against search subscriptions")
    parser.add_argument("--dry-run", action="store_true", help="Log matches without sending or writing")
    args = parser.parse_args()

    exit_code = asyncio.run(main(dry_run=args.dry_run))
    raise SystemExit(exit_code)
