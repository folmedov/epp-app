# ─────────────────────────────────────────────
# Stage 1: builder
# Instala uv y resuelve/instala todas las dependencias
# en un virtualenv en /app/.venv
# ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

# uv necesita estas herramientas de sistema para algunos paquetes
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Instala uv (el gestor de paquetes del proyecto)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copia primero solo los archivos de dependencias para aprovechar el cache de capas.
# Si el código fuente cambia pero pyproject.toml/uv.lock no, Docker reutiliza
# la capa de instalación de deps (mucho más rápido en re-builds).
COPY pyproject.toml uv.lock ./

# Instala las dependencias de producción en /app/.venv
# --frozen: usa exactamente las versiones del uv.lock (no resuelve nada nuevo)
# --no-dev: excluye pytest, ruff y demás herramientas de desarrollo
RUN uv sync --frozen --no-dev

# ─────────────────────────────────────────────
# Stage 2: runner
# Imagen final limpia: solo Python + el .venv generado en el builder
# ─────────────────────────────────────────────
FROM python:3.11-slim AS runner

# libpq-dev runtime es necesario para asyncpg en ejecución
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia el virtualenv ya resuelto desde el builder
COPY --from=builder /app/.venv /app/.venv

# Copia el código fuente y artefactos necesarios
COPY src/ src/
COPY scripts/ scripts/
COPY migrations/ migrations/
COPY alembic.ini alembic.ini

# Copia el entrypoint
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# El virtualenv del builder ya tiene el path correcto (/app/.venv).
# Activar el venv consiste simplemente en anteponer su bin/ al PATH.
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

# Puerto que expone el servicio web (debe coincidir con el de uvicorn)
EXPOSE 8000

# Entrypoint por defecto: ejecuta migraciones y luego el comando pasado al contenedor.
# Se puede sobreescribir por servicio en Dokploy.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
