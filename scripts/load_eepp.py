"""CLI helper to fetch EEPP offers and persist them in Neon.

Usage:
    PYTHONPATH=. python scripts/load_eepp.py [--state STATE,...] [--batch N] [--dry-run] [--out file.json]

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
from src.database.repository import upsert_job_offers, upsert_job_offer_sources
from src.database.session import get_session
from src.ingestion.eepp_client import EEPPClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
LOGGER = logging.getLogger(__name__)

# Prevent SQLAlchemy/DB drivers from emitting full SQL + parameters to stdout
for noisy in ("sqlalchemy.engine", "sqlalchemy.engine.Engine", "asyncpg", "sqlalchemy.pool"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


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
    "external_id_generated",
    "external_id_fallback_type",
    "content_fingerprint",
    "fingerprint",
    "cross_source_key",
    "raw_data",
    "ministry",
    "start_date",
    "close_date",
    "conv_type",
}


def _to_schema(raw: Dict[str, Any]) -> JobOfferSchema | None:
    payload = {k: v for k, v in raw.items() if k in _SCHEMA_FIELDS}
    try:
        return JobOfferSchema.model_validate(payload)
    except ValidationError as exc:
        LOGGER.warning("Validation failed for offer (fingerprint=%s): %s", raw.get("fingerprint"), exc)
        return None


async def _run_upsert(
    session_ctx,
    schemas: List[JobOfferSchema],
    mode: str,
    dry_run: bool,
    label: str,
) -> tuple[int, int]:
    """Run a single upsert+source write within a managed session.

    Returns (offer_count, source_count).
    """
    import datetime
    from pathlib import Path
    async with session_ctx as session:
        try:
            fingerprint_to_id = await upsert_job_offers(session, schemas, mode=mode)
            source_count = await upsert_job_offer_sources(session, schemas, fingerprint_to_id)
            if dry_run:
                await session.rollback()
                LOGGER.info(
                    "Dry run — rolled back %d offer(s), %d source row(s) [%s]",
                    len(fingerprint_to_id), source_count, label,
                )
            else:
                await session.commit()
                LOGGER.info(
                    "Committed %d offer(s) and %d source row(s) to DB [%s]",
                    len(fingerprint_to_id), source_count, label,
                )
            return len(fingerprint_to_id), source_count
        except Exception as exc:
            import traceback
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
            log_path = logs_dir / f"loader_error_{ts}.log"
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            LOGGER.error("DB write failed: %s. Full traceback saved to %s", exc, log_path)
            raise SystemExit(1)


async def _main(
    states: Optional[List[str]],
    out: Optional[Path],
    dry_run: bool = False,
    initial: bool = False,
) -> None:
    client = EEPPClient()
    results: List[Dict[str, Any]] = []

    if initial:
        # Initial bulk load: fetch and commit each state as a SEPARATE transaction
        # in ascending lifecycle order so that postulacion (loaded last) wins
        # any fingerprint conflict.
        LOGGER.info("Running in INITIAL mode — loading states: evaluacion → postulacion")
        total_offers = total_sources = 0
        for state_name, fetch_coro in [
            ("evaluacion", client.fetch_evaluacion()),
            ("postulacion", client.fetch_postulacion()),
        ]:
            state_results = await fetch_coro

            if out:
                results.extend(state_results)

            state_schemas: List[JobOfferSchema] = []
            for raw in state_results:
                s = _to_schema(raw)
                if s is not None:
                    state_schemas.append(s)

            LOGGER.info(
                "state=%s: fetched %d, validated %d",
                state_name, len(state_results), len(state_schemas),
            )
            if not state_schemas:
                continue

            n_offers, n_sources = await _run_upsert(
                get_session(), state_schemas, mode="initial", dry_run=dry_run, label=state_name
            )
            total_offers += n_offers
            total_sources += n_sources

        LOGGER.info("Initial load complete: %d offer(s), %d source row(s) total", total_offers, total_sources)

        if out:
            with out.open("w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=2, default=str)
            LOGGER.info("Wrote raw results to %s", out)
        return

    # Periodic update mode (default) ─────────────────────────────────────────

    states = states or ["all"]
    if "all" in states:
        results.extend(await client.fetch_all())
    else:
        tasks = []
        for st in states:
            if st == "postulacion":
                tasks.append(asyncio.create_task(client.fetch_postulacion()))
            elif st == "evaluacion":
                tasks.append(asyncio.create_task(client.fetch_evaluacion()))
            else:
                LOGGER.warning("Unknown EEPP state %r — skipping", st)
        chunks = await asyncio.gather(*tasks)
        for chunk in chunks:
            results.extend(chunk)

    LOGGER.info("Fetched %d offers from EEPP (states=%s)", len(results), states)

    if out:
        with out.open("w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2, default=str)
        LOGGER.info("Wrote results to %s", out)

    schemas: List[JobOfferSchema] = []
    for raw in results:
        s = _to_schema(raw)
        if s is not None:
            schemas.append(s)

    LOGGER.info("Validated %d/%d offers for DB write", len(schemas), len(results))
    if not schemas:
        LOGGER.info("No valid offers to write; exiting.")
        return

    await _run_upsert(get_session(), schemas, mode="periodic", dry_run=dry_run, label=",".join(states))


def main() -> None:
    parser = argparse.ArgumentParser(description="Load EEPP offers")
    parser.add_argument(
        "--state",
        "--estado",
        dest="states",
        type=str,
        default="all",
        help="Comma-separated list of states: postulacion,evaluacion or 'all'",
    )
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Perform upsert but rollback instead of commit")
    parser.add_argument("--out", type=Path, help="Write JSON output to file")
    parser.add_argument(
        "--initial",
        dest="initial",
        action="store_true",
        help=(
            "Initial bulk load mode: fetch states in lifecycle order "
            "(evaluacion → postulacion) and commit each as a separate "
            "transaction with always-overwrite semantics. "
            "The --state flag is ignored when --initial is set."
        ),
    )
    args = parser.parse_args()

    states = [s.strip() for s in args.states.split(",") if s.strip()]
    asyncio.run(_main(states=states, out=args.out, dry_run=args.dry_run, initial=args.initial))


if __name__ == "__main__":
    main()
