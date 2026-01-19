#!/usr/bin/env python3
"""
Resume text extraction script.
Extracts text from PDF and DOCX resumes for processing.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    get_resumes_path,
    get_requisition_config,
    normalize_candidate_name
)
from utils.pdf_reader import extract_text as extract_pdf, clean_extracted_text
from utils.docx_reader import extract_text as extract_docx


def extract_resumes(
    client_code: str,
    req_id: str,
    input_folder: str = "incoming",
    output_folder: str = "processed",
    overwrite: bool = False
) -> dict:
    """
    Extract text from resumes in a requisition folder.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        input_folder: Source folder (incoming, batches/batch_name)
        output_folder: Destination folder for extracted text
        overwrite: Overwrite existing extractions

    Returns:
        Extraction statistics
    """
    # Verify requisition exists
    req_config = get_requisition_config(client_code, req_id)

    # Set up paths
    if "/" in input_folder:
        # Handle batch path like "batches/batch_20251226_1"
        input_path = get_resumes_path(client_code, req_id, "batches").parent / input_folder
    else:
        input_path = get_resumes_path(client_code, req_id, input_folder)

    output_path = get_resumes_path(client_code, req_id, output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Extracting resumes for {req_id}")
    print(f"  Input: {input_path}")
    print(f"  Output: {output_path}")

    # Find resume files
    resume_files = []
    for ext in ["*.pdf", "*.PDF", "*.docx", "*.DOCX", "*.doc"]:
        resume_files.extend(input_path.glob(ext))

    print(f"  Found {len(resume_files)} resume files")

    stats = {
        "total": len(resume_files),
        "extracted": 0,
        "skipped": 0,
        "errors": 0,
        "files": []
    }

    for resume_file in resume_files:
        print(f"\n  Processing: {resume_file.name}")

        # Determine output filename
        base_name = resume_file.stem
        output_file = output_path / f"{base_name}.txt"

        # Check if already extracted
        if output_file.exists() and not overwrite:
            print(f"    Skipped (exists)")
            stats["skipped"] += 1
            continue

        try:
            # Extract based on file type
            suffix = resume_file.suffix.lower()

            if suffix == ".pdf":
                text = extract_pdf(resume_file)
            elif suffix in [".docx", ".doc"]:
                text = extract_docx(resume_file)
            else:
                print(f"    Unsupported format: {suffix}")
                stats["errors"] += 1
                continue

            # Clean the extracted text
            text = clean_extracted_text(text)

            if not text.strip():
                print(f"    Warning: No text extracted")
                stats["errors"] += 1
                continue

            # Add metadata header
            header = f"""# Extracted Resume
# Source: {resume_file.name}
# Extracted: {datetime.now().isoformat()}
# Requisition: {req_id}

---

"""
            text = header + text

            # Save extracted text
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(text)

            word_count = len(text.split())
            print(f"    Extracted: {word_count} words -> {output_file.name}")

            stats["extracted"] += 1
            stats["files"].append({
                "source": resume_file.name,
                "output": output_file.name,
                "words": word_count
            })

        except ImportError as e:
            print(f"    Error: Missing library - {e}")
            stats["errors"] += 1
        except Exception as e:
            print(f"    Error: {e}")
            stats["errors"] += 1

    # Save extraction log
    log_file = output_path / "extraction_log.json"
    with open(log_file, "w") as f:
        json.dump({
            "extracted_at": datetime.now().isoformat(),
            "input_folder": str(input_path),
            "stats": stats
        }, f, indent=2)

    print(f"\n--- Extraction Summary ---")
    print(f"  Extracted: {stats['extracted']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")

    return stats


def extract_single_resume(resume_path: str | Path) -> str:
    """
    Extract text from a single resume file.

    Args:
        resume_path: Path to resume file

    Returns:
        Extracted text
    """
    resume_path = Path(resume_path)

    if not resume_path.exists():
        raise FileNotFoundError(f"Resume not found: {resume_path}")

    suffix = resume_path.suffix.lower()

    if suffix == ".pdf":
        text = extract_pdf(resume_path)
    elif suffix in [".docx", ".doc"]:
        text = extract_docx(resume_path)
    else:
        raise ValueError(f"Unsupported format: {suffix}")

    return clean_extracted_text(text)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract text from resumes")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--input", "-i", default="incoming",
                       help="Input folder (default: incoming)")
    parser.add_argument("--output", "-o", default="processed",
                       help="Output folder (default: processed)")
    parser.add_argument("--overwrite", action="store_true",
                       help="Overwrite existing extractions")
    parser.add_argument("--single", help="Extract single file and print to stdout")
    args = parser.parse_args()

    if args.single:
        try:
            text = extract_single_resume(args.single)
            print(text)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            extract_resumes(
                client_code=args.client,
                req_id=args.req,
                input_folder=args.input,
                output_folder=args.output,
                overwrite=args.overwrite
            )
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
