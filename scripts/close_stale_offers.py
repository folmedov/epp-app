"""Mark stale active offers as inactive.

An offer is stale when its ``close_date`` is more than ``--grace-days`` days in
the past AND it no longer appears in the live TEEE or EEPP feeds.

The grace window (default 3 days) absorbs normal ingestion lag so that an offer
that closed yesterday is not immediately hidden while the next ingestion has not
yet processed it.

Usage::

    PYTHONPATH=. python scripts/close_stale_offers.py [--grace-days N] [--dry-run]

Options
-------
--grace-days N
    Days of tolerance after ``close_date`` before closing (default: 3).
--dry-run
    Identify stale offers and print what would be updated, but do not commit.

Exit codes
----------
0   Completed (even if zero offers were closed).
1   Unrecoverable error.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

sys.path.insert(0, ".")
from src.database.models import JobOffer, JobOfferSource
from src.database.session import get_session
from src.ingestion.eepp_client import EEPPClient
from src.ingestion.teee_client import TEEEClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Feed index helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _build_active_external_id_set() -> set[str]:
    """Fetch active offers from TEEE and EEPP and return their external_ids."""
    teee = TEEEClient()
    eepp = EEPPClient()

    LOGGER.info("Fetching live TEEE active offers (postulacion + evaluacion)…")
    teee_post, teee_eval = await asyncio.gather(
        teee.fetch_postulacion(),
        teee.fetch_evaluacion(),
    )
    LOGGER.info("  TEEE postulacion: %d  evaluacion: %d", len(teee_post), len(teee_eval))

    LOGGER.info("Fetching live EEPP active offers…")
    eepp_all = await eepp.fetch_all()
    LOGGER.info("  EEPP: %d", len(eepp_all))

    active_ids: set[str] = set()
    for offer in [*teee_post, *teee_eval, *eepp_all]:
        eid = offer.get("external_id")
        if eid:
            active_ids.add(str(eid))

    LOGGER.info("Active external_id set: %d entries", len(active_ids))
    return active_ids


# ─────────────────────────────────────────────────────────────────────────────
# DB queries
# ─────────────────────────────────────────────────────────────────────────────


async def _fetch_stale_offer_ids(
    session: Any,
    cutoff: datetime,
) -> list[UUID]:
    """Return IDs of is_active offers with close_date < cutoff in active states."""
    stmt = (
        select(JobOffer.id)
        .where(JobOffer.is_active.is_(True))
        .where(JobOffer.state.in_(["postulacion", "evaluacion"]))
        .where(JobOffer.close_date.isnot(None))
        .where(JobOffer.close_date < cutoff)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def _fetch_external_ids(
    session: Any,
    offer_ids: list[UUID],
) -> dict[UUID, list[str]]:
    """Return {offer_id: [external_id, ...]} for the given set of offer IDs."""
    if not offer_ids:
        return {}
    stmt = (
        select(JobOfferSource.job_offer_id, JobOfferSource.external_id)
        .where(JobOfferSource.job_offer_id.in_(offer_ids))
        .where(JobOfferSource.external_id.isnot(None))
    )
    rows = (await session.execute(stmt)).all()
    result: dict[UUID, list[str]] = {}
    for r in rows:
        result.setdefault(r.job_offer_id, []).append(str(r.external_id))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main logic
# ─────────────────────────────────────────────────────────────────────────────


async def close_stale(grace_days: int, dry_run: bool) -> int:
    """Mark stale offers as inactive; returns the count of closed offers."""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now_utc - timedelta(days=grace_days)
    LOGGER.info(
        "Cutoff date: %s  (grace_days=%d, dry_run=%s)",
        cutoff.date(),
        grace_days,
        dry_run,
    )

    # Fetch live active feed FIRST (before opening the DB transaction).
    active_external_ids = await _build_active_external_id_set()

    async with get_session() as session:
        stale_ids = await _fetch_stale_offer_ids(session, cutoff)
        LOGGER.info("Stale candidates in DB: %d", len(stale_ids))

        if not stale_ids:
            LOGGER.info("Nothing to close.")
            return 0

        ext_id_map = await _fetch_external_ids(session, stale_ids)

        # An offer should be closed when NONE of its external_ids appear in
        # the live active feed.  Offers with no external_id at all (e.g. from
        # directoresparachile.cl) are closed unconditionally once the grace
        # period has passed — there is no live feed to verify them against.
        to_close: list[UUID] = []
        still_active: list[UUID] = []

        for offer_id in stale_ids:
            eids = ext_id_map.get(offer_id, [])
            if any(eid in active_external_ids for eid in eids):
                still_active.append(offer_id)
            else:
                to_close.append(offer_id)

        LOGGER.info(
            "Still active in live feed: %d  |  To close: %d",
            len(still_active),
            len(to_close),
        )

        if dry_run:
            LOGGER.info("[DRY-RUN] Would set is_active=False on %d offers.", len(to_close))
            for oid in to_close[:25]:
                LOGGER.info("  %s", oid)
            if len(to_close) > 25:
                LOGGER.info("  … and %d more", len(to_close) - 25)
            return len(to_close)

        if to_close:
            await session.execute(
                update(JobOffer)
                .where(JobOffer.id.in_(to_close))
                .values(is_active=False)
            )
            await session.commit()
            LOGGER.info("Closed %d stale offers (is_active=False).", len(to_close))
        else:
            LOGGER.info("No offers to close.")

        return len(to_close)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mark stale active offers as inactive.",
    )
    parser.add_argument(
        "--grace-days",
        type=int,
        default=3,
        metavar="N",
        help="Days of tolerance after close_date (default: 3).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print what would be updated without committing.",
    )
    args = parser.parse_args()

    closed = asyncio.run(close_stale(grace_days=args.grace_days, dry_run=args.dry_run))
    LOGGER.info("Done. Total closed: %d", closed)


if __name__ == "__main__":
    main()
