# Sprint 3.8 — Load & Logging Fixes

Goal
----
Reduce operational friction caused by the `scripts/load_teee.py` pipeline by fixing runtime failures (asyncpg parameter limits) and preventing huge error traces from flooding terminals and CI logs.

Background
----------
Recent changes extended the canonical model and added optional fields used in the fingerprint. During large batch dry-runs the multi-row INSERT generated too many bound parameters and asyncpg raised `the number of query arguments cannot exceed 32767`. In addition, SQLAlchemy/asyncpg were dumping the full SQL and parameter lists into the terminal, producing unreadable logs.

Work items
----------
- Compute insert chunk size dynamically based on number of params per row to guarantee the per-statement parameter count stays below the asyncpg limit.
- Add a defensive schema check in the upsert path to detect missing new columns (`ministry`, `start_date`, `close_date`, `conv_type`) and fail fast with a clear message recommending `alembic upgrade head`.
- Silence noisy `sqlalchemy`/`asyncpg` logger emitters during loader runs to avoid large parameter dumps on error.
- Capture full exception tracebacks into time-stamped log files under `logs/loader_error_*.log` and emit a concise terminal message pointing to that file.
- Add an informational log when chunking is activated so operators can tune batch sizes if desired.

Acceptance criteria
-------------------
- `PYTHONPATH=. .venv/bin/python scripts/load_teee.py --dry-run --state all --batch 10` completes without a terminal flood on failure; any error references a `logs/loader_error_*.log` file.
- Dry-run that previously failed due to parameter limits completes successfully and reports the number of rows it would have upserted.
- The logs include an INFO message indicating chunk size when computed dynamically.
- If the target DB lacks expected new columns, the process exits with a clear RuntimeError message instructing to run migrations.

Testing
-------
- Unit test for chunk-size computation given different `rows` shapes.
- Integration smoke test: run loader with `--batch 10` against a test DB and assert no InterfaceError is raised and the process rolls back in dry-run.

Operational notes
-----------------
- When running in CI or production, ensure `DATABASE_URL` points to a DB where Alembic migrations have been applied.
- Logs are written to `logs/`; consider rotating or shipping them to persistent storage if runner keeps state between runs.

Run commands
------------
```bash
PYTHONPATH=. .venv/bin/python scripts/load_teee.py --dry-run --state all --batch 10
``` 

References
----------
- Asyncpg parameter limit: asyncpg implementation details
- Related code: `src/database/repository.py`, `scripts/load_teee.py`
