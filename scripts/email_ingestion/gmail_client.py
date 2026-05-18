#!/usr/bin/env python3
"""
Gmail client for the email ingestion pipeline.
Uses the web app's encrypted token store for headless / cron use.
Requires gmail.modify scope (superset of gmail.readonly).
"""

import base64
import json
import time
from pathlib import Path
from typing import Optional

import httpx

PROJECT_ROOT = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from web.auth.token_store import get_token, store_token, is_token_expired
from web.auth.config import get_google_client_id, get_google_client_secret

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"

SENDER_EMAIL = "alonso.perez@archtektconsultinginc.com"


def _refresh(token_data: dict) -> Optional[str]:
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        return None
    resp = httpx.post(TOKEN_REFRESH_URL, data={
        "client_id": get_google_client_id(),
        "client_secret": get_google_client_secret(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    if resp.status_code != 200:
        return None
    data = resp.json()
    token_data["access_token"] = data["access_token"]
    token_data["expires_at"] = time.time() + data.get("expires_in", 3600)
    store_token(SENDER_EMAIL, token_data)
    return data["access_token"]


def _get_token() -> str:
    token_data = get_token(SENDER_EMAIL)
    if not token_data:
        raise RuntimeError(
            "No OAuth token found for alonso.perez@archtektconsultinginc.com. "
            "Log in to RAAF at raaf.peoplefindinc.com to authorize Gmail access."
        )
    if is_token_expired(token_data):
        access_token = _refresh(token_data)
        if not access_token:
            raise RuntimeError("OAuth token expired and could not be refreshed. Please re-login to RAAF.")
        return access_token
    return token_data["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


def search_messages(query: str, max_results: int = 100) -> list[dict]:
    """Return list of {id, threadId} matching a Gmail search query."""
    results = []
    page_token = None
    while True:
        params = {"q": query, "maxResults": min(max_results - len(results), 100)}
        if page_token:
            params["pageToken"] = page_token
        resp = httpx.get(f"{GMAIL_BASE}/messages", headers=_headers(), params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("messages", []))
        page_token = data.get("nextPageToken")
        if not page_token or len(results) >= max_results:
            break
    return results


def get_message(msg_id: str, fmt: str = "full") -> dict:
    resp = httpx.get(f"{GMAIL_BASE}/messages/{msg_id}", headers=_headers(),
                     params={"format": fmt}, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_attachment(msg_id: str, attachment_id: str) -> bytes:
    resp = httpx.get(f"{GMAIL_BASE}/messages/{msg_id}/attachments/{attachment_id}",
                     headers=_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", "")
    return base64.urlsafe_b64decode(data + "==")


def add_label(msg_id: str, label_id: str) -> None:
    httpx.post(
        f"{GMAIL_BASE}/messages/{msg_id}/modify",
        headers=_headers(),
        json={"addLabelIds": [label_id]},
        timeout=10,
    ).raise_for_status()


def get_or_create_label(name: str) -> str:
    """Return the label ID for `name`, creating it if it doesn't exist."""
    resp = httpx.get(f"{GMAIL_BASE}/labels", headers=_headers(), timeout=10)
    resp.raise_for_status()
    for label in resp.json().get("labels", []):
        if label["name"].lower() == name.lower():
            return label["id"]
    resp = httpx.post(f"{GMAIL_BASE}/labels", headers=_headers(),
                      json={"name": name, "labelListVisibility": "labelShow",
                            "messageListVisibility": "show"}, timeout=10)
    resp.raise_for_status()
    return resp.json()["id"]


def extract_parts(payload: dict) -> tuple[str, list[dict]]:
    """Recursively extract plain-text body and attachment metadata from a message payload."""
    body_text = ""
    attachments = []

    def _walk(part: dict):
        nonlocal body_text
        mime = part.get("mimeType", "")
        body = part.get("body", {})

        if mime == "text/plain" and not body_text:
            data = body.get("data", "")
            if data:
                body_text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

        # Attachment
        if body.get("attachmentId") and part.get("filename"):
            fname = part["filename"]
            ext = Path(fname).suffix.lower()
            if ext in (".pdf", ".doc", ".docx"):
                attachments.append({
                    "filename": fname,
                    "attachment_id": body["attachmentId"],
                    "mime_type": mime,
                    "size": body.get("size", 0),
                })

        for sub in part.get("parts", []):
            _walk(sub)

    _walk(payload)
    return body_text, attachments


def send_email(to: str, subject: str, body: str, from_name: str = "RAAF Ingestion") -> None:
    """Send a plain-text email from the RAAF account."""
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = f"{from_name} <{SENDER_EMAIL}>"
    msg["To"] = to
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    httpx.post(f"{GMAIL_BASE}/messages/send", headers=_headers(),
               json={"raw": raw}, timeout=15).raise_for_status()
