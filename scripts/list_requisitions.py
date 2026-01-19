#!/usr/bin/env python3
"""
List requisitions across clients.
Displays requisition status and summary information.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    list_clients,
    list_requisitions,
    get_requisition_config,
    get_client_info
)


def list_all_requisitions(
    client_code: str = None,
    status: str = None,
    verbose: bool = False
):
    """
    List requisitions with optional filtering.

    Args:
        client_code: Filter by client (None = all clients)
        status: Filter by status (active, on_hold, filled, cancelled)
        verbose: Show detailed information
    """
    clients = [client_code] if client_code else list_clients()

    if not clients:
        print("No clients found")
        return

    total_reqs = 0

    for cc in sorted(clients):
        try:
            client_info = get_client_info(cc)
            company_name = client_info.get("company_name", cc)
        except FileNotFoundError:
            company_name = cc

        reqs = list_requisitions(cc, status=status)

        if not reqs:
            continue

        print(f"\n{company_name} ({cc})")
        print("=" * 70)

        for req_id in sorted(reqs):
            try:
                req_config = get_requisition_config(cc, req_id)

                title = req_config.get("job", {}).get("title", "Unknown")
                req_status = req_config.get("status", "unknown")
                batches = len(req_config.get("batches_processed", []))
                assessed = req_config.get("total_candidates_assessed", 0)
                report = req_config.get("report_status", "pending")

                status_icon = {
                    "active": "●",
                    "on_hold": "○",
                    "filled": "✓",
                    "cancelled": "✗"
                }.get(req_status, "?")

                print(f"  {status_icon} {req_id}")
                print(f"    Title: {title}")

                if verbose:
                    location = req_config.get("job", {}).get("location", "")
                    salary = req_config.get("job", {}).get("salary_range", {})
                    salary_min = salary.get("min", 0)
                    salary_max = salary.get("max", 0)

                    if location:
                        print(f"    Location: {location}")
                    if salary_max > 0:
                        print(f"    Salary: ${salary_min:,} - ${salary_max:,}")

                print(f"    Status: {req_status} | Batches: {batches} | Assessed: {assessed} | Report: {report}")
                print()

                total_reqs += 1

            except FileNotFoundError:
                print(f"  ? {req_id} (config not found)")
                total_reqs += 1

    print("-" * 70)
    print(f"Total: {total_reqs} requisitions")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="List requisitions")
    parser.add_argument("--client", "-c", help="Filter by client code")
    parser.add_argument("--status", "-s",
                       choices=["active", "on_hold", "filled", "cancelled"],
                       help="Filter by status")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed information")
    args = parser.parse_args()

    list_all_requisitions(
        client_code=args.client,
        status=args.status,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
