"""Repository layer: bulk upsert of job offers into PostgreSQL."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.schemas import JobOfferSchema
from src.database.models import JobOffer, JobOfferSource


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
) -> dict[str, UUID]:
    """Upsert a list of job offers into the job_offers table.

    Uses ``ON CONFLICT (fingerprint) DO UPDATE`` to keep mutable fields
    current on every run. Offers with ``fingerprint=None`` are skipped.

    Returns a mapping of ``fingerprint → job_offer_id`` for every row
    inserted or updated, so callers can resolve the FK when writing
    ``job_offer_sources`` rows.
    """
    valid = [o for o in offers if o.fingerprint is not None]
    skipped = len(offers) - len(valid)
    if skipped:
        LOGGER.warning("Skipping %d offer(s) without fingerprint", skipped)

    if not valid:
        return {}

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

    # Cross-source pre-lookup: some offers in this batch may have a cross_source_key
    # that matches an existing canonical row owned by a different source (e.g. a TEEE
    # row already stored, and now we are loading the same offer from EEPP).  In that
    # case we must NOT insert a second job_offers row; instead we resolve the existing
    # id/fingerprint and add it to fingerprint_to_id so that upsert_job_offer_sources
    # can correctly set job_offer_id on the new source row.
    incoming_cross_keys = [
        r["cross_source_key"]
        for r in rows
        if r.get("cross_source_key") is not None
    ]
    # fingerprint → (id, cross_source_key) for already-stored rows
    existing_by_cross_key: dict[str, tuple[UUID, str]] = {}
    if incoming_cross_keys:
        lookup = await session.execute(
            select(JobOffer.id, JobOffer.fingerprint, JobOffer.cross_source_key).where(
                JobOffer.cross_source_key.in_(incoming_cross_keys)
            )
        )
        for existing_id, existing_fp, existing_csk in lookup:
            existing_by_cross_key[existing_csk] = (existing_id, existing_fp)

    # Partition: rows that map to an existing cross-source canonical row are
    # resolved immediately; the rest go through the normal INSERT path.
    fingerprint_to_id: dict[str, UUID] = {}
    rows_to_insert: list[dict] = []
    for row in rows:
        csk = row.get("cross_source_key")
        if csk and csk in existing_by_cross_key:
            existing_id, existing_fp = existing_by_cross_key[csk]
            if existing_fp != row["fingerprint"]:
                # Different source owns the canonical row — reuse it.
                LOGGER.debug(
                    "Cross-source match: fingerprint %s -> existing row %s (cross_source_key=%s)",
                    row["fingerprint"], existing_id, csk,
                )
                fingerprint_to_id[row["fingerprint"]] = existing_id
                continue
        rows_to_insert.append(row)

    cross_matched = len(rows) - len(rows_to_insert)
    if cross_matched:
        LOGGER.info("Cross-source pre-lookup matched %d offer(s) to existing canonical rows", cross_matched)

    if not rows_to_insert:
        return fingerprint_to_id

    rows = rows_to_insert

    # asyncpg uses a signed Int16 for the Bind message param count, giving
    # a practical maximum of 32_767 parameters per statement. Compute a
    # conservative chunk size dynamically based on the number of columns per
    # row to avoid ever exceeding that limit regardless of schema changes.
    MAX_PARAMS = 32767
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
                "cross_source_key": case((higher_or_equal, inc.cross_source_key), else_=cur.cross_source_key),
                "updated_at":   case((higher_or_equal, func.now()),       else_=cur.updated_at),
            },
        ).returning(JobOffer.id, JobOffer.fingerprint)
        result = await session.execute(stmt)
        for row in result:
            fingerprint_to_id[row.fingerprint] = row.id

    await session.flush()
    return fingerprint_to_id


async def upsert_job_offer_sources(
    session: AsyncSession,
    offers: list[JobOfferSchema],
    fingerprint_to_id: dict[str, UUID],
) -> int:
    """Upsert one source row per offer into the job_offer_sources table.

    Resolves ``job_offer_id`` from the mapping returned by
    ``upsert_job_offers()``. Offers whose fingerprint is not in the mapping
    are skipped with a warning.

    For offers with a stable ``external_id``, uses
    ``ON CONFLICT (source, external_id) DO UPDATE`` so re-running the loader
    is idempotent. For offers with ``external_id=None`` a new audit row is
    inserted on every run (the ``_elastic_id`` stored in ``raw_data`` provides
    per-run traceability).

    Returns the number of rows affected.
    """
    rows = []
    for offer in offers:
        if offer.fingerprint is None:
            continue
        job_offer_id = fingerprint_to_id.get(offer.fingerprint)
        if job_offer_id is None:
            LOGGER.warning(
                "No job_offer_id resolved for fingerprint %s; skipping source row",
                offer.fingerprint,
            )
            continue
        rows.append({
            "id": uuid4(),
            "job_offer_id": job_offer_id,
            "source": offer.source,
            "external_id": offer.external_id,
            "raw_data": offer.raw_data,
            "original_state": offer.state,
        })

    if not rows:
        return 0

    # Deduplicate by (source, external_id) for rows that have a non-NULL external_id.
    # A single batch can contain the same offer across multiple states (e.g. when
    # --state all is used); PostgreSQL raises CardinalityViolationError if ON CONFLICT
    # DO UPDATE would touch the same row twice within one statement.
    # For NULL external_id rows there is no conflict target, so no dedup is needed.
    seen_source_key: dict[tuple[str, str], dict] = {}
    deduped_rows: list[dict] = []
    for row in rows:
        ext_id = row.get("external_id")
        if ext_id is None:
            deduped_rows.append(row)
            continue
        key = (row["source"], ext_id)
        existing = seen_source_key.get(key)
        if existing is None or (
            _STATE_PRIORITY.get(row.get("original_state", ""), 3)
            <= _STATE_PRIORITY.get(existing.get("original_state", ""), 3)
        ):
            seen_source_key[key] = row
    deduped_rows.extend(seen_source_key.values())
    rows = deduped_rows

    MAX_PARAMS = 32767
    params_per_row = len(rows[0])
    safe_chunk = max(1, MAX_PARAMS // (params_per_row + 1))
    total_rows = 0

    for offset in range(0, len(rows), safe_chunk):
        chunk = rows[offset : offset + safe_chunk]
        stmt = insert(JobOfferSource).values(chunk)
        inc = stmt.excluded
        # ON CONFLICT only fires for non-NULL external_id pairs (PostgreSQL
        # treats NULLs as distinct, so NULL external_id rows never conflict).
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "external_id"],
            set_={
                "job_offer_id": inc.job_offer_id,
                "raw_data": inc.raw_data,
                "original_state": inc.original_state,
                "ingested_at": func.now(),
            },
        )
        result = await session.execute(stmt)
        total_rows += result.rowcount

    await session.flush()
    return total_rows


__all__ = ["upsert_job_offers", "upsert_job_offer_sources"]
