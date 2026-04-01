"""One-time script to create all tables in the configured database.

Run this once against a fresh Neon database before executing the pipeline:

    PYTHONPATH=. DATABASE_URL='postgresql+asyncpg://...' uv run python scripts/init_db.py
"""

from __future__ import annotations

import asyncio
import logging

from src.database.models import Base
from src.database.session import get_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)


async def main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    LOGGER.info("Tables created (or already exist).")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
