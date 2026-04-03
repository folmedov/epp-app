# Sprint 3.5 — Refactor: `TEEEClient` usando `search_after` para paginación

Objetivo
--------
- Reemplazar la paginación por offset (`from`/`size`) en `TEEEClient` por
  `search_after` para soportar ingestas profundas (>10k) de forma estable y
  reproducible.

Contexto y motivación
---------------------
- Estado actual: `_fetch_state` usa `from`/`size` (offset pagination). Esto
  funciona para pequeños volúmenes pero fragiliza la ingesta cuando hay
  muchos documentos por `Estado` (límite `index.max_result_window`, por
  defecto 10.000) y puede producir duplicados/u omisiones cuando el índice
  cambia durante la paginación.
- Objetivo: permitir recuperar todos los hits por `Estado` sin límite práctico,
  con un cursor estable y posibilidad de reanudar.

Requisitos funcionales
----------------------
- Soportar >10k resultados por `Estado`.
- Resultados deterministas durante la ejecución.
- Poder reanudar desde la última página en caso de fallo (persistir cursor
  intermedio si hace falta).
- Mantener la forma de salida actual (lista de hits normalizados).
- Compatibilidad: permitir un modo de fallback que use `from`/`size` si `search_after`
  no está disponible en el proxy.

Diseño propuesto
----------------
1. Seleccionar un orden de sort estable y con tie‑breaker:
   - Usar `Datesum` (campo numérico de fecha del índice TEEE) **+** `_id` como
     tie‑breaker — garantiza un orden total reproducible.

2. Loop de `search_after`:
   - En la primera petición no enviar `search_after`.
   - En cada respuesta leer `hits[-1]["sort"]` del último hit y usarlo como
     `search_after` en la siguiente petición.
   - Repetir hasta que `hits` esté vacío.

3. Tamaño de página (`size`): usar un valor intermedio (por ejemplo 1000‑2000)
   según latencia y memoria.

> **Nota:** PIT fue evaluado pero la plataforma TEEE no lo soporta. No incluir
> lógica de apertura/cierre de PIT en la implementación.

Ejemplo de implementación (pseudocódigo / Python async)
-----------------------------------------------------
```py
async def _fetch_state(self, state: str, size: int = 1000, max_pages: int = 0):
    results = []
    last_sort = None
    page = 0

    while True:
        body = {
            "size": size,
            "query": {"bool": {"must": [{"term": {"Estado": state}}]}},
            "sort": [{"Datesum": "asc"}, {"_id": "asc"}],
        }
        if last_sort is not None:
            body["search_after"] = last_sort

        payload = await _do_post(body)
        hits = payload.get("hits", {}).get("hits", [])
        if not hits:
            break

        for h in hits:
            results.append(self._normalize_hit(h))

        last_sort = hits[-1].get("sort")  # cursor for next page

        page += 1
        if max_pages and page >= max_pages:
            break

    return results
```

Notas de implementación
-----------------------
- `Datesum` es un entero numérico en el índice TEEE (confirmado en discovery);
  combinarlo con `_id` garantiza un orden total estable.
- El valor `hits[-1]["sort"]` (lista) se pasa exactamente como `search_after`.
- El proxy HTTP debe exponer `sort` en cada hit; si no está presente, lanzar
  `TEEEResponseFormatError` con mensaje claro.
- PIT no está soportado por la plataforma TEEE — no implementar.

Pruebas y validación
---------------------
- Unit tests: mockear el endpoint y validar que `_fetch_state` itera con
  `search_after` hasta finalizar y que llama a `_normalize_hit` por hit.
- Integración (dry-run): ejecutar en staging con `size=1000` y comparar
  conteos y huellas con la versión `from/size` para detectar diferencias
  relevantes (duplicados / faltantes).
- Performance: medir tiempo total y latencia por página. Ajustar `size`.

Rollout
-------
1. Implementar la versión con `search_after` en una rama (ej. `refactor/teee-search-after`).
2. Ejecutar dry‑run contra staging/neon: comparar conteo total con versión
   anterior y revisar muestras de hits.
3. Habilitar gradualmente en producción (feature flag o CLI flag `--use-search-after`).
4. Monitorear errores, latencias y diferencias de conteo durante 24‑48h.

Compatibilidad y retroceso
--------------------------
- Mantener el parámetro `use_search_after` (default `True`) para poder volver
  al `from/size` si el proxy no soporta `search_after` o los campos de `sort`.
- En caso de fallo, instanciar con `use_search_after=False` para usar el fallback.

Tareas concretas
-----------------
- Crear/editar `src/ingestion/teee_client.py::_fetch_state` según ejemplo.
- Añadir pruebas unitarias para `search_after` behavior.
- Documentar el uso del flag `--use-search-after` en `scripts/load_teee.py`.
- Ejecutar dry‑run y validar contra la ingesta histórica.

Referencias
----------
- `requirement.md` (Sprint 3: entrada y prioridades)
- `docs/sprints/sprint_3_4_job_offers_refactor.md` (contexto de canonicalización)
- `docs/design/teee_external_id_policy.md` (relación con matching)

Fin del plan Sprint 3.5
