#!/usr/bin/env python3
"""
Initialize a new requisition.
Creates the requisition folder structure and configuration files.
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    get_project_root,
    get_client_root,
    get_client_info,
    get_requisition_root,
    get_templates_path,
    list_requisitions
)


def init_requisition(
    client_code: str,
    req_id: str,
    title: str,
    template: str = "base",
    location: str = "",
    salary_min: int = 0,
    salary_max: int = 0,
    experience_years: int = 0
) -> dict:
    """
    Initialize a new requisition.

    Args:
        client_code: Client identifier
        req_id: Requisition ID (e.g., REQ-2025-001-CSM)
        title: Job title
        template: Framework template to use
        location: Job location
        salary_min: Minimum salary
        salary_max: Maximum salary
        experience_years: Minimum years of experience

    Returns:
        Requisition configuration dictionary
    """
    # Verify client exists
    try:
        client_info = get_client_info(client_code)
    except FileNotFoundError:
        raise ValueError(f"Client not found: {client_code}. Initialize client first.")

    # Validate requisition ID format
    if not req_id.startswith("REQ-"):
        print(f"Warning: Requisition ID '{req_id}' doesn't follow REQ-YYYY-NNN-ROLE format")

    # Check if requisition already exists
    req_root = get_requisition_root(client_code, req_id)
    if req_root.exists():
        raise ValueError(f"Requisition already exists: {req_id}")

    print(f"Initializing requisition: {req_id}")
    print(f"  Client: {client_code}")
    print(f"  Title: {title}")
    print(f"  Template: {template}")

    # Create requisition folder structure
    folders = [
        req_root / "framework",
        req_root / "resumes" / "incoming",
        req_root / "resumes" / "processed",
        req_root / "resumes" / "batches",
        req_root / "assessments" / "individual",
        req_root / "assessments" / "consolidated",
        req_root / "reports" / "drafts",
        req_root / "reports" / "final",
        req_root / "correspondence"
    ]

    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)

    # Get commission rate from client
    commission_rate = client_info.get("billing", {}).get("default_commission_rate", 0.20)

    # Create requisition.yaml
    req_config = {
        "requisition_id": req_id,
        "client_code": client_code,
        "created_date": datetime.now().strftime("%Y-%m-%d"),
        "status": "active",
        "job": {
            "title": title,
            "department": "",
            "location": location,
            "salary_range": {
                "min": salary_min,
                "max": salary_max,
                "currency": "CAD"
            },
            "employment_type": "full_time",
            "commission_rate": commission_rate
        },
        "requirements": {
            "experience_years_min": experience_years,
            "education": "",
            "industry_preference": "",
            "special_requirements": []
        },
        "assessment": {
            "framework_template": template,
            "framework_version": "1.0",
            "max_score": 100,
            "thresholds": {
                "strong_recommend": 85,
                "recommend": 70,
                "conditional": 55
            },
            "weight_overrides": {}
        },
        "contacts": {
            "hiring_manager": "",
            "hr_contact": ""
        },
        "pcr_integration": {
            "job_id": "",
            "job_code": "",
            "pipeline_id": "",
            "last_sync": ""
        },
        "batches_processed": [],
        "total_candidates_assessed": 0,
        "last_assessment_date": "",
        "report_status": "pending",
        "notes": ""
    }

    req_config_path = req_root / "requisition.yaml"
    with open(req_config_path, "w") as f:
        yaml.dump(req_config, f, default_flow_style=False, sort_keys=False)

    print(f"  Created: requisition.yaml")

    # Copy framework template
    template_file = f"{template}_template.md"
    template_path = get_templates_path() / "frameworks" / template_file

    if template_path.exists():
        framework_dest = req_root / "framework" / "assessment_framework.md"
        shutil.copy(template_path, framework_dest)
        print(f"  Copied framework template: {template_file}")

        # Create framework notes
        notes_content = f"""# Framework Notes for {req_id}

## Base Template
Template: {template_file}
Copied: {datetime.now().strftime("%Y-%m-%d")}

## Customizations
Document any changes made to the base framework here:
-

## Client-Specific Requirements
Note any specific client requirements or preferences:
-

## Scoring Adjustments
Document any weight or threshold adjustments:
-
"""
        notes_path = req_root / "framework" / "framework_notes.md"
        with open(notes_path, "w") as f:
            f.write(notes_content)
        print(f"  Created: framework_notes.md")
    else:
        print(f"  Warning: Template not found: {template_file}")
        available = list(get_templates_path().glob("frameworks/*_template.md"))
        if available:
            print(f"  Available templates: {[t.stem.replace('_template', '') for t in available]}")

    # Update client's active requisitions
    active_reqs = client_info.get("active_requisitions", [])
    if req_id not in active_reqs:
        active_reqs.append(req_id)
        client_info["active_requisitions"] = active_reqs

        client_info_path = get_client_root(client_code) / "client_info.yaml"
        with open(client_info_path, "w") as f:
            yaml.dump(client_info, f, default_flow_style=False, sort_keys=False)

    print(f"\n✓ Requisition '{req_id}' initialized successfully!")
    print(f"  Location: {req_root}")
    print(f"\nNext steps:")
    print(f"  1. Add job description PDF to {req_root.name}/")
    print(f"  2. Review and customize framework in {req_root.name}/framework/")
    print(f"  3. Add resumes to {req_root.name}/resumes/incoming/")
    print(f"  4. Or sync from PCR: python scripts/pcr/sync_candidates.py --client {client_code} --req {req_id}")

    return req_config


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Initialize a new requisition")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req-id", "-r", required=True,
                       help="Requisition ID (e.g., REQ-2025-001-CSM)")
    parser.add_argument("--title", "-t", required=True, help="Job title")
    parser.add_argument("--template", default="base",
                       help="Framework template (base, saas_csm, saas_ae, construction_pm)")
    parser.add_argument("--location", default="", help="Job location")
    parser.add_argument("--salary-min", type=int, default=0, help="Minimum salary")
    parser.add_argument("--salary-max", type=int, default=0, help="Maximum salary")
    parser.add_argument("--experience", type=int, default=0,
                       help="Minimum years of experience")
    parser.add_argument("--list", action="store_true",
                       help="List existing requisitions for the client")
    args = parser.parse_args()

    if args.list:
        try:
            reqs = list_requisitions(args.client)
            if not reqs:
                print(f"No requisitions found for {args.client}")
            else:
                print(f"Requisitions for {args.client}:")
                for r in sorted(reqs):
                    print(f"  - {r}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
        return

    try:
        init_requisition(
            client_code=args.client,
            req_id=args.req_id,
            title=args.title,
            template=args.template,
            location=args.location,
            salary_min=args.salary_min,
            salary_max=args.salary_max,
            experience_years=args.experience
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
