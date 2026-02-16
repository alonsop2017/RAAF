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
    once: bool = False
):
    """
    Watch for new applicants across requisitions.

    Args:
        client_code: Specific client to watch (None = all)
        req_id: Specific requisition to watch (None = all active)
        interval: Check interval in minutes
        auto_download: Automatically download new resumes
        once: Run once and exit (don't loop)
    """
    print("Starting applicant watcher...")
    print(f"  Check interval: {interval} minutes")
    if client_code:
        print(f"  Client filter: {client_code}")
    if req_id:
        print(f"  Requisition filter: {req_id}")
    print(f"  Auto-download resumes: {auto_download}")
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
                    new_count = check_requisition(client, cc, rid, auto_download)
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
    auto_download: bool
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
            with open(manifest_file, "r") as f:
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

        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2, default=str)

        # Update last sync
        pcr_config["last_sync"] = datetime.now().isoformat()
        req_config["pcr_integration"] = pcr_config
        save_requisition_config(client_code, req_id, req_config)

        # Auto-download if enabled
        if auto_download:
            from download_resumes import download_resumes
            new_ids = [c.get("CandidateId") for c in new_candidates]
            download_resumes(client_code, req_id, candidate_ids=new_ids)

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
    parser.add_argument("--once", action="store_true",
                       help="Run once and exit")
    args = parser.parse_args()

    watch_applicants(
        client_code=args.client,
        req_id=args.req,
        interval=args.interval,
        auto_download=args.auto_download,
        once=args.once
    )


if __name__ == "__main__":
    main()
