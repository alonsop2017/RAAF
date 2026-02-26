"""
FastAPI dependencies for authentication.
"""

from typing import Optional
from fastapi import Request, Depends, HTTPException

from .session import session_manager, SessionManager
from .config import get_admin_emails


def get_session_manager() -> SessionManager:
    """Dependency to get the session manager."""
    return session_manager


def get_current_user(request: Request) -> Optional[dict]:
    """
    Dependency to get the current authenticated user.
    Returns None if not authenticated.
    """
    return session_manager.get_user_from_cookies(request.cookies)


def get_required_user(request: Request) -> dict:
    """
    Dependency to get the current user, raising an exception if not authenticated.
    Use this for routes that require authentication.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request) -> dict:
    """
    Dependency that requires the current user to be an admin.
    Raises HTTP 403 if the user is not in the admin_emails list.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    email = user.get("email", "").lower()
    if email not in get_admin_emails():
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
