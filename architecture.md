# Architecture Specification: Job Tracker (EEPP & TEEE)

## 1. Target Project Structure
All source code should converge toward the following layout as the project evolves:

```text
job_tracker/
├── .github/
│   └── copilot-instructions.md  # Standard engineering rules
├── src/
│   ├── core/
│   │   ├── config.py            # Environment variables (Pydantic Settings)
│   │   └── schemas.py           # Data validation (Pydantic v2 Models)
│   ├── database/
│   │   ├── session.py           # Async SQLAlchemy engine & session setup
│   │   └── models.py            # SQLAlchemy 2.0 ORM Table definitions
│   ├── ingestion/
│   │   ├── base.py              # Abstract Base Class for API clients
│   │   ├── eepp_client.py       # Scraper/Client for Empleos Públicos
│   │   └── teee_client.py       # Scraper/Client for Trabaja en el Estado
│   ├── processing/
│   │   └── transformers.py      # Fingerprinting (MD5) and cleaning logic
│   ├── web/
│   │   ├── app.py               # FastAPI application factory
│   │   ├── routers/
│   │   │   └── offers.py        # Routes: list, filter
│   │   ├── queries.py           # Async DB query functions (filter by region/city/institution)
│   │   ├── templates/
│   │   │   ├── base.html        # Base layout
│   │   │   ├── offers.html      # Offers list page (full page)
│   │   │   └── partials/
│   │   │       └── offers_table.html  # HTMX partial (re-rendered on filter)
│   │   └── static/
│   │       └── style.css        # Minimal custom styles
│   └── main.py                  # Entry point (Orchestrator)
├── requirement.md               # Business logic and functional specs
├── architecture.md              # This file
├── docker-compose.yml           # Infrastructure as code
└── .env                         # Secrets (Database URL, API Keys)
```  

## 2. Database Schema (PostgreSQL / Neon)
The canonical table is `job_offers`. It stores the normalized, queryable fields used by the UI and analysis workloads.

Per-source raw payloads and ingestion metadata are persisted in a separate table `job_offer_sources` (see below). This keeps the canonical table compact and fast while preserving full audit information and allowing multiple source records to link to the same logical offer.

Primary canonical table: `job_offers` (summary)

|Column|Type|Description|
|:---|:---|:---|
|id|UUID|Primary Key (Default: uuid_generate_v4())|
|fingerprint|String(32)|Unique Index. Primary deduplication key for canonical offers (see Fingerprint Strategy). After canonicalization this column holds the canonical fingerprint or cross-source key used for deduplication and linking.
|source|String|Canonical/representative source for this record (e.g. `EEPP`). Indicates which provider's data is being presented as the canonical values; per-ingest provenance lives in `job_offer_sources`.
|title|String|Job position name (Cargo). Normalized for display/search.
|institution|String|Name of the public institution.
|salary_bruto|Numeric|Monthly gross salary (Nullable when not published).
|state|String|Canonical state: `postulacion`, `evaluacion`, `finalizada`.
|region|String|Geographical region in Chile.
|city|String|City or commune.
|url|String|Representative URL for the current canonical state (note: EEPP URLs may change between states).
|ministry|String|Ministry or contracting entity (Nullable). Mapped from `Ministerio` in both EEPP and TEEE.
|start_date|Timestamp (no tz)|Process start date (Nullable). Both EEPP and TEEE deliver dates in `DD/MM/YYYY H:MM` or `DD/MM/YYYY H:MM:SS` format; they are normalized to `datetime` by `parse_date()` in `transformers.py` before fingerprint computation and storage. ISO 8601 serialization is used in Stage-B fingerprints.
|close_date|Timestamp (no tz)|Application close date (Nullable). Same parsing rules as `start_date`.
|cross_source_key|String(32)|Cross-source linking key (Nullable). `MD5("cross\|{external_id}")` when a verified (non-generated) `external_id` is available; `NULL` otherwise. Source-agnostic: the same external ID produces the same key regardless of portal. Used by the upsert flow to link EEPP and TEEE ingestions of the same offer to one canonical row. Added in Sprint 3.11.
|conv_type|String|Convocation type code (Nullable). Populated from TEEE's `Tipo Convocatoria` (e.g. `DEE`, `ADP`); `NULL` for EEPP.
|created_at|Timestamp|Automatic record creation time (UTC).
|updated_at|Timestamp|Time of last canonical update (UTC).

Note: the per-ingest `raw_data` JSONB column previously stored on `job_offers` has been moved to `job_offer_sources` to support multiple source rows per canonical offer and enable history/audit. Following Sprint 3.4, the `external_id` attribute was also moved out of `job_offers` and is now stored on `job_offer_sources`; canonical linking is performed via fingerprints / cross-source keys and the `job_offers.fingerprint` column (or computed at upsert time).

### Source Values

The EEPP portal acts as an aggregator. The `TipoTxt` field in the raw payload identifies the actual origin. `job_offer_sources` records the original source per ingest; the `job_offers.source` column holds the canonical/representative source for the normalized row.

Mapping used for common `source` values:

| TipoTxt (raw, HTML-unescaped) | source value |
|:---|:---|
| `Empleos Públicos` / `Empleos Públicos Evaluación` | `EEPP` |
| `JUNJI` | `JUNJI` |
| `Invitación a Postular` | `EXTERNAL` |
| `DIFUSION` | `DIFUSION` |
| `Comisión Mercado Financiero` | `CMF` |
| TEEE (trabajaenelestado) | `TEEE` |

### External ID Rules

Extraction depends on URL domain and structure. These rules feed `external_id` on `job_offer_sources`. Cross-source linking is performed using computed keys (for example a `cross_source_key` derived from normalized external IDs or the canonical fingerprint); the canonical linking key is persisted on `job_offers.fingerprint` or otherwise computed by the upsert flow.

| Domain | Pattern | Extraction |
|:---|:---|:---|
| `empleospublicos.cl` | `?i=<id>` query param | `i` value (e.g. `139281`) |
| `junji.myfront.cl` | `/oferta-de-empleo/<id>/slug` | **`None`** — JUNJI reuses numeric IDs across different positions; Stage-B (content fingerprint) is used instead to avoid collisions |
| `*.trabajando.cl` | `/trabajo/<id>-slug` | numeric prefix before first `-` |
| `directoresparachile.cl` | `/Repositorio/PDFConcursos/<id>.pdf` | PDF filename without extension (e.g. `dee_1967_7707`) |
| `educacionpublica.gob.cl`, `renca.cl`, etc. | No stable ID | `None` |

### Fingerprint Strategy

Three complementary keys are produced per offer:

- **`fingerprint` (Stage-A, per-source)**: `MD5("source_id|{source}|{external_id}")` when a verified `external_id` is available. Deduplicates within the same source and is the `UNIQUE` key on `job_offers`. Falls back to Stage-B when no reliable `external_id` exists.
- **`content_fingerprint` (Stage-B)**: `MD5("content|" + MD5(title|institution|region|city|ministry|start_date_iso|conv_type|close_date_iso))`. Dates are serialized via `datetime.isoformat()`. Used as the Stage-A fallback and for cross-source content comparison. Both EEPP and TEEE normalize dates through `parse_date()` in `transformers.py` before this computation.
- **`cross_source_key`** (Sprint 3.11): `MD5("cross|{external_id}")` when a verified `external_id` is available; `NULL` otherwise. Source-agnostic: TEEE `ID Conv` and EEPP `?i=` values for the same offer produce the same key. The upsert flow uses this key to detect an existing canonical row from a different source and skips inserting a new `job_offers` row, writing only a new `job_offer_sources` row instead.

When no `external_id` is available the fallback is Stage-B (`content_fingerprint`). Collision risk is higher for generic records without a stable ID.

### Observations

- The URL field is **not stable** across state transitions for EEPP records (the `i` param stays the same but the path changes between pages). Store representative canonical `url` in `job_offers`; retain original per-ingest URLs in `job_offer_sources.raw_data`.
- The system maintains both a per-source fingerprint and a cross-source key to enable robust de-duplication and cross-source linking. Cross-source linking and the merge/canonicalization rules are implemented in Sprint 3.
- **State priority** is enforced at two layers: (1) in-memory dedup within a batch keeps only the highest-priority record per fingerprint; (2) `ON CONFLICT DO UPDATE` uses SQL `CASE` expressions so a lower-priority incoming state (`finalizada`) never overwrites a higher-priority stored state (`postulacion`, `evaluacion`). Priority order: `postulacion (1) > evaluacion (2) > finalizada (3)`. See `src/database/repository.py` (`_STATE_PRIORITY`, `_state_priority()`).
- Moving `raw_data` into `job_offer_sources` enables:
  - preserving multiple raw payloads for the same logical offer (audit/history),
  - avoiding large JSONB columns on the hot canonical table used for queries,
  - applying GIN/jsonb indexes on the per-source table when needed.

## Job offer sources table (`job_offer_sources`)

This table stores every ingest's original payload and metadata. It is the source of truth for raw audit data and is used by migration, reconciliation and debugging tools.

|Column|Type|Description|
|:---|:---|:---|
|id|UUID|Primary Key (Default: uuid_generate_v4())|
|job_offer_id|UUID|FK → `job_offers.id`. Nullable during backfill (populate when canonical row is present).
|source|String|Source name (EEPP, TEEE, JUNJI, ETC).
|external_id|String|Source-native identifier when available.
|raw_data|JSONB|Full original JSON payload returned by the source API. For TEEE records, the pipeline injects a synthetic key `_elastic_id` (string) containing the Elasticsearch document `_id`. This key is **not** part of the source API response; it is added during normalization for traceability when `external_id` is unavailable or generated.
|original_state|String|State value reported by the source for this payload.
|ingested_at|Timestamp|Time when this payload was ingested into the system.

Indexes & constraints:

- `UNIQUE(source, external_id)` where `external_id` is not null — prevents duplicate source rows for the same external record.
- Index on `job_offer_id` to efficiently lookup all source rows for a canonical offer.
- Optional GIN index on `raw_data` for JSONB search when required.

## Migration and operational notes

- Backfill approach: run `scripts/migrate_raw_to_sources.py` which inserts existing `job_offers.raw_data` into `job_offer_sources` in batches, validates counts and samples, then optionally drops/renames the `raw_data` column on `job_offers` once verified.
- Keep the `raw_data` column on `job_offers` until backfill is verified. Use `canonical_raw` if a single representative raw snapshot should be kept on the canonical row.
- Ensure `unaccent` extension and other DB extensions required by queries are installed before running migration or enabling diacritic-insensitive search.

## Repository layer (`src/database/repository.py`)

Two public functions manage persistence:

| Function | Returns | Description |
|:---|:---|:---|
| `upsert_job_offers(session, offers)` | `dict[str, UUID]` | Bulk upsert into `job_offers`. Returns a mapping of `fingerprint → job_offer_id` for every row inserted or updated. Callers use this mapping to resolve the FK when writing source rows. |
| `upsert_job_offer_sources(session, offers, fingerprint_to_id)` | `int` | Upsert one row per offer into `job_offer_sources`. Resolves `job_offer_id` from the mapping returned by `upsert_job_offers()`. Uses `ON CONFLICT (source, external_id) DO UPDATE` for idempotency on offers with a stable `external_id`; inserts a new row on every run for offers without one. |

## 3. Web Interface

**Stack**: FastAPI + Jinja2 + HTMX

- **FastAPI** handles routing and DB session injection via `Depends(get_session)`.
- **Jinja2** renders server-side HTML templates — no separate JS build step.
- **HTMX** handles dynamic filter updates by swapping the `offers_table.html` partial on every filter change (`hx-get`, `hx-trigger="change"`, `hx-target="#results"`).

**Filter behavior**:
- Filters (`region`, `city`, `institution`) are optional query params on `GET /offers/partial`.
- Dropdown values are populated from `SELECT DISTINCT` queries on the `job_offers` table.
- No authentication required — read-only public interface.

**Run the web server**:
```bash
PYTHONPATH=. uv run uvicorn src.web.app:app --reload --port 8000
```