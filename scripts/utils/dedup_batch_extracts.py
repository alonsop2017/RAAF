"""
dedup_batch_extracts.py - Remove duplicate extracted resume files across batch folders.

Each candidate's .txt file should exist in exactly one batch (the earliest one).
Later batches that contain the same file are cleaned up.

Usage:
    # Dry run (default) - shows what would be removed
    python scripts/utils/dedup_batch_extracts.py --client efrat_europe --req REQ-2026-001-Sales_Dir_EMEA

    # Actually delete duplicates and update DB batch counts
    python scripts/utils/dedup_batch_extracts.py --client efrat_europe --req REQ-2026-001-Sales_Dir_EMEA --execute

    # Run across all requisitions for a client
    python scripts/utils/dedup_batch_extracts.py --client efrat_europe --all-reqs --execute
"""

import argparse
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def dedup_requisition(client_code: str, req_id: str, execute: bool) -> dict:
    """
    Scan batch extracted/ folders for a requisition, find duplicates, optionally remove them.
    Returns a summary dict.
    """
    from scripts.utils.client_utils import get_requisition_root

    req_root = get_requisition_root(client_code, req_id)
    batches_dir = req_root / "resumes" / "batches"

    if not batches_dir.exists():
        return {"error": f"Batches dir not found: {batches_dir}"}

    # Sort chronologically — folder names are date-prefixed so lexical = time order
    batch_dirs = sorted([d for d in batches_dir.iterdir() if d.is_dir()])

    seen: dict[str, str] = {}        # name_normalized -> first batch name
    duplicates: list[Path] = []
    batch_counts: dict[str, int] = {}  # batch_name -> unique file count after dedup

    for batch_dir in batch_dirs:
        extracted = batch_dir / "extracted"
        if not extracted.exists():
            batch_counts[batch_dir.name] = 0
            continue

        unique_in_batch = 0
        for txt_file in sorted(extracted.glob("*.txt")):
            name = txt_file.stem.replace("_resume", "")
            if name in seen:
                duplicates.append(txt_file)
            else:
                seen[name] = batch_dir.name
                unique_in_batch += 1

        batch_counts[batch_dir.name] = unique_in_batch

    summary = {
        "req_id": req_id,
        "client_code": client_code,
        "unique_candidates": len(seen),
        "total_files_before": len(seen) + len(duplicates),
        "duplicates_found": len(duplicates),
        "batches_affected": len(set(f.parent.parent.name for f in duplicates)),
        "execute": execute,
        "deleted": 0,
        "errors": [],
    }

    if not duplicates:
        print(f"  {req_id}: no duplicates found ({len(seen)} unique candidates across {len(batch_dirs)} batches)")
        return summary

    print(f"\n  {req_id}: {len(seen)} unique candidates, {len(duplicates)} duplicate files to remove")
    print(f"  Batches affected: {summary['batches_affected']} of {len(batch_dirs)}")

    # Show duplicates grouped by batch
    by_batch: dict[str, list[str]] = {}
    for f in duplicates:
        batch_name = f.parent.parent.name
        by_batch.setdefault(batch_name, []).append(f.name)

    print("\n  Duplicates by batch:")
    for batch_name in sorted(by_batch):
        first_seen_examples = [
            f"  {name.replace('_resume.txt','')} (first in: {seen[name.replace('_resume.txt','')]})"
            for name in by_batch[batch_name][:3]
        ]
        suffix = f" ... and {len(by_batch[batch_name]) - 3} more" if len(by_batch[batch_name]) > 3 else ""
        print(f"    {batch_name}: {len(by_batch[batch_name])} files{suffix}")

    if not execute:
        print("\n  [DRY RUN] No files deleted. Re-run with --execute to apply.")
        return summary

    # Delete duplicates
    print("\n  Deleting duplicates...")
    for f in duplicates:
        try:
            f.unlink()
            summary["deleted"] += 1
        except Exception as e:
            summary["errors"].append(str(e))

    print(f"  Deleted {summary['deleted']} files ({len(summary['errors'])} errors)")

    # Update DB batch counts
    try:
        import os
        os.environ.setdefault("RAAF_DB_MODE", "db")
        from scripts.utils.database import get_db, _use_database
        if _use_database():
            db = get_db()
            updated = 0
            for batch_name, count in batch_counts.items():
                with db._conn() as conn:
                    conn.execute(
                        "UPDATE batches SET candidate_count=? WHERE batch_name=? AND requisition_id="
                        "(SELECT id FROM requisitions WHERE req_id=?)",
                        (count, batch_name, req_id)
                    )
                updated += 1
            print(f"  Updated candidate_count for {updated} batches in DB")
    except Exception as e:
        summary["errors"].append(f"DB update failed: {e}")
        print(f"  WARNING: DB update failed: {e}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Remove duplicate extracted resume files from batch folders")
    parser.add_argument("--client", required=True, help="Client code (e.g. efrat_europe)")
    parser.add_argument("--req", help="Requisition ID (e.g. REQ-2026-001-Sales_Dir_EMEA)")
    parser.add_argument("--all-reqs", action="store_true", help="Run across all requisitions for the client")
    parser.add_argument("--execute", action="store_true", help="Actually delete duplicates (default is dry run)")
    args = parser.parse_args()

    if not args.req and not args.all_reqs:
        parser.error("Specify --req <REQ_ID> or --all-reqs")

    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"=== Batch Extract Deduplication [{mode}] ===\n")

    req_ids = []
    if args.all_reqs:
        from pathlib import Path as P
        client_reqs = P(f"clients/{args.client}/requisitions")
        if not client_reqs.exists():
            print(f"ERROR: {client_reqs} not found")
            sys.exit(1)
        req_ids = [d.name for d in sorted(client_reqs.iterdir()) if d.is_dir()]
    else:
        req_ids = [args.req]

    total_dupes = 0
    total_deleted = 0
    for req_id in req_ids:
        result = dedup_requisition(args.client, req_id, execute=args.execute)
        total_dupes += result.get("duplicates_found", 0)
        total_deleted += result.get("deleted", 0)

    print(f"\n=== Summary ===")
    print(f"  Total duplicates found:  {total_dupes}")
    if args.execute:
        print(f"  Total files deleted:     {total_deleted}")
    else:
        print(f"  Re-run with --execute to delete.")


if __name__ == "__main__":
    main()
