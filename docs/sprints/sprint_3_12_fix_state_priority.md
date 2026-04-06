# Sprint 3.12 — Fix State-Priority Logic

## Goal

After this sprint the ingestion pipeline supports two distinct modes:

1. **Initial load** (`--initial` flag): Loads all states as separate transactions
   in ascending lifecycle order (`finalizadas → evaluacion → postulacion`).
   Each onflict is resolved with an always-overwrite strategy.  Because
   `postulacion` is committed last it wins any fingerprint collision, correctly
   reflecting the current live state of each portal.

2. **Periodic update** (default): Forward-only state transitions
   (`postulacion → evaluacion → finalizada`).  A stored row is only updated
   when the incoming state is at the same stage or further along in the
   lifecycle.  This prevents regressions across cron runs while still handling
   gaps — an offer that went directly from `postulacion` to `finalizada` during
   a downtime period is correctly updated when it appears in the `finalizadas`
   endpoint on the next run.

---

## Background

### Pre-3.9 behaviour (original bug)

Loading `--state all` or running `finalizadas` after `postulacion` caused
`finalizada` records to overwrite `postulacion`/`evaluacion` records because
there was no state guard — last write won.

### Sprint 3.9 workaround (introduces a new bug)

Sprint 3.9 introduced a `postulacion = 1` (highest priority) guard to protect
active offers.  It solved the initial-load problem but made all forward
transitions impossible: an offer stored as `postulacion` can never be updated
to `evaluacion`, even across separate cron runs.

### Root cause: one code path, two conflicting use cases

The same `upsert_job_offers()` function is used for both:
- **Initial load**: should prefer the *most current/active* state — `postulacion`
  beats a stale `finalizada`.
- **Periodic update**: should prefer the *most advanced* state — `evaluacion`
  and `finalizada` must overwrite `postulacion`.

These two semantics are mutually exclusive.  The fix is to make the mode
explicit rather than trying to serve both use cases with a single heuristic.

---

## Design Decisions

### Two modes in `upsert_job_offers()`

A new `mode: str = 'periodic'` parameter is added.

| Mode | `ON CONFLICT DO UPDATE` strategy | Use case |
|------|----------------------------------|----------|
| `'initial'` | Always overwrite | First-time bulk load |
| `'periodic'` | `incoming_priority >= stored_priority` | Cron / periodic refresh |

#### `mode='initial'` — always overwrite

No state guard.  All mutable fields are unconditionally updated on conflict.
The load ORDER determines the winner: callers must commit states from oldest
lifecycle stage to newest so the most current state is written last.

Load order: `finalizadas` → `evaluacion` → `postulacion`

Because each state is committed as a **separate transaction**, postulacion
records loaded in the last transaction overwrite any record for the same
fingerprint regardless of what was stored before.

#### `mode='periodic'` — forward-only guard

New state priority mapping (higher integer = more advanced stage):

```python
_STATE_PRIORITY = {"postulacion": 1, "evaluacion": 2, "finalizada": 3}
```

SQL CASE guard: update mutable fields only when
`priority(incoming) >= priority(stored)`.

```python
higher_or_equal = _state_priority(inc.state) >= _state_priority(cur.state)
```

`else_=0` in the SQL helper ensures any unrecognised state value is treated
as the lowest priority and is always overwritten.

**Forward transition example (periodic run):**
- Stored: `postulacion` (1)
- Incoming: `evaluacion` (2) — `2 >= 1` → update ✅

**Regression prevention:**
- Stored: `evaluacion` (2)
- Incoming: `postulacion` (1) — `1 >= 2` → no update ✅

**Downtime / gap handling:**
- Stored: `postulacion` (1) (system was offline for weeks)
- Incoming: `finalizada` (3) — `3 >= 1` → update ✅

### In-memory dedup (unchanged)

Within a single batch the `seen` dict keeps the highest-stage row per
fingerprint using the same `>=` comparison.  This is correct for both modes:
- `initial`: each state is loaded as a separate single-state batch, so there
  are no cross-state conflicts within one batch.
- `periodic`: correctly keeps the most advanced state per fingerprint.

### `--initial` flag in load scripts

Both `load_teee.py` and `load_eepp.py` gain an `--initial` flag.

When `--initial` is set the script **ignores `--state`** and instead:
1. Fetches each state independently in lifecycle order.
2. Validates and commits each as a separate DB transaction with `mode='initial'`.
3. Logs per-state and total counts.

TEEE order: `finalizadas → evaluacion → postulacion`
EEPP order: `evaluacion → postulacion` (EEPP has no `finalizadas` endpoint)

---

## Work Items

- **`repository.py` — `_STATE_PRIORITY` dict**: `{"postulacion": 1, "evaluacion": 2, "finalizada": 3}`
- **`repository.py` — `_state_priority()` SQL helper**: explicit `finalizada=3` branch; `else_=0`
- **`repository.py` — in-memory dedup guard**: `>=` (highest-stage wins within batch)
- **`repository.py` — `upsert_job_offers()` signature**: add `mode: str = 'periodic'`
- **`repository.py` — `ON CONFLICT DO UPDATE`**: two branches — always-overwrite for `initial`, CASE guard for `periodic`
- **`load_teee.py`**: add `--initial` flag; add `_run_upsert()` helper; sequential state loading in `initial` mode
- **`load_eepp.py`**: same as `load_teee.py`

---

## Acceptance Criteria

### Initial load mode

1. Running `load_teee --initial` loads all three states sequentially.
2. An offer appearing in both `finalizadas` and `postulacion` APIs ends up
   stored as `postulacion` (because postulacion is committed last).
3. An offer appearing only in `finalizadas` is stored as `finalizada`.

### Periodic update mode (default)

4. Loading `--state postulacion` for an offer already stored as `evaluacion`
   does NOT revert the state to `postulacion`.
5. Loading `--state evaluacion` for an offer stored as `postulacion` DOES
   update the state to `evaluacion`.
6. Loading `--state finalizadas` for an offer stored as `evaluacion` DOES
   update the state to `finalizada`.
7. A batch containing the same offer under both `postulacion` and `evaluacion`
   stores it as `evaluacion`.
8. An offer that went `postulacion → finalizada` during downtime (skipped
   `evaluacion`) is correctly updated to `finalizada` on the next periodic run.

---

## Additional fixes included in this sprint

The following issues were discovered and resolved during the implementation and
testing of the initial load flow:

### Stage-A fingerprint domain scoping

**Problem:** `compute_fingerprint` Stage-A formula was `MD5("source_id|{source}|{external_id}")`.
TEEE's `ID Conv` field is the EEPP convocatoria number. Two TEEE offers with the
same `ID Conv` but different portal URLs (e.g. `directoresparachile.cl?c=11293`
and `empleospublicos.cl?i=11293`) produced the same fingerprint and were
incorrectly merged into one canonical row.

**Fix:** Domain included in Stage-A: `MD5("source_id|{source}|{domain}|{external_id}")`.
`url` parameter added to `compute_fingerprint()`. Both clients pass `url=` when
calling it. See `docs/design/deduplication.md §3.2` for full rationale.

**Impact:** All Stage-A fingerprints changed → requires truncate + `--initial`
reload after deploying.

### `cross_source_key` domain scoping

**Problem:** `compute_cross_source_key` formula was `MD5("cross|{external_id}")`.
`directoresparachile.cl?c=11293` and `empleospublicos.cl?i=11293` shared the same
cross-source key, incorrectly linking unrelated offers across portals.

**Fix:** `MD5("cross|{domain}|{external_id}")`. `url` keyword argument added.

### `directoresparachile.cl` URL extraction: `?c=` instead of `?i=`

**Problem:** `extract_external_id` extracted `?i=` (cargo ID, shared across
multiple concursos for the same position). Two different competitions for the
same cargo would share the same `external_id`.

**Fix:** Extract `?c=` (concurso ID, unique per competition).

### `junji.myfront.cl` returns `None`

**Problem:** `junji.myfront.cl` reuses numeric path IDs across unrelated cargos.
Extracting the path segment produced false Stage-A matches.

**Fix:** `extract_external_id` returns `None` for this domain, forcing Stage-B.

### asyncpg 32767-parameter limit on `cross_source_key` lookup

**Problem:** The pre-upsert `SELECT WHERE cross_source_key IN (...)` failed
with `InterfaceError` when the batch exceeded ~32000 offers (initial load of
`finalizadas`).

**Fix:** The IN-list is chunked at 32767 elements, results merged in memory.

### `job_offer_sources` UNIQUE constraint — migration 0007

**Problem:** `UNIQUE(source, external_id)` assumed one source row per
`external_id`. With domain-scoped fingerprints the same `ID Conv` (e.g. `18271`)
can legitimately map to two distinct canonical rows (different portal domains).
Only one source row could be created, leaving the second canonical row orphaned.

**Fix (migration 0007):** Constraint replaced with `UNIQUE(job_offer_id, source)`.
The migration also deletes pre-existing duplicate `(job_offer_id, source)` pairs
(keeping the most recently ingested row) before creating the new constraint.

---

## Notes

- The `cross_source_key` field is included in both ON CONFLICT paths.
- The `_run_upsert()` helper extracted into the load scripts eliminates the
  duplicated try/except/commit/rollback block that existed in both scripts.


---

## Background

### Current behaviour (broken for periodic ingestion)

Sprint 3.9 introduced a state-priority guard in `upsert_job_offers()` to
prevent a "lower-priority" state from overwriting a "higher-priority" one
within a single batch or across runs.  The original motivation was protecting
a `postulacion` record from being silently downgraded when the same offer
appeared twice in a batch with different states (e.g. `--state all` returning
the same offer under both `postulacion` and `evaluacion`).

The guard is implemented at two levels:

1. **In-memory dedup** (`seen` dict): keeps the row with the
   **lowest numeric priority** (closest to 1).
2. **`ON CONFLICT DO UPDATE` CASE expression**: only updates mutable fields
   when `_state_priority(incoming) <= _state_priority(existing)`.

Current mapping:

```python
_STATE_PRIORITY = {"postulacion": 1, "evaluacion": 2}
# anything else (including "finalizada") → 3 via CASE else_=3
```

This makes `postulacion=1` the **winner** of any conflict.  Because the
same `fingerprint` is stable across runs, a row ingested today as
`postulacion` will never be updated to `evaluacion` on tomorrow's run — the
CASE guard always keeps the stored value.

### Required behaviour for periodic ingestion

State transitions are **monotonically forward**: once an offer moves to
`evaluacion` it must not revert to `postulacion`, and once `finalizada` it
must not revert to `evaluacion` or `postulacion`.

The correct semantic is therefore:

| State | Should win conflicts? |
|---|---|
| `postulacion` | Only if stored state is also `postulacion` |
| `evaluacion` | Overwrites `postulacion`; loses to `finalizada` |
| `finalizada` | Overwrites everything |

This is the **opposite** of the current mapping for `postulacion` vs
`evaluacion`, but the logic is identical: "higher stage = higher priority".

---

## Design Decisions

### Invert the priority scale for forward state progression

Rename the semantic: priority 1 = **lowest stage** (postulacion), highest
integer = latest stage.  An incoming state updates the stored one only when
`incoming_priority >= stored_priority`.

New mapping:

```python
_STATE_PRIORITY = {"postulacion": 1, "evaluacion": 2, "finalizada": 3}
```

SQL CASE for the guard:

```sql
CASE WHEN priority(incoming.state) >= priority(current.state)
     THEN incoming.state
     ELSE current.state
END
```

In Python (SQLAlchemy):

```python
higher_or_equal = _state_priority(inc.state) >= _state_priority(cur.state)
```

### In-memory dedup: keep highest-priority row

Within a single batch the `seen` dict must also keep the **highest-stage**
row for each fingerprint (previously kept lowest).  The guard condition
changes from `<=` to `>=`:

```python
if current is None or (
    _STATE_PRIORITY.get(filtered.get("state", ""), 0)
    >= _STATE_PRIORITY.get(current.get("state", ""), 0)
):
    seen[offer.fingerprint] = filtered
```

### `_state_priority()` SQL helper

Update the helper to return 3 for `finalizada` explicitly (currently falls
through to `else_=3` which is implicit and fragile):

```python
def _state_priority(state_col):
    return case(
        (state_col == "postulacion", 1),
        (state_col == "evaluacion",  2),
        (state_col == "finalizada",  3),
        else_=0,   # unknown state loses to everything
    )
```

`else_=0` ensures any unrecognised state value is treated as the lowest
possible and is always overwritten.

### `_STATE_PRIORITY` dict

Used only for in-memory dedup — update to match:

```python
_STATE_PRIORITY = {"postulacion": 1, "evaluacion": 2, "finalizada": 3}
```

---

## Work Items

- **`repository.py` — `_STATE_PRIORITY` dict**: change to
  `{"postulacion": 1, "evaluacion": 2, "finalizada": 3}`.
- **`repository.py` — `_state_priority()` SQL helper**: add explicit
  `(state_col == "finalizada", 3)` branch; change `else_` to `0`.
- **`repository.py` — in-memory dedup guard**: change `<=` to `>=` so the
  highest-stage row per fingerprint survives the dedup pass.
- **`repository.py` — `ON CONFLICT DO UPDATE` guard**: change
  `higher_or_equal = ... <= ...` to `... >= ...` in every CASE expression
  that gates mutable-field updates.

---

## Acceptance Criteria

1. Loading `--state postulacion` for an offer already stored as `evaluacion`
   does NOT revert the state to `postulacion`.
2. Loading `--state evaluacion` for an offer stored as `postulacion` DOES
   update the state to `evaluacion`.
3. Loading `--state finalizada` for an offer stored as `evaluacion` DOES
   update the state to `finalizada`.
4. A batch containing the same offer under both `postulacion` and `evaluacion`
   (e.g. `--state all`) stores it as `evaluacion`.
5. A batch containing the same offer under both `evaluacion` and `finalizada`
   stores it as `finalizada`.

---

## Notes

- The `cross_source_key` CASE expression in `ON CONFLICT DO UPDATE` uses the
  same `higher_or_equal` guard.  This is still correct: the cross-source key
  should be updated alongside other mutable fields when a higher-stage
  ingestion arrives.
- Sprint 3.9 documentation in `requirement.md` described the old behaviour as
  `postulacion > evaluacion > finalizada` (higher priority wins conflicts).
  After this sprint the effective order is `finalizada > evaluacion >
  postulacion` (higher stage overwrites lower stage), which is the intended
  real-world semantic.
