"""Send email notifications for state changes on followed offers.

Queries offer_follows for all active follows. For each followed offer,
compares the current state against last_state. If last_state is NULL
(just followed), records the current state without notifying. If the
state changed since last_state, sends an email to the subscriber.

Usage:
    PYTHONPATH=. python scripts/notify_followed_offers.py [--dry-run]

Exit codes:
    0   Always (SMTP failures are non-fatal).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_engine
from src.notifications.email import NotificationError, send_state_change_email
from src.notifications.email import OfferRow as EmailOfferRow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

# ── SQL statements ────────────────────────────────────────────────────────────

_FOLLOWED_WITH_STATE_SQL = text("""
    SELECT
        ofv.id            AS follow_id,
        ofv.subscription_id,
        ofv.job_offer_id,
        ofv.last_state,
        jo.title,
        jo.institution,
        jo.region,
        jo.close_date,
        jo.url,
        jo.state          AS current_state,
        s.email,
        s.unsubscribe_token
    FROM   offer_follows ofv
    JOIN   job_offers   jo ON jo.id = ofv.job_offer_id
    JOIN   subscriptions s  ON s.id = ofv.subscription_id
    WHERE  s.confirmed = TRUE
      AND (jo.state != ofv.last_state OR ofv.last_state IS NULL)
""")

_UPDATE_LAST_STATE_SQL = text("""
    UPDATE offer_follows
    SET    last_state = :state
    WHERE  id = :follow_id
""")

_STATE_CHANGE_TITLE = "Cambio de estado en oferta seguida"


async def run(dry_run: bool) -> None:
    engine = get_engine()
    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                await _process(session, dry_run)
    finally:
        await engine.dispose()


async def _process(session: AsyncSession, dry_run: bool) -> None:
    result = await session.execute(_FOLLOWED_WITH_STATE_SQL)
    rows = result.fetchall()

    if not rows:
        LOGGER.info("No state changes detected on followed offers.")
        return

    notified = 0
    initialized = 0

    for row in rows:
        follow_id: UUID = UUID(str(row.follow_id))
        email: str = row.email
        unsubscribe_token: str = str(row.unsubscribe_token)
        current_state: str = row.current_state
        last_state: str | None = row.last_state

        if last_state is None:
            # First check since following — just record current state, don't notify
            if dry_run:
                LOGGER.info(
                    "[dry-run] Would initialize last_state='%s' for follow %s (offer: %s)",
                    current_state, follow_id, row.title,
                )
            else:
                await session.execute(
                    _UPDATE_LAST_STATE_SQL,
                    {"follow_id": str(follow_id), "state": current_state},
                )
            initialized += 1
            continue

        # State changed — notify
        offer = EmailOfferRow(
            title=row.title,
            institution=row.institution,
            region=row.region or "",
            close_date=row.close_date,
            url=row.url or "",
        )

        if dry_run:
            LOGGER.info(
                "[dry-run] Would notify %s about state change on '%s': %s → %s",
                email, row.title, last_state, current_state,
            )
        else:
            await _send_state_notification(
                session=session,
                email=email,
                offer=offer,
                unsubscribe_token=unsubscribe_token,
                old_state=last_state,
                new_state=current_state,
            )
            await session.execute(
                _UPDATE_LAST_STATE_SQL,
                {"follow_id": str(follow_id), "state": current_state},
            )

        notified += 1

    LOGGER.info(
        "Done. New follows initialized: %d | State-change notifications: %d",
        initialized, notified,
    )


async def _send_state_notification(
    session: AsyncSession,
    email: str,
    offer: EmailOfferRow,
    unsubscribe_token: str,
    old_state: str,
    new_state: str,
) -> None:
    """Send a state-change notification email."""
    try:
        await send_state_change_email(
            email=email,
            offer=offer,
            unsubscribe_token=unsubscribe_token,
            old_state=old_state,
            new_state=new_state,
        )
        LOGGER.info("Sent state-change notification to %s for '%s'", email, offer.title)
    except NotificationError as exc:
        LOGGER.warning("Failed to send state-change notification to %s: %s", email, exc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send state-change notifications for followed offers.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Read DB and log intent without sending emails or updating state.",
    )
    args = parser.parse_args()

    if args.dry_run:
        LOGGER.info("Running in DRY-RUN mode — no emails will be sent.")

    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
