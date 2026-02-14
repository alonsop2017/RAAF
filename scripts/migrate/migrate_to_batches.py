#!/usr/bin/env python3
"""
One-time migration script: move resumes from incoming/ + processed/
to the new batch-based folder structure.

For each requisition with existing incoming/ or processed/ folders:
1. Creates a batch folder using the earliest file date (YYYY-MM-DD-001)
2. Moves files from incoming/ -> batches/{name}/originals/
3. Moves files from processed/ -> batches/{name}/extracted/
4. Writes a batch_manifest.yaml
5. Removes empty incoming/ and processed/ dirs

Usage:
    python scripts/migrate/migrate_to_batches.py [--dry-run] [--client CODE] [--req REQ_ID]
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.client_utils import (
    list_clients, list_requisitions, get_requisition_root
)


def get_earliest_date(directory: Path) -> str:
    """Get the earliest file modification date in a directory as YYYY-MM-DD."""
    earliest = None
    if directory.exists():
        for f in directory.iterdir():
            if f.is_file():
                mtime = f.stat().st_mtime
                if earliest is None or mtime < earliest:
                    earliest = mtime
    if earliest:
        return datetime.fromtimestamp(earliest).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def migrate_requisition(client_code: str, req_id: str, dry_run: bool = False) -> dict:
    """Migrate a single requisition from incoming/processed to batch structure."""
    req_root = get_requisition_root(client_code, req_id)
    incoming_dir = req_root / "resumes" / "incoming"
    processed_dir = req_root / "resumes" / "processed"
    batches_dir = req_root / "resumes" / "batches"

    stats = {"moved_originals": 0, "moved_extracted": 0, "skipped": 0}

    # Check if there's anything to migrate
    has_incoming = incoming_dir.exists() and any(
        f for f in incoming_dir.iterdir()
        if f.is_file() and not f.name.endswith('.json')
    )
    has_processed = processed_dir.exists() and any(
        f for f in processed_dir.iterdir() if f.is_file()
    )

    if not has_incoming and not has_processed:
        print(f"  {client_code}/{req_id}: Nothing to migrate")
        return stats

    # Determine batch name from earliest file date
    date_str = get_earliest_date(incoming_dir) if has_incoming else get_earliest_date(processed_dir)
    batch_name = f"{date_str}-001"

    # Check if batch already exists
    batch_dir = batches_dir / batch_name
    if batch_dir.exists():
        print(f"  {client_code}/{req_id}: Batch {batch_name} already exists, skipping")
        stats["skipped"] = 1
        return stats

    print(f"  {client_code}/{req_id}: Migrating to batch {batch_name}")

    if dry_run:
        if has_incoming:
            count = sum(1 for f in incoming_dir.iterdir() if f.is_file() and not f.name.endswith('.json'))
            print(f"    Would move {count} files from incoming/ -> originals/")
            stats["moved_originals"] = count
        if has_processed:
            count = sum(1 for f in processed_dir.iterdir() if f.is_file())
            print(f"    Would move {count} files from processed/ -> extracted/")
            stats["moved_extracted"] = count
        return stats

    # Create batch structure
    originals_dir = batch_dir / "originals"
    extracted_dir = batch_dir / "extracted"
    originals_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    source_files = []

    # Move incoming files to originals/
    if has_incoming:
        for f in incoming_dir.iterdir():
            if f.is_file() and not f.name.endswith('.json'):
                dest = originals_dir / f.name
                shutil.move(str(f), str(dest))
                source_files.append(f.name)
                stats["moved_originals"] += 1
                print(f"    Moved original: {f.name}")

    # Move processed files to extracted/
    if has_processed:
        for f in processed_dir.iterdir():
            if f.is_file():
                dest = extracted_dir / f.name
                shutil.move(str(f), str(dest))
                stats["moved_extracted"] += 1
                print(f"    Moved extracted: {f.name}")

    # Write batch manifest
    manifest = {
        'created_at': datetime.now().isoformat(),
        'migrated_from': 'incoming_processed',
        'original_date': date_str,
        'file_count': stats["moved_originals"] + stats["moved_extracted"],
        'source_files': source_files,
        'status': 'migrated',
    }
    with open(batch_dir / "batch_manifest.yaml", 'w') as f:
        yaml.dump(manifest, f, default_flow_style=False)

    # Remove empty directories
    for d in [incoming_dir, processed_dir]:
        if d.exists() and not any(d.iterdir()):
            d.rmdir()
            print(f"    Removed empty: {d.name}/")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Migrate resumes to batch-based folder structure")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without moving files")
    parser.add_argument("--client", "-c", help="Migrate only this client")
    parser.add_argument("--req", "-r", help="Migrate only this requisition (requires --client)")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN - No files will be moved ===\n")

    total = {"moved_originals": 0, "moved_extracted": 0, "skipped": 0, "requisitions": 0}

    if args.client and args.req:
        clients_reqs = [(args.client, [args.req])]
    elif args.client:
        clients_reqs = [(args.client, list_requisitions(args.client))]
    else:
        clients_reqs = [(c, list_requisitions(c)) for c in list_clients()]

    for client_code, reqs in clients_reqs:
        print(f"\nClient: {client_code}")
        for req_id in reqs:
            stats = migrate_requisition(client_code, req_id, dry_run=args.dry_run)
            total["moved_originals"] += stats["moved_originals"]
            total["moved_extracted"] += stats["moved_extracted"]
            total["skipped"] += stats["skipped"]
            if stats["moved_originals"] or stats["moved_extracted"]:
                total["requisitions"] += 1

    print(f"\n{'=== DRY RUN ' if args.dry_run else ''}Migration Summary:")
    print(f"  Requisitions migrated: {total['requisitions']}")
    print(f"  Original files moved: {total['moved_originals']}")
    print(f"  Extracted files moved: {total['moved_extracted']}")
    if total["skipped"]:
        print(f"  Skipped (batch exists): {total['skipped']}")


if __name__ == "__main__":
    main()
