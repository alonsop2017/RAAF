#!/usr/bin/env python3
"""
Update candidate pipeline status in PCRecruiter.
Updates pipeline status based on assessment recommendations.
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
    get_resumes_path,
    get_settings
)


# Default status mappings
DEFAULT_STATUS_MAP = {
    "STRONG RECOMMEND": "Interview Scheduled",
    "RECOMMEND": "Interview Scheduled",
    "CONDITIONAL": "On Hold",
    "DO NOT RECOMMEND": "Not Selected"
}


def update_pipeline(
    client_code: str,
    req_id: str,
    dry_run: bool = False,
    status_map: dict = None
) -> dict:
    """
    Update candidate pipeline status based on assessments.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        dry_run: If True, don't actually update PCR
        status_map: Custom recommendation -> status mapping

    Returns:
        Statistics about the update operation
    """
    status_map = status_map or DEFAULT_STATUS_MAP

    # Load requisition config
    req_config = get_requisition_config(client_code, req_id)
    pcr_config = req_config.get("pcr_integration", {})
    position_id = pcr_config.get("job_id")

    if not position_id:
        raise ValueError(f"No PCR job_id configured for requisition {req_id}")

    # Load candidates manifest
    incoming_path = get_resumes_path(client_code, req_id, "incoming")
    manifest_file = incoming_path / "candidates_manifest.json"

    if not manifest_file.exists():
        raise FileNotFoundError("Candidates manifest not found. Sync candidates first.")

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    # Build candidate ID mapping
    candidate_map = {}
    for c in manifest.get("candidates", []):
        name = f"{c.get('FirstName', '')} {c.get('LastName', '')}".strip().lower()
        name_normalized = name.replace(" ", "_")
        candidate_map[name_normalized] = c.get("CandidateId")
        parts = name.split()
        if len(parts) >= 2:
            alt_name = f"{parts[-1]}_{parts[0]}"
            candidate_map[alt_name] = c.get("CandidateId")

    # Load assessments
    assessments_path = get_assessments_path(client_code, req_id, "individual")
    assessment_files = list(assessments_path.glob("*_assessment.json"))

    print(f"Updating pipeline status for {req_id}...")
    print(f"  Position ID: {position_id}")
    print(f"  Assessments to process: {len(assessment_files)}")
    if dry_run:
        print("  DRY RUN - no changes will be made to PCR")

    print(f"\nStatus mapping:")
    for rec, status in status_map.items():
        print(f"  {rec} -> {status}")

    # Connect to PCR
    client = PCRClient()
    if not dry_run:
        client.ensure_authenticated()

    stats = {
        "total": len(assessment_files),
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "by_status": {},
        "details": []
    }

    for assessment_file in assessment_files:
        with open(assessment_file, "r") as f:
            assessment = json.load(f)

        candidate_info = assessment.get("candidate", {})
        name = candidate_info.get("name", "Unknown")
        name_normalized = candidate_info.get("name_normalized", "")
        recommendation = assessment.get("recommendation", "")

        # Find PCR candidate ID
        pcr_id = candidate_map.get(name_normalized)
        if not pcr_id:
            for key in candidate_map:
                if name_normalized in key or key in name_normalized:
                    pcr_id = candidate_map[key]
                    break

        if not pcr_id:
            print(f"  {name}: No PCR ID found - skipped")
            stats["skipped"] += 1
            continue

        # Get target status
        target_status = status_map.get(recommendation)
        if not target_status:
            print(f"  {name}: No status mapping for '{recommendation}' - skipped")
            stats["skipped"] += 1
            continue

        print(f"  {name} ({pcr_id}): {recommendation} -> {target_status}")

        # Track by status
        stats["by_status"][target_status] = stats["by_status"].get(target_status, 0) + 1

        if dry_run:
            stats["updated"] += 1
            stats["details"].append({
                "name": name,
                "pcr_id": pcr_id,
                "recommendation": recommendation,
                "new_status": target_status
            })
            continue

        try:
            client.update_pipeline_status(
                position_id=position_id,
                candidate_id=pcr_id,
                status=target_status,
                notes=f"Assessment: {recommendation}"
            )

            stats["updated"] += 1
            stats["details"].append({
                "name": name,
                "pcr_id": pcr_id,
                "recommendation": recommendation,
                "new_status": target_status
            })

        except PCRClientError as e:
            print(f"    Error: {e}")
            stats["errors"] += 1

    # Save update log
    log_file = assessments_path / "pipeline_update_log.json"
    with open(log_file, "w") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "dry_run": dry_run,
            "position_id": position_id,
            "status_map": status_map,
            "stats": stats
        }, f, indent=2)

    print(f"\nUpdate Summary:")
    print(f"  Updated: {stats['updated']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")
    print(f"\nBy Status:")
    for status, count in stats["by_status"].items():
        print(f"  {status}: {count}")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Update pipeline status in PCRecruiter")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be updated without making changes")
    parser.add_argument("--strong-recommend-status", default="Interview Scheduled",
                       help="Pipeline status for STRONG RECOMMEND")
    parser.add_argument("--recommend-status", default="Interview Scheduled",
                       help="Pipeline status for RECOMMEND")
    parser.add_argument("--conditional-status", default="On Hold",
                       help="Pipeline status for CONDITIONAL")
    parser.add_argument("--dnr-status", default="Not Selected",
                       help="Pipeline status for DO NOT RECOMMEND")
    args = parser.parse_args()

    status_map = {
        "STRONG RECOMMEND": args.strong_recommend_status,
        "RECOMMEND": args.recommend_status,
        "CONDITIONAL": args.conditional_status,
        "DO NOT RECOMMEND": args.dnr_status
    }

    try:
        update_pipeline(
            client_code=args.client,
            req_id=args.req,
            dry_run=args.dry_run,
            status_map=status_map
        )
    except (PCRClientError, FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
