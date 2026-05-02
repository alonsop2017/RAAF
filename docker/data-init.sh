#!/bin/sh
# RAAF Data Container Initialization
# ─────────────────────────────────────────────────────────────────────────────
# Creates the required directory structure and, on first run, downloads and
# extracts the latest Google Drive backup via rclone.
#
# Expected volume mounts:
#   /mnt/data    → ./data    (SQLite DB)
#   /mnt/clients → ./clients (client/requisition data)
#   /mnt/archive → ./archive (archived requisitions)
#   /mnt/logs    → ./logs    (application logs)
#   /mnt/config  → ./config  (credentials & runtime config)
#
# Environment variables:
#   GDRIVE_REMOTE  rclone remote:path  (default: raaf-backup:RAAF-Backups)
#   FORCE_RESTORE  "true" to overwrite existing data  (default: false)
# ─────────────────────────────────────────────────────────────────────────────
set -e

GDRIVE_REMOTE="${GDRIVE_REMOTE:-raaf-backup:RAAF-Backups}"
FORCE_RESTORE="${FORCE_RESTORE:-false}"
TMP_DIR="/tmp/raaf-restore"

log()  { echo "[data-init] $(date '+%Y-%m-%d %H:%M:%S') $1"; }
fail() { echo "[data-init] FATAL: $1" >&2; exit 1; }

# ── Step 1: Create required directory structure ────────────────────────────────
log "Ensuring directory structure..."
mkdir -p /mnt/data /mnt/clients /mnt/archive /mnt/logs /mnt/config
log "Directories ready."

# ── Step 2: Decide whether a restore is needed ────────────────────────────────
if [ "$FORCE_RESTORE" != "true" ]; then
    HAS_DB=false
    HAS_CLIENTS=false

    [ -f /mnt/data/raaf.db ] && HAS_DB=true
    [ "$(ls -A /mnt/clients 2>/dev/null)" ] && HAS_CLIENTS=true

    if [ "$HAS_DB" = "true" ] || [ "$HAS_CLIENTS" = "true" ]; then
        log "Existing data detected — skipping restore."
        log "  DB      : $([ "$HAS_DB" = "true" ] && echo 'present' || echo 'absent')"
        log "  Clients : $(ls /mnt/clients 2>/dev/null | wc -l | tr -d ' ') folder(s)"
        log "Set FORCE_RESTORE=true to override and re-restore from Google Drive."
        exit 0
    fi
fi

# ── Step 3: Verify rclone configuration ───────────────────────────────────────
REMOTE_NAME=$(echo "$GDRIVE_REMOTE" | cut -d: -f1)
log "Checking rclone remote '$REMOTE_NAME'..."

if ! rclone listremotes 2>/dev/null | grep -q "^${REMOTE_NAME}:$"; then
    log "WARNING: rclone remote '$REMOTE_NAME' is not configured."
    log "  Mount your rclone.conf to /root/.config/rclone/rclone.conf"
    log "  Example: add this to docker-compose.yml under raaf-data-init volumes:"
    log "    - \${HOME}/.config/rclone:/root/.config/rclone:ro"
    log "Proceeding without restore — empty directories are ready for first use."
    exit 0
fi

# ── Step 4: Find the latest backup ────────────────────────────────────────────
log "Scanning $GDRIVE_REMOTE for backups (pattern: raaf_backup_*.tar.gz)..."
LATEST=$(rclone lsf "$GDRIVE_REMOTE" --include "raaf_backup_*.tar.gz" 2>/dev/null \
    | sort -r | head -1)

if [ -z "$LATEST" ]; then
    log "WARNING: No backup archives found at $GDRIVE_REMOTE"
    log "  Run backup.sh --target gdrive to create your first backup."
    log "Proceeding with empty data directories."
    exit 0
fi

log "Latest backup found: $LATEST"

# ── Step 5: Download the archive ──────────────────────────────────────────────
mkdir -p "$TMP_DIR"
log "Downloading from Google Drive..."
rclone copy "$GDRIVE_REMOTE/$LATEST" "$TMP_DIR/" \
    --progress \
    --stats-one-line \
    2>&1 || fail "Download failed for: $LATEST"

ARCHIVE="$TMP_DIR/$LATEST"
ARCHIVE_SIZE=$(du -h "$ARCHIVE" | cut -f1)
log "Download complete: $ARCHIVE_SIZE"

# ── Step 6: Verify archive integrity ──────────────────────────────────────────
log "Verifying archive integrity..."
tar -tzf "$ARCHIVE" > /dev/null 2>&1 || fail "Archive is corrupt: $LATEST — aborting restore."
log "Archive integrity check passed."

# ── Step 7: Extract to staging area ───────────────────────────────────────────
TMP_EXTRACT="$TMP_DIR/extracted"
mkdir -p "$TMP_EXTRACT"
log "Extracting archive..."
tar -xzf "$ARCHIVE" -C "$TMP_EXTRACT" || fail "Extraction failed."
log "Extraction complete."

# ── Step 8: Copy each piece to its mount point ────────────────────────────────
# backup.sh archives: clients/, config/, archive/
# The database (data/raaf.db) is NOT included in the backup —
# it will be re-created by the migration script on first app start.
log "Distributing restored data to volumes..."
for dir in clients config archive; do
    SRC="$TMP_EXTRACT/$dir"
    DEST="/mnt/$dir"
    if [ -d "$SRC" ]; then
        cp -rp "$SRC/." "$DEST/"
        COUNT=$(find "$DEST" -maxdepth 1 -mindepth 1 | wc -l | tr -d ' ')
        log "  $dir/  →  $COUNT item(s) restored"
    else
        log "  $dir/  →  not present in backup (skipped)"
    fi
done

# ── Step 9: Preserve config file permissions ──────────────────────────────────
# Credential files should not be world-readable
for f in /mnt/config/pcr_credentials.yaml \
          /mnt/config/claude_credentials.yaml \
          /mnt/config/.token_store.json; do
    [ -f "$f" ] && chmod 600 "$f" && log "  Set permissions 600 on $(basename "$f")"
done

# ── Step 10: Cleanup ──────────────────────────────────────────────────────────
rm -rf "$TMP_DIR"
log "Temporary files removed."

# ── Summary ───────────────────────────────────────────────────────────────────
log "───────────────────────────────────────────────"
log "Data initialization complete."
log "  Source   : $GDRIVE_REMOTE/$LATEST"
log "  Clients  : $(ls /mnt/clients 2>/dev/null | wc -l | tr -d ' ') folder(s)"
log "  Archive  : $(ls /mnt/archive 2>/dev/null | wc -l | tr -d ' ') folder(s)"
log "  Config   : $(ls /mnt/config 2>/dev/null | wc -l | tr -d ' ') file(s)"
log "───────────────────────────────────────────────"
