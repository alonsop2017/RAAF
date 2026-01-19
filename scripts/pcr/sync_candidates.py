#!/usr/bin/env python3
"""
Sync candidates from PCRecruiter pipeline.
Pulls candidates associated with a position/requisition.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.pcr_client import PCRClient, PCRClientError
from utils.client_utils import (
    get_requisition_config,
    save_requisition_config,
    get_resumes_path
)


def sync_candidates(
    client_code: str,
    req_id: str,
    since_last_sync: bool = False,
    output_format: str = "table"
) -> list[dict]:
    """
    Sync candidates from PCR for a requisition.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        since_last_sync: Only fetch candidates added since last sync
        output_format: Output format (table, json)

    Returns:
        List of candidate records
    """
    # Load requisition config
    req_config = get_requisition_config(client_code, req_id)
    pcr_config = req_config.get("pcr_integration", {})
    position_id = pcr_config.get("job_id")

    if not position_id:
        raise ValueError(f"No PCR job_id configured for requisition {req_id}")

    print(f"Syncing candidates for {req_id}...")
    print(f"  PCR Position ID: {position_id}")

    # Connect to PCR
    client = PCRClient()
    client.ensure_authenticated()

    # Fetch candidates
    all_candidates = []
    offset = 0
    limit = 100

    while True:
        candidates = client.get_position_candidates(
            position_id=position_id,
            limit=limit,
            offset=offset
        )

        if not candidates:
            break

        all_candidates.extend(candidates)
        offset += limit

        if len(candidates) < limit:
            break

    print(f"  Retrieved {len(all_candidates)} candidates")

    # Filter by last sync if requested
    last_sync = pcr_config.get("last_sync")
    if since_last_sync and last_sync:
        last_sync_dt = datetime.fromisoformat(last_sync)
        all_candidates = [
            c for c in all_candidates
            if datetime.fromisoformat(c.get("DateAdded", "2000-01-01")) > last_sync_dt
        ]
        print(f"  New since last sync: {len(all_candidates)} candidates")

    # Update last sync time
    pcr_config["last_sync"] = datetime.now().isoformat()
    req_config["pcr_integration"] = pcr_config
    save_requisition_config(client_code, req_id, req_config)

    # Save candidates list
    incoming_path = get_resumes_path(client_code, req_id, "incoming")
    incoming_path.mkdir(parents=True, exist_ok=True)

    candidates_file = incoming_path / "candidates_manifest.json"
    with open(candidates_file, "w") as f:
        json.dump({
            "synced_at": datetime.now().isoformat(),
            "position_id": position_id,
            "count": len(all_candidates),
            "candidates": all_candidates
        }, f, indent=2, default=str)

    print(f"  Saved manifest to: {candidates_file}")

    # Output results
    if output_format == "json":
        print(json.dumps(all_candidates, indent=2, default=str))
    else:
        print(format_candidates_table(all_candidates))

    return all_candidates


def format_candidates_table(candidates: list[dict]) -> str:
    """Format candidates as a text table."""
    if not candidates:
        return "No candidates found."

    lines = []
    lines.append("-" * 90)
    lines.append(f"{'ID':<12} {'Name':<30} {'Email':<30} {'Status':<15}")
    lines.append("-" * 90)

    for c in candidates:
        cid = str(c.get("CandidateId", ""))[:12]
        name = f"{c.get('FirstName', '')} {c.get('LastName', '')}"[:30]
        email = str(c.get("Email", ""))[:30]
        status = str(c.get("PipelineStatus", ""))[:15]

        lines.append(f"{cid:<12} {name:<30} {email:<30} {status:<15}")

    lines.append("-" * 90)
    lines.append(f"Total: {len(candidates)} candidates")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sync candidates from PCRecruiter")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--since-last-sync", action="store_true",
                       help="Only fetch candidates since last sync")
    parser.add_argument("--format", choices=["table", "json"], default="table",
                       help="Output format")
    args = parser.parse_args()

    try:
        sync_candidates(
            client_code=args.client,
            req_id=args.req,
            since_last_sync=args.since_last_sync,
            output_format=args.format
        )
    except (PCRClientError, ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
