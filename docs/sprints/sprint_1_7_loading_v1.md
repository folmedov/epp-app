# Sprint 1.7 — Loading: Upsert to PostgreSQL (Neon)

## Objective
Implement the persistence layer that takes a list of validated `JobOfferSchema` objects
and writes them to the `job_offers` table using an upsert strategy based on `fingerprint`.

Each pipeline run should reflect the current state of the portal as faithfully as possible,
including updating mutable fields such as `state`, `url`, `salary_bruto`, and `raw_data`.

---

## Scope

- Fix `fingerprint` constraint in `src/database/models.py`: change `index=True` to `unique=True`
- New module: `src/database/repository.py` with `upsert_job_offers`
- New test file: `tests/test_repository.py`
- No changes to `schemas.py`, `transformers.py`, or ingestion code
- No real Neon connection required for tests

---

## Prerequisite Model Fix

`JobOffer.fingerprint` in `models.py` must be `unique=True` for `ON CONFLICT` to work:

```python
fingerprint: Mapped[str | None] = mapped_column(
    String(32), nullable=True, unique=True, index=True
)
```

---

## Module: `src/database/repository.py`

### Public API

```python
async def upsert_job_offers(
    session: AsyncSession,
    offers: list[JobOfferSchema],
) -> int:
    ...
```

Returns the number of rows inserted or updated.

### Upsert Rules

Conflict target: `fingerprint`

| Field | On insert | On conflict (update) |
|:---|:---|:---|
| `id` | `uuid4()` | preserve |
| `fingerprint` | from schema | preserve |
| `external_id` | from schema | preserve |
| `source` | from schema | preserve |
| `title` | from schema | preserve |
| `institution` | from schema | preserve |
| `region` | from schema | preserve |
| `city` | from schema | preserve |
| `created_at` | server default | preserve |
| `state` | from schema | **update** |
| `url` | from schema | **update** |
| `salary_bruto` | from schema | **update** |
| `raw_data` | from schema | **update** |
| `updated_at` | server default | **update** to `now()` |

### Implementation Notes

- Use `insert` from `sqlalchemy.dialects.postgresql` with `.on_conflict_do_update`
- Conflict target: `index_elements=["fingerprint"]`
- `set_` dict on conflict must include: `state`, `url`, `salary_bruto`, `raw_data`, `updated_at`
- `updated_at` on conflict: use `func.now()`
- Convert `JobOfferSchema` to dict via `.model_dump(exclude={"id", "created_at", "updated_at"})`
  before passing to the insert statement; `id` is generated via column `default=uuid4`
- Execute as a single bulk statement, not one INSERT per offer
- Call `await session.flush()` after execute (commit is the caller's responsibility)

### Offers with `fingerprint = None`

Records without a fingerprint must be skipped and logged with a warning.
Do not attempt to insert them.

---

## Tests: `tests/test_repository.py`

Test isolation: mock `AsyncSession.execute` and `AsyncSession.flush`.
No real database connection required.

Required test cases:

1. `test_upsert_returns_correct_rowcount`
   - Pass a list of 3 valid schemas, mock execute to return a result with `rowcount=3`
   - Assert return value is 3

2. `test_upsert_skips_offers_without_fingerprint`
   - Pass a mix of 2 valid + 1 with `fingerprint=None`
   - Assert only 2 rows are sent to execute (the None one is filtered before execute)

3. `test_upsert_empty_list_returns_zero`
   - Pass an empty list
   - Assert execute is never called and return value is 0

---

## Definition of Done

- [ ] `fingerprint` column is `unique=True` in `models.py`
- [ ] `src/database/repository.py` exists with `upsert_job_offers`
- [ ] `tests/test_repository.py` passes (3 tests minimum)
- [ ] All existing tests still pass
- [ ] `requirement.md` updated to mark 1.7 complete
