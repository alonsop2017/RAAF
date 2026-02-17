#!/bin/bash
# scripts/pcr/cron_sync.sh
# Automated PCR resume retrieval for cron execution.
# Runs watch_applicants.py --once --auto-download for all active
# PCR-linked requisitions. Uses flock to prevent overlapping runs.

PROJECT_ROOT="/home/alonsop/RAAF"
VENV_PYTHON="${PROJECT_ROOT}/venv/bin/python3"
SCRIPT="${PROJECT_ROOT}/scripts/pcr/watch_applicants.py"
LOCKFILE="/tmp/raaf_pcr_sync.lock"
LOGFILE="${PROJECT_ROOT}/logs/pcr_sync.log"

mkdir -p "${PROJECT_ROOT}/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOGFILE"
}

# Use flock to prevent concurrent runs
exec 200>"$LOCKFILE"
flock -n 200 || {
    log "SKIP: Another sync is already running"
    exit 1
}

log "========== Starting PCR sync =========="

cd "$PROJECT_ROOT" || {
    log "ERROR: Cannot cd to $PROJECT_ROOT"
    exit 1
}

"$VENV_PYTHON" "$SCRIPT" --once --auto-download --auto-assess >> "$LOGFILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log "OK: Sync completed"
else
    log "ERROR: Sync failed (exit code $EXIT_CODE)"
fi

log "========== Sync complete =========="

exit $EXIT_CODE
