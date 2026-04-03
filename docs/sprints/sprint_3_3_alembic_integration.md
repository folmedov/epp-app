# Sprint 3.3 — Integración de Alembic (migraciones reproducibles)

Fecha: 2026-04-03

Objetivo
--------
Introducir Alembic en el repositorio para gestionar migraciones de esquema de forma reproducible
y portable entre entornos (local, staging, producción). Esto permite recrear la base de
datos a la versión que corresponde a cualquier commit y mantener el historial de cambios DDL.

Motivación
----------
- Evitar que cambios en modelos de SQLAlchemy queden solo en código y no en migraciones.
- Poder aplicar, deshacer y revisar cambios de esquema en entornos CI/CD.
- Resolver problemas de sincronía entre el código y la base al hacer rollback/checkout de commits.

Requisitos previos
------------------
- Entorno Python 3.11+ (proyecto ya lo usa).
- Dependencias: `alembic` y un driver sync para Postgres (recomendado `psycopg[binary]`).

Alta‑nivel: tareas del sprint
---------------------------
1. Añadir configuración base de Alembic (`alembic.ini`, `migrations/` con `env.py`, `script.py.mako`).
2. Configurar `env.py` para usar `target_metadata = src.database.models.Base.metadata`.
3. Soporte para URL async -> sync (p.ej. convertir `postgresql+asyncpg://` → `postgresql+psycopg://`) para que Alembic ejecute migraciones con un engine sync.
4. Crear primer revision de migración (backfill inicial) con `alembic revision --autogenerate -m "initial"`.
5. Documentar comandos de uso y pasos para CI (stamp, upgrade, downgrade).

Detalles de implementación
-------------------------

1) Dependencias

Agregar en el `pyproject.toml` / entorno virtual:

```
pip install alembic
pip install "psycopg[binary]"
```

2) Estructura de migraciones

Crear carpeta `migrations/` (Alembic la genera con `alembic init migrations`).
Ficheros claves:
- `alembic.ini` — configuración principal (contiene `sqlalchemy.url`, puede dejarse vacío y leer desde env).
- `migrations/env.py` — código que configura el contexto de migración y carga `target_metadata`.
- `migrations/versions/` — revisiones generadas por `alembic revision`.

3) `env.py` (ejemplo mínimo y recomendado)

La aplicación usa SQLAlchemy Async. Para autogenerate las migraciones es práctico
crear un engine *sync* dentro de `env.py` usando un DSN sync derivado del DSN async.

Ejemplo (fragmento simplificado):

```py
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from sqlalchemy import create_engine
from alembic import context

import os
from src.database.models import Base

config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata

def get_url():
    url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if url and url.startswith("postgresql+asyncpg://"):
        # convertir asyncpg -> psycopg (sync) para Alembic
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    return url

def run_migrations_online():
    connectable = create_engine(get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
```

Notas:
- Importar `Base` desde `src.database.models` (o desde el módulo que exporte `metadata`).
- Evitar crear side‑effects en import time en `models` para que `alembic revision --autogenerate` funcione correctamente.

4) Flujo de uso (comandos)

- Inicializar alembic (si no existe):
  - `alembic init migrations`
- Crear una nueva revisión autogenerada:
  - `alembic revision --autogenerate -m "add pending_verification to job_offer_sources"`
- Aplicar migraciones a la DB:
  - `alembic upgrade head`
- Revertir una migración:
  - `alembic downgrade -1`
- Marcar la DB como en head cuando ya se sincronizó manualmente (stamp):
  - `alembic stamp head`

5) Backfill y migraciones críticas

- Para columnas deducidas (p.ej. `pending_verification`), crear una migración que:
  1. Añada la columna nullable.
  2. Ejecute un UPDATE backfill (p. ej. `UPDATE job_offer_sources SET pending_verification = (source = 'EEPP') WHERE pending_verification IS NULL;`).
  3. Establezca `NOT NULL` si es seguro.

6) CI / despliegue

- Incluir paso en pipeline para ejecutar `alembic upgrade head` antes de desplegar la app.
- Probar `alembic revision --autogenerate` en PRs que cambien modelos para validar las migraciones generadas.

7) Buenas prácticas

- Mantener las migraciones pequeñas y descriptivas.
- No modificar migraciones ya aplicadas en producción; crear una nueva migración para arreglos.
- Usar `alembic stamp` solo cuando crees la DB desde los modelos (`create_all`) y quieras marcar migraciones aplicadas sin ejecutar SQL.

Aceptación
----------
- `migrations/` está presente en el repo con un `env.py` que carga `target_metadata`.
- `README` / docs incluyen comandos mínimos para generar y aplicar migraciones.
- Ejecución local `alembic upgrade head` funciona contra la base de datos de desarrollo.

Riesgos y mitigaciones
----------------------
- Si el proyecto usa DSN async en `DATABASE_URL`, Alembic necesita un driver sync: documentar instalación y conversión en `env.py`.
- Evitar side effects en los módulos importados por `env.py` para que `autogenerate` no ejecute lógica indeseada.

Notas finales
------------
Este sprint es operativo y debe hacerse antes de añadir más cambios de esquema, ya que garantiza reproducibilidad entre versiones del repositorio.
