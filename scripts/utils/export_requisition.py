#!/usr/bin/env python3
"""
Export requisition data for backup or transfer.
Creates a ZIP archive of a requisition.
"""

import sys
import zipfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.client_utils import get_requisition_root, get_project_root


def export_requisition(
    client_code: str,
    req_id: str,
    output_path: str = None,
    include_resumes: bool = True
) -> str:
    """
    Export a requisition to a ZIP archive.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        output_path: Output file path (auto-generated if None)
        include_resumes: Include resume files in export

    Returns:
        Path to created ZIP file
    """
    req_root = get_requisition_root(client_code, req_id)

    if not req_root.exists():
        raise FileNotFoundError(f"Requisition not found: {req_id}")

    # Generate output path if not specified
    if output_path is None:
        date_str = datetime.now().strftime("%Y%m%d")
        output_path = get_project_root() / f"{req_id}_export_{date_str}.zip"
    else:
        output_path = Path(output_path)

    print(f"Exporting requisition: {req_id}")
    print(f"  Source: {req_root}")
    print(f"  Output: {output_path}")
    if not include_resumes:
        print("  Note: Excluding resume files")

    # Create ZIP archive
    file_count = 0
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in req_root.rglob("*"):
            if file_path.is_file():
                # Skip resume files if requested
                if not include_resumes:
                    relative = file_path.relative_to(req_root)
                    if "resumes" in str(relative):
                        continue

                # Add file to archive
                arc_name = file_path.relative_to(req_root.parent)
                zf.write(file_path, arc_name)
                file_count += 1

    # Get file size
    size_mb = output_path.stat().st_size / (1024 * 1024)

    print(f"\n✓ Export complete!")
    print(f"  Files: {file_count}")
    print(f"  Size: {size_mb:.2f} MB")
    print(f"  Location: {output_path}")

    return str(output_path)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Export requisition to ZIP")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--no-resumes", action="store_true",
                       help="Exclude resume files from export")
    args = parser.parse_args()

    try:
        export_requisition(
            client_code=args.client,
            req_id=args.req,
            output_path=args.output,
            include_resumes=not args.no_resumes
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
