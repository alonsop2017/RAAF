"""
Report generation routes for RAAF Web Application.
"""

import sys
from pathlib import Path
from datetime import datetime
import subprocess
import json
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from scripts.utils.client_utils import (
    get_requisition_root, get_requisition_config, get_client_info,
    get_project_root
)

# Alias for consistency
get_client_config = get_client_info

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def generate_report(client_code: str, req_id: str, output_type: str = "final"):
    """Run report generation script."""
    script_path = get_project_root() / "scripts" / "generate_report.js"

    cmd = [
        "node", str(script_path),
        "--client", client_code,
        "--req", req_id,
        "--output-type", output_type
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(get_project_root())
    )

    return result.returncode == 0, result.stdout, result.stderr


@router.get("/{client_code}/{req_id}", response_class=HTMLResponse)
async def reports_dashboard(request: Request, client_code: str, req_id: str):
    """Reports dashboard for a requisition."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_config = get_client_config(client_code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    req_root = get_requisition_root(client_code, req_id)

    # Get all reports
    reports = []
    for folder in ['final', 'drafts']:
        reports_dir = req_root / "reports" / folder
        if reports_dir.exists():
            for report_file in sorted(reports_dir.glob("*.docx"), reverse=True):
                reports.append({
                    'filename': report_file.name,
                    'type': folder,
                    'path': f"{folder}/{report_file.name}",
                    'created': datetime.fromtimestamp(report_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    'size': f"{report_file.stat().st_size / 1024:.1f} KB"
                })

    # Get assessment summary for report preview
    assessments_dir = req_root / "assessments" / "individual"
    assessments = []
    if assessments_dir.exists():
        for assessment_file in assessments_dir.glob("*.json"):
            try:
                with open(assessment_file, 'r') as f:
                    assessment = json.load(f)
                if assessment.get('recommendation') != 'PENDING':
                    assessments.append({
                        'name': assessment.get('candidate', {}).get('name', 'Unknown'),
                        'score': assessment.get('total_score', 0),
                        'percentage': assessment.get('percentage', 0),
                        'recommendation': assessment.get('recommendation', 'N/A')
                    })
            except Exception:
                continue

    assessments.sort(key=lambda x: x['percentage'], reverse=True)

    # Summary stats
    thresholds = req_config.get('assessment', {}).get('thresholds', {
        'strong_recommend': 85,
        'recommend': 70,
        'conditional': 55
    })

    summary = {
        'total': len(assessments),
        'strong_recommend': sum(1 for a in assessments if a['percentage'] >= thresholds['strong_recommend']),
        'recommend': sum(1 for a in assessments if thresholds['recommend'] <= a['percentage'] < thresholds['strong_recommend']),
        'conditional': sum(1 for a in assessments if thresholds['conditional'] <= a['percentage'] < thresholds['recommend']),
        'do_not_recommend': sum(1 for a in assessments if a['percentage'] < thresholds['conditional'])
    }

    return templates.TemplateResponse("reports/dashboard.html", {
        "request": request,
        "client_code": client_code,
        "req_id": req_id,
        "client_name": client_config.get('company_name', client_code),
        "req_title": req_config.get('job', {}).get('title', req_id),
        "reports": reports,
        "assessments": assessments[:10],  # Top 10 for preview
        "summary": summary,
        "can_generate": len(assessments) > 0
    })


@router.post("/{client_code}/{req_id}/generate")
async def generate_new_report(
    request: Request,
    client_code: str,
    req_id: str,
    output_type: str = Form("final")
):
    """Generate a new report."""
    success, stdout, stderr = generate_report(client_code, req_id, output_type)

    if success:
        return RedirectResponse(
            url=f"/reports/{client_code}/{req_id}?generated=1",
            status_code=303
        )
    else:
        return templates.TemplateResponse("reports/error.html", {
            "request": request,
            "client_code": client_code,
            "req_id": req_id,
            "error": stderr or "Report generation failed",
            "output": stdout
        })


@router.get("/{client_code}/{req_id}/download/{folder}/{filename}")
async def download_report(client_code: str, req_id: str, folder: str, filename: str):
    """Download a report file."""
    if folder not in ['final', 'drafts']:
        raise HTTPException(status_code=400, detail="Invalid folder")

    req_root = get_requisition_root(client_code, req_id)
    file_path = req_root / "reports" / folder / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@router.post("/{client_code}/{req_id}/delete/{folder}/{filename}")
async def delete_report(client_code: str, req_id: str, folder: str, filename: str):
    """Delete a report file."""
    if folder not in ['final', 'drafts']:
        raise HTTPException(status_code=400, detail="Invalid folder")

    req_root = get_requisition_root(client_code, req_id)
    file_path = req_root / "reports" / folder / filename

    if file_path.exists():
        file_path.unlink()

    return RedirectResponse(
        url=f"/reports/{client_code}/{req_id}",
        status_code=303
    )
