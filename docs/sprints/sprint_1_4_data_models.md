# Story: 1.4 Data Models V1

## Objective
Define the first canonical internal data contract for job offers using Pydantic schemas and SQLAlchemy models.

## Scope
Includes:
- align field names with architecture.md
- implement JobOfferSchema in src/core/schemas.py
- implement JobOffer model in src/database/models.py
- include the canonical fields required for EEPP V1 flow
- keep fingerprint present but optional in this iteration

Does not include:
- fingerprint generation logic
- persistence/upsert logic
- TEEE-specific matching rules
- final model hardening for later stages

## Canonical Fields
- id
- fingerprint
- external_id
- source
- title
- institution
- salary_bruto
- state
- region
- city
- url
- raw_data
- created_at
- updated_at

## V1 Contract Rules
- required: source, title, institution, state, raw_data
- optional: id, fingerprint, external_id, salary_bruto, region, city, url, created_at, updated_at
- use raw_data instead of json_raw
- use state instead of status
- use external_id instead of source_id
- use salary_bruto instead of sueldo_bruto

## Definition of Done
A first Pydantic schema and SQLAlchemy model exist, share the same canonical field names, and are compatible with the EEPP client output and target architecture.