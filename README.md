# eepp-app

Rastreador de ofertas laborales del sector público chileno (EEPP + TEEE).  
Ingesta asíncrona, deduplicación cross-source, web con FastAPI.

---

## Desarrollo local

### Requisitos

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (`brew install uv`)
- Docker y Docker Desktop (para correr con contenedores)

### Sin Docker

```bash
# 1. Crear entorno e instalar dependencias
uv sync

# 2. Copiar variables de entorno
cp .env.example .env
# Editar .env con tu DATABASE_URL local

# 3. Aplicar migraciones
alembic upgrade head

# 4. Iniciar la web
uvicorn src.web.app:app --reload
```

### Con Docker Compose

```bash
# 1. Copiar variables de entorno (ajustar DATABASE_URL a la variante Docker Compose)
cp .env.example .env
# DATABASE_URL=postgresql+asyncpg://eepp:eepp@postgres:5432/eepp

# 2. Levantar Postgres + web (aplica migraciones automáticamente al arrancar)
docker compose up

# 3. (Opcional) Ingesta manual de datos
docker compose run --rm worker python scripts/ingest_all.py --initial
```

---

## Despliegue en producción (Dokploy)

### Arquitectura de servicios

El proyecto se despliega en [Dokploy](https://dokploy.com) con cuatro servicios:

| Servicio | Tipo | Descripción |
|---|---|---|
| `eepp-postgres` | Database (Postgres) | Base de datos principal |
| `eepp-web` | Application | API y UI web (FastAPI) |
| `eepp-worker-daily` | Cron | Ingesta diaria (postulacion + evaluacion) |
| `eepp-worker-monthly` | Cron | Ingesta mensual completa |

Todos los servicios de aplicación usan **la misma imagen** construida desde el `Dockerfile` de este repositorio. Solo varía el comando de arranque.

---

### Paso 1 — Crear el servicio de base de datos

1. En Dokploy, ir a **Services → New Service → Database → PostgreSQL**.
2. Asignar el nombre `eepp-postgres`.
3. Dokploy mostrará las credenciales generadas (`user`, `password`, `db`, `host` interno). **Guardar estos valores** — se usarán en el paso 3.
4. Hacer clic en **Deploy**.

---

### Paso 2 — Conectar el repositorio

1. En Dokploy, ir a **Services → New Service → Application**.
2. Conectar con GitHub y seleccionar este repositorio.
3. En **Build Settings**:
   - Build Type: `Dockerfile`
   - Dockerfile Path: `./Dockerfile`
4. Aún **no** hacer deploy — primero configurar las variables de entorno (paso 3).

---

### Paso 3 — Variables de entorno

Configurar las siguientes variables en la sección **Environment Variables** del servicio de aplicación en Dokploy. Repetir para cada servicio de aplicación (`eepp-web`, `eepp-worker-daily`, `eepp-worker-monthly`).

| Variable | Valor de ejemplo | Descripción |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://eepp:secret@eepp-postgres:5432/eepp` | DSN de conexión. El host es el nombre del servicio de BD en Dokploy. |
| `APP_ENV` | `production` | Entorno de ejecución. |
| `LOG_LEVEL` | `INFO` | Nivel de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `SCRAPER_TIMEOUT` | `30` | Timeout en segundos para peticiones HTTP a las APIs externas. |
| `SCRAPER_MAX_RETRIES` | `3` | Reintentos máximos ante fallos de red. |

> **Nota sobre `DATABASE_URL`**: Dokploy conecta los servicios por nombre dentro de una red interna. El host debe ser el nombre exacto del servicio de BD (`eepp-postgres` en este ejemplo), **no** `localhost`.

---

### Paso 4 — Configurar el servicio web (`eepp-web`)

1. En **General Settings**, asignar nombre `eepp-web`.
2. En **Port**, configurar el puerto `8000` (HTTP).
3. En **Command** (sobreescribe el CMD del Dockerfile), dejar vacío — el CMD por defecto del Dockerfile (`uvicorn ...`) es el correcto.
4. Activar un dominio si corresponde en la sección **Domains**.
5. Hacer clic en **Deploy**.

El entrypoint del contenedor corre `alembic upgrade head` automáticamente antes de arrancar uvicorn. Las migraciones se aplican en cada deploy.

---

### Paso 5 — Configurar los workers cron

Crear **dos servicios adicionales** siguiendo el mismo proceso del paso 2 (misma imagen, misma config de entorno). La diferencia está en el **Command** y el **Schedule**.

#### `eepp-worker-daily`

| Campo | Valor |
|---|---|
| Nombre | `eepp-worker-daily` |
| Tipo | Cron |
| Command | `python scripts/ingest_all.py --policy daily` |
| Schedule | `0 8,14,20 * * *` |

Corre a las 08:00, 14:00 y 20:00 (hora del servidor). Ingesta solo las ofertas en estado `postulacion` y `evaluacion`.

#### `eepp-worker-monthly`

| Campo | Valor |
|---|---|
| Nombre | `eepp-worker-monthly` |
| Tipo | Cron |
| Command | `python scripts/ingest_all.py --policy monthly` |
| Schedule | `0 3 1 * *` |

Corre el primer día de cada mes a las 03:00. Hace un sweep completo incluyendo `finalizadas`.

> **Nota sobre el Schedule**: Dokploy usa expresiones cron estándar en UTC. Si el servidor está en UTC, el horario de Chile (UTC-3 o UTC-4 según DST) estará 3-4 horas adelantado. Ajustar los valores según la zona horaria del servidor.

---

### Paso 6 — Carga inicial de datos

Después del primer deploy, la base de datos estará vacía. Hacer una carga histórica completa desde la consola de Dokploy:

1. Ir al servicio `eepp-web` → **Terminal** (o ejecutar desde un servicio worker de un solo uso).
2. Correr:

```bash
python scripts/ingest_all.py --initial
```

Este comando descarga el historial completo de TEEE y EEPP. Puede tardar varios minutos.

---

### Referencia rápida de comandos de ingesta

```bash
# Carga inicial completa (solo la primera vez)
python scripts/ingest_all.py --initial

# Ingesta diaria (cron automático)
python scripts/ingest_all.py --policy daily

# Ingesta mensual completa (cron automático)
python scripts/ingest_all.py --policy monthly

# Dry-run (no escribe en BD, útil para depurar)
python scripts/ingest_all.py --policy daily --dry-run
```
