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
|fingerprint|String(32)|Unique Index. MD5 hash for deduplication — see Fingerprint Strategy below|
|external_id|String|Source-native ID (if extractable) — see External ID Rules below|
|source|String|Origin of the offer — see Source Values below|
|title|String|Job position name (Cargo)|
|institution|String|Name of the public institution|
|salary_bruto|Numeric|Monthly gross salary (Nullable when not published)|
|state|String|Current state: `postulacion`, `evaluacion`, `finalizada`|
|region|String|Geographical region in Chile|
|city|String|City or commune|
|url|String|Current-state URL. Not stable across state transitions for EEPP records.|
|raw_data|JSONB|Full original JSON from the API for auditing|
|created_at|Timestamp|Automatic record creation time (UTC)|
|updated_at|Timestamp|Time of last state change or update (UTC)|

### Source Values

The EEPP portal acts as an aggregator. The `TipoTxt` field in the raw payload identifies the actual origin.
Mapping used for the `source` column:

| TipoTxt (raw, HTML-unescaped) | source value |
|:---|:---|
| `Empleos Públicos` / `Empleos Públicos Evaluación` | `EEPP` |
| `JUNJI` | `JUNJI` |
| `Invitación a Postular` | `EXTERNAL` |
| `DIFUSION` | `DIFUSION` |
| `Comisión Mercado Financiero` | `CMF` |
| (TEEE portal — sprint 2) | `TEEE` |

### External ID Rules

Extraction depends on URL domain and structure:

| Domain | Pattern | Extraction |
|:---|:---|:---|
| `empleospublicos.cl` | `?i=<id>` query param | `i` value (e.g. `139281`) |
| `junji.myfront.cl` | `/oferta-de-empleo/<id>/slug` | path segment after `/oferta-de-empleo/` |
| `*.trabajando.cl` | `/trabajo/<id>-slug` | numeric prefix before first `-` |
| `educacionpublica.gob.cl`, `renca.cl`, etc. | No stable ID | `None` |

### Fingerprint Strategy

- **When `external_id` is available**: `MD5(source + "\|" + external_id)`
  - Stable across URL changes (e.g. postulacion → evaluacion URL change in EEPP)
- **When `external_id` is None** (DIFUSION, generic external links): `MD5(source + "\|" + title + "\|" + institution + "\|" + region)`
  - Higher collision risk; acceptable for the small volume of these records

### Observations:
- The URL field is **not stable** across state transitions for EEPP records (the `i` param stays the same but the path changes from `convpostularavisoTrabajo.aspx` to `convFicha.aspx`).
- The fingerprint is the deduplication key within and across sources.
- Cross-source linking (EEPP ↔ TEEE) will be addressed in sprint 2.2 using `external_id` once TEEE structure is known.