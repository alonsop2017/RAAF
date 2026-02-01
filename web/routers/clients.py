"""
Client management routes for RAAF Web Application.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import yaml

from scripts.utils.client_utils import (
    list_clients, get_client_info, get_client_root,
    get_project_root, list_requisitions, get_requisition_config
)

# Alias for consistency
get_client_config = get_client_info

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def list_all_clients(request: Request):
    """List all clients."""
    clients_data = []

    for client_code in list_clients():
        try:
            config = get_client_config(client_code)
            req_count = len(list_requisitions(client_code))
            clients_data.append({
                'code': client_code,
                'name': config.get('company_name', client_code),
                'industry': config.get('industry', 'N/A'),
                'status': config.get('status', 'active'),
                'requisition_count': req_count
            })
        except Exception:
            continue

    return templates.TemplateResponse("clients/list.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "clients": clients_data
    })


@router.get("/new", response_class=HTMLResponse)
async def new_client_form(request: Request):
    """Show form to create a new client."""
    return templates.TemplateResponse("clients/new.html", {
        "request": request,
        "user": getattr(request.state, 'user', None)
    })


@router.post("/create")
async def create_client(
    request: Request,
    code: str = Form(...),
    company_name: str = Form(...),
    industry: str = Form(""),
    primary_contact_name: str = Form(""),
    primary_contact_email: str = Form(""),
    primary_contact_phone: str = Form(""),
    commission_rate: float = Form(0.20)
):
    """Create a new client."""
    # Validate code
    code = code.lower().replace(" ", "_")

    if code in list_clients():
        raise HTTPException(status_code=400, detail=f"Client '{code}' already exists")

    # Create client directory
    client_root = get_client_root(code)
    client_root.mkdir(parents=True, exist_ok=True)
    (client_root / "requisitions").mkdir(exist_ok=True)

    # Create client_info.yaml
    client_info = {
        'client_code': code,
        'company_name': company_name,
        'industry': industry,
        'status': 'active',
        'contacts': {
            'primary': {
                'name': primary_contact_name,
                'email': primary_contact_email,
                'phone': primary_contact_phone
            }
        },
        'billing': {
            'default_commission_rate': commission_rate,
            'payment_terms': 'Net 30'
        },
        'active_requisitions': []
    }

    with open(client_root / "client_info.yaml", 'w') as f:
        yaml.dump(client_info, f, default_flow_style=False)

    return RedirectResponse(url=f"/clients/{code}", status_code=303)


@router.get("/{client_code}", response_class=HTMLResponse)
async def view_client(request: Request, client_code: str):
    """View client details and requisitions."""
    try:
        config = get_client_config(client_code)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Client '{client_code}' not found")

    # Get requisitions with details
    reqs_data = []
    for req_id in list_requisitions(client_code):
        try:
            req_config = get_requisition_config(client_code, req_id)
            from scripts.utils.client_utils import get_requisition_root
            req_root = get_requisition_root(client_code, req_id)

            # Count candidates
            resumes_dir = req_root / "resumes" / "processed"
            candidate_count = len(list(resumes_dir.glob("*.txt"))) if resumes_dir.exists() else 0

            # Count assessments
            assessments_dir = req_root / "assessments" / "individual"
            assessed_count = len(list(assessments_dir.glob("*.json"))) if assessments_dir.exists() else 0

            reqs_data.append({
                'req_id': req_id,
                'title': req_config.get('job', {}).get('title', req_id),
                'status': req_config.get('status', 'active'),
                'location': req_config.get('job', {}).get('location', 'N/A'),
                'candidate_count': candidate_count,
                'assessed_count': assessed_count
            })
        except Exception:
            continue

    return templates.TemplateResponse("clients/view.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "client": config,
        "client_code": client_code,
        "requisitions": reqs_data
    })


@router.get("/{client_code}/edit", response_class=HTMLResponse)
async def edit_client_form(request: Request, client_code: str):
    """Show form to edit a client."""
    try:
        config = get_client_config(client_code)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Client '{client_code}' not found")

    return templates.TemplateResponse("clients/edit.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "client": config,
        "client_code": client_code
    })


@router.post("/{client_code}/update")
async def update_client(
    request: Request,
    client_code: str,
    company_name: str = Form(...),
    industry: str = Form(""),
    status: str = Form("active"),
    primary_contact_name: str = Form(""),
    primary_contact_email: str = Form(""),
    primary_contact_phone: str = Form(""),
    commission_rate: float = Form(0.20)
):
    """Update client information."""
    client_root = get_client_root(client_code)
    config_path = client_root / "client_info.yaml"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Client '{client_code}' not found")

    # Load existing config
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Update fields
    config['company_name'] = company_name
    config['industry'] = industry
    config['status'] = status
    config['contacts']['primary']['name'] = primary_contact_name
    config['contacts']['primary']['email'] = primary_contact_email
    config['contacts']['primary']['phone'] = primary_contact_phone
    config['billing']['default_commission_rate'] = commission_rate

    # Save
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    return RedirectResponse(url=f"/clients/{client_code}", status_code=303)
