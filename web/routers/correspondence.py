"""
Correspondence routes for RAAF Web Application.
Handles interview invitation generation and draft management.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from scripts.utils.client_utils import (
    get_requisition_root,
    get_requisition_config,
    get_client_info,
    get_assessments_path,
    get_correspondence_path,
    get_settings,
)

# Import invitation generation logic from the CLI script
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from generate_interview_invitations import (
    load_assessments,
    filter_assessments,
    generate_email_draft,
    save_invitations,
    TIER_NAMES,
    TIER_BY_NAME,
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/{client_code}/{req_id}/invitations", response_class=HTMLResponse)
async def invitations_dashboard(request: Request, client_code: str, req_id: str):
    """Interview invitation generator dashboard."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_info = get_client_info(client_code)
        settings = get_settings()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Load all assessments and group by tier
    all_assessments = load_assessments(client_code, req_id)

    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for a in all_assessments:
        rec = a.get("recommendation", "")
        tier = TIER_BY_NAME.get(rec, a.get("recommendation_tier", 4))
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    # Candidates available by tier (cumulative)
    candidates_by_tier = {
        1: filter_assessments(all_assessments, min_tier=1),
        2: filter_assessments(all_assessments, min_tier=2),
        3: filter_assessments(all_assessments, min_tier=3),
    }

    # List existing invitation files
    correspondence_path = get_correspondence_path(client_code, req_id)
    invitations_dir = correspondence_path / "interview_invitations"
    existing_files = []
    if invitations_dir.exists():
        for f in sorted(invitations_dir.glob("*.txt"), key=lambda x: x.stat().st_mtime, reverse=True):
            existing_files.append({
                "filename": f.name,
                "size": f"{f.stat().st_size / 1024:.1f} KB",
                "created": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "path": f.name,
            })

    recruiter = settings.get("recruiter", {})

    return templates.TemplateResponse(
        "correspondence/invitations.html",
        {
            "request": request,
            "user": getattr(request.state, "user", None),
            "client_code": client_code,
            "req_id": req_id,
            "req_title": req_config.get("job", {}).get("title", req_id),
            "client_name": client_info.get("company_name", client_code),
            "tier_counts": tier_counts,
            "candidates_by_tier": candidates_by_tier,
            "total_assessed": len(all_assessments),
            "existing_files": existing_files,
            "recruiter": recruiter,
        },
    )


@router.post("/{client_code}/{req_id}/invitations/generate", response_class=HTMLResponse)
async def generate_invitations(
    request: Request,
    client_code: str,
    req_id: str,
    min_tier: int = Form(2),
    output_format: str = Form("both"),
    recruiter_name: str = Form(""),
    recruiter_email: str = Form(""),
    recruiter_phone: str = Form(""),
):
    """Generate and save interview invitation drafts, then display them."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_info = get_client_info(client_code)
        settings = get_settings()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Load and filter assessments
    all_assessments = load_assessments(client_code, req_id)
    selected = filter_assessments(all_assessments, min_tier=min_tier)

    if not selected:
        raise HTTPException(
            status_code=400,
            detail=f"No candidates found at the selected tier ({TIER_NAMES.get(min_tier)}). "
                   f"Try a lower threshold.",
        )

    # Build recruiter config (form overrides settings)
    base_recruiter = dict(settings.get("recruiter", {}))
    recruiter = {
        "name": recruiter_name.strip() or base_recruiter.get("name", "[Recruiter Name]"),
        "title": base_recruiter.get("title", "Senior Recruitment Consultant"),
        "email": recruiter_email.strip() or base_recruiter.get("email", ""),
        "phone": recruiter_phone.strip() or base_recruiter.get("phone", ""),
        "agency": base_recruiter.get("agency", "Archtekt Consulting Inc."),
    }

    # Generate drafts
    drafts = []
    for assessment in selected:
        email_text = generate_email_draft(assessment, req_config, client_info, recruiter)
        drafts.append((assessment, email_text))

    # Save files
    correspondence_path = get_correspondence_path(client_code, req_id)
    individual = output_format in ("individual", "both")
    combined = output_format in ("combined", "both")

    saved_paths = save_invitations(
        drafts,
        correspondence_path,
        combined=combined,
        individual=individual,
        req_id=req_id,
    )

    # Prepare preview data for template
    draft_previews = []
    for assessment, email_text in drafts:
        cand = assessment.get("candidate", {})
        draft_previews.append({
            "name": cand.get("name", "Unknown"),
            "email": cand.get("email", ""),
            "recommendation": assessment.get("recommendation", ""),
            "percentage": assessment.get("percentage", 0),
            "name_normalized": cand.get("name_normalized", ""),
            "text": email_text,
        })

    saved_filenames = [p.name for p in saved_paths]

    return templates.TemplateResponse(
        "correspondence/invitations_result.html",
        {
            "request": request,
            "user": getattr(request.state, "user", None),
            "client_code": client_code,
            "req_id": req_id,
            "req_title": req_config.get("job", {}).get("title", req_id),
            "client_name": client_info.get("company_name", client_code),
            "drafts": draft_previews,
            "saved_filenames": saved_filenames,
            "total": len(drafts),
        },
    )


@router.get("/{client_code}/{req_id}/invitations/download/{filename}")
async def download_invitation(client_code: str, req_id: str, filename: str):
    """Download a saved invitation file."""
    # Sanitize filename - no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    correspondence_path = get_correspondence_path(client_code, req_id)
    file_path = correspondence_path / "interview_invitations" / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="text/plain",
    )
