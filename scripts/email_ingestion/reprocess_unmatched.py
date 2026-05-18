#!/usr/bin/env python3
"""
Reprocess unmatched emails from a previous ingestion run.

Reads the ingestion log, identifies emails that were marked as unmatched,
removes their raaf-processed label so they are re-evaluated, then calls
the main ingestion pipeline with an expanded requisition list that includes
inactive/pending requisitions and a lower confidence threshold.

Usage:
    python scripts/email_ingestion/reprocess_unmatched.py [--dry-run]
"""

import re
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.email_ingestion.gmail_client import (
    search_messages, get_message, get_attachment, get_or_create_label,
    extract_parts, send_email, GMAIL_BASE, _headers,
)
from scripts.email_ingestion.resume_matcher import match_resume_to_requisition
from scripts.email_ingestion.ingest_resumes import (
    _extract_text, _normalize_name, _store_resume,
    _add_candidate_to_db, _log, PROCESSED_LABEL,
)
import httpx

LOG_FILE = PROJECT_ROOT / "logs" / "email_ingestion.log"

# ── Docs / ads to skip — not actual candidate resumes ────────────────────────
SKIP_FILENAMES = {
    "efrat - all jobs - april 15, 2026.docx",
    "efrat world.docx",
    "account executive germany - freight forwarding software - original npa data.docx",
    "grants & tenders researcher - emea.docx",
    "grants and tenders research - emea - anywhere in europe - feb 21, 2026.docx",
    "commercial account executive – saas sales – remote – targeting job seekers in anywhere in arizona - efrat us.docx",
    "commercial account executive – saas sales - targets job seekers anywhere in ontario - efrat canada.docx",
    "2026-powerup-americas-agenda.pdf",
}

SKIP_SUBJECT_KEYWORDS = [
    "all ads", "listings on pcr", "job descriptions - ads on indeed",
    "efrat us - job descriptions", "efrat canada - job descriptions",
    "ads and notes", "efrat world",
]


def _remove_label(msg_id: str, label_id: str) -> None:
    httpx.post(
        f"{GMAIL_BASE}/messages/{msg_id}/modify",
        headers=_headers(),
        json={"removeLabelIds": [label_id]},
        timeout=10,
    ).raise_for_status()


def _get_unmatched_message_ids() -> list[str]:
    """
    Parse the ingestion log to find message IDs that had at least one
    unmatched attachment (and weren't already fully handled).
    Correlates Processing lines with subsequent Unmatched lines.
    """
    if not LOG_FILE.exists():
        _log("No ingestion log found.")
        return []

    log_text = LOG_FILE.read_text(encoding="utf-8", errors="replace")

    # Extract message IDs from the log by searching Gmail directly for
    # raaf-processed emails that produced Unmatched results.
    # We use the subjects from the log to query Gmail.
    unmatched_subjects = set()
    lines = log_text.splitlines()
    current_subject = None
    has_unmatched = False

    for line in lines:
        m = re.search(r"Processing message from .+?: '(.+?)' \(", line)
        if m:
            if current_subject and has_unmatched:
                unmatched_subjects.add(current_subject)
            current_subject = m.group(1).strip()
            has_unmatched = False
        elif "Unmatched (" in line and current_subject:
            has_unmatched = True

    if current_subject and has_unmatched:
        unmatched_subjects.add(current_subject)

    _log(f"Found {len(unmatched_subjects)} email subjects with unmatched attachments")
    return list(unmatched_subjects)


def run(dry_run: bool = False):
    _log("=" * 60)
    _log(f"Reprocess-unmatched run started {'(DRY RUN)' if dry_run else ''}")

    label_id = get_or_create_label(PROCESSED_LABEL)
    unmatched_subjects = _get_unmatched_message_ids()

    if not unmatched_subjects:
        _log("Nothing to reprocess.")
        return

    processed = 0
    matched = 0
    skipped = 0
    still_unmatched = []

    for subject in unmatched_subjects:
        # Search Gmail for this specific email (labelled raaf-processed)
        query = (
            f"to:alonso.perez@archtektconsultinginc.com "
            f"has:attachment label:{PROCESSED_LABEL} "
            f"subject:\"{subject[:60]}\""
        )
        try:
            messages = search_messages(query, max_results=5)
        except Exception as e:
            _log(f"  Search error for '{subject[:50]}': {e}")
            continue

        if not messages:
            continue

        for msg_ref in messages:
            msg_id = msg_ref["id"]
            try:
                msg = get_message(msg_id)
                payload = msg.get("payload", {})
                headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
                msg_subject = headers.get("subject", "")
                sender = headers.get("from", "")

                # Skip internal docs / ads
                if any(k in msg_subject.lower() for k in SKIP_SUBJECT_KEYWORDS):
                    _log(f"  SKIP (ad/internal): {msg_subject[:60]}")
                    skipped += 1
                    continue

                body_text, attachments = extract_parts(payload)

                for att in attachments:
                    filename = att["filename"]
                    if filename.lower() in SKIP_FILENAMES:
                        _log(f"  SKIP (known non-resume): {filename}")
                        skipped += 1
                        continue

                    ext = Path(filename).suffix.lower()
                    if ext not in (".pdf", ".doc", ".docx"):
                        continue

                    try:
                        file_bytes = get_attachment(msg_id, att["attachment_id"])
                    except Exception as e:
                        _log(f"  Download error {filename}: {e}")
                        continue

                    extracted = _extract_text(file_bytes, filename)
                    name_norm = _normalize_name(filename)
                    parts = name_norm.split("_")
                    candidate_name = " ".join(p.title() for p in parts) if parts else filename

                    _log(f"  Re-evaluating: {filename} ({len(extracted)} chars)")

                    req, confidence, reasoning = match_resume_to_requisition(
                        resume_text=extracted,
                        email_subject=msg_subject,
                        email_body=body_text,
                        sender=sender,
                        filename=filename,
                    )

                    if req:
                        _log(f"    → MATCHED {req['req_id']} ({int(confidence*100)}%) — {reasoning[:80]}")
                        if not dry_run:
                            _store_resume(file_bytes, filename, extracted, req, name_norm, confidence)
                            _add_candidate_to_db(req, name_norm, candidate_name,
                                                 PROJECT_ROOT / "Direct_Submissions" / req["req_id"] / f"{name_norm}_resume.txt",
                                                 sender, confidence)
                        matched += 1
                    else:
                        _log(f"    → Still unmatched ({int(confidence*100)}%): {reasoning[:80]}")
                        if not dry_run:
                            _store_resume(file_bytes, filename, extracted, None, name_norm, confidence)
                        still_unmatched.append({"filename": filename, "sender": sender,
                                                "subject": msg_subject, "reason": reasoning})

                    processed += 1

            except Exception as e:
                _log(f"  Error on message {msg_id}: {e}")

    _log(f"Reprocess complete — {matched} matched, {len(still_unmatched)} still unmatched, {skipped} skipped")

    if still_unmatched:
        _log("Still-unmatched resumes (need manual assignment or new requisition):")
        for item in still_unmatched:
            _log(f"  • {item['filename']} | {item['subject'][:60]}")
            _log(f"    Reason: {item['reason'][:100]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without writing any files")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
