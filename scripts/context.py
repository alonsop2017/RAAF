#!/usr/bin/env python3
"""
Working context management.
Saves and restores client/requisition context for easier command execution.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    load_context,
    save_context,
    clear_context,
    get_context_file,
    get_client_info,
    get_requisition_config
)


def show_context():
    """Display current working context."""
    context = load_context()

    if not context:
        print("No working context set")
        print(f"\nSet context with: python scripts/context.py --set --client <code> --req <id>")
        return

    print("Current Working Context")
    print("=" * 40)

    client = context.get("client")
    req = context.get("requisition")

    if client:
        print(f"  Client: {client}")
        try:
            info = get_client_info(client)
            print(f"    Company: {info.get('company_name', 'Unknown')}")
        except FileNotFoundError:
            print(f"    Warning: Client config not found")

    if req:
        print(f"  Requisition: {req}")
        if client:
            try:
                config = get_requisition_config(client, req)
                print(f"    Title: {config.get('job', {}).get('title', 'Unknown')}")
                print(f"    Status: {config.get('status', 'Unknown')}")
            except FileNotFoundError:
                print(f"    Warning: Requisition config not found")

    print(f"\nContext file: {get_context_file()}")


def set_context(client: str = None, req: str = None):
    """Set working context."""
    context = load_context()

    if client:
        # Verify client exists
        try:
            get_client_info(client)
            context["client"] = client
            print(f"Set client: {client}")
        except FileNotFoundError:
            print(f"Warning: Client '{client}' not found, but setting anyway")
            context["client"] = client

    if req:
        # Verify requisition exists
        if client or context.get("client"):
            try:
                c = client or context.get("client")
                get_requisition_config(c, req)
                context["requisition"] = req
                print(f"Set requisition: {req}")
            except FileNotFoundError:
                print(f"Warning: Requisition '{req}' not found, but setting anyway")
                context["requisition"] = req
        else:
            print("Cannot set requisition without client")
            return

    save_context(context)
    print("\nContext saved!")


def do_clear_context():
    """Clear working context."""
    clear_context()
    print("Context cleared")


def get_current_context() -> tuple[str, str]:
    """Get current client and requisition from context."""
    context = load_context()
    return context.get("client"), context.get("requisition")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Manage working context")
    parser.add_argument("--show", action="store_true", help="Show current context")
    parser.add_argument("--set", action="store_true", help="Set context")
    parser.add_argument("--clear", action="store_true", help="Clear context")
    parser.add_argument("--client", "-c", help="Client code to set")
    parser.add_argument("--req", "-r", help="Requisition ID to set")
    args = parser.parse_args()

    if args.clear:
        do_clear_context()
    elif args.set:
        if not args.client and not args.req:
            print("Specify --client and/or --req to set")
            sys.exit(1)
        set_context(client=args.client, req=args.req)
    else:
        show_context()


if __name__ == "__main__":
    main()
