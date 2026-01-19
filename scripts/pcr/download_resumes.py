#!/usr/bin/env python3
"""
Download resumes from PCRecruiter.
Downloads resume documents for candidates in a requisition's pipeline.
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.pcr_client import PCRClient, PCRClientError
from utils.client_utils import (
    get_requisition_config,
    get_resumes_path,
    normalize_candidate_name
)


def download_resumes(
    client_code: str,
    req_id: str,
    overwrite: bool = False,
    candidate_ids: list[str] = None
) -> dict:
    """
    Download resumes for candidates from PCR.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        overwrite: Overwrite existing files
        candidate_ids: Specific candidate IDs to download (None = all)

    Returns:
        Dictionary with download statistics
    """
    # Load candidates manifest
    incoming_path = get_resumes_path(client_code, req_id, "incoming")
    manifest_file = incoming_path / "candidates_manifest.json"

    if not manifest_file.exists():
        raise FileNotFoundError(
            f"Candidates manifest not found. Run sync_candidates first.\n"
            f"Expected: {manifest_file}"
        )

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    candidates = manifest.get("candidates", [])
    if candidate_ids:
        candidates = [c for c in candidates if c.get("CandidateId") in candidate_ids]

    print(f"Downloading resumes for {req_id}...")
    print(f"  Candidates to process: {len(candidates)}")

    # Connect to PCR
    client = PCRClient()
    client.ensure_authenticated()

    stats = {
        "total": len(candidates),
        "downloaded": 0,
        "skipped": 0,
        "no_resume": 0,
        "errors": 0,
        "files": []
    }

    for candidate in candidates:
        cid = candidate.get("CandidateId")
        name = f"{candidate.get('FirstName', '')} {candidate.get('LastName', '')}".strip()
        normalized_name = normalize_candidate_name(name)

        print(f"  Processing: {name} ({cid})...")

        try:
            # Get candidate documents
            documents = client.get_candidate_documents(cid)

            # Find resume document
            resume_doc = None
            for doc in documents:
                doc_type = doc.get("DocumentType", "").lower()
                doc_name = doc.get("FileName", "").lower()

                if "resume" in doc_type or "resume" in doc_name or "cv" in doc_name:
                    resume_doc = doc
                    break

            # If no resume found, try first document
            if not resume_doc and documents:
                resume_doc = documents[0]

            if not resume_doc:
                print(f"    No resume found")
                stats["no_resume"] += 1
                continue

            # Determine file extension
            filename = resume_doc.get("FileName", "resume.pdf")
            ext = Path(filename).suffix or ".pdf"

            # Output filename
            output_filename = f"{normalized_name}_resume{ext}"
            output_path = incoming_path / output_filename

            # Check if already exists
            if output_path.exists() and not overwrite:
                print(f"    Skipped (exists): {output_filename}")
                stats["skipped"] += 1
                continue

            # Download document
            doc_id = resume_doc.get("DocumentId")
            content = client.download_document(cid, doc_id)

            # Save file
            with open(output_path, "wb") as f:
                f.write(content)

            print(f"    Downloaded: {output_filename}")
            stats["downloaded"] += 1
            stats["files"].append({
                "candidate_id": cid,
                "candidate_name": name,
                "filename": output_filename,
                "source": filename
            })

        except PCRClientError as e:
            print(f"    Error: {e}")
            stats["errors"] += 1

    # Save download log
    log_file = incoming_path / "download_log.json"
    with open(log_file, "w") as f:
        json.dump({
            "downloaded_at": datetime.now().isoformat(),
            "stats": stats
        }, f, indent=2)

    print("\nDownload Summary:")
    print(f"  Downloaded: {stats['downloaded']}")
    print(f"  Skipped (existing): {stats['skipped']}")
    print(f"  No resume found: {stats['no_resume']}")
    print(f"  Errors: {stats['errors']}")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Download resumes from PCRecruiter")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--overwrite", action="store_true",
                       help="Overwrite existing files")
    parser.add_argument("--candidate-id", action="append",
                       help="Specific candidate ID(s) to download")
    args = parser.parse_args()

    try:
        download_resumes(
            client_code=args.client,
            req_id=args.req,
            overwrite=args.overwrite,
            candidate_ids=args.candidate_id
        )
    except (PCRClientError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
