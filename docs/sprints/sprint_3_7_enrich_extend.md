# Sprint 3.7 — Enrich & Extend: `content_fingerprint` y `external_id` para TEEE

Objetivo
--------
Reducir colisiones en el fingerprint de contenido (Stage B) de registros TEEE
que no tienen un `external_id` confiable, extendiendo dos áreas:

1. **`content_fingerprint` enriquecido**: incluir campos adicionales estables
   además del cuarteto base (título, institución, región, ciudad) para
   discriminar mejor entre convocatorias distintas del mismo cargo.

2. **`extract_external_id` extendido**: añadir soporte para URLs de
   `directoresparachile.cl`, que representan un subconjunto significativo de
   registros TEEE sin `ID Conv` pero con PDF de convocatoria identificable.

Contexto y motivación
---------------------
Sprint 3.6 implementó la carga masiva de ofertas TEEE. Al ejecutar
`--state all --dry-run` se observó:

```
Removed 11989 duplicate fingerprint(s) from batch
Would have upserted 37613 row(s)
```

De los ~11 989 duplicados eliminados, la mayoría provienen de Stage B
(registros con `external_id_generated=True`). Estos registros usan como
fingerprint `MD5("content|" + content_fingerprint)`, donde `content_fingerprint`
se calcula sobre solo 4 campos: `title|institution|region|city`.

Muchas convocatorias de directores escolares comparten cargo ("Director(a)"),
institución ("ILUSTRE MUNICIPALIDAD DE ..."), región y ciudad, pero corresponden
a establecimientos distintos (cada establecimiento tiene su propio PDF y proceso).
Con solo 4 campos, estas filas colisionan en Stage B y el pipeline las descarta
como duplicados.

La URL es el campo más discriminante: cada convocatoria tiene un PDF con
identificador único en el path (e.g. `dee_1967_7707`). Cuando la URL contiene
ese ID, debe usarse como `external_id` (Stage A, confiable). Cuando no se puede
extraer, el `content_fingerprint` se enriquece con campos adicionales estables.

---

Cambio 1 — Extender `extract_external_id` para `directoresparachile.cl`
------------------------------------------------------------------------

### Patrón observado

Las URLs de convocatorias DEE siguen el patrón:
```
https://directoresparachile.cl/Repositorio/PDFConcursos/dee_<N>_<M>.pdf?<slug>
```

El segmento `dee_<N>_<M>` (ej. `dee_1967_7707`) es el identificador estable
de la convocatoria dentro del sistema DEE.

### Extracción propuesta

Dominio: `directoresparachile.cl`
Regla: extraer el nombre del archivo PDF sin extensión desde el path.
Formato: `dee_<N>_<M>` o variantes como `mduc_<N>_<M>_<fecha>_<X>`.

```python
# ejemplo
url = "https://directoresparachile.cl/Repositorio/PDFConcursos/dee_1967_7707.pdf?..."
# → external_id = "dee_1967_7707"
```

Implementación en `src/processing/transformers.py`, función `extract_external_id`:

```python
if "directoresparachile.cl" in domain:
    parts = [p for p in parsed.path.split("/") if p]
    if parts:
        filename = parts[-1]  # e.g. "dee_1967_7707.pdf?..."
        stem = filename.split("?")[0].removesuffix(".pdf")
        return stem if stem else None
```

### Impacto

Los registros que hoy caen en Stage B (fingerprint de contenido) pasarían
a Stage A (fingerprint de `external_id`), que es estable y no colisiona entre
convocatorias del mismo cargo.

---

Cambio 2 — Enriquecer `compute_content_fingerprint`
----------------------------------------------------

Para los registros que **no** tienen URL o cuya URL no permite extraer un ID
(URLs genéricas con dominio sin patrón), el Stage B se enriquece con campos
adicionales que son estables entre ejecuciones.

### Campos adicionales propuestos

Estos campos también se añadirán como columnas en `job_offers` (ver Cambio 5).

| Campo TEEE | Campo EEPP | Nombre columna/Python | Justificación |
|---|---|---|---|
| `Ministerio` | `Ministerio` | `ministry` | Discrimina por ministerio/entidad contratante (≠ institución directa) |
| `Fecha inicio Convocatoria` | `Fecha Inicio` | `start_date` | Fecha de inicio del proceso; estable una vez publicada |
| `Tipo Convocatoria` | *(no aplica)* | `conv_type` | `DEE`, `ADP`, `EEPP`, etc. (solo TEEE; `None` para EEPP) |
| `Fecha cierre Convocatoria` | `Fecha Cierre Convocatoria` | `close_date` | Fecha límite de postulación; muy discriminante entre convocatorias |

### Nueva firma

```python
def compute_content_fingerprint(
    title: str,
    institution: str,
    region: str | None,
    city: str | None,
    *,
    ministry: str | None = None,
    start_date: str | None = None,
    conv_type: str | None = None,
    close_date: str | None = None,
) -> str:
```

Todos los campos nuevos son opcionales con default `None` para mantener
compatibilidad con cualquier fuente que no los exponga.

### Normalización

Los campos de texto se normalizan igual que los existentes: `strip().lower()`.
Las fechas (`start_date`, `close_date`) se incluyen tal como vienen del source
(string), sin parsear, para evitar variaciones de formato entre fuentes.

### Ejemplo

```
title|institution|region|city|ministry|start_date|conv_type|close_date
"director(a)|liceo técnico profesional mary graham|valparaíso|villa alemana|...|26/01/2023 0:00:00|dee|09/03/2023 23:59:00"
```

---

Cambio 3 — Actualizar `TEEEClient._normalize_hit`
--------------------------------------------------

Pasar los cuatro campos nuevos al llamar `compute_content_fingerprint` y
exponer los valores en el dict de retorno para que lleguen a `job_offers`:

```python
ministry = src.get("Ministerio")
start_date = src.get("Fecha inicio Convocatoria")
conv_type = src.get("Tipo Convocatoria")
close_date = src.get("Fecha cierre Convocatoria")

content_fingerprint = compute_content_fingerprint(
    title or "",
    institution or "",
    region,
    city,
    ministry=ministry,
    start_date=start_date,
    conv_type=conv_type,
    close_date=close_date,
)
```

Lo mismo aplica para `EEPPClient._normalize_offer`, usando los nombres de
campo propios de EEPP: `Ministerio`, `Fecha Inicio`, `Fecha Cierre Convocatoria`
(`conv_type=None` ya que EEPP no tiene equivalente).

---

Cambio 4 — Campo `_elastic_id` en `raw_data`
---------------------------------------------

Cuando TEEE no provee `external_id` confiable, se usa el `_id` del documento
Elasticsearch como fallback (`external_id = "teee:_id:{_id}"`). Para
preservar trazabilidad, este `_id` se inyecta en `raw_data` bajo la clave
`_elastic_id`:

```python
raw_data = dict(src)
if hit.get("_id") is not None:
    raw_data["_elastic_id"] = hit["_id"]
```

Este campo **no proviene del source API**; es añadido por el pipeline durante
la normalización. Ver documentación en `architecture.md`.

---

Cambio 5 — Nuevas columnas en `job_offers`
------------------------------------------

Los cuatro campos se añaden como columnas opcionales (`nullable=True`) al
modelo `JobOffer` y al schema `JobOfferSchema`:

| Columna | Tipo SQL | Tipo Python | Fuente TEEE | Fuente EEPP |
|---|---|---|---|---|
| `ministry` | `VARCHAR(255)` | `str \| None` | `Ministerio` | `Ministerio` |
| `start_date` | `VARCHAR(64)` | `str \| None` | `Fecha inicio Convocatoria` | `Fecha Inicio` |
| `close_date` | `VARCHAR(64)` | `str \| None` | `Fecha cierre Convocatoria` | `Fecha Cierre Convocatoria` |
| `conv_type` | `VARCHAR(64)` | `str \| None` | `Tipo Convocatoria` | `None` (no aplica) |

Las fechas se almacenan como strings (el formato del source, e.g.
`"26/01/2023 0:00:00"`) para no introducir lógica de parseo en esta fase.
No se añade índice por defecto; pueden indexarse en un sprint posterior si
se requieren queries por fecha.

Se requiere una migración Alembic (`0004_add_ministry_dates_conv_type.py`)
para añadir las 4 columnas a la tabla existente.

### Cambios en `_SCHEMA_FIELDS` de `scripts/load_teee.py`

Añadir los 4 nuevos nombres al set:

```python
"ministry", "start_date", "close_date", "conv_type"
```

---

Archivos modificados
--------------------

| Archivo | Cambio |
|---|---|
| `src/processing/transformers.py` | `extract_external_id`: nuevo caso `directoresparachile.cl`; `compute_content_fingerprint`: 4 parámetros nuevos opcionales |
| `src/ingestion/teee_client.py` | `_normalize_hit`: extrae y pasa los 4 campos nuevos; usa `_elastic_id` en `raw_data` |
| `src/ingestion/eepp_client.py` | `_normalize_offer`: extrae `ministry`, `start_date`, `close_date` (los expone en el dict de retorno) |
| `src/core/schemas.py` | `JobOfferSchema`: añadir `ministry`, `start_date`, `close_date`, `conv_type` como `str \| None = None` |
| `src/database/models.py` | `JobOffer`: añadir las 4 columnas `String(255/64)`, `nullable=True` |
| `src/database/repository.py` | Incluir los 4 campos en la lista de columnas del upsert |
| `scripts/load_teee.py` | `_SCHEMA_FIELDS`: añadir los 4 nombres nuevos |
| `alembic/versions/0004_add_ministry_dates_conv_type.py` | Migración: `op.add_column` × 4 en `job_offers` |
| `tests/test_transformers.py` | Tests para nueva URL DEE; tests para fingerprint enriquecido con 4 campos |
| `tests/test_teee_client.py` | Verificar que los 4 campos nuevos se pasan y que `_elastic_id` aparece en `raw_data` |
| `tests/test_eepp_client.py` | Verificar que `ministry`, `start_date`, `close_date` se extraen correctamente |

---

Criterios de aceptación
------------------------

- [ ] `extract_external_id("https://directoresparachile.cl/Repositorio/PDFConcursos/dee_1967_7707.pdf?slug")` → `"dee_1967_7707"`
- [ ] `compute_content_fingerprint` produce hashes distintos para dos convocatorias con mismo cargo/institución pero distinta `close_date` o `start_date`
- [ ] El batch `--state all --dry-run` produce menos de 5 000 duplicados eliminados (vs ~11 989 actuales)
- [ ] `raw_data["_elastic_id"]` presente en los registros con `external_id_generated=True`
- [ ] Las columnas `ministry`, `start_date`, `close_date`, `conv_type` existen en `job_offers` tras aplicar la migración 0004
- [ ] Los valores se persisten correctamente en un dry-run con `--out` y se inspeccionan en el JSON de salida
- [ ] Todos los tests existentes pasan (`pytest -q`)
