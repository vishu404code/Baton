#!/bin/sh
set -e
echo "[baton] running database migrations"
alembic upgrade head
echo "[baton] starting API on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --log-level "${LOG_LEVEL:-info}"
