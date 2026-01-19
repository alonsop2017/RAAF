#!/usr/bin/env python3
"""
Refresh PCRecruiter session token.
Forces re-authentication and saves new token.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.pcr_client import PCRClient, PCRClientError


def refresh_token(verbose: bool = True) -> bool:
    """
    Refresh the PCR session token.

    Args:
        verbose: Print detailed output

    Returns:
        True if successful, False otherwise
    """
    try:
        client = PCRClient()

        if verbose:
            print("Refreshing PCRecruiter session token...")

        old_token = client.session_token
        new_token = client.refresh_token()

        if verbose:
            if old_token:
                print(f"  Old token: {old_token[:20]}...")
            print(f"  New token: {new_token[:20]}...")
            print(f"  Expires: {client.session_expires}")
            print("✓ Token refreshed successfully")

        return True

    except PCRClientError as e:
        if verbose:
            print(f"✗ Failed to refresh token: {e}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Refresh PCRecruiter session token")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")
    args = parser.parse_args()

    success = refresh_token(verbose=not args.quiet)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
