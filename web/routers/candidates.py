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
    get_requisition_root, get_requisition_config, get_client_info,
    get_resumes_path, create_batch_folder, get_next_batch_name,
    list_all_extracted_resumes, find_resume_in_batches, get_batch_for_resume,
)
import yaml

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
    # Remove trailing _resume to avoid double suffix when _resume.txt is appended
    if name.endswith('_resume'):
        name = name[:-7]
    elif name.endswith('resume'):
        name = name[:-6]
    # Remove trailing underscores
    name = name.rstrip('_')
    return name


@router.get("/{client_code}/{req_id}", response_class=HTMLResponse)
async def list_candidates(request: Request, client_code: str, req_id: str):
    """List all candidates for a requisition, scanning all batch folders."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_config = get_client_config(client_code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    req_root = get_requisition_root(client_code, req_id)
    assessments_dir = req_root / "assessments" / "individual"

    candidates = []
    seen = set()

    # Scan all batch extracted folders
    for resume_file in list_all_extracted_resumes(client_code, req_id):
        name_normalized = resume_file.stem.replace("_resume", "")
        if name_normalized in seen:
            continue
        seen.add(name_normalized)

        batch_name = resume_file.parent.parent.name  # extracted/ -> batch_dir
        assessment_file = assessments_dir / f"{name_normalized}_assessment.json"

        candidate_data = {
            'name_normalized': name_normalized,
            'resume_file': resume_file.name,
            'batch': batch_name,
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

    # Also check legacy processed/ folder for backwards compatibility
    legacy_dir = req_root / "resumes" / "processed"
    if legacy_dir.exists():
        for resume_file in sorted(legacy_dir.glob("*.txt")):
            name_normalized = resume_file.stem.replace("_resume", "")
            if name_normalized in seen:
                continue
            seen.add(name_normalized)

            assessment_file = assessments_dir / f"{name_normalized}_assessment.json"
            candidate_data = {
                'name_normalized': name_normalized,
                'resume_file': resume_file.name,
                'batch': 'legacy',
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
        "user": getattr(request.state, 'user', None),
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
        "user": getattr(request.state, 'user', None),
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
    """Upload one or more resume files into a new batch folder."""
    # Create a new batch folder
    batch_dir = create_batch_folder(client_code, req_id)
    originals_dir = batch_dir / "originals"
    extracted_dir = batch_dir / "extracted"

    uploaded_count = 0
    source_files = []
    for file in files:
        if file.filename:
            # Save original file to originals/
            original_path = originals_dir / file.filename
            content = await file.read()
            with open(original_path, 'wb') as f:
                f.write(content)

            # Extract text based on file type
            normalized_name = normalize_filename(file.filename)
            extracted_path = extracted_dir / f"{normalized_name}_resume.txt"

            try:
                if file.filename.lower().endswith('.pdf'):
                    from scripts.utils.pdf_reader import extract_text
                    text = extract_text(str(original_path))
                elif file.filename.lower().endswith('.docx'):
                    from scripts.utils.docx_reader import extract_text as extract_docx_text
                    text = extract_docx_text(str(original_path))
                elif file.filename.lower().endswith('.txt'):
                    text = content.decode('utf-8', errors='ignore')
                else:
                    text = content.decode('utf-8', errors='ignore')

                header = f"""# Extracted Resume
# Source: {file.filename}
# Batch: {batch_dir.name}
# Extracted: {datetime.now().strftime('%Y-%m-%d')}

---

"""
                with open(extracted_path, 'w', encoding='utf-8') as f:
                    f.write(header + text)

                uploaded_count += 1
            except Exception as e:
                with open(extracted_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Extraction failed: {str(e)}\n\n{content.decode('utf-8', errors='ignore')}")
                uploaded_count += 1

            source_files.append(file.filename)

    # Write batch manifest
    manifest = {
        'created_at': datetime.now().isoformat(),
        'file_count': uploaded_count,
        'source_files': source_files,
        'status': 'uploaded',
    }
    with open(batch_dir / "batch_manifest.yaml", 'w') as f:
        yaml.dump(manifest, f, default_flow_style=False)

    return RedirectResponse(url=f"/candidates/{client_code}/{req_id}?uploaded={uploaded_count}", status_code=303)


# =============================================================================
# GOOGLE DRIVE IMPORT
# =============================================================================

@router.get("/{client_code}/{req_id}/import/drive", response_class=HTMLResponse)
async def drive_import_form(request: Request, client_code: str, req_id: str):
    """Render the Google Drive folder URL input form."""
    from web.auth.token_store import get_token

    user = getattr(request.state, 'user', None)
    email = user.get('email', '') if user else ''
    has_token = get_token(email) is not None if email else False

    return templates.TemplateResponse("candidates/drive_import.html", {
        "request": request,
        "user": user,
        "client_code": client_code,
        "req_id": req_id,
        "has_token": has_token,
    })


@router.post("/{client_code}/{req_id}/import/drive/list", response_class=HTMLResponse)
async def drive_list_files(
    request: Request,
    client_code: str,
    req_id: str,
    folder_url: str = Form(...),
):
    """Parse a Drive folder URL, list files, and render the preview table."""
    from web.auth.token_store import get_token, is_token_expired
    from web.services.google_drive import (
        parse_drive_folder_id, list_folder_files,
        DriveAPIError, TokenExpiredError, FolderNotFoundError,
    )

    user = getattr(request.state, 'user', None)
    email = user.get('email', '') if user else ''

    # Get stored OAuth token
    token_data = get_token(email) if email else None
    if not token_data:
        return templates.TemplateResponse("candidates/drive_import.html", {
            "request": request,
            "user": user,
            "client_code": client_code,
            "req_id": req_id,
            "has_token": False,
            "error": "No Google Drive token found. Please log out and log in again to grant Drive access.",
        })

    # Auto-refresh if expired
    if is_token_expired(token_data):
        import httpx
        from web.auth.config import get_google_client_id, get_google_client_secret
        from web.auth.token_store import store_token
        import time

        if not token_data.get('refresh_token'):
            return templates.TemplateResponse("candidates/drive_import.html", {
                "request": request,
                "user": user,
                "client_code": client_code,
                "req_id": req_id,
                "has_token": True,
                "error": "Drive token expired and no refresh token available. Please log out and log in again.",
            })

        async with httpx.AsyncClient() as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": get_google_client_id(),
                "client_secret": get_google_client_secret(),
                "refresh_token": token_data["refresh_token"],
                "grant_type": "refresh_token",
            })

        if resp.status_code != 200:
            return templates.TemplateResponse("candidates/drive_import.html", {
                "request": request,
                "user": user,
                "client_code": client_code,
                "req_id": req_id,
                "has_token": True,
                "error": "Failed to refresh Drive token. Please log out and log in again.",
            })

        new_token = resp.json()
        token_data["access_token"] = new_token["access_token"]
        token_data["expires_at"] = new_token.get("expires_in", 3600) + time.time()
        store_token(email, token_data)

    # Parse folder ID and list files
    try:
        folder_id = parse_drive_folder_id(folder_url)
        files = await list_folder_files(token_data["access_token"], folder_id)
    except FolderNotFoundError:
        return templates.TemplateResponse("candidates/drive_import.html", {
            "request": request,
            "user": user,
            "client_code": client_code,
            "req_id": req_id,
            "has_token": True,
            "error": "Folder not found. Check the URL and make sure the folder is shared with your Google account.",
            "folder_url": folder_url,
        })
    except TokenExpiredError:
        return templates.TemplateResponse("candidates/drive_import.html", {
            "request": request,
            "user": user,
            "client_code": client_code,
            "req_id": req_id,
            "has_token": True,
            "error": "Drive token expired. Please log out and log in again.",
            "folder_url": folder_url,
        })
    except DriveAPIError as e:
        return templates.TemplateResponse("candidates/drive_import.html", {
            "request": request,
            "user": user,
            "client_code": client_code,
            "req_id": req_id,
            "has_token": True,
            "error": str(e),
            "folder_url": folder_url,
        })

    if not files:
        return templates.TemplateResponse("candidates/drive_import.html", {
            "request": request,
            "user": user,
            "client_code": client_code,
            "req_id": req_id,
            "has_token": True,
            "error": "No PDF or DOCX files found in this folder.",
            "folder_url": folder_url,
        })

    return templates.TemplateResponse("candidates/drive_preview.html", {
        "request": request,
        "user": user,
        "client_code": client_code,
        "req_id": req_id,
        "files": files,
        "folder_url": folder_url,
    })


@router.post("/{client_code}/{req_id}/import/drive/import")
async def drive_import_files(
    request: Request,
    client_code: str,
    req_id: str,
):
    """Download selected files from Drive into a new batch folder."""
    from web.auth.token_store import get_token, is_token_expired, store_token
    from web.services.google_drive import download_file, DriveAPIError, TokenExpiredError
    import time

    user = getattr(request.state, 'user', None)
    email = user.get('email', '') if user else ''
    token_data = get_token(email) if email else None

    if not token_data:
        raise HTTPException(status_code=400, detail="No Drive token. Please re-login.")

    # Auto-refresh if expired
    if is_token_expired(token_data):
        import httpx
        from web.auth.config import get_google_client_id, get_google_client_secret

        if not token_data.get('refresh_token'):
            raise HTTPException(status_code=400, detail="Token expired. Please re-login.")

        async with httpx.AsyncClient() as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": get_google_client_id(),
                "client_secret": get_google_client_secret(),
                "refresh_token": token_data["refresh_token"],
                "grant_type": "refresh_token",
            })

        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to refresh token.")

        new_token = resp.json()
        token_data["access_token"] = new_token["access_token"]
        token_data["expires_at"] = new_token.get("expires_in", 3600) + time.time()
        store_token(email, token_data)

    # Parse form data (dynamic field names from the preview table)
    form = await request.form()

    # Create a new batch folder for this import
    batch_dir = create_batch_folder(client_code, req_id)
    originals_dir = batch_dir / "originals"
    extracted_dir = batch_dir / "extracted"

    imported_count = 0
    source_files = []

    # Collect selected files from form
    # Form fields: selected_<idx>, file_id_<idx>, target_name_<idx>, extension_<idx>
    idx = 0
    while True:
        file_id = form.get(f"file_id_{idx}")
        if file_id is None:
            break

        selected = form.get(f"selected_{idx}")
        if not selected:
            idx += 1
            continue

        target_name = form.get(f"target_name_{idx}", "").strip()
        extension = form.get(f"extension_{idx}", ".pdf")
        original_name = form.get(f"original_name_{idx}", "")

        if not target_name:
            idx += 1
            continue

        # Sanitize target name
        safe_name = target_name.lower().replace(" ", "_").replace("-", "_")
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
        # Remove trailing _resume to avoid double suffix
        if safe_name.endswith('_resume'):
            safe_name = safe_name[:-7]
        elif safe_name.endswith('resume'):
            safe_name = safe_name[:-6]
        safe_name = safe_name.rstrip('_')

        # Download to originals/
        original_path = originals_dir / f"{safe_name}{extension}"
        try:
            await download_file(token_data["access_token"], file_id, original_path)
        except (DriveAPIError, TokenExpiredError) as e:
            idx += 1
            continue

        # Extract text to extracted/
        extracted_path = extracted_dir / f"{safe_name}_resume.txt"
        try:
            if extension == ".pdf":
                from scripts.utils.pdf_reader import extract_text as extract_pdf_text
                text = extract_pdf_text(str(original_path))
            elif extension == ".docx":
                from scripts.utils.docx_reader import extract_text as extract_docx_text
                text = extract_docx_text(str(original_path))
            else:
                with open(original_path, 'r', errors='ignore') as f:
                    text = f.read()

            header = f"""# Extracted Resume
# Source: {original_name} (Google Drive import)
# Saved as: {safe_name}{extension}
# Batch: {batch_dir.name}
# Extracted: {datetime.now().strftime('%Y-%m-%d')}

---

"""
            with open(extracted_path, 'w', encoding='utf-8') as f:
                f.write(header + text)

            imported_count += 1
        except Exception as e:
            with open(extracted_path, 'w', encoding='utf-8') as f:
                f.write(f"# Extraction failed: {str(e)}\n")
            imported_count += 1

        source_files.append(original_name or f"{safe_name}{extension}")
        idx += 1

    # Write batch manifest
    manifest = {
        'created_at': datetime.now().isoformat(),
        'file_count': imported_count,
        'source': 'google_drive',
        'source_files': source_files,
        'status': 'uploaded',
    }
    with open(batch_dir / "batch_manifest.yaml", 'w') as f:
        yaml.dump(manifest, f, default_flow_style=False)

    return RedirectResponse(
        url=f"/candidates/{client_code}/{req_id}?uploaded={imported_count}",
        status_code=303
    )


@router.get("/{client_code}/{req_id}/{name_normalized}", response_class=HTMLResponse)
async def view_candidate(request: Request, client_code: str, req_id: str, name_normalized: str):
    """View candidate details and assessment."""
    req_root = get_requisition_root(client_code, req_id)
    assessments_dir = req_root / "assessments" / "individual"

    # Find resume file across batches
    resume_file = find_resume_in_batches(client_code, req_id, name_normalized, "extracted")
    # Fall back to legacy processed/ folder
    if not resume_file:
        legacy = req_root / "resumes" / "processed" / f"{name_normalized}_resume.txt"
        if legacy.exists():
            resume_file = legacy
    if not resume_file:
        raise HTTPException(status_code=404, detail="Candidate resume not found")

    # Read resume
    with open(resume_file, 'r', encoding='utf-8') as f:
        resume_text = f.read()

    # Check for assessment
    assessment = None
    assessment_file = assessments_dir / f"{name_normalized}_assessment.json"
    if assessment_file.exists():
        with open(assessment_file, 'r') as f:
            assessment = json.load(f)

    # Load lifecycle status if present
    lifecycle = ""
    lifecycle_file = assessments_dir / f"{name_normalized}_lifecycle.json"
    if lifecycle_file.exists():
        with open(lifecycle_file) as lf:
            lifecycle = json.load(lf).get("status", "")

    # Get requisition info
    req_config = get_requisition_config(client_code, req_id)
    client_config = get_client_config(client_code)

    return templates.TemplateResponse("candidates/view.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "client_code": client_code,
        "req_id": req_id,
        "client_name": client_config.get('company_name', client_code),
        "req_title": req_config.get('job', {}).get('title', req_id),
        "name_normalized": name_normalized,
        "name": assessment.get('candidate', {}).get('name', name_normalized.replace("_", " ").title()) if assessment else name_normalized.replace("_", " ").title(),
        "resume_text": resume_text,
        "assessment": assessment,
        "lifecycle": lifecycle,
    })


@router.get("/{client_code}/{req_id}/{name_normalized}/resume")
async def download_resume(client_code: str, req_id: str, name_normalized: str):
    """Download candidate resume (original file from batch originals/)."""
    # Search batch originals/ for original file
    original = find_resume_in_batches(client_code, req_id, name_normalized, "originals")
    if original:
        return FileResponse(original, filename=original.name)

    # Fall back to legacy incoming/
    req_root = get_requisition_root(client_code, req_id)
    incoming_dir = req_root / "resumes" / "incoming"
    if incoming_dir.exists():
        for ext in ['.pdf', '.docx', '.txt']:
            for file in incoming_dir.glob(f"*{ext}"):
                if normalize_filename(file.name) == name_normalized:
                    return FileResponse(file, filename=file.name)

    # Fall back to extracted text
    extracted = find_resume_in_batches(client_code, req_id, name_normalized, "extracted")
    if extracted:
        return FileResponse(extracted, filename=f"{name_normalized}_resume.txt")

    # Legacy processed/
    processed_file = req_root / "resumes" / "processed" / f"{name_normalized}_resume.txt"
    if processed_file.exists():
        return FileResponse(processed_file, filename=f"{name_normalized}_resume.txt")

    raise HTTPException(status_code=404, detail="Resume file not found")


@router.post("/{client_code}/{req_id}/{name_normalized}/delete")
async def delete_candidate(client_code: str, req_id: str, name_normalized: str):
    """Delete a candidate and their assessment."""
    req_root = get_requisition_root(client_code, req_id)

    # Delete extracted resume from batch
    extracted = find_resume_in_batches(client_code, req_id, name_normalized, "extracted")
    if extracted:
        extracted.unlink()

    # Delete original from batch
    original = find_resume_in_batches(client_code, req_id, name_normalized, "originals")
    if original:
        original.unlink()

    # Also delete from legacy folders
    legacy_processed = req_root / "resumes" / "processed" / f"{name_normalized}_resume.txt"
    if legacy_processed.exists():
        legacy_processed.unlink()

    # Delete assessment
    assessment_file = req_root / "assessments" / "individual" / f"{name_normalized}_assessment.json"
    if assessment_file.exists():
        assessment_file.unlink()

    return RedirectResponse(url=f"/candidates/{client_code}/{req_id}", status_code=303)


# =============================================================================
# FILE MANAGER - Incoming folder management
# =============================================================================

@router.get("/{client_code}/{req_id}/files/incoming", response_class=HTMLResponse)
async def file_manager(request: Request, client_code: str, req_id: str):
    """File manager showing all batches and their files."""
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_config = get_client_config(client_code)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    req_root = get_requisition_root(client_code, req_id)
    batches_dir = req_root / "resumes" / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    # Build batch data with files
    batches_data = []
    total_files = 0
    for batch_dir in sorted(batches_dir.iterdir(), reverse=True):
        if not batch_dir.is_dir():
            continue
        originals_dir = batch_dir / "originals"
        extracted_dir = batch_dir / "extracted"

        batch_files = []
        if originals_dir.exists():
            for file_path in sorted(originals_dir.iterdir()):
                if file_path.is_file():
                    normalized = normalize_filename(file_path.name)
                    extracted_file = extracted_dir / f"{normalized}_resume.txt"
                    batch_files.append({
                        'name': file_path.name,
                        'size': f"{file_path.stat().st_size / 1024:.1f} KB",
                        'modified': datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                        'extension': file_path.suffix.lower(),
                        'processed': extracted_file.exists(),
                        'batch': batch_dir.name,
                    })

        # Load manifest
        manifest_path = batch_dir / "batch_manifest.yaml"
        manifest = {}
        if manifest_path.exists():
            with open(manifest_path, 'r') as f:
                manifest = yaml.safe_load(f) or {}

        batches_data.append({
            'name': batch_dir.name,
            'files': batch_files,
            'file_count': len(batch_files),
            'status': manifest.get('status', 'unknown'),
            'created_at': manifest.get('created_at', ''),
        })
        total_files += len(batch_files)

    # Also include legacy incoming/ files if present
    legacy_files = []
    legacy_dir = req_root / "resumes" / "incoming"
    legacy_processed = req_root / "resumes" / "processed"
    if legacy_dir.exists():
        for file_path in sorted(legacy_dir.iterdir()):
            if file_path.is_file() and not file_path.name.endswith('.json'):
                normalized = normalize_filename(file_path.name)
                processed_file = legacy_processed / f"{normalized}_resume.txt" if legacy_processed.exists() else None
                legacy_files.append({
                    'name': file_path.name,
                    'size': f"{file_path.stat().st_size / 1024:.1f} KB",
                    'modified': datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    'extension': file_path.suffix.lower(),
                    'processed': processed_file.exists() if processed_file else False,
                    'batch': 'legacy',
                })
                total_files += 1

    return templates.TemplateResponse("candidates/file_manager.html", {
        "request": request,
        "user": getattr(request.state, 'user', None),
        "client_code": client_code,
        "req_id": req_id,
        "client_name": client_config.get('company_name', client_code),
        "req_title": req_config.get('job', {}).get('title', req_id),
        "batches": batches_data,
        "legacy_files": legacy_files,
        "file_count": total_files,
    })


@router.post("/{client_code}/{req_id}/files/batch/delete")
async def delete_batch_file(
    client_code: str,
    req_id: str,
    filename: str = Form(...),
    batch: str = Form(...)
):
    """Delete a file from a batch originals folder."""
    req_root = get_requisition_root(client_code, req_id)

    if batch == 'legacy':
        file_path = req_root / "resumes" / "incoming" / filename
    else:
        file_path = req_root / "resumes" / "batches" / batch / "originals" / filename

    if file_path.exists() and file_path.is_file():
        # Also delete corresponding extracted file
        normalized = normalize_filename(filename)
        if batch == 'legacy':
            extracted = req_root / "resumes" / "processed" / f"{normalized}_resume.txt"
        else:
            extracted = req_root / "resumes" / "batches" / batch / "extracted" / f"{normalized}_resume.txt"
        if extracted.exists():
            extracted.unlink()
        file_path.unlink()

    return RedirectResponse(
        url=f"/candidates/{client_code}/{req_id}/files/incoming?deleted=1",
        status_code=303
    )


@router.post("/{client_code}/{req_id}/files/batch/rename")
async def rename_batch_file(
    client_code: str,
    req_id: str,
    old_name: str = Form(...),
    new_name: str = Form(...),
    batch: str = Form(...)
):
    """Rename a file in a batch originals folder."""
    req_root = get_requisition_root(client_code, req_id)

    if batch == 'legacy':
        parent_dir = req_root / "resumes" / "incoming"
    else:
        parent_dir = req_root / "resumes" / "batches" / batch / "originals"

    old_path = parent_dir / old_name

    # Preserve extension if not provided in new name
    old_ext = old_path.suffix
    if not Path(new_name).suffix:
        new_name = new_name + old_ext

    new_path = parent_dir / new_name

    if old_path.exists() and old_path.is_file():
        if new_path.exists():
            raise HTTPException(status_code=400, detail=f"File '{new_name}' already exists")
        old_path.rename(new_path)

    return RedirectResponse(
        url=f"/candidates/{client_code}/{req_id}/files/incoming?renamed=1",
        status_code=303
    )


@router.post("/{client_code}/{req_id}/files/batch/process")
async def process_batch_file(
    client_code: str,
    req_id: str,
    filename: str = Form(...),
    batch: str = Form(...)
):
    """Re-extract text for a single file in a batch."""
    req_root = get_requisition_root(client_code, req_id)

    if batch == 'legacy':
        file_path = req_root / "resumes" / "incoming" / filename
        output_dir = req_root / "resumes" / "processed"
    else:
        file_path = req_root / "resumes" / "batches" / batch / "originals" / filename
        output_dir = req_root / "resumes" / "batches" / batch / "extracted"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_name = normalize_filename(filename)
    output_path = output_dir / f"{normalized_name}_resume.txt"

    try:
        if filename.lower().endswith('.pdf'):
            from scripts.utils.pdf_reader import extract_text as extract_pdf_text
            text = extract_pdf_text(str(file_path))
        elif filename.lower().endswith('.docx'):
            from scripts.utils.docx_reader import extract_text as extract_docx_text
            text = extract_docx_text(str(file_path))
        else:
            with open(file_path, 'rb') as f:
                text = f.read().decode('utf-8', errors='ignore')

        header = f"""# Extracted Resume
# Source: {filename}
# Batch: {batch}
# Extracted: {datetime.now().strftime('%Y-%m-%d')}

---

"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(header + text)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

    return RedirectResponse(
        url=f"/candidates/{client_code}/{req_id}/files/incoming?processed=1",
        status_code=303
    )


@router.post("/{client_code}/{req_id}/files/batch/process-all")
async def process_all_batch_files(client_code: str, req_id: str):
    """Re-extract text for all unprocessed files across all batches."""
    req_root = get_requisition_root(client_code, req_id)
    batches_dir = req_root / "resumes" / "batches"

    processed_count = 0

    if batches_dir.exists():
        for batch_dir in batches_dir.iterdir():
            if not batch_dir.is_dir():
                continue
            originals_dir = batch_dir / "originals"
            extracted_dir = batch_dir / "extracted"
            if not originals_dir.exists():
                continue
            extracted_dir.mkdir(parents=True, exist_ok=True)

            for file_path in originals_dir.iterdir():
                if not file_path.is_file():
                    continue
                normalized_name = normalize_filename(file_path.name)
                extracted_path = extracted_dir / f"{normalized_name}_resume.txt"
                if extracted_path.exists():
                    continue

                try:
                    if file_path.name.lower().endswith('.pdf'):
                        from scripts.utils.pdf_reader import extract_text as extract_pdf_text
                        text = extract_pdf_text(str(file_path))
                    elif file_path.name.lower().endswith('.docx'):
                        from scripts.utils.docx_reader import extract_text as extract_docx_text
                        text = extract_docx_text(str(file_path))
                    else:
                        with open(file_path, 'rb') as f:
                            text = f.read().decode('utf-8', errors='ignore')

                    header = f"""# Extracted Resume
# Source: {file_path.name}
# Batch: {batch_dir.name}
# Extracted: {datetime.now().strftime('%Y-%m-%d')}

---

"""
                    with open(extracted_path, 'w', encoding='utf-8') as f:
                        f.write(header + text)
                    processed_count += 1
                except Exception:
                    pass

    return RedirectResponse(
        url=f"/candidates/{client_code}/{req_id}/files/incoming?processed={processed_count}",
        status_code=303
    )


@router.get("/{client_code}/{req_id}/files/batch/download/{batch}/{filename}")
async def download_batch_file(client_code: str, req_id: str, batch: str, filename: str):
    """Download a file from a batch originals folder."""
    req_root = get_requisition_root(client_code, req_id)

    if batch == 'legacy':
        file_path = req_root / "resumes" / "incoming" / filename
    else:
        file_path = req_root / "resumes" / "batches" / batch / "originals" / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path, filename=filename)
