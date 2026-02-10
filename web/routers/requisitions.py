"""
Requisition management routes for RAAF Web Application.
"""

import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import yaml
import shutil
import logging

logger = logging.getLogger(__name__)

from scripts.utils.client_utils import (
    list_clients, get_client_info, get_client_root,
    get_requisition_root, get_requisition_config, list_requisitions,
    get_project_root
)
from scripts.utils.archive_requisition import archive_requisition

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
    currency: str = Form("CAD"),
    experience_years_min: int = Form(0),
    education: str = Form(""),
    framework_source: str = Form("template"),
    template: str = Form("base_framework"),
    notes: str = Form(""),
    job_description: UploadFile = File(None),
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

    # Save uploaded job description if provided
    jd_text = None
    if job_description and job_description.filename:
        jd_content = await job_description.read()
        if jd_content:
            # Determine extension
            ext = Path(job_description.filename).suffix.lower()
            if ext not in (".pdf", ".docx"):
                ext = ".pdf"  # default
            jd_path = req_root / f"job_description{ext}"
            with open(jd_path, "wb") as f:
                f.write(jd_content)
            logger.info(f"Saved job description: {jd_path}")

            # Extract text from job description
            try:
                if ext == ".pdf":
                    from scripts.utils.pdf_reader import extract_text as extract_pdf
                    jd_text = extract_pdf(jd_path, use_ocr_fallback=False)
                elif ext == ".docx":
                    from scripts.utils.docx_reader import extract_text as extract_docx
                    jd_text = extract_docx(jd_path)
                if jd_text:
                    jd_text = jd_text.strip()
                    logger.info(f"Extracted {len(jd_text)} chars from job description")
            except Exception as e:
                logger.warning(f"Failed to extract JD text: {e}")
                jd_text = None

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
                'currency': currency.strip().upper() or 'CAD'
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

    # Add JD info to config if uploaded
    if job_description and job_description.filename:
        req_config['job']['description_file'] = job_description.filename

    with open(req_root / "requisition.yaml", 'w') as f:
        yaml.dump(req_config, f, default_flow_style=False)

    # Generate or copy assessment framework
    framework_generated = False
    if framework_source == "generate" and jd_text:
        try:
            from web.services.framework_generator import generate_framework
            framework_md = await generate_framework(
                jd_text=jd_text,
                job_title=title,
                department=department,
                location=location,
                experience_years_min=experience_years_min,
                education=education,
            )
            with open(req_root / "framework" / "assessment_framework.md", "w") as f:
                f.write(framework_md)
            framework_generated = True
            logger.info(f"Generated AI assessment framework for {req_id}")

            # Save extracted JD text for reference
            with open(req_root / "framework" / "job_description_text.txt", "w") as f:
                f.write(f"# Extracted Job Description Text\n")
                f.write(f"# Source: {job_description.filename}\n")
                f.write(f"# Extracted: {datetime.now().strftime('%Y-%m-%d')}\n\n")
                f.write(jd_text)

        except Exception as e:
            logger.error(f"Framework generation failed: {e}")
            # Fall back to template
            framework_generated = False

    if not framework_generated:
        # Copy framework template
        template_path = get_project_root() / "templates" / "frameworks" / f"{template}_template.md"
        if template_path.exists():
            shutil.copy(template_path, req_root / "framework" / "assessment_framework.md")
        else:
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

    redirect_url = f"/requisitions/{client_code}/{req_id}"
    if framework_generated:
        redirect_url += "?framework=generated"
    return RedirectResponse(url=redirect_url, status_code=303)


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

    # PCR integration data
    pcr_integration = req_config.get('pcr_integration', {})
    pcr_company_name = client_config.get('pcr_company_name', '')

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
        "assessed_count": sum(1 for c in candidates if c['assessed']),
        "pcr_integration": pcr_integration,
        "pcr_company_name": pcr_company_name,
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
    currency: str = Form("CAD"),
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
    config['job']['salary_range']['currency'] = currency.strip().upper() or 'CAD'
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
    status: str = Form(...),
    archive_note: str = Form("")
):
    """Quick status update for requisition. If status is 'cancelled', archives the requisition."""
    req_root = get_requisition_root(client_code, req_id)
    config_path = req_root / "requisition.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Requisition not found")

    # If cancelling, archive the requisition and redirect to list
    if status == "cancelled":
        try:
            archive_requisition(
                client_code=client_code,
                req_id=req_id,
                status="cancelled",
                note=archive_note or "Cancelled via web interface"
            )
            # Redirect to requisitions list since the requisition folder is now archived
            return RedirectResponse(url="/requisitions", status_code=303)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to archive requisition: {str(e)}")

    # For other statuses, just update the YAML
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    config['status'] = status

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    return RedirectResponse(url=f"/requisitions/{client_code}/{req_id}", status_code=303)


@router.post("/{client_code}/{req_id}/link-pcr")
async def link_pcr_position(
    request: Request,
    client_code: str,
    req_id: str,
    job_id: str = Form(...),
    job_title: str = Form(""),
    company_name: str = Form(""),
):
    """Link a PCR position to this requisition."""
    req_root = get_requisition_root(client_code, req_id)
    config_path = req_root / "requisition.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Requisition not found")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    config['pcr_integration'] = {
        'job_id': job_id,
        'job_title': job_title,
        'company_name': company_name,
        'linked_date': datetime.now().strftime("%Y-%m-%d"),
    }

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    return RedirectResponse(url=f"/requisitions/{client_code}/{req_id}", status_code=303)


@router.post("/{client_code}/{req_id}/unlink-pcr")
async def unlink_pcr_position(
    request: Request,
    client_code: str,
    req_id: str,
):
    """Remove PCR position linkage from this requisition."""
    req_root = get_requisition_root(client_code, req_id)
    config_path = req_root / "requisition.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Requisition not found")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    config.pop('pcr_integration', None)

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    return RedirectResponse(url=f"/requisitions/{client_code}/{req_id}", status_code=303)
