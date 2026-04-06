# Sprint 3.15 — State Observer / Source Priority

## Goal

Establish TEEE as the canonical source of truth and define how EEPP data
enriches it. After this sprint:

1. TEEE offers are always ingested first, so canonical rows exist before EEPP
   tries to match them.
2. When both sources carry the same offer (matched by `cross_source_key`), TEEE
   wins all canonical fields; EEPP contributes its exclusive fields.
3. Three new EEPP-exclusive columns are added to `job_offers` and populated
   during the enrichment pass.
4. All field names use English throughout the codebase (migration 0009).

---

## Background

After Sprint 3.11 the cross-source matching logic linked EEPP and TEEE rows to
the same canonical `job_offers` row, but there was no authority system — the
last writer won. In practice this meant an EEPP ingestion run could overwrite
TEEE canonical fields (title, institution, state, salary) with lower-quality
data.

TEEE is more authoritative because it is the official government vacancy portal
and provides richer, validated metadata. EEPP is a secondary aggregator: it has
unique fields (`first_employment`, `vacancies`, `prioritized`) not present in
TEEE, and can fill in `gross_salary` when TEEE omits it.

---

## Design

### Source authority hierarchy

```python
_SOURCE_AUTHORITY = {"TEEE": 10, "EEPP": 5}
```

A higher integer means higher authority. Any future source can be inserted by
assigning it an integer in this dict.

### Cross-source match outcomes

When `upsert_job_offers()` encounters an incoming row whose `cross_source_key`
already maps to an existing canonical row from a *different* source, two
mutually exclusive branches run:

| Condition | Branch | Effect |
|---|---|---|
| `incoming_authority > existing_authority` | **Canonical promotion** | Overwrite title, institution, region, city, url, ministry, start_date, close_date, conv_type, cross_source_key, state (forward-only). |
| `incoming_authority <= existing_authority` | **Enrichment update** | COALESCE `gross_salary` (existing value preserved if non-null); set `first_employment`, `vacancies`, `prioritized` unconditionally (TEEE never provides them). |

The enrichment branch fires only when at least one of the four enrichment
fields is non-null in the incoming row, avoiding no-op writes.

### Forward-only state on canonical promotion

When TEEE promotes an EEPP-owned canonical row the state uses the same
forward-only lifecycle already in place for same-source periodic updates:

```python
winning_state = incoming if incoming_priority >= existing_priority else existing
```

This ensures a TEEE promotion cannot regress a row from `evaluacion` back to
`postulacion`.

### Ingest order

TEEE always runs before EEPP in both initial and periodic modes. This guarantees
that canonical rows exist by the time EEPP processes its batch, so the
enrichment branch is exercised correctly on every run rather than only on
subsequent re-runs.

---

## New columns

Migration 0008 (`0008_add_eepp_enrichment_columns`) added three EEPP-exclusive
columns to `job_offers`. Migration 0009 (`0009_rename_enrichment_columns`)
renamed them (and `salary_bruto`) to English:

| Column (English) | Type | Source field | Notes |
|---|---|---|---|
| `gross_salary` | `NUMERIC(14,2)` | `Renta Bruta` | Previously `salary_bruto`. Nullable; COALESCE on enrichment. |
| `first_employment` | `BOOLEAN` | `esPrimerEmpleo` | `True` when the position qualifies as first employment. |
| `vacancies` | `SMALLINT` | `Nº de Vacantes` | Number of open positions. |
| `prioritized` | `BOOLEAN` | `Priorizado` | Whether the offer is flagged as priority by EEPP. |

`first_employment`, `vacancies`, and `prioritized` are set unconditionally
during enrichment because TEEE never populates them, so there is no risk of
overwriting a higher-authority value.

---

## Implementation

### Files changed

| File | Change |
|---|---|
| `migrations/versions/0008_add_eepp_enrichment_columns.py` | Add `primer_empleo`, `vacantes`, `priorizado` columns |
| `migrations/versions/0009_rename_enrichment_columns.py` | Rename all four columns to English |
| `src/database/models.py` | Add `gross_salary`, `first_employment`, `vacancies`, `prioritized` mapped columns |
| `src/core/schemas.py` | Add same four fields to `JobOfferSchema` |
| `src/ingestion/eepp_client.py` | Extract `first_employment`, `vacancies`, `prioritized`; helper `_parse_vacancies()` and `_parse_bool_str()` |
| `src/ingestion/teee_client.py` | Emit `gross_salary: None` (field parity) |
| `src/database/repository.py` | `_SOURCE_AUTHORITY` dict; cross-source canonical promotion branch; enrichment update branch; both ON CONFLICT set_ blocks include new fields |
| `scripts/ingest_all.py` | Ingest order changed to TEEE-first in all modes |
| `src/main.py` | Add `gross_salary` to allowed sort/export column list |
| `src/web/queries.py` | `OfferRow.gross_salary`; `ALLOWED_SORTS["salary"]` points to `JobOffer.gross_salary` |
| `src/web/templates/partials/offers_table.html` | Render `offer.gross_salary` |

### `upsert_job_offers()` flow (simplified)

```
for each incoming row:
    if cross_source_key maps to existing row from different source:
        if incoming > existing authority:
            add to canonical_promotions
        elif any enrichment field is non-null:
            add to enrichment_updates
        continue  # skip normal insert/upsert path

→ bulk upsert rows_to_insert (ON CONFLICT fingerprint)
→ apply canonical_promotions (UPDATE WHERE id = ?)
→ apply enrichment_updates   (UPDATE WHERE id = ?, gross_salary COALESCE)
```

---

## Work Items

- [x] Migration 0008: add `first_employment`, `vacancies`, `prioritized` columns
- [x] Migration 0009: rename `salary_bruto` → `gross_salary`, plus the three new columns, to English
- [x] `_SOURCE_AUTHORITY` dict in `repository.py`
- [x] Cross-source canonical promotion branch (TEEE overrides EEPP)
- [x] Enrichment update branch (EEPP enriches TEEE canonical rows)
- [x] EEPP client extracts and parses the three new fields
- [x] TEEE client emits `gross_salary: None` for field parity
- [x] Ingest order fixed to TEEE-first in `ingest_all.py`
- [x] Web layer (`queries.py`, template) updated to `gross_salary`
- [x] `required_new_cols` guard in `upsert_job_offers()` detects unapplied migrations early
- [x] Dry-run verified: 1397 TEEE offers, 708 canonical promotions, 734 EEPP offers

---

## Acceptance Criteria

1. After a `--policy daily` run, canonical TEEE rows have their canonical fields
   owned by TEEE and enrichment fields (`first_employment`, `vacancies`,
   `prioritized`, `gross_salary`) populated from EEPP where available.
2. Re-running the pipeline with either source does not regress state
   (forward-only lifecycle applies to both same-source and cross-source updates).
3. EEPP-only offers (no TEEE match) are inserted as canonical rows with
   `source = "EEPP"` and their enrichment fields set.
4. `alembic upgrade head` applies cleanly from any prior revision.
5. `--dry-run` rolls back all writes and exits cleanly.
