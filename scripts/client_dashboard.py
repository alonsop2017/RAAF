#!/usr/bin/env python3
"""
Client dashboard.
Quick status overview of all requisitions for a client.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    get_client_info,
    list_requisitions,
    get_requisition_config,
    get_assessments_path
)


def get_assessment_stats(client_code: str, req_id: str) -> dict:
    """Get assessment statistics for a requisition."""
    assessments_path = get_assessments_path(client_code, req_id, "individual")

    stats = {
        "total": 0,
        "recommended": 0,
        "strong_recommend": 0,
        "conditional": 0,
        "dnr": 0,
        "top_score": 0
    }

    if not assessments_path.exists():
        return stats

    for assessment_file in assessments_path.glob("*_assessment.json"):
        try:
            with open(assessment_file, "r") as f:
                data = json.load(f)

            stats["total"] += 1

            rec = data.get("recommendation", "")
            if rec == "STRONG RECOMMEND":
                stats["strong_recommend"] += 1
                stats["recommended"] += 1
            elif rec == "RECOMMEND":
                stats["recommended"] += 1
            elif rec == "CONDITIONAL":
                stats["conditional"] += 1
            else:
                stats["dnr"] += 1

            pct = data.get("percentage", 0)
            if pct > stats["top_score"]:
                stats["top_score"] = pct

        except (json.JSONDecodeError, KeyError):
            continue

    return stats


def display_dashboard(client_code: str, show_all: bool = False):
    """Display client dashboard."""
    try:
        client_info = get_client_info(client_code)
        company_name = client_info.get("company_name", client_code)
    except FileNotFoundError:
        print(f"Client not found: {client_code}")
        sys.exit(1)

    print(f"\n{company_name} - Recruitment Dashboard")
    print("═" * 75)

    # Get requisitions
    status_filter = None if show_all else "active"
    requisitions = list_requisitions(client_code, status=status_filter)

    if not requisitions:
        filter_msg = "" if show_all else " active"
        print(f"No{filter_msg} requisitions found")
        return

    # Header
    print(f"{'Requisition':<20} {'Title':<25} {'Assessed':>8} {'Rec':>4} {'Top':>5} {'Report':<10}")
    print("─" * 75)

    total_assessed = 0
    total_recommended = 0

    for req_id in sorted(requisitions):
        try:
            config = get_requisition_config(client_code, req_id)
        except FileNotFoundError:
            continue

        title = config.get("job", {}).get("title", "Unknown")[:25]
        status = config.get("status", "unknown")
        report_status = config.get("report_status", "pending")

        stats = get_assessment_stats(client_code, req_id)

        total_assessed += stats["total"]
        total_recommended += stats["recommended"]

        # Status indicator
        status_icon = {
            "active": "●",
            "on_hold": "○",
            "filled": "✓",
            "cancelled": "✗"
        }.get(status, "?")

        top_score = f"{stats['top_score']}%" if stats["top_score"] > 0 else "-"

        print(f"{status_icon} {req_id:<18} {title:<25} {stats['total']:>8} {stats['recommended']:>4} {top_score:>5} {report_status:<10}")

    # Summary
    print("─" * 75)
    print(f"{'Total':<20} {'':<25} {total_assessed:>8} {total_recommended:>4}")
    print()

    # Legend
    print("Status: ● Active  ○ On Hold  ✓ Filled  ✗ Cancelled")
    print("Rec = Recommended (STRONG RECOMMEND + RECOMMEND)")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Client recruitment dashboard")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--all", "-a", action="store_true",
                       help="Show all requisitions (not just active)")
    args = parser.parse_args()

    display_dashboard(args.client, show_all=args.all)


if __name__ == "__main__":
    main()
