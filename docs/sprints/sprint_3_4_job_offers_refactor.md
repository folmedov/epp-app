Sprint 3.4 — Refactor: mover `external_id` fuera de `job_offers`
===============================================================

Objetivo
--------
- Eliminar la columna `external_id` de la tabla `job_offers` y mantener
  los identificadores externos por fuente únicamente en `job_offer_sources`.
- Asegurar que el enlace entre `job_offer_sources` y el registro canónico
  (`job_offers.id`) esté completo antes de eliminar la columna.

Motivación
----------
- Separar responsabilidades: `job_offers` contiene la entidad canónica; los
  identificadores por proveedor y el JSON crudo pertenecen a `job_offer_sources`.
- Evitar inconsistencias y duplicaciones al mantener `external_id` en un
  único lugar por origen.

Precondiciones
--------------
- Tener Alembic integrado (ya existe `migrations/env.py` y `migrations/versions`).
- Tener copia de seguridad del esquema y de los datos antes de aplicar cambios.
- Revisar y resolver duplicados en `job_offers` por `(source, external_id)`.

Resumen del plan
----------------
1. Ejecutar comprobaciones previas en la base de datos y asegurar cópias/backup.
2. Backfill (poblado) de `job_offer_sources.job_offer_id` usando los valores
   actuales en `job_offers` (coincidencia por `source` + `external_id`).
3. Revisar y resolver conflictos (casos con múltiples `job_offers` por mismo
   `(source, external_id)`).
4. Generar una migración Alembic que: (a) ejecute el backfill seguro; (b)
   elimine la columna `external_id` de `job_offers`.
5. Actualizar el código (modelos SQLAlchemy, repositorios, transformadores,
   pruebas) para dejar de usar `job_offers.external_id` y leer identificadores
   desde `job_offer_sources` cuando sea necesario.
6. Aplicar la migración en staging, ejecutar pruebas y, finalmente, ejecutar
   en producción.

Consultas y scripts útiles
-------------------------

Comprobaciones previas

-- Conteos básicos
SELECT count(*) FROM job_offers;
SELECT count(*) FROM job_offer_sources;

-- ¿Cuántos job_offers tienen external_id?
SELECT count(*) FROM job_offers WHERE external_id IS NOT NULL;

-- ¿Hay fuentes con registros de origen sin vínculo a job_offers?
SELECT count(*) FROM job_offer_sources WHERE job_offer_id IS NULL;

-- Detección de external_ids en sources que no tienen job_offer asociado
SELECT s.source, count(*) AS missing
FROM job_offer_sources s
LEFT JOIN job_offers j ON s.source = j.source AND s.external_id = j.external_id
WHERE j.id IS NULL
GROUP BY s.source
ORDER BY missing DESC;

-- Detección de duplicados en job_offers por (source, external_id)
SELECT source, external_id, count(*)
FROM job_offers
WHERE external_id IS NOT NULL
GROUP BY source, external_id
HAVING count(*) > 1;

Backfill SQL (sólo para filas con `external_id`)
---------------------------------------------
-- Este UPDATE asigna `job_offer_id` en `job_offer_sources` cuando existe una
-- fila coincidente en `job_offers` por (source, external_id).
UPDATE job_offer_sources s
SET job_offer_id = j.id
FROM job_offers j
WHERE s.job_offer_id IS NULL
  AND s.external_id IS NOT NULL
  AND s.source = j.source
  AND s.external_id = j.external_id;

Notas sobre el backfill
-----------------------
- Si existen múltiples `job_offers` que coinciden con la misma `(source, external_id)`
  hay que resolver cuál es la fila canónica (por ejemplo `ORDER BY updated_at DESC`)
  antes de ejecutar el UPDATE. Una estrategia segura:

  1. Detectar duplicados (consulta anterior).
  2. Para cada `(source, external_id)` duplicado, elegir el `id` canónico y
     actualizar `job_offer_sources` sólo apuntando a ese `id`.

Backfill avanzado (cuando `external_id` no existe en `job_offer_sources`)
-----------------------------------------------------------------------
- Si hay filas en `job_offer_sources` sin `external_id` (o que no coinciden),
  lo más fiable es realizar un script Python que:

  1. Calcule el `fingerprint` normalizado para cada `job_offer_sources.raw_data`.
  2. Busque la fila en `job_offers` por `fingerprint` y, si existe, actualice
     `job_offer_sources.job_offer_id` con el `job_offers.id` correspondiente.

  Ejemplo esquemático (pseudocódigo):

  ```py
  # conectar con asyncpg/SQLAlchemy
  for s in select(job_offer_sources where job_offer_id is null):
      fp = compute_fingerprint_from_raw(s.raw_data)
      j = select job_offers where fingerprint = fp
      if j:
          update job_offer_sources set job_offer_id = j.id where id = s.id
  ```

Generación de la migración Alembic
---------------------------------
1. Crear una nueva revisión:

```bash
export DATABASE_URL='postgresql+asyncpg://user:pass@host:5432/db'
PYTHONPATH=. alembic revision -m "refactor: drop external_id from job_offers" --autogenerate
```

2. Editar la revisión generada y añadir, en `upgrade()`:
   - `op.execute("<BACKFILL SQL>")` con la sentencia segura de backfill.
   - `op.drop_column('job_offers', 'external_id')`.

3. En `downgrade()` re-crear la columna `external_id` (nullable) y, opcionalmente,
   volver a rellenarla a partir de `job_offer_sources`:

```sql
UPDATE job_offers j
SET external_id = s.external_id
FROM job_offer_sources s
WHERE s.job_offer_id = j.id
  AND j.external_id IS NULL;
```

Política de resolución de conflictos
-----------------------------------
- En caso de múltiples `job_offers` para la misma `(source, external_id)`:
  - Preferir la fila con `updated_at` más reciente como canónica.
  - Registrar los duplicados en una tabla temporal o en un informe para
    revisión manual si hay ambigüedad.

Cambios de código requeridos
----------------------------
- `src/database/models.py`: eliminar la columna `external_id` de `JobOffer`.
- Reescribir consultas/repositorios que lean/escriban `job_offers.external_id`.
- Asegurarse de que el proceso de upsert escribe siempre en
  `job_offer_sources.external_id` y actualiza `job_offer_sources.job_offer_id`.
- Actualizar tests y fixtures que asuman `external_id` en `job_offers`.

Pruebas y verificación
----------------------
1. En staging: ejecutar la migración y correr la suite de tests.
2. Ejecutar consultas de verificación:
   - `SELECT count(*) FROM job_offer_sources WHERE job_offer_id IS NULL;` → debe ser 0.
   - `SELECT count(*) FROM job_offers WHERE external_id IS NOT NULL;` → debe ser 0.
3. Validar la aplicación web y el flujo de ingestión en modo dry-run.

Despliegue seguro
------------------
- Hacer la migración en pasos: primero backfill (mig. que sólo backfill),
  luego revisar, y sólo después ejecutar la migración que elimina la columna.
- Alternativa rápida: ejecutar una única migración que incluya el backfill y
  la eliminación, pero NUNCA sin tener copia de seguridad y pruebas en staging.

Referencias
----------
- `requirement.md` (Sprint 3.4 objetivo)
- `src/database/models.py` — modelo actual (`job_offers` y `job_offer_sources`)
- `migrations/versions/0001_initial.py` — migración inicial añadida

Preguntas para decidir antes de implementar
-----------------------------------------
1. ¿Quieres que genere la migración Alembic (con el backfill incluido) ahora?
2. ¿Prefieres un enfoque en dos pasos (migración de backfill → validación →
   migración de eliminación)?

-- Fin de la especificación de Sprint 3.4
