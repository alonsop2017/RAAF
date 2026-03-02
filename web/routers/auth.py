"""
Authentication routes for RAAF Web Application.
Handles email/password login, registration, and Google OAuth login/logout flow.
"""

import time

import bcrypt
from fastapi import APIRouter, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from web.auth.oauth import oauth
from web.auth.session import session_manager
from web.auth.config import get_allowed_domains, get_allowed_emails, get_google_client_id, get_google_client_secret, get_google_redirect_uri
from web.auth.token_store import store_token, get_token, remove_token, is_token_expired
from web.auth.database import get_db
from web.auth.models import User

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display the login page with email/password form and Google sign-in button."""
    # If already logged in, redirect to dashboard
    user = session_manager.get_user_from_cookies(request.cookies)
    if user:
        return RedirectResponse(url="/", status_code=302)

    error = request.query_params.get("error")
    success = request.query_params.get("success")
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "error": error,
        "success": success,
    })


@router.post("/login")
async def login_email(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Authenticate with email and password."""
    user = db.query(User).filter(User.email == email).first()

    if not user or not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        return RedirectResponse(
            url="/auth/login?error=Invalid+email+or+password",
            status_code=302,
        )

    # Build session data compatible with OAuth sessions
    name_parts = user.name.split()
    user_data = {
        "email": user.email,
        "name": user.name,
        "given_name": name_parts[0],
        "family_name": name_parts[-1] if len(name_parts) > 1 else "",
        "picture": None,
        "email_verified": True,
    }

    session_token = session_manager.create_session(user_data)

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=session_manager.cookie_name,
        value=session_token,
        max_age=session_manager.max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production with HTTPS
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Display the registration page."""
    user = session_manager.get_user_from_cookies(request.cookies)
    if user:
        return RedirectResponse(url="/", status_code=302)

    error = request.query_params.get("error")
    return templates.TemplateResponse("auth/register.html", {
        "request": request,
        "error": error,
    })


@router.post("/register")
async def register_email(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Create a new account with email and password."""
    # Validate passwords match
    if password != confirm_password:
        return templates.TemplateResponse("auth/register.html", {
            "request": request,
            "error": "Passwords do not match.",
            "name": name,
            "email": email,
        })

    # Validate password length
    if len(password) < 8:
        return templates.TemplateResponse("auth/register.html", {
            "request": request,
            "error": "Password must be at least 8 characters.",
            "name": name,
            "email": email,
        })

    # Check if email already exists
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("auth/register.html", {
            "request": request,
            "error": "An account with this email already exists.",
            "name": name,
            "email": email,
        })

    # Hash password and create user
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    new_user = User(email=email, name=name.strip(), password_hash=password_hash)
    db.add(new_user)
    db.commit()

    return RedirectResponse(
        url="/auth/login?success=Account+created+successfully.+Please+sign+in.",
        status_code=302,
    )


@router.get("/login/google")
async def login_google(request: Request):
    """Initiate Google OAuth flow."""
    # Use fixed redirect URI from config if set, otherwise fall back to dynamic URL
    redirect_uri = get_google_redirect_uri() or str(request.url_for("auth_callback"))

    return await oauth.google.authorize_redirect(
        request, redirect_uri,
        access_type='offline',
        prompt='consent'
    )


@router.get("/callback")
async def auth_callback(request: Request):
    """Handle Google OAuth callback."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        return RedirectResponse(
            url="/auth/login?error=OAuth+authorization+failed",
            status_code=302
        )

    # Get user info from the ID token
    user_info = token.get('userinfo')
    if not user_info:
        return RedirectResponse(
            url="/auth/login?error=Failed+to+get+user+info",
            status_code=302
        )

    # Check allowed domains if configured
    allowed_domains = get_allowed_domains()
    if allowed_domains:
        email = user_info.get('email', '')
        domain = email.split('@')[-1] if '@' in email else ''
        if domain not in allowed_domains:
            return RedirectResponse(
                url="/auth/login?error=Email+domain+not+allowed",
                status_code=302
            )

    # Check allowed emails whitelist if configured
    allowed_emails = get_allowed_emails()
    if allowed_emails:
        if user_info.get('email', '').lower() not in allowed_emails:
            return RedirectResponse(
                url="/auth/login?error=Email+not+authorized",
                status_code=302
            )

    # Create session data
    user_data = {
        'email': user_info.get('email'),
        'name': user_info.get('name'),
        'given_name': user_info.get('given_name'),
        'family_name': user_info.get('family_name'),
        'picture': user_info.get('picture'),
        'email_verified': user_info.get('email_verified', False)
    }

    # Store OAuth token (access + refresh) for Drive API use
    email = user_info.get('email')
    if email:
        token_data = {
            'access_token': token.get('access_token'),
            'refresh_token': token.get('refresh_token'),
            'expires_at': token.get('expires_at'),
            'token_type': token.get('token_type', 'Bearer'),
        }
        store_token(email, token_data)

    # Create signed session token
    session_token = session_manager.create_session(user_data)

    # Redirect to dashboard with session cookie
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=session_manager.cookie_name,
        value=session_token,
        max_age=session_manager.max_age,
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto") == "https"
    )

    return response


@router.get("/refresh-token")
async def refresh_drive_token(request: Request):
    """Refresh an expired Google Drive access token using the stored refresh token."""
    import httpx  # already a project dependency

    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    email = user.get('email')
    token_data = get_token(email) if email else None
    if not token_data or not token_data.get('refresh_token'):
        raise HTTPException(status_code=400, detail="No refresh token available. Please re-login.")

    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": get_google_client_id(),
            "client_secret": get_google_client_secret(),
            "refresh_token": token_data["refresh_token"],
            "grant_type": "refresh_token",
        })

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to refresh token")

    new_token = resp.json()
    token_data["access_token"] = new_token["access_token"]
    token_data["expires_at"] = new_token.get("expires_in", 3600) + time.time()
    store_token(email, token_data)

    return {"status": "ok"}


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    """Display the reset password page."""
    user = session_manager.get_user_from_cookies(request.cookies)
    if user:
        return RedirectResponse(url="/", status_code=302)

    error = request.query_params.get("error")
    return templates.TemplateResponse("auth/reset_password.html", {
        "request": request,
        "error": error,
    })


@router.post("/reset-password")
async def reset_password(
    request: Request,
    email: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Reset password for an existing account."""
    def render_error(msg: str):
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request,
            "error": msg,
            "email": email,
        })

    if new_password != confirm_password:
        return render_error("Passwords do not match.")

    if len(new_password) < 8:
        return render_error("Password must be at least 8 characters.")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        # Deliberately vague to avoid user enumeration
        return render_error("No account found for that email address.")

    user.password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    db.commit()

    return RedirectResponse(
        url="/auth/login?success=Password+reset+successfully.+Please+sign+in.",
        status_code=302,
    )


@router.get("/logout")
async def logout(request: Request):
    """Log out the user by clearing the session cookie and stored token."""
    # Clear stored Drive token
    user = getattr(request.state, 'user', None)
    if user and user.get('email'):
        remove_token(user['email'])

    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie(key=session_manager.cookie_name)
    return response
