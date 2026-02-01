"""
Requisition management routes for RAAF Web Application.
"""

import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import yaml
import shutil

from scripts.utils.client_utils import (
    list_clients, get_client_info, get_client_root,
    get_requisition_root, get_requisition_config, list_requisitions,
    get_project_root
)

# Alias for consistency
get_client_config = get_client_info

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def get_available_templates():
    """Get list of available framework templates."""
    templates_dir = get_project_root() / "templates" / "frameworks"
    templates_list = []
    if templates_dir.exists():
        for f in templates_dir.glob("*_template.md"):
            name = f.stem.replace("_template", "")
            templates_list.append({'value': name, 'label': name.replace("_", " ").title()})
    return templates_list


@router.get("/", response_class=HTMLResponse)
async def list_all_requisitions(request: Request, status: str = None):
    """List all requisitions across all clients."""
    reqs_data = []

    for client_code in list_clients():
        try:
            client_config = get_client_config(client_code)
            client_name = client_config.get('company_name', client_code)

            for req_id in list_requisitions(client_code, status):
                try:
                    req_config = get_requisition_config(client_code, req_id)
                    req_root = get_requisition_root(client_code, req_id)

                    # Count candidates
                    resumes_dir = req_root / "resumes" / "processed"
                    candidate_count = len(list(resumes_dir.glob("*.txt"))) if resumes_dir.exists() else 0

                    # Count assessments
                    assessments_dir = req_root / "assessments" / "individual"
                    assessed_count = len(list(assessments_dir.glob("*.json"))) if assessments_dir.exists() else 0

                    reqs_data.append({
                        'client_code': client_code,
                        'client_name': client_name,
                        'req_id': req_id,
                        'title': req_config.get('job', {}).get('title', req_id),
                        'status': req_config.get('status', 'active'),
                        'location': req_config.get('job', {}).get('location', 'N/A'),
                        'candidate_count': candidate_count,
                        'assessed_count': assessed_count,
                        'created_date': req_config.get('created_date', 'N/A')
                    })
                except Exception:
                    continue
        except Exception:
            continue

    return templates.TemplateResponse("requisitions/list.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "requisitions": reqs_data,
        "filter_status": status
    })


@router.get("/new", response_class=HTMLResponse)
async def new_requisition_form(request: Request, client_code: str = None):
    """Show form to create a new requisition."""
    clients = [(c, get_client_config(c).get('company_name', c)) for c in list_clients()]
    templates_list = get_available_templates()

    return templates.TemplateResponse("requisitions/new.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "clients": clients,
        "selected_client": client_code,
        "framework_templates": templates_list
    })


@router.post("/create")
async def create_requisition(
    request: Request,
    client_code: str = Form(...),
    req_id: str = Form(...),
    title: str = Form(...),
    department: str = Form(""),
    location: str = Form(""),
    salary_min: int = Form(0),
    salary_max: int = Form(0),
    experience_years_min: int = Form(0),
    education: str = Form(""),
    template: str = Form("base_framework"),
    notes: str = Form("")
):
    """Create a new requisition."""
    # Validate client exists
    if client_code not in list_clients():
        raise HTTPException(status_code=404, detail=f"Client '{client_code}' not found")

    # Check if requisition already exists
    if req_id in list_requisitions(client_code):
        raise HTTPException(status_code=400, detail=f"Requisition '{req_id}' already exists")

    # Create requisition directory structure
    req_root = get_requisition_root(client_code, req_id)

    # Create all required subdirectories
    subdirs = [
        "framework",
        "resumes/incoming",
        "resumes/processed",
        "resumes/batches",
        "assessments/individual",
        "assessments/consolidated",
        "reports/drafts",
        "reports/final",
        "correspondence"
    ]

    for subdir in subdirs:
        (req_root / subdir).mkdir(parents=True, exist_ok=True)

    # Create requisition.yaml
    req_config = {
        'requisition_id': req_id,
        'client_code': client_code,
        'created_date': datetime.now().strftime("%Y-%m-%d"),
        'status': 'active',
        'job': {
            'title': title,
            'department': department,
            'location': location,
            'salary_range': {
                'min': salary_min,
                'max': salary_max,
                'currency': 'CAD'
            }
        },
        'requirements': {
            'experience_years_min': experience_years_min,
            'education': education
        },
        'assessment': {
            'framework_version': '1.0',
            'max_score': 100,
            'thresholds': {
                'strong_recommend': 85,
                'recommend': 70,
                'conditional': 55
            }
        },
        'notes': notes
    }

    with open(req_root / "requisition.yaml", 'w') as f:
        yaml.dump(req_config, f, default_flow_style=False)

    # Copy framework template
    template_path = get_project_root() / "templates" / "frameworks" / f"{template}_template.md"
    if template_path.exists():
        shutil.copy(template_path, req_root / "framework" / "assessment_framework.md")
    else:
        # Use base template as fallback
        base_template = get_project_root() / "templates" / "frameworks" / "base_framework_template.md"
        if base_template.exists():
            shutil.copy(base_template, req_root / "framework" / "assessment_framework.md")

    # Update client's active requisitions list
    client_root = get_client_root(client_code)
    client_config_path = client_root / "client_info.yaml"
    if client_config_path.exists():
        with open(client_config_path, 'r') as f:
            client_config = yaml.safe_load(f)

        if 'active_requisitions' not in client_config:
            client_config['active_requisitions'] = []

        if req_id not in client_config['active_requisitions']:
            client_config['active_requisitions'].append(req_id)

        with open(client_config_path, 'w') as f:
            yaml.dump(client_config, f, default_flow_style=False)

    return RedirectResponse(url=f"/requisitions/{client_code}/{req_id}", status_code=303)


@router.get("/{client_code}/{req_id}", response_class=HTMLResponse)
async def view_requisition(request: Request, client_code: str, req_id: str):
    """View requisition details."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_config = get_client_config(client_code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    req_root = get_requisition_root(client_code, req_id)

    # Get candidates
    candidates = []
    resumes_dir = req_root / "resumes" / "processed"
    assessments_dir = req_root / "assessments" / "individual"

    if resumes_dir.exists():
        for resume_file in sorted(resumes_dir.glob("*.txt")):
            name_normalized = resume_file.stem.replace("_resume", "")
            assessment_file = assessments_dir / f"{name_normalized}_assessment.json"

            candidate_data = {
                'name_normalized': name_normalized,
                'resume_file': resume_file.name,
                'assessed': assessment_file.exists()
            }

            if assessment_file.exists():
                import json
                with open(assessment_file, 'r') as f:
                    assessment = json.load(f)
                candidate_data['score'] = assessment.get('total_score', 0)
                candidate_data['percentage'] = assessment.get('percentage', 0)
                candidate_data['recommendation'] = assessment.get('recommendation', 'PENDING')
                candidate_data['name'] = assessment.get('candidate', {}).get('name', name_normalized)
            else:
                candidate_data['name'] = name_normalized.replace("_", " ").title()

            candidates.append(candidate_data)

    # Sort by score (assessed first, then by score descending)
    candidates.sort(key=lambda x: (x['assessed'], x.get('score', 0)), reverse=True)

    # Get batches
    batches = []
    batches_dir = req_root / "resumes" / "batches"
    if batches_dir.exists():
        for batch_dir in sorted(batches_dir.iterdir(), reverse=True):
            if batch_dir.is_dir():
                batch_files = list(batch_dir.glob("*.txt"))
                batches.append({
                    'name': batch_dir.name,
                    'candidate_count': len(batch_files)
                })

    # Check for reports
    reports = []
    reports_dir = req_root / "reports" / "final"
    if reports_dir.exists():
        for report_file in sorted(reports_dir.glob("*.docx"), reverse=True):
            reports.append({
                'filename': report_file.name,
                'created': datetime.fromtimestamp(report_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            })

    return templates.TemplateResponse("requisitions/view.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "req": req_config,
        "req_id": req_id,
        "client_code": client_code,
        "client_name": client_config.get('company_name', client_code),
        "candidates": candidates,
        "batches": batches,
        "reports": reports,
        "candidate_count": len(candidates),
        "assessed_count": sum(1 for c in candidates if c['assessed'])
    })


@router.get("/{client_code}/{req_id}/edit", response_class=HTMLResponse)
async def edit_requisition_form(request: Request, client_code: str, req_id: str):
    """Show form to edit requisition."""
    try:
        req_config = get_requisition_config(client_code, req_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Requisition not found")

    return templates.TemplateResponse("requisitions/edit.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "req": req_config,
        "req_id": req_id,
        "client_code": client_code
    })


@router.post("/{client_code}/{req_id}/update")
async def update_requisition(
    request: Request,
    client_code: str,
    req_id: str,
    title: str = Form(...),
    department: str = Form(""),
    location: str = Form(""),
    status: str = Form("active"),
    salary_min: int = Form(0),
    salary_max: int = Form(0),
    experience_years_min: int = Form(0),
    education: str = Form(""),
    notes: str = Form("")
):
    """Update requisition."""
    req_root = get_requisition_root(client_code, req_id)
    config_path = req_root / "requisition.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Requisition not found")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Update fields
    config['status'] = status
    config['job']['title'] = title
    config['job']['department'] = department
    config['job']['location'] = location
    config['job']['salary_range']['min'] = salary_min
    config['job']['salary_range']['max'] = salary_max
    config['requirements']['experience_years_min'] = experience_years_min
    config['requirements']['education'] = education
    config['notes'] = notes

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    return RedirectResponse(url=f"/requisitions/{client_code}/{req_id}", status_code=303)


@router.post("/{client_code}/{req_id}/update-status")
async def update_requisition_status(
    request: Request,
    client_code: str,
    req_id: str,
    status: str = Form(...)
):
    """Quick status update for requisition."""
    req_root = get_requisition_root(client_code, req_id)
    config_path = req_root / "requisition.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Requisition not found")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    config['status'] = status

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    return RedirectResponse(url=f"/requisitions/{client_code}/{req_id}", status_code=303)
