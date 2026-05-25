#!/usr/bin/env python3
"""
Watch for new Indeed applicants in PCRecruiter.
Continuously monitors for new candidates and optionally downloads resumes.
"""

import sys
import time
import json
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

# Force UTF-8 stdout/stderr so candidate names with non-latin-1 chars don't crash print()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from utils.pcr_client import PCRClient, PCRClientError
from utils.client_utils import (
    get_requisition_config,
    save_requisition_config,
    get_resumes_path,
    list_clients,
    list_requisitions
)


def watch_applicants(
    client_code: str = None,
    req_id: str = None,
    interval: int = 15,
    auto_download: bool = False,
    auto_assess: bool = False,
    once: bool = False
):
    """
    Watch for new applicants across requisitions.

    Args:
        client_code: Specific client to watch (None = all)
        req_id: Specific requisition to watch (None = all active)
        interval: Check interval in minutes
        auto_download: Automatically download new resumes
        auto_assess: Automatically run AI assessments after download
        once: Run once and exit (don't loop)
    """
    print("Starting applicant watcher...")
    print(f"  Check interval: {interval} minutes")
    if client_code:
        print(f"  Client filter: {client_code}")
    if req_id:
        print(f"  Requisition filter: {req_id}")
    print(f"  Auto-download resumes: {auto_download}")
    print(f"  Auto-assess candidates: {auto_assess}")
    print("-" * 50)

    client = PCRClient()

    while True:
        try:
            client.ensure_authenticated()
            check_time = datetime.now()
            print(f"\n[{check_time.strftime('%Y-%m-%d %H:%M:%S')}] Checking for new applicants...")

            # Build list of requisitions to check
            reqs_to_check = []

            if client_code and req_id:
                reqs_to_check = [(client_code, req_id)]
            elif client_code:
                for r in list_requisitions(client_code, status="active"):
                    reqs_to_check.append((client_code, r))
            else:
                for c in list_clients():
                    for r in list_requisitions(c, status="active"):
                        reqs_to_check.append((c, r))

            total_new = 0

            for cc, rid in reqs_to_check:
                try:
                    new_count = check_requisition(client, cc, rid, auto_download, auto_assess)
                    total_new += new_count
                except Exception as e:
                    print(f"  Error checking {cc}/{rid}: {e}")

            if total_new > 0:
                print(f"\n  Total new applicants found: {total_new}")
            else:
                print(f"  No new applicants")

            if once:
                break

            print(f"\nNext check in {interval} minutes...")
            time.sleep(interval * 60)

        except KeyboardInterrupt:
            print("\n\nStopping watcher...")
            break
        except PCRClientError as e:
            print(f"\nPCR Error: {e}")
            print(f"Retrying in {interval} minutes...")
            if once:
                break
            time.sleep(interval * 60)


def check_requisition(
    client: PCRClient,
    client_code: str,
    req_id: str,
    auto_download: bool,
    auto_assess: bool = False
) -> int:
    """
    Check a single requisition for new applicants.

    Returns:
        Number of new applicants found
    """
    try:
        req_config = get_requisition_config(client_code, req_id)
    except FileNotFoundError:
        return 0

    pcr_config = req_config.get("pcr_integration", {})

    # Support multi-position linking: collect all position IDs
    position_ids = []
    positions_list = pcr_config.get("positions", [])
    if positions_list:
        position_ids = [str(p.get("job_id")) for p in positions_list if p.get("job_id")]
    elif pcr_config.get("job_id"):
        # Legacy single-position format
        position_ids = [str(pcr_config["job_id"])]

    if not position_ids:
        return 0

    last_sync = pcr_config.get("last_sync")
    last_sync_dt = None
    if last_sync:
        try:
            last_sync_dt = datetime.fromisoformat(last_sync)
        except ValueError:
            pass

    # Get candidates from all linked positions
    all_candidates = []
    seen_ids = set()
    for position_id in position_ids:
        try:
            candidates = client.get_position_candidates(position_id)
            for c in candidates:
                cid = c.get("CandidateId")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_candidates.append(c)
        except Exception as e:
            print(f"    Error fetching candidates for position {position_id}: {e}")

    # Filter to new candidates
    new_candidates = []
    for c in all_candidates:
        date_added = c.get("DateAdded")
        if date_added and last_sync_dt:
            try:
                added_dt = datetime.fromisoformat(date_added.replace("Z", "+00:00"))
                if added_dt.replace(tzinfo=None) > last_sync_dt:
                    new_candidates.append(c)
            except ValueError:
                pass
        elif not last_sync_dt:
            # First sync - all are "new"
            new_candidates.append(c)

    if new_candidates:
        print(f"  {client_code}/{req_id}: {len(new_candidates)} new applicant(s)")
        for c in new_candidates:
            name = f"{c.get('FirstName', '')} {c.get('LastName', '')}"
            print(f"    - {name}")

        # Update manifest
        incoming_path = get_resumes_path(client_code, req_id, "incoming")
        incoming_path.mkdir(parents=True, exist_ok=True)

        manifest_file = incoming_path / "candidates_manifest.json"
        if manifest_file.exists():
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            existing_ids = {c.get("CandidateId") for c in manifest.get("candidates", [])}
            for c in new_candidates:
                if c.get("CandidateId") not in existing_ids:
                    manifest["candidates"].append(c)
        else:
            manifest = {
                "synced_at": datetime.now().isoformat(),
                "position_ids": position_ids,
                "candidates": new_candidates
            }

        manifest["synced_at"] = datetime.now().isoformat()
        manifest["count"] = len(manifest.get("candidates", []))

        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=str, ensure_ascii=False)

        # Update last sync
        pcr_config["last_sync"] = datetime.now().isoformat()
        req_config["pcr_integration"] = pcr_config
        save_requisition_config(client_code, req_id, req_config)

        # Auto-download if enabled
        if auto_download:
            from download_resumes import download_resumes
            new_ids = [c.get("CandidateId") for c in new_candidates]
            download_resumes(client_code, req_id, candidate_ids=new_ids)

            # Auto-assess if enabled (requires download to have run first)
            if auto_assess:
                try:
                    sys.path.insert(0, str(Path(__file__).parent.parent))
                    from assess_candidate import assess_all_pending
                    print(f"  Running auto-assessment for {client_code}/{req_id}...")
                    result = assess_all_pending(
                        client_code, req_id, use_ai=True, workers=4
                    )
                    assessed = result.get("assessed", 0)
                    print(f"  Auto-assessment complete: {assessed} candidates assessed")
                except Exception as e:
                    print(f"  Auto-assessment error: {e}")

    # Catch OLI→RR status transitions: candidates already in the manifest who were
    # previously "On-Line Job Inquiry" (no resume) and are now "Resume Reviewed"
    # but have an empty or missing extracted file.
    if auto_download:
        try:
            from scripts.utils.client_utils import (
                get_resumes_path, normalize_candidate_name, list_all_extracted_resumes
            )
            existing_keys = {
                f.stem.replace("_resume", "")
                for f in list_all_extracted_resumes(client_code, req_id)
            }
            new_ids_set = {str(c.get("CandidateId", "")) for c in new_candidates}
            rr_candidates = [
                c for c in all_candidates
                if c.get("PipelineStatus") == "Resume Reviewed"
                and str(c.get("CandidateId", "")) not in new_ids_set
            ]
            needs_redownload = []
            batches_base = get_resumes_path(client_code, req_id, "batches").parent / "resumes" / "batches"
            for c in rr_candidates:
                first = (c.get("FirstName") or "").strip()
                last = (c.get("LastName") or "").strip()
                key = normalize_candidate_name(f"{first} {last}")
                if key not in existing_keys:
                    needs_redownload.append(c)
                    continue
                # Check if the extracted file is effectively empty
                for txt in batches_base.glob(f"*/extracted/{key}_resume.txt"):
                    body = txt.read_text(errors="replace").split("---\n", 1)[-1].strip()
                    if len(body) < 300:
                        needs_redownload.append(c)
                    break
            if needs_redownload:
                print(f"  {client_code}/{req_id}: {len(needs_redownload)} Resume Reviewed "
                      f"candidate(s) with missing/empty resume — re-downloading")
                for c in needs_redownload:
                    print(f"    - {c.get('FirstName','')} {c.get('LastName','')}")
                from download_resumes import download_resumes
                redownload_ids = [str(c.get("CandidateId")) for c in needs_redownload]
                download_resumes(client_code, req_id, candidate_ids=redownload_ids,
                                 overwrite=True)
                if auto_assess:
                    try:
                        from assess_candidate import assess_all_pending
                        result = assess_all_pending(client_code, req_id, use_ai=True, workers=4)
                        assessed = result.get("assessed", 0)
                        if assessed:
                            print(f"  Auto-assessment complete: {assessed} candidates assessed")
                    except Exception as e:
                        print(f"  Auto-assessment error: {e}")
        except Exception as e:
            print(f"  OLI→RR re-download check error: {e}")

    # Always catch pending DB candidates with no resume on disk —
    # covers the case where sync_candidates ran before watch_applicants
    # and set last_sync, making those candidates invisible to the date filter.
    if auto_download:
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from scripts.utils.database import get_db, _use_database
            if _use_database():
                pending = get_db().list_candidates(req_id, status="pending")
                missing = [
                    c for c in pending
                    if c.get("pcr_candidate_id")
                    and (
                        not c.get("resume_extracted_path")
                        or not Path(c["resume_extracted_path"]).exists()
                    )
                ]
                if missing:
                    missing_ids = [c["pcr_candidate_id"] for c in missing]
                    print(f"  {client_code}/{req_id}: downloading resumes for "
                          f"{len(missing)} pending candidate(s) with no resume")
                    from download_resumes import download_resumes
                    download_resumes(client_code, req_id, candidate_ids=missing_ids)
                    if auto_assess:
                        try:
                            from assess_candidate import assess_all_pending
                            result = assess_all_pending(
                                client_code, req_id, use_ai=True, workers=4
                            )
                            assessed = result.get("assessed", 0)
                            if assessed:
                                print(f"  Auto-assessment complete: {assessed} candidates assessed")
                        except Exception as e:
                            print(f"  Auto-assessment error: {e}")
        except Exception as e:
            print(f"  Resume catchup check error: {e}")

    return len(new_candidates)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Watch for new Indeed applicants")
    parser.add_argument("--client", "-c", help="Specific client to watch")
    parser.add_argument("--req", "-r", help="Specific requisition to watch")
    parser.add_argument("--interval", type=int, default=15,
                       help="Check interval in minutes (default: 15)")
    parser.add_argument("--auto-download", action="store_true",
                       help="Automatically download new resumes")
    parser.add_argument("--auto-assess", action="store_true",
                       help="Automatically run AI assessments after download")
    parser.add_argument("--once", action="store_true",
                       help="Run once and exit")
    args = parser.parse_args()

    watch_applicants(
        client_code=args.client,
        req_id=args.req,
        interval=args.interval,
        auto_download=args.auto_download,
        auto_assess=args.auto_assess,
        once=args.once
    )


if __name__ == "__main__":
    main()
