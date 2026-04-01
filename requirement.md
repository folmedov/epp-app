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
- [ ] **2.2 Offers Query Layer**: Implement `src/web/queries.py` with async function to query `job_offers` filtering by `region`, `city`, and `institution` (optional params). Returns paginated results.
- [ ] **2.3 Offers List Page**: Implement `GET /` route in `src/web/routers/offers.py`. Full page renders `offers.html` with filter form and results table. Dropdown values populated from distinct DB values.
- [ ] **2.4 HTMX Dynamic Filtering**: Add `hx-get` on filter form to call `GET /offers/partial` and swap only the results table (`offers_table.html` partial) without full page reload.

### ⏳ Sprint 3: TEEE Integration & Tracking
- [ ] **3.1 TEEE Client**: Implement async extractor for `trabajaenelestado.cl`.
- [ ] **3.2 Matching Logic**: Link TEEE records with EEPP via `fingerprint` and `ID Conv`.
- [ ] **3.3 State Observer**: Update records to "finalizada" if they disappear from EEPP but exist in TEEE.

### 📊 Sprint 4: Analysis & Reporting
- [ ] **4.1 Analytics Views**: Create SQL views in Postgres for salary averages and regional demand.
- [ ] **4.2 Notification System**: Simple script to alert of new matches via Telegram/Email.