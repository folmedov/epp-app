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


def _build_engine() -> AsyncEngine:
    """Build the async engine, stripping asyncpg-incompatible query params.

    asyncpg does not accept ``sslmode`` or ``channel_binding`` as URL query
    parameters. SSL is enabled instead via ``connect_args``.
    """
    from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

    parsed = urlparse(settings.DATABASE_URL)
    qs = parse_qs(parsed.query)
    needs_ssl = qs.pop("sslmode", [None])[0] in ("require", "verify-ca", "verify-full")
    qs.pop("channel_binding", None)
    clean_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

    connect_args: dict = {"ssl": True} if needs_ssl else {}
    return create_async_engine(
        clean_url,
        echo=False,
        future=True,
        connect_args=connect_args,
        # Neon (and most managed Postgres) closes idle connections after a few
        # minutes.  pool_pre_ping issues a cheap SELECT 1 before handing out a
        # pooled connection; stale connections are discarded transparently.
        # pool_recycle proactively replaces connections older than 5 minutes so
        # they are never handed out in a already-closed state.
        pool_pre_ping=True,
        pool_recycle=300,
    )


engine: AsyncEngine = _build_engine()

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