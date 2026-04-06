# Requirements Specification: Job Tracker (EEPP & TEEE)

## 1. Status Tracker (Sprints)

### 🏗️ Sprint 1: Foundation & EEPP Ingestion
- [x] **1.1 Project Setup**: Initialize folder structure and environment variables (`.env`, `config.py`).
- [x] **1.2 EEPP API Discovery**: Identify endpoints, available statuses, payload structure, key fields, pagination mechanism, and scraping risks.
- [x] **1.3 EEPP Client**: Implement async extractor for `empleospublicos.cl` (Status: postulacion/evaluacion).
- [x] **1.4 Data Models**: Define Pydantic schemas for validation and SQLAlchemy models for Neon.
- [x] **1.5 Database Connectivity**: Configure async SQLAlchemy engine, session management, and Neon connection validation.
- [x] **1.6 Processing**: Implement `external_id` extraction and `fingerprint` V1 logic per source (see `architecture.md` for rules). Update `EEPPClient` to populate `external_id` and `source` from `TipoTxt`.
- [x] **1.7 Loading**: Implement Upsert logic in PostgreSQL (Neon) using `ON CONFLICT`.
- [x] **1.8 Orchestrator**: Implement `src/main.py` as the pipeline entry point (fetch → validate → upsert → commit) and `scripts/init_db.py` for first-time table creation in Neon.

### 🌐 Sprint 2: Web Interface
- [x] **2.1 FastAPI App Setup**: Create `src/web/app.py` with FastAPI app factory, Jinja2 templates, static files, and DB session dependency. Add `jinja2` and `python-multipart` to deps.
- [x] **2.2 Offers Query Layer**: Implement `src/web/queries.py` with async functions to query `job_offers` filtering by `region`, `city`, `institution`, and `state` (optional params). Returns paginated results.
- [x] **2.3 Offers List Page**: Implement `GET /` route in `src/web/routers/offers.py`. Full page renders `offers.html` with filter form and results table. Dropdown values populated from distinct DB values.
- [x] **2.4 HTMX Dynamic Filtering**: Add `hx-get` on filter form to call `GET /offers/partial` and swap only the results table (`partials/offers_table.html` partial) without full page reload.
- [x] **2.5 Server-side pagination**: The offers list endpoint MUST accept `page` and `per_page` parameters and return only the requested page of results. The response MUST include the total number of matching rows and the total number of pages so the UI can render a pager.
- [x] **2.6 Partial updates (HTMX)**: The UI MUST support partial updates of the results table so that applying filters, sorting, or paging updates only the results region without a full page reload.
- [x] **2.7 Filters**: The offers view MUST provide filters for `region`, `city`, `institution`, and `state`. Each filter control MUST be populated from distinct values present in the `job_offers` table and be optional.
- [x] **2.8 Column sorting**: The offers list MUST support ascending/descending sorting by the following fields: `title`, `institution`, `region`, `city`, `salary_bruto`, `state`, and `created_at`. Sort state MUST be preserved while paging and applying filters.
- [x] **2.9 Pager controls**: The UI MUST show pager controls (`First`, `Prev`, `Next`, `Last`) and a results summary of the form `Showing X–Y of N results`.
- [x] **2.10 Currency formatting**: Salary values MUST be displayed in local CLP formatting (thousands separator `.`) and rounded to whole pesos when shown in the UI.
- [x] **2.11 Text search**: The offers list MUST support text search on `title` using SQL LIKE `%term%` (case-insensitive; use `ILIKE` for Postgres). Query param: `q`.

### ⏳ Sprint 3: TEEE Integration & Tracking
- [x] **3.1 Database Refactor**: Introduce `job_offer_sources` to store per-source raw payloads and metadata (details: docs/sprints/sprint_3_1_database_refactor.md)
- [x] **3.2 TEEE Client**: Implement async extractor for `trabajaenelestado.cl` and mapping to the canonical schema (details: docs/sprints/sprint_3_2_teee_client.md)
- [x] **3.3 Alembic Integration**: Set up Alembic for database migrations (details: sprint_3_3_alembic_integration.md)
- [x] **3.4 Refactor `job_offers`**: Remove `external_id` from `job_offers` table (details: docs/sprints/sprint_3_4_job_offers_refactor.md)
- [x] **3.5 Refactor TEEEClient**: use `search_after`to do pagination (details: docs/sprints/sprint_3_5_refactor_teee_client.md)
- [x] **3.6 Load TEEE Offers**: create loader script to fetch and store TEEE offers (details: docs/sprints/sprint_3_6_load_teee_offers.md)
- [x] **3.7 Enrich & Extend**: Enrich `content_fingerprint` and extend `external_id` (details: docs/sprints/sprint_3_7_enrich_extend.md)
- [x] **3.8 Load & Logging Fixes**: Fix `load_teee` runtime failures and noisy error output (details: docs/sprints/sprint_3_8_load_teee_fixes.md)
- [x] **3.9 Data Quality & Schema Fixes** *(no separate sprint doc — changes are self-contained)*:
  - **State priority in upsert**: `postulacion > evaluacion > finalizada`. Applied at two levels: in-memory dedup within a batch (`seen` dict) and `ON CONFLICT DO UPDATE` via SQL `CASE` expressions so a lower-priority state never overwrites a higher-priority one, even across separate loader runs or `--state all`.
  - **`start_date` / `close_date` as `DateTime`**: Migrated from `String(64)` to `DateTime` (migration `0005_dates_as_datetime`). TEEE date strings (`DD/MM/YYYY H:MM` and `DD/MM/YYYY H:MM:SS`) are now parsed in `TEEEClient._parse_teee_date()` before reaching the schema. Fingerprint Stage-B now uses ISO 8601 serialization for dates.
  - **Documentation consolidation**: Merged `fingerprint_generation.md` and `teee_external_id_policy.md` into `docs/design/deduplication.md` (old files removed). Added missing coverage: state priority policy, normalization pipeline gap, `UniqueConstraint` on `job_offer_sources`, MD5 risk notes.
- [x] **3.10 Populate job_offer_sources**: During the `load_teee` upsert flow, write one row per ingested offer to `job_offer_sources` (fields: `source`, `external_id`, `raw_data`, `original_state`) and resolve `job_offer_id` pointing to the canonical row in `job_offers`. Enables raw-data and external-ID auditability without requiring multi-source reconciliation. (details: docs/sprints/sprint_3_10_populate_sources.md)
- [x] **3.11 Cross-source Matching**: Extend upsert flow to support multi-source ingestion (TEEE + EEPP). Link `job_offer_sources` rows across sources to the same canonical `job_offers` row via `external_id` or `content_fingerprint`. Includes `pending_verification` flag and reconciliation script. (details: docs/sprints/sprint_3_11_cross_source_matching.md)
- [x] **3.12 Fix state-priority logic & fingerprint correctness**: Two-mode upsert (`--initial` / periodic), domain-scoped Stage-A fingerprint, `directoresparachile.cl ?c=` extraction, `junji.myfront.cl` returns `None`, asyncpg chunking for cross_source_key lookup, migration 0007 replacing `UNIQUE(source, external_id)` with `UNIQUE(job_offer_id, source)` on `job_offer_sources`. (details: docs/sprints/sprint_3_12_fix_state_priority.md)
- [ ] **3.13 Unified ingestion entrypoint**: unified ingestion entrypoint `scripts/ingest_all.py` that runs both EEPP and TEEE loaders (`--state all`) sequentially with proper exit codes and structured logging
- [ ] **3.14 Configure Periodic Ingestion**: Configure a policy to run periodic ingestion.
- [ ] **3.15 Dokploy cron job configuration**: command, schedule, environment variables. Recommended schedule: 3×/day (morning / afternoon / night).
- [ ] **3.16 State Observer / Reconciliation**: Add a periodic reconciliation job to compute canonical `state` from all sources (details: docs/sprints/sprint_3_13_reconciliation.md)
- [ ] **3.17 Tests & Migration**: Add migration/backfill tooling and unit/integration tests for mapping, upsert, and reconciliation (details: docs/sprints/sprint_3_14_tests_migration.md)

### 📊 Sprint 4: Analysis & Reporting
- [ ] **4.1 Analytics Views**: Create SQL views in Postgres for salary averages and regional demand.
- [ ] **4.2 Notification System**: Simple script to alert of new matches via Telegram/Email.