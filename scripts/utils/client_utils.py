#!/usr/bin/env python3
"""
Client and requisition path utilities.
Provides helper functions for navigating the project directory structure.
"""

import json
import os
from pathlib import Path
from typing import Optional
import yaml


def get_project_root() -> Path:
    """Get the project root directory."""
    # Navigate up from scripts/utils to project root
    current = Path(__file__).resolve()
    return current.parent.parent.parent


def get_config_path() -> Path:
    """Get the config directory path."""
    return get_project_root() / "config"


def get_settings() -> dict:
    """Load global settings from config/settings.yaml."""
    settings_path = get_config_path() / "settings.yaml"
    if not settings_path.exists():
        raise FileNotFoundError(f"Settings file not found: {settings_path}")
    with open(settings_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_client_root(client_code: str) -> Path:
    """Get the root directory for a client."""
    return get_project_root() / "clients" / client_code


def get_client_info(client_code: str) -> dict:
    """Load client info from client_info.yaml."""
    client_info_path = get_client_root(client_code) / "client_info.yaml"
    if not client_info_path.exists():
        raise FileNotFoundError(f"Client info not found: {client_info_path}")
    with open(client_info_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_requisition_root(client_code: str, req_id: str) -> Path:
    """Get the root directory for a requisition."""
    return get_client_root(client_code) / "requisitions" / req_id


def get_requisition_config(client_code: str, req_id: str) -> dict:
    """Load requisition config from requisition.yaml."""
    req_path = get_requisition_root(client_code, req_id) / "requisition.yaml"
    if not req_path.exists():
        raise FileNotFoundError(f"Requisition config not found: {req_path}")
    with open(req_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_requisition_config(client_code: str, req_id: str, config: dict) -> None:
    """Save requisition config to requisition.yaml."""
    req_path = get_requisition_root(client_code, req_id) / "requisition.yaml"
    with open(req_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def get_resumes_path(client_code: str, req_id: str, folder: str = "incoming") -> Path:
    """Get the resumes directory path.

    Args:
        client_code: Client identifier
        req_id: Requisition identifier
        folder: One of 'incoming', 'processed', or 'batches'
    """
    return get_requisition_root(client_code, req_id) / "resumes" / folder


def get_batch_path(client_code: str, req_id: str, batch_name: str) -> Path:
    """Get the path for a specific batch."""
    return get_resumes_path(client_code, req_id, "batches") / batch_name


def get_assessments_path(client_code: str, req_id: str, folder: str = "individual") -> Path:
    """Get the assessments directory path.

    Args:
        client_code: Client identifier
        req_id: Requisition identifier
        folder: One of 'individual' or 'consolidated'
    """
    return get_requisition_root(client_code, req_id) / "assessments" / folder


_TIER_BY_RECOMMENDATION = {
    "STRONG RECOMMEND": 1, "RECOMMEND": 2, "CONDITIONAL": 3, "DO NOT RECOMMEND": 4,
}


def sync_assessment_json_files(client_code: str, req_id: str) -> int:
    """Write out a legacy-shaped JSON file for every DB assessment that
    doesn't have one on disk yet.

    Several consumers (the DOCX/PDF report generator, the PCR score-push
    script, interview-invitation generation) only know how to read
    assessments/individual/*.json off disk — they predate the DB migration
    and were never given a DB read path. Rather than teach each of them
    (one of which is a separate Node.js codebase with no DB access) to query
    SQLite, call this once before they run so any candidate assessed under
    RAAF_DB_MODE=db (which never gets a JSON file written automatically) is
    materialized first. Idempotent — never overwrites an existing file, so a
    prior manual edit to a JSON file is never clobbered.

    Returns the number of files written.
    """
    try:
        from scripts.utils.database import get_db, _use_database
    except ImportError:
        return 0
    if not _use_database():
        return 0

    assessments_dir = get_assessments_path(client_code, req_id, "individual")
    assessments_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for row in get_db().list_assessments(req_id):
        name_normalized = row["name_normalized"]
        out_path = assessments_dir / f"{name_normalized}_assessment.json"
        if out_path.exists():
            continue

        scores = row.get("scores") or {}
        max_score = sum(cat.get("max", 0) for cat in scores.values()) if scores else 100
        recommendation = row.get("recommendation", "")
        doc = {
            "metadata": {
                "client_code": client_code,
                "requisition_id": req_id,
                "assessed_at": row.get("assessed_at"),
                "assessor": row.get("ai_model") or "Claude/Automated",
            },
            "candidate": {
                "name": row.get("name", name_normalized),
                "name_normalized": name_normalized,
                "batch": row.get("batch"),
                "source_platform": row.get("source_platform", ""),
            },
            "scores": scores,
            "total_score": row.get("total_score"),
            "max_score": max_score or 100,
            "percentage": row.get("percentage"),
            "recommendation": recommendation,
            "recommendation_tier": _TIER_BY_RECOMMENDATION.get(recommendation, 4),
            "summary": row.get("summary", ""),
            "key_strengths": row.get("key_strengths", []) or [],
            "areas_of_concern": row.get("areas_of_concern", []) or [],
            "interview_focus_areas": row.get("interview_focus", []) or [],
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
        written += 1

    return written


def get_reports_path(client_code: str, req_id: str, folder: str = "final") -> Path:
    """Get the reports directory path.

    Args:
        client_code: Client identifier
        req_id: Requisition identifier
        folder: One of 'drafts' or 'final'
    """
    return get_requisition_root(client_code, req_id) / "reports" / folder


def get_framework_path(client_code: str, req_id: str) -> Path:
    """Get the framework directory path."""
    return get_requisition_root(client_code, req_id) / "framework"


def get_correspondence_path(client_code: str, req_id: str) -> Path:
    """Get the correspondence directory path."""
    return get_requisition_root(client_code, req_id) / "correspondence"


def get_archive_path(client_code: str) -> Path:
    """Get the archive directory path for a client."""
    return get_project_root() / "archive" / client_code


def get_logs_path(client_code: str) -> Path:
    """Get the logs directory path for a client."""
    return get_project_root() / "logs" / client_code


def get_templates_path() -> Path:
    """Get the templates directory path."""
    return get_project_root() / "templates"


def get_framework_template_path(template_name: str) -> Path:
    """Get the path to a framework template."""
    return get_templates_path() / "frameworks" / f"{template_name}_template.md"


def list_clients() -> list[str]:
    """List all client codes."""
    clients_dir = get_project_root() / "clients"
    if not clients_dir.exists():
        return []
    return [d.name for d in clients_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]


def list_requisitions(client_code: str, status: Optional[str] = None) -> list[str]:
    """List requisition IDs for a client, optionally filtered by status."""
    req_dir = get_client_root(client_code) / "requisitions"
    if not req_dir.exists():
        return []

    reqs = []
    for d in req_dir.iterdir():
        if d.is_dir():
            if status is None:
                reqs.append(d.name)
            else:
                try:
                    config = get_requisition_config(client_code, d.name)
                    if config.get("status") == status:
                        reqs.append(d.name)
                except FileNotFoundError:
                    continue
    return sorted(reqs)


def list_batches(client_code: str, req_id: str) -> list[str]:
    """List all batches for a requisition."""
    batches_dir = get_resumes_path(client_code, req_id, "batches")
    if not batches_dir.exists():
        return []
    return sorted([d.name for d in batches_dir.iterdir() if d.is_dir()])


def get_next_batch_name(client_code: str, req_id: str) -> str:
    """Generate the next batch name (batch_YYYYMMDD_N) for a requisition."""
    from datetime import datetime

    today = datetime.now().strftime("%Y%m%d")
    existing = list_batches(client_code, req_id)

    # Find highest N for today's date
    n = 1
    for batch in existing:
        if batch.startswith(f"batch_{today}_"):
            try:
                num = int(batch.split("_")[-1])
                n = max(n, num + 1)
            except ValueError:
                continue

    return f"batch_{today}_{n}"


def create_batch_folder(client_code: str, req_id: str) -> Path:
    """Create a new batch folder with originals/ and extracted/ subdirectories."""
    batch_name = get_next_batch_name(client_code, req_id)
    batch_dir = get_batch_path(client_code, req_id, batch_name)
    (batch_dir / "originals").mkdir(parents=True, exist_ok=True)
    (batch_dir / "extracted").mkdir(parents=True, exist_ok=True)
    return batch_dir


def list_all_extracted_resumes(client_code: str, req_id: str) -> list[Path]:
    """List all extracted resume files across all batches for a requisition."""
    batches_dir = get_resumes_path(client_code, req_id, "batches")
    results = []
    if batches_dir.exists():
        for batch_dir in sorted(batches_dir.iterdir()):
            extracted_dir = batch_dir / "extracted"
            if extracted_dir.exists():
                results.extend(sorted(extracted_dir.iterdir()))
    return results


def count_unique_candidates(client_code: str, req_id: str) -> int:
    """Count distinct candidates for a requisition (files-mode fallback path).

    Naively summing files under resumes/batches/*/extracted/ double-counts a
    candidate who was reassessed into a second batch, and never sees
    candidates whose resume lives outside the batch layout (e.g.
    Direct_Submissions/). Dedupe by name_normalized across both, matching
    the logic list_candidates() already uses for the same reason.
    """
    seen: set = set()
    for resume_file in list_all_extracted_resumes(client_code, req_id):
        seen.add(resume_file.stem.replace("_resume", ""))

    legacy_dir = get_requisition_root(client_code, req_id) / "resumes" / "processed"
    if legacy_dir.exists():
        for resume_file in legacy_dir.glob("*.txt"):
            seen.add(resume_file.stem.replace("_resume", ""))

    return len(seen)


def find_resume_in_batches(
    client_code: str, req_id: str, name_normalized: str, subfolder: str = "extracted"
) -> Optional[Path]:
    """Find a resume file by normalized name across all batches.

    Args:
        client_code: Client identifier
        req_id: Requisition identifier
        name_normalized: Normalized candidate name (e.g. 'smith_jane')
        subfolder: 'extracted' or 'originals'

    Returns:
        Path to the file if found, None otherwise.
    """
    batches_dir = get_resumes_path(client_code, req_id, "batches")
    if not batches_dir.exists():
        return None
    for batch_dir in sorted(batches_dir.iterdir()):
        sub = batch_dir / subfolder
        if not sub.exists():
            continue
        for f in sub.iterdir():
            if f.stem.replace("_resume", "") == name_normalized:
                return f
    return None


def get_batch_for_resume(client_code: str, req_id: str, name_normalized: str) -> Optional[str]:
    """Get the batch name that contains a given candidate's resume."""
    found = find_resume_in_batches(client_code, req_id, name_normalized, "extracted")
    if found:
        # Path is .../batches/<batch_name>/extracted/<file>
        return found.parent.parent.name
    return None


_PCR_NAME_JUNK_TOKENS: frozenset = frozenset({
    "peoplefind", "peoplefindinc", "indeed", "linkedin", "techleader",
    "litcom", "summary", "director", "management", "accounting",
    "controller", "pmo", "pm", "engineer", "engineering", "specialist",
    "coordinator", "analyst", "consultant", "executive", "developer",
    "administrator", "officer", "lead", "senior", "junior", "sr", "jr",
    "cv", "resume", "hiring", "recruiting",
})


def clean_pcr_name(first: str, last: str) -> tuple:
    """Return (display_name, name_normalized) cleaned from raw PCR FirstName/LastName.

    Applies title case, strips junk tokens, and returns a normalised key.
    If both parts are junk, returns ("", "") so the caller can skip/fallback.
    """
    import re as _re

    def _clean_part(s: str) -> str:
        s = s.strip()
        # Title-case ALL-CAPS words; leave already-mixed-case words alone
        if s == s.upper():
            s = s.title()
        return s

    first_c = _clean_part(first)
    last_c  = _clean_part(last)

    # Drop tokens that are job titles / company names
    first_parts = [p for p in first_c.split() if p.lower() not in _PCR_NAME_JUNK_TOKENS]
    last_parts  = [p for p in last_c.split()  if p.lower() not in _PCR_NAME_JUNK_TOKENS]

    display = " ".join(first_parts + last_parts).strip()
    if not display:
        return ("", "")

    norm = normalize_candidate_name(display)
    # Reject if norm itself still contains junk
    if any(part in _PCR_NAME_JUNK_TOKENS for part in norm.split("_")):
        return ("", "")

    return (display, norm)


def normalize_candidate_name(name: str) -> str:
    """Normalize a candidate name to lastname_firstname format."""
    import re
    parts = name.strip().split()
    if len(parts) < 2:
        return name.lower().replace(" ", "_")

    last_name  = parts[-1].lower()
    first_name = "_".join(parts[:-1]).lower()

    last_name  = re.sub(r'[^a-z]', '', last_name)
    first_name = re.sub(r'[^a-z_]', '', first_name)

    return f"{last_name}_{first_name}"


def get_context_file() -> Path:
    """Get the path to the context file."""
    settings = get_settings()
    context_file = settings.get("context", {}).get("file", ".current_context.yaml")
    return get_project_root() / context_file


def load_context() -> dict:
    """Load the current working context."""
    context_file = get_context_file()
    if not context_file.exists():
        return {}
    with open(context_file, "r") as f:
        return yaml.safe_load(f) or {}


def save_context(context: dict) -> None:
    """Save the current working context."""
    context_file = get_context_file()
    with open(context_file, "w") as f:
        yaml.dump(context, f, default_flow_style=False)


def clear_context() -> None:
    """Clear the current working context."""
    context_file = get_context_file()
    if context_file.exists():
        context_file.unlink()


if __name__ == "__main__":
    # Quick test
    print(f"Project root: {get_project_root()}")
    print(f"Config path: {get_config_path()}")
    print(f"Clients: {list_clients()}")
