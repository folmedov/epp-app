#!/bin/sh
# Entrypoint del contenedor.
# 1. Aplica migraciones pendientes de Alembic.
# 2. Ejecuta el comando recibido como argumentos (CMD o command override en Dokploy).

set -e

echo "[entrypoint] Aplicando migraciones de Alembic..."
/app/.venv/bin/alembic upgrade head

echo "[entrypoint] Iniciando: $*"
exec "$@"
