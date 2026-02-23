"""Users Blueprint — user management (admin only)."""
import logging
from flask import Blueprint, request, jsonify, session
from audit_log import audit_log
import extensions
from helpers.auth_utils import require_auth
from helpers.validation import validate_user_data
from helpers.db import db_retry

logger = logging.getLogger(__name__)
bp = Blueprint('users', __name__)


@bp.route('/api/users/list')
@require_auth(['admin', 'super_admin'])
def list_users():
    """List all users (admin only)."""
    try:
        result = extensions.get_db().table("users").select("username, role, store").execute()
        logger.info(f"User list accessed by {session.get('user')}")
        return jsonify(result.data)
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return jsonify([])


@bp.route('/api/users/save', methods=['POST'])
@require_auth(['admin', 'super_admin'])
def save_user():
    """Create or update a user (admin only) with password hashing and input validation."""
    username = session.get('user')
    role = session.get('role')

    try:
        u = request.json
        if not u:
            return jsonify(error="No data provided"), 400

        # Check if user exists to determine if this is create or update
        user_to_save = u.get('username')
        if not user_to_save:
            return jsonify(error="Username is required"), 400

        try:
            existing = extensions.get_db().table("users").select("*").eq("username", user_to_save).execute()
            is_update = len(existing.data) > 0
            before_state = existing.data[0] if is_update else None
        except Exception as fetch_err:
            logger.warning(f"[save_user] Failed to check existing user {user_to_save!r}: {fetch_err}")
            is_update = False
            before_state = None

        # Validate input
        is_valid, error_msg = validate_user_data(u, is_update=is_update)
        if not is_valid:
            logger.warning(f"Invalid user data from {username}: {error_msg}")
            return jsonify(error=error_msg), 400

        password = u.get('password', '')
        new_role = u['role']
        new_store = u['store']

        # Hash the password if it's not already hashed
        if password and not password.startswith('$2b$'):
            hashed_password = extensions.password_hasher.hash_password(password)
            logger.info(f"Password hashed for user: {user_to_save}")
        elif password:
            hashed_password = password
        else:
            # For updates, keep existing password if none provided
            if is_update and before_state:
                hashed_password = before_state['password']
            else:
                return jsonify(error="Password is required for new users"), 400

        user_data = {
            "username": user_to_save,
            "password": hashed_password,
            "role": new_role,
            "store": new_store
        }

        db_retry(
            lambda: extensions.get_db().table("users").upsert(user_data).execute(),
            label="save_user",
        )

        # Log the action
        action = "USER_UPDATE" if is_update else "USER_CREATE"
        audit_log(
            action=action,
            actor=username,
            role=role,
            entity_type="USER",
            entity_id=user_to_save,
            before={"role": before_state['role'], "store": before_state['store']} if before_state else None,
            after={"role": new_role, "store": new_store},
            success=True,
            context={"ip": request.remote_addr}
        )

        logger.info(f"User {user_to_save} {'updated' if is_update else 'created'} by {username}")
        return jsonify(status="success")

    except Exception as e:
        logger.error(f"Error saving user: {e}", exc_info=True)

        audit_log(
            action="USER_SAVE_FAILED",
            actor=username,
            role=role,
            entity_type="USER",
            entity_id=u.get('username') if 'u' in locals() else None,
            success=False,
            error=str(e),
            context={"ip": request.remote_addr}
        )

        return jsonify(error="Internal server error"), 500


@bp.route('/api/users/delete', methods=['POST'])
@require_auth(['admin', 'super_admin'])
def delete_user():
    """Delete a user (admin only) with audit logging and input validation."""
    username = session.get('user')
    role = session.get('role')

    try:
        if not request.json or 'username' not in request.json:
            return jsonify(error="Username is required"), 400

        user_to_delete = request.json['username']

        # Validate username format
        if not user_to_delete or not isinstance(user_to_delete, str):
            return jsonify(error="Invalid username"), 400
        if len(user_to_delete) < 3 or len(user_to_delete) > 50:
            return jsonify(error="Invalid username length"), 400

        # Prevent self-deletion
        if user_to_delete == username:
            return jsonify(error="Cannot delete your own account"), 403

        # Get user details before deletion
        try:
            existing = extensions.get_db().table("users").select("*").eq("username", user_to_delete).execute()
            before_state = existing.data[0] if existing.data else None
            if not before_state:
                return jsonify(error="User not found"), 404
        except Exception as fetch_err:
            logger.warning(f"[delete_user] Failed to fetch user {user_to_delete!r}: {fetch_err}")
            before_state = None

        db_retry(
            lambda: extensions.get_db().table("users").delete().eq("username", user_to_delete).execute(),
            label="delete_user",
        )

        # Log deletion
        audit_log(
            action="USER_DELETE",
            actor=username,
            role=role,
            entity_type="USER",
            entity_id=user_to_delete,
            before={"role": before_state['role'], "store": before_state['store']} if before_state else None,
            success=True,
            context={"ip": request.remote_addr}
        )

        logger.info(f"User {user_to_delete} deleted by {username}")
        return jsonify(status="success")

    except Exception as e:
        logger.error(f"Error deleting user: {e}", exc_info=True)

        audit_log(
            action="USER_DELETE_FAILED",
            actor=username,
            role=role,
            entity_type="USER",
            entity_id=request.json.get('username') if request.json else None,
            success=False,
            error=str(e),
            context={"ip": request.remote_addr}
        )

        return jsonify(error="Internal server error"), 500
