#!/usr/bin/env python3
"""
Delete stale files from Direct_Submissions/unmatched/.

These are email resume attachments that didn't match any candidate or
requisition at ingestion time. scripts/email_ingestion/reprocess_unmatched.py
can re-match them later (e.g. once a requisition is created for a role that
already had applicants), so they have standing value and should NOT be
deleted on a short fuse — this only clears out ones old enough that a
re-match is no longer realistic.

Run weekly via cron.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
UNMATCHED_DIR = ROOT / "Direct_Submissions" / "unmatched"
LOG_FILE = ROOT / "logs" / "cleanup_unmatched.log"

RETENTION_DAYS = 180


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def main() -> None:
    if not UNMATCHED_DIR.exists():
        return

    cutoff = time.time() - RETENTION_DAYS * 86400
    deleted = 0
    freed_bytes = 0

    for path in UNMATCHED_DIR.iterdir():
        if not path.is_file():
            continue
        if path.stat().st_mtime < cutoff:
            freed_bytes += path.stat().st_size
            path.unlink()
            deleted += 1

    if deleted:
        _log(f"Deleted {deleted} files older than {RETENTION_DAYS}d "
             f"({freed_bytes / (1024 * 1024):.1f} MB freed)")
    else:
        _log(f"No files older than {RETENTION_DAYS}d")


if __name__ == "__main__":
    main()
