"""
Session management using signed cookies.
Uses itsdangerous for secure cookie signing.
"""

import json
from typing import Optional
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from .config import get_session_secret_key, get_session_cookie_name, get_session_max_age


class SessionManager:
    """Manages user sessions with signed cookies."""

    def __init__(self):
        self._serializer = None

    @property
    def serializer(self) -> URLSafeTimedSerializer:
        """Lazy initialization of serializer to allow for late secret key loading."""
        if self._serializer is None:
            secret_key = get_session_secret_key()
            if not secret_key:
                raise ValueError("SESSION_SECRET_KEY environment variable not set")
            self._serializer = URLSafeTimedSerializer(secret_key)
        return self._serializer

    @property
    def cookie_name(self) -> str:
        return get_session_cookie_name()

    @property
    def max_age(self) -> int:
        return get_session_max_age()

    def create_session(self, user_data: dict) -> str:
        """
        Create a signed session token containing user data.

        Args:
            user_data: Dictionary with user info (email, name, picture, etc.)

        Returns:
            Signed session token string
        """
        return self.serializer.dumps(user_data)

    def validate_session(self, token: str) -> Optional[dict]:
        """
        Validate a session token and return user data.

        Args:
            token: Signed session token

        Returns:
            User data dictionary if valid, None otherwise
        """
        if not token:
            return None

        try:
            user_data = self.serializer.loads(token, max_age=self.max_age)
            return user_data
        except SignatureExpired:
            return None
        except BadSignature:
            return None

    def get_user_from_cookies(self, cookies: dict) -> Optional[dict]:
        """
        Extract and validate user from request cookies.

        Args:
            cookies: Request cookies dictionary

        Returns:
            User data dictionary if valid session exists, None otherwise
        """
        token = cookies.get(self.cookie_name)
        return self.validate_session(token)


# Global session manager instance
session_manager = SessionManager()
