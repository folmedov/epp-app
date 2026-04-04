# Gestión de Duplicidad: Fingerprints y External IDs

Documento de referencia consolidado que describe el mecanismo implementado para
identificar y deduplicar registros de ofertas de empleo. Unifica el contenido de
`fingerprint_generation.md` y `teee_external_id_policy.md`.

---

## 1. Contexto y motivación

Las fuentes (TEEE, EEPP, otros portales) publican la misma oferta de empleo
varias veces a lo largo del tiempo: al crearla, al modificarla, al re-indexarla
o al publicarla simultáneamente en múltiples portales. El pipeline necesita una
clave de identidad estable para garantizar que cada oferta canónica se almacene
una sola vez en `job_offers` aunque llegue por distintos caminos o instantes.

La estrategia se apoya en dos tipos de clave:

- **Stage A — External ID**: identificador extraído o provisto directamente por
  el portal. Estable e inequívoco cuando existe.
- **Stage B — Content fingerprint**: hash construido a partir de campos del
  contenido de la oferta. Se usa como fallback cuando no hay ID externo fiable.

### Principios de diseño

- **Determinismo**: el mismo input debe producir siempre la misma huella, sin importar cuántas veces se ejecute el pipeline.
- **Separación de responsabilidades**: `external_id` y metadatos por fuente se almacenan en `job_offer_sources`; la clave canónica se guarda únicamente en `job_offers.fingerprint`.
- **Seguridad operativa**: `content_fingerprint` es heurístico — su uso para merges automáticos debe acompañarse de reglas adicionales (prefer_source, revisión humana, umbral de similitud) para minimizar falsos positivos.
- **Tratamiento de ausencias**: los campos opcionales de Stage B se tratan como cadena vacía para garantizar determinismo cuando los datos están incompletos.

---

## 2. External ID: extracción y validación

### 2.1 Campo `ID Conv` (TEEE)

Cuando el hit de Elasticsearch incluye el campo `ID Conv` con un valor
**puramente numérico**, ese valor se normaliza a string y se usa directamente
como `external_id` en el schema `JobOfferSchema`.

```python
external_id = str(int(raw_id_conv))   # ej. "12345"
external_id_generated = False
```

Si `ID Conv` no es puramente numérico o está ausente, se pasa al siguiente paso.

### 2.2 Extracción desde la URL — `extract_external_id()`

`src/processing/transformers.py::extract_external_id(url)` intenta extraer un
identificador estable desde la URL de la oferta aplicando reglas por dominio:

| Dominio                  | Extracción                                          | Notas |
|--------------------------|-----------------------------------------------------|-------|
| `empleospublicos.cl`     | Query param `?i=<id>`                               | |
| `junji.myfront.cl`       | Segmento de path `/oferta-de-empleo/<id>/slug`      | |
| `*.trabajando.cl`        | Prefijo numérico en `/trabajo/<id>-slug`            | |
| `directoresparachile.cl` | Query param `?i=<id>` **únicamente**                | Los stems de PDF (ej. `dee_18099`) no son únicos: el mismo archivo se reutiliza para convocatorias distintas en distintos años. Si `?i=` no está presente, se devuelve `None`. |
| cualquier otro dominio   | `None`                                              | Fuerza Stage-B |

Cuando `extract_external_id` devuelve `None`, el ID provisional se genera en el
paso siguiente.

### 2.3 Fallback: ID basado en `_id` de Elasticsearch

Si no se obtuvo un `external_id` fiable, se genera uno desde el `_id` del
documento en el índice:

```python
external_id = f"teee:_id:{_id}"
external_id_generated = True
external_id_fallback_type = "index_id"
```

Este valor identifica el registro dentro de la instantánea actual del índice.
Se marca explícitamente como generado porque no es garantía de estabilidad
permanente si el índice se re-indexa.

### 2.4 Campo `external_id_generated`

El flag `external_id_generated` (almacenado en `JobOfferSchema`) controla qué
etapa del fingerprint se aplica:

- `False` → Stage A (external_id fiable, se usa directamente).
- `True`  → Stage B (content fingerprint), ignorando el valor de `external_id`.

---

## 3. Fingerprints: algoritmo implementado

### 3.1 Vista general

```
¿external_id IS NOT NULL AND external_id_generated = False?
│
├─ SÍ ──► fingerprint = MD5("source_id|{source}|{external_id}")   [Stage A]
│
└─ NO ──► content_fp  = MD5("{title}|{institution}|{region}|{city}|
│                             {ministry}|{start_date}|{conv_type}|{close_date}")
│         fingerprint = MD5("content|{content_fp}")               [Stage B]
│         (campos ausentes → cadena vacía "")
```

Los prefijos `"source_id|"` y `"content|"` garantizan que los dos espacios de
hashes no colisionen aunque un `external_id` fuera casualmente igual al hash
de un fingerprint de contenido.

### 3.2 Stage A — External ID fingerprint

Función: `compute_fingerprint(..., external_id=<id>, external_id_generated=False)`

```python
raw = f"source_id|{source}|{external_id}"
fingerprint = hashlib.md5(raw.encode("utf-8")).hexdigest()  # 32 hex chars
```

El prefijo `source` hace que el fingerprint sea único por fuente (dos proveedores
con el mismo ID numérico generan fingerprints distintos), lo que evita falsos
positivos en Stage A.

### 3.3 Stage B — Content fingerprint

Función: `compute_content_fingerprint()` + `compute_fingerprint()` con
`external_id=None` o `external_id_generated=True`.

**Paso 1 — hash intermedio del contenido:**

```python
parts = [
    title.strip().lower(),
    institution.strip().lower(),
    (region   or "").strip().lower(),
    (city     or "").strip().lower(),
    (ministry or "").strip().lower(),   # campo introducido en Sprint 3.7
    (start_date  or ""),                # fecha incluida sin normalizar
    (conv_type or "").strip().lower(),  # campo introducido en Sprint 3.7
    (close_date  or ""),                # fecha incluida sin normalizar
]
content_fp = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
```

**Paso 2 — fingerprint canónico:**

```python
fingerprint = hashlib.md5(f"content|{content_fp}".encode("utf-8")).hexdigest()
```

**Por qué 8 campos (Sprint 3.7):** Antes de Sprint 3.7, Stage B solo usaba
`title|institution|region|city`. Esto producía colisiones falsas cuando el mismo
cargo se convocaba más de una vez (distintas fechas, ministerios distintos) porque
el título e institución son idénticos. Los campos `ministry`, `start_date`,
`conv_type` y `close_date` diferencian convocatorias distintas del mismo cargo.
Los campos ausentes se tratan como cadena vacía para mantener compatibilidad
regresiva con registros anteriores al Sprint 3.7 (solo si todos esos campos
son `None`).

> **Nota — normalización de texto (implementación actual vs. recomendada):**
> El código actual aplica únicamente `strip().lower()`. La especificación original
> sugería un pipeline más completo (unicode NFKD + eliminación de diacríticos +
> colapso de espacios + eliminación de puntuación); ese nivel de normalización
> **aún no está implementado**. En consecuencia, dos registros que difieran
> únicamente en acentos o puntuación producirán fingerprints Stage-B distintos
> en lugar de unirse. Ver §10.6 en posibles mejoras futuras.

---

## 4. Persistencia del fingerprint

### 4.1 Tabla `job_offers`

La columna `fingerprint` (`String(32)`, `UNIQUE`, `INDEX`) es la clave canónica.
Se calcula antes del upsert y es el único campo que determina si una fila es
nueva o actualización de una existente.

Columnas actualizadas en cada `ON CONFLICT (fingerprint) DO UPDATE`:
`state`, `url`, `salary_bruto`, `ministry`, `start_date`, `close_date`,
`conv_type`, `updated_at`.

Columnas que **no** se actualizan en conflicto (inmutables tras la primera
inserción): `id`, `created_at`, `source`, `title`, `institution`, `region`,
`city`.

### 4.2 Tabla `job_offer_sources`

Almacena el registro original por fuente con los campos `external_id`, `raw_data`
y `original_state`. La columna `job_offer_id` apunta al canónico en `job_offers`.

Estado actual: la tabla existe en el esquema y `scripts/migrate_raw_to_sources.py`
puede poblarla desde `job_offers.raw_data` (backfill idempotente). El loader
principal (`scripts/load_teee.py`) **no escribe en esta tabla** en el flujo normal.

La tabla define `UniqueConstraint("source", "external_id")`: dos filas del mismo
proveedor no pueden compartir el mismo `external_id`. Un intento de inserción
duplicada sin `ON CONFLICT DO NOTHING` producirá un error de integridad en la
base de datos; el pipeline debe deduplicar antes de llegar al insert.

> **Precaución de backfill:** calcular `content_fingerprint` directamente en SQL
> es frágil porque SQL no replica fielmente la normalización Python. Usar siempre
> un script Python (como `migrate_raw_to_sources.py`) que ejecute el mismo
> pipeline de normalización.

### 4.3 Schema `JobOfferSchema`

Los campos `external_id`, `external_id_generated`, `external_id_fallback_type` y
`content_fingerprint` existen en el schema Pydantic como campos de transporte
entre el cliente de ingestión y el repositorio. No se persisten en `job_offers`
(ese modelo solo almacena `fingerprint`).

---

## 5. Deduplicación en el repositorio (`upsert_job_offers`)

El proceso de upsert implementado en `src/database/repository.py` aplica dos
niveles de deduplicación:

1. **En memoria (dentro del batch):** Antes de enviar al DB, se construye un
   diccionario `{fingerprint → row}` que conserva la última ocurrencia para cada
   fingerprint. Esto elimina duplicados dentro del mismo batch de ingestión.

2. **En base de datos (`ON CONFLICT ... DO UPDATE`):** Si ya existe una fila con
   el mismo fingerprint en `job_offers`, se actualizan los campos mutables. El
   `id` y `created_at` originales se preservan.

**Chunking dinámico:** asyncpg tiene un límite de 32 767 parámetros por sentencia.
El tamaño del chunk se calcula dinámicamente:

```python
safe_chunk = max(1, 32_767 // (params_per_row + 1))
# Con 14 columnas/fila → chunk = 2184 filas
```

**Validación de esquema:** Al inicio del upsert se verifica que las columnas
`ministry`, `start_date`, `close_date` y `conv_type` existan en el modelo ORM;
si faltan (migraciones no aplicadas) falla rápido con un mensaje claro en lugar
de un error críptico de SQL.

---

## 6. Normalización de estados (TEEE)

La fuente TEEE usa variaciones ortográficas para algunos estados. El cliente
de ingestión normaliza antes de crear el schema:

- `"finalizadas"` → `"finalizada"`

(Otras normalizaciones similares se aplican en el cliente TEEE.)

---

## 7. Detección de duplicados en reportes

`scripts/report_teee_duplicates.py` permite auditar duplicados en la base de
datos agrupando filas por fingerprint:

```bash
PYTHONPATH=. uv run python scripts/report_teee_duplicates.py \
    --state postulacion \
    --out reports/teee_duplicates_postulacion.json
```

Genera un JSON con `summary` (total de grupos duplicados, total de filas extra)
y `groups` (lista de grupos con más de 1 miembro). Se puede pasar `--sample N`
para limitar el número de grupos devueltos.

---

## 8. Política de fuente canónica

TEEE es la fuente principal (*source of truth*) del pipeline:

- Solo los registros de TEEE deben crear o actualizar filas canónicas en `job_offers`.
- Los registros de EEPP representan una *foto temporal* de la convocatoria y deben
  tratarse como pendientes de verificación hasta que TEEE confirme la misma oferta
  mediante `external_id` o `content_fingerprint`.
- En la implementación actual, EEPP y TEEE compiten en igualdad de condiciones en
  el upsert (no hay control técnico `prefer_source` activo). La distinción es
  una política de datos intencionada; su implementación técnica está descrita en
  §10.3 (columna `pending_verification`).

---

## 9. Riesgos y compensaciones

**Colisiones MD5:** MD5 genera 32 caracteres hexadecimales (128 bits). Las colisiones
son teóricamente posibles pero extremadamente raras a la escala de este dataset.
Si se requiriera mayor resistencia criptográfica, se puede migrar a SHA-256
truncado (mayor storage y coste de cómputo).

**Falsos positivos en Stage B:** `content_fingerprint` puede unir dos ofertas distintas
si comparten título, institución, región, ciudad, ministerio, tipo y fechas idénticos.
Este riesgo es bajo para datos reales pero existe. El uso automático de Stage-B
para merges debe acompañarse de al menos una de estas salvaguardas:

- Preferencia de fuente (`prefer_source`) para descartar matches ambiguos.
- Revisión humana de los candidatos de merge.
- Score de similitud adicional (fuzzy matching sobre campos secundarios).

**Inestabilidad del `_id` de Elasticsearch:** El fallback `teee:_id:{_id}` está
vinculado al índice actual. Si el índice se re-indexa, el mismo documento puede
recibir un `_id` distinto, rompiendo la continuidad del fingerprint Stage-A para
esa oferta. Por eso se marca con `external_id_generated = True` y se trata como
Stage-B en el fingerprint canónico.

---

## 10. Posibles mejoras futuras

Las siguientes funcionalidades fueron diseñadas pero **no están implementadas**
en el código actual.

### 10.1 Cross-source fingerprint (Stage A sin prefijo de fuente)

Permitiría unir registros de distintas fuentes (TEEE + EEPP) cuando ambos
comparten el mismo `external_id`:

```python
# Activable vía parámetro cross_match=True (no implementado)
raw = f"source_id|{external_id}"   # sin {source}
fingerprint = hashlib.md5(raw.encode()).hexdigest()
```

Riesgo conocido: si dos proveedores usan el mismo esquema de IDs con semánticas
distintas, se producirían falsos positivos.

> **Precaución operativa:** Si esta funcionalidad se expone como opción CLI
> (`--cross-match-external-id`), debe habilitarse con cautela. Proveedores cuyos
> rangos de IDs se solapan con semánticas distintas producirían merges incorrectos;
> revertirlos requiere intervención manual en la base de datos.

### 10.2 `per_source_fingerprint` en `job_offer_sources`

Añadir una columna `per_source_fingerprint String(32)` a `job_offer_sources`
para acelerar búsquedas de deduplicación dentro de una fuente y facilitar el
debugging sin necesidad de recalcular el hash.

### 10.3 `pending_verification` en `job_offer_sources`

Marcar registros de EEPP como pendientes de comprobación hasta que TEEE
confirme la misma oferta mediante `external_id` o `content_fingerprint`:

```sql
-- Migración propuesta (no aplicada)
ALTER TABLE job_offer_sources ADD COLUMN pending_verification boolean NOT NULL DEFAULT false;
UPDATE job_offer_sources SET pending_verification = true WHERE source = 'EEPP';
```

Esto reflejaría la política de "TEEE como fuente canónica" a nivel de datos.

### 10.4 Escritura continua de `job_offer_sources` en el flujo de ingestión

Actualmente `job_offer_sources` solo se puebla via backfill
(`scripts/migrate_raw_to_sources.py`). Se propone modificar `upsert_job_offers`
o crear un paso adicional para insertar la fila de fuente durante el flujo
normal de carga.

### 10.5 Script de reconciliación cross-source

`scripts/reconcile_sources.py` (referenciado en docs pero no creado) que
itere filas en `job_offer_sources` con `job_offer_id = NULL` o
`pending_verification = true` e intente ligarlas a canónicos por
`content_fingerprint` o por `external_id` proveniente de TEEE.

### 10.6 Pipeline de normalización de texto completo

Implementar en `compute_content_fingerprint` la secuencia completa sugerida por
la especificación original:

1. `unicodedata.normalize('NFKD', s)` — descomponer caracteres compuestos.
2. Eliminar categorías unicode `Mn` (diacríticos).
3. Colapsar cualquier secuencia de whitespace a un espacio simple.
4. Eliminar puntuación básica (excepto la que forme parte de IDs).
5. `strip()` + `lower()`.

Esto permitiría que registros con "Director Académico" y "Director Academico"
produzcan el mismo fingerprint Stage-B y se consoliden en el mismo canónico.

---

## 11. Referencias

| Archivo | Propósito |
|---------|-----------|
| `src/processing/transformers.py` | `extract_external_id`, `compute_content_fingerprint`, `compute_fingerprint` |
| `src/database/repository.py` | `upsert_job_offers` (deduplicación, chunking, ON CONFLICT) |
| `src/database/models.py` | `JobOffer`, `JobOfferSource` (esquema de tablas) |
| `src/core/schemas.py` | `JobOfferSchema` (DTO con campos de transporte) |
| `src/ingestion/teee_client.py` | Normalización del hit TEEE, asignación de `external_id` |
| `scripts/load_teee.py` | Loader principal — fetching + transformación + upsert |
| `scripts/report_teee_duplicates.py` | Auditoría de grupos duplicados por fingerprint |
| `scripts/migrate_raw_to_sources.py` | Backfill de `job_offer_sources` desde `job_offers` |
