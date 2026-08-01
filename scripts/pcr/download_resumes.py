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

# Force UTF-8 stdout/stderr so candidate names with non-latin-1 chars don't crash print()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from utils.pcr_client import PCRClient, PCRClientError
from utils.client_utils import (
    get_requisition_config,
    get_resumes_path,
    normalize_candidate_name,
    clean_pcr_name,
    create_batch_folder,
    list_all_extracted_resumes,
)

def download_resumes(
    client_code: str,
    req_id: str,
    overwrite: bool = False,
    candidate_ids: list[str] = None,
    auto_assess: bool = False
) -> dict:
    """
    Download resumes for candidates from PCR into a new batch folder.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        overwrite: Overwrite existing files
        candidate_ids: Specific candidate IDs to download (None = all)
        auto_assess: Automatically run AI assessments after download

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

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    candidates = manifest.get("candidates", [])
    if candidate_ids:
        id_set = {str(cid) for cid in candidate_ids}
        candidates = [c for c in candidates if str(c.get("CandidateId", "")) in id_set]

    print(f"Downloading resumes for {req_id}...")

    # ── Cross-batch dedup ─────────────────────────────────────────────────────
    # A resume is downloaded ONCE and lives in one batch folder. Without this,
    # every run created a fresh batch and re-copied everyone (runaway growth:
    # 1,700+ folders for ~40 candidates). Skip any candidate already on disk —
    # by PCR CandidateId (from prior batch download logs) or by name key.
    already_ids: set[str] = set()
    already_keys: set[str] = set()
    if not overwrite:
        batches_root = get_resumes_path(client_code, req_id, "batches")
        if batches_root.exists():
            for log in batches_root.glob("*/download_log.json"):
                try:
                    data = json.loads(log.read_text(encoding="utf-8"))
                    for f in data.get("stats", {}).get("files", []):
                        if f.get("candidate_id"):
                            already_ids.add(str(f["candidate_id"]))
                except Exception:
                    pass
        already_keys = {
            f.stem.replace("_resume", "")
            for f in list_all_extracted_resumes(client_code, req_id)
        }

    pending = []
    for c in candidates:
        cid = str(c.get("CandidateId", ""))
        first = (c.get("FirstName") or "").strip()
        last = (c.get("LastName") or "").strip()
        _, key = clean_pcr_name(first, last)
        if not key:
            key = normalize_candidate_name(f"{first} {last}".strip() or "unknown")
        if not overwrite and (cid in already_ids or key in already_keys):
            continue
        pending.append(c)

    print(f"  Candidates in manifest: {len(candidates)} | "
          f"already downloaded: {len(candidates) - len(pending)} | "
          f"to download: {len(pending)}")

    stats = {
        "total": len(pending),
        "downloaded": 0,
        "skipped": 0,
        "no_resume": 0,
        "errors": 0,
        "files": []
    }

    # Nothing new — do not create an empty batch folder
    if not pending:
        print("  No new resumes to download.")
        return stats

    candidates = pending

    # Create a batch folder only now that we have real work to do
    batch_dir = create_batch_folder(client_code, req_id)
    originals_dir = batch_dir / "originals"
    extracted_dir = batch_dir / "extracted"
    print(f"  Batch: {batch_dir.name}")

    # Connect to PCR
    client = PCRClient()
    client.ensure_authenticated()

    # Canonical norm per PCR CandidateId, taken from the existing DB row when present.
    # Using the DB row's name_normalized keeps the downloaded filename in lockstep with
    # the candidate record (and any prior manual correction), so assessment attaches to
    # the same row and no phantom duplicate is created.
    canonical_by_cid = {}
    try:
        from utils.database import get_db, _use_database
        if _use_database():
            for row in get_db().list_candidates(req_id):
                if row.get("pcr_candidate_id"):
                    canonical_by_cid[str(row["pcr_candidate_id"])] = (
                        row.get("name") or "", row["name_normalized"]
                    )
    except Exception:
        pass

    for candidate in candidates:
        cid = candidate.get("CandidateId")
        first = (candidate.get("FirstName") or "").strip()
        last  = (candidate.get("LastName")  or "").strip()
        canon = canonical_by_cid.get(str(cid))
        if canon and canon[1]:
            name, normalized_name = (canon[0] or canon[1].replace("_", " ").title()), canon[1]
        else:
            name, normalized_name = clean_pcr_name(first, last)
            if not name:
                raw = f"{first} {last}".strip()
                name = raw.title() if raw else "Unknown"
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

                # NOTE: the filename / name_normalized is deliberately NOT changed
                # from the canonical (DB / clean_pcr_name) key here. Renaming to a
                # resume-text-derived norm previously caused the file, DB row, and
                # assessment to diverge into phantom duplicate rows. Display-name
                # correction is a separate, DB-level concern keyed on CandidateId.
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

            # Update pipeline status in PCR so manual users see it's been processed.
            # Use PipelineInterviewId (the ActivityId used to GET the record) — this is
            # the correct identifier for PUT /PipelineInterviews/{id}. SendoutId is a
            # different PCR object and was causing silent 404s on every status update.
            pi_id = candidate.get("PipelineInterviewId") or candidate.get("SendoutId")
            if pi_id:
                try:
                    client.update_pipeline_interview(
                        sendout_id=str(pi_id),
                        status="Resume Reviewed"
                    )
                except PCRClientError as e:
                    print(f"    WARN: pipeline status update failed for {name}: {e}")

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
    with open(batch_dir / "batch_manifest.yaml", "w", encoding="utf-8") as f:
        yaml.dump(batch_manifest, f, default_flow_style=False, allow_unicode=True)

    # Save download log in batch
    log_file = batch_dir / "download_log.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump({
            "downloaded_at": datetime.now().isoformat(),
            "stats": stats
        }, f, indent=2, ensure_ascii=False)

    print("\nDownload Summary:")
    print(f"  Batch: {batch_dir.name}")
    print(f"  Downloaded: {stats['downloaded']}")
    print(f"  Skipped (existing): {stats['skipped']}")
    print(f"  No resume found: {stats['no_resume']}")
    print(f"  Errors: {stats['errors']}")

    # Auto-assess if enabled and we downloaded at least one resume
    if auto_assess and stats['downloaded'] > 0:
        try:
            from assess_candidate import assess_all_pending
            print(f"\nRunning auto-assessment for {req_id}...")
            result = assess_all_pending(
                client_code, req_id, use_ai=True, workers=4
            )
            assessed = result.get("assessed", 0)
            print(f"Auto-assessment complete: {assessed} candidates assessed")
            stats["auto_assessed"] = assessed
        except Exception as e:
            print(f"Auto-assessment error: {e}")
            stats["auto_assess_error"] = str(e)

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
    parser.add_argument("--auto-assess", action="store_true",
                       help="Automatically run AI assessments after download")
    args = parser.parse_args()

    try:
        download_resumes(
            client_code=args.client,
            req_id=args.req,
            overwrite=args.overwrite,
            candidate_ids=args.candidate_id,
            auto_assess=args.auto_assess
        )
    except (PCRClientError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
