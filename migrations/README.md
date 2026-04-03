Alembic migrations for eepp

This folder contains Alembic environment for the project. Use the
`alembic` CLI to create and run migrations. The `env.py` file converts an
asyncpg DSN to a sync psycopg DSN so Alembic can operate against the
database using SQLAlchemy's synchronous engine.

Typical usage:

- Set `DATABASE_URL` to your database URL (e.g. postgresql+asyncpg://...)
- Run: `alembic revision --autogenerate -m "create initial tables"`
- Run: `alembic upgrade head`
