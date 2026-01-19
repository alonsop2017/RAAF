#!/usr/bin/env python3
"""
Full sync from PCRecruiter for a client.
Syncs positions, candidates, and downloads resumes.
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.pcr_client import PCRClient, PCRClientError
from utils.client_utils import (
    get_client_info,
    list_requisitions
)

from sync_candidates import sync_candidates
from download_resumes import download_resumes


def full_sync(client_code: str, download: bool = True) -> dict:
    """
    Perform full sync for a client.

    Args:
        client_code: Client identifier
        download: Whether to download resumes

    Returns:
        Sync statistics
    """
    print(f"Full sync for client: {client_code}")
    print("=" * 50)

    # Verify client exists
    try:
        client_info = get_client_info(client_code)
        print(f"Client: {client_info.get('company_name')}")
    except FileNotFoundError:
        raise ValueError(f"Client not found: {client_code}")

    # Get active requisitions
    reqs = list_requisitions(client_code, status="active")
    print(f"Active requisitions: {len(reqs)}")

    stats = {
        "client": client_code,
        "synced_at": datetime.now().isoformat(),
        "requisitions": {}
    }

    for req_id in reqs:
        print(f"\n--- {req_id} ---")

        req_stats = {
            "candidates_synced": 0,
            "resumes_downloaded": 0,
            "errors": []
        }

        try:
            # Sync candidates
            candidates = sync_candidates(
                client_code=client_code,
                req_id=req_id,
                output_format="table"
            )
            req_stats["candidates_synced"] = len(candidates)

            # Download resumes
            if download and candidates:
                dl_stats = download_resumes(
                    client_code=client_code,
                    req_id=req_id
                )
                req_stats["resumes_downloaded"] = dl_stats.get("downloaded", 0)

        except Exception as e:
            print(f"  Error: {e}")
            req_stats["errors"].append(str(e))

        stats["requisitions"][req_id] = req_stats

    # Summary
    print("\n" + "=" * 50)
    print("SYNC SUMMARY")
    print("=" * 50)

    total_candidates = 0
    total_resumes = 0

    for req_id, req_stats in stats["requisitions"].items():
        candidates = req_stats["candidates_synced"]
        resumes = req_stats["resumes_downloaded"]
        total_candidates += candidates
        total_resumes += resumes
        print(f"  {req_id}: {candidates} candidates, {resumes} resumes")

    print(f"\nTotal: {total_candidates} candidates, {total_resumes} resumes downloaded")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Full sync from PCRecruiter")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--no-download", action="store_true",
                       help="Skip resume download")
    args = parser.parse_args()

    try:
        full_sync(
            client_code=args.client,
            download=not args.no_download
        )
    except (PCRClientError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
