"""
Admin routes for RAAF Web Application.
All routes require admin-level access.
"""

import asyncio
import io
import os
import shutil
import sqlite3 as _sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from web.auth.dependencies import require_admin
from web.auth.config import get_admin_emails, get_allowed_emails
import web.backup_state as _bstate

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

_SETTINGS_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "raaf.db"
_CLIENTS_PATH = Path(__file__).parent.parent.parent / "clients"
_BACKUP_LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "backup.log"


def _load_settings() -> dict:
    with open(_SETTINGS_PATH, "r") as f:
        return yaml.safe_load(f) or {}


def _save_settings(settings: dict) -> None:
    with open(_SETTINGS_PATH, "w") as f:
        yaml.dump(settings, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, _admin=Depends(require_admin)):
    """System status dashboard."""
    import sqlite3

    db_stats = {}
    db_size_mb = None
    if _DB_PATH.exists():
        db_size_mb = round(_DB_PATH.stat().st_size / (1024 * 1024), 2)
        try:
            conn = sqlite3.connect(str(_DB_PATH))
            for table in ("clients", "requisitions", "candidates", "assessments", "batches", "reports"):
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    db_stats[table] = row[0] if row else 0
                except Exception:
                    db_stats[table] = "N/A"
            conn.close()
        except Exception:
            pass

    disk = shutil.disk_usage("/")
    disk_info = {
        "total_gb": round(disk.total / (1024 ** 3), 1),
        "used_gb": round(disk.used / (1024 ** 3), 1),
        "free_gb": round(disk.free / (1024 ** 3), 1),
        "used_pct": round(disk.used / disk.total * 100, 1),
    }

    service_info = {}
    try:
        result = subprocess.run(
            ["systemctl", "show", "raaf-web",
             "--property=ActiveState,MainPID,ExecMainStartTimestamp"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                service_info[k] = v
    except Exception:
        service_info = {"ActiveState": "unknown"}

    app_info = {
        "python_version": sys.version.split()[0],
        "db_mode": os.environ.get("RAAF_DB_MODE", "db"),
        "raaf_version": "1.0.0",
    }

    # Read last 50 lines of backup log
    backup_log = None
    if _BACKUP_LOG_PATH.exists():
        try:
            lines = _BACKUP_LOG_PATH.read_text().splitlines()
            backup_log = "\n".join(lines[-50:])
        except Exception:
            backup_log = None

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": getattr(request.state, "user", None),
        "db_stats": db_stats,
        "db_size_mb": db_size_mb,
        "disk_info": disk_info,
        "service_info": service_info,
        "app_info": app_info,
        "backup_log": backup_log,
    })


# ---------------------------------------------------------------------------
# Users management
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, _admin=Depends(require_admin)):
    """Manage allowed and admin email lists."""
    settings = _load_settings()
    auth = settings.get("auth", {})
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "user": getattr(request.state, "user", None),
        "allowed_emails": auth.get("allowed_emails", []),
        "admin_emails": auth.get("admin_emails", []),
        "message": request.query_params.get("message"),
        "error": request.query_params.get("error"),
    })


@router.post("/users/add")
async def admin_users_add(request: Request, email: str = Form(...), _admin=Depends(require_admin)):
    email = email.strip().lower()
    if not email:
        return RedirectResponse("/admin/users?error=Email+required", status_code=303)
    settings = _load_settings()
    auth = settings.setdefault("auth", {})
    allowed = auth.setdefault("allowed_emails", [])
    if email not in [e.lower() for e in allowed]:
        allowed.append(email)
        _save_settings(settings)
    return RedirectResponse(f"/admin/users?message=Added+{email}", status_code=303)


@router.post("/users/remove")
async def admin_users_remove(request: Request, email: str = Form(...), _admin=Depends(require_admin)):
    email = email.strip().lower()
    settings = _load_settings()
    auth = settings.setdefault("auth", {})
    allowed = auth.get("allowed_emails", [])
    auth["allowed_emails"] = [e for e in allowed if e.strip().lower() != email]
    _save_settings(settings)
    return RedirectResponse(f"/admin/users?message=Removed+{email}", status_code=303)


@router.post("/users/add-admin")
async def admin_users_add_admin(request: Request, email: str = Form(...), _admin=Depends(require_admin)):
    email = email.strip().lower()
    if not email:
        return RedirectResponse("/admin/users?error=Email+required", status_code=303)
    settings = _load_settings()
    auth = settings.setdefault("auth", {})
    admins = auth.setdefault("admin_emails", [])
    if email not in [e.lower() for e in admins]:
        admins.append(email)
        _save_settings(settings)
    return RedirectResponse(f"/admin/users?message=Added+{email}+as+admin", status_code=303)


@router.post("/users/remove-admin")
async def admin_users_remove_admin(request: Request, email: str = Form(...), _admin=Depends(require_admin)):
    email = email.strip().lower()
    settings = _load_settings()
    auth = settings.setdefault("auth", {})
    admins = auth.get("admin_emails", [])
    remaining = [e for e in admins if e.strip().lower() != email]
    if not remaining:
        return RedirectResponse("/admin/users?error=Cannot+remove+last+admin", status_code=303)
    auth["admin_emails"] = remaining
    _save_settings(settings)
    return RedirectResponse(f"/admin/users?message=Removed+{email}+from+admins", status_code=303)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _clients_dir_size_mb() -> float:
    total = sum(f.stat().st_size for f in _CLIENTS_PATH.rglob("*") if f.is_file()) if _CLIENTS_PATH.exists() else 0
    return round(total / (1024 * 1024), 1)


def _backup_page_context(request: Request, **extra) -> dict:
    """Build the common context dict for the backup page."""
    db_size_mb = round(_DB_PATH.stat().st_size / (1024 * 1024), 2) if _DB_PATH.exists() else 0
    settings_size_kb = round(_SETTINGS_PATH.stat().st_size / 1024, 1) if _SETTINGS_PATH.exists() else 0
    clients_size_mb = _clients_dir_size_mb()
    settings = _load_settings()
    lan_path = settings.get("backup", {}).get("lan_path", "")
    ctx = {
        "request": request,
        "user": getattr(request.state, "user", None),
        "db_size_mb": db_size_mb,
        "settings_size_kb": settings_size_kb,
        "clients_size_mb": clients_size_mb,
        "quick_size_mb": round(db_size_mb + settings_size_kb / 1024, 2),
        "full_size_mb": round(db_size_mb + settings_size_kb / 1024 + clients_size_mb, 1),
        "lan_path": lan_path,
    }
    ctx.update(extra)
    return ctx


@router.get("/backup", response_class=HTMLResponse)
async def admin_backup(request: Request, _admin=Depends(require_admin)):
    """Backup page with download options."""
    return templates.TemplateResponse("admin/backup.html", _backup_page_context(request))


@router.get("/backup/download/quick")
async def admin_backup_quick(_admin=Depends(require_admin)):
    """Stream a quick backup zip to the browser."""
    buf, filename = _build_zip("quick")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backup/download/full")
async def admin_backup_full(_admin=Depends(require_admin)):
    """Stream a full backup zip to the browser."""
    buf, filename = _build_zip("full")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_zip(backup_type: str) -> tuple[io.BytesIO, str]:
    """Build a backup zip in memory; return (buffer, filename).

    Uses sqlite3.connection.backup() for a consistent DB snapshot so the
    file captured is never mid-write.  No temp files are created on disk for
    local browser downloads.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"raaf_backup_{backup_type}_{ts}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Consistent DB snapshot via sqlite3.backup()
        if _DB_PATH.exists():
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                src = _sqlite3.connect(str(_DB_PATH))
                dst = _sqlite3.connect(str(tmp_path))
                src.backup(dst)
                dst.close()
                src.close()
                zf.write(tmp_path, "raaf.db")
            finally:
                tmp_path.unlink(missing_ok=True)
        if _SETTINGS_PATH.exists():
            zf.write(_SETTINGS_PATH, "config/settings.yaml")
        if backup_type == "full" and _CLIENTS_PATH.exists():
            for f in _CLIENTS_PATH.rglob("*"):
                if f.is_file():
                    zf.write(f, str(f.relative_to(_CLIENTS_PATH.parent)))
    buf.seek(0)
    return buf, filename


def _run_rsync_backup(backup_type: str, dest_dir: Path) -> tuple[bool, str]:
    """Incremental backup to dest_dir using sqlite3.backup() for the DB and
    rsync for the clients/ directory.

    Writes to dest_dir/latest/ so subsequent runs only copy changed files.
    Updates dest_dir/backup_manifest.yaml with timestamp on success.
    """
    latest = dest_dir / "latest"
    latest.mkdir(parents=True, exist_ok=True)

    # DB: hot consistent snapshot
    if _DB_PATH.exists():
        dst_db = latest / "raaf.db"
        src = _sqlite3.connect(str(_DB_PATH))
        dst = _sqlite3.connect(str(dst_db))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    # Settings
    if _SETTINGS_PATH.exists():
        cfg_dir = latest / "config"
        cfg_dir.mkdir(exist_ok=True)
        shutil.copy2(_SETTINGS_PATH, cfg_dir / "settings.yaml")

    # Full backup: rsync clients/
    if backup_type == "full" and _CLIENTS_PATH.exists():
        clients_dest = latest / "clients"
        clients_dest.mkdir(exist_ok=True)
        result = subprocess.run(
            ["rsync", "-a", "--delete",
             f"{_CLIENTS_PATH}/", f"{clients_dest}/"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            return False, f"rsync failed: {result.stderr.strip()}"

    # Write manifest
    manifest = dest_dir / "backup_manifest.yaml"
    manifest.write_text(
        f"last_backup: {datetime.now().isoformat()}\n"
        f"backup_type: {backup_type}\n"
    )
    return True, str(latest)


@router.post("/backup/save")
async def admin_backup_save(
    request: Request,
    _admin=Depends(require_admin),
    backup_type: str = Form(...),
    lan_path: str = Form(...),
    quiesce: bool = Form(False),
):
    """Save backup to a server-side directory (LAN path) using rsync."""
    lan_path = lan_path.strip()
    if not lan_path:
        ctx = _backup_page_context(request, save_error="LAN path cannot be empty.")
        return templates.TemplateResponse("admin/backup.html", ctx)

    dest_dir = Path(lan_path)
    if not dest_dir.exists():
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            ctx = _backup_page_context(request, save_error=f"Cannot create directory: {e}")
            return templates.TemplateResponse("admin/backup.html", ctx)

    if not dest_dir.is_dir():
        ctx = _backup_page_context(request, save_error=f"Path is not a directory: {lan_path}")
        return templates.TemplateResponse("admin/backup.html", ctx)

    try:
        if quiesce:
            _bstate.backup_in_progress = True
        success, result = await asyncio.to_thread(_run_rsync_backup, backup_type, dest_dir)
    except Exception as e:
        success, result = False, str(e)
    finally:
        _bstate.backup_in_progress = False

    if not success:
        ctx = _backup_page_context(request, save_error=result)
        return templates.TemplateResponse("admin/backup.html", ctx)

    # Persist the path for next time
    settings = _load_settings()
    settings.setdefault("backup", {})["lan_path"] = lan_path
    _save_settings(settings)

    ctx = _backup_page_context(
        request,
        save_success=f"Backup saved to {result}",
        saved_lan_path=lan_path,
    )
    return templates.TemplateResponse("admin/backup.html", ctx)


# ---------------------------------------------------------------------------
# Settings editor
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, _admin=Depends(require_admin)):
    """Settings editor."""
    settings = _load_settings()
    return templates.TemplateResponse("admin/settings.html", {
        "request": request,
        "user": getattr(request.state, "user", None),
        "settings": settings,
        "message": request.query_params.get("message"),
        "error": request.query_params.get("error"),
        "db_mode": os.environ.get("RAAF_DB_MODE", "db"),
        "google_client_id": settings.get("auth", {}).get("google", {}).get("client_id", ""),
        "redirect_uri": settings.get("auth", {}).get("google", {}).get("redirect_uri", ""),
    })


@router.post("/settings/update")
async def admin_settings_update(
    request: Request,
    _admin=Depends(require_admin),
    strong_recommend: int = Form(...),
    recommend: int = Form(...),
    conditional: int = Form(...),
    max_age_hours: int = Form(...),
    recruiter_name: str = Form(...),
    recruiter_title: str = Form(...),
    recruiter_email: str = Form(...),
    recruiter_phone: str = Form(...),
    recruiter_agency: str = Form(...),
    invitation_subject: str = Form(...),
    invitation_opening: str = Form(...),
    invitation_call_to_action: str = Form(...),
    invitation_not_interested: str = Form(...),
    invitation_closing: str = Form(...),
):
    """Update whitelisted settings fields only."""
    settings = _load_settings()

    # Assessment thresholds
    settings.setdefault("assessment", {}).setdefault("default_thresholds", {})
    settings["assessment"]["default_thresholds"]["strong_recommend"] = strong_recommend
    settings["assessment"]["default_thresholds"]["recommend"] = recommend
    settings["assessment"]["default_thresholds"]["conditional"] = conditional

    # Session max age
    settings.setdefault("auth", {}).setdefault("session", {})
    settings["auth"]["session"]["max_age_hours"] = max_age_hours

    # Recruiter profile
    settings["recruiter"] = {
        "name": recruiter_name,
        "title": recruiter_title,
        "email": recruiter_email,
        "phone": recruiter_phone,
        "agency": recruiter_agency,
    }

    # Invitation template
    settings["invitation_template"] = {
        "subject": invitation_subject,
        "opening": invitation_opening,
        "call_to_action": invitation_call_to_action,
        "not_interested": invitation_not_interested,
        "closing": invitation_closing,
    }

    _save_settings(settings)
    return RedirectResponse("/admin/settings?message=Settings+saved+successfully", status_code=303)


# ---------------------------------------------------------------------------
# Log viewer
# ---------------------------------------------------------------------------

@router.get("/logs", response_class=HTMLResponse)
async def admin_logs(request: Request, _admin=Depends(require_admin)):
    """Display recent service logs."""
    log_lines = ""
    error = None
    try:
        result = subprocess.run(
            ["journalctl", "-u", "raaf-web", "-n", "200", "--no-pager", "--output=short"],
            capture_output=True, text=True, timeout=10
        )
        log_lines = result.stdout or "(no log output)"
    except FileNotFoundError:
        error = "journalctl not available on this system"
    except subprocess.TimeoutExpired:
        error = "Log retrieval timed out"
    except Exception as e:
        error = f"Error retrieving logs: {e}"

    return templates.TemplateResponse("admin/logs.html", {
        "request": request,
        "user": getattr(request.state, "user", None),
        "log_lines": log_lines,
        "error": error,
    })


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

@router.post("/database/integrity-check", response_class=HTMLResponse)
async def admin_db_integrity(request: Request, _admin=Depends(require_admin)):
    """Run PRAGMA integrity_check on the database."""
    import sqlite3

    result = "Database not found"
    status = "error"
    if _DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(_DB_PATH))
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            conn.close()
            result = "\n".join(r[0] for r in rows)
            status = "ok" if result.strip() == "ok" else "error"
        except Exception as e:
            result = str(e)
            status = "error"

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": getattr(request.state, "user", None),
        "integrity_result": result,
        "integrity_status": status,
        # Reload other dashboard data
        "db_stats": {},
        "db_size_mb": None,
        "disk_info": {"total_gb": "—", "used_gb": "—", "free_gb": "—", "used_pct": 0},
        "service_info": {},
        "app_info": {"python_version": sys.version.split()[0],
                     "db_mode": os.environ.get("RAAF_DB_MODE", "db"),
                     "raaf_version": "1.0.0"},
    })


@router.post("/database/backfill", response_class=HTMLResponse)
async def admin_db_backfill(request: Request, _admin=Depends(require_admin)):
    """Run the backfill migration script."""
    script = Path(__file__).parent.parent.parent / "scripts" / "migrate" / "backfill_data.py"
    output = ""
    error = None
    if not script.exists():
        error = f"Backfill script not found: {script}"
    else:
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=120
            )
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            error = "Backfill timed out (120s)"
        except Exception as e:
            error = str(e)

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": getattr(request.state, "user", None),
        "backfill_output": output,
        "backfill_error": error,
        "db_stats": {},
        "db_size_mb": None,
        "disk_info": {"total_gb": "—", "used_gb": "—", "free_gb": "—", "used_pct": 0},
        "service_info": {},
        "app_info": {"python_version": sys.version.split()[0],
                     "db_mode": os.environ.get("RAAF_DB_MODE", "db"),
                     "raaf_version": "1.0.0"},
    })
