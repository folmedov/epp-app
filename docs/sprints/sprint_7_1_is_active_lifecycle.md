# Sprint 6.1 — Offer Lifecycle Flag (`is_active`)

## Context

The audit performed on 2026-04-07 revealed **688 offers** still recorded as `postulacion` or `evaluacion` whose `close_date` is in the past. Two root causes were identified:

1. **Ingestion lag (solvable):** Offers recently moved to `finalizada` in the source portal; the next daily run normally corrects these.
2. **Structural gap (persistent):** Offers originating from `directoresparachile.cl` are published via TEEE but their lifecycle is managed through PDF documents, not through the TEEE Elasticsearch index. When these concursos end, TEEE does not transition them to `finalizadas` nor removes them cleanly — they stay as `evaluacion` in our DB indefinitely.

Directly modifying the `state` column was rejected to preserve referential integrity with the source portals. Instead, a new `is_active` flag is introduced as a pipeline-managed visibility control.

## Design

### New column: `job_offers.is_active`

| Property | Value |
|---|---|
| Type | `BOOLEAN NOT NULL DEFAULT TRUE` |
| Default | `True` — all existing offers remain visible after migration |
| Managed by | `scripts/close_stale_offers.py` (pipeline, not the ingest upsert) |
| UI default | Filters `is_active = True` AND (`close_date IS NULL` OR `close_date >= CURRENT_DATE`); toggle disables both|

### Dual-condition filtering

The default UI query applies two independent conditions together:

1. `is_active = TRUE` — pipeline-managed flag, set to `False` by `close_stale_offers.py` when an offer disappears from both active feeds.
2. `close_date IS NULL OR close_date >= CURRENT_DATE` — date-based filter that hides offers with a known past close date.

**Why both?** TEEE retains offers in its `postulacion`/`evaluacion` index even after `close_date` elapses — the portal itself does not transition them. This means `close_stale_offers.py` currently closes 0 offers per run (all stale candidates still appear in the live feed). The `close_date` filter in the query layer is the primary mechanism that hides stale offers from the default view. `is_active` is preserved as a pipeline-managed override for future scenarios (e.g., offers that disappear from all feeds without transitioning to `finalizada`).

The "Vencidas" toggle passes `include_inactive=true` which removes **both** conditions, showing all offers regardless of date or flag.

### Invariants

- **`state` is never modified** by this feature — it always reflects the last value reported by the source portal.
- `is_active = False` means "hidden from the default view" — not deleted, not archived.
- The ingest upsert (`repository.py`) never touches `is_active`; only `close_stale_offers.py` writes to it.
- An offer can be reactivated automatically if a future ingestion finds it in an active feed again (not implemented in v1 — current script is append-only toward `False`).

## Implementation

### 1. Migration `0011_add_is_active`

```sql
ALTER TABLE job_offers ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
CREATE INDEX ix_job_offers_is_active ON job_offers (is_active);
```

Existing rows receive `is_active = TRUE` via the column default.

### 2. `src/database/models.py`

Added field:
```python
is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True, index=True)
```

### 3. `src/web/queries.py`

`get_offers()` gains an `include_inactive: bool = False` parameter.
When `False` (default), adds both:
- `WHERE is_active = TRUE`
- `AND (close_date IS NULL OR close_date >= CURRENT_DATE)`

When `True` ("Vencidas" toggle active), both conditions are omitted.

### 4. `src/web/routers/offers.py`

Both `GET /` and `GET /offers/partial` accept `include_inactive: bool = False`.
Passed through to `get_offers()`.

### 5. UI toggle (`offers.html`)

A "Vencidas" checkbox pill added to the filter bar. When unchecked (default), the query hides stale offers via the dual condition above. When checked, `include_inactive=true` is sent and all offers are shown including those with past `close_date`.

### 6. `scripts/close_stale_offers.py`

Algorithm:
1. Query DB: offers where `state IN ('postulacion','evaluacion')` AND `close_date < today` AND `is_active = TRUE`.
2. Fetch full active index from TEEE (postulacion + evaluacion) and active EEPP offers.
3. Build a set of active `external_id` values from both feeds.
4. For each stale DB offer: look up its `external_id`(s) in `job_offer_sources`.
5. If **none** of its external IDs appear in the active feeds → mark `is_active = False`.
6. Commit; log counts.

CLI options:
- `--dry-run`: print what would change, no writes.
- `--grace-days N` (default: 3): offers whose `close_date` is within N days are left active (buffer for ingestion lag).

### 7. `scripts/ingest_all.py`

`close_stale_offers.py` is run as a subprocess at the end of every daily/monthly policy execution (not in `--initial` mode). If it fails, a warning is logged but the exit code of `ingest_all.py` is not affected.

## Acceptance criteria

- [x] `alembic upgrade head` applies migration 0011 cleanly.
- [x] Default query hides stale offers (past `close_date` with known date); toggle shows them.
- [x] `state` values of hidden offers are unchanged.
- [x] `close_stale_offers.py --dry-run` prints expected rows without writing.
- [x] `ingest_all.py --policy daily` calls `close_stale_offers.py` at the end.
- [x] Re-running `close_stale_offers.py` is idempotent (no double-processing).

## Known limitations

- **`close_stale_offers.py` currently closes 0 offers** per run: TEEE keeps all its offers in the active Elasticsearch index regardless of `close_date`, so every stale DB candidate still has an active external_id match. The `close_date`-based UI filter compensates for this at query time.
- Offers with `close_date IS NULL` are always shown in the default view (not filter-able by date).
- `is_active` reactivation is not automatic: if a future ingestion finds a deactivated offer in an active feed, the flag is not set back to `True` (v1 limitation).
