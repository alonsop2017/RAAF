"""
Authentication configuration loader.
Reads OAuth settings from settings.yaml and resolves environment variables.
"""

import os
from pathlib import Path
from typing import Optional
import yaml


def get_auth_config() -> dict:
    """
    Load authentication configuration from settings.yaml.
    Resolves environment variable references for secrets.
    """
    config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

    with open(config_path, 'r') as f:
        settings = yaml.safe_load(f)

    auth_config = settings.get('auth', {})

    # Resolve Google client secret from environment variable
    google_config = auth_config.get('google', {})
    client_secret_env = google_config.get('client_secret_env', 'GOOGLE_CLIENT_SECRET')
    google_config['client_secret'] = os.environ.get(client_secret_env, '')

    # Resolve session secret from environment variable
    session_config = auth_config.get('session', {})
    secret_key_env = session_config.get('secret_key_env', 'SESSION_SECRET_KEY')
    session_config['secret_key'] = os.environ.get(secret_key_env, '')

    return auth_config


def get_google_client_id() -> str:
    """Get the Google OAuth client ID."""
    config = get_auth_config()
    return config.get('google', {}).get('client_id', '')


def get_google_client_secret() -> str:
    """Get the Google OAuth client secret from environment."""
    config = get_auth_config()
    return config.get('google', {}).get('client_secret', '')


def get_session_secret_key() -> str:
    """Get the session signing secret key from environment."""
    config = get_auth_config()
    return config.get('session', {}).get('secret_key', '')


def get_session_cookie_name() -> str:
    """Get the session cookie name."""
    config = get_auth_config()
    return config.get('session', {}).get('cookie_name', 'raaf_session')


def get_session_max_age() -> int:
    """Get the session max age in seconds."""
    config = get_auth_config()
    hours = config.get('session', {}).get('max_age_hours', 8)
    return hours * 3600


def get_allowed_domains() -> list:
    """Get list of allowed email domains (empty = allow all)."""
    config = get_auth_config()
    return config.get('allowed_domains', [])
