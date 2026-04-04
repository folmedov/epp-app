# Sprint 3.10 — Populate job_offer_sources

Goal
----
During the `load_teee` upsert flow, write one row per ingested offer into
`job_offer_sources` and resolve the `job_offer_id` FK pointing to the canonical
`job_offers` row. After this sprint every TEEE load is fully auditable: the raw
Elasticsearch payload, the source-native external ID, and the original state are
preserved independently of any future changes to the canonical row.

Background
----------
`job_offer_sources` was introduced in Sprint 3.1 and the ORM model / migration
(`0003_add_job_offer_sources`) already exist. The table has been empty because no
loader wrote to it. The canonical upsert in `repository.py` operates exclusively on
`job_offers` and strips `external_id` and `raw_data` before inserting (those fields
are excluded from `allowed_cols`).

The challenge is that the source row needs the `UUID` of the canonical `job_offers`
row — the `id` that was either just inserted or already existed. PostgreSQL's
`INSERT … ON CONFLICT DO UPDATE … RETURNING id` returns the id in both cases, so
we can collect the mapping `fingerprint → job_offer_id` from the upsert result and
use it immediately to write `job_offer_sources`.

The `UNIQUE(source, external_id)` constraint on `job_offer_sources` (where
`external_id IS NOT NULL`) means source upserts must use `ON CONFLICT DO UPDATE`
as well, so re-running the loader is idempotent.

Design decisions
----------------
### Where the source upsert lives
A new function `upsert_job_offer_sources()` is added to `repository.py`. It is
called by the loader immediately after `upsert_job_offers()`, within the same
database session and transaction, so both sets of writes are committed atomically.

### Returning job_offer_id from the job_offers upsert
`upsert_job_offers()` is updated to return `dict[str, UUID]` — a mapping of
`fingerprint → job_offer_id` — instead of a plain integer count. The loader still
logs the count; callsites that only care about the count use `len(mapping)`.

### ON CONFLICT for job_offer_sources
Conflict key: `(source, external_id)` when `external_id IS NOT NULL`; for rows
with `external_id IS NULL` there is no unique constraint so every load inserts a
new row (the ES `_elastic_id` in `raw_data` provides traceability). The update
on conflict refreshes `raw_data`, `original_state`, `job_offer_id`, and
`ingested_at`.

### Chunking
The same dynamic chunk-size logic used in `upsert_job_offers()` is applied to the
source upsert to stay within asyncpg's 32 767 parameter limit.

Work items
----------
- **`repository.py` — change `upsert_job_offers()` return type**: collect the
  `RETURNING id, fingerprint` result set and build a `fingerprint → UUID` mapping.
  Return `dict[str, UUID]` instead of `int`.
- **`repository.py` — add `upsert_job_offer_sources()`**: accepts
  `list[JobOfferSchema]` + `fingerprint_to_id: dict[str, UUID]`, builds source rows
  (fields: `source`, `external_id`, `raw_data`, `original_state`, `job_offer_id`),
  chunked insert with `ON CONFLICT (source, external_id) DO UPDATE` (skip conflict
  resolution for rows where `external_id IS NULL`).
- **`schemas.py` — add `JobOfferSourceSchema`**: Pydantic DTO mirroring the
  `job_offer_sources` ORM model. Used by the repository to validate source rows
  before insert.
- **`scripts/load_teee.py` — call `upsert_job_offer_sources()`**: after
  `upsert_job_offers()` resolves the mapping, pass `schemas` + mapping to
  `upsert_job_offer_sources()`. Log source row count separately.
- **`repository.py` — update `__all__`**: export `upsert_job_offer_sources`.

Files changed
-------------
| File | Change |
|:---|:---|
| `src/database/repository.py` | `upsert_job_offers()` returns `dict[str, UUID]`; new `upsert_job_offer_sources()` |
| `src/core/schemas.py` | New `JobOfferSourceSchema`; add to `__all__` |
| `scripts/load_teee.py` | Call `upsert_job_offer_sources()`; update log messages |

No new migration is required — `job_offer_sources` schema is already current.

Key contracts
-------------

```python
# repository.py

async def upsert_job_offers(
    session: AsyncSession,
    offers: list[JobOfferSchema],
) -> dict[str, UUID]:
    """Returns fingerprint → job_offer_id for every row inserted or updated."""
    ...

async def upsert_job_offer_sources(
    session: AsyncSession,
    offers: list[JobOfferSchema],
    fingerprint_to_id: dict[str, UUID],
) -> int:
    """Upsert one source row per offer.  Returns the number of rows affected."""
    ...
```

```python
# schemas.py

class JobOfferSourceSchema(BaseModel):
    id: UUID | None = None
    job_offer_id: UUID | None = None
    source: str
    external_id: str | None = None
    raw_data: dict[str, Any]
    original_state: str | None = None
    ingested_at: datetime | None = None

    model_config = ConfigDict(extra="forbid", from_attributes=True)
```

Acceptance criteria
-------------------
- After `load_teee --state all`, `SELECT count(*) FROM job_offer_sources` equals
  the number of unique ingested offers (one row per offer per run for offers with
  `external_id IS NULL`; exactly one row per `(source, external_id)` pair for offers
  with a stable `external_id`).
- All `job_offer_sources.job_offer_id` values are non-NULL and reference a valid row
  in `job_offers`.
- Re-running the loader does not insert duplicate rows for offers with a stable
  `external_id`; it updates `raw_data` and `ingested_at` on conflict instead.
- The loader commits both `job_offers` and `job_offer_sources` atomically — a failure
  in the source upsert rolls back the canonical upsert too.
- Dry-run mode (`--dry-run`) rolls back both tables, leaving them unchanged.

Testing
-------
- Unit test for `upsert_job_offers()` return type: given a list of schemas, the
  function returns a `dict` mapping fingerprint strings to `UUID` values.
- Unit test for `upsert_job_offer_sources()`: given a list of schemas and a
  fingerprint mapping, the correct rows are built and the `job_offer_id` FK is
  resolved.
- Unit test for `ON CONFLICT` idempotency: inserting the same `(source, external_id)`
  twice must produce exactly one row in `job_offer_sources`.
- Integration test: full `load_teee` flow against a test DB; assert
  `count(job_offer_sources) == count(job_offers)` (for TEEE-only loads).
