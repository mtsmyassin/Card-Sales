"""Auth Blueprint — login, logout, CSRF token, logo, session timeout."""
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, session
from flask_wtf.csrf import generate_csrf
from audit_log import audit_log
import extensions
from helpers.auth_utils import require_auth
from helpers.offline_queue import get_logo
from config import Config

logger = logging.getLogger(__name__)

bp = Blueprint('auth', __name__)

_SESSION_SKIP_ENDPOINTS = frozenset({
    'auth.login', 'auth.csrf_token', 'telegram.telegram_webhook',
    'static', 'main.favicon', 'main.index',
})


@bp.before_app_request
def enforce_session_timeout():
    """Expire sessions that have been idle longer than SESSION_TIMEOUT_MINUTES."""
    if not session.get('logged_in'):
        return  # unauthenticated — let route handlers deal with it
    if request.endpoint in _SESSION_SKIP_ENDPOINTS:
        return

    timeout = timedelta(minutes=Config.SESSION_TIMEOUT_MINUTES)
    last_str = session.get('last_active')
    now = datetime.now(timezone.utc)

    if last_str:
        try:
            last_dt = datetime.fromisoformat(last_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if now - last_dt > timeout:
                username = session.get('user', 'unknown')
                logger.info("Session timeout for user: %s (idle >%dm)", username, Config.SESSION_TIMEOUT_MINUTES)
                session.clear()
                return  # require_auth will return 401; frontend shows login screen
        except (ValueError, TypeError):
            session.clear()
            return

    session['last_active'] = now.isoformat()
    session.modified = True


@bp.route('/api/csrf-token', methods=['GET'])
def csrf_token():
    """Return a fresh CSRF token for the current session."""
    return jsonify(token=generate_csrf())


@bp.route('/api/get_logo', methods=['POST'])
@require_auth()
def api_get_logo():
    """Get store logo with authentication and input validation."""
    try:
        if not request.json:
            return jsonify(error="No data provided", code="BAD_REQUEST"), 400

        store = request.json.get('store', 'carimas')

        # Whitelist validation to prevent path traversal
        valid_stores = Config.STORES + ['Carimas', None]
        if store not in valid_stores:
            logger.warning(f"Invalid store name requested: {store}")
            store = None  # Default to Carimas logo

        return jsonify(logo=get_logo(store))
    except Exception as e:
        logger.error(f"Error in get_logo: {e}")
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/login', methods=['POST'])
@extensions.csrf.exempt
@extensions.limiter.limit(Config.RATELIMIT_LOGIN)
def login():
    """
    Authenticate user with password hashing and brute-force protection.
    Logs all login attempts (success and failure) to audit log.
    """
    try:
        u = request.json.get('username', '').strip()
        p = request.json.get('password', '')

        if not u or not p:
            logger.warning("Login attempt with empty username or password")
            return jsonify(status="fail", error="Username and password required", code="BAD_REQUEST"), 400

        # Check if account is locked out
        if extensions.login_tracker.is_locked_out(u):
            remaining = extensions.login_tracker.get_lockout_remaining(u)
            logger.warning(f"Login attempt for locked out account: {u}")
            audit_log(
                action="LOGIN_BLOCKED",
                actor=u,
                role="UNKNOWN",
                entity_type="SESSION",
                success=False,
                error=f"Account locked out ({remaining}s remaining)",
                context={"ip": request.remote_addr}
            )
            return jsonify(
                status="fail",
                error=f"Account locked due to too many failed attempts. Try again in {remaining} seconds.",
                code="ACCOUNT_LOCKED"
            ), 429

        # --- CHECK EMERGENCY BACKDOOR ACCOUNTS (HASHED) ---
        if u in extensions.EMERGENCY_ACCOUNTS:
            stored_hash = extensions.EMERGENCY_ACCOUNTS[u]
            if extensions.password_hasher.verify_password(p, stored_hash):
                # Determine role based on username
                role = 'super_admin' if u == 'super' else 'admin'

                # Regenerate session to prevent fixation
                session.clear()
                session.permanent = True
                session['logged_in'] = True
                session['user'] = u
                session['role'] = role
                session['store'] = 'All'
                session['login_time'] = datetime.now(timezone.utc).isoformat()
                session['last_active'] = datetime.now(timezone.utc).isoformat()

                extensions.login_tracker.record_successful_login(u)

                logger.info(f"Emergency account login: {u} as {role}")
                audit_log(
                    action="LOGIN_SUCCESS",
                    actor=u,
                    role=role,
                    entity_type="SESSION",
                    success=True,
                    context={"ip": request.remote_addr, "account_type": "emergency"}
                )

                return jsonify(status="ok", role=role, store='All', username=u)

        # --- CHECK DATABASE ACCOUNTS ---
        try:
            res = extensions.get_db().table("users").select("*").eq("username", u).execute()
            if res.data:
                user = res.data[0]

                # Only accept bcrypt-hashed passwords — plaintext is rejected
                if user['password'].startswith('$2b$'):
                    password_valid = extensions.password_hasher.verify_password(p, user['password'])
                else:
                    logger.error(f"[login] User {u!r} has unhashed password in DB — rejecting login. "
                                 "Admin must reset this password.")
                    password_valid = False

                if password_valid:
                    # Regenerate session to prevent fixation
                    session.clear()
                    session.permanent = True
                    session['logged_in'] = True
                    session['user'] = u
                    session['role'] = user['role']
                    session['store'] = user['store']
                    session['login_time'] = datetime.now(timezone.utc).isoformat()
                    session['last_active'] = datetime.now(timezone.utc).isoformat()

                    extensions.login_tracker.record_successful_login(u)

                    logger.info(f"User login: {u} as {user['role']}")
                    audit_log(
                        action="LOGIN_SUCCESS",
                        actor=u,
                        role=user['role'],
                        entity_type="SESSION",
                        success=True,
                        context={"ip": request.remote_addr, "store": user['store']}
                    )

                    return jsonify(status="ok", role=user['role'], store=user['store'], username=u)

        except Exception as e:
            logger.error(f"Database error during login for {u}: {e}")
            # Continue to failed login handling

        # --- FAILED LOGIN ---
        is_locked, remaining_attempts = extensions.login_tracker.record_failed_attempt(u)

        logger.warning(f"Failed login attempt for: {u} (remaining attempts: {remaining_attempts})")
        audit_log(
            action="LOGIN_FAILED",
            actor=u,
            role="UNKNOWN",
            entity_type="SESSION",
            success=False,
            error="Invalid credentials",
            context={"ip": request.remote_addr, "remaining_attempts": remaining_attempts}
        )

        if is_locked:
            lockout_duration = extensions.login_tracker.get_lockout_remaining(u)
            return jsonify(
                status="fail",
                error=f"Too many failed attempts. Account locked for {lockout_duration} seconds.",
                code="ACCOUNT_LOCKED"
            ), 429
        else:
            return jsonify(
                status="fail",
                error=f"Invalid credentials. {remaining_attempts} attempts remaining.",
                code="LOGIN_FAILED"
            ), 401

    except Exception as e:
        logger.error(f"Unexpected error in login: {e}", exc_info=True)
        return jsonify(status="error", error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/logout', methods=['POST'])
def logout():
    """Log out user and record in audit log."""
    username = session.get('user', 'unknown')
    role = session.get('role', 'unknown')

    logger.info(f"User logout: {username}")
    audit_log(
        action="LOGOUT",
        actor=username,
        role=role,
        entity_type="SESSION",
        success=True,
        context={"ip": request.remote_addr}
    )

    session.clear()
    return jsonify(status="ok")
