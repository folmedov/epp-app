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
- [x] **4.6 Cron schedules**: Set the following schedules in Dokploy for the worker services:
  - `eepp-worker-daily`: `0 8,14,20 * * *` — 3×/day (08:00, 14:00, 20:00 Chile time)
  - `eepp-worker-monthly`: `0 3 1 * *` — 1st of every month at 03:00
- [x] **4.7 Initial data load**: After first deploy, run the initial ingestion manually from Dokploy console: `python scripts/ingest_all.py --initial`

### 🎨 Sprint 5: UI Enhancements
- [x] **5.1 Modern UI / Minimal Design**: Update the base layout and styles to a modern, minimal and mobile-first design. Deliverables: base CSS (or small utility stylesheet), updated base template, color tokens, font stack, and responsive breakpoints. Acceptance: offers list and detail pages use the new layout and pass basic visual QA on desktop and mobile.
- [x] **5.2 Show start and close dates**: Surface `start_date` and `close_date` on the offers list and the offer detail page. Deliverables: templates updated to include formatted dates, server-side formatting helper, and tests. Acceptance:Dates are shown in local format and present in both list and detail views.
- [x] **5.3 Sorting selector (replace header-click)**: Replace click-on-table-header sorting with a compact sorting control (field selector + asc/desc toggle) placed above the results. The selector must integrate with HTMX partial updates and preserve state in the query string. Acceptance: selecting sort updates the partial results and the URL reflects the choice.
- [x] **5.4 Filters UX improvements**: Improve filter ergonomics: grouped filters, clear/reset action, and persistent filter state when navigating pages. Deliverables: small UX tweaks in templates and HTMX interactions. Acceptance: users can clear filters and share URLs with filters applied.
- [x] **5.5 Accessibility & responsiveness**: Ensure keyboard navigation, ARIA attributes for interactive controls, focus styles, and sufficient color contrast. Deliverables: minor ARIA updates and focus-visible styles. Acceptance: basic accessibility checks (aria roles, keyboard navigation) pass.
- [ ] **5.6 Performance & search improvements**: Add short TTL server-side caching for the offers list and consider a `tsvector` index for future full-text search. Deliverables: caching layer (in-memory or pluggable), migration notes for search indexing. Acceptance: list endpoint latency improved under load in smoke tests.
- [ ] **5.7 E2E tests and CI**: Add Playwright (or equivalent) tests covering filtering, sorting, date display, and initial load. Integrate into CI so UI regressions are detected. Acceptance: core E2E tests run in CI and pass.
- [ ] **5.8 Follow-up ideas**: small feature ideas to consider after UI baseline is complete:
  - Dark mode toggle
  - Saved searches / permalinked filters
  - CSV export of current results
  - Notification alerts (email/Telegram) for new matching offers
  - Analytics views (salary averages by region) — ties to Sprint 5/6

### 📧 Sprint 6: Notifications
- [x] **6.1 DB schema**: New tables `subscriptions` (email, keywords array, confirmation token, unsubscribe token) and `notification_queue` (idempotent work queue per subscriber/offer pair). New column `job_offers.notified_at` to track which offers have been processed. (details: docs/sprints/sprint_6_1_notifications_schema.md)
- [x] **6.2 Email sender module** (`src/notifications/email.py`): Async SMTP client via `aiosmtplib`. HTML + plain-text multipart emails from Jinja2 templates. Config via env vars. (details: docs/sprints/sprint_6_2_email_sender.md)
- [x] **6.3 Subscription router** (`src/web/routers/subscriptions.py`): `POST /subscribe`, `GET /confirm/{token}` (double opt-in, 24h expiry), `GET /unsubscribe/{token}` (one-click, no auth). (details: docs/sprints/sprint_6_3_subscription_router.md)
- [x] **6.4 Subscription UI**: Subscribe form linked from topbar + confirmation/unsubscribe result pages. (details: docs/sprints/sprint_6_4_subscription_ui.md)
- [x] **6.5 Keyword matcher** (`src/notifications/matcher.py`): DB-level `unaccent ILIKE` match of subscriber keywords against new offer titles.
- [x] **6.6 Immediate notification script** (`scripts/notify_new_offers.py`): Called by `ingest_all.py` after each ingestion. Queues and sends one email per subscriber for each new matching offer. Uses `notified_at IS NULL` as the new-offer marker.
- [x] **6.7 Weekly digest script** (`scripts/weekly_digest.py`): Standalone cron script. Sends one grouped email per subscriber with all matching offers from the past 7 days.
- [ ] **6.8 Hook into `ingest_all.py`**: Call `notify_new_offers.py` after `close_stale_offers.py` (non-fatal, forwards `--dry-run`).
- [ ] **6.9 Env vars & Dokploy crons**: `SMTP_*` vars + `APP_BASE_URL`. Two new cron services: `eepp-worker-digest` (Mondays 09:00) and `eepp-worker-cleanup` (daily 02:00). (details: docs/sprints/sprint_6_notifications.md)

### 🔍 Sprint 7: Data Quality & Lifecycle
- [x] **7.1 Offer lifecycle flag (`is_active`)**: Add a boolean `is_active` column to `job_offers` (default `True`). A new script `scripts/close_stale_offers.py` sets `is_active = False` for offers in `postulacion` or `evaluacion` whose `close_date` is in the past and that no longer appear in any active TEEE or EEPP feed. The script is called at the end of every daily ingestion run (`scripts/ingest_all.py`). The `state` column is **never modified** — it preserves the portal-reported value. The web UI default query applies two conditions: `is_active = True` AND (`close_date IS NULL OR close_date >= CURRENT_DATE`). A filter toggle "Vencidas" passes `include_inactive=true` to the API, removing both conditions and showing all rows. **Design note:** TEEE keeps offers in its active index even after `close_date` elapses, so `close_stale_offers.py` currently closes 0 offers per run. The `close_date`-based filter in the query layer is the primary mechanism that hides stale offers; `is_active` is preserved as a pipeline-managed override for future use (e.g., manually deactivating specific offers). (details: docs/sprints/sprint_7_1_is_active_lifecycle.md)
