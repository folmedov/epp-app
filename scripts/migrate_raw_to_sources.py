"""Backfill script: migrate `job_offers.raw_data` into `job_offer_sources`.

Usage:
    PYTHONPATH=. DATABASE_URL='postgresql+asyncpg://...' uv run python scripts/migrate_raw_to_sources.py [--dry-run] [--batch-size N]

This script is idempotent and uses `ON CONFLICT DO NOTHING` when inserting.
It will create the `job_offer_sources` table via `Base.metadata.create_all()` if it doesn't exist.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
import json

from sqlalchemy import text

from src.database.session import get_engine
from src.database.models import Base


async def main(dry_run: bool, batch_size: int) -> None:
    engine = get_engine()

    async with engine.connect() as conn:
        # Ensure tables exist
        await conn.run_sync(Base.metadata.create_all)

        # If the legacy `raw_data` column has already been removed, exit early
        col_exists_res = await conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='job_offers' AND column_name='raw_data')"
            )
        )
        has_raw_column = bool(col_exists_res.scalar() or False)
        if not has_raw_column:
            logging.info("Column job_offers.raw_data not present; nothing to migrate.")
            await engine.dispose()
            return

        # Count rows with raw_data
        count_res = await conn.execute(text("SELECT count(*) FROM job_offers WHERE raw_data IS NOT NULL"))
        total = int(count_res.scalar() or 0)
        logging.info("Found %d job_offers with raw_data", total)

        if total == 0:
            await engine.dispose()
            return

        if dry_run:
            sample = await conn.execute(text("SELECT id, source, external_id FROM job_offers WHERE raw_data IS NOT NULL ORDER BY id LIMIT 5"))
            rows = sample.fetchall()
            logging.info("Sample rows (dry-run): %s", rows)
            await engine.dispose()
            return

        inserted_total = 0
        offset = 0

        select_stmt = text(
            """
            SELECT id, source, external_id, raw_data, state, created_at
            FROM job_offers
            WHERE raw_data IS NOT NULL
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """
        )

        insert_stmt = text(
            """
            INSERT INTO job_offer_sources (id, job_offer_id, source, external_id, raw_data, original_state, ingested_at)
            VALUES (:id, :job_offer_id, :source, :external_id, :raw_data, :original_state, :ingested_at)
            ON CONFLICT (source, external_id) DO NOTHING
            """
        )

        while offset < total:
            # Fetch a batch of source rows to migrate
            res = await conn.execute(select_stmt, {"limit": batch_size, "offset": offset})
            rows = res.fetchall()
            if not rows:
                break

            batch_inserted = 0
            async with engine.begin() as batch_conn:
                for row in rows:
                    # row: (job_offer_id, source, external_id, raw_data, original_state, ingested_at)
                    # serialize raw_data to JSON string for safe binding with asyncpg
                    raw_val = row[3]
                    if raw_val is None:
                        raw_param = None
                    elif isinstance(raw_val, str):
                        raw_param = raw_val
                    else:
                        try:
                            raw_param = json.dumps(raw_val, ensure_ascii=False)
                        except Exception:
                            raw_param = json.dumps(str(raw_val), ensure_ascii=False)

                    params = {
                        "id": str(uuid.uuid4()),
                        "job_offer_id": row[0],
                        "source": row[1],
                        "external_id": row[2],
                        "raw_data": raw_param,
                        "original_state": row[4],
                        "ingested_at": row[5],
                    }
                    try:
                        res_ins = await batch_conn.execute(insert_stmt, params)
                        rc = getattr(res_ins, "rowcount", None) or 0
                        batch_inserted += rc
                    except Exception:
                        logging.exception("Insert failed for job_offer_id=%s", row[0])

            inserted_total += batch_inserted
            logging.info("Batch inserted %d rows (offset=%d)", batch_inserted, offset)
            offset += batch_size

        logging.info("Migration complete — total inserted: %d", inserted_total)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show counts and samples without inserting")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(main(dry_run=args.dry_run, batch_size=args.batch_size))
