#!/usr/bin/env python3
"""
Client and requisition path utilities.
Provides helper functions for navigating the project directory structure.
"""

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
    return [d.name for d in clients_dir.iterdir() if d.is_dir()]


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


def normalize_candidate_name(name: str) -> str:
    """Normalize a candidate name to lastname_firstname format."""
    # Remove extra whitespace and split
    parts = name.strip().split()
    if len(parts) < 2:
        return name.lower().replace(" ", "_")

    # Assume last part is last name, rest is first name
    last_name = parts[-1].lower()
    first_name = "_".join(parts[:-1]).lower()

    # Remove special characters
    import re
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
