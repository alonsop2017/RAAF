"""
Google Drive API service using httpx.
Provides folder listing and file download without the heavy google-api-python-client.
"""

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class DriveAPIError(Exception):
    """General Drive API error."""
    pass


class TokenExpiredError(DriveAPIError):
    """The access token has expired and needs refreshing."""
    pass


class FolderNotFoundError(DriveAPIError):
    """The specified folder was not found or is inaccessible."""
    pass


class DrivePermissionError(DriveAPIError):
    """Insufficient permissions to access the Drive resource."""
    pass


# ---------------------------------------------------------------------------
# URL / ID parsing
# ---------------------------------------------------------------------------

def parse_drive_folder_id(url_or_id: str) -> str:
    """
    Extract a Google Drive folder ID from a URL or raw ID string.

    Supported formats:
        - https://drive.google.com/drive/folders/FOLDER_ID
        - https://drive.google.com/drive/folders/FOLDER_ID?usp=sharing
        - https://drive.google.com/drive/u/0/folders/FOLDER_ID
        - Raw folder ID string (alphanumeric + hyphens + underscores)
    """
    url_or_id = url_or_id.strip()

    # Match /folders/<id> in any Drive URL
    m = re.search(r'/folders/([A-Za-z0-9_-]+)', url_or_id)
    if m:
        return m.group(1)

    # Accept a raw folder ID (no slashes, reasonable length)
    if re.fullmatch(r'[A-Za-z0-9_-]{10,}', url_or_id):
        return url_or_id

    raise DriveAPIError(f"Could not parse a folder ID from: {url_or_id}")


# ---------------------------------------------------------------------------
# Filename → candidate name guessing
# ---------------------------------------------------------------------------

# Words to strip from filenames before guessing candidate names
_NOISE_WORDS = {
    "resume", "cv", "curriculum", "vitae", "cover", "letter",
    "updated", "final", "new", "copy", "draft",
    "information", "for", "about", "regarding", "profile",
}

# Pattern for 4-digit years
_YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')

# CamelCase splitter
_CAMEL_RE = re.compile(r'(?<=[a-z])(?=[A-Z])')


def guess_candidate_name(filename: str) -> str:
    """
    Best-guess a `lastname_firstname` string from a resume filename.

    Strategy:
    1. Strip extension
    2. Split on camelCase boundaries
    3. Replace separators (-, _, .) with spaces
    4. Remove noise words (resume, cv, years, etc.)
    5. Assume last remaining token is the surname
    """
    stem = Path(filename).stem

    # Split camelCase
    stem = _CAMEL_RE.sub(' ', stem)

    # Replace separators with spaces
    stem = re.sub(r'[-_.]', ' ', stem)

    # Remove parenthesised content
    stem = re.sub(r'\([^)]*\)', '', stem)

    # Remove years
    stem = _YEAR_RE.sub('', stem)

    # Remove digits-only tokens and noise words
    tokens = [
        t for t in stem.split()
        if t and not t.isdigit() and t.lower() not in _NOISE_WORDS
    ]

    if not tokens:
        # Fall back to sanitised stem
        fallback = re.sub(r'[^a-zA-Z]', '_', Path(filename).stem).strip('_').lower()
        return fallback or "unknown"

    if len(tokens) == 1:
        return tokens[0].lower()

    # Assume last token is surname
    last_name = tokens[-1].lower()
    first_parts = '_'.join(t.lower() for t in tokens[:-1])

    # Clean non-alpha chars
    last_name = re.sub(r'[^a-z]', '', last_name)
    first_parts = re.sub(r'[^a-z_]', '', first_parts)

    return f"{last_name}_{first_parts}"


# ---------------------------------------------------------------------------
# Drive API calls
# ---------------------------------------------------------------------------

async def list_folder_files(
    access_token: str,
    folder_id: str,
) -> list[dict]:
    """
    List PDF and DOCX files in a Google Drive folder.

    Returns a list of dicts with keys:
        id, name, guessed_name, extension, size_kb
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    query = (
        f"'{folder_id}' in parents and trashed = false "
        f"and (mimeType='application/pdf' "
        f"or mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document')"
    )
    params = {
        "q": query,
        "fields": "files(id,name,mimeType,size)",
        "pageSize": 200,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DRIVE_API_BASE}/files",
            headers=headers,
            params=params,
            timeout=30,
        )

    if resp.status_code == 401:
        raise TokenExpiredError("Access token expired")
    if resp.status_code == 404:
        raise FolderNotFoundError(f"Folder {folder_id} not found")
    if resp.status_code != 200:
        raise DriveAPIError(f"Drive API error {resp.status_code}: {resp.text}")

    data = resp.json()
    files = []
    for f in data.get("files", []):
        ext = ".pdf" if f["mimeType"] == "application/pdf" else ".docx"
        size_bytes = int(f.get("size", 0))
        files.append({
            "id": f["id"],
            "name": f["name"],
            "guessed_name": guess_candidate_name(f["name"]),
            "extension": ext,
            "size_kb": round(size_bytes / 1024, 1),
        })

    # Sort alphabetically by guessed name
    files.sort(key=lambda x: x["guessed_name"])
    return files


async def download_file(
    access_token: str,
    file_id: str,
    destination: Path,
) -> Path:
    """
    Download a file from Google Drive to a local path.

    Args:
        access_token: Valid OAuth access token.
        file_id: Drive file ID.
        destination: Local file path to write to.

    Returns:
        The destination Path.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{DRIVE_API_BASE}/files/{file_id}?alt=media"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=60, follow_redirects=True)

    if resp.status_code == 401:
        raise TokenExpiredError("Access token expired")
    if resp.status_code != 200:
        raise DriveAPIError(f"Download failed ({resp.status_code}): {resp.text}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "wb") as f:
        f.write(resp.content)

    return destination


# ---------------------------------------------------------------------------
# Backup helpers
# ---------------------------------------------------------------------------

_BACKUP_FOLDER_NAME = "RAAF Backups"


async def get_or_create_backup_folder(access_token: str) -> str:
    """Return the ID of the 'RAAF Backups' folder, creating it if absent."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        # Search for existing folder
        resp = await client.get(
            f"{DRIVE_API_BASE}/files",
            headers=headers,
            params={
                "q": f"name='{_BACKUP_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                "fields": "files(id,name)",
                "pageSize": 1,
            },
        )
        if resp.status_code == 401:
            raise TokenExpiredError("Access token expired")
        if resp.status_code == 403:
            raise DrivePermissionError("Insufficient Drive permissions")
        if resp.status_code != 200:
            raise DriveAPIError(f"Drive API error {resp.status_code}: {resp.text}")

        files = resp.json().get("files", [])
        if files:
            return files[0]["id"]

        # Create the folder
        resp = await client.post(
            f"{DRIVE_API_BASE}/files",
            headers=headers,
            json={"name": _BACKUP_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
        )
        if resp.status_code not in (200, 201):
            raise DriveAPIError(f"Failed to create backup folder: {resp.text}")
        return resp.json()["id"]


async def upload_backup(access_token: str, folder_id: str, filename: str,
                        data: "bytes | None" = None, file_path: "Path | None" = None) -> str:
    """Upload a backup zip to Drive using a resumable upload.

    Pass either `data` (bytes) or `file_path` (Path, streamed in chunks to avoid OOM).
    """
    import json as _json

    headers = {"Authorization": f"Bearer {access_token}"}
    metadata = {"name": filename, "parents": [folder_id]}

    if file_path is not None:
        file_size = file_path.stat().st_size
    elif data is not None:
        file_size = len(data)
    else:
        raise ValueError("Either data or file_path must be provided")

    # Step 1: Initiate resumable upload session
    async with httpx.AsyncClient(timeout=60) as client:
        init_resp = await client.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            headers={
                **headers,
                "Content-Type": "application/json",
                "X-Upload-Content-Type": "application/zip",
                "X-Upload-Content-Length": str(file_size),
            },
            content=_json.dumps(metadata).encode(),
        )
    if init_resp.status_code == 401:
        raise TokenExpiredError("Access token expired")
    if init_resp.status_code == 403:
        raise DrivePermissionError("Insufficient Drive permissions")
    if init_resp.status_code != 200:
        raise DriveAPIError(f"Resumable upload init failed ({init_resp.status_code}): {init_resp.text}")

    upload_url = init_resp.headers.get("Location")
    if not upload_url:
        raise DriveAPIError("No upload URL returned from Drive")

    # Step 2: Upload — stream file in 8 MB chunks so we never hold the full zip in RAM
    CHUNK = 8 * 1024 * 1024

    async def _iter_chunks():
        if file_path is not None:
            with open(file_path, "rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    yield chunk
        else:
            for i in range(0, len(data), CHUNK):
                yield data[i:i + CHUNK]

    async with httpx.AsyncClient(timeout=600) as client:
        upload_resp = await client.put(
            upload_url,
            content=_iter_chunks(),
            headers={"Content-Type": "application/zip", "Content-Length": str(file_size)},
        )

    if upload_resp.status_code not in (200, 201):
        raise DriveAPIError(f"Upload failed ({upload_resp.status_code}): {upload_resp.text}")
    return upload_resp.json()["id"]


async def list_drive_backups(access_token: str, folder_id: str) -> list[dict]:
    """List backup zips in a Drive folder, newest first."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{DRIVE_API_BASE}/files",
            headers=headers,
            params={
                "q": f"'{folder_id}' in parents and name contains 'raaf_backup' and trashed=false",
                "fields": "files(id,name,createdTime,size)",
                "orderBy": "createdTime desc",
                "pageSize": 50,
            },
        )
    if resp.status_code == 401:
        raise TokenExpiredError("Access token expired")
    if resp.status_code != 200:
        raise DriveAPIError(f"Drive API error {resp.status_code}: {resp.text}")
    return resp.json().get("files", [])


async def delete_drive_file(access_token: str, file_id: str) -> None:
    """Permanently delete a Drive file."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(f"{DRIVE_API_BASE}/files/{file_id}", headers=headers)
    if resp.status_code == 401:
        raise TokenExpiredError("Access token expired")
    if resp.status_code not in (200, 204):
        raise DriveAPIError(f"Delete failed ({resp.status_code}): {resp.text}")
