"""
Shared Flask extension objects and application state.

All attributes start as None/empty and are populated by the app factory
in app.py. Routes must access these as module attributes (not destructured)
so they see the updated values after the factory runs:

    import extensions
    db = extensions.supabase_admin or extensions.supabase   # CORRECT
    from extensions import supabase  # WRONG — gets None at import time
"""
from flask_wtf.csrf import CSRFProtect
from security import PasswordHasher, LoginAttemptTracker
from config import Config

csrf = CSRFProtect()

# Supabase clients — set by app factory after create_client() succeeds.
supabase = None
supabase_admin = None

# Emergency admin accounts — set by app factory from Config.
EMERGENCY_ACCOUNTS: dict = {}

# Auth utilities — initialized here so routes can import them directly.
password_hasher = PasswordHasher()
login_tracker = LoginAttemptTracker(
    max_attempts=Config.MAX_LOGIN_ATTEMPTS,
    lockout_duration_minutes=Config.LOCKOUT_DURATION_MINUTES,
)

VERSION = "v41-CYCLE20"
