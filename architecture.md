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
│   └── main.py                  # Entry point (Orchestrator)
├── requirement.md               # Business logic and functional specs
├── architecture.md              # This file
├── docker-compose.yml           # Infrastructure as code
└── .env                         # Secrets (Database URL, API Keys)
```  

## 2. Database Schema (PostgreSQL / Neon)
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

### Observations:
- The system uses a fingerprint as the deduplication key across sources.