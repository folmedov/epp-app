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
|fingerprint|String(32)|Unique Index. Primary deduplication key for canonical offers (see Fingerprint Strategy).|
|external_id|String|Canonical external identifier when applicable (may be null). Used for cross-source linking when available.|
|source|String|Canonical source for this record (e.g. `EEPP`). This represents the source that provided the canonical/representative fields; details for each ingest are in `job_offer_sources`.
|title|String|Job position name (Cargo). Normalized for display/search.
|institution|String|Name of the public institution.
|salary_bruto|Numeric|Monthly gross salary (Nullable when not published).
|state|String|Canonical state: `postulacion`, `evaluacion`, `finalizada`.
|region|String|Geographical region in Chile.
|city|String|City or commune.
|url|String|Representative URL for the current canonical state (note: EEPP URLs may change between states).
|created_at|Timestamp|Automatic record creation time (UTC).
|updated_at|Timestamp|Time of last canonical update (UTC).

Note: the per-ingest `raw_data` JSONB column previously stored on `job_offers` has been moved to `job_offer_sources` to support multiple source rows per canonical offer and enable history/audit.

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

Extraction depends on URL domain and structure. These rules feed `external_id` on `job_offer_sources` and — when applicable — the canonical `job_offers.external_id` used for cross-source linking.

| Domain | Pattern | Extraction |
|:---|:---|:---|
| `empleospublicos.cl` | `?i=<id>` query param | `i` value (e.g. `139281`) |
| `junji.myfront.cl` | `/oferta-de-empleo/<id>/slug` | path segment after `/oferta-de-empleo/` |
| `*.trabajando.cl` | `/trabajo/<id>-slug` | numeric prefix before first `-` |
| `educacionpublica.gob.cl`, `renca.cl`, etc. | No stable ID | `None` |

### Fingerprint Strategy

Two complementary fingerprint keys are produced to serve different purposes:

- `per_source_fingerprint` (existing behavior): when `external_id` is available compute `MD5(source + "|" + external_id)`. This key deduplicates records within the same source and is stable across URL/state transitions for that source.
- `cross_source_key` (new): when `external_id` is available compute a source-agnostic key (e.g. `MD5(external_id)` or normalized external identifier) to enable linking the same logical offer across different sources (EEPP ↔ TEEE). The exact choice and normalization rules for `cross_source_key` are defined in Sprint 3 and implemented in the upsert flow.

When no `external_id` is available, fall back to a composed fingerprint such as `MD5(title + "|" + institution + "|" + region)` with awareness that collision risk is higher for these generic records.

### Observations

- The URL field is **not stable** across state transitions for EEPP records (the `i` param stays the same but the path changes between pages). Store representative canonical `url` in `job_offers`; retain original per-ingest URLs in `job_offer_sources.raw_data`.
- The system maintains both a per-source fingerprint and a cross-source key to enable robust de-duplication and cross-source linking. Cross-source linking and the merge/canonicalization rules are implemented in Sprint 3.
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
|raw_data|JSONB|Full original JSON payload returned by the source API.
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