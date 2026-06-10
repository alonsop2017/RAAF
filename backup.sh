#!/bin/bash
# RAAF Backup Script
# Usage:
#   ./backup.sh --target local --local-path /path/to/backups
#   ./backup.sh --target onedrive --remote "onedrive:PeopleFind/RAAF-backups"
#   ./backup.sh --target gdrive   --remote "gdrive:RAAF-Backups"

set -euo pipefail

LOG_FILE="/app/logs/backup.log"
RETENTION_COUNT=30
RCLONE_CONFIG="/app/config/rclone.conf"

# Defaults
TARGET=""
LOCAL_PATH=""
REMOTE=""
QUIET=false

usage() {
    echo "Usage: $0 --target local|onedrive|gdrive [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --target local|onedrive|gdrive   Backup destination (required)"
    echo "  --local-path /path               Local backup directory (required for local)"
    echo "  --remote remote:path             rclone remote and path (required for cloud targets)"
    echo "  --quiet                          Suppress output (for cron usage)"
    exit 1
}

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "$msg" >> "$LOG_FILE"
    if [ "$QUIET" = false ]; then
        echo "$msg"
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --target)      TARGET="$2";     shift 2 ;;
        --local-path)  LOCAL_PATH="$2"; shift 2 ;;
        --remote)      REMOTE="$2";     shift 2 ;;
        --quiet)       QUIET=true;      shift   ;;
        # Legacy compat
        --gdrive-remote) REMOTE="$2"; TARGET="gdrive"; shift 2 ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate
if [ -z "$TARGET" ]; then echo "Error: --target is required"; usage; fi
if [ "$TARGET" = "local" ] && [ -z "$LOCAL_PATH" ]; then echo "Error: --local-path required for local"; usage; fi
if [ "$TARGET" != "local" ] && [ -z "$REMOTE" ]; then echo "Error: --remote required for $TARGET"; usage; fi

# Create archive
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
ARCHIVE_NAME="raaf_backup_${TIMESTAMP}.tar.gz"
TMP_DIR=$(mktemp -d)
TMP_ARCHIVE="$TMP_DIR/$ARCHIVE_NAME"

log "Starting RAAF backup (target: $TARGET)"

# Back up DB + config + client data (resumes, assessments, frameworks)
log "Creating archive: $ARCHIVE_NAME"
tar -czf "$TMP_ARCHIVE" \
    -C /app \
    data/ \
    config/ \
    clients/ \
    --exclude="config/.token_store.json" \
    --exclude="config/users.db" \
    --exclude="clients/*/requisitions/*/resumes/batches/*/originals" \
    2>/dev/null || true

ARCHIVE_SIZE=$(du -h "$TMP_ARCHIVE" | cut -f1)
log "Archive created: $ARCHIVE_SIZE"

# Deliver
if [ "$TARGET" = "local" ]; then
    mkdir -p "$LOCAL_PATH"
    cp "$TMP_ARCHIVE" "$LOCAL_PATH/"
    log "Backup saved to $LOCAL_PATH/$ARCHIVE_NAME"

    BACKUP_COUNT=$(ls -1 "$LOCAL_PATH"/raaf_backup_*.tar.gz 2>/dev/null | wc -l)
    if [ "$BACKUP_COUNT" -gt "$RETENTION_COUNT" ]; then
        DELETE_COUNT=$((BACKUP_COUNT - RETENTION_COUNT))
        ls -1t "$LOCAL_PATH"/raaf_backup_*.tar.gz | tail -n "$DELETE_COUNT" | xargs rm -f
        log "Retention: deleted $DELETE_COUNT old backup(s)"
    fi

else
    # Cloud target via rclone (onedrive, gdrive, or any rclone remote)
    if ! command -v rclone &>/dev/null; then
        log "ERROR: rclone is not installed"
        rm -rf "$TMP_DIR"
        exit 1
    fi

    RCLONE_ARGS="--config $RCLONE_CONFIG"
    REMOTE_NAME=$(echo "$REMOTE" | cut -d: -f1)

    if ! rclone $RCLONE_ARGS listremotes | grep -q "^${REMOTE_NAME}:$"; then
        log "ERROR: rclone remote '${REMOTE_NAME}' not configured. Run: rclone --config $RCLONE_CONFIG config"
        rm -rf "$TMP_DIR"
        exit 1
    fi

    log "Uploading to ${TARGET}: $REMOTE"
    rclone $RCLONE_ARGS copy "$TMP_ARCHIVE" "$REMOTE" --transfers=1 2>&1 | \
        while read -r line; do if [ "$QUIET" = false ]; then echo "$line"; fi; done
    log "Upload complete: $REMOTE/$ARCHIVE_NAME"

    # Retention
    REMOTE_FILES=$(rclone $RCLONE_ARGS lsf "$REMOTE" --include "raaf_backup_*.tar.gz" | sort)
    REMOTE_COUNT=$(echo "$REMOTE_FILES" | grep -c . 2>/dev/null || echo 0)
    if [ "$REMOTE_COUNT" -gt "$RETENTION_COUNT" ]; then
        DELETE_COUNT=$((REMOTE_COUNT - RETENTION_COUNT))
        echo "$REMOTE_FILES" | head -n "$DELETE_COUNT" | while read -r file; do
            rclone $RCLONE_ARGS deletefile "$REMOTE/$file"
            log "Retention: deleted $file"
        done
    fi

    # Sync resume originals (PDFs/DOCXs) incrementally — too large for tar, rclone only uploads new files
    ORIGINALS_REMOTE="$REMOTE/resume-originals"
    log "Syncing resume originals to ${TARGET}: $ORIGINALS_REMOTE"
    rclone $RCLONE_ARGS sync /app/clients/ "$ORIGINALS_REMOTE" \
        --include "**/originals/**" \
        --transfers=4 \
        --checksum \
        2>&1 | while read -r line; do if [ "$QUIET" = false ]; then echo "$line"; fi; done
    log "Resume originals sync complete"
fi

rm -rf "$TMP_DIR"
log "Backup completed successfully"
