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

# Markers that indicate a body contains a resume/candidate profile rather than
# a plain conversational email.  Two or more must be present.
_RESUME_BODY_MARKERS = [
    "work history", "work experience", "employment history",
    "professional experience", "professional summary",
    "education", "certifications", "skills",
    "job history", "career history",
]

# Emails whose subjects indicate internal job-posting / ad-distribution messages
# (not candidate applications) — skip entirely rather than trying to match.
SKIP_SUBJECT_KEYWORDS = [
    "all ads", "listings on pcr", "job descriptions - ads on indeed",
    "efrat us - job descriptions", "efrat canada - job descriptions",
    "ads and notes", "efrat world",
    "all jobs - ", "jobs - april", "jobs - may", "jobs - june",
    "jobs - july", "jobs - august", "jobs - september",
]


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


def _looks_like_resume(text: str) -> bool:
    """Return True if the text body appears to be a resume or candidate profile."""
    lower = text.lower()
    hits = sum(1 for marker in _RESUME_BODY_MARKERS if marker in lower)
    return hits >= 2 and len(text.strip()) > 300


def _extract_name_from_body(body: str, subject: str) -> str:
    """
    Best-effort candidate name extraction from an email body or subject.

    Tries:
      1. ALL-CAPS name block near the top of the body (PCR/Indeed profile style)
      2. Title-case name-looking line near the top
      3. Last token(s) after a dash in the subject ("Reliability Engineer - Quentin")
    """
    name_re = re.compile(r"^[A-ZÀ-Ža-z][A-ZÀ-Ža-z'\-]+(?:\s+[A-ZÀ-Ža-z'\-]+){1,3}$")
    skip_words = {
        "resume", "profile", "insights", "summary", "experience", "education",
        "skills", "certifications", "contact", "history", "recently", "active",
    }
    lines = body.strip().split("\n")
    # Pass 1 — ALL-CAPS name line (e.g. "QUENTIN FOSTER")
    for line in lines[:30]:
        line = line.strip()
        if not line or len(line) > 50:
            continue
        if line.upper() == line and len(line.split()) in (2, 3):
            words = line.split()
            if all(w.isalpha() and w.lower() not in skip_words for w in words):
                return line.title()
    # Pass 2 — title-case name-looking line
    for line in lines[:20]:
        line = line.strip()
        if not line or len(line) > 50:
            continue
        if any(line.lower().startswith(w) for w in skip_words):
            continue
        if name_re.match(line):
            return line
    # Pass 3 — subject fallback: "Job Title - First Last" or "Job Title - First"
    if " - " in subject:
        after_dash = subject.rsplit(" - ", 1)[-1].strip()
        after_dash = re.sub(r"[^A-Za-z\s]", "", after_dash).strip()
        if after_dash and len(after_dash.split()) <= 3:
            return after_dash.title()
    return ""


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

            # Skip internal job-posting / ad-distribution emails
            if any(kw in subject.lower() for kw in SKIP_SUBJECT_KEYWORDS):
                _log(f"SKIP (ad/internal subject): {subject!r}")
                add_label(msg_id, label_id)
                processed_ids.append(msg_id)
                continue

            body_text, attachments = extract_parts(payload)

            if not attachments:
                # Check if this is a body-only resume from a trusted sender
                # (PCR/Indeed profile emails embed the full resume in the HTML body)
                _m = re.search(r"@([\w.\-]+)", sender)
                sender_domain = _m.group(1).lower() if _m else ""
                is_trusted = any(td in sender_domain for td in TRUSTED_SENDERS)
                if is_trusted and body_text and _looks_like_resume(body_text):
                    _log(f"Processing body-only resume from {sender!r}: {subject!r}")
                    display_name = _extract_name_from_body(body_text, subject)
                    name_norm = _normalize_name(display_name or subject) if display_name else "candidate_unknown"
                    candidate_name = display_name or name_norm.replace("_", " ").title()
                    pseudo_filename = f"{name_norm}.txt"

                    req, confidence, reasoning = match_resume_to_requisition(
                        resume_text=body_text,
                        email_subject=subject,
                        email_body=body_text,
                        sender=sender,
                        filename=pseudo_filename,
                    )

                    if req:
                        _log(f"  Matched → {req['req_id']} ({req['title']}) — {int(confidence*100)}% — {reasoning}")
                        orig_path, txt_path = _store_resume(
                            body_text.encode(), pseudo_filename, body_text, req, name_norm, confidence
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
                        _store_resume(body_text.encode(), pseudo_filename, body_text, None, name_norm, confidence)
                        unmatched.append({
                            "filename": pseudo_filename,
                            "sender": sender,
                            "reason": reasoning,
                        })

                    add_label(msg_id, label_id)
                    processed_ids.append(msg_id)
                else:
                    # Not a resume body — mark and skip
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
