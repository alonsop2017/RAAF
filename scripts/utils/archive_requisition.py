#!/usr/bin/env python3
"""
Archive completed requisitions.
Moves requisition to archive folder with timestamp.
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.client_utils import (
    get_requisition_root,
    get_requisition_config,
    get_client_info,
    get_client_root,
    get_archive_path
)


def archive_requisition(
    client_code: str,
    req_id: str,
    status: str = "filled",
    note: str = ""
) -> str:
    """
    Archive a requisition.

    Args:
        client_code: Client identifier
        req_id: Requisition ID to archive
        status: Final status (filled, cancelled, etc.)
        note: Optional archival note

    Returns:
        Path to archived requisition
    """
    req_root = get_requisition_root(client_code, req_id)

    if not req_root.exists():
        raise FileNotFoundError(f"Requisition not found: {req_id}")

    # Update requisition status before archiving
    config = get_requisition_config(client_code, req_id)
    config["status"] = status
    config["archived_at"] = datetime.now().isoformat()
    if note:
        existing_notes = config.get("notes", "")
        config["notes"] = f"{existing_notes}\n\nArchived: {note}" if existing_notes else f"Archived: {note}"

    config_path = req_root / "requisition.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Create archive path
    archive_root = get_archive_path(client_code)
    archive_root.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    archive_name = f"{req_id}_{date_str}"
    archive_path = archive_root / archive_name

    # Handle existing archive with same name
    counter = 1
    while archive_path.exists():
        archive_path = archive_root / f"{archive_name}_{counter}"
        counter += 1

    print(f"Archiving requisition: {req_id}")
    print(f"  From: {req_root}")
    print(f"  To: {archive_path}")
    print(f"  Status: {status}")

    # Move to archive
    shutil.move(str(req_root), str(archive_path))

    # Update client's active requisitions
    client_info = get_client_info(client_code)
    active_reqs = client_info.get("active_requisitions", [])
    if req_id in active_reqs:
        active_reqs.remove(req_id)
        client_info["active_requisitions"] = active_reqs

        client_info_path = get_client_root(client_code) / "client_info.yaml"
        with open(client_info_path, "w") as f:
            yaml.dump(client_info, f, default_flow_style=False, sort_keys=False)

    print(f"\n✓ Requisition archived successfully!")
    print(f"  Archive location: {archive_path}")

    return str(archive_path)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Archive a requisition")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--status", "-s", default="filled",
                       choices=["filled", "cancelled", "on_hold", "closed"],
                       help="Final status (default: filled)")
    parser.add_argument("--note", "-n", default="", help="Archival note")
    args = parser.parse_args()

    try:
        archive_requisition(
            client_code=args.client,
            req_id=args.req,
            status=args.status,
            note=args.note
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
