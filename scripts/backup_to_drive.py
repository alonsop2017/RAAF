#!/usr/bin/env python3
"""
Cron-compatible Drive backup script.
Reads admin token from the token store (populated when an admin logs in via the web UI)
and uploads a full backup zip to Google Drive.

Usage:
    python scripts/backup_to_drive.py [--keep N]
"""
import asyncio
import sys
import argparse
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


async def main(keep_n: int = 3) -> int:
    from web.auth.token_store import get_token, is_token_expired, store_token
    from web.routers.admin import _build_zip_to_file
    from web.services.google_drive import (
        get_or_create_backup_folder, upload_backup,
        list_drive_backups, delete_drive_file,
        DriveAPIError, DrivePermissionError, TokenExpiredError,
    )
    import httpx
    import yaml

    settings_path = Path("/app/config/settings.yaml")
    settings = yaml.safe_load(settings_path.read_text()) if settings_path.exists() else {}

    # Find an admin email that has a stored Drive token
    admin_emails = settings.get("auth", {}).get("admin_emails", [])
    if isinstance(admin_emails, str):
        admin_emails = [admin_emails]

    token_data = None
    used_email = None
    for email in admin_emails:
        t = get_token(email)
        if t:
            token_data = t
            used_email = email
            break

    if not token_data:
        log("ERROR: No Drive token found for any admin. Log in via the web UI first.")
        return 1

    log(f"Using token for: {used_email}")

    # Refresh token if expired
    if is_token_expired(token_data):
        if not token_data.get("refresh_token"):
            log("ERROR: Token expired and no refresh token available. Re-login via the web UI.")
            return 1
        log("Token expired — refreshing...")
        auth_cfg = settings.get("auth", {}).get("google", {})
        import os
        client_id = auth_cfg.get("client_id") or os.environ.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        async with httpx.AsyncClient() as http:
            resp = await http.post("https://oauth2.googleapis.com/token", data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": token_data["refresh_token"],
                "grant_type": "refresh_token",
            })
        if resp.status_code != 200:
            log(f"ERROR: Token refresh failed: {resp.text}")
            return 1
        new_token = resp.json()
        token_data["access_token"] = new_token["access_token"]
        token_data["expires_at"] = new_token.get("expires_in", 3600) + time.time()
        store_token(used_email, token_data)
        log("Token refreshed.")

    access_token = token_data["access_token"]

    # Get/create the RAAF Backups folder in Drive
    try:
        folder_id = await get_or_create_backup_folder(access_token)
    except (DriveAPIError, DrivePermissionError, TokenExpiredError) as e:
        log(f"ERROR: Could not access Drive folder: {e}")
        return 1

    # Build the backup zip
    log("Building backup zip...")
    tmp_path, filename = await asyncio.to_thread(_build_zip_to_file, "full")
    try:
        size_mb = tmp_path.stat().st_size / 1_048_576
        log(f"Zip built: {filename} ({size_mb:.1f} MB)")
        data = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    # Upload
    log(f"Uploading to Drive folder {folder_id}...")
    try:
        await upload_backup(access_token, folder_id, filename, data)
    except (DriveAPIError, DrivePermissionError, TokenExpiredError) as e:
        log(f"ERROR: Upload failed: {e}")
        return 1
    log(f"Upload complete: {filename}")

    # Prune old backups
    try:
        backups = await list_drive_backups(access_token, folder_id)
        for old in backups[keep_n:]:
            try:
                await delete_drive_file(access_token, old["id"])
                log(f"Pruned old backup: {old.get('name', old['id'])}")
            except DriveAPIError:
                pass
    except DriveAPIError:
        pass

    # Persist folder_id to settings so the admin page shows it
    bk = settings.setdefault("backup", {})
    bk["drive_folder_id"] = folder_id
    bk["drive_keep_n"] = keep_n
    settings_path.write_text(yaml.dump(settings, default_flow_style=False, allow_unicode=True, sort_keys=False))

    log("Drive backup completed successfully.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=int, default=3, help="Number of backups to keep on Drive")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(keep_n=args.keep)))
