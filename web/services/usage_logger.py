"""
Application Usage Logger for RAAF.

Tracks user logins, page navigation, and errors in a separate SQLite database
(data/usage.db) to avoid polluting the main raaf.db.

Event types:
  login        — user authenticated (method: google | email)
  logout       — user signed out
  nav          — page navigation (non-static GET/POST)
  error        — 4xx / 5xx responses or uncaught exceptions
"""

import csv
import io
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "usage.db"
_local = threading.local()


# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Return a per-thread connection, creating the DB if needed."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _init_schema(conn)
        _local.conn = conn
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS usage_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL    NOT NULL,           -- Unix timestamp (float)
            event_type  TEXT    NOT NULL,           -- login | logout | nav | error
            email       TEXT,                       -- user email (nullable for anon)
            method      TEXT,                       -- HTTP method or auth method
            path        TEXT,                       -- URL path
            status_code INTEGER,                    -- HTTP status
            duration_ms INTEGER,                   -- response time ms
            detail      TEXT                        -- extra info (error msg, etc.)
        );

        CREATE INDEX IF NOT EXISTS idx_usage_ts    ON usage_events(ts);
        CREATE INDEX IF NOT EXISTS idx_usage_email ON usage_events(email);
        CREATE INDEX IF NOT EXISTS idx_usage_type  ON usage_events(event_type);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Core write
# ---------------------------------------------------------------------------

def log_event(
    event_type: str,
    email: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    status_code: Optional[int] = None,
    duration_ms: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    """Insert one usage event. Never raises — errors are silently swallowed."""
    try:
        conn = _get_conn()
        conn.execute(
            """INSERT INTO usage_events
               (ts, event_type, email, method, path, status_code, duration_ms, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), event_type, email, method, path, status_code, duration_ms, detail),
        )
        conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_stats(since_ts: Optional[float] = None) -> dict:
    """
    Return summary stats for the dashboard.

    since_ts: Unix timestamp; if None, covers all time.
    Returns dict with keys: total_requests, unique_users, error_count,
    avg_response_ms, login_count_today, top_paths (list of {path, count}).
    """
    conn = _get_conn()
    where = "WHERE ts >= ?" if since_ts else ""
    params = (since_ts,) if since_ts else ()

    nav_where = f"WHERE event_type = 'nav' {'AND ts >= ?' if since_ts else ''}"
    nav_params = (since_ts,) if since_ts else ()

    # today's start (UTC midnight)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    row = conn.execute(f"""
        SELECT
            COUNT(*)                                          AS total_requests,
            COUNT(DISTINCT email)                             AS unique_users,
            SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS error_count,
            AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) AS avg_response_ms
        FROM usage_events
        {where}
    """, params).fetchone()

    login_row = conn.execute("""
        SELECT COUNT(*) FROM usage_events
        WHERE event_type = 'login' AND ts >= ?
    """, (today_start,)).fetchone()

    top_paths = conn.execute(f"""
        SELECT path, COUNT(*) AS cnt
        FROM usage_events
        {nav_where}
        AND path IS NOT NULL
        GROUP BY path
        ORDER BY cnt DESC
        LIMIT 10
    """, nav_params).fetchall()

    return {
        "total_requests": row["total_requests"] or 0,
        "unique_users": row["unique_users"] or 0,
        "error_count": row["error_count"] or 0,
        "avg_response_ms": round(row["avg_response_ms"] or 0),
        "login_count_today": login_row[0] if login_row else 0,
        "top_paths": [{"path": r["path"], "count": r["cnt"]} for r in top_paths],
    }


def get_logs(
    limit: int = 500,
    offset: int = 0,
    event_type: Optional[str] = None,
    email: Optional[str] = None,
    since_ts: Optional[float] = None,
    until_ts: Optional[float] = None,
    status_code_gte: Optional[int] = None,
) -> list[dict]:
    """Return recent usage events as a list of dicts, newest first."""
    conn = _get_conn()
    clauses = []
    params: list = []

    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if email:
        clauses.append("email LIKE ?")
        params.append(f"%{email}%")
    if since_ts:
        clauses.append("ts >= ?")
        params.append(since_ts)
    if until_ts:
        clauses.append("ts <= ?")
        params.append(until_ts)
    if status_code_gte:
        clauses.append("status_code >= ?")
        params.append(status_code_gte)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params += [limit, offset]

    rows = conn.execute(f"""
        SELECT id, ts, event_type, email, method, path, status_code, duration_ms, detail
        FROM usage_events
        {where}
        ORDER BY ts DESC
        LIMIT ? OFFSET ?
    """, params).fetchall()

    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "ts": r["ts"],
            "datetime": datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": r["event_type"],
            "email": r["email"] or "—",
            "method": r["method"] or "—",
            "path": r["path"] or "—",
            "status_code": r["status_code"],
            "duration_ms": r["duration_ms"],
            "detail": r["detail"] or "",
        })
    return result


def export_csv(
    since_ts: Optional[float] = None,
    until_ts: Optional[float] = None,
) -> str:
    """Return usage events as a CSV string."""
    rows = get_logs(limit=50000, since_ts=since_ts, until_ts=until_ts)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "datetime", "event_type", "email", "method", "path",
                    "status_code", "duration_ms", "detail"],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
