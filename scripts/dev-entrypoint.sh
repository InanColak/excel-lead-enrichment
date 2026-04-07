#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding admin user (if needed)..."
python -m app.seed

echo "Starting uvicorn with hot-reload..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
