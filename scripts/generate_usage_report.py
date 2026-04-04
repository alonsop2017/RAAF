#!/usr/bin/env python3
"""
Generate a usage report from data/usage.db.

Usage:
    python scripts/generate_usage_report.py [--days N] [--csv] [--output FILE]

Options:
    --days N       Report period in days (default: 7)
    --csv          Output raw CSV instead of human-readable summary
    --output FILE  Write output to FILE instead of stdout

Cron example (daily report at 08:00, appended to log):
    0 8 * * * cd /home/alonsop/RAAF && RAAF_DB_MODE=db \
        python scripts/generate_usage_report.py --days 1 >> logs/usage_report.log 2>&1
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on terminals with restrictive encodings
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from web.services.usage_logger import get_stats, get_logs, export_csv


def print_summary(stats: dict, logs: list, days: int) -> str:
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"{'='*60}",
        f"RAAF Usage Report - {now_str}",
        f"Period: last {days} day{'s' if days != 1 else ''}",
        f"{'=' * 60}",
        "",
        "SUMMARY",
        f"  Total requests   : {stats['total_requests']}",
        f"  Unique users     : {stats['unique_users']}",
        f"  Errors (4xx/5xx) : {stats['error_count']}",
        f"  Avg response     : {stats['avg_response_ms']} ms",
        f"  Logins today     : {stats['login_count_today']}",
        "",
    ]

    if stats["top_paths"]:
        lines.append("TOP PAGES")
        for p in stats["top_paths"]:
            lines.append(f"  {p['count']:>6}  {p['path']}")
        lines.append("")

    # Login events
    logins = [e for e in logs if e["event_type"] == "login"]
    if logins:
        lines.append("LOGINS")
        for e in logins:
            lines.append(f"  {e['datetime']}  {e['email']}  [{e['method']}]")
        lines.append("")

    # Errors
    errors = [e for e in logs if e["event_type"] == "error"]
    if errors:
        lines.append(f"ERRORS ({len(errors)} total)")
        for e in errors[:20]:
            detail = f"  {e['detail']}" if e["detail"] else ""
            lines.append(f"  {e['datetime']}  {e['status_code']}  {e['path']}{detail}")
        if len(errors) > 20:
            lines.append(f"  ... and {len(errors) - 20} more")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate RAAF usage report")
    parser.add_argument("--days", type=int, default=7, help="Report period in days (default: 7)")
    parser.add_argument("--csv", action="store_true", help="Output raw CSV")
    parser.add_argument("--output", type=str, help="Output file path (default: stdout)")
    args = parser.parse_args()

    since_ts = time.time() - args.days * 86400

    if args.csv:
        output = export_csv(since_ts=since_ts)
    else:
        stats = get_stats(since_ts=since_ts)
        logs = get_logs(limit=1000, since_ts=since_ts)
        output = print_summary(stats, logs, args.days)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Report written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
