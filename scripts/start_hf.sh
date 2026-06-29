#!/bin/bash
# HF Spaces entrypoint — uses /data (persistent bucket) for database & storage.
set -e

# Persistent bucket mounted at /data — create subdirs if first run
mkdir -p /data/pdfs /data/logs

# Point everything at the persistent volume
export DATABASE_URL="sqlite:////data/uraas.db"
export STORAGE_PATH="/data/pdfs"

# Init DB (creates tables if not present, skips if already exists)
echo "[INIT] Initialising database at /data/uraas.db..."
python scripts/init_db.py

echo "[INIT] Starting URAAS dashboard on port 7860..."
exec gunicorn \
  --bind 0.0.0.0:7860 \
  --worker-class gthread \
  --workers 1 \
  --threads 4 \
  --timeout 120 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile - \
  uraas.dashboard.app:app
