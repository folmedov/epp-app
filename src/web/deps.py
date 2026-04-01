"""FastAPI shared dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import SessionFactory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield an async DB session for use as a FastAPI dependency."""
    async with SessionFactory() as session:
        yield session
