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
