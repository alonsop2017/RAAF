#!/usr/bin/env python3
"""
Create assessment batch from processed resumes.
Organizes resumes into batches for assessment.
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    get_resumes_path,
    get_batch_path,
    get_requisition_config,
    save_requisition_config
)


def create_batch(
    client_code: str,
    req_id: str,
    batch_name: str = None,
    source: str = "processed",
    move_files: bool = False,
    max_candidates: int = None
) -> dict:
    """
    Create a new batch from processed resumes.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        batch_name: Name for the batch (auto-generated if None)
        source: Source folder for resumes
        move_files: Move files instead of copying
        max_candidates: Maximum candidates per batch

    Returns:
        Batch information
    """
    # Verify requisition
    req_config = get_requisition_config(client_code, req_id)

    # Auto-generate batch name if needed
    if not batch_name:
        date_str = datetime.now().strftime("%Y%m%d")
        existing_batches = req_config.get("batches_processed", [])
        today_batches = [b for b in existing_batches if date_str in b]
        batch_num = len(today_batches) + 1
        batch_name = f"batch_{date_str}_{batch_num}"

    # Set up paths
    source_path = get_resumes_path(client_code, req_id, source)
    batch_path = get_batch_path(client_code, req_id, batch_name)

    if batch_path.exists():
        raise ValueError(f"Batch already exists: {batch_name}")

    # Find resume files
    resume_files = list(source_path.glob("*.txt"))

    if not resume_files:
        raise ValueError(f"No processed resumes found in {source_path}")

    # Limit candidates if specified
    if max_candidates and len(resume_files) > max_candidates:
        resume_files = resume_files[:max_candidates]
        print(f"Limiting batch to {max_candidates} candidates")

    print(f"Creating batch: {batch_name}")
    print(f"  Source: {source_path}")
    print(f"  Destination: {batch_path}")
    print(f"  Resumes: {len(resume_files)}")

    # Create batch folder
    batch_path.mkdir(parents=True, exist_ok=True)

    # Copy/move files
    batch_files = []
    for resume_file in resume_files:
        dest_file = batch_path / resume_file.name

        if move_files:
            shutil.move(resume_file, dest_file)
            print(f"  Moved: {resume_file.name}")
        else:
            shutil.copy2(resume_file, dest_file)
            print(f"  Copied: {resume_file.name}")

        batch_files.append(resume_file.name)

    # Create batch manifest
    batch_info = {
        "batch_name": batch_name,
        "created_at": datetime.now().isoformat(),
        "requisition_id": req_id,
        "client_code": client_code,
        "source_folder": source,
        "file_count": len(batch_files),
        "files": batch_files,
        "status": "pending",  # pending, in_progress, completed
        "assessed_count": 0
    }

    manifest_path = batch_path / "batch_manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(batch_info, f, default_flow_style=False)

    # Update requisition config
    batches = req_config.get("batches_processed", [])
    if batch_name not in batches:
        batches.append(batch_name)
        req_config["batches_processed"] = batches
        save_requisition_config(client_code, req_id, req_config)

    print(f"\n✓ Batch created: {batch_name}")
    print(f"  Files: {len(batch_files)}")
    print(f"  Manifest: {manifest_path}")

    return batch_info


def list_batches(client_code: str, req_id: str) -> list[dict]:
    """List all batches for a requisition."""
    batches_path = get_resumes_path(client_code, req_id, "batches")

    if not batches_path.exists():
        return []

    batches = []
    for batch_dir in sorted(batches_path.iterdir()):
        if batch_dir.is_dir():
            manifest_path = batch_dir / "batch_manifest.yaml"
            if manifest_path.exists():
                with open(manifest_path, "r") as f:
                    batch_info = yaml.safe_load(f)
                batches.append(batch_info)

    return batches


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Create assessment batch")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--batch-name", "-b", help="Batch name (auto-generated if not specified)")
    parser.add_argument("--source", default="processed",
                       help="Source folder (default: processed)")
    parser.add_argument("--move", action="store_true",
                       help="Move files instead of copying")
    parser.add_argument("--max", type=int, help="Maximum candidates per batch")
    parser.add_argument("--list", action="store_true", help="List existing batches")
    args = parser.parse_args()

    try:
        if args.list:
            batches = list_batches(args.client, args.req)
            if not batches:
                print("No batches found")
            else:
                print(f"Batches for {args.req}:")
                print("-" * 60)
                for b in batches:
                    status = b.get("status", "unknown")
                    count = b.get("file_count", 0)
                    assessed = b.get("assessed_count", 0)
                    print(f"  {b['batch_name']}: {count} files, {assessed} assessed [{status}]")
        else:
            create_batch(
                client_code=args.client,
                req_id=args.req,
                batch_name=args.batch_name,
                source=args.source,
                move_files=args.move,
                max_candidates=args.max
            )
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
