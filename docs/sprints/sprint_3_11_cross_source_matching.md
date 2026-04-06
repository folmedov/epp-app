# Sprint 3.11 — Cross-source Matching

## Goal

After this sprint, running `load_teee` and `load_eepp` on the same offer
population should produce **one canonical `job_offers` row** per logical offer,
not two separate rows. Both ingestions are recorded in `job_offer_sources`,
pointing at the same `job_offer_id`.

---

## Background

Two independent problems cause TEEE and EEPP ingestions of the same offer to
diverge:

### Problem 1 — Stage-A fingerprint includes `source`

The current Stage-A formula is:

```
MD5("source_id|{source}|{external_id}")
```

TEEE stores an offer with `source="TEEE"` and `external_id="241072"` (TEEE's
`ID Conv` field). EEPP ingests the same offer via `?i=241072`, computing
`MD5("source_id|EEPP|241072")`. Different hash → second canonical row.

The numeric IDs are identical across portals: TEEE's `Tipo Convocatoria: "EEPP"`
entries carry an `ID Conv` value that matches the `?i=` query param used by the
`empleospublicos.cl` URL. This makes reliable Stage-A cross-source linking
possible for those records.

### Problem 2 — EEPP dates are raw strings (Stage-B fingerprint divergence)

`compute_content_fingerprint()` serializes dates via `.isoformat()`, expecting
`datetime | None`. TEEE parses its date strings before fingerprint computation
via a private `_parse_teee_date()` in `teee_client.py`. EEPP passed raw strings
(`"26/03/2026 0:00:00"`) directly — Stage-B fingerprints for the two canonical
rows of the same offer therefore differed even when content was identical.

Both portals use the same date format: `DD/MM/YYYY H:MM:SS` (with zero or
single-digit hour). The existing `_DATE_FORMATS` tuple handles both unchanged.

---

## Design Decisions

### Phase A — Shared `parse_date()` utility (prerequisite)

Move `_DATE_FORMATS` and `_parse_teee_date()` out of `teee_client.py` and into
`transformers.py` as a public `parse_date()` function:

```python
def parse_date(raw: str | datetime | None) -> datetime | None: ...
```

Both clients call `parse_date()` on every date field before passing the value
to `compute_fingerprint()` or building the schema dict. An already-parsed
`datetime` is returned as-is, making the function idempotent and safe to
call redundantly.

`parse_date` is added to `transformers.__all__`.

### Phase B — `cross_source_key` column

A new nullable column `cross_source_key VARCHAR(32)` is added to `job_offers`.
It is computed only when a **verified** (non-generated) `external_id` is
available:

```
cross_source_key = MD5("cross|{external_id}")
```

The `"cross|"` prefix prevents accidental collisions with Stage-A or Stage-B
hashes. The key is source-agnostic: the same `external_id` value produces the
same key regardless of which portal delivered it.

`cross_source_key` is added to `JobOfferSchema` as `str | None` and propagated
to the DB. A new Alembic migration (`0006_add_cross_source_key`) creates the
column with a non-unique index (multiple source rows may reference the same
canonical row, but the column itself is not the PK).

### Phase C — Cross-source upsert logic

`upsert_job_offers()` gains a two-step resolution for offers that carry a
`cross_source_key`:

1. Before the bulk INSERT, collect all non-null `cross_source_key` values in the
   batch and issue a single `SELECT id, fingerprint, cross_source_key FROM
   job_offers WHERE cross_source_key = ANY(...)` lookup.
2. For any offer whose `cross_source_key` matches an existing row **with a
   different `fingerprint`** (i.e., a different source already owns the canonical
   row), do not insert a new `job_offers` row. Instead, add the existing
   `id`/`fingerprint` pair directly to the returned `fingerprint → UUID` mapping
   so that the subsequent `upsert_job_offer_sources()` call correctly sets
   `job_offer_id` on the new source row.
3. Offers with no `cross_source_key`, or whose key has no existing match,
   proceed through the normal `INSERT ... ON CONFLICT DO UPDATE` path.

The canonical row keeps whichever source first created it. Subsequent ingestions
from other sources only add `job_offer_sources` rows.

### Phase D — EEPP loader

A new script `scripts/load_eepp.py` mirrors `scripts/load_teee.py`. It
instantiates `EEPPClient`, fetches both states, validates against
`JobOfferSchema`, calls `upsert_job_offers()` then `upsert_job_offer_sources()`
inside a single transaction, and logs `"Committed {N} offer(s) and {M} source
row(s) to DB"`.

### `pending_verification` flag (deferred to Sprint 3.12)

Stage-A cross-source matches (same `external_id`) are high-confidence and can
be auto-linked. Stage-B matches (same `content_fingerprint`, different source,
no reliable `external_id`) are lower-confidence. A `pending_verification` flag
on `job_offer_sources` for Stage-B cross-source candidates is deferred to Sprint
3.12 (reconciliation), which handles the manual review / automatic confirmation
workflow.

---

## Work Items

### Phase A — `parse_date()` in `transformers.py`

- **`transformers.py`**: add module-level `_DATE_FORMATS` tuple and
  `parse_date(raw: str | datetime | None) -> datetime | None`. Add to
  `__all__`.
- **`teee_client.py`**: remove `_DATE_FORMATS` and `_parse_teee_date()`.
  Import `parse_date` from `transformers`. Replace both `_parse_teee_date(...)`
  calls with `parse_date(...)`.
- **`eepp_client.py`**: import `parse_date` from `transformers`. Wrap
  `start_date` and `close_date` extraction with `parse_date()`. Update the
  returned dict so `start_date` and `close_date` carry `datetime | None` values
  instead of raw strings.

### Phase B — `cross_source_key` column

- **`transformers.py`**: add `compute_cross_source_key(external_id: str | None,
  external_id_generated: bool) -> str | None`. Returns
  `MD5("cross|{external_id}")` when `external_id` is non-null and not
  generated, else `None`. Add to `__all__`.
- **`schemas.py`**: add `cross_source_key: str | None = None` to
  `JobOfferSchema`.
- **`migrations/`**: new migration `0006_add_cross_source_key.py` — adds
  `cross_source_key VARCHAR(32)` with a non-unique index to `job_offers`.
- **`models.py`**: add `cross_source_key: Mapped[str | None]` column.
- **`teee_client.py`** (`_normalize_hit`): call `compute_cross_source_key()`
  and include result in the returned dict.
- **`eepp_client.py`** (`_normalize_offer`): same.

### Phase C — Cross-source upsert logic

- **`repository.py`** (`upsert_job_offers`): add cross-source pre-lookup step
  (see Design Decisions — Phase C). Return mapping must cover both
  normally-inserted offers and cross-source-resolved offers.

### Phase D — EEPP loader

- **`scripts/load_eepp.py`**: new script — fetch → validate → upsert. Supports
  `--state postulacion|evaluacion|all` and `--batch` size flags.

---

## Files Changed

| File | Change |
|:---|:---|
| `src/processing/transformers.py` | Add `_DATE_FORMATS`, `parse_date()`, `compute_cross_source_key()` |
| `src/ingestion/teee_client.py` | Remove `_DATE_FORMATS`, `_parse_teee_date()`; use `parse_date`, `compute_cross_source_key` |
| `src/ingestion/eepp_client.py` | Use `parse_date`, `compute_cross_source_key`; dates are now `datetime \| None` |
| `src/core/schemas.py` | Add `cross_source_key: str \| None` to `JobOfferSchema` |
| `src/database/models.py` | Add `cross_source_key` column |
| `src/database/repository.py` | Cross-source pre-lookup in `upsert_job_offers()` |
| `migrations/versions/0006_add_cross_source_key.py` | New migration |
| `scripts/load_eepp.py` | New EEPP loader script |

---

## Key Contracts

| Contract | Detail |
|:---|:---|
| `parse_date` is idempotent | Passing an already-parsed `datetime` returns it unchanged; `None` / empty string returns `None`. |
| `cross_source_key` is source-agnostic | `MD5("cross\|241072")` is identical whether computed by `TEEEClient` or `EEPPClient`. |
| No new canonical row when key matches | If `cross_source_key` resolves to an existing `job_offers` row, only a new `job_offer_sources` row is written. |
| Stage-A within-source dedup is unchanged | The `fingerprint` column and its `UNIQUE` index continue to deduplicate records from the same source. |
| `load_eepp.py` is independently runnable | Running the EEPP loader after `load_teee` (or before) is idempotent in both directions. |

---

## Acceptance Criteria

- Loading TEEE then EEPP for the same batch of offers produces **one** `job_offers`
  row and **two** `job_offer_sources` rows per offer (one per source), not two
  separate canonical rows.
- Stage-B `content_fingerprint` values are identical across sources for the same
  offer (verified by comparing a sample of matched rows).
- `scripts/load_eepp.py --state all` runs without errors and reports correct
  source-row counts.
- Re-running either loader does not create duplicate `job_offer_sources` rows for
  offers that have a stable `external_id`.
