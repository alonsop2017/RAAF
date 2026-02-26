"""
RAAF Web Application - MVP
Resume Assessment Automation Framework Web Interface
"""

import os
import sys
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

from web.routers import clients, requisitions, candidates, assessments, reports, pcr, search, correspondence
from web.routers import auth as auth_router, admin as admin_router
from web.auth.oauth import setup_oauth
from web.auth.session import session_manager
from web.auth.config import get_session_secret_key, get_admin_emails

app = FastAPI(
    title="RAAF - Resume Assessment Automation Framework",
    description="Web interface for managing candidate assessments",
    version="1.0.0"
)

# Add session middleware for OAuth state (required by Authlib)
# Use a fallback secret for development if not set
session_secret = get_session_secret_key() or "dev-secret-change-in-production"
app.add_middleware(SessionMiddleware, secret_key=session_secret)

# Setup OAuth
setup_oauth()

# Mount static files
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


# Authentication middleware
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """
    Middleware to check authentication and redirect to login if needed.
    Allows access to auth routes, static files, and health check without auth.
    Set DEV_MODE=1 to bypass authentication for local development.
    """
    dev_mode = os.environ.get("DEV_MODE", "0") == "1"

    # Paths that don't require authentication
    public_paths = ["/auth", "/static", "/health"]

    # Check if path is public
    path = request.url.path
    is_public = any(path.startswith(p) for p in public_paths)

    if dev_mode:
        # Bypass auth in dev mode with a default user
        request.state.user = {
            "email": "dev@localhost",
            "name": "Dev User",
            "given_name": "Dev",
            "family_name": "User",
        }
    elif not is_public:
        # Check for valid session
        user = session_manager.get_user_from_cookies(request.cookies)
        if not user:
            return RedirectResponse(url="/auth/login", status_code=302)
        # Attach user to request state for use in routes
        request.state.user = user
    else:
        # Still try to get user for public pages (e.g., login page redirect)
        request.state.user = session_manager.get_user_from_cookies(request.cookies)

    # Set admin flag on request state
    user = getattr(request.state, 'user', None)
    if user:
        email = user.get("email", "").lower()
        request.state.is_admin = email in get_admin_emails()
    else:
        request.state.is_admin = False

    response = await call_next(request)
    return response


# Include routers
app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(clients.router, prefix="/clients", tags=["clients"])
app.include_router(requisitions.router, prefix="/requisitions", tags=["requisitions"])
app.include_router(candidates.router, prefix="/candidates", tags=["candidates"])
app.include_router(assessments.router, prefix="/assessments", tags=["assessments"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(pcr.router, prefix="/pcr", tags=["pcr"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(correspondence.router, prefix="/correspondence", tags=["correspondence"])
app.include_router(admin_router.router, prefix="/admin", tags=["admin"])


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard showing overview of all clients and requisitions."""
    from scripts.utils.database import get_db, _use_database

    dashboard_data = []
    total_candidates = 0
    total_assessed = 0

    if _use_database():
        # Single query replaces the nested client/requisition file loop
        rows = get_db().get_dashboard_data()
        clients_seen: dict = {}
        for row in rows:
            cc = row["client_code"]
            candidate_count = row.get("candidate_count", 0)
            assessed_count = row.get("assessed_count", 0)
            total_candidates += candidate_count
            total_assessed += assessed_count
            req_entry = {
                "req_id": row["req_id"],
                "title": row["job_title"],
                "status": row["req_status"],
                "candidate_count": candidate_count,
                "assessed_count": assessed_count,
            }
            if cc not in clients_seen:
                clients_seen[cc] = {
                    "client_code": cc,
                    "client_name": row["company_name"],
                    "status": row["client_status"],
                    "requisitions": [],
                }
                dashboard_data.append(clients_seen[cc])
            clients_seen[cc]["requisitions"].append(req_entry)
    else:
        from scripts.utils.client_utils import (
            list_clients, list_requisitions, get_client_info, get_requisition_config,
            get_requisition_root, count_unique_candidates,
        )
        for client_code in list_clients():
            try:
                client_config = get_client_info(client_code)
                client_name = client_config.get("company_name", client_code)
                client_reqs = []
                for req_id in list_requisitions(client_code):
                    try:
                        req_config = get_requisition_config(client_code, req_id)
                        req_root = get_requisition_root(client_code, req_id)
                        candidate_count = count_unique_candidates(client_code, req_id)
                        assessments_dir = req_root / "assessments" / "individual"
                        assessed_count = len([
                            f for f in assessments_dir.glob("*.json")
                            if not f.stem.endswith("_lifecycle")
                        ]) if assessments_dir.exists() else 0
                        total_candidates += candidate_count
                        total_assessed += assessed_count
                        client_reqs.append({
                            "req_id": req_id,
                            "title": req_config.get("job", {}).get("title", req_id),
                            "status": req_config.get("status", "unknown"),
                            "candidate_count": candidate_count,
                            "assessed_count": assessed_count,
                        })
                    except Exception:
                        continue
                if client_reqs:
                    dashboard_data.append({
                        "client_code": client_code,
                        "client_name": client_name,
                        "requisitions": client_reqs,
                        "status": client_config.get("status", "active"),
                    })
            except Exception:
                continue

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "clients": dashboard_data,
        "total_clients": len(dashboard_data),
        "total_requisitions": sum(len(c["requisitions"]) for c in dashboard_data),
        "total_candidates": total_candidates,
        "total_assessed": total_assessed,
    })


@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    """How It Works page with workflow diagram and scoring reference."""
    return templates.TemplateResponse("help.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
    })


@app.get("/help/user-guide")
async def download_user_guide():
    """Serve the RAAF User Guide PDF for download."""
    pdf_path = Path(__file__).parent.parent / "docs" / "RAAF_User_Guide.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="User guide not found")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename="RAAF_User_Guide.pdf",
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
