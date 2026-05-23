"""Alembic environment for eepp project.

This `env.py` loads the project's SQLAlchemy `Base.metadata` as
`target_metadata` and provides a helper to convert an async DSN
(postgresql+asyncpg://) to a sync DSN (postgresql+psycopg://) so Alembic
can run using a synchronous engine.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

# Load .env from the project root so DATABASE_URL (and other vars) are
# available without requiring the user to export them manually.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Ensure the project root is on sys.path so imports like `src.*` work
# without requiring PYTHONPATH to be set manually.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Alembic Config object
config = context.config

# Interpret the config file for Python logging.
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
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
