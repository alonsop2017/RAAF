"""
Assessment routes for RAAF Web Application.
"""

import sys
from pathlib import Path
from datetime import datetime
import json
import subprocess
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from scripts.utils.client_utils import (
    get_requisition_root, get_requisition_config, get_client_info,
    get_project_root
)

# Alias for consistency
get_client_config = get_client_info

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def run_assessment(
    client_code: str,
    req_id: str,
    candidate_name: str = None,
    batch_name: str = None,
    use_ai: bool = True
):
    """Run assessment script as a subprocess. Uses AI by default."""
    script_path = get_project_root() / "scripts" / "assess_candidate.py"

    cmd = ["python3", str(script_path), "--client", client_code, "--req", req_id]

    if candidate_name:
        cmd.extend(["--resume", f"{candidate_name}_resume.txt"])
    elif batch_name:
        cmd.extend(["--batch", batch_name])
    else:
        cmd.append("--all-pending")

    # Add AI flag if requested
    if use_ai:
        cmd.append("--use-ai")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(get_project_root()))
    return result.returncode == 0, result.stdout, result.stderr


@router.get("/{client_code}/{req_id}", response_class=HTMLResponse)
async def assessment_dashboard(request: Request, client_code: str, req_id: str):
    """Assessment dashboard for a requisition."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_config = get_client_config(client_code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    req_root = get_requisition_root(client_code, req_id)
    assessments_dir = req_root / "assessments" / "individual"
    resumes_dir = req_root / "resumes" / "processed"

    # Get all assessments with details
    assessments = []
    pending = []

    if resumes_dir.exists():
        for resume_file in sorted(resumes_dir.glob("*.txt")):
            name_normalized = resume_file.stem.replace("_resume", "")
            assessment_file = assessments_dir / f"{name_normalized}_assessment.json"

            if assessment_file.exists():
                with open(assessment_file, 'r') as f:
                    assessment = json.load(f)

                assessments.append({
                    'name_normalized': name_normalized,
                    'name': assessment.get('candidate', {}).get('name', name_normalized),
                    'score': assessment.get('total_score', 0),
                    'max_score': assessment.get('max_score', 100),
                    'percentage': assessment.get('percentage', 0),
                    'recommendation': assessment.get('recommendation', 'PENDING'),
                    'assessed_at': assessment.get('metadata', {}).get('assessed_at', 'N/A'),
                    'stability': assessment.get('scores', {}).get('job_stability', {}).get('tenure_analysis', {}).get('risk_level', 'N/A')
                })
            else:
                pending.append({
                    'name_normalized': name_normalized,
                    'name': name_normalized.replace("_", " ").title()
                })

    # Sort assessments by percentage descending
    assessments.sort(key=lambda x: x['percentage'], reverse=True)

    # Calculate summary stats
    thresholds = req_config.get('assessment', {}).get('thresholds', {
        'strong_recommend': 85,
        'recommend': 70,
        'conditional': 55
    })

    summary = {
        'strong_recommend': sum(1 for a in assessments if a['percentage'] >= thresholds['strong_recommend']),
        'recommend': sum(1 for a in assessments if thresholds['recommend'] <= a['percentage'] < thresholds['strong_recommend']),
        'conditional': sum(1 for a in assessments if thresholds['conditional'] <= a['percentage'] < thresholds['recommend']),
        'do_not_recommend': sum(1 for a in assessments if a['percentage'] < thresholds['conditional'] and a['recommendation'] != 'PENDING'),
        'pending': len(pending)
    }

    return templates.TemplateResponse("assessments/dashboard.html", {
        "request": request,
        "client_code": client_code,
        "req_id": req_id,
        "client_name": client_config.get('company_name', client_code),
        "req_title": req_config.get('job', {}).get('title', req_id),
        "assessments": assessments,
        "pending": pending,
        "summary": summary,
        "thresholds": thresholds
    })


@router.post("/{client_code}/{req_id}/run")
async def run_all_assessments(
    request: Request,
    client_code: str,
    req_id: str,
    background_tasks: BackgroundTasks,
    use_ai: str = Form(default="true")
):
    """Run assessments for all pending candidates."""
    # Default to AI assessment (use_ai=true unless explicitly set to false)
    use_ai_bool = use_ai.lower() not in ("false", "0", "off", "no")
    success, stdout, stderr = run_assessment(client_code, req_id, use_ai=use_ai_bool)

    if success:
        mode = "ai" if use_ai_bool else "manual"
        return RedirectResponse(
            url=f"/assessments/{client_code}/{req_id}?success=1&mode={mode}",
            status_code=303
        )
    else:
        return templates.TemplateResponse("assessments/error.html", {
            "request": request,
            "client_code": client_code,
            "req_id": req_id,
            "error": stderr or "Assessment failed",
            "output": stdout
        })


@router.post("/{client_code}/{req_id}/{name_normalized}/run")
async def run_single_assessment(
    request: Request,
    client_code: str,
    req_id: str,
    name_normalized: str,
    use_ai: str = Form(default="true")
):
    """Run assessment for a single candidate."""
    # Default to AI assessment (use_ai=true unless explicitly set to false)
    use_ai_bool = use_ai.lower() not in ("false", "0", "off", "no")
    success, stdout, stderr = run_assessment(
        client_code, req_id,
        candidate_name=name_normalized,
        use_ai=use_ai_bool
    )

    if success:
        mode = "ai" if use_ai_bool else "manual"
        return RedirectResponse(
            url=f"/candidates/{client_code}/{req_id}/{name_normalized}?assessed=1&mode={mode}",
            status_code=303
        )
    else:
        raise HTTPException(status_code=500, detail=stderr or "Assessment failed")


@router.get("/{client_code}/{req_id}/{name_normalized}", response_class=HTMLResponse)
async def view_assessment(request: Request, client_code: str, req_id: str, name_normalized: str):
    """View detailed assessment for a candidate."""
    req_root = get_requisition_root(client_code, req_id)
    assessment_file = req_root / "assessments" / "individual" / f"{name_normalized}_assessment.json"

    if not assessment_file.exists():
        raise HTTPException(status_code=404, detail="Assessment not found")

    with open(assessment_file, 'r') as f:
        assessment = json.load(f)

    req_config = get_requisition_config(client_code, req_id)
    client_config = get_client_config(client_code)

    return templates.TemplateResponse("assessments/view.html", {
        "request": request,
        "client_code": client_code,
        "req_id": req_id,
        "client_name": client_config.get('company_name', client_code),
        "req_title": req_config.get('job', {}).get('title', req_id),
        "name_normalized": name_normalized,
        "assessment": assessment
    })


@router.get("/{client_code}/{req_id}/{name_normalized}/edit", response_class=HTMLResponse)
async def edit_assessment_form(request: Request, client_code: str, req_id: str, name_normalized: str):
    """Edit assessment scores and notes."""
    req_root = get_requisition_root(client_code, req_id)
    assessment_file = req_root / "assessments" / "individual" / f"{name_normalized}_assessment.json"

    if not assessment_file.exists():
        raise HTTPException(status_code=404, detail="Assessment not found")

    with open(assessment_file, 'r') as f:
        assessment = json.load(f)

    req_config = get_requisition_config(client_code, req_id)

    return templates.TemplateResponse("assessments/edit.html", {
        "request": request,
        "client_code": client_code,
        "req_id": req_id,
        "name_normalized": name_normalized,
        "assessment": assessment,
        "thresholds": req_config.get('assessment', {}).get('thresholds', {})
    })


@router.post("/{client_code}/{req_id}/{name_normalized}/update")
async def update_assessment(
    request: Request,
    client_code: str,
    req_id: str,
    name_normalized: str
):
    """Update assessment with form data."""
    req_root = get_requisition_root(client_code, req_id)
    assessment_file = req_root / "assessments" / "individual" / f"{name_normalized}_assessment.json"

    if not assessment_file.exists():
        raise HTTPException(status_code=404, detail="Assessment not found")

    with open(assessment_file, 'r') as f:
        assessment = json.load(f)

    # Get form data
    form_data = await request.form()

    # Update scores from form
    scores = assessment.get('scores', {})
    total = 0

    for category in scores:
        if category in form_data:
            try:
                new_score = int(form_data[category])
                max_score = scores[category].get('max', 0)
                scores[category]['score'] = min(new_score, max_score)
                total += scores[category]['score']
            except (ValueError, TypeError):
                pass

        # Update notes
        notes_key = f"{category}_notes"
        if notes_key in form_data:
            scores[category]['notes'] = form_data[notes_key]

    assessment['scores'] = scores
    assessment['total_score'] = total
    assessment['max_score'] = sum(s.get('max', 0) for s in scores.values())
    assessment['percentage'] = round((total / assessment['max_score']) * 100, 1) if assessment['max_score'] > 0 else 0

    # Update recommendation
    req_config = get_requisition_config(client_code, req_id)
    thresholds = req_config.get('assessment', {}).get('thresholds', {
        'strong_recommend': 85,
        'recommend': 70,
        'conditional': 55
    })

    pct = assessment['percentage']
    if pct >= thresholds['strong_recommend']:
        assessment['recommendation'] = 'STRONG RECOMMEND'
        assessment['recommendation_tier'] = 1
    elif pct >= thresholds['recommend']:
        assessment['recommendation'] = 'RECOMMEND'
        assessment['recommendation_tier'] = 2
    elif pct >= thresholds['conditional']:
        assessment['recommendation'] = 'CONDITIONAL'
        assessment['recommendation_tier'] = 3
    else:
        assessment['recommendation'] = 'DO NOT RECOMMEND'
        assessment['recommendation_tier'] = 4

    # Update summary fields
    if 'summary' in form_data:
        assessment['summary'] = form_data['summary']
    if 'key_strengths' in form_data:
        assessment['key_strengths'] = [s.strip() for s in form_data['key_strengths'].split('\n') if s.strip()]
    if 'areas_of_concern' in form_data:
        assessment['areas_of_concern'] = [s.strip() for s in form_data['areas_of_concern'].split('\n') if s.strip()]
    if 'interview_focus_areas' in form_data:
        assessment['interview_focus_areas'] = [s.strip() for s in form_data['interview_focus_areas'].split('\n') if s.strip()]

    # Update metadata
    assessment['metadata']['assessed_at'] = datetime.now().isoformat()
    assessment['metadata']['assessor'] = form_data.get('assessor', 'Manual/Web')

    # Save
    with open(assessment_file, 'w') as f:
        json.dump(assessment, f, indent=2)

    return RedirectResponse(
        url=f"/assessments/{client_code}/{req_id}/{name_normalized}",
        status_code=303
    )


@router.get("/{client_code}/{req_id}/{name_normalized}/json")
async def get_assessment_json(client_code: str, req_id: str, name_normalized: str):
    """Get assessment as JSON."""
    req_root = get_requisition_root(client_code, req_id)
    assessment_file = req_root / "assessments" / "individual" / f"{name_normalized}_assessment.json"

    if not assessment_file.exists():
        raise HTTPException(status_code=404, detail="Assessment not found")

    with open(assessment_file, 'r') as f:
        assessment = json.load(f)

    return JSONResponse(content=assessment)
