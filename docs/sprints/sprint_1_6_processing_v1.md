# Sprint 1.6 — Processing: external_id extraction & fingerprint V1

## Goal
Implement the processing layer that enriches each raw offer dict (produced by `EEPPClient`)
with two derived fields: `external_id` and `fingerprint`.

Update `EEPPClient._normalize_offer` to populate `source` from `TipoTxt` and call
the extraction functions.

## Scope
- New module: `src/processing/transformers.py`
- Modified: `src/ingestion/eepp_client.py` (`_normalize_offer`)
- No changes to `schemas.py` or `models.py` (fields already exist)
- No database interaction

---

## Module: `src/processing/transformers.py`

### Public API

```python
def extract_external_id(url: str) -> str | None: ...
def compute_fingerprint(source: str, external_id: str | None, *, title: str, institution: str, region: str | None) -> str: ...
```

### `extract_external_id(url)`

Extracts the source-native ID from the offer URL. Returns `None` if no stable ID exists.

| URL domain | Pattern | Result |
|:---|:---|:---|
| `empleospublicos.cl` | `?i=<id>` | `i` query-param value |
| `junji.myfront.cl` | `/oferta-de-empleo/<id>/slug` | path segment at index 2 |
| `*.trabajando.cl` | `/trabajo/<id>-slug` | numeric prefix before first `-` |
| anything else | — | `None` |

Edge cases:
- Empty or `None` URL → `None`
- Pattern present but value is empty string → `None`
- Non-numeric prefix for trabajando.cl → `None`

### `compute_fingerprint(...)`

Returns the MD5 hex digest (32 chars) used as deduplication key.

Rules (in order):
1. If `external_id` is not `None`:
   `MD5(f"{source}|{external_id}")`
2. If `external_id` is `None` (fallback):
   `MD5(f"{source}|{title or ''}|{institution or ''}|{region or ''}")`

---

## Changes to `EEPPClient._normalize_offer`

Map `TipoTxt` to `source` using the following table:

| TipoTxt (HTML-unescaped) | source |
|:---|:---|
| `Empleos Públicos` | `EEPP` |
| `Empleos Públicos Evaluación` | `EEPP` |
| `JUNJI` | `JUNJI` |
| `Invitación a Postular` | `EXTERNAL` |
| `DIFUSION` | `DIFUSION` |
| `Comisión Mercado Financiero` | `CMF` |
| (unknown / missing) | `EEPP` (default) |

Call `extract_external_id` and `compute_fingerprint` and include results in the
normalized dict under keys `external_id` and `fingerprint`.

> Note: HTML entities in `TipoTxt` must be unescaped (use `html.unescape`) before mapping.

---

## Tests: `tests/test_transformers.py`

Required test cases for `extract_external_id`:
- EEPP URL with `?i=` → returns the id string
- JUNJI URL with `/oferta-de-empleo/<id>/` → returns the id string
- trabajando.cl URL with numeric slug → returns the id string
- DIFUSION URL without id → returns `None`
- Empty string → returns `None`

Required test cases for `compute_fingerprint`:
- With `external_id` present → `MD5(source|external_id)`
- With `external_id = None` → `MD5(source|title|institution|region)`
- Deterministic: same inputs → same output

---

## Out of scope
- TEEE extraction rules (sprint 2.1)
- Any database writes
- Changes to `JobOfferSchema` or `JobOffer` model
