"""
Authentication and authorization helpers.
No dependency on app.py — import from flask and audit_log only.
"""
import logging
from functools import wraps
from flask import session, request, jsonify
from audit_log import audit_log

logger = logging.getLogger(__name__)


def require_auth(allowed_roles=None):
    """
    Decorator to enforce authentication and role-based access control.

    Args:
        allowed_roles: List of roles allowed to access this endpoint.
                      If None, any authenticated user is allowed.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('logged_in'):
                logger.warning(f"Unauthorized access attempt to {request.endpoint}")
                return jsonify(error="Authentication required"), 401
            if allowed_roles:
                user_role = session.get('role')
                if user_role not in allowed_roles:
                    username = session.get('user', 'unknown')
                    logger.warning(
                        f"Access denied: {username} ({user_role}) "
                        f"attempted to access {request.endpoint} "
                        f"(requires: {allowed_roles})"
                    )
                    audit_log(
                        action="ACCESS_DENIED",
                        actor=username,
                        role=user_role,
                        entity_type="ENDPOINT",
                        entity_id=request.endpoint,
                        success=False,
                        error=f"Insufficient permissions (requires: {allowed_roles})",
                        context={"ip": request.remote_addr}
                    )
                    return jsonify(error="Insufficient permissions"), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def can_access_photo(photo_store, user_role: str, user_store: str) -> bool:
    """Return True if the user is authorized to access a photo from photo_store."""
    if user_role in ("admin", "super_admin"):
        return True
    # If store is NULL in DB, only admins can access (handled above)
    if photo_store is None:
        return False
    return photo_store == user_store
