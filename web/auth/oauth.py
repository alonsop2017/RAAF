"""
Google OAuth client configuration using Authlib.
"""

from authlib.integrations.starlette_client import OAuth

from .config import get_google_client_id, get_google_client_secret


# Create OAuth instance
oauth = OAuth()


def setup_oauth():
    """
    Configure the Google OAuth client.
    Must be called after environment variables are loaded.
    """
    oauth.register(
        name='google',
        client_id=get_google_client_id(),
        client_secret=get_google_client_secret(),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )
    return oauth
