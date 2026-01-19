#!/usr/bin/env python3
"""
List archived requisitions.
Shows all archived requisitions for a client.
"""

import sys
from pathlib import Path
from datetime import datetime

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.client_utils import get_archive_path, list_clients


def list_archive(client_code: str = None) -> list[dict]:
    """
    List archived requisitions.

    Args:
        client_code: Filter by client (None = all clients)

    Returns:
        List of archived requisitions with metadata
    """
    clients = [client_code] if client_code else list_clients()
    archives = []

    for cc in clients:
        archive_path = get_archive_path(cc)

        if not archive_path.exists():
            continue

        for archive_dir in sorted(archive_path.iterdir()):
            if not archive_dir.is_dir():
                continue

            # Try to load requisition config
            config_path = archive_dir / "requisition.yaml"

            if config_path.exists():
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)

                archives.append({
                    "client_code": cc,
                    "archive_name": archive_dir.name,
                    "requisition_id": config.get("requisition_id", archive_dir.name),
                    "title": config.get("job", {}).get("title", "Unknown"),
                    "status": config.get("status", "archived"),
                    "archived_at": config.get("archived_at", ""),
                    "path": str(archive_dir)
                })
            else:
                # Minimal info from folder name
                archives.append({
                    "client_code": cc,
                    "archive_name": archive_dir.name,
                    "requisition_id": archive_dir.name.split("_")[0],
                    "title": "Unknown",
                    "status": "archived",
                    "archived_at": "",
                    "path": str(archive_dir)
                })

    return archives


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="List archived requisitions")
    parser.add_argument("--client", "-c", help="Filter by client code")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    archives = list_archive(args.client)

    if args.json:
        print(json.dumps(archives, indent=2))
    else:
        if not archives:
            print("No archived requisitions found")
            return

        current_client = None
        for a in archives:
            if a["client_code"] != current_client:
                current_client = a["client_code"]
                print(f"\n{current_client}")
                print("=" * 70)

            archived_date = ""
            if a["archived_at"]:
                try:
                    dt = datetime.fromisoformat(a["archived_at"])
                    archived_date = dt.strftime("%Y-%m-%d")
                except ValueError:
                    archived_date = a["archived_at"][:10]

            print(f"  {a['archive_name']}")
            print(f"    Title: {a['title']}")
            print(f"    Status: {a['status']}")
            if archived_date:
                print(f"    Archived: {archived_date}")
            print()


if __name__ == "__main__":
    main()
