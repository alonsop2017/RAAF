#!/usr/bin/env python3
"""
Rotate plain-append cron logs and trim the activity events feed.

pcr_sync.log, email_ingestion.log, backup.log, and assessment.log are
written via shell `>>` redirection in docker/crontab, so they have no
built-in size cap (unlike app.log/access.log, which use a Python
RotatingFileHandler — see docker/logging_config.json). Left alone,
pcr_sync.log grows unbounded since PCR sync runs every 5 minutes.

activity_events.jsonl is append-only JSONL; web/activity_monitor.py only
ever reads the last 10,000 lines, so anything beyond that is dead weight.

Run daily via cron.
"""

import gzip
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
LOG_DIR = ROOT / "logs"
ARCHIVE_DIR = LOG_DIR / "archive"

MAX_LOG_BYTES = 10 * 1024 * 1024  # rotate once a log exceeds 10MB
ROTATED_KEEP = 5  # keep this many gzipped rotations per log name

ROTATE_LOGS = ["pcr_sync.log", "email_ingestion.log", "backup.log", "assessment.log"]

ACTIVITY_EVENTS_FILE = ROOT / "data" / "activity_events.jsonl"
ACTIVITY_EVENTS_KEEP_LINES = 20_000  # activity_monitor.py only reads the last 10,000


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat()} {msg}")


def rotate_log(name: str) -> None:
    path = LOG_DIR / name
    if not path.exists() or path.stat().st_size < MAX_LOG_BYTES:
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rotated = ARCHIVE_DIR / f"{name}.{stamp}.gz"

    with open(path, "rb") as src, gzip.open(rotated, "wb") as dst:
        shutil.copyfileobj(src, dst)
    # Truncate in place (not rename+recreate) so any process with the file
    # already open via `>>` keeps writing to the same inode safely.
    with open(path, "r+b") as f:
        f.truncate(0)
    _log(f"Rotated {name} -> {rotated.name}")

    # Retention: keep only the newest ROTATED_KEEP gzips for this log name
    rotations = sorted(ARCHIVE_DIR.glob(f"{name}.*.gz"), key=lambda p: p.stat().st_mtime)
    for stale in rotations[:-ROTATED_KEEP]:
        stale.unlink()
        _log(f"Deleted old rotation {stale.name}")


def trim_activity_events() -> None:
    if not ACTIVITY_EVENTS_FILE.exists():
        return
    lines = ACTIVITY_EVENTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= ACTIVITY_EVENTS_KEEP_LINES:
        return
    kept = lines[-ACTIVITY_EVENTS_KEEP_LINES:]
    ACTIVITY_EVENTS_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    _log(f"Trimmed activity_events.jsonl: {len(lines)} -> {len(kept)} lines")


def main() -> None:
    for name in ROTATE_LOGS:
        rotate_log(name)
    trim_activity_events()


if __name__ == "__main__":
    main()
