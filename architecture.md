# Architecture Specification: Job Tracker (EEPP & TEEE)

## 1. System Overview
An ETL (Extract, Transform, Load) pipeline written in Python to synchronize job offers from Chilean public sector portals (EEPP and TEEE) into a Neon (PostgreSQL) database for tracking and data analysis.

## 2. Project Directory Structure
All source code must reside in the `src/` directory following this layout:

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
│   └── main.py                  # Entry point (Orchestrator)
├── requirement.md               # Business logic and functional specs
├── architecture.md              # This file
├── docker-compose.yml           # Infrastructure as code
└── .env                         # Secrets (Database URL, API Keys)
```  

## 3. Database Schema (PostgreSQL / Neon)
The primary table is job_offers. It must support high-performance analysis and JSON audit.

|Column|Type|Description|
|:---|:---|:---|
|id|UUID|Primary Key (Default: uuid_generate_v4())
|fingerprint|String(32)|Unique Index. MD5 hash of core fields (Identity)|
|external_id|String|Original ID from EEPP/TEEE (if available)|
|source|String|'EEPP' or 'TEEE'|
|title|String|Job position name (Cargo)|
|institution|String|Name of the public institution|
|salary_bruto|Numeric|Monthly gross salary (Nullable for TEEE)|
|state|String|Current state (postulacion, evaluacion, finalizada)|
|region|String|Geographical region in Chile|
|city|String|City or commune|
|url|String|Direct link to the job offer|
|raw_data|JSONB|Full original JSON from the API for auditing|
|created_at|Timestamp|Automatic record creation time (UTC)|
|updated_at|Timestamp|Time of last state change or update (UTC)|

## 4. Technical Constraints
* ORM: SQLAlchemy 2.0 using the `AsyncAttrs` mixin and `AsyncSession`.
* Drivers: `asyncpg` for PostgreSQL connection.
* Deduplication: Use PostgreSQL `ON CONFLICT (fingerprint) DO UPDATE` to ensure idempotency.
* Schemas: Every database interaction must be preceded by a Pydantic `JobOffer` schema validation.

## 5. Data Flow (The Pipeline)
1. Extraction: `EEPPClient` fetches active offers (hot data).
2. Transformation: `transformers.py` cleans text and generates the `fingerprint` based on: `title + institution + region + salary_bruto`.
3. Persistence: `main.py` calls the database layer to perform an Upsert (Insert new or Update state if fingerprint exists).
