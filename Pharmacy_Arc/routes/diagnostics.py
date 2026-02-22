"""Diagnostics Blueprint — /api/diagnostics health and status endpoint."""
import os
import logging
from flask import Blueprint, request, jsonify, session
from audit_log import get_audit_logger
import extensions
from helpers.auth_utils import require_auth
from helpers.offline_queue import load_queue
from config import Config

logger = logging.getLogger(__name__)
bp = Blueprint('diagnostics', __name__)

# Match the version string defined in app.py (updated when app.py is rewritten)
_VERSION = "v40-SECURE"
_PORT = int(os.getenv('PORT', str(Config.PORT)))


@bp.route('/api/diagnostics')
@require_auth(['admin', 'super_admin'])
def diagnostics():
    """
    System diagnostics endpoint (admin only).
    Returns system health, version, and configuration status.
    """
    try:
        # Check database connectivity
        db_status = "connected"
        try:
            extensions.supabase.table("users").select("username").limit(1).execute()
        except Exception as e:
            db_status = f"error: {str(e)}"

        # Check audit log integrity
        audit_logger = get_audit_logger()
        audit_valid, audit_errors = audit_logger.verify_integrity()

        # Count pending offline queue
        offline_count = len(load_queue())

        # Get session info
        session_info = {
            "user": session.get('user'),
            "role": session.get('role'),
            "store": session.get('store'),
            "login_time": session.get('login_time'),
        }

        supabase_url = Config.SUPABASE_URL
        diagnostics_data = {
            "version": _VERSION,
            "port": _PORT,
            "database": {
                "status": db_status,
                "url": supabase_url[:30] + "..." if len(supabase_url) > 30 else supabase_url,
                "admin_client": "configured" if extensions.supabase_admin is not None else "NOT SET — bot inserts will fail RLS",
            },
            "audit_log": {
                "integrity": "valid" if audit_valid else "FAILED",
                "errors": audit_errors if not audit_valid else [],
                "entry_count": len(audit_logger.get_entries()),
            },
            "offline_queue": {
                "pending": offline_count,
            },
            "security": {
                "session_timeout_minutes": Config.SESSION_TIMEOUT_MINUTES,
                "max_login_attempts": Config.MAX_LOGIN_ATTEMPTS,
                "emergency_accounts": len(extensions.EMERGENCY_ACCOUNTS),
            },
            "session": session_info,
        }

        # Storage diagnostics — prefer admin client to bypass RLS on bucket listing
        _storage_client = extensions.supabase_admin or extensions.supabase
        storage_info = {
            "z_reports_bucket": "unknown",
            "photos_total": 0,
            "photos_missing_path": 0,
        }
        try:
            _storage_client.storage.from_("z-reports").list("")
            storage_info["z_reports_bucket"] = "exists"
        except Exception as bucket_err:
            storage_info["z_reports_bucket"] = f"error: {bucket_err}"

        try:
            count_resp = extensions.supabase.table("z_report_photos").select("id", count="exact").execute()
            storage_info["photos_total"] = count_resp.count or 0

            no_path_resp = extensions.supabase.table("z_report_photos") \
                .select("id", count="exact") \
                .eq("storage_path", "") \
                .execute()
            storage_info["photos_missing_path"] = no_path_resp.count or 0
        except Exception as diag_err:
            logger.warning(f"diagnostics storage query failed: {diag_err}")

        diagnostics_data["storage"] = storage_info

        logger.info(f"Diagnostics accessed by {session.get('user')}")
        return jsonify(diagnostics_data)

    except Exception as e:
        logger.error(f"Error in diagnostics endpoint: {e}", exc_info=True)
        return jsonify(error=str(e)), 500
