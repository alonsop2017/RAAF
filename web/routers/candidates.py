"""
Candidate management routes for RAAF Web Application.
"""

import sys
from pathlib import Path
from datetime import datetime
import json
import shutil
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from scripts.utils.client_utils import (
    get_requisition_root, get_requisition_config, get_client_info
)

# Alias for consistency
get_client_config = get_client_info

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def normalize_filename(name: str) -> str:
    """Normalize candidate name for filename."""
    # Remove extension
    name = name.rsplit('.', 1)[0]
    # Convert to lowercase and replace spaces with underscores
    name = name.lower().replace(" ", "_").replace("-", "_")
    # Remove special characters
    name = ''.join(c for c in name if c.isalnum() or c == '_')
    return name


@router.get("/{client_code}/{req_id}", response_class=HTMLResponse)
async def list_candidates(request: Request, client_code: str, req_id: str):
    """List all candidates for a requisition."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_config = get_client_config(client_code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    req_root = get_requisition_root(client_code, req_id)
    resumes_dir = req_root / "resumes" / "processed"
    assessments_dir = req_root / "assessments" / "individual"

    candidates = []
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
                with open(assessment_file, 'r') as f:
                    assessment = json.load(f)
                candidate_data['score'] = assessment.get('total_score', 0)
                candidate_data['max_score'] = assessment.get('max_score', 100)
                candidate_data['percentage'] = assessment.get('percentage', 0)
                candidate_data['recommendation'] = assessment.get('recommendation', 'PENDING')
                candidate_data['name'] = assessment.get('candidate', {}).get('name', name_normalized)
                candidate_data['stability'] = assessment.get('scores', {}).get('job_stability', {}).get('tenure_analysis', {}).get('risk_level', 'N/A')
            else:
                candidate_data['name'] = name_normalized.replace("_", " ").title()

            candidates.append(candidate_data)

    # Sort by score (assessed first, then by percentage descending)
    candidates.sort(key=lambda x: (x['assessed'], x.get('percentage', 0)), reverse=True)

    return templates.TemplateResponse("candidates/list.html", {
        "request": request,
        "candidates": candidates,
        "req_id": req_id,
        "client_code": client_code,
        "client_name": client_config.get('company_name', client_code),
        "req_title": req_config.get('job', {}).get('title', req_id)
    })


@router.get("/{client_code}/{req_id}/upload", response_class=HTMLResponse)
async def upload_resume_form(request: Request, client_code: str, req_id: str):
    """Show form to upload resumes."""
    return templates.TemplateResponse("candidates/upload.html", {
        "request": request,
        "client_code": client_code,
        "req_id": req_id
    })


@router.post("/{client_code}/{req_id}/upload")
async def upload_resumes(
    request: Request,
    client_code: str,
    req_id: str,
    files: list[UploadFile] = File(...)
):
    """Upload one or more resume files."""
    req_root = get_requisition_root(client_code, req_id)
    incoming_dir = req_root / "resumes" / "incoming"
    processed_dir = req_root / "resumes" / "processed"

    incoming_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    uploaded_count = 0
    for file in files:
        if file.filename:
            # Save original file to incoming
            original_path = incoming_dir / file.filename
            content = await file.read()
            with open(original_path, 'wb') as f:
                f.write(content)

            # Extract text based on file type
            normalized_name = normalize_filename(file.filename)
            processed_path = processed_dir / f"{normalized_name}_resume.txt"

            try:
                if file.filename.lower().endswith('.pdf'):
                    # Extract from PDF
                    from scripts.utils.pdf_reader import extract_text_from_pdf
                    text = extract_text_from_pdf(str(original_path))
                elif file.filename.lower().endswith('.docx'):
                    # Extract from DOCX
                    from scripts.utils.docx_reader import extract_text_from_docx
                    text = extract_text_from_docx(str(original_path))
                elif file.filename.lower().endswith('.txt'):
                    # Already text
                    text = content.decode('utf-8', errors='ignore')
                else:
                    # Try to read as text
                    text = content.decode('utf-8', errors='ignore')

                # Add metadata header
                header = f"""# Extracted Resume
# Source: {file.filename}
# Extracted: {datetime.now().strftime('%Y-%m-%d')}

---

"""
                with open(processed_path, 'w') as f:
                    f.write(header + text)

                uploaded_count += 1
            except Exception as e:
                # If extraction fails, save raw content
                with open(processed_path, 'w') as f:
                    f.write(f"# Extraction failed: {str(e)}\n\n{content.decode('utf-8', errors='ignore')}")
                uploaded_count += 1

    return RedirectResponse(url=f"/candidates/{client_code}/{req_id}?uploaded={uploaded_count}", status_code=303)


@router.get("/{client_code}/{req_id}/{name_normalized}", response_class=HTMLResponse)
async def view_candidate(request: Request, client_code: str, req_id: str, name_normalized: str):
    """View candidate details and assessment."""
    req_root = get_requisition_root(client_code, req_id)
    resumes_dir = req_root / "resumes" / "processed"
    assessments_dir = req_root / "assessments" / "individual"

    # Find resume file
    resume_file = resumes_dir / f"{name_normalized}_resume.txt"
    if not resume_file.exists():
        raise HTTPException(status_code=404, detail="Candidate resume not found")

    # Read resume
    with open(resume_file, 'r') as f:
        resume_text = f.read()

    # Check for assessment
    assessment = None
    assessment_file = assessments_dir / f"{name_normalized}_assessment.json"
    if assessment_file.exists():
        with open(assessment_file, 'r') as f:
            assessment = json.load(f)

    # Get requisition info
    req_config = get_requisition_config(client_code, req_id)
    client_config = get_client_config(client_code)

    return templates.TemplateResponse("candidates/view.html", {
        "request": request,
        "client_code": client_code,
        "req_id": req_id,
        "client_name": client_config.get('company_name', client_code),
        "req_title": req_config.get('job', {}).get('title', req_id),
        "name_normalized": name_normalized,
        "name": assessment.get('candidate', {}).get('name', name_normalized.replace("_", " ").title()) if assessment else name_normalized.replace("_", " ").title(),
        "resume_text": resume_text,
        "assessment": assessment
    })


@router.get("/{client_code}/{req_id}/{name_normalized}/resume")
async def download_resume(client_code: str, req_id: str, name_normalized: str):
    """Download candidate resume."""
    req_root = get_requisition_root(client_code, req_id)

    # Check incoming folder for original
    incoming_dir = req_root / "resumes" / "incoming"
    for ext in ['.pdf', '.docx', '.txt']:
        for file in incoming_dir.glob(f"*{ext}"):
            if normalize_filename(file.name) == name_normalized:
                return FileResponse(file, filename=file.name)

    # Fall back to processed
    processed_file = req_root / "resumes" / "processed" / f"{name_normalized}_resume.txt"
    if processed_file.exists():
        return FileResponse(processed_file, filename=f"{name_normalized}_resume.txt")

    raise HTTPException(status_code=404, detail="Resume file not found")


@router.post("/{client_code}/{req_id}/{name_normalized}/delete")
async def delete_candidate(client_code: str, req_id: str, name_normalized: str):
    """Delete a candidate and their assessment."""
    req_root = get_requisition_root(client_code, req_id)

    # Delete processed resume
    resume_file = req_root / "resumes" / "processed" / f"{name_normalized}_resume.txt"
    if resume_file.exists():
        resume_file.unlink()

    # Delete assessment
    assessment_file = req_root / "assessments" / "individual" / f"{name_normalized}_assessment.json"
    if assessment_file.exists():
        assessment_file.unlink()

    return RedirectResponse(url=f"/candidates/{client_code}/{req_id}", status_code=303)
