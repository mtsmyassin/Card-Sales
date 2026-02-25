"""Main UI Blueprint — serves the SPA shell, favicon, health check, and metrics."""

import io
import logging
import os

import extensions
from config import Config
from flask import Blueprint, current_app, jsonify, render_template, send_file, session
from helpers.auth_utils import require_auth
from helpers.offline_queue import load_queue
from helpers.paths import get_base_path, get_logo

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


@bp.route("/health")
def health():
    """Unauthenticated health check for load balancers and uptime monitors."""
    db_ok = False
    try:
        _db = extensions.get_db()
        if _db:
            _db.table("users").select("username").limit(1).execute()
            db_ok = True
    except Exception:  # noqa: S110 — health check intentionally swallows DB errors
        pass
    status = "ok" if db_ok else "degraded"
    return jsonify(
        status=status,
        version=extensions.VERSION,
        database="connected" if db_ok else "unreachable",
        admin_client="configured" if extensions.has_admin_client() else "missing",
    ), 200 if db_ok else 503


@bp.route("/metrics")
@require_auth(["admin", "super_admin"])
def metrics():
    """Admin-only operational metrics endpoint."""
    return jsonify(
        version=extensions.VERSION,
        offline_queue_depth=len(load_queue()),
        admin_client_available=extensions.has_admin_client(),
    )


@bp.route("/")
def index():
    current_store = session.get("store", "Carimas #1")
    logo_data = get_logo(current_store)
    has_pending = len(load_queue()) > 0
    template = "main.html" if session.get("logged_in") else "login.html"
    version = current_app.config.get("APP_VERSION", "")
    return render_template(template, logo=logo_data, pending=has_pending, version=version, stores=Config.STORES)


@bp.route("/favicon.ico")
def favicon():
    """Serve logo.png as the site favicon (eliminates 404 on every page load)."""
    logo_path = os.path.join(get_base_path(), "logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as fh:
            return send_file(io.BytesIO(fh.read()), mimetype="image/png")
    return "", 204
