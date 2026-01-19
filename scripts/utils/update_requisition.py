#!/usr/bin/env python3
"""
Update requisition status and configuration.
"""

import sys
from pathlib import Path
from datetime import datetime

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.client_utils import (
    get_requisition_config,
    save_requisition_config
)


def update_requisition(
    client_code: str,
    req_id: str,
    status: str = None,
    note: str = None,
    hiring_manager: str = None,
    hr_contact: str = None
):
    """
    Update requisition configuration.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        status: New status (active, on_hold, filled, cancelled)
        note: Note to append
        hiring_manager: Update hiring manager contact
        hr_contact: Update HR contact
    """
    config = get_requisition_config(client_code, req_id)

    changes = []

    if status:
        old_status = config.get("status")
        config["status"] = status
        changes.append(f"Status: {old_status} → {status}")

    if note:
        existing = config.get("notes", "")
        timestamp = datetime.now().strftime("%Y-%m-%d")
        new_note = f"[{timestamp}] {note}"
        config["notes"] = f"{existing}\n\n{new_note}" if existing else new_note
        changes.append(f"Added note")

    if hiring_manager:
        config.setdefault("contacts", {})["hiring_manager"] = hiring_manager
        changes.append(f"Hiring manager: {hiring_manager}")

    if hr_contact:
        config.setdefault("contacts", {})["hr_contact"] = hr_contact
        changes.append(f"HR contact: {hr_contact}")

    if changes:
        save_requisition_config(client_code, req_id, config)
        print(f"Updated {req_id}:")
        for change in changes:
            print(f"  • {change}")
    else:
        print("No changes specified")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Update requisition")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--status", "-s",
                       choices=["active", "on_hold", "filled", "cancelled"],
                       help="New status")
    parser.add_argument("--note", "-n", help="Note to add")
    parser.add_argument("--hiring-manager", help="Update hiring manager")
    parser.add_argument("--hr-contact", help="Update HR contact")
    args = parser.parse_args()

    try:
        update_requisition(
            client_code=args.client,
            req_id=args.req,
            status=args.status,
            note=args.note,
            hiring_manager=args.hiring_manager,
            hr_contact=args.hr_contact
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
