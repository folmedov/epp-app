"""Purge old rows from the notification_queue table.

Cleanup policy:
  - 'sent' rows with sent_at older than --sent-days (default 30) are deleted.
  - 'pending' rows with created_at older than --pending-days (default 7) are deleted.

Usage:
    PYTHONPATH=. python scripts/cleanup_notification_queue.py [--dry-run]
                        [--sent-days DAYS] [--pending-days DAYS]

Exit codes:
    0   Always (DB errors exit non-zero naturally).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

# ── SQL statements ────────────────────────────────────────────────────────────

_DELETE_SENT_SQL = text("""
    DELETE FROM notification_queue
    WHERE  status = 'sent'
      AND  sent_at < NOW() - CAST(:days || ' days' AS INTERVAL)
""")

_DELETE_PENDING_SQL = text("""
    DELETE FROM notification_queue
    WHERE  status = 'pending'
      AND  created_at < NOW() - CAST(:days || ' days' AS INTERVAL)
""")

_COUNT_SENT_SQL = text("""
    SELECT COUNT(*) AS cnt
    FROM   notification_queue
    WHERE  status = 'sent'
      AND  sent_at < NOW() - CAST(:days || ' days' AS INTERVAL)
""")

_COUNT_PENDING_SQL = text("""
    SELECT COUNT(*) AS cnt
    FROM   notification_queue
    WHERE  status = 'pending'
      AND  created_at < NOW() - CAST(:days || ' days' AS INTERVAL)
""")


# ── Main logic ────────────────────────────────────────────────────────────────

async def run(dry_run: bool, sent_days: int, pending_days: int) -> None:
    engine = get_engine()
    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                await _process(session, dry_run, sent_days, pending_days)
    finally:
        await engine.dispose()


async def _process(
    session: AsyncSession,
    dry_run: bool,
    sent_days: int,
    pending_days: int,
) -> None:
    if dry_run:
        sent_result = await session.execute(_COUNT_SENT_SQL, {"days": sent_days})
        pending_result = await session.execute(_COUNT_PENDING_SQL, {"days": pending_days})
        sent_count: int = sent_result.fetchone().cnt
        pending_count: int = pending_result.fetchone().cnt

        if sent_count == 0 and pending_count == 0:
            LOGGER.info("[dry-run] Nothing to clean up.")
        else:
            LOGGER.info(
                "[dry-run] Would delete %d sent row(s) older than %d day(s) "
                "and %d pending row(s) older than %d day(s).",
                sent_count, sent_days,
                pending_count, pending_days,
            )
        return

    # Step 1: delete old sent rows
    sent_result = await session.execute(_DELETE_SENT_SQL, {"days": sent_days})
    deleted_sent: int = sent_result.rowcount

    # Step 2: delete orphaned pending rows
    pending_result = await session.execute(_DELETE_PENDING_SQL, {"days": pending_days})
    deleted_pending: int = pending_result.rowcount

    if deleted_sent == 0 and deleted_pending == 0:
        LOGGER.info("Nothing to clean up.")
    else:
        LOGGER.info(
            "Cleanup complete. Deleted %d sent row(s) older than %d day(s) "
            "and %d pending row(s) older than %d day(s).",
            deleted_sent, sent_days,
            deleted_pending, pending_days,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purge old rows from the notification_queue table.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Count rows that would be deleted without actually deleting them.",
    )
    parser.add_argument(
        "--sent-days",
        dest="sent_days",
        type=int,
        default=30,
        metavar="DAYS",
        help="Retention window for 'sent' rows in days (default: 30).",
    )
    parser.add_argument(
        "--pending-days",
        dest="pending_days",
        type=int,
        default=7,
        metavar="DAYS",
        help="Retention window for 'pending' rows in days (default: 7).",
    )
    args = parser.parse_args()

    if args.dry_run:
        LOGGER.info("Running in DRY-RUN mode — no rows will be deleted.")

    asyncio.run(run(args.dry_run, args.sent_days, args.pending_days))


if __name__ == "__main__":
    main()
