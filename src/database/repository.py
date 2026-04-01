"""Repository layer: bulk upsert of job offers into PostgreSQL."""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.schemas import JobOfferSchema
from src.database.models import JobOffer


LOGGER = logging.getLogger(__name__)


async def upsert_job_offers(
    session: AsyncSession,
    offers: list[JobOfferSchema],
) -> int:
    """Upsert a list of job offers into the job_offers table.

    Uses ``ON CONFLICT (fingerprint) DO UPDATE`` to keep mutable fields
    (state, url, salary_bruto, raw_data, updated_at) current on every run.

    Offers with ``fingerprint=None`` are skipped and logged as warnings.

    Returns the number of rows affected (inserted + updated).
    """
    valid = [o for o in offers if o.fingerprint is not None]
    skipped = len(offers) - len(valid)
    if skipped:
        LOGGER.warning("Skipping %d offer(s) without fingerprint", skipped)

    if not valid:
        return 0

    rows = []
    for offer in valid:
        row = offer.model_dump(exclude={"id", "created_at", "updated_at"})
        row["id"] = uuid4()
        rows.append(row)

    stmt = insert(JobOffer).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["fingerprint"],
        set_={
            "state": stmt.excluded.state,
            "url": stmt.excluded.url,
            "salary_bruto": stmt.excluded.salary_bruto,
            "raw_data": stmt.excluded.raw_data,
            "updated_at": func.now(),
        },
    )

    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount


__all__ = ["upsert_job_offers"]
