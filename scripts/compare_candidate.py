#!/usr/bin/env python3
"""
Compare candidate assessments across requisitions.
Shows how a candidate scored against different role frameworks.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    get_assessments_path,
    get_requisition_config
)
from search_candidate import search_candidate


def compare_candidate(
    client_code: str,
    candidate_name: str,
    req_ids: list[str] = None
) -> dict:
    """
    Compare a candidate's assessments across requisitions.

    Args:
        client_code: Client identifier
        candidate_name: Candidate name to search for
        req_ids: Specific requisition IDs to compare (None = all)

    Returns:
        Comparison data
    """
    # Find all assessments for this candidate
    results = search_candidate(candidate_name, client_code)

    if not results:
        raise ValueError(f"No assessments found for '{candidate_name}'")

    # Filter to specific requisitions if provided
    if req_ids:
        results = [r for r in results if r["requisition_id"] in req_ids]

    if not results:
        raise ValueError(f"No assessments found for '{candidate_name}' in specified requisitions")

    # Build comparison
    comparison = {
        "candidate_name": results[0]["name"],
        "client_code": client_code,
        "assessments": []
    }

    for r in results:
        req_config = get_requisition_config(client_code, r["requisition_id"])

        assessment_data = {
            "requisition_id": r["requisition_id"],
            "job_title": req_config.get("job", {}).get("title", "Unknown"),
            "score": r["score"],
            "percentage": r["percentage"],
            "recommendation": r["recommendation"],
            "assessed_at": r["assessed_at"]
        }

        # Load full assessment for detailed breakdown
        with open(r["file"], "r") as f:
            full_assessment = json.load(f)

        assessment_data["scores_breakdown"] = {}
        for category, data in full_assessment.get("scores", {}).items():
            if isinstance(data, dict):
                assessment_data["scores_breakdown"][category] = {
                    "score": data.get("score", 0),
                    "max": data.get("max", 0)
                }

        comparison["assessments"].append(assessment_data)

    # Sort by percentage descending
    comparison["assessments"].sort(key=lambda x: x["percentage"], reverse=True)

    return comparison


def display_comparison(comparison: dict):
    """Display comparison in a readable format."""
    print(f"\nCandidate Comparison: {comparison['candidate_name']}")
    print(f"Client: {comparison['client_code']}")
    print("=" * 80)

    for a in comparison["assessments"]:
        print(f"\n{a['requisition_id']} - {a['job_title']}")
        print("-" * 60)
        print(f"  Overall: {a['score']} ({a['percentage']}%) - {a['recommendation']}")
        print(f"  Assessed: {a['assessed_at'][:10] if a['assessed_at'] else 'N/A'}")

        if a["scores_breakdown"]:
            print("\n  Category Breakdown:")
            for category, scores in a["scores_breakdown"].items():
                category_display = category.replace("_", " ").title()
                pct = round((scores['score'] / scores['max']) * 100) if scores['max'] > 0 else 0
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                print(f"    {category_display:25} {scores['score']:2}/{scores['max']:2} [{bar}] {pct}%")

    print("\n" + "=" * 80)

    # Best fit recommendation
    if len(comparison["assessments"]) > 1:
        best = comparison["assessments"][0]
        print(f"\nBest Fit: {best['job_title']} ({best['requisition_id']}) at {best['percentage']}%")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Compare candidate across requisitions")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--candidate", required=True, help="Candidate name")
    parser.add_argument("--reqs", nargs="+", help="Specific requisition IDs to compare")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        comparison = compare_candidate(
            client_code=args.client,
            candidate_name=args.candidate,
            req_ids=args.reqs
        )

        if args.json:
            print(json.dumps(comparison, indent=2))
        else:
            display_comparison(comparison)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
