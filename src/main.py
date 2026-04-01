"""Pipeline entry point: fetch EEPP offers, validate, upsert to Neon.

Usage:

    # Fetch from live EEPP and upsert to Neon:
    PYTHONPATH=. DATABASE_URL='postgresql+asyncpg://...' uv run python -m src.main

    # Dry run (fetch from EEPP but do NOT commit to DB):
    PYTHONPATH=. DATABASE_URL='...' uv run python -m src.main --dry-run
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from pydantic import ValidationError

from src.core.schemas import JobOfferSchema
from src.database.repository import upsert_job_offers
from src.database.session import get_session
from src.ingestion.eepp_client import EEPPClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

# Fields produced by EEPPClient that map to JobOfferSchema
_SCHEMA_FIELDS = {
    "source",
    "state",
    "title",
    "institution",
    "region",
    "city",
    "url",
    "salary_bruto",
    "external_id",
    "fingerprint",
    "raw_data",
}


def _to_schema(raw: dict[str, Any]) -> JobOfferSchema | None:
    """Validate a normalized offer dict into a JobOfferSchema.

    Returns None and logs a warning if validation fails.
    """
    payload = {k: v for k, v in raw.items() if k in _SCHEMA_FIELDS}
    try:
        return JobOfferSchema.model_validate(payload)
    except ValidationError as exc:
        LOGGER.warning("Validation failed for offer (fingerprint=%s): %s", raw.get("fingerprint"), exc)
        return None


async def run_pipeline(*, dry_run: bool = False) -> None:
    """Fetch EEPP offers, validate, and upsert to Neon.

    Args:
        dry_run: When True, skips the database commit. Useful for testing
                 the fetch and validation steps without writing to Neon.
    """
    LOGGER.info("Pipeline started (dry_run=%s)", dry_run)

    # 1. Fetch
    client = EEPPClient()
    raw_offers = await client.fetch_all()

    fetched = len(raw_offers)
    LOGGER.info("Fetched %d offers from EEPP", fetched)

    # 2. Validate
    schemas: list[JobOfferSchema] = []
    for raw in raw_offers:
        schema = _to_schema(raw)
        if schema is not None:
            schemas.append(schema)

    valid = len(schemas)
    invalid = fetched - valid
    if invalid:
        LOGGER.warning("%d offer(s) failed validation and were skipped", invalid)
    LOGGER.info("%d offers passed validation", valid)

    if dry_run:
        LOGGER.info("Dry run — skipping database write.")
        return

    # 3. Upsert + commit
    try:
        async with get_session() as session:
            upserted = await upsert_job_offers(session, schemas)
            await session.commit()
    except Exception:
        LOGGER.exception("Pipeline failed during database write")
        raise

    LOGGER.info("Upserted %d row(s) to Neon.", upserted)
    LOGGER.info("Pipeline complete.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(run_pipeline(dry_run=dry_run))
