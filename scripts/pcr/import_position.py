#!/usr/bin/env python3
"""
Import a PCRecruiter position as a local requisition.
Creates the requisition folder structure and links to PCR.
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.pcr_client import PCRClient, PCRClientError
from utils.client_utils import (
    get_client_root,
    get_client_info,
    get_requisition_root,
    get_templates_path,
    get_config_path
)


def import_position(
    job_id: str,
    client_code: str,
    req_id: str,
    framework_template: str = "base"
) -> dict:
    """
    Import a PCR position as a local requisition.

    Args:
        job_id: PCR Job/Position ID
        client_code: Client code for the requisition
        req_id: Requisition ID to create
        framework_template: Framework template to use

    Returns:
        Created requisition configuration
    """
    # Verify client exists
    try:
        client_info = get_client_info(client_code)
    except FileNotFoundError:
        raise ValueError(f"Client not found: {client_code}")

    # Check if requisition already exists
    req_root = get_requisition_root(client_code, req_id)
    if req_root.exists():
        raise ValueError(f"Requisition already exists: {req_id}")

    # Fetch position from PCR
    print(f"Fetching position {job_id} from PCRecruiter...")
    client = PCRClient()
    client.ensure_authenticated()

    position = client.get_position(job_id)

    print(f"  Title: {position.get('Title')}")
    print(f"  Company: {position.get('CompanyName')}")
    print(f"  Status: {position.get('Status')}")

    # Create requisition folder structure
    print(f"\nCreating requisition {req_id}...")

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

    # Create requisition.yaml
    salary_min = position.get("SalaryMin", 0)
    salary_max = position.get("SalaryMax", 0)
    commission_rate = client_info.get("billing", {}).get("default_commission_rate", 0.20)

    req_config = {
        "requisition_id": req_id,
        "client_code": client_code,
        "created_date": datetime.now().strftime("%Y-%m-%d"),
        "status": "active",
        "job": {
            "title": position.get("Title", ""),
            "department": position.get("Department", ""),
            "location": position.get("Location", ""),
            "salary_range": {
                "min": salary_min,
                "max": salary_max,
                "currency": "CAD"
            },
            "employment_type": "full_time",
            "commission_rate": commission_rate
        },
        "requirements": {
            "experience_years_min": 0,
            "education": "",
            "industry_preference": "",
            "special_requirements": []
        },
        "assessment": {
            "framework_template": framework_template,
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
            "hiring_manager": position.get("HiringManager", ""),
            "hr_contact": ""
        },
        "pcr_integration": {
            "job_id": job_id,
            "job_code": position.get("JobCode", ""),
            "pipeline_id": position.get("PipelineId", ""),
            "last_sync": ""
        },
        "batches_processed": [],
        "total_candidates_assessed": 0,
        "last_assessment_date": "",
        "report_status": "pending",
        "notes": f"Imported from PCR position {job_id} on {datetime.now().strftime('%Y-%m-%d')}"
    }

    req_config_path = req_root / "requisition.yaml"
    with open(req_config_path, "w") as f:
        yaml.dump(req_config, f, default_flow_style=False, sort_keys=False)

    print(f"  Created: {req_config_path}")

    # Copy framework template
    template_path = get_templates_path() / "frameworks" / f"{framework_template}_template.md"
    if template_path.exists():
        framework_dest = req_root / "framework" / "assessment_framework.md"
        shutil.copy(template_path, framework_dest)
        print(f"  Copied framework template: {framework_template}")

        # Create framework notes
        notes_path = req_root / "framework" / "framework_notes.md"
        with open(notes_path, "w") as f:
            f.write(f"# Framework Notes for {req_id}\n\n")
            f.write(f"## Base Template\n")
            f.write(f"Template: {framework_template}_template.md\n\n")
            f.write(f"## Customizations\n")
            f.write(f"Document any changes made to the framework here.\n\n")
            f.write(f"## Client Requirements\n")
            f.write(f"Note any specific client requirements or preferences.\n")

    # Save job description if available
    job_desc = position.get("Description", "")
    if job_desc:
        jd_path = req_root / "job_description.txt"
        with open(jd_path, "w") as f:
            f.write(f"# {position.get('Title')}\n\n")
            f.write(job_desc)
        print(f"  Saved job description")

    # Update client's active requisitions
    active_reqs = client_info.get("active_requisitions", [])
    if req_id not in active_reqs:
        active_reqs.append(req_id)
        client_info["active_requisitions"] = active_reqs

        client_info_path = get_client_root(client_code) / "client_info.yaml"
        with open(client_info_path, "w") as f:
            yaml.dump(client_info, f, default_flow_style=False, sort_keys=False)

    print(f"\n✓ Requisition {req_id} created successfully!")
    print(f"  Location: {req_root}")

    return req_config


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Import PCR position as requisition")
    parser.add_argument("--job-id", required=True, help="PCR Job/Position ID")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req-id", required=True, help="Requisition ID to create")
    parser.add_argument("--template", default="base",
                       help="Framework template (base, saas_csm, saas_ae, construction_pm)")
    args = parser.parse_args()

    try:
        import_position(
            job_id=args.job_id,
            client_code=args.client,
            req_id=args.req_id,
            framework_template=args.template
        )
    except (PCRClientError, ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
