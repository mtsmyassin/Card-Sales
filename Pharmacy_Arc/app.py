"""Flask application factory — Pharmacy Carimas sales auditor v40-SECURE."""
import os
import sys
import time
import logging
import uuid as _uuid
from logging.handlers import RotatingFileHandler
from datetime import timedelta
from flask import Flask, jsonify, redirect, request
from supabase import create_client
from config import Config
import extensions
from helpers.offline_queue import (
    save_to_queue, load_queue, clear_queue, get_queue_path,
    OFFLINE_QUEUE_MAX_SIZE, OFFLINE_FILE,
)

try:
    from pythonjsonlogger import jsonlogger
    _HAS_JSON_LOGGER = True
except ImportError:
    _HAS_JSON_LOGGER = False

# ── Logging ──────────────────────────────────────────────────────────────────
_log_level = getattr(logging, Config.LOG_LEVEL)
_file_handler = RotatingFileHandler(
    Config.LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8',
)
_stream_handler = logging.StreamHandler(sys.stdout)

if _HAS_JSON_LOGGER:
    _json_fmt = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s',
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    _file_handler.setFormatter(_json_fmt)
    _stream_handler.setFormatter(_json_fmt)
else:
    _text_fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _file_handler.setFormatter(_text_fmt)
    _stream_handler.setFormatter(_text_fmt)

logging.basicConfig(level=_log_level, handlers=[_file_handler, _stream_handler])
logger = logging.getLogger(__name__)

VERSION = extensions.VERSION
PORT = int(os.getenv('PORT', str(Config.PORT)))


def _init_supabase(url: str, key: str, label: str, max_attempts: int = 3):
    """Create a Supabase client, retrying on failure (handles cold-start latency)."""
    for attempt in range(1, max_attempts + 1):
        try:
            client = create_client(url, key)
            logger.info("Supabase %s client connected (attempt %d)", label, attempt)
            return client
        except Exception as exc:
            if attempt == max_attempts:
                logger.critical("Supabase %s: all %d attempts failed: %s", label, max_attempts, exc)
                return None
            delay = 2 ** (attempt - 1)  # 1s, 2s
            logger.warning("Supabase %s: attempt %d failed, retrying in %ds: %s", label, attempt, delay, exc)
            time.sleep(delay)
    return None


def create_app() -> Flask:
    """Build and return the configured Flask application."""
    Config.startup_check()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = Config.SECRET_KEY
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=Config.SESSION_TIMEOUT_MINUTES)
    app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken']
    app.config['MAX_CONTENT_LENGTH'] = Config.MAX_UPLOAD_SIZE
    app.config['APP_VERSION'] = VERSION
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # CSRF — extensions.csrf is a CSRFProtect() instance created in extensions.py
    extensions.csrf.init_app(app)

    # HTTPS enforcement
    if Config.REQUIRE_HTTPS:
        app.config['SESSION_COOKIE_SECURE'] = True
        logger.info("HTTPS enforcement enabled with secure cookie flags")

        @app.before_request
        def enforce_https():
            # Trust X-Forwarded-Proto from reverse proxies (Railway, Heroku, etc.)
            if request.headers.get('X-Forwarded-Proto', 'https') == 'https':
                return  # already secure via proxy
            if not request.is_secure and request.url.startswith('http://'):
                if not (request.host.startswith('127.0.0.1') or
                        request.host.startswith('localhost')):
                    return redirect(request.url.replace('http://', 'https://', 1), code=301)
    else:
        app.config['SESSION_COOKIE_SECURE'] = False

    # ── Request ID middleware ────────────────────────────────────────────────
    @app.before_request
    def attach_request_id():
        request._request_id = _uuid.uuid4().hex[:12]
        request._start_time = time.time()

    @app.after_request
    def log_request_end(response):
        duration_ms = (time.time() - getattr(request, '_start_time', time.time())) * 1000
        rid = getattr(request, '_request_id', '')
        response.headers['X-Request-ID'] = rid
        if request.path != '/health':
            logger.info("[%s] %s %s -> %s (%.0fms)", rid, request.method, request.path, response.status_code, duration_ms)
        return response

    # ── Security headers ─────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob: https://*.supabase.co; "
            "connect-src 'self' https://*.supabase.co; "
            "frame-ancestors 'none'"
        )
        if Config.REQUIRE_HTTPS:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # ── Lazy Supabase reconnect (S3) ─────────────────────────────────────────
    @app.before_request
    def _lazy_reconnect_supabase():
        """Attempt to reconnect Supabase if the anon client is None (throttled to 60s)."""
        if extensions.supabase is not None:
            return
        last = getattr(app, '_last_supabase_reconnect', 0)
        if time.time() - last < 60:
            return
        app._last_supabase_reconnect = time.time()
        extensions.supabase = _init_supabase(Config.SUPABASE_URL, Config.SUPABASE_KEY, "anon", max_attempts=1)
        if extensions.supabase:
            logger.info("Supabase lazy reconnection succeeded")

    # Supabase clients
    extensions.supabase = _init_supabase(Config.SUPABASE_URL, Config.SUPABASE_KEY, "anon")
    if extensions.supabase is None:
        logger.critical("Supabase anon client unavailable — app running in offline mode")

    extensions.supabase_admin = None
    _service_key = Config.SUPABASE_SERVICE_KEY
    if _service_key:
        extensions.supabase_admin = _init_supabase(Config.SUPABASE_URL, _service_key, "admin")
        if extensions.supabase_admin is None:
            logger.warning("Supabase admin client unavailable — photo uploads disabled")

    # Configure Supabase-backed persistence for lockout tracker and audit logger
    _db = extensions.get_db()
    if _db:
        from audit_log import get_audit_logger
        extensions.login_tracker.configure_db(_db)
        logger.info("Login lockout tracker configured with Supabase persistence")
        get_audit_logger().configure_db(_db)
        logger.info("Audit logger configured with Supabase persistence")
    else:
        logger.warning("Login lockout tracker using local file (no Supabase client available)")

    # Emergency backdoor accounts (hashed passwords from env)
    extensions.EMERGENCY_ACCOUNTS = Config.load_emergency_accounts()
    logger.info("Loaded %d emergency admin account(s)", len(extensions.EMERGENCY_ACCOUNTS))

    # Register blueprints
    from routes.main import bp as main_bp
    from routes.auth import bp as auth_bp
    from routes.audits import bp as audits_bp
    from routes.users import bp as users_bp
    from routes.zreports import bp as zreports_bp
    from routes.telegram import bp as telegram_bp
    from routes.diagnostics import bp as diagnostics_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(audits_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(zreports_bp)
    app.register_blueprint(telegram_bp)
    app.register_blueprint(diagnostics_bp)

    # ── Error handlers ───────────────────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error="Bad request"), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error="Not found"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify(error="Method not allowed"), 405

    @app.errorhandler(413)
    def payload_too_large(e):
        max_mb = Config.MAX_UPLOAD_SIZE // (1024 * 1024)
        return jsonify(error=f"Payload too large (maximo {max_mb} MB)"), 413

    @app.errorhandler(500)
    def internal_error(e):
        logger.error("Unhandled 500: %s", e, exc_info=True)
        return jsonify(error="Internal server error"), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        logger.error("Unhandled exception: %s", e, exc_info=True)
        return jsonify(error="Internal server error"), 500

    # APScheduler — EOD reminders (helpers/scheduler.py)
    from helpers.scheduler import init_scheduler
    init_scheduler(app)

    logger.info("--- LAUNCHING %s ON PORT %d ---", VERSION, PORT)
    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=Config.DEBUG)
