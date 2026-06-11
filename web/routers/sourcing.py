"""
Indeed Smart Sourcing routes for RAAF.

Provides AI-powered boolean search query generation for Indeed Smart Sourcing
and a simple form to manually add candidates found via Smart Sourcing back into
RAAF.  No Indeed API calls are made — the recruiter opens search URLs in their
browser and manually adds candidates they find.
"""

import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from scripts.utils.client_utils import (
    get_client_info,
    get_requisition_config,
    get_requisition_root,
)

try:
    from scripts.utils.database import _use_database, get_db
except ImportError:
    def _use_database() -> bool: return False  # noqa: E704
    def get_db(): return None  # noqa: E704

# Run migration 002 lazily so the table always exists.
# Use importlib because the filename starts with a digit (invalid Python identifier).
try:
    import importlib.util as _ilu
    _mig_path = Path(__file__).parent.parent.parent / "scripts" / "migrate" / "002_sourcing_sessions.py"
    _spec = _ilu.spec_from_file_location("migration_002", str(_mig_path))
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.upgrade()
except Exception:
    pass  # DB may not exist yet — the router handles missing table gracefully at runtime


router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Normalize a candidate name to a safe filesystem-friendly key."""
    substitutions = {
        "ä": "ae", "Ä": "ae", "ö": "oe", "Ö": "oe",
        "ü": "ue", "Ü": "ue", "ß": "ss",
        "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae",
        "å": "a", "Å": "a",
    }
    for char, replacement in substitutions.items():
        name = name.replace(char, replacement)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = name.lower().replace(" ", "_").replace("-", "_")
    name = "".join(c for c in name if c.isalnum() or c == "_")
    return name.strip("_")


def _load_jd_text(client_code: str, req_id: str) -> str:
    """
    Try to read job description text for the requisition.

    Looks for:
      1. job_description.txt (pre-extracted plain text)
      2. job_description.pdf  (extracted via pdf_reader)
      3. job_description.docx (extracted via docx_reader)

    Returns empty string if nothing is found.
    """
    req_root = get_requisition_root(client_code, req_id)

    # Plain text first (fastest)
    txt_path = req_root / "job_description.txt"
    if txt_path.exists():
        try:
            return txt_path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            pass

    # PDF
    pdf_path = req_root / "job_description.pdf"
    if pdf_path.exists():
        try:
            from scripts.utils.pdf_reader import extract_text
            return extract_text(str(pdf_path)).strip()
        except Exception:
            pass

    # DOCX
    docx_path = req_root / "job_description.docx"
    if docx_path.exists():
        try:
            from scripts.utils.docx_reader import extract_text as extract_docx
            return extract_docx(str(docx_path)).strip()
        except Exception:
            pass

    return ""


def _load_framework_text(client_code: str, req_id: str) -> str:
    """Read the assessment framework markdown if present (for AI context)."""
    req_root = get_requisition_root(client_code, req_id)
    fw_path = req_root / "framework" / "assessment_framework.md"
    if fw_path.exists():
        try:
            return fw_path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            pass
    return ""


def _load_sourced_candidates(client_code: str, req_id: str) -> list[dict]:
    """
    Return candidates in this requisition whose source_platform contains
    'Smart Sourcing', by scanning assessment directories.
    """
    sourced = []
    req_root = get_requisition_root(client_code, req_id)
    batches_dir = req_root / "resumes" / "batches" / "sourced" / "extracted"
    if not batches_dir.exists():
        return sourced

    assessments_dir = req_root / "assessments" / "individual"
    for txt_file in sorted(batches_dir.glob("*_resume.txt")):
        name_normalized = txt_file.stem.replace("_resume", "")
        display_name = name_normalized.replace("_", " ").title()

        # Try to read contact info from stub file
        email = ""
        phone = ""
        added_date = ""
        try:
            content = txt_file.read_text(encoding="utf-8", errors="ignore")
            for line in content.splitlines():
                if line.startswith("Email:"):
                    email = line.split(":", 1)[1].strip()
                elif line.startswith("Phone:"):
                    phone = line.split(":", 1)[1].strip()
        except Exception:
            pass

        try:
            added_date = datetime.fromtimestamp(txt_file.stat().st_mtime).strftime("%Y-%m-%d")
        except Exception:
            pass

        assessed = (assessments_dir / f"{name_normalized}_assessment.json").exists()

        sourced.append({
            "name_normalized": name_normalized,
            "name": display_name,
            "email": email,
            "phone": phone,
            "added_date": added_date,
            "assessed": assessed,
        })

    return sourced


def _load_sessions(client_code: str, req_id: str) -> list[dict]:
    """Load previous sourcing sessions from DB — returns [] on any error."""
    try:
        if _use_database():
            db = get_db()
            return db.list_sourcing_sessions(client_code, req_id)
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/sourcing/{client_code}/{req_id}", response_class=HTMLResponse)
async def sourcing_index(request: Request, client_code: str, req_id: str):
    """Show the Smart Sourcing page for a requisition."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_info = get_client_info(client_code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    sessions = _load_sessions(client_code, req_id)
    sourced_candidates = _load_sourced_candidates(client_code, req_id)

    return templates.TemplateResponse("sourcing/index.html", {
        "request": request,
        "user": getattr(request.state, "user", None),
        "client_code": client_code,
        "req_id": req_id,
        "client_name": client_info.get("company_name", client_code),
        "req_title": req_config.get("job", {}).get("title", req_id),
        "req_location": req_config.get("job", {}).get("location", ""),
        "sessions": sessions,
        "sourced_candidates": sourced_candidates,
        "added": request.query_params.get("added") == "1",
    })


@router.post("/sourcing/{client_code}/{req_id}/generate")
async def generate_queries(request: Request, client_code: str, req_id: str):
    """
    Generate AI-powered Indeed Smart Sourcing boolean queries for this requisition.

    Returns JSON: {"queries": [...], "session_ids": [...]}
    Each query dict: {name, query, location, rationale, search_url}
    """
    try:
        req_config = get_requisition_config(client_code, req_id)
    except Exception as e:
        return JSONResponse(status_code=404, content={"error": str(e)})

    job_title = req_config.get("job", {}).get("title", req_id)
    location = req_config.get("job", {}).get("location", "Canada")

    jd_text = _load_jd_text(client_code, req_id)
    if not jd_text:
        jd_text = f"Role: {job_title}\nLocation: {location}"

    framework_text = _load_framework_text(client_code, req_id)

    try:
        from web.services.smart_sourcing import SmartSourcingService
        service = SmartSourcingService()
        queries = await service.generate_queries(
            jd_text=jd_text,
            job_title=job_title,
            location=location,
            framework_text=framework_text,
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Query generation failed: {str(e)}"})

    # Build search URLs and persist sessions
    session_ids = []
    enriched_queries = []
    for q in queries:
        try:
            search_url = service.build_search_url(q["query"], q.get("location", location))
        except Exception:
            search_url = ""
        try:
            linkedin_url = service.build_linkedin_url(q["query"], q.get("location", location))
        except Exception:
            linkedin_url = ""
        enriched = {**q, "search_url": search_url, "linkedin_url": linkedin_url}
        enriched_queries.append(enriched)

        # Persist to DB
        try:
            if _use_database():
                db = get_db()
                sid = db.create_sourcing_session(
                    client_code=client_code,
                    requisition_id=req_id,
                    query=q["query"],
                    search_url=search_url,
                    location=q.get("location", location),
                    rationale=q.get("rationale", ""),
                    query_name=q.get("name", ""),
                )
                session_ids.append(sid)
        except Exception:
            pass

    return JSONResponse(content={"queries": enriched_queries, "session_ids": session_ids})


@router.post("/sourcing/{client_code}/{req_id}/add-candidate")
async def add_sourced_candidate(
    request: Request,
    client_code: str,
    req_id: str,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    query_used: str = Form(""),
    notes: str = Form(""),
):
    """
    Add a candidate found via Indeed Smart Sourcing into RAAF.

    Creates a stub resume text file in resumes/batches/sourced/extracted/
    and upserts to the candidates DB table.
    """
    try:
        req_config = get_requisition_config(client_code, req_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Candidate name is required.")

    name_normalized = _normalize_name(name)
    if not name_normalized:
        raise HTTPException(status_code=400, detail="Could not normalize candidate name.")

    # Create stub resume file in sourced batch folder
    req_root = get_requisition_root(client_code, req_id)
    sourced_extracted = req_root / "resumes" / "batches" / "sourced" / "extracted"
    sourced_extracted.mkdir(parents=True, exist_ok=True)

    stub_path = sourced_extracted / f"{name_normalized}_resume.txt"
    stub_lines = [
        "[Sourced from Indeed Smart Sourcing]",
        f"Name: {name}",
        f"Email: {email}",
        f"Phone: {phone}",
        f"Query Used: {query_used}",
        f"Notes: {notes}",
        f"Added: {datetime.now().strftime('%Y-%m-%d')}",
    ]
    stub_path.write_text("\n".join(stub_lines), encoding="utf-8")

    # Upsert to DB when enabled
    try:
        if _use_database():
            db = get_db()
            db.upsert_candidate({
                "req_id": req_id,
                "name": name,
                "name_normalized": name_normalized,
                "email": email or None,
                "phone": phone or None,
                "source_platform": "Indeed Smart Sourcing",
                "batch": "sourced",
                "resume_extracted_path": str(stub_path),
            })
    except Exception:
        pass

    return RedirectResponse(
        url=f"/sourcing/{client_code}/{req_id}?added=1",
        status_code=303,
    )


@router.post("/sourcing/{client_code}/{req_id}/prescreen")
async def prescreen_candidate(request: Request, client_code: str, req_id: str):
    """
    Pre-screen a candidate profile snippet before paying for an Indeed unlock.

    Accepts JSON body: {"snippet": "<visible profile text from Indeed>"}
    Returns JSON:  {"score": int, "unlock": bool, "verdict": str, "reasons": [...]}
    """
    try:
        req_config = get_requisition_config(client_code, req_id)
    except Exception as e:
        return JSONResponse(status_code=404, content={"error": str(e)})

    try:
        body = await request.json()
        snippet = (body.get("snippet") or "").strip()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Request body must be JSON with a 'snippet' field."})

    if not snippet:
        return JSONResponse(status_code=400, content={"error": "snippet is required."})

    job_title = req_config.get("job", {}).get("title", req_id)
    jd_text = _load_jd_text(client_code, req_id)
    framework_text = _load_framework_text(client_code, req_id)

    try:
        from web.services.smart_sourcing import SmartSourcingService
        service = SmartSourcingService()
        result = await service.prescreen_snippet(
            snippet=snippet,
            job_title=job_title,
            jd_text=jd_text,
            framework_text=framework_text,
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Pre-screen failed: {e}"})

    return JSONResponse(content=result)
