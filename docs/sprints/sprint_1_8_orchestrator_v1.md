# Sprint 1.8 — Orchestrator: Pipeline Entry Point & Table Initialization

## Objective
Connect all Sprint 1 components into a runnable pipeline that fetches EEPP offers,
validates them, and persists them to Neon in a single execution.

Also provide a one-time script to create the `job_offers` table in Neon from the
existing SQLAlchemy models (no Alembic yet).

---

## Scope

- New script: `scripts/init_db.py` — creates tables in Neon via `Base.metadata.create_all`
- New module: `src/main.py` — async pipeline entry point
- No new tests required (the pipeline glues already-tested components)
- No changes to existing modules

---

## Script: `scripts/init_db.py`

Runs `Base.metadata.create_all` against the engine from `session.py`.
Must be executed once before any pipeline run against a fresh Neon database.

```
PYTHONPATH=. uv run python scripts/init_db.py
```

Logs success or failure. Does not drop or migrate existing tables.

---

## Module: `src/main.py`

### Pipeline flow

```
1. EEPPClient.fetch_all()          → list[dict[str, Any]]
2. JobOfferSchema(**offer)         → list[JobOfferSchema]   (skip invalid, log warnings)
3. upsert_job_offers(session, ...) → int (rows affected)
4. session.commit()
5. Log summary: fetched / valid / upserted
```

### Public API

```python
async def run_pipeline() -> None: ...

if __name__ == "__main__":
    asyncio.run(run_pipeline())
```

### Validation step (step 2)

Use `JobOfferSchema.model_validate(offer)` inside a try/except `ValidationError`.
Log a warning for each invalid offer and continue. Do not abort the pipeline.

Fields present in the raw dict from `EEPPClient` but absent from `JobOfferSchema`
must be excluded before validation (`extra="forbid"` is set on the schema).
Allowed fields to pass: `source`, `state`, `title`, `institution`, `region`, `city`,
`url`, `salary_bruto`, `external_id`, `fingerprint`, `raw_data`.

### Session management

Use `get_session()` from `src/database/session.py` as an async context manager.
Commit inside the context manager after a successful upsert.
On exception: log the error and re-raise (no silent failures).

### Logging

Configure basic logging at `INFO` level at the top of `main.py`.
Log at minimum:
- Number of offers fetched from EEPP
- Number of offers that passed validation
- Number of rows upserted
- Any validation errors (WARNING)
- Any pipeline-level errors (ERROR)

---

## Definition of Done

- [ ] `scripts/init_db.py` runs cleanly against a real Neon URL and creates the table
- [ ] `src/main.py` runs end-to-end and logs a summary
- [ ] At least one successful run against Neon confirmed (rows visible in the table)
- [ ] All existing tests still pass
- [ ] `requirement.md` updated to mark 1.8 complete
