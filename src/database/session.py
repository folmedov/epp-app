"""Async database session management for the project.

This module provides the minimal database connectivity layer required to
initialize an async SQLAlchemy engine, create sessions, and validate that the
configured database is reachable.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings


LOGGER = logging.getLogger(__name__)


engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def get_engine() -> AsyncEngine:
    """Return the shared async database engine."""

    return engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared async session factory."""

    return SessionFactory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session from the shared factory."""

    async with SessionFactory() as session:
        yield session


async def check_database_connection() -> None:
    """Validate that the configured database is reachable."""

    LOGGER.info("Checking database connectivity")
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


__all__ = [
    "SessionFactory",
    "check_database_connection",
    "engine",
    "get_engine",
    "get_session",
    "get_session_factory",
]