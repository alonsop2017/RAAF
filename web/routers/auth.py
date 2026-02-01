"""
Authentication routes for RAAF Web Application.
Handles Google OAuth login/logout flow.
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from web.auth.oauth import oauth
from web.auth.session import session_manager
from web.auth.config import get_allowed_domains

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display the login page with Google sign-in button."""
    # If already logged in, redirect to dashboard
    user = session_manager.get_user_from_cookies(request.cookies)
    if user:
        return RedirectResponse(url="/", status_code=302)

    error = request.query_params.get("error")
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "error": error
    })


@router.get("/login/google")
async def login_google(request: Request):
    """Initiate Google OAuth flow."""
    # Build callback URL
    redirect_uri = str(request.url_for("auth_callback"))

    return await oauth.google.authorize_redirect(request, redirect_uri)


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

    # Create session data
    user_data = {
        'email': user_info.get('email'),
        'name': user_info.get('name'),
        'given_name': user_info.get('given_name'),
        'family_name': user_info.get('family_name'),
        'picture': user_info.get('picture'),
        'email_verified': user_info.get('email_verified', False)
    }

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
        secure=False  # Set to True in production with HTTPS
    )

    return response


@router.get("/logout")
async def logout(request: Request):
    """Log out the user by clearing the session cookie."""
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie(key=session_manager.cookie_name)
    return response
