# Requirements Specification: Job Tracker (EEPP & TEEE)

## 1. Project Goal
Build an automated ETL pipeline to track Chilean public sector job offers, prioritizing EEPP for fresh data and TEEE for historical state tracking.

## 2. Status Tracker (Sprints)

### 🏗️ Sprint 1: Foundation & EEPP Ingestion
- [ ] **1.1 Project Setup**: Initialize folder structure and environment variables (`.env`, `config.py`).
- [x] **1.1 Project Setup**: Initialize folder structure and environment variables (`.env`, `config.py`).
- [x] **1.2 EEPP API Discovery**: Identify endpoints, available statuses, payload structure, key fields, pagination mechanism, and scraping risks.
- [ ] **1.3 EEPP Client**: Implement async extractor for `empleospublicos.cl` (Status: postulacion/evaluacion).
- [ ] **1.4 Data Models**: Define Pydantic schemas for validation and SQLAlchemy models for Neon.
- [ ] **1.5 Processing**: Implement `fingerprint` V1 logic (title + institution + region + salary).
- [ ] **1.6 Loading**: Implement Upsert logic in PostgreSQL (Neon) using `ON CONFLICT`.

### ⏳ Sprint 2: TEEE Integration & Tracking
- [ ] **2.1 TEEE Client**: Implement async extractor for `trabajaenelestado.cl`.
- [ ] **2.2 Matching Logic**: Link TEEE records with EEPP via `fingerprint` and `ID Conv`.
- [ ] **2.3 State Observer**: Update records to "finalizada" if they disappear from EEPP but exist in TEEE.

### 📊 Sprint 3: Analysis & Reporting
- [ ] **3.1 Analytics Views**: Create SQL views in Postgres for salary averages and regional demand.
- [ ] **3.2 Notification System**: Simple script to alert of new matches via Telegram/Email.

---

## 3. Business Rules (Current)
- **Identity**: The `fingerprint` is the primary key for deduplication.
- **Source Priority**: EEPP is the "Master" for salary data.
- **Audit**: Every record must store the original JSON in a `raw_data` (JSONB) column.