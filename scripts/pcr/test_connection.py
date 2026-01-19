#!/usr/bin/env python3
"""
Test PCRecruiter API connection.
Verifies credentials and API connectivity.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.pcr_client import PCRClient, PCRClientError


def test_connection(verbose: bool = True) -> bool:
    """
    Test connection to PCRecruiter API.

    Args:
        verbose: Print detailed output

    Returns:
        True if connection successful, False otherwise
    """
    try:
        if verbose:
            print("Testing PCRecruiter API connection...")
            print("-" * 50)

        # Initialize client
        client = PCRClient()
        if verbose:
            print("✓ Credentials loaded successfully")

        # Authenticate
        token = client.authenticate()
        if verbose:
            print(f"✓ Authentication successful")
            print(f"  Session token: {token[:20]}...")
            print(f"  Expires: {client.session_expires}")

        # Test API call - get positions
        positions = client.get_positions(limit=1)
        if verbose:
            print(f"✓ API call successful")
            print(f"  Retrieved {len(positions)} position(s) as test")

        if verbose:
            print("-" * 50)
            print("✓ All tests passed! PCR connection is working.")

        return True

    except FileNotFoundError as e:
        if verbose:
            print(f"✗ Credentials file not found")
            print(f"  {e}")
            print("\nTo fix:")
            print("  1. Copy config/pcr_credentials_template.yaml to config/pcr_credentials.yaml")
            print("  2. Fill in your PCR credentials")
        return False

    except ValueError as e:
        if verbose:
            print(f"✗ Invalid credentials configuration")
            print(f"  {e}")
        return False

    except PCRClientError as e:
        if verbose:
            print(f"✗ PCR API error")
            print(f"  {e}")
        return False

    except Exception as e:
        if verbose:
            print(f"✗ Unexpected error")
            print(f"  {type(e).__name__}: {e}")
        return False


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Test PCRecruiter API connection")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode - only return exit code")
    args = parser.parse_args()

    success = test_connection(verbose=not args.quiet)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
