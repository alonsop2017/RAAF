#!/usr/bin/env python3
"""
Client and requisition path utilities.
Provides helper functions for navigating the project directory structure.
"""

import logging
import os
from pathlib import Path
from typing import Optional
import yaml

_log = logging.getLogger(__name__)


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


def get_requisition_root(client_code: str, req_id: str) -> Path:
    """Get the root directory for a requisition."""
    return get_client_root(client_code) / "requisitions" / req_id


def _get_requisition_config_from_file(client_code: str, req_id: str) -> dict:
    """Load requisition config directly from requisition.yaml (file fallback)."""
    req_path = get_requisition_root(client_code, req_id) / "requisition.yaml"
    if not req_path.exists():
        raise FileNotFoundError(f"Requisition config not found: {req_path}")
    with open(req_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_requisition_config(client_code: str, req_id: str) -> dict:
    """Load requisition config (from DB when enabled, else from requisition.yaml)."""
    try:
        from scripts.utils.database import get_db, _use_database
        if _use_database():
            row = get_db().get_requisition(req_id)
            if row:
                return _db_req_to_config(row, client_code)
    except Exception as _e:
        _log.debug("DB get_requisition_config failed, falling back to files: %s", _e)
    return _get_requisition_config_from_file(client_code, req_id)


def save_requisition_config(client_code: str, req_id: str, config: dict) -> None:
    """Save requisition config to requisition.yaml."""
    req_path = get_requisition_root(client_code, req_id) / "requisition.yaml"
    with open(req_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Dual-write to DB when enabled
    try:
        from scripts.utils.database import get_db, _use_database
        if _use_database():
            job = config.get("job", {})
            assessment_cfg = config.get("assessment", {})
            thresholds = assessment_cfg.get("thresholds", {})
            salary = job.get("salary_range", {})
            get_db().update_requisition(req_id, {
                "job_title": job.get("title"),
                "location": job.get("location"),
                "salary_min": salary.get("min", 0),
                "salary_max": salary.get("max", 0),
                "status": config.get("status"),
                "notes": config.get("notes"),
                "threshold_strong": thresholds.get("strong_recommend"),
                "threshold_recommend": thresholds.get("recommend"),
                "threshold_conditional": thresholds.get("conditional"),
            })
    except Exception as _db_err:
        _log.warning("DB dual-write failed in save_requisition_config: %s", _db_err)


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


def _db_client_to_dict(row: dict) -> dict:
    """Transform a DatabaseManager client row to the client_info.yaml dict shape."""
    result = {
        "client_code": row["client_code"],
        "company_name": row["company_name"],
        "industry": row.get("industry"),
        "status": row.get("status", "active"),
        "billing": {
            "default_commission_rate": row.get("default_commission_rate"),
            "payment_terms": row.get("payment_terms"),
            "guarantee_period_days": row.get("guarantee_period_days"),
        },
    }
    if row.get("preferences"):
        result["preferences"] = row["preferences"]
    contacts_raw = row.get("contacts", {})
    if contacts_raw:
        contacts = {}
        for ctype, data in contacts_raw.items():
            contacts[ctype] = {k: data.get(k) for k in ("name", "title", "email", "phone")}
        result["contacts"] = contacts
    return result


def _db_req_to_config(row: dict, client_code: str) -> dict:
    """Transform a DatabaseManager requisition row to the requisition.yaml dict shape."""
    config = {
        "requisition_id": row["req_id"],
        "client_code": client_code,
        "created_date": row.get("created_date"),
        "status": row.get("status", "active"),
        "job": {
            "title": row.get("job_title", ""),
            "department": row.get("department"),
            "location": row.get("location"),
            "salary_range": {
                "min": row.get("salary_min", 0),
                "max": row.get("salary_max", 0),
                "currency": row.get("salary_currency", "CAD"),
            },
        },
        "requirements": {
            "experience_years_min": row.get("experience_years_min", 0),
            "education": row.get("education"),
        },
        "assessment": {
            "framework_version": row.get("framework_version", "1.0"),
            "max_score": row.get("max_score", 100),
            "thresholds": {
                "strong_recommend": row.get("threshold_strong", 85),
                "recommend": row.get("threshold_recommend", 70),
                "conditional": row.get("threshold_conditional", 55),
            },
        },
        "notes": row.get("notes"),
    }
    # pcr_integration: DB stores only the primary job_id; last_sync and multi-position
    # list live in the YAML. Always read from YAML to get the full picture.
    try:
        yaml_pcr = _get_requisition_config_from_file(client_code, row["req_id"]).get("pcr_integration", {})
    except FileNotFoundError:
        yaml_pcr = {}

    if row.get("pcr_job_id") or yaml_pcr.get("job_id"):
        pcr_integration = {
            "job_id": row.get("pcr_job_id") or yaml_pcr.get("job_id"),
            "positions": [{
                "job_id": row["pcr_job_id"],
                "job_title": row.get("pcr_job_title", ""),
                "company_name": row.get("pcr_company_name", ""),
                "linked_date": row.get("pcr_linked_date", ""),
            }] if row.get("pcr_job_id") else [],
            "linked_date": row.get("pcr_linked_date") or yaml_pcr.get("linked_date"),
        }
        # YAML is authoritative for last_sync and multi-position list
        if yaml_pcr.get("last_sync"):
            pcr_integration["last_sync"] = yaml_pcr["last_sync"]
        if yaml_pcr.get("positions"):
            pcr_integration["positions"] = yaml_pcr["positions"]
        config["pcr_integration"] = pcr_integration
    return config


def list_clients() -> list[str]:
    """List all client codes."""
    try:
        from scripts.utils.database import get_db, _use_database
        if _use_database():
            return [r["client_code"] for r in get_db().list_clients()]
    except Exception as _e:
        _log.debug("DB list_clients failed, falling back to files: %s", _e)

    clients_dir = get_project_root() / "clients"
    if not clients_dir.exists():
        return []
    return [d.name for d in clients_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]


def get_client_info(client_code: str) -> dict:
    """Load client info (from DB when enabled, else from client_info.yaml)."""
    try:
        from scripts.utils.database import get_db, _use_database
        if _use_database():
            row = get_db().get_client(client_code)
            if row:
                return _db_client_to_dict(row)
    except Exception as _e:
        _log.debug("DB get_client_info failed, falling back to files: %s", _e)

    client_info_path = get_client_root(client_code) / "client_info.yaml"
    if not client_info_path.exists():
        raise FileNotFoundError(f"Client info not found: {client_info_path}")
    with open(client_info_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_requisitions(client_code: str, status: Optional[str] = None) -> list[str]:
    """List requisition IDs for a client, optionally filtered by status."""
    try:
        from scripts.utils.database import get_db, _use_database
        if _use_database():
            return [r["req_id"] for r in get_db().list_requisitions(client_code, status)]
    except Exception as _e:
        _log.debug("DB list_requisitions failed, falling back to files: %s", _e)

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
                    config = _get_requisition_config_from_file(client_code, d.name)
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
    """Determine the next batch name in YYYY-MM-DD-HH-MM format."""
    from datetime import datetime as _dt
    timestamp = _dt.now().strftime("%Y-%m-%d-%H-%M")
    batches_dir = get_resumes_path(client_code, req_id, "batches")
    batches_dir.mkdir(parents=True, exist_ok=True)

    # If a folder with the same timestamp already exists, append -2, -3, etc.
    candidate = timestamp
    suffix = 2
    while (batches_dir / candidate).exists():
        candidate = f"{timestamp}-{suffix}"
        suffix += 1
    return candidate


def create_batch_folder(client_code: str, req_id: str, batch_name: str = None) -> Path:
    """Create a new batch folder with originals/ and extracted/ subdirectories.

    Returns the batch folder path.
    """
    if batch_name is None:
        batch_name = get_next_batch_name(client_code, req_id)
    batch_dir = get_resumes_path(client_code, req_id, "batches") / batch_name
    (batch_dir / "originals").mkdir(parents=True, exist_ok=True)
    (batch_dir / "extracted").mkdir(parents=True, exist_ok=True)
    return batch_dir


def count_unique_candidates(client_code: str, req_id: str) -> int:
    """Count unique candidates (deduplicated by name) across all batches + legacy folder."""
    seen = set()
    for f in list_all_extracted_resumes(client_code, req_id):
        seen.add(f.stem.replace("_resume", ""))
    legacy_dir = get_requisition_root(client_code, req_id) / "resumes" / "processed"
    if legacy_dir.exists():
        for f in legacy_dir.glob("*.txt"):
            seen.add(f.stem.replace("_resume", ""))
    return len(seen)


def list_all_extracted_resumes(client_code: str, req_id: str) -> list[Path]:
    """Find all extracted TXT resume files across all batches."""
    batches_dir = get_resumes_path(client_code, req_id, "batches")
    if not batches_dir.exists():
        return []
    results = []
    for batch_dir in sorted(batches_dir.iterdir()):
        if batch_dir.is_dir():
            extracted_dir = batch_dir / "extracted"
            if extracted_dir.exists():
                results.extend(sorted(extracted_dir.glob("*.txt")))
    return results


def find_resume_in_batches(
    client_code: str, req_id: str, name_normalized: str, subfolder: str = "extracted"
) -> Optional[Path]:
    """Find a resume file across all batch folders.

    Args:
        subfolder: 'extracted' to find TXT files, 'originals' to find original uploads
    """
    batches_dir = get_resumes_path(client_code, req_id, "batches")
    if not batches_dir.exists():
        return None
    for batch_dir in sorted(batches_dir.iterdir()):
        if not batch_dir.is_dir():
            continue
        target_dir = batch_dir / subfolder
        if not target_dir.exists():
            continue
        if subfolder == "extracted":
            candidate = target_dir / f"{name_normalized}_resume.txt"
            if candidate.exists():
                return candidate
        else:
            # originals - match by normalized filename
            for f in target_dir.iterdir():
                if f.is_file():
                    # Inline normalization to avoid circular import
                    n = f.name.rsplit('.', 1)[0].lower().replace(" ", "_").replace("-", "_")
                    n = ''.join(c for c in n if c.isalnum() or c == '_')
                    if n.endswith('_resume'):
                        n = n[:-7]
                    elif n.endswith('resume'):
                        n = n[:-6]
                    n = n.rstrip('_')
                    if n == name_normalized:
                        return f
    return None


def get_batch_for_resume(client_code: str, req_id: str, name_normalized: str) -> Optional[str]:
    """Get the batch name that contains a given resume."""
    batches_dir = get_resumes_path(client_code, req_id, "batches")
    if not batches_dir.exists():
        return None
    for batch_dir in sorted(batches_dir.iterdir()):
        if not batch_dir.is_dir():
            continue
        extracted_dir = batch_dir / "extracted"
        if extracted_dir.exists():
            candidate = extracted_dir / f"{name_normalized}_resume.txt"
            if candidate.exists():
                return batch_dir.name
    return None


def _transliterate_to_ascii(text: str) -> str:
    """Transliterate European characters to ASCII equivalents."""
    import unicodedata
    # Common European substitutions that don't decompose cleanly via NFKD
    substitutions = {
        'ä': 'ae', 'Ä': 'ae', 'ö': 'oe', 'Ö': 'oe',
        'ü': 'ue', 'Ü': 'ue', 'ß': 'ss',
        'ø': 'o', 'Ø': 'o', 'æ': 'ae', 'Æ': 'ae',
        'å': 'a', 'Å': 'a', 'þ': 'th', 'ð': 'd',
    }
    for char, replacement in substitutions.items():
        text = text.replace(char, replacement)
    # Decompose remaining accented characters and strip diacritics
    text = unicodedata.normalize('NFKD', text)
    return text.encode('ascii', 'ignore').decode('ascii')


def normalize_candidate_name(name: str) -> str:
    """Normalize a candidate name to lastname_firstname format."""
    import re
    # Remove extra whitespace and split
    parts = name.strip().split()
    if len(parts) < 2:
        cleaned = _transliterate_to_ascii(name).lower().replace(" ", "_")
        return re.sub(r'[^a-z_]', '', cleaned)

    # Assume last part is last name, rest is first name
    last_name = _transliterate_to_ascii(parts[-1]).lower()
    first_name = "_".join(_transliterate_to_ascii(p).lower() for p in parts[:-1])

    last_name = re.sub(r'[^a-z]', '', last_name)
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
    with open(context_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_context(context: dict) -> None:
    """Save the current working context."""
    context_file = get_context_file()
    with open(context_file, "w", encoding="utf-8") as f:
        yaml.dump(context, f, default_flow_style=False, allow_unicode=True)


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
