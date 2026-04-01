"""One-time script to create all tables in the configured database.

Run this once against a fresh Neon database before executing the pipeline:

    PYTHONPATH=. DATABASE_URL='postgresql+asyncpg://...' uv run python scripts/init_db.py
"""

from __future__ import annotations

import asyncio
import logging

from src.database.models import Base
from src.database.session import get_engine
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)


async def main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        # Create tables
        await conn.run_sync(Base.metadata.create_all)
        # Enable the unaccent extension for diacritic-insensitive searches
        # Note: requires superuser or appropriate privileges in the DB
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent;"))
    LOGGER.info("Tables created (or already exist).")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
