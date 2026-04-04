#!/usr/bin/env python3
"""
RAAF Pre-Start Data Verification
─────────────────────────────────────────────────────────────────────────────
Validates data integrity before the application server is allowed to start.
Run automatically by the raaf-verify service in docker-compose.yml.

Checks performed:
  1. Required directory structure exists
  2. Critical configuration files are present
  3. SQLite database integrity (PRAGMA integrity_check)
  4. Database schema — all expected tables are present
  5. Record counts (informational)
  6. Client data presence (warning if empty)

Exit codes:
  0  All critical checks passed — safe to start the application
  1  One or more critical checks failed — do NOT start the application
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import sqlite3
from pathlib import Path
from typing import NamedTuple

# ── Paths ─────────────────────────────────────────────────────────────────────
APP_ROOT   = Path("/app")
DATA_DIR   = APP_ROOT / "data"
CLIENTS_DIR = APP_ROOT / "clients"
ARCHIVE_DIR = APP_ROOT / "archive"
LOGS_DIR   = APP_ROOT / "logs"
CONFIG_DIR  = APP_ROOT / "config"
DB_PATH    = DATA_DIR / "raaf.db"

# ── Critical files (app cannot function without these) ────────────────────────
CRITICAL_CONFIG_FILES = [
    CONFIG_DIR / "settings.yaml",
]

# ── Expected-but-optional files (warnings only) ───────────────────────────────
EXPECTED_CONFIG_FILES = [
    CONFIG_DIR / "pcr_credentials.yaml",
    CONFIG_DIR / "claude_credentials.yaml",
]

# ── Expected SQLite tables ────────────────────────────────────────────────────
EXPECTED_TABLES = [
    "clients",
    "client_contacts",
    "requisitions",
    "candidates",
    "assessments",
    "batches",
    "reports",
    "pcr_positions_cache",
]

# ── ANSI colours ──────────────────────────────────────────────────────────────
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"
INFO = "\033[94mℹ\033[0m"


class CheckResult(NamedTuple):
    name: str
    passed: bool
    critical: bool
    message: str


results: list[CheckResult] = []


def check(name: str, passed: bool, message: str, critical: bool = True) -> bool:
    result = CheckResult(name=name, passed=passed, critical=critical, message=message)
    results.append(result)
    icon = PASS if passed else (FAIL if critical else WARN)
    print(f"  {icon}  {name}: {message}")
    return passed


def run_checks() -> bool:
    print()
    print("═" * 64)
    print("  RAAF Pre-Start Data Verification")
    print("═" * 64)

    all_critical_passed = True

    # ── 1. Directory structure ─────────────────────────────────────────────────
    print("\n[1/5] Directory Structure")
    required_dirs = [
        (DATA_DIR,    "data/",    True),
        (CLIENTS_DIR, "clients/", True),
        (ARCHIVE_DIR, "archive/", False),
        (LOGS_DIR,    "logs/",    False),
        (CONFIG_DIR,  "config/",  True),
    ]
    for dir_path, label, is_critical in required_dirs:
        exists = dir_path.is_dir()
        msg = "exists" if exists else "MISSING"
        if not check(label, exists, msg, critical=is_critical):
            if is_critical:
                all_critical_passed = False

    # ── 2. Configuration files ─────────────────────────────────────────────────
    print("\n[2/5] Configuration Files")
    for cfg_path in CRITICAL_CONFIG_FILES:
        exists = cfg_path.exists()
        msg = "present" if exists else f"MISSING — required at {cfg_path}"
        if not check(cfg_path.name, exists, msg, critical=True):
            all_critical_passed = False

    for cfg_path in EXPECTED_CONFIG_FILES:
        exists = cfg_path.exists()
        msg = "present" if exists else "not found — app features may be limited"
        check(cfg_path.name, exists, msg, critical=False)

    # Verify session secret is available
    session_key_set = bool(os.environ.get("SESSION_SECRET_KEY"))
    env_file_exists = (APP_ROOT / ".env").exists()
    env_ok = session_key_set or env_file_exists
    if session_key_set:
        msg = "SESSION_SECRET_KEY set via environment"
    elif env_file_exists:
        msg = ".env file present"
    else:
        msg = "SESSION_SECRET_KEY not set and .env not found — authentication will fail"
    if not check("session secret", env_ok, msg, critical=True):
        all_critical_passed = False

    # ── 3. SQLite database ─────────────────────────────────────────────────────
    print("\n[3/5] SQLite Database")
    if not DB_PATH.exists():
        check(
            "raaf.db",
            False,
            "not found — the migration script will create it on first app start",
            critical=False,
        )
    else:
        db_size_kb = DB_PATH.stat().st_size / 1024
        check("raaf.db", True, f"present ({db_size_kb:.1f} KB)")

        # Integrity check
        try:
            conn = sqlite3.connect(str(DB_PATH))
            row = conn.execute("PRAGMA integrity_check;").fetchone()
            conn.close()
            ok = row[0] == "ok"
            msg = "integrity OK" if ok else f"INTEGRITY FAILURE: {row[0]}"
            if not check("PRAGMA integrity_check", ok, msg, critical=True):
                all_critical_passed = False
        except Exception as exc:
            check("PRAGMA integrity_check", False, f"ERROR: {exc}", critical=True)
            all_critical_passed = False

        # Schema validation
        try:
            conn = sqlite3.connect(str(DB_PATH))
            existing_tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
            conn.close()
            missing = [t for t in EXPECTED_TABLES if t not in existing_tables]
            if missing:
                msg = f"missing tables: {', '.join(missing)} — run migration script"
                check("schema", False, msg, critical=False)
            else:
                check("schema", True, f"all {len(EXPECTED_TABLES)} expected tables present")
        except Exception as exc:
            check("schema", False, f"ERROR reading schema: {exc}", critical=False)

        # Record counts (informational, no pass/fail)
        try:
            conn = sqlite3.connect(str(DB_PATH))
            tables_to_count = ["clients", "requisitions", "candidates", "assessments"]
            counts = {}
            for tbl in tables_to_count:
                try:
                    counts[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl};").fetchone()[0]
                except Exception:
                    counts[tbl] = "?"
            conn.close()
            summary = "  |  ".join(f"{k}: {v}" for k, v in counts.items())
            print(f"  {INFO}  record counts — {summary}")
        except Exception:
            pass

    # ── 4. Client data ─────────────────────────────────────────────────────────
    print("\n[4/5] Client Data")
    if CLIENTS_DIR.is_dir():
        client_folders = [d for d in CLIENTS_DIR.iterdir() if d.is_dir()]
        if client_folders:
            names = ", ".join(d.name for d in sorted(client_folders)[:6])
            suffix = f" (…+{len(client_folders)-6} more)" if len(client_folders) > 6 else ""
            check(
                "clients/",
                True,
                f"{len(client_folders)} client(s): {names}{suffix}",
                critical=False,
            )
        else:
            check(
                "clients/",
                False,
                "directory is empty — no client data found (expected after restore)",
                critical=False,
            )
    else:
        check("clients/", False, "directory missing", critical=True)
        all_critical_passed = False

    # ── 5. Config file permissions ─────────────────────────────────────────────
    print("\n[5/5] Config File Permissions")
    sensitive_files = [
        CONFIG_DIR / "pcr_credentials.yaml",
        CONFIG_DIR / "claude_credentials.yaml",
        CONFIG_DIR / ".token_store.json",
    ]
    any_perm_found = False
    for f in sensitive_files:
        if not f.exists():
            continue
        any_perm_found = True
        mode = oct(f.stat().st_mode)[-3:]
        safe = mode in ("600", "400")
        msg = f"mode {mode}" + (" — OK" if safe else " — WARNING: readable by others")
        check(f.name, safe, msg, critical=False)
    if not any_perm_found:
        print(f"  {INFO}  No sensitive credential files present yet (expected after first run)")

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print("─" * 64)
    total    = len(results)
    passed   = sum(1 for r in results if r.passed)
    failures = sum(1 for r in results if not r.passed and r.critical)
    warnings = sum(1 for r in results if not r.passed and not r.critical)

    print(f"  Results: {passed}/{total} passed  |  {failures} critical failure(s)  |  {warnings} warning(s)")
    print()

    if all_critical_passed:
        print(f"  {PASS}  Verification PASSED — application may start.")
    else:
        print(f"  {FAIL}  Verification FAILED — resolve the issues above before starting.")
        print()
        print("  Critical failures:")
        for r in results:
            if not r.passed and r.critical:
                print(f"    • {r.name}: {r.message}")

    print("═" * 64)
    print()

    return all_critical_passed


if __name__ == "__main__":
    ok = run_checks()
    sys.exit(0 if ok else 1)
