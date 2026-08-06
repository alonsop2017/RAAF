#!/usr/bin/env python3
"""
Disk-space and config-integrity health check for RAAF.

Run hourly via cron. Logs WARNING/CRITICAL lines to logs/health_check.log
and stdout (captured by `docker logs raaf-cron`) so a repeat of the
2026-07-30 disk-full incident — which silently truncated
config/pcr_credentials.yaml to 0 bytes and broke PCR sync for ~2 days
unnoticed — gets caught within the hour instead.

Exit codes: 0 = healthy, 1 = warning, 2 = critical.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
LOG_FILE = ROOT / "logs" / "health_check.log"
ALERT_COOLDOWN_MARKER = ROOT / "logs" / ".last_disk_alert_ts"
ALERT_COOLDOWN_SECONDS = 6 * 3600  # don't re-email more than once per 6h

DISK_WARN_PCT = 70
DISK_CRITICAL_PCT = 85

# Config files that must never be empty. A 0-byte file here means something
# (usually a disk-full event) truncated it mid-write.
CRITICAL_CONFIG_FILES = [
    ROOT / "config" / "pcr_credentials.yaml",
    ROOT / "config" / "claude_credentials.yaml",
]


def _log(level: str, msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} [{level}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _send_alert_email(critical_messages: list[str]) -> None:
    """Email admins on CRITICAL, rate-limited to once per ALERT_COOLDOWN_SECONDS."""
    now = time.time()
    if ALERT_COOLDOWN_MARKER.exists():
        try:
            last = float(ALERT_COOLDOWN_MARKER.read_text().strip())
            if now - last < ALERT_COOLDOWN_SECONDS:
                _log("INFO", "Alert email suppressed (within cooldown window)")
                return
        except ValueError:
            pass

    try:
        import yaml
        settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text()) or {}
        admin_emails = settings.get("auth", {}).get("admin_emails", [])
        if not admin_emails:
            _log("WARNING", "No admin_emails configured — cannot send alert email")
            return

        from scripts.email_ingestion.gmail_client import send_email
        send_email(
            to=", ".join(admin_emails),
            subject="[RAAF] CRITICAL disk health alert",
            body="RAAF health check found critical issue(s) on the droplet:\n\n"
                 + "\n".join(f"- {m}" for m in critical_messages)
                 + "\n\nCheck the admin dashboard and `df -h` on the droplet.",
            from_name="RAAF Health Check",
        )
        _log("INFO", f"Alert email sent to {admin_emails}")
        ALERT_COOLDOWN_MARKER.write_text(str(now))
    except Exception as e:
        _log("WARNING", f"Failed to send alert email: {e}")


def check_disk(critical_messages: list[str]) -> int:
    import shutil

    usage = shutil.disk_usage("/")
    pct = usage.used / usage.total * 100
    free_gb = usage.free / (1024 ** 3)

    if pct >= DISK_CRITICAL_PCT:
        msg = (f"Disk usage at {pct:.1f}% ({free_gb:.1f} GB free) — "
               f"disk-full risk, config files can silently truncate")
        _log("CRITICAL", msg)
        critical_messages.append(msg)
        return 2
    if pct >= DISK_WARN_PCT:
        _log("WARNING", f"Disk usage at {pct:.1f}% ({free_gb:.1f} GB free)")
        return 1
    _log("OK", f"Disk usage at {pct:.1f}% ({free_gb:.1f} GB free)")
    return 0


def check_config_files(critical_messages: list[str]) -> int:
    worst = 0
    for path in CRITICAL_CONFIG_FILES:
        if not path.exists():
            continue  # absent is a valid first-run state; only flag truncation
        size = path.stat().st_size
        if size == 0:
            msg = f"{path} is 0 bytes — likely truncated by a disk-full event"
            _log("CRITICAL", msg)
            critical_messages.append(msg)
            worst = 2
    if worst == 0:
        _log("OK", "Critical config files present and non-empty")
    return worst


def main() -> None:
    critical_messages: list[str] = []
    exit_code = max(check_disk(critical_messages), check_config_files(critical_messages))
    if critical_messages:
        _send_alert_email(critical_messages)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
