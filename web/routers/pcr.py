"""
PCRecruiter integration routes for RAAF Web Application.
"""

import asyncio
import sys
from functools import partial
from pathlib import Path
import subprocess
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from scripts.utils.client_utils import (
    get_requisition_config, get_client_info, get_project_root,
    list_clients, list_requisitions
)

# Alias for consistency
get_client_config = get_client_info

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def run_pcr_script(script_name: str, *args, timeout: int = 60):
    """Run a PCR script and return results. Raises subprocess.TimeoutExpired if it takes too long."""
    script_path = get_project_root() / "scripts" / "pcr" / script_name

    cmd = ["python3", str(script_path)] + list(args)
    env = {**__import__('os').environ, "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(get_project_root()),
            env=env,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Script timed out after {timeout}s — PCR API may be unreachable"


def run_pcr_script_async(script_name: str, *args):
    """Run a PCR script in the background. Returns the Popen object."""
    import os
    script_path = get_project_root() / "scripts" / "pcr" / script_name
    log_dir = get_project_root() / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "pcr_sync.log"

    cmd = ["python3", str(script_path)] + list(args)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    with open(log_file, "a") as lf:
        lf.write(f"\n[{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                 f"Starting: {script_name} {' '.join(args)}\n")
        lf.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=subprocess.STDOUT,
            cwd=str(get_project_root()),
            env=env,
        )
    return proc


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
                    positions = pcr_info.get('positions', [])
                    first_pos_id = positions[0].get('position_id', '') if positions else ''
                    pcr_requisitions.append({
                        'client_code': client_code,
                        'client_name': client_config.get('company_name', client_code),
                        'req_id': req_id,
                        'title': req_config.get('job', {}).get('title', req_id),
                        'pcr_job_id': pcr_info.get('job_id'),
                        'pcr_position_id': first_pos_id,
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


@router.get("/api/positions")
async def api_list_positions(request: Request, search: str = Query(""), include_closed: bool = Query(False)):
    """Return PCR positions as JSON, filtered by company name."""
    search_lower = search.strip().lower()
    if not search_lower:
        return JSONResponse([])

    def _fetch_all_positions():
        from scripts.utils.pcr_client import PCRClient
        from concurrent.futures import ThreadPoolExecutor
        import requests as http_requests
        from urllib.parse import urljoin
        from scripts.utils.database import get_db, _use_database

        client = PCRClient()
        client.ensure_authenticated()
        headers = client._get_headers()

        # DB cache fast path
        if _use_database():
            try:
                cached = get_db().get_cached_pcr_positions(max_age_seconds=3600)
                if cached is not None:
                    return cached, client, headers
            except Exception:
                pass

        url = urljoin(client.base_url + "/", "positions")

        def fetch_page(page: int) -> tuple:
            r = http_requests.get(
                url, headers=headers,
                params={"ResultsPerPage": 500, "Page": page, "Status": "Open"},
                timeout=30,
            )
            data = r.json()
            return data.get("Results", []), data.get("TotalRecords")

        first_results, total = fetch_page(1)
        if total is None:
            total = 5000
        max_pages = (total + 499) // 500
        all_positions = list(first_results)

        if max_pages > 1:
            with ThreadPoolExecutor(max_workers=min(max_pages - 1, 20)) as executor:
                extra_pages = list(executor.map(fetch_page, range(2, max_pages + 1)))
            for results, _ in extra_pages:
                all_positions.extend(results)

        if _use_database():
            try:
                get_db().cache_pcr_positions(all_positions)
            except Exception:
                pass

        return all_positions, client, headers

    try:
        all_positions, client, headers = await asyncio.to_thread(_fetch_all_positions)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    import fnmatch

    def _matches(company: str, pattern: str) -> bool:
        """Match company name against pattern.

        Supports explicit wildcards (* and ?) via fnmatch.  When no wildcards
        are present every space-separated word in the pattern must appear
        somewhere in the company name (case-insensitive), so a search like
        "Cataldi Fresh Market" will match "Cataldi Fresh Markets Ltd".
        """
        c = company.lower()
        p = pattern.lower().strip()
        if not p:
            return True
        if "*" in p or "?" in p:
            # Wrap with * so the pattern is a contains-style glob
            glob = p if p.startswith("*") else "*" + p
            if not glob.endswith("*"):
                glob += "*"
            return fnmatch.fnmatch(c, glob)
        # Word-based: every token must appear in the company name
        return all(word in c for word in p.split())

    # Filter by company name first
    matched = []
    for pos in all_positions:
        company = pos.get("CompanyName", "") or ""
        if not _matches(company, search_lower):
            continue
        status = (pos.get("Status") or "").strip()
        if status and status.lower() not in ("open", "active"):
            continue
        matched.append(pos)

    if not matched:
        return JSONResponse([])

    def _fetch_details(positions, pcr_client, pcr_headers):
        import requests as _req
        from urllib.parse import urljoin as _urljoin
        from concurrent.futures import ThreadPoolExecutor as _TPE

        def fetch_one(pos):
            job_id = pos.get("JobId", "")
            position_id = ""
            detail_status = (pos.get("Status") or "").strip()
            if job_id:
                try:
                    url = _urljoin(pcr_client.base_url + "/", f"positions/{job_id}")
                    r = _req.get(url, headers=pcr_headers, timeout=15)
                    detail = r.json()
                    position_id = detail.get("PositionId") or ""
                    detail_status = (detail.get("Status") or detail_status).strip()
                except Exception:
                    pass
            return {
                "job_id": job_id,
                "position_id": position_id,
                "title": pos.get("JobTitle", pos.get("Title", "")),
                "company": pos.get("CompanyName", "") or "",
                "location": pos.get("City", ""),
                "status": detail_status,
            }

        with _TPE(max_workers=min(len(positions), 20)) as ex:
            return list(ex.map(fetch_one, positions))

    try:
        results = await asyncio.to_thread(_fetch_details, matched, client, headers)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    if not include_closed:
        results = [r for r in results if (r.get("status") or "").lower() != "closed"]

    return JSONResponse(results)


@router.get("/positions", response_class=HTMLResponse)
async def list_pcr_positions(request: Request):
    """List available positions from PCR."""
    def _fetch_positions():
        import sqlite3 as _sqlite3
        from scripts.utils.pcr_client import PCRClient, PCRClientError

        # Load PCR job IDs for active requisitions from the DB
        linked: dict[str, dict] = {}  # pcr_job_id -> requisition info
        db_path = get_project_root() / "data" / "raaf.db"
        if db_path.exists():
            try:
                conn = _sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                rows = conn.execute(
                    "SELECT req_id, pcr_job_id FROM requisitions "
                    "WHERE status='active' AND pcr_job_id IS NOT NULL"
                ).fetchall()
                conn.close()
                linked = {str(row[1]): {"req_id": row[0]} for row in rows}
            except Exception:
                pass

        client = PCRClient()
        client.ensure_authenticated()
        page = client.get_positions(status="Open", limit=200, offset=0)

        results = []
        for p in (page or []):
            job_id = str(p.get("JobId", ""))
            req_info = linked.get(job_id, {})
            results.append({
                "job_id": job_id,
                "position_id": p.get("PositionId", ""),
                "title": p.get("JobTitle") or p.get("Title", ""),
                "company": p.get("CompanyName", ""),
                "location": p.get("City", ""),
                "status": p.get("Status", "Open"),
                "req_id": req_info.get("req_id", ""),
                "linked": bool(req_info),
            })

        # Sort: linked requisitions first, then unlinked
        results.sort(key=lambda x: (not x["linked"], x["title"]))
        return results

    try:
        positions = await asyncio.wait_for(
            asyncio.to_thread(_fetch_positions),
            timeout=60,
        )
    except asyncio.TimeoutError:
        return templates.TemplateResponse("pcr/error.html", {
            "request": request,
            "user": getattr(request.state, 'user', None),
            "error": "PCR API timed out after 60 seconds. The PCR server may be slow — please try again.",
        })
    except Exception as e:
        return templates.TemplateResponse("pcr/error.html", {
            "request": request,
            "user": getattr(request.state, 'user', None),
            "error": str(e),
        })

    return templates.TemplateResponse("pcr/positions.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "positions": positions,
    })


@router.post("/sync-candidates")
async def sync_candidates(
    request: Request,
    client_code: str = Form(...),
    req_id: str = Form(...)
):
    """Sync candidates from PCR for a requisition (runs in background)."""
    run_pcr_script_async(
        "sync_candidates.py",
        "--client", client_code,
        "--req", req_id
    )
    return RedirectResponse(
        url=f"/requisitions/{client_code}/{req_id}?pcr_sync=started",
        status_code=303
    )


@router.post("/download-resumes")
async def download_resumes(
    request: Request,
    client_code: str = Form(...),
    req_id: str = Form(...)
):
    """Download resumes from PCR for a requisition (runs in background with auto-assess)."""
    run_pcr_script_async(
        "download_resumes.py",
        "--client", client_code,
        "--req", req_id,
        "--auto-assess"
    )
    return RedirectResponse(
        url=f"/requisitions/{client_code}/{req_id}?download=started",
        status_code=303
    )


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
        "has_pcr_link": bool(pcr_info.get('job_id'))
    })
