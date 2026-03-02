#!/bin/bash
# RAAF Backup Script
# Usage:
#   ./backup.sh --target local --local-path /path/to/backups
#   ./backup.sh --target gdrive --gdrive-remote raaf-backup:RAAF-Backups
#   ./backup.sh --target gdrive --gdrive-remote raaf-backup:RAAF-Backups --quiet

set -euo pipefail

RAAF_DIR="/home/alonsop/RAAF"
LOG_FILE="$RAAF_DIR/logs/backup.log"
RETENTION_COUNT=30

# Defaults
TARGET=""
LOCAL_PATH=""
GDRIVE_REMOTE=""
QUIET=false

usage() {
    echo "Usage: $0 --target local|gdrive [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --target local|gdrive       Backup destination (required)"
    echo "  --local-path /path          Local backup directory (required for local target)"
    echo "  --gdrive-remote remote:path rclone remote and path (required for gdrive target)"
    echo "  --quiet                     Suppress output (for cron usage)"
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
        --target)
            TARGET="$2"
            shift 2
            ;;
        --local-path)
            LOCAL_PATH="$2"
            shift 2
            ;;
        --gdrive-remote)
            GDRIVE_REMOTE="$2"
            shift 2
            ;;
        --quiet)
            QUIET=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate arguments
if [ -z "$TARGET" ]; then
    echo "Error: --target is required"
    usage
fi

if [ "$TARGET" = "local" ] && [ -z "$LOCAL_PATH" ]; then
    echo "Error: --local-path is required for local target"
    usage
fi

if [ "$TARGET" = "gdrive" ] && [ -z "$GDRIVE_REMOTE" ]; then
    echo "Error: --gdrive-remote is required for gdrive target"
    usage
fi

# Create timestamp and archive name
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
ARCHIVE_NAME="raaf_backup_${TIMESTAMP}.tar.gz"
TMP_DIR=$(mktemp -d)
TMP_ARCHIVE="$TMP_DIR/$ARCHIVE_NAME"

log "Starting RAAF backup (target: $TARGET)"

# Create the backup archive
log "Creating archive: $ARCHIVE_NAME"
tar -czf "$TMP_ARCHIVE" \
    -C "$RAAF_DIR" \
    clients/ \
    config/ \
    archive/ \
    2>/dev/null || true

ARCHIVE_SIZE=$(du -h "$TMP_ARCHIVE" | cut -f1)
log "Archive created: $ARCHIVE_SIZE"

# Deliver backup to target
if [ "$TARGET" = "local" ]; then
    mkdir -p "$LOCAL_PATH"
    cp "$TMP_ARCHIVE" "$LOCAL_PATH/"
    log "Backup saved to $LOCAL_PATH/$ARCHIVE_NAME"

    # Retention: keep last N backups, delete older ones
    BACKUP_COUNT=$(ls -1 "$LOCAL_PATH"/raaf_backup_*.tar.gz 2>/dev/null | wc -l)
    if [ "$BACKUP_COUNT" -gt "$RETENTION_COUNT" ]; then
        DELETE_COUNT=$((BACKUP_COUNT - RETENTION_COUNT))
        ls -1t "$LOCAL_PATH"/raaf_backup_*.tar.gz | tail -n "$DELETE_COUNT" | xargs rm -f
        log "Retention: deleted $DELETE_COUNT old backup(s), keeping last $RETENTION_COUNT"
    fi

elif [ "$TARGET" = "gdrive" ]; then
    if ! command -v rclone &>/dev/null; then
        log "ERROR: rclone is not installed. Install it with: sudo apt install rclone"
        rm -rf "$TMP_DIR"
        exit 1
    fi

    REMOTE_NAME=$(echo "$GDRIVE_REMOTE" | cut -d: -f1)
    if ! rclone listremotes | grep -q "^${REMOTE_NAME}:$"; then
        log "ERROR: rclone remote '$REMOTE_NAME' not configured. Run: rclone config"
        rm -rf "$TMP_DIR"
        exit 1
    fi

    log "Uploading to Google Drive: $GDRIVE_REMOTE"
    rclone copy "$TMP_ARCHIVE" "$GDRIVE_REMOTE" --progress 2>&1 | while read -r line; do
        if [ "$QUIET" = false ]; then echo "$line"; fi
    done
    log "Upload complete: $GDRIVE_REMOTE/$ARCHIVE_NAME"

    # Retention: keep last N backups on Google Drive
    REMOTE_FILES=$(rclone lsf "$GDRIVE_REMOTE" --include "raaf_backup_*.tar.gz" | sort)
    REMOTE_COUNT=$(echo "$REMOTE_FILES" | grep -c . || true)
    if [ "$REMOTE_COUNT" -gt "$RETENTION_COUNT" ]; then
        DELETE_COUNT=$((REMOTE_COUNT - RETENTION_COUNT))
        echo "$REMOTE_FILES" | head -n "$DELETE_COUNT" | while read -r file; do
            rclone deletefile "$GDRIVE_REMOTE/$file"
            log "Retention: deleted remote backup $file"
        done
    fi
fi

# Cleanup temp files
rm -rf "$TMP_DIR"

log "Backup completed successfully"
