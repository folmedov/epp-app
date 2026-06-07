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
from collections import defaultdict
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import JobOffer, Subscription, SearchSubscription, NotificationQueue
from src.database.session import SessionFactory
from src.notifications.email import OfferRow, NotificationError, send_search_match_email

MAX_EMAILS_PER_USER = 20

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
                JobOffer.state == "postulacion",
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


async def _send_digest_and_enqueue(
    session: AsyncSession,
    email: str,
    unsubscribe_token: str,
    matches: list[dict[str, Any]],
    dry_run: bool,
) -> bool:
    """Send one digest email with all matches, then enqueue queue rows.

    Returns True on success (email sent + all queue rows written).
    """
    if dry_run:
        terms = ", ".join(m["term"] for m in matches)
        LOGGER.info(
            "[DRY-RUN] Would send digest to %s (%d match(es): %s)",
            email, len(matches), terms,
        )
        return True

    # Build (OfferRow, term) list for the digest
    offer_term_pairs: list[tuple[OfferRow, str]] = []
    queue_rows: list[NotificationQueue] = []
    for m in matches:
        offer = OfferRow(
            title=m["title"],
            institution=m["institution"],
            region=m["region"] or "",
            close_date=m["close_date"],
            url=m["url"] or "",
        )
        offer_term_pairs.append((offer, m["term"]))
        # Enqueue each match for future dedup
        nq = NotificationQueue(
            subscription_id=m["subscription_id"],
            job_offer_id=m["offer_id"],
            notification_type="search_match",
        )
        session.add(nq)
        queue_rows.append(nq)

    try:
        await send_search_match_email(
            email=email,
            matches=offer_term_pairs,
            unsubscribe_token=str(unsubscribe_token),
        )
    except NotificationError as exc:
        LOGGER.error("Failed to send digest to %s: %s", email, exc)
        for nq in queue_rows:
            nq.status = "failed"
        return False

    for nq in queue_rows:
        nq.status = "sent"
        nq.sent_at = func.now()

    LOGGER.info("Digest sent to %s (%d match(es))", email, len(matches))
    return True


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

        # Group by email for per-user digest
        by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for m in matches:
            by_email[m["email"]].append(m)

        fail_count = 0
        for email, user_matches in by_email.items():
            token = str(user_matches[0]["unsubscribe_token"])
            if len(user_matches) > MAX_EMAILS_PER_USER:
                LOGGER.warning(
                    "Capping %d → %d matches for %s",
                    len(user_matches), MAX_EMAILS_PER_USER, email,
                )
                user_matches = user_matches[:MAX_EMAILS_PER_USER]
            ok = await _send_digest_and_enqueue(session, email, token, user_matches, dry_run)
            if not ok:
                fail_count += 1

        if not dry_run:
            await session.commit()

    if fail_count:
        LOGGER.warning(
            "%d / %d digest(s) failed to send",
            fail_count, len(by_email),
        )
        return 1

    LOGGER.info(
        "All %d digest(s) sent successfully (%d total match(es))",
        len(by_email), len(matches),
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Match offers against search subscriptions")
    parser.add_argument("--dry-run", action="store_true", help="Log matches without sending or writing")
    args = parser.parse_args()

    exit_code = asyncio.run(main(dry_run=args.dry_run))
    raise SystemExit(exit_code)
