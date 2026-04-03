"""CLI helper to fetch TEEE offers and persist them in Neon.

Usage:
    PYTHONPATH=. python scripts/load_teee.py [--state STATE,...] [--batch N] [--dry-run] [--out file.json]

Behavior:
  - By default the script writes validated offers to the DB configured by
    `DATABASE_URL` (via `src.core.config`). Use `--dry-run` to exercise the
    full flow without committing the transaction.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from src.core.schemas import JobOfferSchema
from src.database.repository import upsert_job_offers
from src.database.session import get_session
from src.ingestion.teee_client import TEEEClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
LOGGER = logging.getLogger(__name__)


# Fields accepted by JobOfferSchema (used to filter normalized dicts)
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


def _to_schema(raw: Dict[str, Any]) -> JobOfferSchema | None:
    payload = {k: v for k, v in raw.items() if k in _SCHEMA_FIELDS}
    try:
        return JobOfferSchema.model_validate(payload)
    except ValidationError as exc:
        LOGGER.warning("Validation failed for offer (fingerprint=%s): %s", raw.get("fingerprint"), exc)
        return None


async def _main(batch: int, out: Optional[Path], states: Optional[List[str]] = None, dry_run: bool = False) -> None:
    client = TEEEClient()
    results: List[Dict[str, Any]] = []

    states = states or ["all"]
    if "all" in states:
        results.extend(await client.fetch_all())
    else:
        tasks = [asyncio.create_task(client._fetch_state(st, size=batch)) for st in states]
        chunks = await asyncio.gather(*tasks)
        for chunk in chunks:
            results.extend(chunk)

    LOGGER.info("Fetched %d offers from TEEE (states=%s)", len(results), states)

    if out:
        with out.open("w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        LOGGER.info("Wrote results to %s", out)

    # Validate and convert to schemas
    schemas: List[JobOfferSchema] = []
    for raw in results:
        s = _to_schema(raw)
        if s is not None:
            schemas.append(s)

    LOGGER.info("Validated %d/%d offers for DB write", len(schemas), len(results))
    if not schemas:
        LOGGER.info("No valid offers to write; exiting.")
        return

    # Upsert into DB; when dry_run is True, rollback instead of committing.
    async with get_session() as session:
        try:
            count = await upsert_job_offers(session, schemas)
            if dry_run:
                await session.rollback()
                LOGGER.info("Dry run enabled — rolled back. Would have upserted %d row(s)", count)
            else:
                await session.commit()
                LOGGER.info("Committed %d row(s) to DB", count)
        except Exception:
            LOGGER.exception("Failed during DB write")
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Load TEEE offers")
    parser.add_argument(
        "--state",
        "--estado",
        dest="states",
        type=str,
        default="all",
        help="Comma-separated list of states: postulacion,evaluacion,finalizadas or 'all'",
    )
    parser.add_argument("--batch", "--size", dest="batch", type=int, default=1000, help="Batch size to request from TEEE (per page)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="When present, perform upsert but rollback instead of commit")
    parser.add_argument("--out", type=Path, help="Write JSON output to file")

    args = parser.parse_args()

    # Parse comma-separated states into a list and validate values
    raw_states = args.states or "all"
    states_list = [s.strip() for s in raw_states.split(",") if s.strip()]
    valid = {"postulacion", "evaluacion", "finalizadas", "all"}
    for s in states_list:
        if s not in valid:
            parser.error(f"Invalid state: {s}. Allowed: postulacion,evaluacion,finalizadas,all")

    # If 'all' present, treat as a special value handled by _main
    asyncio.run(_main(args.batch, args.out, states_list, args.dry_run))


if __name__ == "__main__":
    main()
