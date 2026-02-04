"""
Search routes for RAAF Web Application.
Provides candidate repository search functionality.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from scripts.utils.candidate_search import (
    load_candidate_repository,
    search_candidates,
    search_candidates_simple,
    search_by_name,
    search_by_text,
    get_repository_stats
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def search_page(request: Request):
    """Search landing page with JD upload form."""
    # Get repository stats for display
    try:
        stats = get_repository_stats()
    except Exception:
        stats = {"total_candidates": 0, "by_recommendation": {}, "avg_score": 0}

    return templates.TemplateResponse("search/index.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "stats": stats
    })


@router.post("/", response_class=HTMLResponse)
async def search_candidates_post(
    request: Request,
    jd_text: str = Form(None),
    jd_file: UploadFile = File(None),
    use_ai: bool = Form(True),
    top_n: int = Form(20)
):
    """Execute search and show results."""
    # Get job description text
    job_description = ""

    if jd_file and jd_file.filename:
        content = await jd_file.read()
        file_ext = Path(jd_file.filename).suffix.lower()

        try:
            if file_ext == '.pdf':
                # Save temp file and extract
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name

                from scripts.utils.pdf_reader import extract_text
                job_description = extract_text(tmp_path)
                Path(tmp_path).unlink()

            elif file_ext == '.docx':
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name

                from scripts.utils.docx_reader import extract_text as extract_docx
                job_description = extract_docx(tmp_path)
                Path(tmp_path).unlink()

            else:
                job_description = content.decode('utf-8', errors='ignore')

        except Exception as e:
            return templates.TemplateResponse("search/results.html", {
                "request": request,
                "user": getattr(request.state, 'user', None),
                "error": f"Failed to extract text from file: {str(e)}",
                "results": [],
                "job_description": ""
            })

    elif jd_text:
        job_description = jd_text.strip()

    if not job_description:
        return templates.TemplateResponse("search/index.html", {
            "request": request,
            "user": getattr(request.state, 'user', None),
            "error": "Please provide a job description (paste text or upload file)",
            "stats": get_repository_stats()
        })

    # Load candidates
    try:
        candidates = load_candidate_repository()
    except Exception as e:
        return templates.TemplateResponse("search/results.html", {
            "request": request,
            "user": getattr(request.state, 'user', None),
            "error": f"Failed to load candidate repository: {str(e)}",
            "results": [],
            "job_description": job_description[:500]
        })

    if not candidates:
        return templates.TemplateResponse("search/results.html", {
            "request": request,
            "user": getattr(request.state, 'user', None),
            "error": "No assessed candidates found in the repository",
            "results": [],
            "job_description": job_description[:500]
        })

    # Perform search
    try:
        if use_ai:
            results = search_candidates(
                job_description=job_description,
                candidates=candidates,
                top_n=top_n
            )
        else:
            results = search_candidates_simple(
                job_description=job_description,
                candidates=candidates
            )[:top_n]

    except Exception as e:
        # Fall back to simple search on AI failure
        try:
            results = search_candidates_simple(
                job_description=job_description,
                candidates=candidates
            )[:top_n]
        except Exception:
            return templates.TemplateResponse("search/results.html", {
                "request": request,
                "user": getattr(request.state, 'user', None),
                "error": f"Search failed: {str(e)}",
                "results": [],
                "job_description": job_description[:500]
            })

    return templates.TemplateResponse("search/results.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "results": results,
        "total_searched": len(candidates),
        "job_description": job_description[:500] + ("..." if len(job_description) > 500 else ""),
        "use_ai": use_ai
    })


@router.get("/api/search")
async def api_search(
    jd_text: str,
    use_ai: bool = True,
    top_n: int = 20
):
    """JSON API for search results."""
    if not jd_text:
        raise HTTPException(status_code=400, detail="jd_text parameter is required")

    try:
        candidates = load_candidate_repository()

        if use_ai:
            results = search_candidates(
                job_description=jd_text,
                candidates=candidates,
                top_n=top_n
            )
        else:
            results = search_candidates_simple(
                job_description=jd_text,
                candidates=candidates
            )[:top_n]

        return {
            "total_searched": len(candidates),
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stats")
async def api_stats():
    """Get repository statistics."""
    try:
        stats = get_repository_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quick", response_class=HTMLResponse)
async def quick_search(
    request: Request,
    q: str = "",
    search_type: str = "all"
):
    """
    Quick search by name or skills/keywords.

    Args:
        q: Search query
        search_type: 'all', 'name', or 'skills'
    """
    # Get repository stats for display
    try:
        stats = get_repository_stats()
    except Exception:
        stats = {"total_candidates": 0, "by_recommendation": {}, "avg_score": 0}

    if not q:
        # Show search form without results
        return templates.TemplateResponse("search/index.html", {
            "request": request,
            "user": getattr(request.state, 'user', None),
            "stats": stats,
            "quick_search": True,
            "search_query": "",
            "search_type": search_type
        })

    # Load candidates once
    try:
        candidates = load_candidate_repository()
    except Exception as e:
        return templates.TemplateResponse("search/quick_results.html", {
            "request": request,
            "user": getattr(request.state, 'user', None),
            "error": f"Failed to load candidate repository: {str(e)}",
            "results": [],
            "search_query": q,
            "search_type": search_type
        })

    results = []

    if search_type == "name":
        # Search by name only
        results = search_by_name(q, candidates)
    elif search_type == "skills":
        # Search by skills/text only (excluding name field)
        results = search_by_text(q, candidates, search_fields=['summary', 'strengths', 'resume'])
    else:
        # Search all - combine name and text search
        name_results = search_by_name(q, candidates)
        text_results = search_by_text(q, candidates)

        # Merge results, avoiding duplicates (prefer text results with scores)
        seen_ids = set()
        for r in text_results:
            results.append(r)
            seen_ids.add(r["candidate_id"])

        for r in name_results:
            if r["candidate_id"] not in seen_ids:
                # Add a match score for name-only results
                r["match_score"] = 100
                r["matched_keywords"] = [q]
                r["recommendation"] = "strong_match"
                results.append(r)

        # Sort combined results by match score
        results.sort(key=lambda x: x.get("match_score", 100), reverse=True)

    return templates.TemplateResponse("search/quick_results.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "results": results,
        "total_searched": len(candidates),
        "search_query": q,
        "search_type": search_type
    })


@router.get("/api/quick")
async def api_quick_search(
    q: str,
    search_type: str = "all"
):
    """
    JSON API for quick search.

    Args:
        q: Search query
        search_type: 'all', 'name', or 'skills'
    """
    if not q:
        raise HTTPException(status_code=400, detail="q parameter is required")

    try:
        candidates = load_candidate_repository()

        if search_type == "name":
            results = search_by_name(q, candidates)
        elif search_type == "skills":
            results = search_by_text(q, candidates, search_fields=['summary', 'strengths', 'resume'])
        else:
            # Combine name and text search
            name_results = search_by_name(q, candidates)
            text_results = search_by_text(q, candidates)

            seen_ids = set()
            results = []
            for r in text_results:
                results.append(r)
                seen_ids.add(r["candidate_id"])

            for r in name_results:
                if r["candidate_id"] not in seen_ids:
                    r["match_score"] = 100
                    r["matched_keywords"] = [q]
                    r["recommendation"] = "strong_match"
                    results.append(r)

            results.sort(key=lambda x: x.get("match_score", 100), reverse=True)

        return {
            "total_searched": len(candidates),
            "query": q,
            "search_type": search_type,
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
