#!/usr/bin/env python3
"""
Email Resume Ingestion — daily cron job.

Scans alonso.perez@archtektconsultinginc.com for emails with resume attachments
from known recruitment sources (peoplefindinc.com, indeed.com) or applications
to active RAAF requisitions. Matches each resume to the best active requisition,
stores it in Direct_Submissions/, adds the candidate as pending in the DB,
and sends a daily digest summary email.

Cron: 6:00 AM UTC daily.
"""

import hashlib
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from scripts.email_ingestion.gmail_client import (
    search_messages, get_message, get_attachment, get_or_create_label,
    add_label, extract_parts, send_email,
)
from scripts.email_ingestion.resume_matcher import match_resume_to_requisition

# ── Paths ────────────────────────────────────────────────────────────────────
DIRECT_SUBMISSIONS_ROOT = PROJECT_ROOT / "Direct_Submissions"
STATE_FILE = PROJECT_ROOT / "config" / "email_ingestion_state.json"
LOG_FILE   = PROJECT_ROOT / "logs" / "email_ingestion.log"

PROCESSED_LABEL = "raaf-processed"
DIGEST_RECIPIENT = "alonso.perez@archtektconsultinginc.com"

# Known recruitment senders — emails from these domains are always scanned
TRUSTED_SENDERS = ["peoplefindinc.com", "indeed.com", "noreply@indeed.com"]


# ── State ────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"processed_ids": [], "last_run": None}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Logging ──────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Helpers ──────────────────────────────────────────────────────────────────

def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _normalize_name(filename: str) -> str:
    """Turn 'John Smith Resume.pdf' → 'smith_john' best-effort."""
    stem = Path(filename).stem
    stem = re.sub(r"[-_\.\s]+", " ", stem)
    stem = re.sub(r"(?i)\b(resume|cv|curriculum.?vitae|application)\b", "", stem).strip()
    parts = stem.split()
    if len(parts) >= 2:
        return f"{parts[-1]}_{parts[0]}".lower()
    return stem.lower().replace(" ", "_") or "candidate_unknown"


def _extract_text(file_bytes: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            from scripts.utils.pdf_reader import extract_text
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                text = extract_text(Path(tmp_path))
            finally:
                os.unlink(tmp_path)
            return text or ""
        elif ext in (".doc", ".docx"):
            from scripts.utils.docx_reader import extract_text
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                text = extract_text(Path(tmp_path))
            finally:
                os.unlink(tmp_path)
            return text or ""
    except Exception as e:
        _log(f"  WARN: text extraction failed for {filename}: {e}")
    return ""


def _store_resume(
    file_bytes: bytes,
    filename: str,
    extracted_text: str,
    req: Optional[dict],
    name_normalized: str,
    confidence: float,
) -> tuple[Path, Path]:
    """
    Write original + extracted text to Direct_Submissions/ and return (orig_path, txt_path).
    Also copies into the requisition's batch folder for standard RAAF processing.
    """
    today = datetime.now().strftime("%Y%m%d")
    ext = Path(filename).suffix.lower()

    if req:
        folder = DIRECT_SUBMISSIONS_ROOT / req["req_id"]
    else:
        folder = DIRECT_SUBMISSIONS_ROOT / "unmatched"

    folder.mkdir(parents=True, exist_ok=True)
    orig_path = folder / f"{name_normalized}_resume{ext}"
    txt_path  = folder / f"{name_normalized}_resume.txt"

    # Avoid overwriting — append hash suffix if collision
    if orig_path.exists():
        h = _file_hash(file_bytes)
        orig_path = folder / f"{name_normalized}_{h}_resume{ext}"
        txt_path  = folder / f"{name_normalized}_{h}_resume.txt"

    orig_path.write_bytes(file_bytes)
    txt_path.write_text(extracted_text, encoding="utf-8")

    # Also copy into standard batch structure so RAAF UI picks it up
    if req:
        _store_in_batch(file_bytes, extracted_text, req, name_normalized, ext, today)

    return orig_path, txt_path


def _store_in_batch(
    file_bytes: bytes,
    extracted_text: str,
    req: dict,
    name_normalized: str,
    ext: str,
    today: str,
) -> None:
    from scripts.utils.client_utils import get_requisition_root
    try:
        req_root = get_requisition_root(req["client_code"], req["req_id"])
        batch_base = req_root / "resumes" / "batches"

        # Find or create today's direct batch
        existing = sorted(batch_base.glob(f"direct_{today}_*"))
        if existing:
            batch_dir = existing[-1]
        else:
            n = len(list(batch_base.glob(f"direct_{today}_*"))) + 1
            batch_dir = batch_base / f"direct_{today}_{n}"

        (batch_dir / "originals").mkdir(parents=True, exist_ok=True)
        (batch_dir / "extracted").mkdir(parents=True, exist_ok=True)

        (batch_dir / "originals" / f"{name_normalized}{ext}").write_bytes(file_bytes)
        (batch_dir / "extracted" / f"{name_normalized}_resume.txt").write_text(
            extracted_text, encoding="utf-8"
        )
    except Exception as e:
        _log(f"  WARN: could not copy to batch folder: {e}")


def _add_candidate_to_db(
    req: dict,
    name_normalized: str,
    candidate_name: str,
    txt_path: Path,
    sender_email: str,
    confidence: float,
) -> None:
    try:
        from scripts.utils.database import get_db, _use_database
        if not _use_database():
            return
        db = get_db()
        today = datetime.now().strftime("%Y%m%d")
        db.upsert_candidate({
            "req_id": req["req_id"],
            "name": candidate_name,
            "name_normalized": name_normalized,
            "source_platform": "Email Direct",
            "batch": f"direct_{today}_1",
            "resume_extracted_path": str(txt_path),
            "status": "pending",
            "pipeline_status": "New",
        })
    except Exception as e:
        _log(f"  WARN: DB candidate upsert failed: {e}")


# ── Gmail query builder ───────────────────────────────────────────────────────

def _build_query(processed_ids: list[str]) -> str:
    """
    Build a Gmail search query that finds candidate emails not yet processed.
    Targets: known senders OR any email with resume-like subject to our address.
    """
    sender_clause = " OR ".join(f"from:{s}" for s in TRUSTED_SENDERS)
    # Broad application subject keywords
    subject_clause = (
        'subject:(resume OR "job application" OR applying OR application OR CV OR candidate)'
    )
    query = (
        f"to:alonso.perez@archtektconsultinginc.com "
        f"has:attachment "
        f"({sender_clause} OR {subject_clause}) "
        f"-label:{PROCESSED_LABEL}"
    )
    return query


# ── Digest email ─────────────────────────────────────────────────────────────

def _send_digest(ingested: list[dict], unmatched: list[dict], errors: list[str]) -> None:
    today_str = datetime.now().strftime("%B %d, %Y")
    lines = [f"RAAF Email Ingestion Report — {today_str}", "=" * 50, ""]

    if ingested:
        lines.append(f"✓ {len(ingested)} resume(s) ingested and staged for assessment:")
        for item in ingested:
            lines.append(
                f"  • {item['candidate']} → {item['req_id']} ({item['req_title']}) "
                f"[{int(item['confidence']*100)}% match confidence]"
            )
    else:
        lines.append("No new resumes matched to active requisitions.")

    if unmatched:
        lines.append("")
        lines.append(f"⚠ {len(unmatched)} resume(s) could not be matched — stored in Direct_Submissions/unmatched/:")
        for item in unmatched:
            lines.append(f"  • {item['filename']} (from {item['sender']}) — {item['reason']}")
        lines.append("")
        lines.append("Action required: review unmatched resumes and assign manually in RAAF.")

    if errors:
        lines.append("")
        lines.append(f"✗ {len(errors)} error(s) during this run:")
        for e in errors:
            lines.append(f"  • {e}")

    if not ingested and not unmatched and not errors:
        lines.append("")
        lines.append("No new resume emails found in this run.")

    lines += ["", "—", "RAAF Automated Ingestion | raaf.peoplefindinc.com"]
    body = "\n".join(lines)

    total = len(ingested) + len(unmatched)
    subject = f"RAAF Ingestion: {total} new resume(s) — {today_str}" if total else f"RAAF Ingestion: no new resumes — {today_str}"

    try:
        send_email(DIGEST_RECIPIENT, subject, body, from_name="RAAF Ingestion")
        _log(f"Digest sent to {DIGEST_RECIPIENT}")
    except Exception as e:
        _log(f"WARN: could not send digest: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    _log("=" * 60)
    _log("Email ingestion run started")

    state = _load_state()
    processed_ids: list[str] = state.get("processed_ids", [])

    ingested: list[dict] = []
    unmatched: list[dict] = []
    errors: list[str] = []

    try:
        label_id = get_or_create_label(PROCESSED_LABEL)
    except Exception as e:
        _log(f"ERROR: cannot connect to Gmail — {e}")
        errors.append(f"Gmail connection failed: {e}")
        _send_digest(ingested, unmatched, errors)
        return

    query = _build_query(processed_ids)
    _log(f"Gmail query: {query}")

    try:
        messages = search_messages(query, max_results=200)
    except Exception as e:
        _log(f"ERROR: Gmail search failed: {e}")
        errors.append(f"Gmail search failed: {e}")
        _send_digest(ingested, unmatched, errors)
        return

    _log(f"Found {len(messages)} message(s) to process")

    for msg_ref in messages:
        msg_id = msg_ref["id"]
        if msg_id in processed_ids:
            continue

        try:
            msg = get_message(msg_id)
            payload = msg.get("payload", {})
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

            subject = headers.get("subject", "(no subject)")
            sender  = headers.get("from", "")
            date    = headers.get("date", "")

            body_text, attachments = extract_parts(payload)

            if not attachments:
                # Mark and skip — no resume attachment
                add_label(msg_id, label_id)
                processed_ids.append(msg_id)
                continue

            _log(f"Processing message from {sender!r}: {subject!r} ({len(attachments)} attachment(s))")

            for att in attachments:
                filename = att["filename"]
                try:
                    file_bytes = get_attachment(msg_id, att["attachment_id"])
                except Exception as e:
                    err = f"Download failed for {filename}: {e}"
                    _log(f"  ERROR: {err}")
                    errors.append(err)
                    continue

                extracted = _extract_text(file_bytes, filename)
                name_norm = _normalize_name(filename)

                # Derive candidate display name from normalized key
                parts = name_norm.split("_")
                candidate_name = " ".join(p.title() for p in parts) if parts else filename

                _log(f"  Attachment: {filename} ({len(file_bytes)//1024}KB, {len(extracted)} chars extracted)")

                req, confidence, reasoning = match_resume_to_requisition(
                    resume_text=extracted,
                    email_subject=subject,
                    email_body=body_text,
                    sender=sender,
                    filename=filename,
                )

                if req:
                    _log(f"  Matched → {req['req_id']} ({req['title']}) — {int(confidence*100)}% — {reasoning}")
                    orig_path, txt_path = _store_resume(
                        file_bytes, filename, extracted, req, name_norm, confidence
                    )
                    _add_candidate_to_db(req, name_norm, candidate_name, txt_path, sender, confidence)
                    ingested.append({
                        "candidate": candidate_name,
                        "req_id": req["req_id"],
                        "req_title": req["title"],
                        "confidence": confidence,
                        "reasoning": reasoning,
                    })
                else:
                    _log(f"  Unmatched ({int(confidence*100)}%) — {reasoning}")
                    _store_resume(file_bytes, filename, extracted, None, name_norm, confidence)
                    unmatched.append({
                        "filename": filename,
                        "sender": sender,
                        "reason": reasoning,
                    })

            # Mark email as processed
            add_label(msg_id, label_id)
            processed_ids.append(msg_id)

        except Exception as e:
            err = f"Error processing message {msg_id}: {e}"
            _log(f"  ERROR: {err}")
            _log(traceback.format_exc())
            errors.append(err)

    # Persist state (keep last 2000 processed IDs to bound file size)
    state["processed_ids"] = processed_ids[-2000:]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    _log(f"Run complete — {len(ingested)} ingested, {len(unmatched)} unmatched, {len(errors)} errors")
    _send_digest(ingested, unmatched, errors)


if __name__ == "__main__":
    run()
