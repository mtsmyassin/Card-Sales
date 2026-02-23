"""
Shared Flask extension objects and application state.

All attributes start as None/empty and are populated by the app factory
in app.py. Routes must access these as module attributes (not destructured)
so they see the updated values after the factory runs:

    import extensions
    db = extensions.get_db()                                # CORRECT (preferred)
    db = extensions.supabase_admin or extensions.supabase   # CORRECT (legacy)
    from extensions import supabase  # WRONG — gets None at import time
"""
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from security import PasswordHasher, LoginAttemptTracker
from config import Config

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=Config.RATELIMIT_STORAGE_URI,
)

# Supabase clients — set by app factory after create_client() succeeds.
supabase = None
supabase_admin = None


def get_db():
    """Return the best available Supabase client (admin preferred, anon fallback).

    This is the canonical way to get a DB client. It replaces the pattern
    ``extensions.supabase_admin or extensions.supabase`` that was previously
    repeated 30+ times across the codebase.
    """
    return supabase_admin or supabase


def has_admin_client() -> bool:
    """Return True if the service-role admin client is configured."""
    return supabase_admin is not None

# Emergency admin accounts — set by app factory from Config.
EMERGENCY_ACCOUNTS: dict = {}

# Auth utilities — initialized here so routes can import them directly.
password_hasher = PasswordHasher()
login_tracker = LoginAttemptTracker(
    max_attempts=Config.MAX_LOGIN_ATTEMPTS,
    lockout_duration_minutes=Config.LOCKOUT_DURATION_MINUTES,
)

VERSION = "v43"
