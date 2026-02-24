"""
Migration 001: Initial schema creation.

Creates all tables, views, and FTS5 index. Idempotent — safe to run
multiple times against an existing database.

Usage:
    python scripts/migrate/001_initial_schema.py
    python scripts/migrate/001_initial_schema.py --db /path/to/custom.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.utils.database import DatabaseManager, reset_db_instance


def run(db_path: Path) -> None:
    print(f"Initialising schema at: {db_path}")
    reset_db_instance()
    db = DatabaseManager(db_path)
    db.initialize()
    print("Schema initialised.")

    # Verification
    conn = sqlite3.connect(str(db_path))
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    views = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
        ).fetchall()
    ]
    version = conn.execute(
        "SELECT version FROM schema_version"
    ).fetchone()[0]
    conn.close()

    print(f"  Schema version : {version}")
    print(f"  Tables ({len(tables)}) : {', '.join(tables)}")
    print(f"  Views  ({len(views)}) : {', '.join(views)}")
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create initial RAAF database schema"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).parent.parent.parent / "data" / "raaf.db",
        help="Path to SQLite database file (default: data/raaf.db)",
    )
    args = parser.parse_args()
    run(args.db)
