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
    normalize_candidate_name,
    create_batch_folder,
)


def download_resumes(
    client_code: str,
    req_id: str,
    overwrite: bool = False,
    candidate_ids: list[str] = None
) -> dict:
    """
    Download resumes for candidates from PCR into a new batch folder.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        overwrite: Overwrite existing files
        candidate_ids: Specific candidate IDs to download (None = all)

    Returns:
        Dictionary with download statistics
    """
    import yaml

    # Load candidates manifest - check both legacy and new locations
    req_root = get_resumes_path(client_code, req_id, "batches").parent
    manifest_file = None
    for loc in [
        req_root / "incoming" / "candidates_manifest.json",
        req_root / "candidates_manifest.json",
    ]:
        if loc.exists():
            manifest_file = loc
            break

    if not manifest_file:
        raise FileNotFoundError(
            f"Candidates manifest not found. Run sync_candidates first.\n"
            f"Expected: {req_root / 'incoming' / 'candidates_manifest.json'}"
        )

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    candidates = manifest.get("candidates", [])
    if candidate_ids:
        candidates = [c for c in candidates if c.get("CandidateId") in candidate_ids]

    print(f"Downloading resumes for {req_id}...")
    print(f"  Candidates to process: {len(candidates)}")

    # Create a new batch folder for this PCR download
    batch_dir = create_batch_folder(client_code, req_id)
    originals_dir = batch_dir / "originals"
    extracted_dir = batch_dir / "extracted"

    print(f"  Batch: {batch_dir.name}")

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

            # Output filename - save to originals/
            output_filename = f"{normalized_name}{ext}"
            output_path = originals_dir / output_filename

            # Check if already exists
            if output_path.exists() and not overwrite:
                print(f"    Skipped (exists): {output_filename}")
                stats["skipped"] += 1
                continue

            # Download document
            doc_id = resume_doc.get("DocumentId")
            content = client.download_document(cid, doc_id)

            # Save original file
            with open(output_path, "wb") as f:
                f.write(content)

            # Extract text to extracted/
            extracted_path = extracted_dir / f"{normalized_name}_resume.txt"
            try:
                if ext.lower() == ".pdf":
                    from utils.pdf_reader import extract_text as extract_pdf_text
                    text = extract_pdf_text(str(output_path))
                elif ext.lower() == ".docx":
                    from utils.docx_reader import extract_text as extract_docx_text
                    text = extract_docx_text(str(output_path))
                else:
                    text = content.decode('utf-8', errors='ignore')

                header = f"""# Extracted Resume
# Source: {filename} (PCR download)
# Candidate ID: {cid}
# Batch: {batch_dir.name}
# Extracted: {datetime.now().strftime('%Y-%m-%d')}

---

"""
                with open(extracted_path, 'w', encoding='utf-8') as f:
                    f.write(header + text)
            except Exception as e:
                with open(extracted_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Extraction failed: {str(e)}\n")

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

    # Write batch manifest
    batch_manifest = {
        'created_at': datetime.now().isoformat(),
        'file_count': stats['downloaded'],
        'source': 'pcr',
        'source_files': [f['filename'] for f in stats['files']],
        'status': 'uploaded',
    }
    with open(batch_dir / "batch_manifest.yaml", "w") as f:
        yaml.dump(batch_manifest, f, default_flow_style=False)

    # Save download log in batch
    log_file = batch_dir / "download_log.json"
    with open(log_file, "w") as f:
        json.dump({
            "downloaded_at": datetime.now().isoformat(),
            "stats": stats
        }, f, indent=2)

    print("\nDownload Summary:")
    print(f"  Batch: {batch_dir.name}")
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
