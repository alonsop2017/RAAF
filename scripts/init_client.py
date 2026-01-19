#!/usr/bin/env python3
"""
Initialize a new client.
Creates the client folder structure and configuration files.
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    get_project_root,
    get_client_root,
    get_config_path,
    list_clients
)


def init_client(
    client_code: str,
    company_name: str,
    industry: str = "",
    commission_rate: float = 0.20,
    contact_name: str = "",
    contact_email: str = ""
) -> dict:
    """
    Initialize a new client.

    Args:
        client_code: Short code for the client (lowercase, no spaces)
        company_name: Full company name
        industry: Industry/sector
        commission_rate: Default commission rate (decimal)
        contact_name: Primary contact name
        contact_email: Primary contact email

    Returns:
        Client configuration dictionary
    """
    # Validate client code
    client_code = client_code.lower().replace(" ", "_")

    if not client_code.replace("_", "").isalnum():
        raise ValueError("Client code must contain only letters, numbers, and underscores")

    # Check if client already exists
    client_root = get_client_root(client_code)
    if client_root.exists():
        raise ValueError(f"Client already exists: {client_code}")

    print(f"Initializing client: {client_code}")
    print(f"  Company: {company_name}")

    # Create client directory structure
    folders = [
        client_root,
        client_root / "requisitions"
    ]

    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        print(f"  Created: {folder.relative_to(get_project_root())}")

    # Create client_info.yaml
    client_info = {
        "client_code": client_code,
        "company_name": company_name,
        "industry": industry,
        "relationship_start": datetime.now().strftime("%Y-%m-%d"),
        "status": "active",
        "contacts": {
            "primary": {
                "name": contact_name,
                "title": "",
                "email": contact_email,
                "phone": ""
            },
            "billing": {
                "name": "",
                "email": ""
            }
        },
        "billing": {
            "default_commission_rate": commission_rate,
            "payment_terms": "Net 30",
            "guarantee_period_days": 90
        },
        "preferences": {
            "report_format": "docx",
            "delivery_method": "email",
            "include_rejected_candidates": False
        },
        "pcr_integration": {
            "enabled": False,
            "company": {
                "company_id": "",
                "company_name": ""
            }
        },
        "active_requisitions": [],
        "notes": ""
    }

    client_info_path = client_root / "client_info.yaml"
    with open(client_info_path, "w") as f:
        yaml.dump(client_info, f, default_flow_style=False, sort_keys=False)

    print(f"  Created: {client_info_path.relative_to(get_project_root())}")

    # Create logs directory for client
    logs_dir = get_project_root() / "logs" / client_code
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Create archive directory for client
    archive_dir = get_project_root() / "archive" / client_code
    archive_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n✓ Client '{client_code}' initialized successfully!")
    print(f"  Location: {client_root}")
    print(f"\nNext steps:")
    print(f"  1. Edit {client_info_path.name} to complete contact and billing details")
    print(f"  2. If using PCR, add company_id to pcr_integration section")
    print(f"  3. Create requisitions with: python scripts/init_requisition.py --client {client_code} ...")

    return client_info


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Initialize a new client")
    parser.add_argument("--code", required=True, help="Client code (short, lowercase)")
    parser.add_argument("--name", required=True, help="Company name")
    parser.add_argument("--industry", default="", help="Industry/sector")
    parser.add_argument("--commission", type=float, default=0.20,
                       help="Default commission rate (default: 0.20)")
    parser.add_argument("--contact-name", default="", help="Primary contact name")
    parser.add_argument("--contact-email", default="", help="Primary contact email")
    parser.add_argument("--list", action="store_true", help="List existing clients")
    args = parser.parse_args()

    if args.list:
        clients = list_clients()
        if not clients:
            print("No clients found")
        else:
            print("Existing clients:")
            for c in sorted(clients):
                print(f"  - {c}")
        return

    try:
        init_client(
            client_code=args.code,
            company_name=args.name,
            industry=args.industry,
            commission_rate=args.commission,
            contact_name=args.contact_name,
            contact_email=args.contact_email
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
