#!/bin/bash
set -e

# Run database migrations (allow failure if already up to date)
alembic upgrade head || echo "WARNING: alembic migration failed, continuing..."

# Start the application
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
