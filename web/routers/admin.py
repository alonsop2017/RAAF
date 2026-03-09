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
import time
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

    fs_stats = _collect_fs_stats()

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": getattr(request.state, "user", None),
        "db_stats": db_stats,
        "db_size_mb": db_size_mb,
        "disk_info": disk_info,
        "service_info": service_info,
        "app_info": app_info,
        "backup_log": backup_log,
        "fs_stats": fs_stats,
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


def _collect_fs_stats() -> dict:
    """Scan the clients/ directory and return structured file system stats."""
    stats = {
        "clients": 0,
        "requisitions": 0,
        "resumes_raw": {"count": 0, "size_mb": 0.0},
        "resumes_extracted": {"count": 0, "size_mb": 0.0},
        "assessments": {"count": 0, "size_mb": 0.0},
        "reports": {"count": 0, "size_mb": 0.0},
        "frameworks": {"count": 0, "size_mb": 0.0},
        "total_size_mb": 0.0,
        "by_client": [],
    }
    if not _CLIENTS_PATH.exists():
        return stats

    def _sz(p: Path) -> int:
        return p.stat().st_size if p.is_file() else 0

    def _count_and_size(root: Path, pattern: str) -> tuple[int, float]:
        files = list(root.rglob(pattern)) if root.exists() else []
        total = sum(_sz(f) for f in files)
        return len(files), round(total / (1024 * 1024), 3)

    for client_dir in sorted(_CLIENTS_PATH.iterdir()):
        if not client_dir.is_dir() or client_dir.name.startswith("."):
            continue
        stats["clients"] += 1
        c_resumes_raw = c_resumes_ext = c_assessments = c_reports = 0
        c_size = 0.0
        req_count = 0

        req_root = client_dir / "requisitions"
        if req_root.exists():
            for req_dir in sorted(req_root.iterdir()):
                if not req_dir.is_dir():
                    continue
                req_count += 1

                # Raw resumes: incoming/ + batches/*/original(s)/
                raw_n, raw_mb = _count_and_size(req_dir / "resumes" / "incoming", "*.*")
                for batch_dir in (req_dir / "resumes" / "batches").glob("*") if (req_dir / "resumes" / "batches").exists() else []:
                    for orig_sub in ("original", "originals"):
                        bn, bm = _count_and_size(batch_dir / orig_sub, "*.*")
                        raw_n += bn; raw_mb += bm
                # Deduplicate: if incoming and batch originals overlap, trust batch count
                # (don't double-count — use processed/ as extracted source instead)
                ext_n, ext_mb = _count_and_size(req_dir / "resumes" / "processed", "*.txt")
                for batch_dir in (req_dir / "resumes" / "batches").glob("*") if (req_dir / "resumes" / "batches").exists() else []:
                    xn, xm = _count_and_size(batch_dir / "extracted", "*.txt")
                    ext_n += xn; ext_mb += xm

                ass_n, ass_mb = _count_and_size(req_dir / "assessments" / "individual", "*.json")
                rep_n, rep_mb = _count_and_size(req_dir / "reports", "*.docx")
                fw_n, fw_mb = _count_and_size(req_dir / "framework", "*.*")

                stats["resumes_raw"]["count"] += raw_n
                stats["resumes_raw"]["size_mb"] = round(stats["resumes_raw"]["size_mb"] + raw_mb, 3)
                stats["resumes_extracted"]["count"] += ext_n
                stats["resumes_extracted"]["size_mb"] = round(stats["resumes_extracted"]["size_mb"] + ext_mb, 3)
                stats["assessments"]["count"] += ass_n
                stats["assessments"]["size_mb"] = round(stats["assessments"]["size_mb"] + ass_mb, 3)
                stats["reports"]["count"] += rep_n
                stats["reports"]["size_mb"] = round(stats["reports"]["size_mb"] + rep_mb, 3)
                stats["frameworks"]["count"] += fw_n
                stats["frameworks"]["size_mb"] = round(stats["frameworks"]["size_mb"] + fw_mb, 3)

                c_resumes_raw += raw_n
                c_resumes_ext += ext_n
                c_assessments += ass_n
                c_reports += rep_n
                client_total = sum(f.stat().st_size for f in req_dir.rglob("*") if f.is_file())
                c_size += client_total

        stats["requisitions"] += req_count
        stats["by_client"].append({
            "code": client_dir.name,
            "requisitions": req_count,
            "resumes_raw": c_resumes_raw,
            "resumes_extracted": c_resumes_ext,
            "assessments": c_assessments,
            "reports": c_reports,
            "size_mb": round(c_size / (1024 * 1024), 1),
        })
        stats["total_size_mb"] += c_size

    stats["total_size_mb"] = round(stats["total_size_mb"] / (1024 * 1024), 1)
    return stats


def _backup_page_context(request: Request, **extra) -> dict:
    """Build the common context dict for the backup page."""
    from web.auth.token_store import get_token

    db_size_mb = round(_DB_PATH.stat().st_size / (1024 * 1024), 2) if _DB_PATH.exists() else 0
    settings_size_kb = round(_SETTINGS_PATH.stat().st_size / 1024, 1) if _SETTINGS_PATH.exists() else 0
    clients_size_mb = _clients_dir_size_mb()
    settings = _load_settings()
    bk_cfg = settings.get("backup", {})
    lan_path = bk_cfg.get("lan_path", "")
    drive_folder_id = bk_cfg.get("drive_folder_id", "")
    drive_keep_n = bk_cfg.get("drive_keep_n", 3)

    user = getattr(request.state, "user", None)
    email = (user.get("email") or "") if user else ""
    has_drive_token = bool(get_token(email)) if email else False

    ctx = {
        "request": request,
        "user": user,
        "db_size_mb": db_size_mb,
        "settings_size_kb": settings_size_kb,
        "clients_size_mb": clients_size_mb,
        "quick_size_mb": round(db_size_mb + settings_size_kb / 1024, 2),
        "full_size_mb": round(db_size_mb + settings_size_kb / 1024 + clients_size_mb, 1),
        "lan_path": lan_path,
        "drive_folder_id": drive_folder_id,
        "drive_keep_n": drive_keep_n,
        "has_drive_token": has_drive_token,
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


def _zip_contents(zf: zipfile.ZipFile, backup_type: str) -> None:
    """Write backup contents into an open ZipFile object."""
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
        _zip_contents(zf, backup_type)
    buf.seek(0)
    return buf, filename


def _build_zip_to_file(backup_type: str) -> tuple[Path, str]:
    """Write a backup zip to a temp file on disk; return (path, filename).

    Avoids holding the entire zip in RAM — essential for full backups on
    memory-constrained hardware (Raspberry Pi).  Caller must delete the file.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"raaf_backup_{backup_type}_{ts}.zip"
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        _zip_contents(zf, backup_type)
    return tmp_path, filename


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
# Drive backup helpers
# ---------------------------------------------------------------------------

async def _get_drive_access_token(request: Request) -> tuple[str | None, str | None]:
    """
    Return (access_token, None) if a valid Drive token is available,
    or (None, error_message) if the user needs to re-authenticate.

    Automatically refreshes expired tokens using the stored refresh_token.
    """
    from web.auth.token_store import get_token, is_token_expired, store_token
    from web.auth.config import get_google_client_id, get_google_client_secret
    import httpx as _httpx

    user = getattr(request.state, "user", None)
    email = (user.get("email") or "") if user else ""
    if not email:
        return None, "Not logged in with a Google account."

    token_data = get_token(email)
    if not token_data:
        return None, (
            "No Google Drive token found. Please log out and log back in "
            "to grant Drive access."
        )

    if is_token_expired(token_data):
        if not token_data.get("refresh_token"):
            return None, (
                "Drive token expired and no refresh token available. "
                "Please log out and log back in."
            )
        async with _httpx.AsyncClient() as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": get_google_client_id(),
                "client_secret": get_google_client_secret(),
                "refresh_token": token_data["refresh_token"],
                "grant_type": "refresh_token",
            })
        if resp.status_code != 200:
            return None, "Failed to refresh Drive token. Please log out and log back in."
        new_token = resp.json()
        token_data["access_token"] = new_token["access_token"]
        token_data["expires_at"] = new_token.get("expires_in", 3600) + time.time()
        store_token(email, token_data)

    return token_data["access_token"], None


# ---------------------------------------------------------------------------
# Drive token diagnostic
# ---------------------------------------------------------------------------

@router.get("/backup/drive/test")
async def admin_backup_drive_test(request: Request, _admin=Depends(require_admin)):
    """Return the raw token info from Google's tokeninfo endpoint for diagnosis."""
    import httpx as _httpx
    access_token, token_error = await _get_drive_access_token(request)
    if token_error:
        return {"error": token_error}
    async with _httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/tokeninfo",
            params={"access_token": access_token},
            timeout=10,
        )
    return resp.json()


# ---------------------------------------------------------------------------
# Drive backup route
# ---------------------------------------------------------------------------

@router.post("/backup/drive")
async def admin_backup_drive(
    request: Request,
    _admin=Depends(require_admin),
    keep_n: int = Form(3),
):
    """
    Upload a quick backup to Google Drive.

    The app auto-creates (or reuses) a folder named 'RAAF Backups' in the
    user's Drive — no manual folder creation required. Old backups beyond
    keep_n are deleted automatically.
    """
    from web.services.google_drive import (
        get_or_create_backup_folder, upload_backup, list_drive_backups,
        delete_drive_file, DriveAPIError, DrivePermissionError, TokenExpiredError,
    )

    keep_n = max(1, min(keep_n, 10))

    # Get access token
    access_token, token_error = await _get_drive_access_token(request)
    if token_error:
        ctx = _backup_page_context(request, drive_error=token_error, saved_keep_n=keep_n)
        return templates.TemplateResponse("admin/backup.html", ctx)

    # Get or create the RAAF Backups folder
    try:
        folder_id = await get_or_create_backup_folder(access_token)
    except (DriveAPIError, DrivePermissionError, TokenExpiredError) as e:
        ctx = _backup_page_context(request, drive_error=str(e), saved_keep_n=keep_n)
        return templates.TemplateResponse("admin/backup.html", ctx)

    # Build the full backup zip to disk (avoids double in-memory copy on Pi)
    tmp_path, filename = await asyncio.to_thread(_build_zip_to_file, "full")
    try:
        data = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    # Upload
    try:
        await upload_backup(access_token, folder_id, filename, data)
    except (DriveAPIError, DrivePermissionError, TokenExpiredError) as e:
        ctx = _backup_page_context(request, drive_error=str(e), saved_keep_n=keep_n)
        return templates.TemplateResponse("admin/backup.html", ctx)

    # Prune: delete oldest backups beyond keep_n
    deleted = 0
    try:
        backups = await list_drive_backups(access_token, folder_id)
        for old in backups[keep_n:]:
            try:
                await delete_drive_file(access_token, old["id"])
                deleted += 1
            except DriveAPIError:
                pass
    except DriveAPIError:
        pass

    # Persist settings
    settings = _load_settings()
    bk = settings.setdefault("backup", {})
    bk["drive_folder_id"] = folder_id
    bk["drive_keep_n"] = keep_n
    _save_settings(settings)

    size_mb = round(len(data) / (1024 * 1024), 2)
    msg = f"Backed up to Drive: {filename} ({size_mb} MB)"
    if deleted:
        msg += f" — {deleted} old backup(s) deleted (keeping latest {keep_n})."

    ctx = _backup_page_context(request, drive_success=msg, saved_keep_n=keep_n)
    return templates.TemplateResponse("admin/backup.html", ctx)


# ---------------------------------------------------------------------------
# Drive restore routes
# ---------------------------------------------------------------------------

@router.get("/backup/drive/list")
async def admin_backup_drive_list(request: Request, _admin=Depends(require_admin)):
    """Return JSON list of RAAF backups in the configured Drive folder."""
    from web.services.google_drive import (
        parse_drive_folder_id, list_drive_backups, DriveAPIError,
    )

    settings = _load_settings()
    folder_id = settings.get("backup", {}).get("drive_folder_id", "")
    if not folder_id:
        return {"backups": [], "error": "No Drive folder configured."}

    access_token, token_error = await _get_drive_access_token(request)
    if token_error:
        return {"backups": [], "error": token_error}

    try:
        backups = await list_drive_backups(access_token, folder_id)
        return {"backups": backups, "error": None}
    except DriveAPIError as e:
        return {"backups": [], "error": str(e)}


@router.post("/backup/drive/restore/{file_id}")
async def admin_backup_drive_restore(
    request: Request,
    file_id: str,
    _admin=Depends(require_admin),
    restore_settings: bool = Form(False),
):
    """
    Restore from a Drive backup zip.

    Saves the current DB as data/raaf_pre_restore.db before overwriting.
    Optionally restores config/settings.yaml if restore_settings is True.
    """
    from web.services.google_drive import download_file_bytes, DriveAPIError

    access_token, token_error = await _get_drive_access_token(request)
    if token_error:
        ctx = _backup_page_context(request, drive_error=f"Restore failed: {token_error}")
        return templates.TemplateResponse("admin/backup.html", ctx)

    # Download the backup zip
    try:
        data = await download_file_bytes(access_token, file_id)
    except DriveAPIError as e:
        ctx = _backup_page_context(request, drive_error=f"Download failed: {e}")
        return templates.TemplateResponse("admin/backup.html", ctx)

    # Quiesce writes during restore
    _bstate.backup_in_progress = True
    restored_items = []
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            names = zf.namelist()

            # Restore DB
            if "raaf.db" in names:
                if _DB_PATH.exists():
                    pre_restore = _DB_PATH.parent / "raaf_pre_restore.db"
                    shutil.copy2(_DB_PATH, pre_restore)
                _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                _DB_PATH.write_bytes(zf.read("raaf.db"))
                restored_items.append("data/raaf.db")

            # Restore settings (optional)
            if restore_settings and "config/settings.yaml" in names:
                _SETTINGS_PATH.write_bytes(zf.read("config/settings.yaml"))
                restored_items.append("config/settings.yaml")

    except zipfile.BadZipFile:
        _bstate.backup_in_progress = False
        ctx = _backup_page_context(request, drive_error="Restore failed: invalid zip file.")
        return templates.TemplateResponse("admin/backup.html", ctx)
    except Exception as e:
        _bstate.backup_in_progress = False
        ctx = _backup_page_context(request, drive_error=f"Restore failed: {e}")
        return templates.TemplateResponse("admin/backup.html", ctx)
    finally:
        _bstate.backup_in_progress = False

    msg = f"Restored: {', '.join(restored_items)}. Pre-restore DB saved as raaf_pre_restore.db."
    if restore_settings:
        msg += " Restart the service for settings changes to take effect."
    ctx = _backup_page_context(request, drive_success=msg)
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
        "fs_stats": _collect_fs_stats(),
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
        "fs_stats": _collect_fs_stats(),
    })
