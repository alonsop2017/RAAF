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

    # Support multi-position linking
    position_ids = []
    positions_list = pcr_config.get("positions", [])
    if positions_list:
        position_ids = [str(p.get("job_id")) for p in positions_list if p.get("job_id")]
    elif pcr_config.get("job_id"):
        position_ids = [str(pcr_config["job_id"])]

    if not position_ids:
        raise ValueError(f"No PCR position linked to requisition {req_id}")

    print(f"Syncing candidates for {req_id}...")
    print(f"  PCR Position IDs: {', '.join(position_ids)}")

    # Connect to PCR
    client = PCRClient()
    client.ensure_authenticated()

    # Fetch candidates from all linked positions, deduplicating
    all_candidates = []
    seen_ids = set()
    for position_id in position_ids:
        try:
            candidates = client.get_position_candidates(position_id=position_id)
            for c in candidates:
                cid = c.get("CandidateId")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_candidates.append(c)
            print(f"  Position {position_id}: {len(candidates)} candidate(s)")
        except Exception as e:
            print(f"  Position {position_id}: error - {e}")

    print(f"  Total unique candidates: {len(all_candidates)}")

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
            "position_ids": position_ids,
            "count": len(all_candidates),
            "candidates": all_candidates
        }, f, indent=2, default=str)

    print(f"  Saved manifest to: {candidates_file}")

    # Output results
    if output_format == "json":
        print(json.dumps(all_candidates, indent=2, default=str, ensure_ascii=True))
    else:
        table = format_candidates_table(all_candidates)
        print(table.encode("utf-8", errors="replace").decode("utf-8"))

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
