"""
Server-side encrypted file store for OAuth tokens.
Stores tokens keyed by user email, encrypted with Fernet using SESSION_SECRET_KEY.
"""

import json
import base64
import hashlib
import time
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from .config import get_session_secret_key

TOKEN_STORE_PATH = Path(__file__).parent.parent.parent / "config" / ".token_store.json"


def _get_fernet() -> Fernet:
    """Derive a Fernet key from SESSION_SECRET_KEY."""
    secret = get_session_secret_key() or "dev-secret-change-in-production"
    # Derive a 32-byte key via SHA-256, then base64-encode for Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _read_store() -> dict:
    """Read the encrypted token store from disk."""
    if not TOKEN_STORE_PATH.exists():
        return {}
    try:
        with open(TOKEN_STORE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _write_store(store: dict) -> None:
    """Write the token store to disk."""
    TOKEN_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_STORE_PATH, "w") as f:
        json.dump(store, f)


def store_token(email: str, token_data: dict) -> None:
    """
    Encrypt and store an OAuth token for a user.

    Args:
        email: User email (key)
        token_data: OAuth token dict (access_token, refresh_token, expires_at, etc.)
    """
    fernet = _get_fernet()
    payload = json.dumps(token_data).encode()
    encrypted = fernet.encrypt(payload).decode()

    store = _read_store()
    store[email] = encrypted
    _write_store(store)


def get_token(email: str) -> Optional[dict]:
    """
    Retrieve and decrypt an OAuth token for a user.

    Args:
        email: User email (key)

    Returns:
        Decrypted token dict, or None if not found / decryption fails.
    """
    store = _read_store()
    encrypted = store.get(email)
    if not encrypted:
        return None

    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted.encode())
        return json.loads(decrypted)
    except Exception:
        return None


def remove_token(email: str) -> None:
    """Remove the stored token for a user."""
    store = _read_store()
    store.pop(email, None)
    _write_store(store)


def is_token_expired(token_data: dict) -> bool:
    """
    Check if an OAuth token is expired (with 60-second buffer).

    Args:
        token_data: Token dict with 'expires_at' timestamp.

    Returns:
        True if expired or missing expiry info.
    """
    expires_at = token_data.get("expires_at")
    if not expires_at:
        return True
    return time.time() > (expires_at - 60)
