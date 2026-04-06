# Sprint 3.16 — Tests & Data Integrity

## Goal

After this sprint the pipeline has two quality layers:

1. **Unit tests** covering the cross-source matching logic (canonical promotion
   and enrichment) and the state-priority CASE expressions in `repository.py`.
2. **Sample-based integrity check** (`scripts/integrity_check.py`) that
   re-fetches a small random subset of DB rows from the upstream APIs, compares
   key fields, logs any drift as `WARNING`, and exits with code `1` if any
   discrepancy is found.

---

## Background

The existing test suite covers schema validation, basic upsert counts, and
client normalization, but has no coverage for the two most complex pieces added
in Sprint 3.15:

- The cross-source matching branches in `upsert_job_offers()` — canonical
  promotion and enrichment updates.
- The `_state_priority()` CASE expression and the forward-only guard that
  prevents state regressions.

These are business-critical paths: a silent bug here would either corrupt
canonical ownership or allow state regressions that make the DB inconsistent
with live portals.

The integrity check complements automated tests by catching real-world drift:
cases where an upstream API silently changes a field value (e.g. corrects a
salary, reopens a closed offer) that the normal deduplication fingerprint would
not detect.

---

## Part 1 — Unit Tests

### Scope

All new tests go in `tests/test_repository.py`, following the existing
mock-based pattern (`AsyncMock` session, no real DB required).

### Test cases

#### Cross-source canonical promotion

| Test | Description |
|---|---|
| `test_cross_source_higher_authority_promotes` | TEEE row matched against EEPP canonical row: canonical fields in `set_` reflect TEEE values. |
| `test_cross_source_lower_authority_enriches` | EEPP row matched against TEEE canonical row: only enrichment fields (`gross_salary` COALESCE, `first_employment`, `vacancies`, `prioritized`) are written; canonical fields unchanged. |
| `test_cross_source_enrichment_skipped_when_all_null` | EEPP row with all four enrichment fields `None`: enrichment update is NOT appended. |
| `test_cross_source_promotion_state_forward_only` | TEEE promotes EEPP row but existing state is `evaluacion` and incoming is `postulacion`: stored state stays `evaluacion`. |
| `test_cross_source_promotion_state_advances` | TEEE promotes EEPP row with existing `postulacion` and incoming `evaluacion`: stored state updated to `evaluacion`. |

#### State-priority CASE logic

| Test | Description |
|---|---|
| `test_state_priority_initial_mode_always_overwrites` | `mode='initial'`: two rows with same fingerprint but different states; last write wins regardless of lifecycle order. |
| `test_state_priority_periodic_mode_forward_only` | `mode='periodic'`: incoming `postulacion` cannot overwrite stored `evaluacion`. |
| `test_state_priority_periodic_mode_advances` | `mode='periodic'`: incoming `finalizada` updates stored `evaluacion`. |
| `test_state_priority_same_stage_updates` | `mode='periodic'`: same state (`postulacion → postulacion`) triggers update (for URL / salary changes). |

### Approach

Mirror the existing `test_repository.py` style:
- Build `JobOfferSchema` instances with `_make_schema()`.
- Mock the `AsyncSession` with `AsyncMock`.
- Inspect the compiled SQLAlchemy statement or mock call args to assert
  correct branching behaviour.
- No real database connection needed.

---

## Part 2 — Sample-based Integrity Check

### Deliverable

`scripts/integrity_check.py` — standalone script, no server required.

### Sampling modes

The script supports two sampling modes, selectable via `--sampling`:

#### `proportional` (default)

Sample is stratified by `state` in proportion to the actual distribution in the
DB. If the DB contains 10 % `postulacion`, 20 % `evaluacion`, and 70 %
`finalizada`, a sample of 10 will contain 1, 2, and 7 rows from each bucket
respectively (rounded; any remainder is assigned to the largest bucket).

```
PYTHONPATH=. python scripts/integrity_check.py --sampling proportional --sample-size 20
```

**Rationale**: `finalizadas` are the majority of rows. Without stratification a
purely random sample would almost always consist entirely of `finalizadas`,
giving no signal about active offers that are far more likely to drift.

#### `random`

Completely uniform random sample across all rows, regardless of state. Useful
for unbiased statistical coverage and for checking the `finalizada` population
more thoroughly.

```
PYTHONPATH=. python scripts/integrity_check.py --sampling random --sample-size 20
```

### What it does

1. **Sample**: Query `N` random `job_offers` rows using the selected sampling
   mode. Default: `N = 20` (configurable via `--sample-size`).
2. **Re-fetch**: For each sampled row, call the corresponding client
   (`EEPPClient` or `TEEEClient`) to retrieve the offer by `external_id`.
3. **Compare**: Check the following fields between DB value and API value:

   | Field | Notes |
   |---|---|
   | `state` | Drift here is the most critical signal |
   | `gross_salary` | Null-safe: `None` vs `None` is not drift |
   | `title` | Minor diffs (encoding, extra spaces) normalized before compare |
   | `close_date` | Detects silently-extended deadlines |

4. **Report**: Log each differing field as `WARNING` with:
   - `job_offer_id`, `source`, `external_id`
   - field name, DB value, API value
5. **Exit code**: `0` if no drift found; `1` if any field differs on any row.

### CLI

```
PYTHONPATH=. python scripts/integrity_check.py \
    [--sample-size N] \
    [--sampling proportional|random] \
    [--source TEEE|EEPP]
```

| Flag | Default | Description |
|---|---|---|
| `--sample-size` | `20` | Total rows to sample |
| `--sampling` | `proportional` | `proportional`: stratified by state; `random`: uniform |
| `--source` | *(all)* | Restrict sampling to one source |

### What it does NOT do

- Does **not** auto-correct drift. Correction is left to the next normal
  ingestion run.
- Does **not** mark offers as stale or trigger re-ingestion.
- Does **not** alert via email/Telegram (that is Sprint 5.2).

### Cron recommendation

Run weekly, independently of the daily ingestion:

```
# Every Sunday at 06:00
0 6 * * 0  PYTHONPATH=. python scripts/integrity_check.py
```

The exit code `1` is enough for cron/CI to surface the event via normal
alerting.

---

## Work Items

- [x] `test_cross_source_higher_authority_promotes`
- [x] `test_cross_source_lower_authority_enriches`
- [x] `test_cross_source_enrichment_skipped_when_all_null`
- [x] `test_cross_source_promotion_state_forward_only`
- [x] `test_cross_source_promotion_state_advances`
- [x] `test_state_priority_initial_mode_always_overwrites`
- [x] `test_state_priority_periodic_mode_forward_only`
- [x] `test_state_priority_periodic_mode_advances`
- [x] `test_state_priority_same_stage_updates`
- [x] `scripts/integrity_check.py`: proportional stratified sample query (count per state, then `ORDER BY random() LIMIT k` per bucket)
- [x] `scripts/integrity_check.py`: uniform random sample query (`ORDER BY random() LIMIT N`)
- [x] `--sampling proportional|random` CLI flag (default: `proportional`)
- [x] Re-fetch by `external_id` for TEEE and EEPP sources
- [x] Field comparison with null-safe and whitespace-normalized equality
- [x] WARNING logging per differing field
- [x] Exit code `1` on any drift
- [x] `--sample-size` and `--source` CLI flags
- [x] Update `requirement.md` 3.16 entry

---

## Acceptance Criteria

1. All nine new test cases pass under `pytest tests/test_repository.py`.
2. Running `integrity_check.py` against a DB with known-clean data exits `0`.
3. Seeding a row with a manually-altered `state` and running the check exits `1`
   and logs a `WARNING` naming the differing field.
4. `--source EEPP` restricts sampling to EEPP rows only.
5. `--sampling proportional` with a DB containing skewed state distribution produces a sample with the correct per-state counts (within rounding).
6. `--sampling random` produces a flat sample without state constraints.
5. The script handles the case where `external_id` is not found upstream
   (offer removed) gracefully — logs `WARNING` and continues; does not crash.
