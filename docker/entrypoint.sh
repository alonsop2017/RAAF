#!/bin/bash
# RAAF container entrypoint
# Handles first-run initialization then delegates to the requested command.
set -e

echo "[entrypoint] Starting RAAF container..."

# ── First-run: copy credential templates if not present ──────────────────────
for template in config/pcr_credentials_template.yaml config/claude_credentials_template.yaml; do
    target="${template/_template/}"
    if [ ! -f "$target" ]; then
        cp "$template" "$target"
        echo "[entrypoint] Created $target from template"
    fi
done

# ── First-run: ensure data directories exist ─────────────────────────────────
mkdir -p data clients archive logs

# ── Run DB migrations / backfill if DB is empty ──────────────────────────────
if [ ! -f "data/raaf.db" ]; then
    echo "[entrypoint] No DB found — running initial schema setup..."
    python scripts/migrate/001_initial_schema.py 2>/dev/null || true
fi

# ── Delegate to the requested service ────────────────────────────────────────
case "$1" in
    uvicorn)
        echo "[entrypoint] Starting web server..."
        exec python -m uvicorn web.app:app \
            --host 0.0.0.0 \
            --port 8000 \
            --proxy-headers \
            "--forwarded-allow-ips=*"
        ;;
    cron)
        echo "[entrypoint] Starting cron scheduler..."
        exec supercronic /app/docker/crontab
        ;;
    *)
        exec "$@"
        ;;
esac
