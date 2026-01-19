#!/usr/bin/env python3
"""
Push assessment scores back to PCRecruiter.
Updates candidate records with assessment results.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.pcr_client import PCRClient, PCRClientError
from utils.client_utils import (
    get_requisition_config,
    get_assessments_path,
    get_resumes_path
)


def push_scores(
    client_code: str,
    req_id: str,
    dry_run: bool = False,
    batch: str = None
) -> dict:
    """
    Push assessment scores to PCR candidate records.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        dry_run: If True, don't actually update PCR
        batch: Specific batch to push (None = all)

    Returns:
        Statistics about the push operation
    """
    # Load requisition config
    req_config = get_requisition_config(client_code, req_id)

    # Load candidates manifest to get PCR IDs
    incoming_path = get_resumes_path(client_code, req_id, "incoming")
    manifest_file = incoming_path / "candidates_manifest.json"

    if not manifest_file.exists():
        raise FileNotFoundError("Candidates manifest not found. Sync candidates first.")

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    # Build candidate ID mapping (normalized name -> PCR ID)
    candidate_map = {}
    for c in manifest.get("candidates", []):
        name = f"{c.get('FirstName', '')} {c.get('LastName', '')}".strip().lower()
        name_normalized = name.replace(" ", "_")
        candidate_map[name_normalized] = c.get("CandidateId")
        # Also map by lastname_firstname
        parts = name.split()
        if len(parts) >= 2:
            alt_name = f"{parts[-1]}_{parts[0]}"
            candidate_map[alt_name] = c.get("CandidateId")

    # Load assessments
    assessments_path = get_assessments_path(client_code, req_id, "individual")
    assessment_files = list(assessments_path.glob("*_assessment.json"))

    if batch:
        # Filter to specific batch
        assessment_files = [
            f for f in assessment_files
            if batch in json.loads(f.read_text()).get("candidate", {}).get("batch", "")
        ]

    print(f"Pushing assessment scores for {req_id}...")
    print(f"  Assessments to process: {len(assessment_files)}")
    if dry_run:
        print("  DRY RUN - no changes will be made to PCR")

    # Connect to PCR
    client = PCRClient()
    if not dry_run:
        client.ensure_authenticated()

    stats = {
        "total": len(assessment_files),
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "details": []
    }

    for assessment_file in assessment_files:
        with open(assessment_file, "r") as f:
            assessment = json.load(f)

        candidate_info = assessment.get("candidate", {})
        name = candidate_info.get("name", "Unknown")
        name_normalized = candidate_info.get("name_normalized", "")

        # Find PCR candidate ID
        pcr_id = candidate_map.get(name_normalized)
        if not pcr_id:
            # Try variations
            for key in candidate_map:
                if name_normalized in key or key in name_normalized:
                    pcr_id = candidate_map[key]
                    break

        if not pcr_id:
            print(f"  {name}: No PCR ID found - skipped")
            stats["skipped"] += 1
            continue

        score = assessment.get("total_score", 0)
        percentage = assessment.get("percentage", 0)
        recommendation = assessment.get("recommendation", "")
        summary = assessment.get("summary", "")

        print(f"  {name} ({pcr_id}): {score}/100 ({percentage}%) - {recommendation}")

        if dry_run:
            stats["updated"] += 1
            stats["details"].append({
                "name": name,
                "pcr_id": pcr_id,
                "score": score,
                "recommendation": recommendation
            })
            continue

        try:
            # Update candidate with assessment score
            # Note: Field names may need to be customized based on PCR configuration
            client.set_assessment_score(
                candidate_id=pcr_id,
                score=percentage,
                recommendation=recommendation
            )

            # Add assessment note
            note_text = (
                f"Assessment Score: {score}/100 ({percentage}%)\n"
                f"Recommendation: {recommendation}\n\n"
                f"Summary: {summary}"
            )
            client.add_candidate_note(
                candidate_id=pcr_id,
                note=note_text,
                note_type="Assessment"
            )

            stats["updated"] += 1
            stats["details"].append({
                "name": name,
                "pcr_id": pcr_id,
                "score": score,
                "recommendation": recommendation
            })

        except PCRClientError as e:
            print(f"    Error: {e}")
            stats["errors"] += 1

    # Save push log
    log_file = assessments_path / "push_log.json"
    with open(log_file, "w") as f:
        json.dump({
            "pushed_at": datetime.now().isoformat(),
            "dry_run": dry_run,
            "stats": stats
        }, f, indent=2)

    print(f"\nPush Summary:")
    print(f"  Updated: {stats['updated']}")
    print(f"  Skipped (no PCR ID): {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Push assessment scores to PCRecruiter")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--batch", help="Specific batch to push")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be pushed without making changes")
    args = parser.parse_args()

    try:
        push_scores(
            client_code=args.client,
            req_id=args.req,
            dry_run=args.dry_run,
            batch=args.batch
        )
    except (PCRClientError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
