"""Flask application factory — Pharmacy Carimas sales auditor v40-SECURE."""
import os
import sys
import time
import logging
from datetime import timedelta
from flask import Flask, jsonify, redirect, request
from supabase import create_client
from config import Config
import extensions
from helpers.offline_queue import (
    save_to_queue, load_queue, clear_queue, get_queue_path,
    OFFLINE_QUEUE_MAX_SIZE, OFFLINE_FILE,
)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

VERSION = "v40-SECURE"
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
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB — prevents stalled workers on huge uploads
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
    _db = extensions.supabase_admin or extensions.supabase
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

    @app.errorhandler(413)
    def payload_too_large(e):
        return jsonify(error="Payload too large (máximo 5 MB)"), 413

    # APScheduler — EOD reminders (helpers/scheduler.py)
    from helpers.scheduler import init_scheduler
    init_scheduler(app)

    logger.info("--- LAUNCHING %s ON PORT %d ---", VERSION, PORT)
    return app


app = create_app()

_main_tmpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'main.html')
try:
    with open(_main_tmpl, encoding='utf-8') as _f:
        MAIN_UI = _f.read()
except FileNotFoundError:
    MAIN_UI = ''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=Config.DEBUG)
