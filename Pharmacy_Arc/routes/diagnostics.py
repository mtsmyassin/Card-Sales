"""Diagnostics Blueprint — /api/diagnostics health and status endpoint."""
import os
import logging
from flask import Blueprint, request, jsonify, session
from audit_log import get_audit_logger
import extensions
from helpers.auth_utils import require_auth
from helpers.offline_queue import load_queue
from config import Config

_BUCKET = Config.STORAGE_BUCKET

logger = logging.getLogger(__name__)
bp = Blueprint('diagnostics', __name__)

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
        _db = extensions.get_db()
        db_status = "connected"
        try:
            _db.table("users").select("username").limit(1).execute()
        except Exception as e:
            logger.error(f"[diagnostics] DB connectivity check failed: {e}")
            db_status = "error: connection failed"

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
            "version": extensions.VERSION,
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
        _storage_client = extensions.get_db()
        storage_info = {
            "z_reports_bucket": "unknown",
            "photos_total": 0,
            "photos_missing_path": 0,
        }
        try:
            _storage_client.storage.from_(_BUCKET).list("")
            storage_info["z_reports_bucket"] = "exists"
        except Exception as bucket_err:
            logger.error(f"[diagnostics] Storage bucket check failed: {bucket_err}")
            storage_info["z_reports_bucket"] = "error: bucket check failed"

        try:
            count_resp = _db.table("z_report_photos").select("id", count="exact").execute()
            storage_info["photos_total"] = count_resp.count or 0

            no_path_resp = _db.table("z_report_photos") \
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
        return jsonify(error="Internal server error"), 500
