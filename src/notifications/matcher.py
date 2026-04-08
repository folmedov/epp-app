"""Keyword matcher for job offer notifications.

Matches confirmed subscriptions against a batch of new offers using
PostgreSQL unaccent ILIKE at the DB level.

Public interface:
- find_matches(session, offer_ids) -> dict[UUID, list[UUID]]
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LOGGER = logging.getLogger(__name__)

_MATCH_SQL = text("""
    SELECT s.id        AS subscription_id,
           jo.id       AS job_offer_id
    FROM   subscriptions s
    CROSS  JOIN job_offers jo
    JOIN   LATERAL unnest(s.keywords) AS kw ON TRUE
    WHERE  jo.id = ANY(:offer_ids)
      AND  s.confirmed = TRUE
      AND  unaccent(jo.title) ILIKE unaccent('%' || kw || '%')
    GROUP  BY s.id, jo.id
""")


async def find_matches(
    session: AsyncSession,
    offer_ids: list[UUID],
) -> dict[UUID, list[UUID]]:
    """Return matching offer IDs per confirmed subscription.

    Args:
        session: Active async SQLAlchemy session.
        offer_ids: IDs of new offers to match against (typically offers
            with notified_at IS NULL from the current ingestion run).

    Returns:
        A dict mapping subscription_id → [job_offer_id, ...] for every
        confirmed subscription that matches at least one keyword in at
        least one of the given offers. Subscriptions with no matches are
        absent from the dict. Returns {} immediately if offer_ids is empty.
    """
    if not offer_ids:
        return {}

    result = await session.execute(
        _MATCH_SQL,
        {"offer_ids": [str(oid) for oid in offer_ids]},
    )
    rows = result.fetchall()

    matches: dict[UUID, list[UUID]] = {}
    for row in rows:
        sub_id = UUID(str(row.subscription_id))
        offer_id = UUID(str(row.job_offer_id))
        matches.setdefault(sub_id, []).append(offer_id)

    LOGGER.info(
        "Matcher: %d offer(s) → %d subscription(s) matched",
        len(offer_ids),
        len(matches),
    )
    return matches
