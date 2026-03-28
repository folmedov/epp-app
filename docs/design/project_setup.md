# Project Setup — Design

## Class Diagram

```mermaid
classDiagram
    class Config {
        +DATABASE_URL: str
        +APP_ENV: str
        +LOG_LEVEL: str
    }

    class JobOfferSchema {
        +id: int | None
        +source: str
        +source_id: str
        +title: str
        +description: str | None
        +sueldo_bruto: int | None
        +fingerprint: str
        +status: str
        +json_raw: object
        +created_at: datetime
        +updated_at: datetime
    }

    class JobOfferModel {
        +id: int
        +fingerprint: str
        +source: str
        +source_id: str
        +title: str
        +sueldo_bruto: int | None
        +status: str
        +json_raw: jsonb
        +created_at: timestamptz
        +updated_at: timestamptz
    }

    Config <|-- JobOfferSchema : uses
    JobOfferSchema <|-- JobOfferModel : persists
```

## Sequence Diagram

```mermaid
sequenceDiagram
    participant EEPP as API Client (EEPP/TEEE)
    participant Transformer as Transformer/Validator
    participant Repo as DB Repository
    participant Logger as Notifier/Logger

    EEPP->>Transformer: fetch job offer JSON
    Transformer->>Transformer: validate & compute fingerprint
    Transformer->>Repo: upsert by fingerprint (idempotent)
    Repo-->>Transformer: upsert result (created/updated)
    Transformer->>Logger: log success or IntegrityError
```

## Notes / Decisions
- `fingerprint`: MD5 hex string, unique constraint in DB.
- `sueldo_bruto`: stored as `Integer` (CLP) by default; can change to `Numeric` if decimals/precision required.
- `json_raw`: stored as JSONB for auditing.
- `status`: enum-like string (e.g., `active`, `finalizada`, `archived`) — soft delete semantics.

Persisted: `docs/design/project_setup.md`
