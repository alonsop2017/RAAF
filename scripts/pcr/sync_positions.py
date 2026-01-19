#!/usr/bin/env python3
"""
Sync positions from PCRecruiter.
Pulls positions/jobs from PCR and displays them.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.pcr_client import PCRClient, PCRClientError


def sync_positions(
    status: str = None,
    company_id: str = None,
    output_format: str = "table",
    output_file: str = None
) -> list[dict]:
    """
    Sync positions from PCR.

    Args:
        status: Filter by status (Open, Closed, etc.)
        company_id: Filter by company ID
        output_format: Output format (table, json, csv)
        output_file: Optional file to save output

    Returns:
        List of position records
    """
    client = PCRClient()
    client.ensure_authenticated()

    print(f"Fetching positions from PCRecruiter...")
    if status:
        print(f"  Status filter: {status}")
    if company_id:
        print(f"  Company filter: {company_id}")

    # Fetch all positions with pagination
    all_positions = []
    offset = 0
    limit = 100

    while True:
        positions = client.get_positions(
            status=status,
            company_id=company_id,
            limit=limit,
            offset=offset
        )

        if not positions:
            break

        all_positions.extend(positions)
        offset += limit

        if len(positions) < limit:
            break

    print(f"  Retrieved {len(all_positions)} positions")

    # Output results
    if output_format == "json":
        output = json.dumps(all_positions, indent=2, default=str)
    elif output_format == "csv":
        import csv
        import io
        output_buffer = io.StringIO()
        if all_positions:
            writer = csv.DictWriter(output_buffer, fieldnames=all_positions[0].keys())
            writer.writeheader()
            writer.writerows(all_positions)
        output = output_buffer.getvalue()
    else:  # table format
        output = format_positions_table(all_positions)

    if output_file:
        with open(output_file, "w") as f:
            f.write(output)
        print(f"  Saved to: {output_file}")
    else:
        print("\n" + output)

    return all_positions


def format_positions_table(positions: list[dict]) -> str:
    """Format positions as a text table."""
    if not positions:
        return "No positions found."

    lines = []
    lines.append("-" * 100)
    lines.append(f"{'ID':<12} {'Title':<35} {'Company':<25} {'Status':<10} {'Posted':<12}")
    lines.append("-" * 100)

    for pos in positions:
        job_id = str(pos.get("JobId", ""))[:12]
        title = str(pos.get("Title", ""))[:35]
        company = str(pos.get("CompanyName", ""))[:25]
        status = str(pos.get("Status", ""))[:10]
        posted = str(pos.get("PostedDate", ""))[:12]

        lines.append(f"{job_id:<12} {title:<35} {company:<25} {status:<10} {posted:<12}")

    lines.append("-" * 100)
    lines.append(f"Total: {len(positions)} positions")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sync positions from PCRecruiter")
    parser.add_argument("--status", help="Filter by status (Open, Closed, etc.)")
    parser.add_argument("--company-id", help="Filter by company ID")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table",
                       help="Output format")
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    try:
        sync_positions(
            status=args.status,
            company_id=args.company_id,
            output_format=args.format,
            output_file=args.output
        )
    except PCRClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
