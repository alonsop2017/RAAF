#!/usr/bin/env python3
"""
Cron backup script for RAAF.
Calls _run_rsync_backup() directly — no web server required.

Usage (set via crontab):
  Daily quick:   python scripts/backup_cron.py quick
  Weekly full:   python scripts/backup_cron.py full
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

DEST = Path("/home/alonsop/raaf_backups")
LOG_FILE = Path(__file__).parent.parent / "logs" / "backup.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def main():
    backup_type = sys.argv[1] if len(sys.argv) > 1 else "quick"
    if backup_type not in ("quick", "full"):
        log.error("Usage: backup_cron.py [quick|full]")
        sys.exit(1)

    log.info("Starting %s backup to %s", backup_type, DEST)

    from web.routers.admin import _run_rsync_backup

    try:
        ok, result = _run_rsync_backup(backup_type, DEST)
    except Exception as e:
        log.error("Backup failed with exception: %s", e)
        sys.exit(1)

    if ok:
        log.info("Backup complete: %s", result)
    else:
        log.error("Backup failed: %s", result)
        sys.exit(1)


if __name__ == "__main__":
    main()
