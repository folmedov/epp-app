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
- [x] **3.13 Unified ingestion entrypoint**: `scripts/ingest_all.py` runs EEPP then TEEE loaders sequentially via subprocess; accepts `--policy daily|monthly`, `--initial`, `--dry-run`; exits 1 if any loader fails; second loader always runs regardless of first result. (details: docs/sprints/sprint_3_13_unified_entrypoint.md)
- [x] **3.14 Configure Periodic Ingestion**: Define and configure two ingestion policies:
  - **daily** (`--policy daily`): fetches `postulacion` + `evaluacion` only. Finalised offers do not change, so `finalizadas` is omitted from daily runs. Cron: once per day.
  - **monthly** (`--policy monthly`): full sweep including `finalizadas` to catch any missed or anomalous offers. Cron: once per month.
  - `--initial` bypasses both policies for the historical full load. (details: docs/sprints/sprint_3_14_periodic_ingestion.md)
- [x] **3.15 State Observer / Source Priority**: TEEE is the primary source of truth. EEPP enriches TEEE rows and adds EEPP-only offers. Key changes: (1) new columns `primer_empleo`, `vacantes`, `priorizado` on `job_offers` (migration 0008); (2) EEPP client extracts these fields; (3) cross-source match logic: TEEE promotes EEPP canonical rows (overwrites canonical fields, state-priority-aware); EEPP enriches TEEE canonical rows (salary COALESCE, EEPP-exclusive fields); (4) ingest order fixed to TEEE-first in both initial and periodic modes. (details: docs/sprints/sprint_3_15_source_priority.md)
- [x] **3.16 Tests & Data Integrity**: Unit/integration tests for mapping, upsert, and reconciliation logic. Also includes a **sample-based integrity check**: periodically re-fetch a small random subset of `job_offers` from the source APIs and compare key fields (state, salary, dates) to detect data drift between DB and upstream. (details: docs/sprints/sprint_3_16_tests_and_integrity.md)

### 🚀 Sprint 4: Deployment
- [x] **4.0 Install Dokploy on server**: Dokploy is installed and running on the target server.
- [x] **4.1 Dockerfile**: Single multi-stage Dockerfile (`builder` with `uv sync --frozen`, `runner` with Python slim image). One image serves both the web process and the ingestion scripts; the startup command is overridden per service in Dokploy.
- [x] **4.2 docker-compose.yml (local dev)**: Replicates the Dokploy topology locally: `web` (FastAPI on port 8000), `postgres` (official image, data volume), and an optional `worker` service for manual ingestion runs. Reads from `.env`.
- [x] **4.3 Alembic on startup**: The web container's entrypoint runs `alembic upgrade head` before starting uvicorn so schema migrations are applied automatically on every deploy.
- [x] **4.4 Environment variables**: Document the full set of variables that must be configured in Dokploy for each service:
  - `DATABASE_URL` — asyncpg DSN pointing to the Dokploy Postgres service (internal network URL)
  - `APP_ENV=production`
  - `LOG_LEVEL=INFO`
  - `SCRAPER_TIMEOUT=30`
  - `SCRAPER_MAX_RETRIES=3`
- [x] **4.5 Dokploy services**: Configure three services in the Dokploy UI, all built from the same image:
  - `eepp-web` — Application service, port 8000, command: `alembic upgrade head && uvicorn src.web.app:app --host 0.0.0.0 --port 8000`
  - `eepp-worker-daily` — Cron service, command: `python scripts/ingest_all.py --policy daily`
  - `eepp-worker-monthly` — Cron service, command: `python scripts/ingest_all.py --policy monthly`
  - `postgres` — Database service (Dokploy built-in Postgres)
- [ ] **4.6 Cron schedules**: Set the following schedules in Dokploy for the worker services:
  - `eepp-worker-daily`: `0 8,14,20 * * *` — 3×/day (08:00, 14:00, 20:00 Chile time)
  - `eepp-worker-monthly`: `0 3 1 * *` — 1st of every month at 03:00
- [ ] **4.7 Initial data load**: After first deploy, run the initial ingestion manually from Dokploy console: `python scripts/ingest_all.py --initial`

### 📊 Sprint 5: Analysis & Reporting
- [ ] **5.1 Analytics Views**: Create SQL views in Postgres for salary averages and regional demand.
- [ ] **5.2 Notification System**: Simple script to alert of new matches via Telegram/Email.