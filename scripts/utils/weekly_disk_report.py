#!/usr/bin/env python3
"""
Weekly disk usage summary, emailed to admins regardless of severity.

Unlike check_disk_health.py (which only fires on WARNING/CRITICAL
thresholds), this always sends — routine visibility into disk trends so
slow bloat (like the archive/ duplication or unbounded pcr_sync.log seen
in 2026-07/08) gets noticed before it becomes an incident.

Run weekly via cron.
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
LOG_FILE = ROOT / "logs" / "weekly_disk_report.log"

# Directories bind-mounted into the container that are worth reporting on
TRACKED_DIRS = ["data", "clients", "archive", "logs", "backups", "Direct_Submissions", "config"]


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _dir_size_human(path: Path) -> str:
    if not path.exists():
        return "—"
    try:
        result = subprocess.run(["du", "-sh", str(path)], capture_output=True, text=True, timeout=30)
        return result.stdout.split()[0] if result.returncode == 0 else "?"
    except Exception:
        return "?"


def build_report() -> str:
    import shutil

    usage = shutil.disk_usage("/")
    pct = usage.used / usage.total * 100
    used_gb = usage.used / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    free_gb = usage.free / (1024 ** 3)

    lines = [
        f"RAAF weekly disk report — {datetime.now(timezone.utc):%Y-%m-%d}",
        "",
        f"Root disk: {used_gb:.1f}G / {total_gb:.1f}G used ({pct:.1f}%), {free_gb:.1f}G free",
        "",
        "Breakdown:",
    ]
    for name in TRACKED_DIRS:
        size = _dir_size_human(ROOT / name)
        lines.append(f"  {size:>8}  {name}/")

    lines.append("")
    lines.append("(Docker image/build-cache usage isn't visible from inside this "
                  "container — check `docker system df` on the droplet directly if needed.)")
    return "\n".join(lines)


def main() -> None:
    body = build_report()
    _log("Weekly disk report generated")

    try:
        import yaml
        settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text()) or {}
        admin_emails = settings.get("auth", {}).get("admin_emails", [])
        if not admin_emails:
            _log("No admin_emails configured — skipping email")
            return

        from scripts.email_ingestion.gmail_client import send_email
        send_email(
            to=", ".join(admin_emails),
            subject="[RAAF] Weekly disk usage report",
            body=body,
            from_name="RAAF Disk Report",
        )
        _log(f"Report emailed to {admin_emails}")
    except Exception as e:
        _log(f"Failed to send report email: {e}")


if __name__ == "__main__":
    main()
