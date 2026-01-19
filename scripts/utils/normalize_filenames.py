#!/usr/bin/env python3
"""
Normalize resume filenames.
Converts resume filenames to lastname_firstname format.
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.client_utils import get_resumes_path


def normalize_name(filename: str) -> str:
    """
    Normalize a filename to lastname_firstname format.

    Args:
        filename: Original filename

    Returns:
        Normalized filename
    """
    # Remove extension
    stem = Path(filename).stem
    ext = Path(filename).suffix.lower()

    # Remove common suffixes
    for suffix in ["_resume", "_cv", "-resume", "-cv", " resume", " cv"]:
        stem = stem.replace(suffix, "").replace(suffix.upper(), "").replace(suffix.title(), "")

    # Clean up the name
    name = stem.strip()

    # Replace common separators with space
    name = re.sub(r'[-_.]', ' ', name)

    # Remove extra whitespace
    name = ' '.join(name.split())

    # Split into parts
    parts = name.split()

    if len(parts) < 2:
        # Can't determine first/last, just lowercase and replace spaces
        normalized = name.lower().replace(' ', '_')
    else:
        # Assume last word is last name
        last_name = parts[-1].lower()
        first_name = '_'.join(p.lower() for p in parts[:-1])

        # Remove non-alphanumeric characters except underscore
        last_name = re.sub(r'[^a-z]', '', last_name)
        first_name = re.sub(r'[^a-z_]', '', first_name)

        normalized = f"{last_name}_{first_name}"

    return f"{normalized}_resume{ext}"


def normalize_filenames(
    client_code: str,
    req_id: str,
    folder: str = "incoming",
    dry_run: bool = False
) -> dict:
    """
    Normalize all resume filenames in a folder.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        folder: Folder to process
        dry_run: Show changes without renaming

    Returns:
        Statistics about renamed files
    """
    folder_path = get_resumes_path(client_code, req_id, folder)

    if not folder_path.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    print(f"Normalizing filenames in: {folder_path}")
    if dry_run:
        print("  DRY RUN - no changes will be made")

    stats = {
        "total": 0,
        "renamed": 0,
        "skipped": 0,
        "conflicts": 0,
        "changes": []
    }

    # Find resume files
    resume_files = []
    for ext in ["*.pdf", "*.PDF", "*.docx", "*.DOCX", "*.doc", "*.DOC"]:
        resume_files.extend(folder_path.glob(ext))

    stats["total"] = len(resume_files)

    for resume_file in resume_files:
        original_name = resume_file.name
        normalized_name = normalize_name(original_name)

        if original_name == normalized_name:
            stats["skipped"] += 1
            continue

        new_path = folder_path / normalized_name

        # Handle conflicts
        if new_path.exists() and new_path != resume_file:
            # Add number suffix
            counter = 1
            stem = Path(normalized_name).stem
            ext = Path(normalized_name).suffix
            while new_path.exists():
                new_path = folder_path / f"{stem}_{counter}{ext}"
                counter += 1
            normalized_name = new_path.name
            stats["conflicts"] += 1

        print(f"  {original_name}")
        print(f"    → {normalized_name}")

        stats["changes"].append({
            "original": original_name,
            "normalized": normalized_name
        })

        if not dry_run:
            resume_file.rename(new_path)
            stats["renamed"] += 1

    print(f"\n--- Summary ---")
    print(f"  Total files: {stats['total']}")
    print(f"  Renamed: {stats['renamed'] if not dry_run else len(stats['changes'])}")
    print(f"  Skipped (already normalized): {stats['skipped']}")
    if stats["conflicts"] > 0:
        print(f"  Conflicts resolved: {stats['conflicts']}")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Normalize resume filenames")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--folder", "-f", default="incoming",
                       help="Folder to process (default: incoming)")
    parser.add_argument("--dry-run", "-n", action="store_true",
                       help="Show changes without renaming")
    args = parser.parse_args()

    try:
        normalize_filenames(
            client_code=args.client,
            req_id=args.req,
            folder=args.folder,
            dry_run=args.dry_run
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
