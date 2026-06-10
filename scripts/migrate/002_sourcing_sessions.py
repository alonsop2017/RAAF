"""
Migration 002: Create sourcing_sessions table.

Stores AI-generated Indeed Smart Sourcing query sessions per requisition.
Idempotent — safe to run multiple times against an existing database.

Usage:
    python scripts/migrate/002_sourcing_sessions.py
    python scripts/migrate/002_sourcing_sessions.py --db /path/to/custom.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.utils.database import get_db, reset_db_instance


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sourcing_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_code     TEXT NOT NULL,
    requisition_id  TEXT NOT NULL,
    query           TEXT NOT NULL,
    search_url      TEXT,
    location        TEXT,
    rationale       TEXT,
    query_name      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""


def upgrade(db_path: Path = None) -> None:
    """Apply the migration — create sourcing_sessions table if not present."""
    if db_path is None:
        db_path = Path(__file__).parent.parent.parent / "data" / "raaf.db"

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_CREATE_TABLE_SQL)
        conn.commit()
        print(f"Migration 002: sourcing_sessions table ready at {db_path}")
    finally:
        conn.close()


def run(db_path: Path) -> None:
    """Entry-point used by the CLI below."""
    upgrade(db_path)

    # Verify
    conn = sqlite3.connect(str(db_path))
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    conn.close()
    print(f"Tables present: {tables}")
    assert "sourcing_sessions" in tables, "sourcing_sessions table not found after migration!"
    print("Migration 002: OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run migration 002: sourcing_sessions")
    parser.add_argument("--db", type=Path, default=None, help="Path to raaf.db")
    args = parser.parse_args()

    db_path = args.db or (Path(__file__).parent.parent.parent / "data" / "raaf.db")
    run(db_path)
