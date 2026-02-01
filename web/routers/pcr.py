"""
PCRecruiter integration routes for RAAF Web Application.
"""

import sys
from pathlib import Path
import subprocess
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from scripts.utils.client_utils import (
    get_requisition_config, get_client_info, get_project_root,
    list_clients, list_requisitions
)

# Alias for consistency
get_client_config = get_client_info

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def run_pcr_script(script_name: str, *args):
    """Run a PCR script and return results."""
    script_path = get_project_root() / "scripts" / "pcr" / script_name

    cmd = ["python3", str(script_path)] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(get_project_root())
    )

    return result.returncode == 0, result.stdout, result.stderr


def check_pcr_connection():
    """Check if PCR credentials are configured and connection works."""
    try:
        from scripts.utils.pcr_client import PCRClient
        client = PCRClient()
        # Check if credentials file exists
        creds_file = get_project_root() / "config" / "pcr_credentials.yaml"
        return creds_file.exists()
    except Exception:
        return False


@router.get("/", response_class=HTMLResponse)
async def pcr_dashboard(request: Request):
    """PCRecruiter integration dashboard."""
    pcr_configured = check_pcr_connection()

    # Get requisitions with PCR links
    pcr_requisitions = []
    for client_code in list_clients():
        try:
            client_config = get_client_config(client_code)
            for req_id in list_requisitions(client_code):
                req_config = get_requisition_config(client_code, req_id)
                pcr_info = req_config.get('pcr_integration', {})
                if pcr_info:
                    pcr_requisitions.append({
                        'client_code': client_code,
                        'client_name': client_config.get('company_name', client_code),
                        'req_id': req_id,
                        'title': req_config.get('job', {}).get('title', req_id),
                        'pcr_job_id': pcr_info.get('position_id'),
                        'last_sync': pcr_info.get('last_sync', 'Never')
                    })
        except Exception:
            continue

    return templates.TemplateResponse("pcr/dashboard.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "pcr_configured": pcr_configured,
        "requisitions": pcr_requisitions
    })


@router.get("/test", response_class=HTMLResponse)
async def test_connection(request: Request):
    """Test PCR API connection."""
    success, stdout, stderr = run_pcr_script("test_connection.py")

    return templates.TemplateResponse("pcr/test_result.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "success": success,
        "output": stdout,
        "error": stderr
    })


@router.get("/positions", response_class=HTMLResponse)
async def list_pcr_positions(request: Request):
    """List available positions from PCR."""
    success, stdout, stderr = run_pcr_script("sync_positions.py", "--list-only")

    if not success:
        return templates.TemplateResponse("pcr/error.html", {
            "request": request,
            "user": getattr(request.state, 'user', None),
            "error": stderr or "Failed to fetch positions from PCR"
        })

    # Parse positions from output (this is simplified - real implementation would use JSON output)
    positions = []
    for line in stdout.split('\n'):
        if line.strip() and ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                positions.append({
                    'id': parts[0].strip(),
                    'title': parts[1].strip()
                })

    return templates.TemplateResponse("pcr/positions.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "positions": positions
    })


@router.post("/sync-candidates")
async def sync_candidates(
    request: Request,
    client_code: str = Form(...),
    req_id: str = Form(...)
):
    """Sync candidates from PCR for a requisition."""
    success, stdout, stderr = run_pcr_script(
        "sync_candidates.py",
        "--client", client_code,
        "--req", req_id
    )

    if success:
        return RedirectResponse(
            url=f"/requisitions/{client_code}/{req_id}?pcr_sync=1",
            status_code=303
        )
    else:
        raise HTTPException(status_code=500, detail=stderr or "Sync failed")


@router.post("/download-resumes")
async def download_resumes(
    request: Request,
    client_code: str = Form(...),
    req_id: str = Form(...)
):
    """Download resumes from PCR for a requisition."""
    success, stdout, stderr = run_pcr_script(
        "download_resumes.py",
        "--client", client_code,
        "--req", req_id
    )

    if success:
        return RedirectResponse(
            url=f"/candidates/{client_code}/{req_id}?downloaded=1",
            status_code=303
        )
    else:
        raise HTTPException(status_code=500, detail=stderr or "Download failed")


@router.post("/push-scores")
async def push_scores(
    request: Request,
    client_code: str = Form(...),
    req_id: str = Form(...)
):
    """Push assessment scores to PCR."""
    success, stdout, stderr = run_pcr_script(
        "push_scores.py",
        "--client", client_code,
        "--req", req_id
    )

    if success:
        return RedirectResponse(
            url=f"/assessments/{client_code}/{req_id}?pushed=1",
            status_code=303
        )
    else:
        raise HTTPException(status_code=500, detail=stderr or "Push failed")


@router.post("/update-pipeline")
async def update_pipeline(
    request: Request,
    client_code: str = Form(...),
    req_id: str = Form(...)
):
    """Update candidate pipeline statuses in PCR."""
    success, stdout, stderr = run_pcr_script(
        "update_pipeline.py",
        "--client", client_code,
        "--req", req_id
    )

    if success:
        return RedirectResponse(
            url=f"/requisitions/{client_code}/{req_id}?pipeline_updated=1",
            status_code=303
        )
    else:
        raise HTTPException(status_code=500, detail=stderr or "Update failed")


@router.get("/sync/{client_code}/{req_id}", response_class=HTMLResponse)
async def sync_requisition_page(request: Request, client_code: str, req_id: str):
    """Page for syncing a specific requisition with PCR."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_config = get_client_config(client_code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    pcr_info = req_config.get('pcr_integration', {})

    return templates.TemplateResponse("pcr/sync.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "client_code": client_code,
        "req_id": req_id,
        "client_name": client_config.get('company_name', client_code),
        "req_title": req_config.get('job', {}).get('title', req_id),
        "pcr_info": pcr_info,
        "has_pcr_link": bool(pcr_info.get('position_id'))
    })
