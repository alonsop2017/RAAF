#!/usr/bin/env python3
"""
Generate a weekly RAAF system performance report as PDF.

Queries the database, assessment and backup logs, and git history to produce
a management summary saved to data/system-reports/.

Usage:
    python scripts/generate_system_report.py [--days N] [--output FILE]

Cron example (weekly on Monday at 06:00):
    0 6 * * 1 cd /home/alonsop/RAAF && RAAF_DB_MODE=db \
        python scripts/generate_system_report.py >> logs/system_report.log 2>&1
"""

import argparse
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# ---------------------------------------------------------------------------
# Colours (matching RAAF admin UI)
# ---------------------------------------------------------------------------
RAAF_BLUE      = colors.HexColor("#D5E8F0")
RAAF_BLUE_DARK = colors.HexColor("#4A90B8")
HEADER_BG      = colors.HexColor("#2C3E50")
SECTION_BG     = colors.HexColor("#EBF5FB")
ROW_ALT        = colors.HexColor("#F8FCFF")
DANGER_RED     = colors.HexColor("#C0392B")
WARNING_ORANGE = colors.HexColor("#E67E22")
SUCCESS_GREEN  = colors.HexColor("#27AE60")
TEXT_DARK      = colors.HexColor("#2C3E50")

# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

def _git_commits(days: int) -> list[dict]:
    """Return commits from the last `days` days."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        out = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "log",
             f"--since={since}", "--format=%h|%ad|%ae|%s", "--date=short"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace").strip()
        if not out:
            return []
        commits = []
        for line in out.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({"hash": parts[0], "date": parts[1],
                                 "author": parts[2].split("@")[0], "msg": parts[3]})
        return commits
    except Exception:
        return []


def _git_contributors(days: int) -> list[tuple[int, str]]:
    """Return (count, author_email) sorted by commit count."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        out = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "shortlog",
             f"--since={since}", "-sne"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace").strip()
        if not out:
            return []
        result = []
        for line in out.splitlines():
            m = re.match(r"\s*(\d+)\s+(.+?)\s+<(.+?)>", line)
            if m:
                result.append((int(m.group(1)), m.group(2)))
        return result
    except Exception:
        return []


def _pending_cvs() -> list[dict]:
    """Return pending candidate counts per requisition."""
    db_path = PROJECT_ROOT / "data" / "raaf.db"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT cl.company_name, cl.client_code,
                   r.req_id, r.job_title,
                   COUNT(*) AS pending_count
            FROM candidates c
            JOIN requisitions r ON c.requisition_id = r.id
            JOIN clients cl ON r.client_id = cl.id
            WHERE c.status = 'pending'
              AND r.status = 'active'
            GROUP BY r.id
            ORDER BY pending_count DESC
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _db_summary() -> dict:
    """Return high-level counts from the database."""
    db_path = PROJECT_ROOT / "data" / "raaf.db"
    result = {}
    if not db_path.exists():
        return result
    try:
        conn = sqlite3.connect(str(db_path))
        for table in ("clients", "requisitions", "candidates", "assessments", "batches", "reports"):
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                result[table] = row[0] if row else 0
            except Exception:
                result[table] = "N/A"
        result["db_size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 1)
        conn.close()
    except Exception:
        pass
    return result


def _last_assessment() -> dict:
    """Parse assessment.log for the most recent assessment entry."""
    log_path = PROJECT_ROOT / "logs" / "assessment.log"
    if not log_path.exists():
        return {}
    try:
        content = log_path.read_bytes().decode("utf-8", errors="replace")
        # Find all timestamp lines
        ts_pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.+)")
        matches = ts_pattern.findall(content)
        if not matches:
            return {}
        last_ts, last_msg = matches[-1]

        # Find last "Starting assessment" entry and the summary after it
        start_pattern = re.compile(
            r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] Starting assessment: .+?--req\s+(\S+)"
        )
        starts = start_pattern.findall(content)
        summary_pattern = re.compile(
            r"Two-pass complete: (\d+) total \| (\d+) screened out \| (\d+) fully assessed \| (\d+) errors"
        )
        summaries = summary_pattern.findall(content)

        result = {"last_timestamp": last_ts, "last_message": last_msg}
        if starts:
            result["last_req"] = starts[-1][1]
            result["last_start_ts"] = starts[-1][0]
        if summaries:
            total, screened_out, assessed, errors = summaries[-1]
            result["last_total"] = int(total)
            result["last_errors"] = int(errors)
            result["last_assessed"] = int(assessed)
            result["had_errors"] = int(errors) > 0

        # Detect API credit error
        if "credit balance is too low" in content.split(last_ts)[-1][:500]:
            result["api_error"] = "Insufficient Anthropic API credits"
        elif "credit balance is too low" in content[-5000:]:
            result["api_error"] = "Insufficient Anthropic API credits"

        return result
    except Exception:
        return {}


def _backup_stats(days: int) -> dict:
    """Parse backup.log for recent backup activity."""
    log_path = PROJECT_ROOT / "logs" / "backup.log"
    if not log_path.exists():
        return {}
    try:
        content = log_path.read_text(errors="replace")
        cutoff = datetime.now() - timedelta(days=days)

        # Format 1: [YYYY-MM-DD HH:MM:SS] ...
        fmt1_ts = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.+)")
        # Format 2: YYYY-MM-DD HH:MM:SS,mmm [LEVEL] ...
        fmt2_ts = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[(\w+)\] (.+)")

        starts, successes, failures = [], [], []
        last_size = None

        for line in content.splitlines():
            ts_str = msg = None
            m1 = fmt1_ts.match(line)
            m2 = fmt2_ts.match(line)
            if m1:
                ts_str, msg = m1.group(1), m1.group(2)
            elif m2:
                ts_str, msg = m2.group(1), m2.group(3)

            if not ts_str:
                continue

            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if ts < cutoff:
                continue

            if msg and ("starting" in msg.lower() and "backup" in msg.lower()):
                starts.append(ts_str)
            if msg and ("backup complete" in msg.lower() or "completed successfully" in msg.lower()):
                successes.append(ts_str)
            if msg and "error" in msg.lower():
                failures.append(ts_str)

            # Extract archive size (e.g. "Archive created: 1007M")
            size_m = re.search(r"Archive created:\s+(\S+)", msg or "")
            if size_m:
                last_size = size_m.group(1)

        last_backup = successes[-1] if successes else None
        return {
            "starts": len(starts),
            "successes": len(successes),
            "failures": len(failures),
            "last_backup": last_backup,
            "last_size": last_size,
            "success_rate": (
                round(len(successes) / len(starts) * 100) if starts else None
            ),
        }
    except Exception:
        return {}


def _days_since(ts_str: str) -> str:
    """Return human-readable time since a timestamp string."""
    try:
        ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - ts
        d = delta.days
        h = delta.seconds // 3600
        if d == 0:
            return f"{h}h ago"
        elif d == 1:
            return "1 day ago"
        else:
            return f"{d} days ago"
    except Exception:
        return ts_str


# ---------------------------------------------------------------------------
# PDF building
# ---------------------------------------------------------------------------

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"],
                                fontSize=22, textColor=colors.white,
                                spaceAfter=4, leading=26),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"],
                                   fontSize=11, textColor=colors.HexColor("#BDC3C7"),
                                   spaceAfter=2),
        "section": ParagraphStyle("section", parent=base["Heading2"],
                                  fontSize=13, textColor=RAAF_BLUE_DARK,
                                  spaceBefore=14, spaceAfter=6, leading=16),
        "body": ParagraphStyle("body", parent=base["Normal"],
                               fontSize=10, textColor=TEXT_DARK, leading=14),
        "small": ParagraphStyle("small", parent=base["Normal"],
                                fontSize=8.5, textColor=colors.HexColor("#7F8C8D")),
        "alert": ParagraphStyle("alert", parent=base["Normal"],
                                fontSize=10, textColor=DANGER_RED, leading=14),
        "success": ParagraphStyle("success", parent=base["Normal"],
                                  fontSize=10, textColor=SUCCESS_GREEN, leading=14),
        "mono": ParagraphStyle("mono", parent=base["Code"],
                               fontSize=8.5, leading=12),
    }


def _header_table(period_label: str, generated: str) -> Table:
    data = [
        [Paragraph("<b>RAAF — System Performance Report</b>",
                   ParagraphStyle("th", fontSize=20, textColor=colors.white,
                                  fontName="Helvetica-Bold")),
         ""],
        [Paragraph(f"Period: {period_label}",
                   ParagraphStyle("ts", fontSize=10, textColor=colors.HexColor("#BDC3C7"))),
         Paragraph(f"Generated: {generated}",
                   ParagraphStyle("ts2", fontSize=10, textColor=colors.HexColor("#BDC3C7"),
                                  alignment=2))],
    ]
    t = Table(data, colWidths=[4.5 * inch, 2.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 18),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (0, -1), 20),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 20),
        ("SPAN", (0, 0), (0, 0)),
    ]))
    return t


def _kv_table(rows: list[tuple], col_widths=None) -> Table:
    if col_widths is None:
        col_widths = [2.2 * inch, 4.8 * inch]
    st = ParagraphStyle("kv_val", fontSize=10, textColor=TEXT_DARK)
    st_k = ParagraphStyle("kv_key", fontSize=10, textColor=TEXT_DARK, fontName="Helvetica-Bold")
    data = [[Paragraph(k, st_k), Paragraph(str(v), st)] for k, v in rows]
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, -1), 8),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5D8DC")),
    ]))
    return t


def _pending_table(pending: list[dict]) -> Table:
    header = ["Client", "Requisition", "Role", "Pending CVs"]
    st_h = ParagraphStyle("ph", fontSize=9.5, textColor=colors.white, fontName="Helvetica-Bold")
    st_v = ParagraphStyle("pv", fontSize=9.5, textColor=TEXT_DARK)
    st_n = ParagraphStyle("pn", fontSize=9.5, textColor=DANGER_RED, fontName="Helvetica-Bold")

    data = [[Paragraph(h, st_h) for h in header]]
    total = 0
    for row in pending:
        n = row["pending_count"]
        total += n
        num_style = st_n if n >= 20 else st_v
        data.append([
            Paragraph(row["company_name"], st_v),
            Paragraph(row["req_id"], st_v),
            Paragraph(row["job_title"], st_v),
            Paragraph(str(n), num_style),
        ])
    # Totals row
    st_tot = ParagraphStyle("pt", fontSize=9.5, textColor=TEXT_DARK, fontName="Helvetica-Bold")
    data.append([
        Paragraph("TOTAL", st_tot), "", "",
        Paragraph(str(total), ParagraphStyle("ptt", fontSize=9.5,
                                             textColor=RAAF_BLUE_DARK, fontName="Helvetica-Bold")),
    ])

    col_widths = [1.8 * inch, 2.0 * inch, 2.2 * inch, 1.0 * inch]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), RAAF_BLUE_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ROW_ALT]),
        ("BACKGROUND", (0, -1), (-1, -1), SECTION_BG),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5D8DC")),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("SPAN", (1, -1), (2, -1)),
    ]))
    return t


def _commits_table(commits: list[dict]) -> Table:
    if not commits:
        return None
    header = ["Date", "Author", "Commit"]
    st_h = ParagraphStyle("ch", fontSize=9, textColor=colors.white, fontName="Helvetica-Bold")
    st_v = ParagraphStyle("cv", fontSize=8.5, textColor=TEXT_DARK)
    st_hash = ParagraphStyle("chash", fontSize=8.5, textColor=RAAF_BLUE_DARK,
                             fontName="Helvetica-Oblique")
    data = [[Paragraph(h, st_h) for h in header]]
    for c in commits[:25]:  # cap at 25 rows
        data.append([
            Paragraph(c["date"], st_v),
            Paragraph(c["author"], st_v),
            Paragraph(f'<font name="Helvetica-Oblique" color="#4A90B8">[{c["hash"]}]</font> '
                      + c["msg"], st_v),
        ])
    col_widths = [0.85 * inch, 1.3 * inch, 4.85 * inch]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), RAAF_BLUE_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5D8DC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def build_pdf(output_path: Path, days: int) -> None:
    now = datetime.now()
    period_start = now - timedelta(days=days)
    period_label = f"{period_start.strftime('%b %d, %Y')} — {now.strftime('%b %d, %Y')}"
    generated = now.strftime("%Y-%m-%d %H:%M")

    # Gather data
    commits     = _git_commits(days)
    contribs    = _git_contributors(days)
    pending     = _pending_cvs()
    db_summary  = _db_summary()
    last_assess = _last_assessment()
    backups     = _backup_stats(days)

    st = _styles()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.75 * inch,
    )

    story = []

    # ── Header ──────────────────────────────────────────────────────────────
    story.append(_header_table(period_label, generated))
    story.append(Spacer(1, 16))

    # ── Executive Summary ────────────────────────────────────────────────────
    story.append(Paragraph("Executive Summary", st["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=RAAF_BLUE, spaceAfter=8))

    total_pending = sum(r["pending_count"] for r in pending)
    api_status = "ERROR — Insufficient API credits" if last_assess.get("api_error") else "OK"
    api_color = DANGER_RED if last_assess.get("api_error") else SUCCESS_GREEN

    summary_rows = [
        ("Reporting period", f"{days} days ({period_label})"),
        ("Commits (period)",  str(len(commits)) if commits is not None else "0"),
        ("Total pending CVs", str(total_pending)),
        ("Active requisitions", str(len(pending))),
        ("Last assessment",
         f"{last_assess.get('last_start_ts', 'Unknown')} "
         f"({_days_since(last_assess['last_start_ts'])})"
         if last_assess.get("last_start_ts") else "No assessments found"),
        ("Assessment API status", api_status),
        ("Backups (period)",
         f"{backups.get('successes', 0)}/{backups.get('starts', 0)} successful"
         if backups else "No backup data"),
    ]
    story.append(_kv_table(summary_rows))
    story.append(Spacer(1, 14))

    # ── Pending CVs ──────────────────────────────────────────────────────────
    story.append(Paragraph("Pending CV Assessments", st["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=RAAF_BLUE, spaceAfter=8))

    if pending:
        story.append(_pending_table(pending))
        story.append(Spacer(1, 6))
        if total_pending > 0 and last_assess.get("api_error"):
            story.append(Paragraph(
                f"⚠ {total_pending} CVs are queued but assessments are blocked: "
                f"{last_assess['api_error']}. Top up Anthropic API credits to resume.",
                st["alert"],
            ))
    else:
        story.append(Paragraph("No pending candidates found.", st["body"]))
    story.append(Spacer(1, 14))

    # ── Assessment System ────────────────────────────────────────────────────
    story.append(Paragraph("Assessment System", st["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=RAAF_BLUE, spaceAfter=8))

    if last_assess:
        assess_rows = []
        if last_assess.get("last_start_ts"):
            assess_rows.append(("Last run", last_assess["last_start_ts"] +
                                f" ({_days_since(last_assess['last_start_ts'])})"))
        if last_assess.get("last_req"):
            assess_rows.append(("Requisition", last_assess["last_req"]))
        if "last_total" in last_assess:
            assess_rows.append(("Candidates processed",
                                f"{last_assess['last_total']} total, "
                                f"{last_assess['last_assessed']} assessed, "
                                f"{last_assess['last_errors']} errors"))
        if last_assess.get("api_error"):
            assess_rows.append(("Failure reason", last_assess["api_error"]))
        if assess_rows:
            story.append(_kv_table(assess_rows))
    else:
        story.append(Paragraph("No assessment log data found.", st["body"]))
    story.append(Spacer(1, 14))

    # ── Database Summary ─────────────────────────────────────────────────────
    story.append(Paragraph("Database Summary", st["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=RAAF_BLUE, spaceAfter=8))

    if db_summary:
        db_rows = [
            ("Database size", f"{db_summary.get('db_size_mb', '?')} MB"),
            ("Clients", str(db_summary.get("clients", "N/A"))),
            ("Requisitions", str(db_summary.get("requisitions", "N/A"))),
            ("Candidates (total)", str(db_summary.get("candidates", "N/A"))),
            ("Assessments", str(db_summary.get("assessments", "N/A"))),
            ("Batches", str(db_summary.get("batches", "N/A"))),
            ("Reports", str(db_summary.get("reports", "N/A"))),
        ]
        story.append(_kv_table(db_rows))
    else:
        story.append(Paragraph("Database not found.", st["body"]))
    story.append(Spacer(1, 14))

    # ── Backup Operations ────────────────────────────────────────────────────
    story.append(Paragraph("Backup Operations", st["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=RAAF_BLUE, spaceAfter=8))

    if backups:
        success_rate = backups.get("success_rate")
        rate_str = f"{success_rate}%" if success_rate is not None else "N/A"
        backup_rows = [
            ("Backups initiated", str(backups.get("starts", 0))),
            ("Backups succeeded", str(backups.get("successes", 0))),
            ("Backups failed", str(backups.get("failures", 0))),
            ("Success rate", rate_str),
            ("Last successful backup",
             f"{backups['last_backup']} ({_days_since(backups['last_backup'])})"
             if backups.get("last_backup") else "None"),
            ("Last archive size", backups.get("last_size", "Unknown")),
        ]
        story.append(_kv_table(backup_rows))
    else:
        story.append(Paragraph("No backup log data found.", st["body"]))
    story.append(Spacer(1, 14))

    # ── Development Activity ─────────────────────────────────────────────────
    story.append(Paragraph("Development Activity", st["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=RAAF_BLUE, spaceAfter=8))

    if commits:
        dev_rows = [("Commits", str(len(commits)))]
        if contribs:
            dev_rows.append(("Contributors",
                             ", ".join(f"{name} ({n})" for n, name in contribs)))
        story.append(_kv_table(dev_rows))
        story.append(Spacer(1, 8))
        t = _commits_table(commits)
        if t:
            story.append(t)
        if len(commits) > 25:
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"… and {len(commits) - 25} more commits not shown.",
                                   st["small"]))
    else:
        story.append(Paragraph(
            f"No commits in the last {days} days. Repository is in maintenance hold.",
            st["body"],
        ))
    story.append(Spacer(1, 14))

    # ── Footer ───────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#BDC3C7"),
                            spaceBefore=6, spaceAfter=6))
    story.append(Paragraph(
        f"RAAF System Performance Report • Generated {generated} • "
        "Archtekt Consulting Inc. — CONFIDENTIAL",
        ParagraphStyle("footer", fontSize=8, textColor=colors.HexColor("#95A5A6"),
                       alignment=TA_CENTER),
    ))

    doc.build(story)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate RAAF system performance report (PDF)")
    parser.add_argument("--days", type=int, default=14,
                        help="Reporting period in days (default: 14)")
    parser.add_argument("--output", type=str,
                        help="Output file path (default: data/system-reports/system_report_YYYYMMDD.pdf)")
    args = parser.parse_args()

    if args.output:
        output_path = Path(args.output)
    else:
        reports_dir = PROJECT_ROOT / "data" / "system-reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        filename = f"system_report_{datetime.now().strftime('%Y%m%d')}.pdf"
        output_path = reports_dir / filename

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
          f"Generating system report (last {args.days} days)...")
    build_pdf(output_path, args.days)
    size_kb = round(output_path.stat().st_size / 1024, 1)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
          f"Report saved: {output_path} ({size_kb} KB)")


if __name__ == "__main__":
    main()
