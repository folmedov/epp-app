"""Sample-based integrity check for job_offers.

Re-fetches a random sample of DB rows from the upstream APIs and compares key
fields (state, title, gross_salary, close_date) to detect data drift. Exits
with code 1 if any field differs on any sampled row.

Usage:
    PYTHONPATH=. python scripts/integrity_check.py [options]

Options:
    --sample-size N             Total rows to sample (default: 20)
    --sampling proportional|random
                                proportional: stratified by state distribution (default)
                                random: uniform random sample
    --source TEEE|EEPP          Restrict sampling to one source (default: both)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from src.core.config import settings
from src.database.models import JobOffer, JobOfferSource
from src.database.session import get_session
from src.ingestion.eepp_client import EEPPClient
from src.ingestion.teee_client import TEEEClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

# Fields compared between the DB row and the re-fetched API offer.
_COMPARE_FIELDS: tuple[str, ...] = ("state", "title", "gross_salary", "close_date")

# Columns selected from the DB for each sampled row (via JOIN on canonical source).
_SAMPLE_COLS = (
    JobOffer.id.label("job_offer_id"),
    JobOffer.source,
    JobOffer.state,
    JobOffer.title,
    JobOffer.gross_salary,
    JobOffer.close_date,
    JobOfferSource.external_id,
)


def _base_query(source_filter: str | None):
    """Build the base SELECT + JOIN query used by both sampling modes."""
    q = (
        select(*_SAMPLE_COLS)
        .join(
            JobOfferSource,
            (JobOfferSource.job_offer_id == JobOffer.id)
            & (JobOfferSource.source == JobOffer.source),
        )
    )
    if source_filter:
        q = q.where(JobOffer.source == source_filter)
    return q


async def _sample_random(
    session: AsyncSession,
    sample_size: int,
    source_filter: str | None,
) -> list:
    """Return a uniform random sample of DB rows."""
    q = _base_query(source_filter).order_by(func.random()).limit(sample_size)
    result = await session.execute(q)
    return result.fetchall()


async def _sample_proportional(
    session: AsyncSession,
    sample_size: int,
    source_filter: str | None,
) -> list:
    """Return a sample stratified by state distribution.

    Each state contributes rows proportional to its share of the total row
    count so that active-state offers (postulacion, evaluacion) are always
    represented even though finalizada vastly outnumbers them.

    Rounding error is allocated to the largest bucket.
    """
    count_q = select(JobOffer.state, func.count().label("cnt"))
    if source_filter:
        count_q = count_q.where(JobOffer.source == source_filter)
    count_q = count_q.group_by(JobOffer.state)
    count_result = await session.execute(count_q)
    state_counts: dict[str, int] = {row.state: row.cnt for row in count_result}

    if not state_counts:
        return []

    total = sum(state_counts.values())
    # Compute per-state allocations (minimum 1 per state).
    per_state = {
        state: max(1, round(cnt / total * sample_size))
        for state, cnt in state_counts.items()
    }
    # Redistribute rounding error to the largest bucket.
    diff = sample_size - sum(per_state.values())
    if diff != 0:
        largest = max(state_counts, key=lambda s: state_counts[s])
        per_state[largest] = max(1, per_state[largest] + diff)

    rows: list = []
    for state, k in per_state.items():
        if k <= 0:
            continue
        q = (
            _base_query(source_filter)
            .where(JobOffer.state == state)
            .order_by(func.random())
            .limit(k)
        )
        result = await session.execute(q)
        rows.extend(result.fetchall())
    return rows


def _normalize(field: str, value: Any) -> Any:
    """Normalize a field value before drift comparison.

    - title: collapse whitespace + lowercase for encoding-tolerant comparison.
    - gross_salary: round to 2 dp so Decimal("1000000") == Decimal("1000000.00").
    - close_date: compare calendar date only (ignore time / timezone).
    """
    if value is None:
        return None
    if field == "title":
        return " ".join(str(value).lower().split())
    if field == "gross_salary":
        try:
            return round(Decimal(str(value)), 2)
        except InvalidOperation:
            return value
    if field == "close_date" and hasattr(value, "date"):
        return value.date()
    return value


async def _fetch_teee_offer(external_id: str, state: str) -> dict | None:
    """Query TEEE Elasticsearch for a single offer by external_id.

    Handles the two external_id formats used by TEEEClient:
    - Numeric string → query by ``ID Conv`` field.
    - ``teee:_id:<es_id>`` → query by Elasticsearch document ``_id``.
    """
    teee_state = "finalizadas" if state == "finalizada" else state

    if external_id.startswith("teee:_id:"):
        es_id = external_id.removeprefix("teee:_id:")
        query: dict = {"ids": {"values": [es_id]}}
    else:
        query = {
            "bool": {
                "must": [
                    {"term": {"Estado": teee_state}},
                    {"term": {"ID Conv": external_id}},
                ]
            }
        }

    body = {"size": 1, "query": query}
    try:
        async with httpx.AsyncClient(timeout=float(settings.SCRAPER_TIMEOUT)) as client:
            resp = await client.post(TEEEClient.ENDPOINT, json=body)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
    except httpx.HTTPError as exc:
        LOGGER.warning(
            "TEEE HTTP error re-fetching external_id=%s: %s", external_id, exc
        )
        return None

    if not hits:
        return None
    return TEEEClient()._normalize_hit(hits[0])


async def _build_eepp_cache(state: str) -> dict[str, dict]:
    """Fetch all EEPP offers for the given state and index them by external_id.

    Called at most once per state per script run so that multiple sampled
    rows from the same state share a single HTTP round-trip.
    """
    async with httpx.AsyncClient(timeout=float(settings.SCRAPER_TIMEOUT)) as client:
        eepp = EEPPClient(client=client)
        if state == "postulacion":
            offers = await eepp.fetch_postulacion()
        elif state == "evaluacion":
            offers = await eepp.fetch_evaluacion()
        else:
            offers = await eepp.fetch_all()
    return {o["external_id"]: o for o in offers if o.get("external_id")}


async def _check(
    session: AsyncSession,
    sample_size: int,
    sampling: str,
    source_filter: str | None,
) -> int:
    """Run the integrity check. Returns the total count of drifted fields."""
    if sampling == "proportional":
        rows = await _sample_proportional(session, sample_size, source_filter)
    else:
        rows = await _sample_random(session, sample_size, source_filter)

    LOGGER.info(
        "Sampled %d row(s) for integrity check (sampling=%s source=%s)",
        len(rows),
        sampling,
        source_filter or "all",
    )

    eepp_cache: dict[str, dict[str, dict]] = {}
    drift_count = 0

    for row in rows:
        job_offer_id = row.job_offer_id
        source = row.source
        external_id = row.external_id
        state = row.state

        if source == "TEEE":
            api_offer = await _fetch_teee_offer(external_id, state)
        elif source == "EEPP":
            if state not in eepp_cache:
                LOGGER.info("Fetching EEPP offers for state=%s", state)
                eepp_cache[state] = await _build_eepp_cache(state)
            api_offer = eepp_cache[state].get(external_id)
        else:
            LOGGER.warning(
                "Unsupported source %r — skipping job_offer_id=%s",
                source,
                job_offer_id,
            )
            continue

        if api_offer is None:
            LOGGER.warning(
                "Offer not found in upstream API — "
                "job_offer_id=%s source=%s external_id=%s state=%s "
                "(offer may have been removed or is no longer active in API)",
                job_offer_id,
                source,
                external_id,
                state,
            )
            drift_count += 1
            continue

        for field in _COMPARE_FIELDS:
            db_val = _normalize(field, getattr(row, field, None))
            api_val = _normalize(field, api_offer.get(field))

            if db_val is None and api_val is None:
                continue  # null == null is not drift

            if db_val != api_val:
                LOGGER.warning(
                    "Drift detected — "
                    "job_offer_id=%s source=%s external_id=%s "
                    "field=%s db=%r api=%r",
                    job_offer_id,
                    source,
                    external_id,
                    field,
                    db_val,
                    api_val,
                )
                drift_count += 1

    return drift_count


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Sample-based integrity check for job_offers",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        metavar="N",
        help="Number of rows to sample (default: 20)",
    )
    parser.add_argument(
        "--sampling",
        choices=["proportional", "random"],
        default="proportional",
        help=(
            "proportional: stratified by state distribution (default); "
            "random: uniform random sample"
        ),
    )
    parser.add_argument(
        "--source",
        choices=["TEEE", "EEPP"],
        default=None,
        help="Restrict sampling to a single source (default: both)",
    )
    args = parser.parse_args()

    async with get_session() as session:
        drift = await _check(
            session,
            sample_size=args.sample_size,
            sampling=args.sampling,
            source_filter=args.source,
        )

    if drift > 0:
        LOGGER.warning(
            "Integrity check FAILED — %d drifted field(s) detected", drift
        )
        return 1

    LOGGER.info("Integrity check PASSED — no drift detected")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
