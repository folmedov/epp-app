"""Repository layer: bulk upsert of job offers into PostgreSQL."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.schemas import JobOfferSchema
from src.database.models import JobOffer, JobOfferSource


LOGGER = logging.getLogger(__name__)

# State priority: higher integer = more advanced stage.
# A conflicting row only updates mutable fields when the incoming state is
# at the same stage or further along than the currently stored state.
# This allows forward transitions (postulacion → evaluacion → finalizada)
# while preventing regressions (e.g. a stale postulacion batch must not
# overwrite a row already stored as evaluacion or finalizada).
_STATE_PRIORITY = {"postulacion": 1, "evaluacion": 2, "finalizada": 3}


def _state_priority(state_col):
    """Return a SQL CASE expression mapping state → priority int (higher = more advanced)."""
    return case(
        (state_col == "postulacion", 1),
        (state_col == "evaluacion",  2),
        (state_col == "finalizada",  3),
        else_=0,  # unknown state loses to everything
    )


# Source authority: higher integer = more authoritative for canonical fields.
# TEEE is the primary source of truth; EEPP contributes new offers and enrichment.
_SOURCE_AUTHORITY: dict[str, int] = {"TEEE": 10, "EEPP": 5}



async def upsert_job_offers(
    session: AsyncSession,
    offers: list[JobOfferSchema],
    mode: str = "periodic",
) -> dict[str, UUID]:
    """Upsert a list of job offers into the job_offers table.

    Uses ``ON CONFLICT (fingerprint) DO UPDATE`` to keep mutable fields
    current on every run. Offers with ``fingerprint=None`` are skipped.

    ``mode`` controls the conflict resolution strategy:

    * ``'periodic'`` (default): forward-only state transitions.  A stored row
      is only updated when the incoming state is at the same lifecycle stage or
      further along (``postulacion → evaluacion → finalizada``).  This prevents
      regressions across cron runs while still handling gaps — e.g. an offer
      that went directly from ``postulacion`` to ``finalizada`` during a
      downtime period is correctly updated on the next run.

    * ``'initial'``: always overwrite on conflict (no state guard).  Designed
      for the first-time bulk load where callers load states in ascending
      lifecycle order (``finalizadas`` first, ``postulacion`` last) so the
      most current/active state wins any fingerprint conflict.  Each state
      MUST be committed as a separate transaction by the caller.

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
    required_new_cols = {"ministry", "start_date", "close_date", "conv_type", "first_employment", "vacancies", "prioritized"}
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
            _STATE_PRIORITY.get(filtered.get("state", ""), 0)
            >= _STATE_PRIORITY.get(current.get("state", ""), 0)
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
    # fingerprint → (id, fingerprint, source, state) for already-stored rows
    existing_by_cross_key: dict[str, tuple[UUID, str, str, str]] = {}
    if incoming_cross_keys:
        # Chunk the IN-list to stay under asyncpg's 32767-parameter limit.
        _CSK_CHUNK = 32767
        for _offset in range(0, len(incoming_cross_keys), _CSK_CHUNK):
            _chunk_keys = incoming_cross_keys[_offset : _offset + _CSK_CHUNK]
            lookup = await session.execute(
                select(JobOffer.id, JobOffer.fingerprint, JobOffer.cross_source_key, JobOffer.source, JobOffer.state).where(
                    JobOffer.cross_source_key.in_(_chunk_keys)
                )
            )
            for existing_id, existing_fp, existing_csk, existing_source, existing_state in lookup:
                existing_by_cross_key[existing_csk] = (existing_id, existing_fp, existing_source or "", existing_state or "")

    # Partition: rows that map to an existing cross-source canonical row are
    # resolved immediately; the rest go through the normal INSERT path.
    #
    # Source priority policy:
    #   TEEE (authority=10) is the primary source of truth.  When a TEEE offer
    #   matches an EEPP canonical row (EEPP ran first), TEEE promotes the canonical
    #   row by overwriting canonical fields (title, state, url, etc.) with TEEE
    #   data.  State follows forward-only lifecycle logic (TEEE state wins unless
    #   the stored state is already more advanced).
    #
    #   EEPP (authority=5) defers to TEEE for canonical fields.  It enriches the
    #   canonical row with EEPP-exclusive fields: gross_salary (COALESCE — only if
    #   lacking), first_employment, vacancies, prioritized.
    fingerprint_to_id: dict[str, UUID] = {}
    rows_to_insert: list[dict] = []
    enrichment_updates: list[dict] = []   # EEPP-exclusive fields pushed to canonical row
    canonical_promotions: list[dict] = [] # TEEE overrides EEPP-owned canonical rows
    for row in rows:
        csk = row.get("cross_source_key")
        if csk and csk in existing_by_cross_key:
            existing_id, existing_fp, existing_source, existing_state = existing_by_cross_key[csk]
            if existing_fp != row["fingerprint"]:
                # Different source owns the canonical row — reuse it.
                incoming_source = row.get("source", "")
                incoming_auth = _SOURCE_AUTHORITY.get(incoming_source, 0)
                existing_auth = _SOURCE_AUTHORITY.get(existing_source, 0)
                LOGGER.debug(
                    "Cross-source match: fingerprint %s → existing row %s "
                    "(cross_source_key=%s, incoming=%s auth=%d, existing=%s auth=%d)",
                    row["fingerprint"], existing_id, csk,
                    incoming_source, incoming_auth, existing_source, existing_auth,
                )
                fingerprint_to_id[row["fingerprint"]] = existing_id

                if incoming_auth > existing_auth:
                    # Higher-authority source (TEEE) promotes the canonical row.
                    # State uses forward-only lifecycle: incoming wins at same or
                    # higher stage; existing wins if already more advanced.
                    incoming_state_pri = _STATE_PRIORITY.get(row.get("state", ""), 0)
                    existing_state_pri = _STATE_PRIORITY.get(existing_state, 0)
                    winning_state = row["state"] if incoming_state_pri >= existing_state_pri else existing_state
                    canonical_promotions.append({
                        "job_offer_id": existing_id,
                        "source": incoming_source,
                        "state": winning_state,
                        "title": row.get("title"),
                        "institution": row.get("institution"),
                        "region": row.get("region"),
                        "city": row.get("city"),
                        "url": row.get("url"),
                        "ministry": row.get("ministry"),
                        "start_date": row.get("start_date"),
                        "close_date": row.get("close_date"),
                        "conv_type": row.get("conv_type"),
                        "cross_source_key": csk,
                    })
                elif any(
                    row.get(f) is not None
                    for f in ("gross_salary", "first_employment", "vacancies", "prioritized")
                ):
                    # Lower-authority source (EEPP) enriches EEPP-exclusive fields.
                    # gross_salary: COALESCE — only fill if the canonical row has no salary.
                    # first_employment / vacancies / prioritized: always update (TEEE never has them).
                    enrichment_updates.append({
                        "job_offer_id": existing_id,
                        "gross_salary": row.get("gross_salary"),
                        "first_employment": row.get("first_employment"),
                        "vacancies": row.get("vacancies"),
                        "prioritized": row.get("prioritized"),
                    })
                continue
        rows_to_insert.append(row)

    # Apply canonical promotion updates (TEEE overrides EEPP-owned canonical rows).
    if canonical_promotions:
        LOGGER.info("Promoting %d canonical row(s) from EEPP to TEEE ownership", len(canonical_promotions))
        for cp in canonical_promotions:
            await session.execute(
                update(JobOffer)
                .where(JobOffer.id == cp["job_offer_id"])
                .values(
                    source=cp["source"],
                    state=cp["state"],
                    title=cp["title"],
                    institution=cp["institution"],
                    region=cp["region"],
                    city=cp["city"],
                    url=cp["url"],
                    ministry=cp["ministry"],
                    start_date=cp["start_date"],
                    close_date=cp["close_date"],
                    conv_type=cp["conv_type"],
                    cross_source_key=cp["cross_source_key"],
                    updated_at=func.now(),
                )
            )

    # Apply enrichment updates to existing canonical rows (cross-source matches).
    # gross_salary uses COALESCE so that a TEEE salary is never overwritten.
    # The three EEPP-exclusive fields are set unconditionally since TEEE never
    # provides them.
    if enrichment_updates:
        LOGGER.info("Applying EEPP enrichment to %d existing canonical row(s)", len(enrichment_updates))
        for eu in enrichment_updates:
            await session.execute(
                update(JobOffer)
                .where(JobOffer.id == eu["job_offer_id"])
                .values(
                    gross_salary=func.coalesce(JobOffer.gross_salary, eu["gross_salary"]),
                    first_employment=eu["first_employment"],
                    vacancies=eu["vacancies"],
                    prioritized=eu["prioritized"],
                    updated_at=func.now(),
                )
            )

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

        if mode == "initial":
            # Initial load: always overwrite on conflict.  The caller is
            # responsible for loading states in ascending lifecycle order
            # (finalizadas first, postulacion last) so that the most
            # current/active state wins any fingerprint collision.
            stmt = stmt.on_conflict_do_update(
                index_elements=["fingerprint"],
                set_={
                    "state":            inc.state,
                    "url":              inc.url,
                    "gross_salary":     inc.gross_salary,
                    "ministry":         inc.ministry,
                    "start_date":       inc.start_date,
                    "close_date":       inc.close_date,
                    "conv_type":        inc.conv_type,
                    "cross_source_key": inc.cross_source_key,
                    "first_employment": inc.first_employment,
                    "vacancies":        inc.vacancies,
                    "prioritized":      inc.prioritized,
                    "updated_at":       func.now(),
                },
            ).returning(JobOffer.id, JobOffer.fingerprint)
        else:
            # Periodic updates: forward-only state transitions.  A stored row
            # is only updated when the incoming state is at the same lifecycle
            # stage or further along, preventing regressions while still
            # handling gaps (e.g. postulacion → finalizada in one hop).
            higher_or_equal = _state_priority(inc.state) >= _state_priority(cur.state)
            stmt = stmt.on_conflict_do_update(
                index_elements=["fingerprint"],
                set_={
                    "state":        case((higher_or_equal, inc.state),        else_=cur.state),
                    "url":          case((higher_or_equal, inc.url),          else_=cur.url),
                    "gross_salary": case((higher_or_equal, inc.gross_salary), else_=cur.gross_salary),
                    "ministry":     case((higher_or_equal, inc.ministry),     else_=cur.ministry),
                    "start_date":   case((higher_or_equal, inc.start_date),   else_=cur.start_date),
                    "close_date":   case((higher_or_equal, inc.close_date),   else_=cur.close_date),
                    "conv_type":    case((higher_or_equal, inc.conv_type),    else_=cur.conv_type),
                    "cross_source_key": case((higher_or_equal, inc.cross_source_key), else_=cur.cross_source_key),
                    "first_employment": inc.first_employment,
                    "vacancies":        inc.vacancies,
                    "prioritized":      inc.prioritized,
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

    Uses ``ON CONFLICT (job_offer_id, source) DO UPDATE`` so re-running the
    loader is idempotent.  The conflict target is the canonical job offer +
    source pair, which allows the same ``external_id`` to legitimately appear
    in multiple source rows when those rows belong to different canonical
    ``job_offer`` rows (e.g. two TEEE offers sharing the same ``ID Conv`` but
    originating from different portals).

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

    # Deduplicate by (job_offer_id, source) — the same conflict target used by
    # ON CONFLICT below.  A single batch can contain the same canonical offer
    # more than once (e.g. when --state all is used); PostgreSQL raises
    # CardinalityViolationError if ON CONFLICT DO UPDATE would touch the same
    # row twice within one statement.
    seen_jo_source: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (str(row["job_offer_id"]), row["source"])
        existing = seen_jo_source.get(key)
        if existing is None or (
            _STATE_PRIORITY.get(row.get("original_state", ""), 3)
            <= _STATE_PRIORITY.get(existing.get("original_state", ""), 3)
        ):
            seen_jo_source[key] = row
    rows = list(seen_jo_source.values())

    MAX_PARAMS = 32767
    params_per_row = len(rows[0])
    safe_chunk = max(1, MAX_PARAMS // (params_per_row + 1))
    total_rows = 0

    for offset in range(0, len(rows), safe_chunk):
        chunk = rows[offset : offset + safe_chunk]
        stmt = insert(JobOfferSource).values(chunk)
        inc = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["job_offer_id", "source"],
            set_={
                "external_id": inc.external_id,
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
