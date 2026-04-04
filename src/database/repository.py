"""Repository layer: bulk upsert of job offers into PostgreSQL."""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.schemas import JobOfferSchema
from src.database.models import JobOffer


LOGGER = logging.getLogger(__name__)

# State priority: lower integer = higher priority.
# A conflicting row only updates mutable fields when the incoming state has
# equal or higher priority than the currently stored state.
_STATE_PRIORITY = {"postulacion": 1, "evaluacion": 2}


def _state_priority(state_col):
    """Return a SQL CASE expression mapping state → priority int (lower = higher)."""
    return case(
        (state_col == "postulacion", 1),
        (state_col == "evaluacion", 2),
        else_=3,
    )


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
        current = seen.get(offer.fingerprint)  # type: ignore[arg-type]
        if current is None or (
            _STATE_PRIORITY.get(filtered.get("state", ""), 3)
            <= _STATE_PRIORITY.get(current.get("state", ""), 3)
        ):
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
        inc = stmt.excluded                   # incoming (excluded) row
        cur = JobOffer.__table__.c            # current row in DB
        # Only update when the incoming state has equal or higher priority.
        # This prevents a later-loaded "finalizada" batch from overwriting
        # records already stored as "postulacion" or "evaluacion".
        higher_or_equal = _state_priority(inc.state) <= _state_priority(cur.state)
        stmt = stmt.on_conflict_do_update(
            index_elements=["fingerprint"],
            set_={
                "state":        case((higher_or_equal, inc.state),        else_=cur.state),
                "url":          case((higher_or_equal, inc.url),          else_=cur.url),
                "salary_bruto": case((higher_or_equal, inc.salary_bruto), else_=cur.salary_bruto),
                "ministry":     case((higher_or_equal, inc.ministry),     else_=cur.ministry),
                "start_date":   case((higher_or_equal, inc.start_date),   else_=cur.start_date),
                "close_date":   case((higher_or_equal, inc.close_date),   else_=cur.close_date),
                "conv_type":    case((higher_or_equal, inc.conv_type),    else_=cur.conv_type),
                "updated_at":   case((higher_or_equal, func.now()),       else_=cur.updated_at),
            },
        )
        result = await session.execute(stmt)
        total_rows += result.rowcount

    await session.flush()
    return total_rows


__all__ = ["upsert_job_offers"]
