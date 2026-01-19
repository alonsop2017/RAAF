#!/usr/bin/env python3
"""
Search for candidates across requisitions.
Finds candidate assessments by name across a client's requisitions.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    list_clients,
    list_requisitions,
    get_assessments_path,
    get_client_info
)


def search_candidate(
    name: str,
    client_code: str = None,
    exact_match: bool = False
) -> list[dict]:
    """
    Search for a candidate across requisitions.

    Args:
        name: Candidate name to search for
        client_code: Filter by client (None = all clients)
        exact_match: Require exact name match

    Returns:
        List of found assessments with metadata
    """
    name_lower = name.lower()
    clients = [client_code] if client_code else list_clients()
    results = []

    for cc in clients:
        for req_id in list_requisitions(cc):
            assessments_path = get_assessments_path(cc, req_id, "individual")

            if not assessments_path.exists():
                continue

            for assessment_file in assessments_path.glob("*_assessment.json"):
                try:
                    with open(assessment_file, "r") as f:
                        data = json.load(f)

                    candidate_name = data.get("candidate", {}).get("name", "")
                    candidate_normalized = data.get("candidate", {}).get("name_normalized", "")

                    match = False
                    if exact_match:
                        if name_lower == candidate_name.lower():
                            match = True
                    else:
                        if (name_lower in candidate_name.lower() or
                            name_lower in candidate_normalized.lower() or
                            candidate_name.lower() in name_lower):
                            match = True

                    if match:
                        results.append({
                            "client_code": cc,
                            "requisition_id": req_id,
                            "name": candidate_name,
                            "name_normalized": candidate_normalized,
                            "score": data.get("total_score", 0),
                            "percentage": data.get("percentage", 0),
                            "recommendation": data.get("recommendation", ""),
                            "assessed_at": data.get("metadata", {}).get("assessed_at", ""),
                            "batch": data.get("candidate", {}).get("batch", ""),
                            "file": str(assessment_file)
                        })

                except (json.JSONDecodeError, KeyError):
                    continue

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Search for candidates")
    parser.add_argument("--name", "-n", required=True, help="Candidate name to search")
    parser.add_argument("--client", "-c", help="Filter by client code")
    parser.add_argument("--exact", action="store_true", help="Exact name match only")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    results = search_candidate(
        name=args.name,
        client_code=args.client,
        exact_match=args.exact
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print(f"No candidates found matching '{args.name}'")
        else:
            print(f"Found {len(results)} result(s) for '{args.name}':")
            print("-" * 80)

            for r in results:
                print(f"\n  {r['name']}")
                print(f"    Client: {r['client_code']}")
                print(f"    Requisition: {r['requisition_id']}")
                print(f"    Score: {r['score']} ({r['percentage']}%)")
                print(f"    Recommendation: {r['recommendation']}")
                if r['batch']:
                    print(f"    Batch: {r['batch']}")


if __name__ == "__main__":
    main()
