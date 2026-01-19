#!/usr/bin/env python3
"""
Validate assessment framework completeness.
Checks that a requisition's framework is properly configured.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.client_utils import (
    get_requisition_config,
    get_framework_path
)


def validate_framework(client_code: str, req_id: str) -> dict:
    """
    Validate framework configuration for a requisition.

    Args:
        client_code: Client identifier
        req_id: Requisition ID

    Returns:
        Validation results with warnings and errors
    """
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "info": []
    }

    # Check requisition config
    try:
        config = get_requisition_config(client_code, req_id)
    except FileNotFoundError:
        results["valid"] = False
        results["errors"].append("Requisition configuration not found")
        return results

    # Check assessment section
    assessment = config.get("assessment", {})

    if not assessment:
        results["valid"] = False
        results["errors"].append("No assessment configuration found")
        return results

    # Check required fields
    if not assessment.get("framework_template"):
        results["warnings"].append("No framework template specified")

    if not assessment.get("framework_version"):
        results["warnings"].append("No framework version specified")

    # Check thresholds
    thresholds = assessment.get("thresholds", {})
    if not thresholds:
        results["warnings"].append("No custom thresholds - using defaults")
    else:
        strong = thresholds.get("strong_recommend", 0)
        recommend = thresholds.get("recommend", 0)
        conditional = thresholds.get("conditional", 0)

        if not (strong > recommend > conditional > 0):
            results["errors"].append(
                f"Invalid thresholds: strong({strong}) > recommend({recommend}) > conditional({conditional})"
            )
            results["valid"] = False

    # Check max score
    max_score = assessment.get("max_score", 100)
    if max_score != 100:
        results["info"].append(f"Non-standard max score: {max_score}")

    # Check framework files
    framework_path = get_framework_path(client_code, req_id)

    if not framework_path.exists():
        results["errors"].append("Framework directory not found")
        results["valid"] = False
    else:
        # Check for framework document
        framework_files = list(framework_path.glob("*.md")) + list(framework_path.glob("*.pdf"))
        if not framework_files:
            results["warnings"].append("No framework document found (*.md or *.pdf)")

        # Check for framework notes
        notes_file = framework_path / "framework_notes.md"
        if not notes_file.exists():
            results["info"].append("No framework notes file")

        # Check for framework config
        config_file = framework_path / "framework_config.yaml"
        if config_file.exists():
            results["info"].append("Custom framework config found")

    # Check weight overrides
    overrides = assessment.get("weight_overrides", {})
    if overrides:
        total_override = sum(overrides.values())
        results["info"].append(f"Weight overrides configured: {list(overrides.keys())}")
        if total_override > 0:
            results["warnings"].append(
                f"Weight overrides total {total_override}% - ensure remaining weights balance to 100%"
            )

    return results


def display_results(req_id: str, results: dict):
    """Display validation results."""
    status = "✓ VALID" if results["valid"] else "✗ INVALID"
    print(f"\nFramework Validation: {req_id}")
    print(f"Status: {status}")
    print("-" * 50)

    if results["errors"]:
        print("\nErrors:")
        for e in results["errors"]:
            print(f"  ✗ {e}")

    if results["warnings"]:
        print("\nWarnings:")
        for w in results["warnings"]:
            print(f"  ⚠ {w}")

    if results["info"]:
        print("\nInfo:")
        for i in results["info"]:
            print(f"  ℹ {i}")

    if results["valid"] and not results["warnings"]:
        print("\n  Framework configuration looks good!")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Validate framework configuration")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    import json

    results = validate_framework(args.client, args.req)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        display_results(args.req, results)

    sys.exit(0 if results["valid"] else 1)


if __name__ == "__main__":
    main()
