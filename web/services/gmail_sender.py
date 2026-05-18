"""
Gmail send service for RAAF.
Uses the stored per-user OAuth token to send emails via the Gmail API.
"""

import base64
import re
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import httpx

from web.auth.token_store import get_token, store_token, is_token_expired
from web.auth.config import get_google_client_id, get_google_client_secret

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"

REQUIRED_SCOPE = "https://www.googleapis.com/auth/gmail.send"


async def _refresh_access_token(refresh_token: str) -> Optional[dict]:
    """Exchange a refresh token for a fresh access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(TOKEN_REFRESH_URL, data={
            "client_id": get_google_client_id(),
            "client_secret": get_google_client_secret(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
    if resp.status_code != 200:
        return None
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 3600),
    }


async def _get_valid_token(user_email: str) -> Optional[str]:
    """Return a valid access token for user_email, refreshing if needed."""
    token_data = get_token(user_email)
    if not token_data:
        return None

    if is_token_expired(token_data):
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            return None
        refreshed = await _refresh_access_token(refresh_token)
        if not refreshed:
            return None
        token_data.update(refreshed)
        store_token(user_email, token_data)

    return token_data.get("access_token")


async def check_gmail_scope(user_email: str) -> bool:
    """
    Return True if the stored token can reach the Gmail API.
    Makes a lightweight profile call; returns False on 401/403.
    """
    access_token = await _get_valid_token(user_email)
    if not access_token:
        return False
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GMAIL_PROFILE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=8,
        )
    return resp.status_code == 200


async def send_email(
    user_email: str,
    to_email: str,
    subject: str,
    body: str,
    from_name: Optional[str] = None,
) -> dict:
    """
    Send an email via the Gmail API on behalf of user_email.

    Returns:
        {"ok": True, "message_id": "..."}           on success
        {"ok": False, "error": "...", "reauth": bool}  on failure
    """
    access_token = await _get_valid_token(user_email)
    if not access_token:
        return {"ok": False, "error": "No valid OAuth token. Please re-authenticate.", "reauth": True}

    # Build RFC 2822 message
    msg = MIMEMultipart("alternative")
    from_header = f"{from_name} <{user_email}>" if from_name else user_email
    msg["From"] = from_header
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GMAIL_SEND_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
            timeout=15,
        )

    if resp.status_code == 200:
        return {"ok": True, "message_id": resp.json().get("id", "")}

    if resp.status_code in (401, 403):
        error_data = resp.json()
        error_msg = error_data.get("error", {}).get("message", "Insufficient permissions")
        return {"ok": False, "error": error_msg, "reauth": True}

    return {"ok": False, "error": f"Gmail API error {resp.status_code}: {resp.text}", "reauth": False}


def parse_subject_from_draft(draft_text: str) -> str:
    """Extract the SUBJECT line from a generated invitation draft."""
    match = re.search(r"^SUBJECT:\s*(.+)$", draft_text, re.MULTILINE)
    return match.group(1).strip() if match else "Interview Opportunity"


def parse_body_from_draft(draft_text: str) -> str:
    """
    Extract the sendable email body from a draft (everything after the
    header block, starting from 'Dear ...').
    """
    # The body starts after the '---' separator that follows SUBJECT:
    parts = re.split(r"\n---\n", draft_text, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else draft_text.strip()
