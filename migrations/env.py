"""Alembic environment for eepp project.

This `env.py` loads the project's SQLAlchemy `Base.metadata` as
`target_metadata` and provides a helper to convert an async DSN
(postgresql+asyncpg://) to a sync DSN (postgresql+psycopg://) so Alembic
can run using a synchronous engine.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# Import the project's metadata
try:
    from src.database.models import Base
except Exception:
    # Avoid raising on import-time side-effects during autogenerate
    Base = None  # type: ignore

target_metadata = Base.metadata if Base is not None else None


def get_url() -> str | None:
    url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        return None
    # Convert asyncpg URL to a sync psycopg URL for Alembic operations
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    return url


def run_migrations_online() -> None:
    url = get_url()
    if url is None:
        raise RuntimeError("DATABASE_URL is not set for Alembic migrations")

    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    url = get_url()
    if url is None:
        raise RuntimeError("DATABASE_URL is not set for Alembic offline migrations")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# ensure project root is on sys.path so imports like `src.*` work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import application metadata and settings
try:
    from src.database.models import Base
    from src.core.config import settings

    target_metadata = Base.metadata
except Exception:
    # Fallback to None if imports fail; useful for isolated alembic operations
    target_metadata = None

# Prefer DATABASE_URL environment variable; fall back to alembic.ini value
# and finally to project settings if available.
db_url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if not db_url and "settings" in globals():
    try:
        db_url = settings.DATABASE_URL
    except Exception:
        db_url = None

# Convert async driver URL to sync driver URL for Alembic (asyncpg -> psycopg)
if db_url and db_url.startswith("postgresql+asyncpg"):
    db_url_sync = db_url.replace("postgresql+asyncpg", "postgresql", 1)
else:
    db_url_sync = db_url

if db_url_sync:
    config.set_main_option("sqlalchemy.url", db_url_sync)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
