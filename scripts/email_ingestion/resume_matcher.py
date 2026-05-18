#!/usr/bin/env python3
"""
AI-powered requisition matcher for incoming email resumes.
Uses Claude to match a resume + email context to the best active requisition.
"""

import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_active_requisitions() -> list[dict]:
    """Return all active requisitions with client, req_id, job title, and location."""
    try:
        from scripts.utils.database import get_db, _use_database
        if _use_database():
            db = get_db()
            reqs = db.list_requisitions(status="active")
            return [
                {
                    "client_code": r.get("client_code", ""),
                    "req_id": r.get("req_id", ""),
                    "title": r.get("job_title", ""),
                    "location": r.get("location", ""),
                }
                for r in reqs
            ]
    except Exception:
        pass

    # File fallback
    from scripts.utils.client_utils import list_clients, list_requisitions, get_requisition_config
    result = []
    for client_code in list_clients():
        for req_id in list_requisitions(client_code, status="active"):
            try:
                cfg = get_requisition_config(client_code, req_id)
                result.append({
                    "client_code": client_code,
                    "req_id": req_id,
                    "title": cfg.get("job", {}).get("title", ""),
                    "location": cfg.get("job", {}).get("location", ""),
                })
            except Exception:
                pass
    return result


def match_resume_to_requisition(
    resume_text: str,
    email_subject: str,
    email_body: str,
    sender: str,
    filename: str,
) -> tuple[Optional[dict], float, str]:
    """
    Use Claude to match a resume to the best active requisition.

    Returns:
        (requisition_dict or None, confidence 0-1, reasoning_string)
    """
    active = get_active_requisitions()
    if not active:
        return None, 0.0, "No active requisitions found."

    reqs_list = "\n".join(
        f"- {r['req_id']} | {r['title']} | {r['location']} (client: {r['client_code']})"
        for r in active
    )

    # Truncate resume text to keep the prompt lean
    resume_snippet = resume_text[:3000] if resume_text else "(no text extracted)"

    prompt = f"""You are a recruitment system matching an incoming resume email to the correct open job requisition.

ACTIVE REQUISITIONS:
{reqs_list}

INCOMING EMAIL:
  From: {sender}
  Subject: {email_subject}
  Body (first 500 chars): {email_body[:500]}
  Attachment filename: {filename}

RESUME EXCERPT (first 3000 chars):
{resume_snippet}

TASK:
1. Identify which active requisition this resume best matches, based on the job title, skills, experience, and any clues in the email subject/body.
2. Return a JSON object with exactly these fields:
   - "req_id": the matching requisition ID string, or null if no confident match
   - "confidence": a float 0.0-1.0 (0.8+ = strong match, 0.5-0.79 = possible, <0.5 = unmatched)
   - "reasoning": one sentence explaining the match or why it's unmatched

Respond with ONLY the JSON object, no other text."""

    try:
        import anthropic
        import os
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
    except Exception as e:
        return None, 0.0, f"AI matching error: {e}"

    req_id = result.get("req_id")
    confidence = float(result.get("confidence", 0.0))
    reasoning = result.get("reasoning", "")

    if req_id and confidence >= 0.5:
        matched = next((r for r in active if r["req_id"] == req_id), None)
        return matched, confidence, reasoning

    return None, confidence, reasoning
