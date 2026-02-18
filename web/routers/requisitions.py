"""
Requisition management routes for RAAF Web Application.
"""

import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
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

                    # Count candidates from batch extracted/ folders + legacy processed/
                    candidate_count = 0
                    batches_dir = req_root / "resumes" / "batches"
                    if batches_dir.exists():
                        for batch_d in batches_dir.iterdir():
                            if batch_d.is_dir():
                                ext_dir = batch_d / "extracted"
                                if ext_dir.exists():
                                    candidate_count += len(list(ext_dir.glob("*.txt")))
                    legacy_dir = req_root / "resumes" / "processed"
                    if legacy_dir.exists():
                        candidate_count += len(list(legacy_dir.glob("*.txt")))

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


@router.get("/api/pcr-jd")
async def get_pcr_jd(job_id: str = Query(...)):
    """Fetch job description text and metadata from a PCR position."""
    try:
        from scripts.utils.pcr_client import PCRClient
        client = PCRClient()
        client.ensure_authenticated()
        position = client.get_position(job_id)
        jd_text = client.get_position_description(job_id)
        return JSONResponse({
            "jd_text": jd_text,
            "title": position.get("JobTitle", position.get("Title", "")),
            "location": position.get("City", ""),
            "salary_min": position.get("SalaryLow", 0) or 0,
            "salary_max": position.get("SalaryHigh", 0) or 0,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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
    pcr_job_id: str = Form(""),
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
    pcr_job_id = pcr_job_id.strip() if pcr_job_id else ""

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

    # Pull JD from PCR position if pcr_job_id is provided and no file was uploaded
    if pcr_job_id and not jd_text and framework_source == "generate":
        try:
            from scripts.utils.pcr_client import PCRClient
            pcr_client = PCRClient()
            pcr_client.ensure_authenticated()
            jd_text = pcr_client.get_position_description(pcr_job_id)
            if jd_text:
                jd_text = jd_text.strip()
                logger.info(f"Fetched {len(jd_text)} chars from PCR position {pcr_job_id}")
        except Exception as e:
            logger.warning(f"Failed to fetch JD from PCR position {pcr_job_id}: {e}")
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

    # Set up PCR integration if pcr_job_id was provided
    if pcr_job_id:
        req_config['pcr_integration'] = {
            'job_id': pcr_job_id,
            'positions': [{
                'job_id': pcr_job_id,
                'job_title': title,
                'linked_date': datetime.now().strftime("%Y-%m-%d"),
            }],
            'linked_date': datetime.now().strftime("%Y-%m-%d"),
        }

    with open(req_root / "requisition.yaml", 'w') as f:
        yaml.dump(req_config, f, default_flow_style=False)

    # Generate or copy assessment framework
    framework_generated = False
    framework_warning = None
    if framework_source == "generate":
        if not jd_text:
            # JD extraction failed - copy template as fallback but warn user
            logger.warning(f"Framework generation requested but JD text extraction failed for {req_id}")
            framework_warning = "extraction_failed"
        else:
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
                with open(req_root / "framework" / "assessment_framework.md", "w", encoding="utf-8") as f:
                    f.write(framework_md)
                framework_generated = True
                logger.info(f"Generated AI assessment framework for {req_id}")

                # Save extracted JD text for reference
                jd_source = (
                    f"PCR Position {pcr_job_id}" if pcr_job_id and not (job_description and job_description.filename)
                    else (job_description.filename if job_description and job_description.filename else "unknown")
                )
                with open(req_root / "framework" / "job_description_text.txt", "w", encoding="utf-8") as f:
                    f.write(f"# Extracted Job Description Text\n")
                    f.write(f"# Source: {jd_source}\n")
                    f.write(f"# Extracted: {datetime.now().strftime('%Y-%m-%d')}\n\n")
                    f.write(jd_text)

            except Exception as e:
                logger.error(f"Framework generation failed: {e}")
                framework_warning = "generation_failed"

    if not framework_generated:
        # Copy framework template as fallback
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
    elif framework_warning:
        redirect_url += f"?framework={framework_warning}"
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

    # Get candidates from batch extracted/ folders + legacy processed/
    import json
    from scripts.utils.client_utils import list_all_extracted_resumes
    candidates = []
    seen = set()
    assessments_dir = req_root / "assessments" / "individual"

    for resume_file in list_all_extracted_resumes(client_code, req_id):
        name_normalized = resume_file.stem.replace("_resume", "")
        if name_normalized in seen:
            continue
        seen.add(name_normalized)
        assessment_file = assessments_dir / f"{name_normalized}_assessment.json"

        candidate_data = {
            'name_normalized': name_normalized,
            'resume_file': resume_file.name,
            'assessed': assessment_file.exists()
        }

        if assessment_file.exists():
            with open(assessment_file, 'r') as f:
                assessment = json.load(f)
            candidate_data['score'] = assessment.get('total_score', 0)
            candidate_data['percentage'] = assessment.get('percentage', 0)
            candidate_data['recommendation'] = assessment.get('recommendation', 'PENDING')
            candidate_data['name'] = assessment.get('candidate', {}).get('name', name_normalized)
        else:
            candidate_data['name'] = name_normalized.replace("_", " ").title()

        candidates.append(candidate_data)

    # Also check legacy processed/ folder
    legacy_dir = req_root / "resumes" / "processed"
    if legacy_dir.exists():
        for resume_file in sorted(legacy_dir.glob("*.txt")):
            name_normalized = resume_file.stem.replace("_resume", "")
            if name_normalized in seen:
                continue
            seen.add(name_normalized)
            assessment_file = assessments_dir / f"{name_normalized}_assessment.json"
            candidate_data = {
                'name_normalized': name_normalized,
                'resume_file': resume_file.name,
                'assessed': assessment_file.exists()
            }
            if assessment_file.exists():
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
                extracted_dir = batch_dir / "extracted"
                batch_files = list(extracted_dir.glob("*.txt")) if extracted_dir.exists() else []
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

    # Check for job description file
    has_job_description = False
    jd_filename = None
    for ext in (".pdf", ".docx"):
        jd_path = req_root / f"job_description{ext}"
        if jd_path.exists():
            has_job_description = True
            jd_filename = jd_path.name
            break

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
        "has_job_description": has_job_description,
        "jd_filename": jd_filename,
    })


@router.get("/{client_code}/{req_id}/edit", response_class=HTMLResponse)
async def edit_requisition_form(request: Request, client_code: str, req_id: str):
    """Show form to edit requisition."""
    try:
        req_config = get_requisition_config(client_code, req_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Requisition not found")

    # Check for job description file
    req_root = get_requisition_root(client_code, req_id)
    has_job_description = False
    jd_filename = None
    for ext in (".pdf", ".docx"):
        jd_path = req_root / f"job_description{ext}"
        if jd_path.exists():
            has_job_description = True
            jd_filename = jd_path.name
            break

    return templates.TemplateResponse("requisitions/edit.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "req": req_config,
        "req_id": req_id,
        "client_code": client_code,
        "has_job_description": has_job_description,
        "jd_filename": jd_filename,
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
    notes: str = Form(""),
    job_description: UploadFile = File(None),
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

    # Handle job description upload
    if job_description and job_description.filename:
        jd_content = await job_description.read()
        if jd_content:
            ext = Path(job_description.filename).suffix.lower()
            if ext not in (".pdf", ".docx"):
                ext = ".pdf"
            # Remove existing JD files
            for old_ext in (".pdf", ".docx"):
                old_jd = req_root / f"job_description{old_ext}"
                if old_jd.exists():
                    old_jd.unlink()
            jd_path = req_root / f"job_description{ext}"
            with open(jd_path, "wb") as f:
                f.write(jd_content)
            config['job']['description_file'] = job_description.filename
            logger.info(f"Updated job description for {req_id}: {jd_path}")

            # Extract text from new JD
            try:
                if ext == ".pdf":
                    from scripts.utils.pdf_reader import extract_text as extract_pdf
                    jd_text = extract_pdf(jd_path, use_ocr_fallback=False)
                elif ext == ".docx":
                    from scripts.utils.docx_reader import extract_text as extract_docx
                    jd_text = extract_docx(jd_path)
                else:
                    jd_text = None
                if jd_text:
                    jd_text = jd_text.strip()
                    framework_dir = req_root / "framework"
                    framework_dir.mkdir(parents=True, exist_ok=True)
                    with open(framework_dir / "job_description_text.txt", "w", encoding="utf-8") as f:
                        f.write(f"# Extracted Job Description Text\n")
                        f.write(f"# Source: {job_description.filename}\n")
                        f.write(f"# Extracted: {datetime.now().strftime('%Y-%m-%d')}\n\n")
                        f.write(jd_text)
            except Exception as e:
                logger.warning(f"Failed to extract JD text during update: {e}")

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
    """Link a PCR position to this requisition (supports multiple positions)."""
    req_root = get_requisition_root(client_code, req_id)
    config_path = req_root / "requisition.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Requisition not found")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    pcr = config.get('pcr_integration', {})

    # Migrate legacy single-position format to multi-position
    positions = pcr.get('positions', [])
    if not positions and pcr.get('job_id'):
        positions = [{
            'job_id': pcr['job_id'],
            'job_title': pcr.get('job_title', ''),
            'company_name': pcr.get('company_name', ''),
            'linked_date': pcr.get('linked_date', ''),
        }]

    # Don't add duplicates
    existing_ids = {str(p['job_id']) for p in positions}
    if str(job_id) not in existing_ids:
        positions.append({
            'job_id': job_id,
            'job_title': job_title,
            'company_name': company_name,
            'linked_date': datetime.now().strftime("%Y-%m-%d"),
        })

    # Keep legacy job_id pointing to first position for backward compat
    config['pcr_integration'] = {
        'job_id': positions[0]['job_id'],
        'positions': positions,
        'linked_date': pcr.get('linked_date') or datetime.now().strftime("%Y-%m-%d"),
        'last_sync': pcr.get('last_sync'),
    }

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    return RedirectResponse(url=f"/requisitions/{client_code}/{req_id}", status_code=303)


@router.post("/{client_code}/{req_id}/unlink-pcr")
async def unlink_pcr_position(
    request: Request,
    client_code: str,
    req_id: str,
    job_id: str = Form(None),
):
    """Remove PCR position linkage. If job_id given, remove just that one; otherwise remove all."""
    req_root = get_requisition_root(client_code, req_id)
    config_path = req_root / "requisition.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Requisition not found")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    if job_id:
        # Remove a single position
        pcr = config.get('pcr_integration', {})
        positions = pcr.get('positions', [])
        positions = [p for p in positions if str(p['job_id']) != str(job_id)]
        if positions:
            pcr['positions'] = positions
            pcr['job_id'] = positions[0]['job_id']
            config['pcr_integration'] = pcr
        else:
            config.pop('pcr_integration', None)
    else:
        config.pop('pcr_integration', None)

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    return RedirectResponse(url=f"/requisitions/{client_code}/{req_id}", status_code=303)


@router.post("/{client_code}/{req_id}/regenerate-framework")
async def regenerate_framework(request: Request, client_code: str, req_id: str):
    """Regenerate the assessment framework from the stored job description using AI."""
    req_root = get_requisition_root(client_code, req_id)
    req_config = get_requisition_config(client_code, req_id)

    # Find the job description file
    jd_text = None
    for ext in (".docx", ".pdf"):
        jd_path = req_root / f"job_description{ext}"
        if jd_path.exists():
            try:
                if ext == ".pdf":
                    from scripts.utils.pdf_reader import extract_text as extract_pdf
                    jd_text = extract_pdf(jd_path, use_ocr_fallback=False)
                elif ext == ".docx":
                    from scripts.utils.docx_reader import extract_text as extract_docx
                    jd_text = extract_docx(jd_path)
                if jd_text:
                    jd_text = jd_text.strip()
            except Exception as e:
                logger.error(f"JD extraction failed during regeneration: {e}")
            break

    if not jd_text:
        return RedirectResponse(
            url=f"/requisitions/{client_code}/{req_id}?framework=extraction_failed",
            status_code=303
        )

    try:
        from web.services.framework_generator import generate_framework
        job = req_config.get('job', {})
        reqs = req_config.get('requirements', {})
        framework_md = await generate_framework(
            jd_text=jd_text,
            job_title=job.get('title', ''),
            department=job.get('department', ''),
            location=job.get('location', ''),
            experience_years_min=reqs.get('experience_years_min', 0),
            education=reqs.get('education', ''),
        )
        with open(req_root / "framework" / "assessment_framework.md", "w", encoding="utf-8") as f:
            f.write(framework_md)

        # Save extracted JD text for reference
        with open(req_root / "framework" / "job_description_text.txt", "w", encoding="utf-8") as f:
            f.write(f"# Extracted Job Description Text\n")
            f.write(f"# Regenerated: {datetime.now().strftime('%Y-%m-%d')}\n\n")
            f.write(jd_text)

        logger.info(f"Regenerated AI framework for {req_id}")
        return RedirectResponse(
            url=f"/requisitions/{client_code}/{req_id}?framework=regenerated",
            status_code=303
        )
    except Exception as e:
        logger.error(f"Framework regeneration failed: {e}")
        return RedirectResponse(
            url=f"/requisitions/{client_code}/{req_id}?framework=generation_failed",
            status_code=303
        )


@router.get("/{client_code}/{req_id}/download-jd")
async def download_job_description(client_code: str, req_id: str):
    """Download the job description file for a requisition."""
    req_root = get_requisition_root(client_code, req_id)

    for ext in (".pdf", ".docx"):
        jd_path = req_root / f"job_description{ext}"
        if jd_path.exists():
            media_type = (
                "application/pdf" if ext == ".pdf"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            return FileResponse(jd_path, filename=jd_path.name, media_type=media_type)

    raise HTTPException(status_code=404, detail="No job description file found")


@router.post("/{client_code}/{req_id}/update-jd")
async def update_job_description(
    request: Request,
    client_code: str,
    req_id: str,
    job_description: UploadFile = File(...),
):
    """Upload or replace the job description file for a requisition."""
    req_root = get_requisition_root(client_code, req_id)
    config_path = req_root / "requisition.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Requisition not found")

    jd_content = await job_description.read()
    if not jd_content:
        return RedirectResponse(
            url=f"/requisitions/{client_code}/{req_id}?jd=empty",
            status_code=303,
        )

    ext = Path(job_description.filename).suffix.lower()
    if ext not in (".pdf", ".docx"):
        ext = ".pdf"

    # Remove existing JD files
    for old_ext in (".pdf", ".docx"):
        old_jd = req_root / f"job_description{old_ext}"
        if old_jd.exists():
            old_jd.unlink()

    # Save new file
    jd_path = req_root / f"job_description{ext}"
    with open(jd_path, "wb") as f:
        f.write(jd_content)
    logger.info(f"Updated job description for {req_id}: {jd_path}")

    # Update requisition.yaml
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    config.setdefault('job', {})['description_file'] = job_description.filename
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    # Extract text from new JD
    try:
        if ext == ".pdf":
            from scripts.utils.pdf_reader import extract_text as extract_pdf
            jd_text = extract_pdf(jd_path, use_ocr_fallback=False)
        elif ext == ".docx":
            from scripts.utils.docx_reader import extract_text as extract_docx
            jd_text = extract_docx(jd_path)
        else:
            jd_text = None
        if jd_text:
            jd_text = jd_text.strip()
            framework_dir = req_root / "framework"
            framework_dir.mkdir(parents=True, exist_ok=True)
            with open(framework_dir / "job_description_text.txt", "w", encoding="utf-8") as f:
                f.write(f"# Extracted Job Description Text\n")
                f.write(f"# Source: {job_description.filename}\n")
                f.write(f"# Extracted: {datetime.now().strftime('%Y-%m-%d')}\n\n")
                f.write(jd_text)
    except Exception as e:
        logger.warning(f"Failed to extract JD text: {e}")

    return RedirectResponse(
        url=f"/requisitions/{client_code}/{req_id}?jd=updated",
        status_code=303,
    )


@router.get("/{client_code}/{req_id}/sync-log")
async def get_sync_log(
    client_code: str,
    req_id: str,
    lines: int = Query(50, ge=1, le=500),
):
    """Return recent PCR sync log entries, filtered to this requisition."""
    log_path = get_project_root() / "logs" / "pcr_sync.log"
    if not log_path.exists():
        return JSONResponse({"lines": [], "last_sync": None})

    # Read last N*10 lines to have enough to filter from
    req_filter = f"{client_code}/{req_id}"
    all_lines = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception:
        return JSONResponse({"lines": [], "last_sync": None})

    # Collect lines relevant to this requisition plus global status lines
    global_markers = (
        "Starting PCR sync",
        "Sync complete",
        "OK:",
        "ERROR:",
        "SKIP:",
        "Checking for new applicants",
        "No new applicants",
        "Total new applicants",
    )
    filtered = []
    for line in all_lines:
        stripped = line.rstrip()
        if not stripped:
            continue
        if req_filter in stripped:
            filtered.append(stripped)
        elif any(m in stripped for m in global_markers):
            filtered.append(stripped)

    # Return last N lines
    result = filtered[-lines:]

    # Get last_sync from requisition config
    last_sync = None
    try:
        req_config = get_requisition_config(client_code, req_id)
        last_sync = req_config.get("pcr_integration", {}).get("last_sync")
    except Exception:
        pass

    return JSONResponse({"lines": result, "last_sync": last_sync})
