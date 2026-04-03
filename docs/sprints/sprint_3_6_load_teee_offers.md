# Sprint 3.6 — Load TEEE Offers: script de carga desde línea de comandos

Objetivo
--------
Implementar `scripts/load_teee.py` como script CLI reutilizable para obtener
ofertas de la API TEEE y persisitrlas en la base de datos Neon de forma
idempotente. El script sirve como herramienta operacional y también como
mecanismo de prueba de ingesta mediante la opción `--dry-run`.

Contexto y motivación
---------------------
- Sprint 3.5 implementó `TEEEClient` con paginación `search_after`.
- Aún no existe un script CLI autónomo que orqueste el ciclo completo
  *fetch → validar → upsert → commit* para TEEE.
- La operación de ingesta tiene riesgo de afectar datos de producción;
  se requiere un modo de prueba en seco (`--dry-run`) que ejecute la
  validación y el upsert dentro de una transacción que se revierte
  al final en lugar de confirmarse.

Especificación de la interfaz CLI
----------------------------------

```
PYTHONPATH=. python scripts/load_teee.py [opciones]
```

### Parámetros

| Parámetro | Tipo | Obligatorio | Default | Descripción |
|-----------|------|-------------|---------|-------------|
| `--state` / `--estado` | `str` (lista separada por `,`) | No | `all` | Estados a cargar. Valores soportados: `postulacion`, `evaluacion`, `finalizadas`, `all`. Se pueden combinar: `--state postulacion,evaluacion`. |
| `--dry-run` | flag (booleano) | No | `False` | Cuando está presente, ejecuta el ciclo completo de fetch → validar → upsert pero **revierte la transacción** en lugar de hacer `commit`. No modifica la base de datos. |
| `--batch` | `int` | No | `1000` | Número de elementos solicitados por petición a la API TEEE (tamaño de página). Equivale al parámetro `size` en la query Elasticsearch. Rango recomendado: `500`–`2000`. |
| `--out` | `Path` | No | — | Ruta de archivo para escribir los resultados normalizados en JSON. Compatible con cualquier combinación de otros parámetros. |

### Valores de `--state`

| Valor | Estado en TEEE (`Estado`) |
|-------|--------------------------|
| `postulacion` | `postulacion` |
| `evaluacion` | `evaluacion` |
| `finalizadas` | `finalizadas` |
| `all` | Equivale a `postulacion,evaluacion,finalizadas` (todos los estados) |

Los valores se pueden combinar separados por coma:
```bash
--state postulacion,evaluacion
```
Si `all` está presente junto con otros valores, tiene precedencia y se cargan
todos los estados.

### Ejemplos de uso

#### 1. Verificar qué se fetcharía (sin tocar la BD)
```bash
PYTHONPATH=. DATABASE_URL="$DATABASE_URL" \
    python scripts/load_teee.py --state all
```

#### 2. Dry-run completo (fetch → validar → upsert simulado)
```bash
PYTHONPATH=. DATABASE_URL="$DATABASE_URL" \
    python scripts/load_teee.py --state all --dry-run
```

#### 3. Carga real de ofertas en postulación
```bash
PYTHONPATH=. DATABASE_URL="$DATABASE_URL" \
    python scripts/load_teee.py --state postulacion --batch 1000
```

#### 4. Carga de múltiples estados con salida a archivo
```bash
PYTHONPATH=. DATABASE_URL="$DATABASE_URL" \
    python scripts/load_teee.py --state postulacion,evaluacion --out resultado.json
```

Flujo interno
-------------
```
parse_args
    ↓
TEEEClient.fetch_state(s, batch)  ← por cada estado en --state
    ↓
_to_schema(raw)                   ← valida con JobOfferSchema; descarta inválidos
    ↓
BEGIN transaction
upsert_job_offers(session, schemas)
if --dry-run:
    ROLLBACK   ← no escribe, sólo reporta count esperado
else:
    COMMIT     ← persiste en Neon
    ↓
if --out:
    escribir JSON normalizado al path indicado
    ↓
print resumen (fetched / valid / upserted / dry_run)
```

Comportamiento de `--dry-run`
------------------------------
- Realiza el ciclo completo: fetch, normalización, validación Pydantic, upsert
  en memoria (SQLAlchemy en transacción abierta).
- **No persiste**: llama a `session.rollback()` en lugar de `session.commit()`.
- Imprime cuántas filas *se habrían* insertado/actualizado.
- Permite detectar errores de validación, fingerprints faltantes y problemas
  de conectividad sin riesgo de datos.
- Útil en CI para validar que la ingesta es funcional antes de desplegar a
  producción.

Salida esperada (stdout/log)
-----------------------------
```
INFO  Fetched 1420 offers from TEEE (use_search_after=True, states=['postulacion'])
INFO  Validated 1418/1420 offers for DB write
INFO  Dry run enabled — rolled back. Would have upserted 1418 row(s)
```

O sin dry-run:
```
INFO  Fetched 1420 offers from TEEE (use_search_after=True, states=['postulacion'])
INFO  Validated 1418/1420 offers for DB write
INFO  Committed 1418 row(s) to DB
```

Archivos afectados
------------------
| Archivo | Cambio |
|---------|--------|
| `scripts/load_teee.py` | Implementación principal del CLI |
| `src/ingestion/teee_client.py` | Usa `_fetch_state(state, size=batch)` ya implementado |
| `src/database/repository.py` | Usa `upsert_job_offers` ya implementado |
| `src/core/schemas.py` | `JobOfferSchema` para validación (sin cambios) |

Criterios de aceptación
------------------------
- [ ] `--state all --dry-run` completa sin errores y sin modificar la BD.
- [ ] `--state postulacion` escribe filas en `job_offers` y se puede repetir (idempotencia).
- [ ] `--state postulacion,evaluacion` carga exactamente esos dos estados.
- [ ] Un valor de `--state` inválido produce un error claro con `parser.error()`.
- [ ] `--batch 500` se usa como `size` al llamar `TEEEClient._fetch_state`.
- [ ] `--out resultado.json` escribe JSON normalizado independientemente de `--to-db`.
- [ ] El script funciona con `DATABASE_URL` desde `.env` (vía `src.core.config.settings`).

Dependencias
------------
- Sprint 3.5 completado (`TEEEClient` con `search_after`).
- Sprint 3.4 completado (`job_offers` sin `external_id`; `repository.upsert_job_offers` actualizado).

Referencias
-----------
- `docs/sprints/sprint_3_5_refactor_teee_client.md`
- `docs/sprints/sprint_3_4_job_offers_refactor.md`
- `src/main.py` — pipeline equivalente para EEPP (referencia de patrón)
- `architecture.md`

Fin del plan Sprint 3.6
