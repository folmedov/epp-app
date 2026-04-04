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

    # Deduplicate by fingerprint — keep last occurrence (same as DB would keep on conflict).
    # Only include columns that exist on the JobOffer ORM model (schema may contain
    # per-source fields such as `external_id` and `raw_data` which live in
    # `job_offer_sources`).
    allowed_cols = {c.name for c in JobOffer.__table__.columns}

    # Defensive check: new sprint added columns must exist in the target DB schema.
    # If migrations haven't been applied against the DATABASE_URL used by this
    # process, the multi-row INSERT below will fail with a cryptic SQLAlchemy
    # DataError. Detect and fail fast with a clear message.
    required_new_cols = {"ministry", "start_date", "close_date", "conv_type"}
    missing = required_new_cols - allowed_cols
    if missing:
        LOGGER.error(
            "Database schema missing expected columns: %s. Run alembic upgrade head against the DATABASE_URL in your environment.",
            ", ".join(sorted(missing)),
        )
        raise RuntimeError(
            "Database schema out-of-sync: missing columns: " + ", ".join(sorted(missing))
        )
    seen: dict[str, dict] = {}
    for offer in valid:
        row = offer.model_dump(exclude={"id", "created_at", "updated_at"})
        row["id"] = uuid4()
        filtered = {k: v for k, v in row.items() if k in allowed_cols}
        seen[offer.fingerprint] = filtered  # type: ignore[index]
    rows = list(seen.values())
    deduped = len(valid) - len(rows)
    if deduped:
        LOGGER.warning("Removed %d duplicate fingerprint(s) from batch", deduped)

    # asyncpg uses a signed Int16 for the Bind message param count, giving
    # a practical maximum of 32_767 parameters per statement. Compute a
    # conservative chunk size dynamically based on the number of columns per
    # row to avoid ever exceeding that limit regardless of schema changes.
    MAX_PARAMS = 32767
    total_rows = 0
    # Determine number of parameters per row (all rows are dicts with same keys)
    params_per_row = len(rows[0])
    # Reserve one parameter as safety margin
    safe_chunk = max(1, MAX_PARAMS // (params_per_row + 1))
    if safe_chunk < len(rows):
        LOGGER.info(
            "Chunking inserts: %d params/row -> using chunk size %d to avoid exceeding %d parameters",
            params_per_row,
            safe_chunk,
            MAX_PARAMS,
        )
    for offset in range(0, len(rows), safe_chunk):
        chunk = rows[offset : offset + safe_chunk]
        stmt = insert(JobOffer).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["fingerprint"],
            set_={
                "state": stmt.excluded.state,
                "url": stmt.excluded.url,
                "salary_bruto": stmt.excluded.salary_bruto,
                "ministry": stmt.excluded.ministry,
                "start_date": stmt.excluded.start_date,
                "close_date": stmt.excluded.close_date,
                "conv_type": stmt.excluded.conv_type,
                "updated_at": func.now(),
            },
        )
        result = await session.execute(stmt)
        total_rows += result.rowcount

    await session.flush()
    return total_rows


__all__ = ["upsert_job_offers"]
