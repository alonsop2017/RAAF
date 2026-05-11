"""
Google OAuth client configuration using Authlib.
"""

import os

from authlib.integrations.starlette_client import OAuth

from .config import get_google_client_id, get_google_client_secret


# Create OAuth instance
oauth = OAuth()


def setup_oauth():
    """
    Configure the Google OAuth client.
    Must be called after environment variables are loaded.
    """
    client_id = get_google_client_id()
    client_secret = get_google_client_secret()
    dev_mode = os.environ.get("DEV_MODE", "0") == "1"

    if not dev_mode and (not client_id or not client_secret or client_secret == "placeholder-set-real-value-before-production"):
        raise RuntimeError("GOOGLE_CLIENT_SECRET is not set or is still a placeholder — cannot start OAuth in production")

    oauth.register(
        name='google',
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly'
        }
    )
    return oauth
