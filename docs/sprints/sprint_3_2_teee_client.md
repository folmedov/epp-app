# Sprint 3.2 — TEEE Client: ingestion and mapping

## Objective

Implement an async client that queries the `trabajaenelestado.cl` Elasticsearch endpoint, normalizes responses into the canonical schema, and hands records to the ingestion/upsert pipeline.

## Scope

- Implement `src/ingestion/teee_client.py` using `httpx.AsyncClient`.
- Map TEEE fields to canonical fields used by `job_offers` (title, institution, region, city, url, state, external_id, etc.).
- Compute `fingerprint` with existing `compute_fingerprint()` to allow cross-source matching.
- Provide unit tests that validate mapping against `docs/discovery/teee_*.json` fixtures.

## Field mapping (examples)

- `Cargo` -> `title`
- `Institucion/Entidad` -> `institution`
- `URL` -> `url`
- `Region` -> `region` (normalize prefix `Región de `)
- `Ciudad` -> `city`
- `Estado` -> `state`
- `ID Conv` -> `external_id` (fallback to `_id` if missing)

## Expected output

- `src/ingestion/teee_client.py` with: async fetcher, paginator support, normalizer function returning canonical dicts.
- Unit tests using the provided discovery fixtures.

## Acceptance criteria

- Client ingests sample fixture(s) and returns normalized records compatible with the pipeline's `upsert_job_offers` function.
