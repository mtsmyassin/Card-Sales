import json, webbrowser, os, sys, base64, re, time, io, hmac
import logging
from functools import wraps
from threading import Timer, Thread
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template_string, request, jsonify, session, redirect, send_file
from flask_wtf.csrf import CSRFProtect, generate_csrf
from supabase import create_client, Client

# Import our security and config modules
try:
    from config import Config
    from security import PasswordHasher, LoginAttemptTracker
    from audit_log import audit_log, get_audit_logger
except ImportError as e:
    print(f"CRITICAL ERROR: Failed to import required modules: {e}")
    print("Please run: pip install -r requirements.txt")
    sys.exit(1)

# --- CONFIGURATION VALIDATION ---
Config.startup_check()

# --- LOGGING SETUP ---
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# --- RBAC DECORATOR (defined early so all routes can use it) ---
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


def _can_access_photo(photo_store, user_role: str, user_store: str) -> bool:
    """Return True if the user is authorized to access a photo from photo_store."""
    if user_role in ("admin", "super_admin"):
        return True
    # If store is NULL in DB, only admins can access (handled above)
    if photo_store is None:
        return False
    return photo_store == user_store


# --- FLASK APP INITIALIZATION ---
# Railway (and most PaaS) inject $PORT — fall back to FLASK_PORT for local dev
PORT = int(os.getenv('PORT', str(Config.PORT)))
VERSION = "v40-SECURE"
print(f"--- LAUNCHING {VERSION} ON PORT {PORT} ---")

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=Config.SESSION_TIMEOUT_MINUTES)
app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken']
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB — prevents stalled workers from huge uploads
csrf = CSRFProtect(app)

@app.errorhandler(413)
def payload_too_large(e):
    return jsonify(error="Payload too large (máximo 5 MB)"), 413

# --- HTTPS ENFORCEMENT MIDDLEWARE ---
# Always set HttpOnly and SameSite flags for session security
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

if Config.REQUIRE_HTTPS:
    @app.before_request
    def enforce_https():
        """Enforce HTTPS if REQUIRE_HTTPS is enabled."""
        if not request.is_secure and request.url.startswith('http://'):
            # Allow localhost for development
            if request.host.startswith('127.0.0.1') or request.host.startswith('localhost'):
                pass
            else:
                url = request.url.replace('http://', 'https://', 1)
                return redirect(url, code=301)
    
    # Set secure cookie flag in production
    app.config['SESSION_COOKIE_SECURE'] = True
    logger.info("HTTPS enforcement enabled with secure cookie flags")
else:
    app.config['SESSION_COOKIE_SECURE'] = False
    logger.warning("⚠️  SESSION_COOKIE_SECURE disabled - HTTPS not required. Enable for production!")


_SESSION_SKIP_ENDPOINTS = frozenset({
    "login", "telegram_webhook", "csrf_token", "static", "favicon", "health",
})

@app.before_request
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


@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
    if Config.REQUIRE_HTTPS:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


# --- SECURITY COMPONENTS ---
password_hasher = PasswordHasher()
login_tracker = LoginAttemptTracker(
    max_attempts=Config.MAX_LOGIN_ATTEMPTS,
    lockout_duration_minutes=Config.LOCKOUT_DURATION_MINUTES
)

# Emergency admin accounts (hashed passwords)
EMERGENCY_ACCOUNTS = Config.load_emergency_accounts()
logger.info(f"Loaded {len(EMERGENCY_ACCOUNTS)} emergency admin account(s)")

# --- 1. CLOUD & LOCAL CONFIGURATION ---
SUPABASE_URL = Config.SUPABASE_URL
SUPABASE_KEY = Config.SUPABASE_KEY
OFFLINE_FILE = Config.OFFLINE_FILE

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

supabase = _init_supabase(SUPABASE_URL, SUPABASE_KEY, "anon")
if supabase is None:
    print("CRITICAL ERROR: Supabase anon client unavailable — app running in offline mode")

# Admin client (service role key) — used for storage operations that require
# elevated permissions (e.g. creating buckets, bypassing RLS on uploads).
# Optional: if SUPABASE_SERVICE_KEY is not set, photo uploads are skipped.
supabase_admin = None
_service_key = Config.SUPABASE_SERVICE_KEY
if _service_key:
    supabase_admin = _init_supabase(SUPABASE_URL, _service_key, "admin")
    if supabase_admin is None:
        logger.warning("Supabase admin client unavailable — photo uploads disabled")

# Switch lockout tracker to Supabase-backed persistence so lockouts survive
# Railway redeploys (ephemeral filesystem would wipe the local file on every deploy).
_lockout_db = supabase_admin or supabase
if _lockout_db:
    login_tracker.configure_db(_lockout_db)
    logger.info("Login lockout tracker configured with Supabase persistence")
    get_audit_logger().configure_db(_lockout_db)
    logger.info("Audit logger configured with Supabase persistence")
else:
    logger.warning("Login lockout tracker using local file (no Supabase client available)")

# --- INPUT VALIDATION HELPERS ---
def validate_audit_entry(data: dict) -> tuple[bool, str]:
    """
    Validate audit entry data.
    Returns (is_valid, error_message).
    """
    # Required fields
    required_fields = ['date', 'reg', 'staff', 'gross', 'net', 'variance']
    for field in required_fields:
        if field not in data or data[field] is None or data[field] == '':
            return False, f"Missing required field: {field}"
    
    # Validate date format (YYYY-MM-DD)
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(data['date'])):
        return False, "Invalid date format. Use YYYY-MM-DD"
    
    # Validate numeric fields
    try:
        gross = float(data['gross'])
        net = float(data['net'])
        variance = float(data['variance'])
        
        # Range checks
        if gross < 0 or gross > 1000000:
            return False, "Gross must be between 0 and 1,000,000"
        if net < -100000 or net > 1000000:
            return False, "Net must be between -100,000 and 1,000,000"
        if abs(variance) > 100000:
            return False, "Variance must be between -100,000 and 100,000"
    except (ValueError, TypeError):
        return False, "Invalid numeric values in gross, net, or variance"
    
    # Validate string lengths
    if len(str(data['reg'])) > 50:
        return False, "Register name too long (max 50 characters)"
    if len(str(data['staff'])) > 100:
        return False, "Staff name too long (max 100 characters)"
    
    # Validate store if provided
    if 'store' in data and data['store']:
        valid_stores = ['Carimas #1', 'Carimas #2', 'Carimas #3', 'Carimas #4', 'Carthage', 'Main']
        if data['store'] not in valid_stores:
            return False, f"Invalid store. Must be one of: {', '.join(valid_stores)}"

    # Math cross-check: if breakdown is present, verify gross/net/variance are consistent
    if 'breakdown' in data and isinstance(data.get('breakdown'), dict):
        b = data['breakdown']
        try:
            card_keys = ['ath', 'athm', 'visa', 'mc', 'amex', 'disc', 'wic', 'mcs', 'sss']
            cash_sales = float(b.get('cash', 0))
            card_sales = sum(float(b.get(k, 0)) for k in card_keys)
            payouts = float(b.get('payouts', 0))
            float_amount = float(b.get('float', 0))
            actual = float(b.get('actual', 0))
            TOLERANCE = 0.02  # 2-cent floating-point tolerance

            expected_gross = cash_sales + card_sales
            if abs(gross - expected_gross) > TOLERANCE:
                return False, f"Gross mismatch: got {gross:.2f}, expected {expected_gross:.2f} (cash + cards)"

            expected_net = expected_gross - payouts
            if abs(net - expected_net) > TOLERANCE:
                return False, f"Net mismatch: got {net:.2f}, expected {expected_net:.2f} (gross - payouts)"

            expected_variance = (actual - float_amount) - (cash_sales - payouts)
            if abs(variance - expected_variance) > TOLERANCE:
                return False, f"Variance mismatch: got {variance:.2f}, expected {expected_variance:.2f}"
        except (TypeError, ValueError):
            pass  # Malformed breakdown values are caught by earlier validation

    return True, ""

def validate_user_data(data: dict, is_update: bool = False) -> tuple[bool, str]:
    """
    Validate user account data.
    Returns (is_valid, error_message).
    """
    # Username validation
    if 'username' not in data or not data['username']:
        return False, "Username is required"
    
    username = str(data['username'])
    if len(username) < 3 or len(username) > 50:
        return False, "Username must be 3-50 characters"
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        return False, "Username can only contain letters, numbers, hyphens, and underscores"
    
    # Password validation (only for new users or if password is being changed)
    if 'password' in data and data['password']:
        password = str(data['password'])
        # Skip validation if it's already a bcrypt hash
        if not password.startswith('$2b$'):
            if len(password) < 8:
                return False, "Password must be at least 8 characters"
            if len(password) > 100:
                return False, "Password must be less than 100 characters"
    elif not is_update:
        return False, "Password is required for new users"
    
    # Role validation
    if 'role' in data and data['role']:
        valid_roles = ['staff', 'manager', 'admin', 'super_admin']
        if data['role'] not in valid_roles:
            return False, f"Invalid role. Must be one of: {', '.join(valid_roles)}"
    
    # Store validation
    if 'store' in data and data['store']:
        valid_stores = ['All', 'Carimas #1', 'Carimas #2', 'Carimas #3', 'Carimas #4', 'Carthage']
        if data['store'] not in valid_stores:
            return False, f"Invalid store. Must be one of: {', '.join(valid_stores)}"
    
    return True, ""

# --- 2. PATHS & ASSETS ---
def get_base_path():
    return sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

def get_queue_path():
    onedrive = os.environ.get('OneDrive') or os.environ.get('OneDriveConsumer')
    target = onedrive if onedrive and os.path.exists(onedrive) else os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(target, OFFLINE_FILE)

def get_logo(store_name=None):
    filename = 'logo.png' 
    if store_name == 'Carthage': filename = 'carthage.png'
    p = os.path.join(get_base_path(), filename)
    if not os.path.exists(p): p = os.path.join(get_base_path(), 'logo.png')
    if not os.path.exists(p):
        return ""
    with open(p, "rb") as fh:
        return base64.b64encode(fh.read()).decode()

# --- 3. OFFLINE HANDLERS ---
OFFLINE_QUEUE_MAX_SIZE = int(os.getenv('OFFLINE_QUEUE_MAX_SIZE', '2000'))

def save_to_queue(payload) -> bool:
    """Append payload to offline queue. Returns False if queue is full (record dropped)."""
    q_path = get_queue_path()
    queue = []
    if os.path.exists(q_path):
        try:
            with open(q_path, encoding='utf-8') as fh:
                queue = json.load(fh)
        except Exception:
            pass
    if len(queue) >= OFFLINE_QUEUE_MAX_SIZE:
        logger.error(
            "Offline queue FULL (%d/%d) — record dropped: date=%s store=%s",
            len(queue), OFFLINE_QUEUE_MAX_SIZE,
            payload.get('date'), payload.get('store'),
        )
        return False
    queue.append(payload)
    with open(q_path, 'w', encoding='utf-8') as f:
        json.dump(queue, f, ensure_ascii=False)
    return True

def load_queue():
    q_path = get_queue_path()
    if os.path.exists(q_path):
        try:
            with open(q_path, encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            return []
    return []

def clear_queue():
    q_path = get_queue_path()
    if os.path.exists(q_path): os.remove(q_path)

# --- 4. API ENDPOINTS ---
@app.route('/')
def index():
    current_store = session.get('store', 'Carimas #1')
    logo_data = get_logo(current_store)
    has_pending = len(load_queue()) > 0
    return render_template_string(MAIN_UI if session.get('logged_in') else LOGIN_UI, logo=logo_data, pending=has_pending)

@app.route('/favicon.ico')
def favicon():
    """Serve logo.png as the site favicon (eliminates 404 on every page load)."""
    logo_path = os.path.join(get_base_path(), 'logo.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as fh:
            return send_file(io.BytesIO(fh.read()), mimetype='image/png')
    return '', 204


@app.route('/api/get_logo', methods=['POST'])
@require_auth()
def api_get_logo():
    """Get store logo with authentication and input validation."""
    try:
        if not request.json:
            return jsonify(error="No data provided"), 400
        
        store = request.json.get('store', 'carimas')
        
        # Whitelist validation to prevent path traversal
        valid_stores = ['Carimas', 'Carimas #1', 'Carimas #2', 'Carimas #3', 'Carimas #4', 'Carthage', None]
        if store not in valid_stores:
            logger.warning(f"Invalid store name requested: {store}")
            store = None  # Default to Carimas logo
        
        return jsonify(logo=get_logo(store))
    except Exception as e:
        logger.error(f"Error in get_logo: {e}")
        return jsonify(error="Internal server error"), 500

@app.route('/api/csrf-token', methods=['GET'])
def csrf_token():
    """Return a fresh CSRF token for the current session."""
    return jsonify(token=generate_csrf())


@app.route('/api/login', methods=['POST'])
@csrf.exempt
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
            return jsonify(status="fail", error="Username and password required"), 400
        
        # Check if account is locked out
        if login_tracker.is_locked_out(u):
            remaining = login_tracker.get_lockout_remaining(u)
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
                error=f"Account locked due to too many failed attempts. Try again in {remaining} seconds."
            ), 429
        
        # --- CHECK EMERGENCY BACKDOOR ACCOUNTS (HASHED) ---
        if u in EMERGENCY_ACCOUNTS:
            stored_hash = EMERGENCY_ACCOUNTS[u]
            if password_hasher.verify_password(p, stored_hash):
                # Determine role based on username
                role = 'super_admin' if u == 'super' else 'admin'
                
                # Regenerate session to prevent fixation
                old_session = dict(session)
                session.clear()
                session.permanent = True
                session['logged_in'] = True
                session['user'] = u
                session['role'] = role
                session['store'] = 'All'
                session['login_time'] = datetime.utcnow().isoformat()
                session['last_active'] = datetime.now(timezone.utc).isoformat()
                
                login_tracker.record_successful_login(u)
                
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
            res = (supabase_admin or supabase).table("users").select("*").eq("username", u).execute()
            if res.data:
                user = res.data[0]
                
                # Check if password is hashed (starts with $2b$ for bcrypt)
                if user['password'].startswith('$2b$'):
                    # Hashed password - verify properly
                    password_valid = password_hasher.verify_password(p, user['password'])
                else:
                    # Legacy plaintext password - still support but auto-upgrade
                    logger.warning(f"User {u} still using plaintext password!")
                    password_valid = (user['password'] == p)
                    if password_valid:
                        try:
                            hashed = password_hasher.hash_password(p)
                            _db = supabase_admin or supabase
                            _db.table("users").update({"password": hashed}).eq("username", u).execute()
                            logger.info(f"[login] Auto-hashed password for {u!r}")
                        except Exception as _he:
                            logger.warning(f"[login] Could not auto-hash password for {u!r}: {_he}")

                if password_valid:
                    # Regenerate session to prevent fixation
                    old_session = dict(session)
                    session.clear()
                    session.permanent = True
                    session['logged_in'] = True
                    session['user'] = u
                    session['role'] = user['role']
                    session['store'] = user['store']
                    session['login_time'] = datetime.utcnow().isoformat()
                    session['last_active'] = datetime.now(timezone.utc).isoformat()
                    
                    login_tracker.record_successful_login(u)
                    
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
        is_locked, remaining_attempts = login_tracker.record_failed_attempt(u)
        
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
            lockout_duration = login_tracker.get_lockout_remaining(u)
            return jsonify(
                status="fail",
                error=f"Too many failed attempts. Account locked for {lockout_duration} seconds."
            ), 429
        else:
            return jsonify(
                status="fail",
                error=f"Invalid credentials. {remaining_attempts} attempts remaining."
            ), 401
    
    except Exception as e:
        logger.error(f"Unexpected error in login: {e}", exc_info=True)
        return jsonify(status="error", error="Internal server error"), 500

@app.route('/api/logout', methods=['POST'])
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

def _send_variance_alert(store: str, date: str, reg: str, variance: float, gross: float, submitted_by: str) -> None:
    """Send Telegram alert to admin/manager bot users when |variance| > $5."""
    try:
        from telegram_bot import send_message
        _db = supabase_admin or supabase
        if _db is None:
            return
        bot_users_resp = _db.table("bot_users").select("telegram_id, username, store").execute()
        if not (bot_users_resp.data):
            return
        # Cross-reference roles
        unames = [u["username"] for u in bot_users_resp.data if u.get("username")]
        role_map = {}
        if unames:
            users_resp = _db.table("users").select("username, role, store").in_("username", unames).execute()
            role_map = {u["username"]: (u.get("role", "staff"), u.get("store", "")) for u in (users_resp.data or [])}
        sign = "🔴 Corto" if variance < 0 else "🟡 Sobre"
        msg = (
            f"⚠️ Varianza {sign}: ${abs(variance):.2f}\n"
            f"Tienda: {store} | Caja: {reg} | Fecha: {date}\n"
            f"Bruto: ${gross:.2f} | Enviado por: {submitted_by}"
        )
        for bu in bot_users_resp.data:
            role, user_store = role_map.get(bu.get("username", ""), ("staff", ""))
            if role in ("admin", "super_admin", "manager") or user_store == store:
                try:
                    send_message(bu["telegram_id"], msg)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"_send_variance_alert failed: {e}")


@app.route('/api/save', methods=['POST'])
@require_auth()
def save():
    """Create a new audit entry with audit logging and input validation."""
    try:
        d = request.json
        if not d:
            return jsonify(error="No data provided"), 400
        
        # Validate input
        is_valid, error_msg = validate_audit_entry(d)
        if not is_valid:
            logger.warning(f"Invalid audit entry data from {session.get('user')}: {error_msg}")
            return jsonify(error=error_msg), 400

        # Duplicate check — use admin client so RLS doesn't hide existing entries
        _dup_db = supabase_admin or supabase
        try:
            dup = _dup_db.table("audits").select("id") \
                .eq("date", d['date']) \
                .eq("store", d.get('store', 'Main')) \
                .eq("reg", d['reg']) \
                .execute()
            if dup.data:
                logger.warning(
                    f"[save] Duplicate entry rejected: user={session.get('user')!r} "
                    f"date={d['date']} store={d.get('store')} reg={d['reg']}"
                )
                return jsonify(
                    error=f"Duplicate: a record for {d['date']} / {d.get('store')} / {d['reg']} already exists.",
                    code="DUPLICATE"
                ), 409
        except Exception as e:
            logger.warning(f"[save] Duplicate check failed (proceeding): {e}")

        username = session.get('user')
        role = session.get('role')

        record = {
            "date": d['date'], 
            "reg": d['reg'], 
            "staff": d['staff'], 
            "store": d.get('store', 'Main'),
            "gross": float(d['gross']), 
            "net": float(d['net']), 
            "variance": float(d['variance']), 
            "payload": d
        }
        
        try:
            result = (supabase_admin or supabase).table("audits").insert(record).execute()
            
            # Log successful creation
            audit_log(
                action="CREATE",
                actor=username,
                role=role,
                entity_type="AUDIT_ENTRY",
                entity_id=str(result.data[0]['id']) if result.data else None,
                after={"date": d['date'], "store": d.get('store'), "gross": d['gross']},
                success=True,
                context={"ip": request.remote_addr}
            )
            
            logger.info(f"Audit entry created by {username}: date={d['date']}, store={d.get('store')}")
            # Variance alert — fire-and-forget, never block the response
            variance_val = float(d.get('variance', 0))
            if abs(variance_val) > 5:
                try:
                    _send_variance_alert(
                        store=d.get('store', 'Main'),
                        date=d['date'],
                        reg=d['reg'],
                        variance=variance_val,
                        gross=float(d['gross']),
                        submitted_by=username,
                    )
                except Exception:
                    pass
            return jsonify(status="success")
        
        except Exception as e:
            logger.warning(f"Failed to save to database, queuing offline: {e}")
            save_to_queue(record)
            
            # Log offline save
            audit_log(
                action="CREATE_OFFLINE",
                actor=username,
                role=role,
                entity_type="AUDIT_ENTRY",
                after={"date": d['date'], "store": d.get('store'), "gross": d['gross']},
                success=True,
                context={"ip": request.remote_addr, "reason": "database_unavailable"}
            )
            
            return jsonify(status="offline")
    
    except Exception as e:
        logger.error(f"Error in save endpoint: {e}", exc_info=True)
        return jsonify(error="Internal server error"), 500

@app.route('/api/sync', methods=['POST'])
@require_auth()
def sync():
    """Sync offline queue to database (authenticated users only)."""
    username = session.get('user')
    role = session.get('role')
    
    queue = load_queue()
    if not queue: return jsonify(status="empty")
    failed_items = []
    success_count = 0
    for item in queue:
        try:
            # Validate before inserting (offline entries skip the /api/save validation)
            ok, err = validate_audit_entry(item)
            if not ok:
                logger.warning(f"[sync] Skipping invalid queue item: {err} — {item}")
                failed_items.append(item)
                continue

            # Duplicate check — DB unique constraint on (date, store, reg)
            _db = supabase_admin or supabase
            date_val = item.get('date')
            store_val = item.get('store')
            reg_val = item.get('reg')
            dup = _db.table("audits").select("id").eq("date", date_val).eq(
                "store", store_val).eq("reg", reg_val).limit(1).execute()
            if dup.data:
                logger.warning(f"[sync] Skipping duplicate: date={date_val} store={store_val} reg={reg_val}")
                success_count += 1  # Don't keep retrying a duplicate — remove from queue
                continue

            _db.table("audits").insert(item).execute()
            success_count += 1

            # Log successful sync
            audit_log(
                action="SYNC",
                actor=username,
                role=role,
                entity_type="OFFLINE_QUEUE",
                success=True,
                context={"ip": request.remote_addr, "records": 1}
            )
        except Exception as exc:
            logger.warning(f"[sync] Insert failed for item date={item.get('date')} store={item.get('store')}: {exc}")
            failed_items.append(item)
    if failed_items:
        q_path = get_queue_path()
        with open(q_path, 'w', encoding='utf-8') as f: json.dump(failed_items, f, ensure_ascii=False)
    else:
        clear_queue()
    return jsonify(status="success", count=success_count, remaining=len(failed_items))

@app.route('/api/update', methods=['POST'])
@require_auth()
def update():
    """Update an audit entry with RBAC, input validation, and audit logging."""
    username = session.get('user')
    role = session.get('role')
    
    # Staff cannot edit
    if role == 'staff':
        logger.warning(f"Staff user {username} attempted to edit entry")
        audit_log(
            action="UPDATE_DENIED",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            success=False,
            error="Staff role cannot edit entries",
            context={"ip": request.remote_addr}
        )
        return jsonify(error="Permission Denied: Staff cannot edit entries"), 403
    
    try:
        d = request.json
        if not d:
            return jsonify(error="No data provided"), 400
        
        # Validate ID
        uid = d.get('id')
        if not uid:
            return jsonify(error="Missing entry ID"), 400
        
        # Validate input
        is_valid, error_msg = validate_audit_entry(d)
        if not is_valid:
            logger.warning(f"Invalid audit entry data from {username}: {error_msg}")
            return jsonify(error=error_msg), 400
        
        # Get current record for audit trail
        try:
            old_record = (supabase_admin or supabase).table("audits").select("*").eq("id", uid).execute()
            before_state = old_record.data[0] if old_record.data else None
        except Exception:
            before_state = None

        record = {
            "date": d['date'],
            "reg": d['reg'],
            "staff": d['staff'], 
            "store": d.get('store', 'Main'),
            "gross": float(d['gross']), 
            "net": float(d['net']), 
            "variance": float(d['variance']), 
            "payload": d
        }
        
        (supabase_admin or supabase).table("audits").update(record).eq("id", uid).execute()
        
        # Log successful update
        audit_log(
            action="UPDATE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(uid),
            before={"date": before_state['date'], "gross": before_state['gross']} if before_state else None,
            after={"date": d['date'], "gross": d['gross']},
            success=True,
            context={"ip": request.remote_addr}
        )
        
        logger.info(f"Audit entry {uid} updated by {username}")
        return jsonify(status="success")
    
    except Exception as e:
        logger.error(f"Error updating entry {uid}: {e}", exc_info=True)
        
        audit_log(
            action="UPDATE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(uid) if uid else None,
            success=False,
            error=str(e),
            context={"ip": request.remote_addr}
        )
        
        return jsonify(error=str(e)), 500

@app.route('/api/delete', methods=['POST'])
@require_auth()
def delete():
    """Delete an audit entry with RBAC and audit logging."""
    username = session.get('user')
    role = session.get('role')
    
    # Staff cannot delete
    if role == 'staff':
        logger.warning(f"Staff user {username} attempted to delete entry")
        audit_log(
            action="DELETE_DENIED",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            success=False,
            error="Staff role cannot delete entries",
            context={"ip": request.remote_addr}
        )
        return jsonify(error="Permission Denied: Staff cannot delete entries"), 403
    
    try:
        uid = request.json['id']
        
        # Get current record for audit trail
        try:
            old_record = (supabase_admin or supabase).table("audits").select("*").eq("id", uid).execute()
            before_state = old_record.data[0] if old_record.data else None
        except Exception:
            before_state = None


        (supabase_admin or supabase).table("audits").delete().eq("id", uid).execute()
        
        # Log successful deletion
        audit_log(
            action="DELETE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(uid),
            before={"date": before_state['date'], "gross": before_state['gross'], "store": before_state['store']} if before_state else None,
            success=True,
            context={"ip": request.remote_addr}
        )
        
        logger.info(f"Audit entry {uid} deleted by {username}")
        return jsonify(status="success")
    
    except Exception as e:
        logger.error(f"Error deleting entry: {e}", exc_info=True)
        
        audit_log(
            action="DELETE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(request.json.get('id')) if request.json.get('id') else None,
            success=False,
            error=str(e),
            context={"ip": request.remote_addr}
        )
        
        return jsonify(error=str(e)), 500

@app.route('/api/list')
@require_auth()
def list_audits():
    """List audit entries filtered by user's store access, with photo counts."""
    try:
        user_store = session.get('store')
        user_role = session.get('role')
        user = session.get('user')

        _db = supabase_admin or supabase
        logger.info(f"[list_audits] using_admin={supabase_admin is not None}")

        # Push store filter to DB for non-admin users — avoids fetching all rows
        query = _db.table("audits").select("*").order("date", desc=True).limit(2000)
        if user_role not in ('admin', 'super_admin'):
            query = query.eq("store", user_store)
        response = query.execute()
        allowed_rows = response.data

        logger.info(
            f"[list_audits] user={user!r} role={user_role!r} store={user_store!r} "
            f"using_admin={supabase_admin is not None} "
            f"rows_returned={len(allowed_rows)}"
        )

        # Batch-fetch photo counts using service-role client to bypass RLS
        photo_counts: dict = {}
        if allowed_rows:
            entry_ids = [r['id'] for r in allowed_rows]
            photo_resp = _db.table("z_report_photos") \
                .select("entry_id") \
                .in_("entry_id", entry_ids) \
                .execute()
            for p in photo_resp.data:
                eid = p['entry_id']
                photo_counts[eid] = photo_counts.get(eid, 0) + 1
            logger.info(
                f"[list_audits] photo_counts fetched: {len(photo_resp.data)} photo rows "
                f"for {len(entry_ids)} entries → {len(photo_counts)} entries have photos"
            )

        clean_rows = []
        for r in allowed_rows:
            merged = r['payload']
            merged['id'] = r['id']
            merged['store'] = r.get('store', 'Main')
            merged['photo_count'] = photo_counts.get(r['id'], 0)
            clean_rows.append(merged)

        return jsonify(clean_rows)
    except Exception as e:
        logger.error(f"[list_audits] Error: {e}", exc_info=True)
        return jsonify(error=str(e), code="LIST_ERROR"), 500


# --- DIAGNOSTIC ENDPOINT ---
@app.route('/api/diagnostics')
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
            supabase.table("users").select("username").limit(1).execute()
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
        
        diagnostics_data = {
            "version": VERSION,
            "port": PORT,
            "database": {
                "status": db_status,
                "url": SUPABASE_URL[:30] + "..." if len(SUPABASE_URL) > 30 else SUPABASE_URL,
                "admin_client": "configured" if supabase_admin is not None else "NOT SET — bot inserts will fail RLS",
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
                "emergency_accounts": len(EMERGENCY_ACCOUNTS),
            },
            "session": session_info,
        }

        # Storage diagnostics — prefer admin client to bypass RLS on bucket listing
        _storage_client = supabase_admin or supabase
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
            count_resp = supabase.table("z_report_photos").select("id", count="exact").execute()
            storage_info["photos_total"] = count_resp.count or 0

            no_path_resp = supabase.table("z_report_photos") \
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

@app.route('/api/users/list')
@require_auth(['admin', 'super_admin'])
def list_users():
    """List all users (admin only)."""
    try:
        result = (supabase_admin or supabase).table("users").select("*").execute()
        logger.info(f"User list accessed by {session.get('user')}")
        return jsonify(result.data)
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return jsonify([])

@app.route('/api/users/save', methods=['POST'])
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
            existing = (supabase_admin or supabase).table("users").select("*").eq("username", user_to_save).execute()
            is_update = len(existing.data) > 0
            before_state = existing.data[0] if is_update else None
        except:
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
            hashed_password = password_hasher.hash_password(password)
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
        
        (supabase_admin or supabase).table("users").upsert(user_data).execute()
        
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
        
        return jsonify(error=str(e)), 500

@app.route('/api/users/delete', methods=['POST'])
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
            existing = (supabase_admin or supabase).table("users").select("*").eq("username", user_to_delete).execute()
            before_state = existing.data[0] if existing.data else None
            if not before_state:
                return jsonify(error="User not found"), 404
        except:
            before_state = None
        
        (supabase_admin or supabase).table("users").delete().eq("username", user_to_delete).execute()
        
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
        
        return jsonify(status="error"), 500


# ── TELEGRAM BOT WEBHOOK ──────────────────────────────────────────────────────

@app.route('/api/telegram/webhook', methods=['POST'])
@csrf.exempt
def telegram_webhook():
    """Receive updates from Telegram and dispatch to bot state machine."""
    # Verify secret token set via TELEGRAM_WEBHOOK_SECRET env var.
    # Use constant-time compare to prevent timing-oracle attacks.
    expected_secret = Config.TELEGRAM_WEBHOOK_SECRET
    incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected_secret:
        logger.warning("Telegram webhook: TELEGRAM_WEBHOOK_SECRET not set — rejecting all requests")
        return jsonify(ok=False), 403
    if not hmac.compare_digest(incoming_secret, expected_secret):
        logger.warning("Telegram webhook: invalid secret token from %s",
                       request.headers.get("X-Forwarded-For", request.remote_addr))
        return jsonify(ok=False), 403

    update = request.json
    if not update:
        return jsonify(ok=False), 400

    def _dispatch():
        try:
            from telegram_bot import handle_update
            handle_update(update)
        except Exception as e:
            logger.error(f"Telegram webhook handler error: {e}", exc_info=True)

    t = Thread(target=_dispatch, daemon=True)
    t.start()

    # Return 200 immediately — Telegram requires a response within 5 seconds
    return jsonify(ok=True)


# ── Z REPORT IMAGE ENDPOINT ───────────────────────────────────────────────────

@app.route('/api/audit/<int:audit_id>/zreport_image')
@require_auth()
def get_zreport_image(audit_id: int):
    """Return a short-lived signed URL for the Z report image of an audit entry (legacy)."""
    try:
        result = supabase.table("audits").select("payload,store").eq("id", audit_id).execute()
        if not result.data:
            return jsonify(error="Not found"), 404

        row = result.data[0]
        entry_store = row.get('store')
        if not _can_access_photo(entry_store, session.get('role'), session.get('store')):
            logger.warning(
                f"[get_zreport_image] IDOR attempt: user={session.get('user')!r} "
                f"tried audit_id={audit_id} (store={entry_store!r})"
            )
            return jsonify(error="Not authorized", code="FORBIDDEN"), 403

        payload = row.get("payload", {})
        image_path = payload.get("z_report_image_path")
        if not image_path:
            return jsonify(error="No image for this entry"), 404

        signed = supabase.storage.from_("z-reports").create_signed_url(image_path, 3600)
        return jsonify(url=signed["signedURL"])

    except Exception as e:
        logger.error(f"get_zreport_image error: {e}", exc_info=True)
        return jsonify(error="Internal server error"), 500


@app.route('/api/zreport/photos')
@require_auth()
def get_entry_photos():
    """Return photo metadata (no URLs) for an audit entry. Store-scoped."""
    entry_id = request.args.get('entry_id', type=int)
    if not entry_id:
        return jsonify(error="entry_id required", code="MISSING_PARAM"), 400

    try:
        # Use service-role client so RLS doesn't block server-side reads
        _db = supabase_admin or supabase
        using_admin = supabase_admin is not None
        logger.info(f"[get_entry_photos] entry_id={entry_id} using_admin={using_admin}")

        entry_resp = _db.table("audits").select("store").eq("id", entry_id).execute()
        if not entry_resp.data:
            logger.warning(f"[get_entry_photos] entry_id={entry_id} not found in audits")
            return jsonify(error="Not found", code="NOT_FOUND"), 404

        entry_store = entry_resp.data[0].get('store')
        if not _can_access_photo(entry_store, session.get('role'), session.get('store')):
            logger.warning(
                f"[get_entry_photos] Access denied: user={session.get('user')!r} "
                f"(store={session.get('store')!r}) tried entry_id={entry_id} (store={entry_store!r})"
            )
            return jsonify(error="Not authorized", code="FORBIDDEN"), 403

        photos = _db.table("z_report_photos") \
            .select("id, store, business_date, register_id, uploaded_by, uploaded_at, storage_path") \
            .eq("entry_id", entry_id) \
            .order("uploaded_at") \
            .execute()

        logger.info(
            f"[get_entry_photos] entry_id={entry_id} store={entry_store!r} "
            f"using_admin={using_admin} → {len(photos.data)} photo(s)"
        )
        return jsonify(photos.data)

    except Exception as e:
        logger.error(f"[get_entry_photos] entry_id={entry_id} EXCEPTION: {e}", exc_info=True)
        return jsonify(error=str(e), code="FETCH_ERROR"), 500


@app.route('/api/zreport/signed_url')
@require_auth()
def get_photo_signed_url():
    """Return a 1-hour signed URL for a specific photo. Store-scoped IDOR check."""
    photo_id = request.args.get('photo_id', type=int)
    if not photo_id:
        return jsonify(error="photo_id required", code="MISSING_PARAM"), 400

    try:
        # Use service-role client so RLS doesn't block server-side reads
        _db = supabase_admin or supabase

        photo_resp = _db.table("z_report_photos").select("*").eq("id", photo_id).execute()
        if not photo_resp.data:
            logger.warning(f"[signed_url] photo_id={photo_id} not found in z_report_photos")
            return jsonify(error="Photo record not found", code="NOT_FOUND"), 404

        photo = photo_resp.data[0]
        storage_path = photo.get('storage_path', '')
        photo_store = photo.get('store')

        if not _can_access_photo(photo_store, session.get('role'), session.get('store')):
            logger.warning(
                f"[signed_url] IDOR attempt: user={session.get('user')!r} "
                f"(store={session.get('store')!r}) tried photo_id={photo_id} "
                f"(store={photo_store!r})"
            )
            return jsonify(error="Not authorized", code="FORBIDDEN"), 403

        if not storage_path:
            logger.error(f"[signed_url] photo_id={photo_id} has empty storage_path")
            return jsonify(error="Photo has no storage path", code="NO_PATH"), 500

        storage_client = supabase_admin or supabase
        logger.info(
            f"[signed_url] Generating URL: photo_id={photo_id} "
            f"bucket=z-reports path={storage_path!r} "
            f"user={session.get('user')!r} using_admin={supabase_admin is not None}"
        )
        signed = storage_client.storage.from_("z-reports").create_signed_url(
            storage_path, 3600
        )
        # storage3 v2.x returns a SignedURLResponse object; older versions returned a dict
        url = signed.signed_url if hasattr(signed, 'signed_url') else signed["signedURL"]
        if not url:
            raise ValueError("create_signed_url returned empty URL")
        logger.info(f"[signed_url] Success: photo_id={photo_id} url_prefix={url[:60]!r}")
        return jsonify(url=url)

    except Exception as e:
        logger.error(
            f"[signed_url] FAILED photo_id={photo_id}: {e}",
            exc_info=True
        )
        return jsonify(error=str(e), code="STORAGE_ERROR"), 500


@app.route('/api/zreport/photo/<int:photo_id>', methods=['DELETE'])
@require_auth(['manager', 'admin', 'super_admin'])
def delete_photo(photo_id):
    """Delete a Z-report photo from storage and DB (manager/admin only)."""
    try:
        _db = supabase_admin or supabase
        photo_resp = _db.table("z_report_photos").select("*") \
            .eq("id", photo_id).maybe_single().execute()

        if not photo_resp.data:
            return jsonify(error="Photo not found", code="NOT_FOUND"), 404

        # IDOR check — non-admins can only delete photos from their own store
        photo_store = photo_resp.data.get('store')
        user_store = session.get('store')
        user_role = session.get('role')
        if user_role not in ('admin', 'super_admin') and photo_store != user_store:
            logger.warning(
                f"[delete_photo] IDOR attempt: user={session.get('user')!r} "
                f"(store={user_store!r}) tried photo_id={photo_id} (store={photo_store!r})"
            )
            return jsonify(error="Not authorized", code="FORBIDDEN"), 403

        # Remove from Supabase Storage (non-fatal if file already gone)
        storage_path = photo_resp.data.get('storage_path', '')
        if storage_path:
            try:
                (supabase_admin or supabase).storage.from_("z-reports").remove([storage_path])
                logger.info(f"[delete_photo] Removed storage file: {storage_path!r}")
            except Exception as e:
                logger.warning(f"[delete_photo] Storage removal failed (continuing): {e}")

        # Delete DB record
        _db.table("z_report_photos").delete().eq("id", photo_id).execute()
        logger.info(
            f"[delete_photo] photo_id={photo_id} deleted by {session.get('user')!r}"
        )
        return jsonify(status="deleted")

    except Exception as e:
        logger.error(f"[delete_photo] Error: {e}", exc_info=True)
        return jsonify(error=str(e), code="DELETE_ERROR"), 500


# ── Z REPORT REVIEW UTILITIES ─────────────────────────────────────────────────

_ZR_PAYMENT_FIELDS = ['cash', 'ath', 'athm', 'visa', 'mc', 'amex', 'disc', 'wic', 'mcs', 'sss']

VALID_REVIEW_STATUSES = (
    'NEEDS_ASSIGNMENT', 'PENDING_REVIEW', 'IN_REVIEW',
    'FINAL_APPROVED', 'REJECTED', 'DUPLICATE', 'AMENDED'
)


def _zr_recalculate(breakdown: dict, payouts_total: float, cash_actual: float) -> dict:
    """Recalculate gross, net, variance from raw breakdown. Raises ValueError on bad data."""
    opening_float = float(breakdown.get('float', 100.0))
    cash = float(breakdown.get('cash', 0))
    gross = sum(float(breakdown.get(f, 0)) for f in _ZR_PAYMENT_FIELDS)
    net = gross - payouts_total
    variance = (cash_actual - opening_float) - (cash - payouts_total)
    if payouts_total > gross + 0.01:
        raise ValueError(f"payouts_total {payouts_total:.2f} exceeds gross {gross:.2f}")
    return {
        'gross': round(gross, 2),
        'net': round(net, 2),
        'variance': round(variance, 2),
        'opening_float': round(opening_float, 2),
    }


def _zr_validate_breakdown(payouts_total: float, payouts_breakdown: dict | None) -> None:
    """Assert payouts_breakdown values sum to payouts_total. Raises ValueError on mismatch."""
    if not payouts_breakdown:
        return
    total = sum(float(v) for v in payouts_breakdown.values())
    if abs(total - payouts_total) > 0.01:
        raise ValueError(
            f"payouts_breakdown sum {total:.2f} != payouts_total {payouts_total:.2f}"
        )


def _zr_log(db_client, audit_id: int, action: str, actor: str,
            ip: str = None, old_val: dict = None, new_val: dict = None,
            reason: str = None) -> None:
    """Append a row to z_report_audit_log. Swallows errors to avoid blocking main flow."""
    try:
        db_client.table('z_report_audit_log').insert({
            'audit_id': audit_id,
            'action': action,
            'actor_username': actor,
            'actor_ip': ip,
            'old_val': old_val,
            'new_val': new_val,
            'reason': reason,
        }).execute()
    except Exception as e:
        logger.error(f"[zr_log] Failed to write audit log for audit_id={audit_id}: {e}")


# ── Z REPORT REVIEW API ───────────────────────────────────────────────────────

@app.route('/api/z-reports')
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
def zr_list():
    """List audits with review status, optional ?status= filter."""
    status_filter = request.args.get('status')
    try:
        q = supabase_admin.table('audits').select(
            'id,store,date,review_status,review_locked_by,review_locked_at'
        ).order('date', desc=True)
        if status_filter and status_filter in VALID_REVIEW_STATUSES:
            q = q.eq('review_status', status_filter)
        result = q.execute()
        return jsonify(result.data)
    except Exception as e:
        logger.error(f"[zr_list] {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>')
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
def zr_detail(audit_id: int):
    """Return audit row plus current review record."""
    try:
        audit = supabase_admin.table('audits').select('*').eq('id', audit_id).single().execute()
        review = supabase_admin.table('z_report_reviews').select('*').eq(
            'audit_id', audit_id).eq('is_current', True).maybe_single().execute()
        return jsonify({'audit': audit.data, 'review': review.data if review else None})
    except Exception as e:
        logger.error(f"[zr_detail] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>/lock', methods=['POST'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
def zr_lock(audit_id: int):
    """Lock an audit for review by the current user."""
    actor = session['user']
    ip = request.remote_addr
    try:
        audit = supabase_admin.table('audits').select(
            'id,store,review_status,review_locked_by,review_locked_at'
        ).eq('id', audit_id).single().execute().data

        if session.get('role') == 'manager' and audit.get('store') != session.get('store'):
            return jsonify(error="You can only review entries for your store"), 403

        status = audit['review_status']
        locked_by = audit.get('review_locked_by')
        locked_at = audit.get('review_locked_at')

        if status in ('PENDING_REVIEW', 'NEEDS_ASSIGNMENT'):
            pass  # always lockable
        elif status == 'IN_REVIEW':
            if locked_by == actor:
                pass  # re-locking own audit is fine
            else:
                # Another user holds the lock — check if it's expired
                from datetime import timezone
                lock_time = datetime.fromisoformat(
                    locked_at.replace('Z', '+00:00')
                ) if locked_at else None
                if lock_time and datetime.now(timezone.utc) - lock_time < timedelta(minutes=30):
                    return jsonify(
                        error=f"Audit is locked by {locked_by}"
                    ), 409
                # Lock expired — allow stealing it
        else:
            return jsonify(error=f"Cannot lock audit in status '{status}'"), 409

        old_status = audit['review_status']
        supabase_admin.table('audits').update({
            'review_status': 'IN_REVIEW',
            'review_locked_by': actor,
            'review_locked_at': datetime.utcnow().isoformat(),
        }).eq('id', audit_id).execute()

        _zr_log(supabase_admin, audit_id, 'LOCK', actor, ip=ip,
                old_val={'review_status': old_status},
                new_val={'review_status': 'IN_REVIEW', 'locked_by': actor})
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_lock] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>/lock', methods=['DELETE'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
def zr_unlock(audit_id: int):
    """Release the review lock on an audit."""
    actor = session['user']
    role = session.get('role')
    ip = request.remote_addr
    try:
        audit = supabase_admin.table('audits').select(
            'id,review_status,review_locked_by'
        ).eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'IN_REVIEW':
            return jsonify(error="Audit is not IN_REVIEW"), 409

        if audit['review_locked_by'] != actor and role not in ('admin', 'super_admin'):
            return jsonify(error="You do not hold the lock on this audit"), 403

        supabase_admin.table('audits').update({
            'review_status': 'PENDING_REVIEW',
            'review_locked_by': None,
            'review_locked_at': None,
        }).eq('id', audit_id).execute()

        _zr_log(supabase_admin, audit_id, 'UNLOCK', actor, ip=ip,
                old_val={'locked_by': audit['review_locked_by']},
                new_val={'review_status': 'PENDING_REVIEW'})
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_unlock] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>/approve', methods=['POST'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
def zr_approve(audit_id: int):
    """Approve a Z Report. Recalculates figures server-side."""
    actor = session['user']
    ip = request.remote_addr
    body = request.get_json(force=True) or {}

    payouts_total = float(body.get('payouts_total', 0))
    cash_actual = float(body.get('cash_in_register_actual', 0))
    payouts_breakdown = body.get('payouts_breakdown')
    manager_notes = body.get('manager_notes', '')

    try:
        _zr_validate_breakdown(payouts_total, payouts_breakdown)
    except ValueError as e:
        return jsonify(error=str(e)), 400

    try:
        audit = supabase_admin.table('audits').select('*').eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'IN_REVIEW':
            return jsonify(error=f"Audit is not IN_REVIEW (status: {audit['review_status']})"), 409
        if audit.get('review_locked_by') != actor:
            return jsonify(error="You do not hold the lock on this audit"), 403
        if session.get('role') == 'manager' and audit.get('store') != session.get('store'):
            return jsonify(error="You can only review entries for your store"), 403

        breakdown = (audit.get('payload') or {}).get('breakdown', {})
        try:
            calc = _zr_recalculate(breakdown, payouts_total, cash_actual)
        except ValueError as e:
            return jsonify(error=str(e)), 400

        # Mark previous review as not current
        supabase_admin.table('z_report_reviews').update({'is_current': False}).eq(
            'audit_id', audit_id).eq('is_current', True).execute()

        # Get next version number
        existing = supabase_admin.table('z_report_reviews').select('version').eq(
            'audit_id', audit_id).order('version', desc=True).limit(1).execute()
        next_version = (existing.data[0]['version'] + 1) if existing.data else 1

        supabase_admin.table('z_report_reviews').insert({
            'audit_id': audit_id,
            'payouts_total': payouts_total,
            'cash_in_register_actual': cash_actual,
            'payouts_breakdown': payouts_breakdown,
            'manager_notes': manager_notes,
            'calculated_gross': calc['gross'],
            'calculated_net': calc['net'],
            'calculated_variance': calc['variance'],
            'opening_float_used': calc['opening_float'],
            'reviewed_by': actor,
            'approved_ip': ip,
            'action': 'APPROVED',
            'version': next_version,
            'is_current': True,
        }).execute()

        old_status = audit['review_status']
        supabase_admin.table('audits').update({
            'review_status': 'FINAL_APPROVED',
            'review_locked_by': None,
            'review_locked_at': None,
        }).eq('id', audit_id).execute()

        _zr_log(supabase_admin, audit_id, 'APPROVE', actor, ip=ip,
                old_val={'review_status': old_status},
                new_val={'review_status': 'FINAL_APPROVED', 'gross': calc['gross'],
                         'net': calc['net'], 'variance': calc['variance']})
        return jsonify(ok=True, **calc)
    except Exception as e:
        logger.error(f"[zr_approve] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>/reject', methods=['POST'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
def zr_reject(audit_id: int):
    """Reject a Z Report with a mandatory reason."""
    actor = session['user']
    ip = request.remote_addr
    body = request.get_json(force=True) or {}
    reason = (body.get('rejection_reason') or '').strip()
    if not reason:
        return jsonify(error="rejection_reason is required"), 400

    try:
        audit = supabase_admin.table('audits').select(
            'id,store,review_status,review_locked_by'
        ).eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'IN_REVIEW':
            return jsonify(error=f"Audit is not IN_REVIEW (status: {audit['review_status']})"), 409
        if audit.get('review_locked_by') != actor:
            return jsonify(error="You do not hold the lock on this audit"), 403
        if session.get('role') == 'manager' and audit.get('store') != session.get('store'):
            return jsonify(error="You can only review entries for your store"), 403

        existing = supabase_admin.table('z_report_reviews').select('version').eq(
            'audit_id', audit_id).order('version', desc=True).limit(1).execute()
        next_version = (existing.data[0]['version'] + 1) if existing.data else 1

        supabase_admin.table('z_report_reviews').update({'is_current': False}).eq(
            'audit_id', audit_id).eq('is_current', True).execute()

        supabase_admin.table('z_report_reviews').insert({
            'audit_id': audit_id,
            'payouts_total': 0,
            'cash_in_register_actual': 0,
            'calculated_gross': 0,
            'calculated_net': 0,
            'calculated_variance': 0,
            'opening_float_used': 100,
            'reviewed_by': actor,
            'approved_ip': ip,
            'action': 'REJECTED',
            'rejection_reason': reason,
            'version': next_version,
            'is_current': True,
        }).execute()

        old_status = audit['review_status']
        supabase_admin.table('audits').update({
            'review_status': 'REJECTED',
            'review_locked_by': None,
            'review_locked_at': None,
        }).eq('id', audit_id).execute()

        _zr_log(supabase_admin, audit_id, 'REJECT', actor, ip=ip,
                old_val={'review_status': old_status},
                new_val={'review_status': 'REJECTED'},
                reason=reason)
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_reject] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>/reopen', methods=['POST'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
def zr_reopen(audit_id: int):
    """Reopen a REJECTED audit back to PENDING_REVIEW so it can be re-reviewed."""
    actor = session['user']
    ip = request.remote_addr
    body = request.get_json(force=True) or {}
    reason = (body.get('reason') or '').strip()
    if not reason:
        return jsonify(error="reason is required"), 400

    try:
        audit = supabase_admin.table('audits').select(
            'id,store,review_status'
        ).eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'REJECTED':
            return jsonify(error=f"Audit is not REJECTED (status: {audit['review_status']})"), 409
        if session.get('role') == 'manager' and audit.get('store') != session.get('store'):
            return jsonify(error="You can only reopen entries for your store"), 403

        supabase_admin.table('audits').update({
            'review_status': 'PENDING_REVIEW',
            'review_locked_by': None,
            'review_locked_at': None,
        }).eq('id', audit_id).execute()

        _zr_log(supabase_admin, audit_id, 'REOPEN', actor, ip=ip,
                old_val={'review_status': 'REJECTED'},
                new_val={'review_status': 'PENDING_REVIEW'},
                reason=reason)
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_reopen] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>/amend', methods=['POST'])
@require_auth(allowed_roles=['admin', 'super_admin'])
def zr_amend(audit_id: int):
    """Reopen a FINAL_APPROVED audit for amendment (admin only)."""
    actor = session['user']
    ip = request.remote_addr
    body = request.get_json(force=True) or {}
    reason = (body.get('amendment_reason') or '').strip()
    if not reason:
        return jsonify(error="amendment_reason is required"), 400

    try:
        audit = supabase_admin.table('audits').select(
            'id,review_status'
        ).eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'FINAL_APPROVED':
            return jsonify(
                error=f"Can only amend FINAL_APPROVED audits (status: {audit['review_status']})"
            ), 409

        # Get current review row to link amendment chain
        current = supabase_admin.table('z_report_reviews').select('id,version').eq(
            'audit_id', audit_id).eq('is_current', True).maybe_single().execute()
        current_data = current.data if current else None
        amendment_of_id = current_data['id'] if current_data else None
        next_version = (current_data['version'] + 1) if current_data else 1

        supabase_admin.table('z_report_reviews').update({'is_current': False}).eq(
            'audit_id', audit_id).eq('is_current', True).execute()

        supabase_admin.table('z_report_reviews').insert({
            'audit_id': audit_id,
            'payouts_total': 0,
            'cash_in_register_actual': 0,
            'calculated_gross': 0,
            'calculated_net': 0,
            'calculated_variance': 0,
            'opening_float_used': 100,
            'reviewed_by': actor,
            'approved_ip': ip,
            'action': 'AMENDED',
            'amendment_reason': reason,
            'amendment_of_id': amendment_of_id,
            'version': next_version,
            'is_current': True,
        }).execute()

        supabase_admin.table('audits').update({
            'review_status': 'PENDING_REVIEW',
            'review_locked_by': None,
            'review_locked_at': None,
        }).eq('id', audit_id).execute()

        _zr_log(supabase_admin, audit_id, 'AMEND', actor, ip=ip,
                old_val={'review_status': 'FINAL_APPROVED'},
                new_val={'review_status': 'PENDING_REVIEW'},
                reason=reason)
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_amend] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>/history')
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
def zr_history(audit_id: int):
    """Return all review records for an audit, newest first."""
    try:
        result = supabase_admin.table('z_report_reviews').select('*').eq(
            'audit_id', audit_id).order('version', desc=True).execute()
        return jsonify(result.data)
    except Exception as e:
        logger.error(f"[zr_history] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/<int:audit_id>/audit-log')
@require_auth(allowed_roles=['admin', 'super_admin'])
def zr_audit_log(audit_id: int):
    """Return the audit trail for a Z Report (admin only)."""
    try:
        result = supabase_admin.table('z_report_audit_log').select('*').eq(
            'audit_id', audit_id).order('ts', desc=True).execute()
        return jsonify(result.data)
    except Exception as e:
        logger.error(f"[zr_audit_log] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error=str(e)), 500


@app.route('/api/z-reports/unlock-timed-out', methods=['POST'])
@require_auth(allowed_roles=['admin', 'super_admin'])
def zr_unlock_timed_out():
    """Release all locks older than 30 minutes (admin cron / manual trigger)."""
    actor = session['user']
    ip = request.remote_addr
    cutoff = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
    try:
        stale = supabase_admin.table('audits').select('id,review_locked_by').eq(
            'review_status', 'IN_REVIEW').lt('review_locked_at', cutoff).execute()
        count = 0
        for row in stale.data:
            supabase_admin.table('audits').update({
                'review_status': 'PENDING_REVIEW',
                'review_locked_by': None,
                'review_locked_at': None,
            }).eq('id', row['id']).execute()
            _zr_log(supabase_admin, row['id'], 'UNLOCK', actor, ip=ip,
                    old_val={'locked_by': row['review_locked_by']},
                    new_val={'review_status': 'PENDING_REVIEW'},
                    reason='lock_timeout')
            count += 1
        return jsonify(ok=True, unlocked=count)
    except Exception as e:
        logger.error(f"[zr_unlock_timed_out] {e}", exc_info=True)
        return jsonify(error=str(e)), 500


# --- 4. FRONTEND UI ---
LOGIN_UI = """<!DOCTYPE html><html><body style="background:#0f172a;color:white;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;">
<div style="background:#1e293b;padding:40px;border-radius:20px;text-align:center;width:320px;border:1px solid #334155;">
{% if logo %}<img src="data:image/png;base64,{{logo}}" style="max-width:140px;margin-bottom:20px">{% endif %}
<h2>System Login</h2><small style="color:#0097b2;font-weight:900;font-size:14px">""" + VERSION + """</small><br><br>
<div id="errorMsg" style="display:none;background:#fee2e2;color:#991b1b;padding:10px;border-radius:8px;margin-bottom:15px;font-size:13px;font-weight:600;"></div>
<input type="text" id="u" placeholder="Username" style="width:90%;padding:12px;margin-bottom:10px;border-radius:8px;border:none;text-align:center;font-weight:bold;font-size:16px;">
<input type="password" id="p" placeholder="Password" style="width:90%;padding:12px;margin-bottom:20px;border-radius:8px;border:none;text-align:center;font-weight:bold;font-size:16px;">
<button onclick="l()" id="loginBtn" style="width:100%;padding:12px;background:#0097b2;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:bold;font-size:16px;">Login</button>
</div><script>
function l(){
    const btn = document.getElementById('loginBtn');
    const errDiv = document.getElementById('errorMsg');
    btn.disabled = true;
    btn.innerText = 'Logging in...';
    errDiv.style.display = 'none';
    
    fetch('/api/login',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
            username:document.getElementById('u').value,
            password:document.getElementById('p').value
        })
    })
    .then(r => r.json().then(d => ({status: r.status, data: d})))
    .then(({status, data}) => {
        if(data.status==='ok'){
            localStorage.setItem('role',data.role);
            localStorage.setItem('store',data.store);
            localStorage.setItem('user',data.username);
            location.reload();
        } else {
            errDiv.innerText = data.error || 'Invalid credentials';
            errDiv.style.display = 'block';
            btn.disabled = false;
            btn.innerText = 'Login';
        }
    })
    .catch(e => {
        errDiv.innerText = 'Connection error. Please try again.';
        errDiv.style.display = 'block';
        btn.disabled = false;
        btn.innerText = 'Login';
    });
}
document.getElementById('p').addEventListener('keypress', function(e){
    if(e.key === 'Enter') l();
});
</script></body></html>"""

MAIN_UI = """<!DOCTYPE html><html><head><title>Pharmacy Director</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.0.0"></script>
<style>
/* TURQUOISE BRANDING */
:root{--p:#0097b2;--sidebar:#00697d;--sidebar-dark:#00525f;--bg:#7a9aaa;--card:#ffffff;--danger:#ef4444;--success:#047857;--txt:#1e293b;--muted:#64748b;--warn:#f59e0b;}
*{box-sizing:border-box; font-family: 'Segoe UI', system-ui, sans-serif;}
body{background-color:var(--bg);margin:0;padding:0;color:var(--txt);min-height:100vh;display:flex;}
/* WATERMARK: Full Color, Visible */
.watermark {
    position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
    width: 500px; opacity: 0.15; z-index: -1; pointer-events: none;
}

/* SIDEBAR */
.sidebar{
    position:fixed; top:0; left:0; width:220px; height:100vh;
    background:var(--sidebar); display:flex; flex-direction:column;
    z-index:100; box-shadow:4px 0 20px rgba(0,0,0,0.15);
}
.sidebar-logo{
    padding:24px 20px 16px; border-bottom:1px solid rgba(255,255,255,0.15);
    display:flex; flex-direction:column; align-items:center; gap:10px;
}
.sidebar-logo img{max-width:150px; filter:brightness(0) invert(1);}
.sidebar-logo h2{display:none;}
.sidebar-nav{flex:1; padding:16px 12px; display:flex; flex-direction:column; gap:4px;}
.tab-btn{
    display:flex; align-items:center; gap:10px;
    padding:11px 14px; border-radius:10px; cursor:pointer;
    border:none; color:rgba(255,255,255,0.75); font-weight:700; font-size:13px;
    transition:0.2s; background:transparent; width:100%; text-align:left;
}
.tab-btn:hover{background:rgba(255,255,255,0.12); color:white;}
.tab-btn.active{background:white; color:var(--sidebar); box-shadow:0 2px 8px rgba(0,0,0,0.15);}
.tab-icon{font-size:16px; width:20px; text-align:center;}
.sidebar-footer{
    padding:16px 12px; border-top:1px solid rgba(255,255,255,0.15);
    display:flex; flex-direction:column; gap:8px;
}
.sidebar-user{color:rgba(255,255,255,0.7); font-size:11px; font-weight:800; text-transform:uppercase; padding:0 4px;}

/* MAIN CONTENT */
.main-content{margin-left:220px; flex:1; padding:30px; min-height:100vh;}

/* PANEL becomes a section card */
.panel{background:var(--card); padding:28px; border-radius:14px; box-shadow:0 2px 12px rgba(0,0,0,0.07); border:1px solid #e8edf2;}

.view{display:none;} .view.active{display:block;}
.grid-form{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;}
input,select{width:100%;padding:11px 13px;border:1.5px solid #cbd5e1;border-radius:8px;margin-bottom:15px;color:#1e293b;background:#fff;font-weight:600;transition:border-color 0.2s,box-shadow 0.2s;}
input:focus,select:focus{outline:none;border-color:var(--p);box-shadow:0 0 0 3px rgba(0,151,178,0.12);}
.btn-main{background:var(--p);color:white;padding:13px 32px;border:none;border-radius:10px;cursor:pointer;font-size:14px;font-weight:800;transition:background 0.2s;width:auto;}
.btn-main:hover{background:var(--sidebar);}

.section{font-size:11px;color:var(--sidebar);text-transform:uppercase;margin:24px 0 14px;padding-bottom:8px;border-bottom:2px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;letter-spacing:1.2px;font-weight:900;}
.section-badge{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;background:var(--sidebar);color:white;border-radius:50%;font-size:11px;font-weight:900;margin-right:8px;flex-shrink:0;}

/* --- ENTERPRISE ANALYTICS STYLES --- */
.control-bar { display:flex; justify-content:space-between; align-items:center; background:white; padding:15px 20px; border-radius:12px; border:1px solid #e2e8f0; margin-bottom:25px; flex-wrap:wrap; gap:15px; box-shadow:0 2px 4px rgba(0,0,0,0.02); }
.control-group { display:flex; align-items:center; gap:10px; }
.control-label { font-size:12px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; }

.cc-container { display:flex; flex-direction:column; gap:30px; padding-bottom:40px; }
.section-header { font-size:14px; font-weight:800; color:#1e293b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; padding-bottom:8px; margin-bottom:15px; display:flex; align-items:center; gap:10px; }

/* KPI CARDS */
.kpi-row { display:grid; grid-template-columns:repeat(4,1fr); gap:20px; }
.kpi-card { background:white; padding:20px; border-radius:12px; border:1px solid #f1f5f9; box-shadow:0 4px 6px -2px rgba(0,0,0,0.05); display:flex; flex-direction:column; justify-content:center; transition:transform 0.2s; }
.kpi-card:hover { transform:translateY(-2px); box-shadow:0 10px 15px -3px rgba(0,0,0,0.05); }
.kpi-val { font-size: 28px; font-weight: 900; color: #1e293b; letter-spacing:-0.5px; margin: 8px 0; }
.kpi-label { font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 800; letter-spacing:0.5px; }
.kpi-accent-teal { border-left:4px solid #0097b2; }
.kpi-accent-green { border-left:4px solid #047857; }
.kpi-accent-blue { border-left:4px solid #3b82f6; }
.kpi-accent-amber { border-left:4px solid #f59e0b; }

/* HERO ROW */
.hero-row { display:grid; grid-template-columns:3fr 1fr; gap:20px; min-height:400px; }
.chart-shell { background:white; border-radius:12px; padding:20px; border:1px solid #f1f5f9; box-shadow:0 4px 6px -2px rgba(0,0,0,0.05); display:flex; flex-direction:column; height:100%; }
.chart-shell h4 { margin:0 0 15px 0; font-size:13px; color:#475569; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; }
.leaderboard-container { flex:1; overflow-y:auto; padding-right:5px; }
.lb-item { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid #f8fafc; font-size: 13px; font-weight: 600; }
.lb-tag { padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 800; text-transform: uppercase; }
.tag-green { background: #dcfce7; color: #166534; } .tag-red { background: #fee2e2; color: #991b1b; }
.lb-date { color:#64748b; font-weight:600; } .lb-val { font-weight:700; }

/* SIGNALS ROW */
.signals-row { display:grid; grid-template-columns:repeat(3,1fr); gap:20px; min-height:300px; }

/* ACTION BUTTONS */
.action-btn { border:none; padding:8px 12px; border-radius:6px; cursor:pointer; font-weight:bold; font-size:12px; margin-left:4px; }
.btn-print { background: #eff6ff; color: #1d4ed8; } .btn-edit { background: #fffbeb; color: #b45309; } .btn-del { background: #fef2f2; color: #b91c1c; }

/* RESPONSIVE */
@media (max-width:1100px) {
    .hero-row { grid-template-columns:1fr; height:auto; }
    .signals-row { grid-template-columns:1fr; height:auto; }
    .kpi-row { grid-template-columns:1fr 1fr; }
}
@media (max-width:640px) {
    .kpi-row { grid-template-columns:1fr; }
    .control-bar { flex-direction:column; align-items:flex-start; }
    .control-group { width:100%; justify-content:space-between; }
    .control-bar select, .control-bar input { flex:1; }
}

/* MOBILE SIDEBAR */
#menuToggle { display:none; }
@media (max-width:768px) {
    #menuToggle {
        display:block; position:fixed; top:12px; left:12px; z-index:200;
        background:var(--sidebar); color:white; border:none; border-radius:8px;
        padding:8px 12px; font-size:20px; cursor:pointer; line-height:1;
        box-shadow:0 2px 8px rgba(0,0,0,0.25);
    }
    .sidebar {
        transform:translateX(-100%);
        transition:transform 0.25s ease;
    }
    .sidebar.open { transform:translateX(0); }
    .main-content { margin-left:0 !important; padding:20px 14px; padding-top:56px; }
}

table{width:100%;border-collapse:collapse;} th,td{padding:12px;text-align:left;border-bottom:1px solid #f1f5f9; font-weight:600;}
.hidden{display:none !important;}

/* Loading Overlay */
.loading-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(255,255,255,0.85);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 9999;
    font-weight: 800;
    font-size: 18px;
    color: #0097b2;
}
.loading-spinner {
    display: inline-block;
    width: 20px;
    height: 20px;
    border: 3px solid #e2e8f0;
    border-top-color: #0097b2;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-right: 10px;
}
@keyframes spin {
    to { transform: rotate(360deg); }
}
</style></head><body>

<div id="loadingOverlay" class="loading-overlay" style="display:none;">
    <div class="loading-spinner"></div>
    Loading...
</div>

<img src="data:image/png;base64,{{logo}}" class="watermark">

<button id="menuToggle" onclick="app.toggleMenu()" aria-label="Open menu">&#9776;</button>

<div class="sidebar">
    <div class="sidebar-logo">
        <img id="sidebarLogo" src="data:image/png;base64,{{logo}}" alt="Farmacia Carimas">
        <h2>Farmacia Carimas</h2>
    </div>
    <nav class="sidebar-nav">
        <div id="tab-dash" class="tab-btn active" onclick="app.tab('dash')"><span class="tab-icon">📋</span>Audit Entry</div>
        <div id="tab-calendar" class="tab-btn" onclick="app.tab('calendar')"><span class="tab-icon">📅</span>Calendar</div>
        <div id="tab-analytics" class="tab-btn" onclick="app.tab('analytics')"><span class="tab-icon">📊</span>Command Center</div>
        <div id="tab-logs" class="tab-btn" onclick="app.tab('logs')"><span class="tab-icon">📜</span>History</div>
        <div id="tab-users" class="tab-btn" onclick="app.tab('users')"><span class="tab-icon">👥</span>Users</div>
        <div id="tab-zreviews" class="tab-btn" onclick="app.tab('zreviews')"><span class="tab-icon">🔍</span>Z Reviews</div>
    </nav>
    <div class="sidebar-footer">
        <div class="sidebar-user" id="userDisplay"></div>
        <button id="syncBtn" style="background:#f59e0b;color:white;border:none;padding:6px 10px;border-radius:6px;font-weight:bold;font-size:12px;display:none;cursor:pointer">⚠️ Sync</button>
        <button onclick="app.logout()" style="padding:9px 14px;cursor:pointer;background:#ef4444;color:white;border:none;border-radius:8px;font-size:12px;font-weight:800;width:100%">Log Out</button>
    </div>
</div>

<div class="main-content">
<div id="dash" class="view active">
    <div class="panel" id="dashPanel">
        <input type="hidden" id="editId" value="">
        <div class="section" style="margin-top:0" id="modeLabel"><span><span class="section-badge">1</span>Store & Metadata</span></div>
        <div class="grid-form">
            <div><label>Store Location</label><select id="storeLoc" onchange="app.checkStore()"><option>Carimas #1</option><option>Carimas #2</option><option>Carimas #3</option><option>Carimas #4</option><option>Carthage</option></select></div>
            <div><label>Date</label><input type="date" id="date"></div>
            <div><label>Register</label><select id="reg"><option>Reg 1</option><option>Reg 2</option><option>Reg 3</option><option>Reg 4</option><option>Reg 5</option><option>Reg 6</option><option>Reg 7</option><option>Reg 8</option></select></div>
            <div><label>Staff Name</label><input type="text" id="staff" list="staffList" placeholder="Name"><datalist id="staffList"><option>Manager</option><option>Pharmacist</option><option>Clerk</option></datalist></div>
        </div>
        <div class="section"><span><span class="section-badge">2</span>Revenue</span></div>
        <div style="display:grid;grid-template-columns:1fr 4fr;gap:20px">
            <div><label>Cash Sales</label><input type="number" id="cash" placeholder="0.00"></div>
            <div class="grid-form">
                <div><label>ATH</label><input type="number" id="ath" placeholder="0.00"></div>
                <div><label>ATHM</label><input type="number" id="athm" placeholder="0.00"></div>
                <div><label>Visa</label><input type="number" id="visa" placeholder="0.00"></div>
                <div><label>MC</label><input type="number" id="mc" placeholder="0.00"></div>
                <div><label>AmEx</label><input type="number" id="amex" placeholder="0.00"></div>
                <div><label>Disc</label><input type="number" id="disc" placeholder="0.00"></div>
                <div><label>WIC</label><input type="number" id="wic" placeholder="0.00"></div>
                <div><label>MCS</label><input type="number" id="mcs" placeholder="0.00"></div>
                <div><label>Triple S</label><input type="number" id="sss" placeholder="0.00" style="border:2px solid var(--p)"></div>
            </div>
        </div>
        <div id="tipsSection" class="hidden" style="margin-top:5px;background:#ecfdf5;padding:10px;border:1px solid #10b981;border-radius:8px;">
            <div style="color:#047857;font-weight:800;font-size:12px">Carthage Tip Tracker</div><input type="number" id="ccTips" placeholder="Total CC Tips" style="margin:0;width:150px">
        </div>
        <div class="section"><span><span class="section-badge">3</span>Deductions</span> <button onclick="app.calcTax()" style="cursor:pointer;font-size:10px;padding:2px 8px;border:1px solid #cbd5e1;border-radius:4px;background:white;color:var(--sidebar);font-weight:700;">Auto 11.5%</button></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px"><div><label>State (10.5%)</label><input type="number" id="taxState"></div><div><label>City (1%)</label><input type="number" id="taxCity"></div></div>
        <div class="section"><span><span class="section-badge">4</span>Payouts</span> <button onclick="app.addPayout()" style="cursor:pointer;font-size:10px;padding:2px 8px;border:1px solid #cbd5e1;border-radius:4px;background:white;color:var(--sidebar);font-weight:700;">+ Add</button></div><div id="payoutList"></div>
        <div class="section"><span><span class="section-badge">5</span>Reconciliation</span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px"><div><label>Opening Float</label><input type="number" id="float" value="150.00"></div><div><label>Actual Cash</label><input type="number" id="actual" onclick="app.openCount()"></div></div>
        <div style="display:flex;gap:12px;margin-top:24px;justify-content:flex-start"><button id="saveBtn" class="btn-main" onclick="app.save()">Finalize & Upload</button><button id="cancelBtn" class="btn-main" onclick="app.resetForm()" style="background:#64748b;display:none;">Cancel</button></div>
    </div>
</div>

<div id="analytics" class="view">
    <div class="panel">
        <div class="control-bar">
            <div class="control-group">
                <span class="control-label">Scope</span>
                <select id="anStoreFilter" onchange="app.renderAnalytics()" style="width:200px;margin:0;font-weight:600">
                    <option value="All">All Locations</option>
                    <option>Carimas #1</option>
                    <option>Carimas #2</option>
                    <option>Carimas #3</option>
                    <option>Carimas #4</option>
                    <option>Carthage</option>
                </select>
            </div>
            <div class="control-group">
                <span class="control-label">Period</span>
                <select id="anFilter" onchange="app.toggleCustomRange()" style="width:160px;margin:0;font-weight:600">
                    <option value="all">All Time</option>
                    <option value="30">Last 30 Days</option>
                    <option value="7">Last 7 Days</option>
                    <option value="90">Last 90 Days</option>
                    <option value="ytd">Year to Date</option>
                    <option value="custom">Custom Range</option>
                </select>
                <div id="customRange" style="display:none; gap:10px; align-items:center;">
                    <input type="date" id="startRange" style="margin:0;padding:8px;border:1px solid #cbd5e1;border-radius:6px">
                    <span style="color:#94a3b8;font-weight:bold">-</span>
                    <input type="date" id="endRange" style="margin:0;padding:8px;border:1px solid #cbd5e1;border-radius:6px">
                    <button onclick="app.renderAnalytics()" class="btn-main" style="padding:8px 16px; width:auto; font-size:12px; margin:0">Update</button>
                </div>
            </div>
        </div>

        <div class="cc-container">
            <div>
                <div class="section-header">Performance Overview</div>
                <div class="kpi-row">
                    <div class="kpi-card kpi-accent-teal">
                        <div class="kpi-label">Gross Revenue</div>
                        <div class="kpi-val" id="kGross">-</div>
                        <div id="tGross" style="font-size:12px;font-weight:700;margin-top:5px"></div>
                    </div>
                    <div class="kpi-card kpi-accent-green">
                        <div class="kpi-label">Net (Gross − Payouts)</div>
                        <div class="kpi-val" id="kNet">-</div>
                        <div id="tNet" style="font-size:12px;font-weight:700;margin-top:5px"></div>
                    </div>
                    <div class="kpi-card kpi-accent-blue">
                        <div class="kpi-label">Projected EOM</div>
                        <div class="kpi-val" id="kProj" style="color:#3b82f6">-</div>
                        <div style="font-size:11px;color:#94a3b8;margin-top:5px;font-weight:600">Based on Daily Avg</div>
                    </div>
                    <div class="kpi-card kpi-accent-amber">
                        <div class="kpi-label">Avg Ticket</div>
                        <div class="kpi-val" id="kAvg" style="color:#f59e0b">-</div>
                        <div style="font-size:11px;color:#94a3b8;margin-top:5px;font-weight:600">Gross / Transactions</div>
                    </div>
                </div>
            </div>

            <div>
                <div class="section-header">Revenue Trend</div>
                <div class="hero-row">
                    <div class="chart-shell">
                        <h4>Sales Trajectory</h4>
                        <div style="flex:1; position:relative; min-height:300px; width:100%;">
                            <canvas id="lineChart"></canvas>
                        </div>
                    </div>
                    <div class="chart-shell">
                        <h4>Outliers (Highs & Lows)</h4>
                        <div class="leaderboard-container" id="leaderboardList"></div>
                    </div>
                </div>
            </div>

            <div>
                <div class="section-header">Operational Signals & Diagnostics</div>
                <div class="signals-row">
                    <div class="chart-shell">
                        <h4>Weekly Rhythm (Avg)</h4>
                        <div style="flex:1; position:relative; min-height:200px;">
                            <canvas id="dowChart"></canvas>
                        </div>
                    </div>
                    <div class="chart-shell">
                        <h4>Register Volume</h4>
                        <div style="flex:1; position:relative; min-height:200px;">
                            <canvas id="regChart"></canvas>
                        </div>
                    </div>
                    <div class="chart-shell">
                        <h4>Expense Breakdown</h4>
                        <div style="flex:1; position:relative; min-height:200px;">
                            <canvas id="payoutChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<div id="logs" class="view">
    <div class="panel">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <h3>Entry Log</h3>
            <div style="display:flex;gap:10px;">
                <select id="histRange" onchange="app.filterHistory()" style="margin:0;width:120px"><option value="9999" selected>All</option><option value="30">Last 30 Days</option><option value="7">Last 7 Days</option><option value="0">Today</option><option value="custom">Custom</option></select>
                <input type="date" id="historyFilter" onchange="document.getElementById('histRange').value='custom';app.filterHistory()" style="margin:0;padding:5px;">
                <select id="histStoreFilter" onchange="app.filterHistory()" style="margin:0;width:120px"><option value="All">All Stores</option><option>Carimas #1</option><option>Carimas #2</option><option>Carimas #3</option><option>Carimas #4</option><option>Carthage</option></select>
                <button onclick="app.fetch()" class="btn-main" style="padding:7px 14px;font-size:12px;width:auto;">↻ Refresh</button>
                <button onclick="app.exportCSV()" class="btn-main" style="padding:7px 14px;font-size:12px;width:auto;background:#047857;">📥 CSV</button>
            </div>
        </div>
        <div id="logTable" style="max-height:600px;overflow-y:auto"></div>
        <div id="histHidden" style="display:none;margin-top:8px;padding:6px 10px;background:#fef9c3;border:1px solid #fde68a;border-radius:6px;font-size:13px;color:#92400e"></div>
    </div>
</div>

<div id="calendar" class="view">
    <div class="panel">
        <div class="cal-nav" style="display:flex;gap:10px;margin-bottom:10px">
            <select id="calStoreFilter" onchange="app.updateCalView()" style="width:150px;margin:0"><option value="All">All Stores</option><option>Carimas #1</option><option>Carimas #2</option><option>Carimas #3</option><option>Carimas #4</option><option>Carthage</option></select>
            <select id="calMonthSelect" onchange="app.updateCalView()" style="width:150px;margin:0"></select><input type="number" id="calYearInput" onchange="app.updateCalView()" style="width:100px;margin:0" placeholder="Year">
        </div>
        <div id="calGrid" style="display:grid;grid-template-columns:repeat(7,1fr);gap:5px;"></div>
    </div>
</div>

<div id="users" class="view">
    <div class="panel">
        <div class="section" style="margin-top:0">Manage Users</div>
        <div class="grid-form">
            <input type="text" id="u_name" placeholder="Username">
            <input type="password" id="u_pass" placeholder="Password" autocomplete="new-password">
            <select id="u_role"><option value="staff">Staff</option><option value="manager">Manager</option><option value="admin">Admin</option><option value="super_admin">Super Admin</option></select>
            <select id="u_store"><option value="All">All (Admin)</option><option>Carimas #1</option><option>Carimas #2</option><option>Carimas #3</option><option>Carimas #4</option><option>Carthage</option></select>
        </div>
        <button id="userSaveBtn" class="btn-main" onclick="app.saveUser()" style="margin-top:10px">Create User</button>
        <br><br><div id="userTable"></div>
    </div>
</div>

<div id="zreviews" class="view">
    <div class="panel">
        <div class="section" style="margin-top:0">Z Report Review Queue
            <span><select id="zrStatusFilter" onchange="app.zr.fetchList()" style="width:auto;margin:0;padding:6px 10px;font-size:12px;border-radius:6px">
                <option value="">All Statuses</option>
                <option value="PENDING_REVIEW">Pending Review</option>
                <option value="IN_REVIEW">In Review</option>
                <option value="FINAL_APPROVED">Approved</option>
                <option value="REJECTED">Rejected</option>
                <option value="AMENDED">Amended</option>
            </select></span>
        </div>
        <div id="zrList"><p style="color:#64748b">Loading...</p></div>
    </div>
</div>
</div><!-- end .main-content -->

<!-- Z Report Review Modal -->
<div id="zrModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:9998;align-items:center;justify-content:center;" onclick="if(event.target===this)this.style.display='none'">
  <div style="background:white;border-radius:16px;padding:30px;width:560px;max-width:95vw;max-height:88vh;overflow-y:auto;position:relative;">
    <button onclick="document.getElementById('zrModal').style.display='none'" style="position:absolute;top:12px;right:16px;background:none;border:none;font-size:22px;cursor:pointer;color:#64748b">✕</button>
    <h3 id="zrModalTitle" style="margin:0 0 16px;color:#1e293b">Review Z Report</h3>
    <div id="zrModalBody"></div>
  </div>
</div>

<div id="modalCount" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);justify-content:center;align-items:center;z-index:9999;">
    <div style="background:white;padding:30px;border-radius:15px;width:350px;border:2px solid var(--p);">
        <h2>Bill Counter</h2><div id="billRows"></div><hr>
        <h3>Total: <span id="billTotal">$0.00</span></h3>
        <button class="btn-main" onclick="app.applyCount()">Apply Total</button>
        <button onclick="document.getElementById('modalCount').style.display='none'" style="margin-top:10px;width:100%;padding:10px;border:none;background:#fee2e2;color:red;border-radius:10px;cursor:pointer">Cancel</button>
    </div>
</div>

<script>
// ── CSRF: fetch token once, then patch window.fetch to inject it automatically ──
let _csrfToken = null;
(async () => {
    try {
        const r = await window._origFetch('/api/csrf-token');
        _csrfToken = (await r.json()).token;
    } catch(e) { console.warn('CSRF token fetch failed', e); }
})();
window._origFetch = window.fetch;
window.fetch = (url, opts = {}) => {
    const method = (opts.method || 'GET').toUpperCase();
    if (['POST','PUT','PATCH','DELETE'].includes(method) && _csrfToken) {
        opts.headers = Object.assign({'X-CSRFToken': _csrfToken}, opts.headers || {});
    }
    return window._origFetch(url, opts);
};
// ── End CSRF patch ──

const app = {
    data: [], users: [], calDate: new Date(), calInitialized: false, role: '', store: '', _galleryPhotos: [], _galleryIdx: 0,
    init: () => {
        app.role = localStorage.getItem('role'); app.store = localStorage.getItem('store');
        document.getElementById('userDisplay').innerText = `User: ${app.role}`;
        document.getElementById('date').value = new Date().toISOString().split('T')[0];
        app.enforcePermissions();
        app.setupBill(); app.setupCalControls(); app.checkPending(); app.checkStore(); app.fetch();
    },
    enforcePermissions: () => {
        const r = app.role;
        if (r === 'staff') {
            ['tab-calendar','tab-analytics','tab-users','tab-zreviews'].forEach(x=>document.getElementById(x).style.display='none');
            const sl = document.getElementById('storeLoc'); sl.value = app.store; sl.disabled = true;
            document.getElementById('histStoreFilter').parentElement.style.display = 'none';
        } else if (r === 'manager') {
            ['tab-analytics','tab-users'].forEach(x=>document.getElementById(x).style.display='none');
            const sl = document.getElementById('storeLoc'); sl.value = app.store; sl.disabled = true;
            document.getElementById('calStoreFilter').parentElement.style.display = 'none';
            document.getElementById('histStoreFilter').parentElement.style.display = 'none';
        }
    },
    checkPending: () => { if({{ 'true' if pending else 'false' }}) document.getElementById('syncBtn').style.display = 'block'; },
    showLoading: () => { document.getElementById('loadingOverlay').style.display = 'flex'; },
    hideLoading: () => { document.getElementById('loadingOverlay').style.display = 'none'; },
    sync: async () => {
        document.getElementById('syncBtn').innerText = "Syncing...";
        const d = await (await fetch('/api/sync', {method:'POST'})).json();
        if(d.status === 'success') { alert(`Synced ${d.count} records!`); if(d.remaining === 0) document.getElementById('syncBtn').style.display = 'none'; app.fetch(); } 
        else { alert('Sync failed. Check internet.'); document.getElementById('syncBtn').innerText = "⚠️ Sync"; }
    },
    checkStore: () => {
        const s = document.getElementById('storeLoc').value;
        if(s === 'Carthage') document.getElementById('tipsSection').classList.remove('hidden'); else { document.getElementById('tipsSection').classList.add('hidden'); document.getElementById('ccTips').value = ''; }
        const logoEl = document.getElementById('sidebarLogo');
        logoEl.style.filter = s === 'Carthage' ? 'none' : 'brightness(0) invert(1)';
        fetch('/api/get_logo', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({store:s})}).then(r=>r.json()).then(d=>{if(d.logo){logoEl.src='data:image/png;base64,'+d.logo;}});
    },
    save: async () => {
        app.showLoading();
        try {
            const getVal = (id) => parseFloat(document.getElementById(id).value || 0);
            const cash = getVal('cash'), cards = getVal('ath')+getVal('athm')+getVal('visa')+getVal('mc')+getVal('amex')+getVal('disc')+getVal('wic')+getVal('mcs')+getVal('sss');
            let payouts = 0, payoutList = [];
            document.querySelectorAll('.payout-row').forEach(row => { const a = parseFloat(row.querySelector('.p-amt').value||0); if(a>0){payouts+=a; payoutList.push({r:row.querySelector('.p-reason').value, a:a});}});
            const payload = {
                date: document.getElementById('date').value, reg: document.getElementById('reg').value, staff: document.getElementById('staff').value, store: document.getElementById('storeLoc').value,
                gross: cash + cards, net: (cash + cards) - payouts, variance: ((getVal('actual') - getVal('float')) - (cash - payouts)).toFixed(2),
                breakdown: { cash: cash, ath: getVal('ath'), sss: getVal('sss'), visa: getVal('visa'), mc: getVal('mc'), amex: getVal('amex'), disc: getVal('disc'), wic: getVal('wic'), mcs: getVal('mcs'), athm: getVal('athm'), payouts: payouts, payoutList: payoutList, taxState: getVal('taxState'), taxCity: getVal('taxCity'), float: getVal('float'), actual: getVal('actual'), ccTips: getVal('ccTips') }
            };
            const editId = document.getElementById('editId').value;
            const res = await fetch(editId ? '/api/update' : '/api/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(editId ? {...payload, id:editId} : payload)});
            const r = await res.json();
            if(res.ok && (r.status === 'success' || r.status === 'offline')) { alert(r.status==='offline'?'Offline Mode: Saved to Queue':'Saved!'); app.resetForm(); app.fetch(); app.tab('logs'); if(r.status==='offline') document.getElementById('syncBtn').style.display='block'; } else alert('Error');
        } catch(e) {
            console.error('Failed to save:', e);
            alert('Failed to save. Please try again.');
        } finally {
            app.hideLoading();
        }
    },
    logout: () => fetch('/api/logout', {method:'POST'}).then(()=>location.reload()),
    tab: (id) => {
        if(app.role==='staff' && (id!=='dash' && id!=='logs')) return;
        if(app.role==='manager' && (id!=='dash' && id!=='logs' && id!=='calendar' && id!=='zreviews')) return;
        document.querySelectorAll('.view,.tab-btn').forEach(e=>e.classList.remove('active'));
        document.getElementById(id).classList.add('active'); document.getElementById('tab-'+id).classList.add('active');
        if(id==='analytics'||id==='calendar'||id==='logs')app.fetch(); if(id==='users')app.fetchUsers();
        if(id==='zreviews')app.zr.fetchList();
        document.querySelector('.sidebar').classList.remove('open');
    },
    toggleMenu: () => { document.querySelector('.sidebar').classList.toggle('open'); },
    setupBill: () => { const d=document.getElementById('billRows'); [100,50,20,10,5,1,0.25,0.1,0.05,0.01].forEach(v=>{d.innerHTML+=`<div style="display:flex;justify-content:space-between;margin-bottom:5px"><span>$${v}</span><input type="number" class="bi" data-v="${v}" style="width:70px;padding:5px"></div>`}); d.addEventListener('input',()=>{let t=0;document.querySelectorAll('.bi').forEach(i=>t+=i.value*i.dataset.v);document.getElementById('billTotal').innerText='$'+t.toFixed(2)}) },
    addPayout: (r='',a='') => { const d=document.createElement('div');d.className='payout-row';d.innerHTML=`<div style="display:flex;gap:5px;margin-bottom:5px"><input class="p-reason" placeholder="Reason" value="${r}" style="flex:2"><input type="number" class="p-amt" placeholder="Amt" value="${a}" style="flex:1"><button onclick="this.parentElement.remove()" style="background:#fee2e2;border:1px solid #ef4444;cursor:pointer">X</button></div>`;document.getElementById('payoutList').appendChild(d)},
    calcTax: () => { const c=parseFloat(document.getElementById('cash').value||0); document.getElementById('taxState').value=(c*0.105).toFixed(2); document.getElementById('taxCity').value=(c*0.01).toFixed(2); },
    openCount: () => document.getElementById('modalCount').style.display='flex',
    applyCount: () => { document.getElementById('actual').value=document.getElementById('billTotal').innerText.replace('$',''); document.getElementById('modalCount').style.display='none'; },
    resetForm: () => { document.getElementById('editId').value=''; document.getElementById('saveBtn').innerText="Finalize & Upload"; document.getElementById('saveBtn').style.background="#0097b2"; document.getElementById('cancelBtn').style.display="none"; document.getElementById('dashPanel').classList.remove('edit-mode'); document.getElementById('modeLabel').innerText="1. Store & Metadata"; document.querySelectorAll('input[type="number"]').forEach(i=>i.value=''); document.getElementById('float').value='150.00'; document.getElementById('payoutList').innerHTML=''; app.checkStore(); },
    editAudit: (idx) => { const d=app.data[idx], b=d.breakdown; document.getElementById('editId').value=d.id; document.getElementById('date').value=d.date; document.getElementById('storeLoc').value=d.store; app.checkStore(); document.getElementById('reg').value=d.reg; document.getElementById('staff').value=d.staff; Object.keys(b).forEach(k=>{if(document.getElementById(k))document.getElementById(k).value=b[k]}); document.getElementById('payoutList').innerHTML=''; (b.payoutList||[]).forEach(p=>app.addPayout(p.r,p.a)); document.getElementById('saveBtn').innerText="Update Record"; document.getElementById('saveBtn').style.background="#f59e0b"; document.getElementById('cancelBtn').style.display="inline-block"; document.getElementById('dashPanel').classList.add('edit-mode'); document.getElementById('modeLabel').innerText="EDITING RECORD #"+d.id; app.tab('dash'); window.scrollTo({ top: 0, behavior: 'smooth' }); document.getElementById('dashPanel').style.boxShadow = '0 0 20px rgba(245, 158, 11, 0.5)'; setTimeout(() => { document.getElementById('dashPanel').style.boxShadow = ''; }, 2000); },
    deleteAudit: async (id) => { if(confirm("Permanently Delete?")) { await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})}); app.fetch(); } },
    fetch: async () => {
        app.showLoading();
        let ok = false;
        try {
            const raw = await (await fetch('/api/list')).json();
            if (!Array.isArray(raw)) {
                console.error('[fetch] /api/list returned non-array:', raw);
                alert('Failed to load data: ' + (raw.error || 'Unknown error'));
            } else {
                app.data = raw;
                ok = true;
            }
        } catch(e) {
            console.error('Failed to fetch:', e);
            alert('Connection error. Please check your internet and try again.');
        } finally {
            app.hideLoading();
        }
        if (!ok) return;
        if (!app.calInitialized && app.data.length > 0) {
            const latest = app.data.reduce((a,b) => a.date > b.date ? a : b);
            const parts = latest.date.split('-').map(Number);
            app.calDate = new Date(parts[0], parts[1]-1, 1);
            app.calInitialized = true;
            const ms = document.getElementById('calMonthSelect');
            const yi = document.getElementById('calYearInput');
            if (ms) ms.value = app.calDate.getMonth();
            if (yi) yi.value = app.calDate.getFullYear();
        }
        app.renderLogs();
        try { app.renderCalendar(); } catch(e) { console.error('renderCalendar error:', e); }
        try { app.renderAnalytics(); } catch(e) { console.error('renderAnalytics error:', e); }
    },
    renderLogs: () => { app.filterHistory(); },
    filterHistory: () => { const r=document.getElementById('histRange').value, d=document.getElementById('historyFilter').value, s=(app.role!=='staff')?document.getElementById('histStoreFilter').value:app.store; let f=app.data; if(s&&s!=='All')f=f.filter(x=>x.store===s); const afterStore=f.length; if(r==='custom'){if(d)f=f.filter(x=>x.date===d)}else{const days=parseInt(r), cut=new Date(); cut.setDate(cut.getDate()-days); if(days===0)f=f.filter(x=>x.date===new Date().toISOString().split('T')[0]); else if(days!==9999)f=f.filter(x=>new Date(x.date)>=cut);} const hidden=afterStore-f.length; const hd=document.getElementById('histHidden'); if(hd){if(hidden>0){hd.textContent=`⚠️ ${hidden} entr${hidden===1?'y':'ies'} hidden by date filter — select "All" to see them.`;hd.style.display='block';}else{hd.style.display='none';}} app._filteredRows=f; app.renderTable(f); },
    exportCSV: () => { const rows=app._filteredRows||app.data; if(!rows.length){alert('No data to export.');return;} const hdr='Date,Store,Register,Staff,Gross,Net,Variance'; const lines=rows.map(d=>[d.date,d.store,d.reg||'',d.staff||'',(d.gross||0).toFixed(2),(d.net||0).toFixed(2),(d.variance||0)].map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')); const csv=[hdr,...lines].join('\\r\\n'); const blob=new Blob([csv],{type:'text/csv'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=`carimas_history_${new Date().toISOString().split('T')[0]}.csv`; a.click(); URL.revokeObjectURL(a.href); },
    renderTable: (rows) => { let h='<table><tr><th>Date</th><th>Store</th><th>Gross</th><th>Var</th><th>Actions</th></tr>'; rows.forEach(d=>{ const i=app.data.indexOf(d), camBtn=d.photo_count>0?`<button onclick="app.viewZReport(${d.id})" class="action-btn btn-cam" title="Ver ${d.photo_count} foto(s)">📷(${d.photo_count})</button>`:'', acts=(app.role==='staff')?`<button onclick="app.print(${i})" class="action-btn btn-print">🖨 Print</button>`:`<button onclick="app.print(${i})" class="action-btn btn-print">🖨</button><button onclick="app.editAudit(${i})" class="action-btn btn-edit">✏️</button><button onclick="app.deleteAudit(${d.id})" class="action-btn btn-del">🗑</button>${camBtn}`; h+=`<tr><td>${d.date}</td><td>${d.store}</td><td>$${(d.gross||0).toFixed(2)}</td><td style="color:${d.variance<0?'#be123c':'#047857'};font-weight:800">$${d.variance}</td><td>${acts}</td></tr>`;}); document.getElementById('logTable').innerHTML=h+'</table>'; },
    viewZReport: async (auditId) => {
        try {
            const photosResp = await fetch(`/api/zreport/photos?entry_id=${auditId}`);
            if (!photosResp.ok) {
                const errJson = await photosResp.json().catch(()=>({}));
                console.error('[viewZReport] photos fetch failed:', photosResp.status, errJson);
                alert(photosResp.status === 403 ? 'No autorizado.' : `No hay imagen para esta entrada. [${errJson.code||photosResp.status}]`);
                return;
            }
            const photos = await photosResp.json();
            if (!photos.length) { alert('No hay imagen para esta entrada.'); return; }
            app._galleryPhotos = photos;
            app._galleryIdx = 0;
            await app._showGalleryPhoto(0);
            document.getElementById('zreportModal').style.display = 'flex';
        } catch(e) { console.error('[viewZReport] unexpected error:', e); alert('Error cargando imagen: ' + e.toString()); }
    },
    _showGalleryPhoto: async (idx) => {
        const photos = app._galleryPhotos;
        const photo = photos[idx];
        const urlResp = await fetch(`/api/zreport/signed_url?photo_id=${photo.id}`);
        if (!urlResp.ok) {
            const errJson = await urlResp.json().catch(()=>({}));
            console.error('[gallery] signed_url failed:', urlResp.status, errJson);
            alert(urlResp.status === 403 ? 'No autorizado.' : `Error cargando imagen [${errJson.code||urlResp.status}]: ${errJson.error||'Unknown error'}`);
            return;
        }
        const { url } = await urlResp.json();
        document.getElementById('zreportImg').src = url;
        const meta = document.getElementById('zreportMeta');
        if (meta) {
            meta.querySelector('[data-store]').textContent = photo.store;
            meta.querySelector('[data-register]').textContent = photo.register_id;
            meta.querySelector('[data-date]').textContent = photo.business_date;
            meta.querySelector('[data-by]').textContent = photo.uploaded_by;
            meta.querySelector('[data-at]').textContent = new Date(photo.uploaded_at).toLocaleString('es-PR');
        }
        const counter = document.getElementById('zreportCounter');
        if (counter) counter.textContent = photos.length > 1 ? `${idx+1} / ${photos.length}` : '';
        const prev = document.getElementById('zreportPrev');
        const next = document.getElementById('zreportNext');
        if (prev) prev.style.display = idx > 0 ? 'block' : 'none';
        if (next) next.style.display = idx < photos.length - 1 ? 'block' : 'none';
        const delBtn = document.getElementById('zreportDeleteBtn');
        if (delBtn) delBtn.style.display = ['manager','admin','super_admin'].includes(app.role) ? 'inline-block' : 'none';
    },
    galleryNav: async (dir) => {
        const idx = app._galleryIdx + dir;
        if (idx < 0 || idx >= app._galleryPhotos.length) return;
        app._galleryIdx = idx;
        await app._showGalleryPhoto(idx);
    },
    deleteCurrentPhoto: async () => {
        const photo = app._galleryPhotos[app._galleryIdx];
        if (!photo || !confirm('Permanently delete this photo?')) return;
        const resp = await fetch(`/api/zreport/photo/${photo.id}`, { method: 'DELETE' });
        if (!resp.ok) {
            const err = await resp.json().catch(()=>({}));
            alert('Delete failed: ' + (err.error || resp.status));
            return;
        }
        app._galleryPhotos.splice(app._galleryIdx, 1);
        if (!app._galleryPhotos.length) {
            document.getElementById('zreportModal').style.display = 'none';
            app.fetch();
            return;
        }
        app._galleryIdx = Math.min(app._galleryIdx, app._galleryPhotos.length - 1);
        await app._showGalleryPhoto(app._galleryIdx);
        app.fetch();
    },
    print: async (idx) => {
        const d=app.data[idx], b=d.breakdown||{}, val=v=>(v||0).toFixed(2);
        const logo='data:image/png;base64,'+(await(await fetch('/api/get_logo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({store:d.store})})).json()).logo;
        const cards=(d.gross||0)-(b.cash||0), net=(d.gross||0)-(b.payouts||0), expected=(b.float||0)+(b.cash||0)-(b.payouts||0), absVar=Math.abs(d.variance||0);
        const vc=absVar<0.01?'balanced':absVar<50?'review':'discrepancy';
        const vl={'balanced':'✓  Balanced','review':'⚠  Review Required','discrepancy':'✗  Discrepancy'}[vc];
        const vn={'balanced':'Cash matches expected amount.','review':'Minor variance — verify before approving.','discrepancy':'Significant variance — explanation required.'}[vc];
        const brand=d.store==='Carthage'?'Carthage Express':'Farmacia Carimas';
        const html=`<!DOCTYPE html><html><head><meta charset="UTF-8"><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background:#fff;color:#1e293b;font-size:13px;padding:36px 44px;max-width:680px;margin:0 auto;line-height:1.5}.hdr{text-align:center;padding-bottom:22px;border-bottom:2px solid #e2e8f0;margin-bottom:22px}.hdr img{max-height:64px;margin-bottom:12px;display:block;margin-left:auto;margin-right:auto}.brand{font-size:22px;font-weight:700;color:#0097b2;letter-spacing:-0.5px}.sub{font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:2px;color:#94a3b8;margin-top:4px}.meta{display:flex;justify-content:space-between;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 20px;margin-bottom:22px}.mi{text-align:center}.ml{font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:3px}.mv{font-size:14px;font-weight:600;color:#1e293b}.krow{display:flex;gap:10px;margin-bottom:4px}.kpi{flex:1;border:1px solid #e2e8f0;border-radius:10px;padding:14px 10px;text-align:center}.kl{font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8;margin-bottom:6px}.kv{font-size:18px;font-weight:700;color:#0097b2;font-variant-numeric:tabular-nums}.st{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:1.2px;color:#0097b2;border-bottom:1px solid #e2e8f0;padding-bottom:7px;margin-bottom:10px;margin-top:22px}.row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:13px}.row:last-child{border-bottom:none}.lbl{color:#475569}.amt{font-weight:600;font-variant-numeric:tabular-nums;color:#1e293b}.dim{color:#e2e8f0}.pg{display:grid;grid-template-columns:1fr 1fr;gap:0 32px}.fml{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px 20px;margin-top:10px}.fr{display:flex;justify-content:space-between;padding:5px 0;font-size:13px;font-variant-numeric:tabular-nums;color:#64748b}.fr strong{color:#1e293b;font-weight:600}.frt{border-top:1px solid #cbd5e1;margin-top:8px;padding-top:10px;font-weight:700;font-size:14px;color:#1e293b;display:flex;justify-content:space-between}.fra{display:flex;justify-content:space-between;margin-top:10px;padding-top:12px;border-top:2px solid #1e293b;font-weight:700;font-size:15px;color:#1e293b}.vb{border-radius:12px;padding:20px 26px;display:flex;justify-content:space-between;align-items:center;margin:22px 0}.balanced{background:#f0fdf4;border:1.5px solid #16a34a}.review{background:#fefce8;border:1.5px solid #ca8a04}.discrepancy{background:#fef2f2;border:1.5px solid #dc2626}.vl{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px}.balanced .vl{color:#15803d}.review .vl{color:#92400e}.discrepancy .vl{color:#991b1b}.vn{font-size:11px;margin-top:5px;opacity:0.75}.balanced .vn{color:#15803d}.review .vn{color:#92400e}.discrepancy .vn{color:#991b1b}.va{font-size:36px;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-1.5px}.balanced .va{color:#15803d}.review .va{color:#92400e}.discrepancy .va{color:#991b1b}.sigs{display:flex;gap:28px;margin-top:28px;padding-top:20px;border-top:1px solid #e2e8f0}.sig{flex:1}.sl{border-bottom:1px solid #1e293b;height:38px;margin-bottom:8px}.sg{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:#94a3b8}.foot{text-align:center;margin-top:22px;padding-top:14px;border-top:1px solid #f1f5f9;font-size:10px;color:#cbd5e1;letter-spacing:0.5px}@page{size:letter portrait;margin:0.35in}@media print{body{padding:6px 10px;max-width:100%;font-size:12px;line-height:1.3}.hdr{padding-bottom:10px;margin-bottom:12px}.hdr img{max-height:44px;margin-bottom:7px}.brand{font-size:18px}.meta{padding:8px 14px;margin-bottom:12px;border-radius:7px}.mv{font-size:12px}.krow{margin-bottom:2px}.kpi{padding:8px 6px;border-radius:7px}.kv{font-size:14px}.st{margin-top:12px;margin-bottom:7px;padding-bottom:5px}.row{padding:3px 0;font-size:12px}.pg{gap:0 20px}.fml{padding:10px 14px;margin-top:6px;border-radius:7px}.fr{padding:2px 0;font-size:12px}.frt{margin-top:4px;padding-top:7px;font-size:12px}.fra{margin-top:6px;padding-top:8px;font-size:13px}.vb{padding:12px 18px;margin:12px 0;border-radius:8px;-webkit-print-color-adjust:exact;print-color-adjust:exact}.va{font-size:26px}.sigs{margin-top:16px;padding-top:12px;gap:20px}.sl{height:24px;margin-bottom:6px}.foot{margin-top:12px;padding-top:10px}}</style></head><body><div class="hdr"><img src="${logo}"><div class="brand">${brand}</div><div class="sub">Daily Audit Report</div></div><div class="meta"><div class="mi"><div class="ml">Store</div><div class="mv">${d.store}</div></div><div class="mi"><div class="ml">Date</div><div class="mv">${d.date}</div></div><div class="mi"><div class="ml">Staff</div><div class="mv">${d.staff||'—'}</div></div><div class="mi"><div class="ml">Register</div><div class="mv">${d.reg||'—'}</div></div></div><div class="krow"><div class="kpi"><div class="kl">Gross Revenue</div><div class="kv">$${val(d.gross)}</div></div><div class="kpi"><div class="kl">Cash Sales</div><div class="kv">$${val(b.cash)}</div></div><div class="kpi"><div class="kl">Card Sales</div><div class="kv">$${val(cards)}</div></div><div class="kpi"><div class="kl">Net Revenue</div><div class="kv">$${val(net)}</div></div></div><div class="st">Payment Channels</div><div class="pg"><div class="row"><span class="lbl">ATH</span><span class="${b.ath?'amt':'dim'}">$${val(b.ath)}</span></div><div class="row"><span class="lbl">WIC</span><span class="${b.wic?'amt':'dim'}">$${val(b.wic)}</span></div><div class="row"><span class="lbl">ATH Móvil</span><span class="${b.athm?'amt':'dim'}">$${val(b.athm)}</span></div><div class="row"><span class="lbl">MCS</span><span class="${b.mcs?'amt':'dim'}">$${val(b.mcs)}</span></div><div class="row"><span class="lbl">Visa</span><span class="${b.visa?'amt':'dim'}">$${val(b.visa)}</span></div><div class="row"><span class="lbl">Triple S</span><span class="${b.sss?'amt':'dim'}">$${val(b.sss)}</span></div><div class="row"><span class="lbl">Mastercard</span><span class="${b.mc?'amt':'dim'}">$${val(b.mc)}</span></div><div class="row"><span class="lbl">AmEx</span><span class="${b.amex?'amt':'dim'}">$${val(b.amex)}</span></div><div class="row"><span class="lbl">Discover</span><span class="${b.disc?'amt':'dim'}">$${val(b.disc)}</span></div><div class="row" style="border-top:1px solid #e2e8f0;margin-top:4px"><span class="lbl" style="color:#0097b2;font-weight:600">Total Cards</span><span style="font-weight:700;color:#0097b2;font-variant-numeric:tabular-nums">$${val(cards)}</span></div></div><div class="st">Deductions</div><div class="row"><span class="lbl">State Tax (10.5%)</span><span class="${b.taxState?'amt':'dim'}">$${val(b.taxState)}</span></div><div class="row"><span class="lbl">City Tax (1.0%)</span><span class="${b.taxCity?'amt':'dim'}">$${val(b.taxCity)}</span></div>${(b.payoutList||[]).length?`<div style="margin-top:12px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;padding-bottom:4px">Payouts</div>`+(b.payoutList||[]).map(p=>`<div class="row"><span class="lbl">${p.r||'Payout'}</span><span class="amt">$${val(p.a)}</span></div>`).join('')+`<div class="row" style="font-weight:600;border-top:1px solid #e2e8f0;margin-top:4px"><span>Total Payouts</span><span class="amt">$${val(b.payouts)}</span></div>`:`<div class="row"><span class="lbl">Total Payouts</span><span class="${b.payouts?'amt':'dim'}">$${val(b.payouts)}</span></div>`}<div class="st">Cash Reconciliation</div><div class="fml"><div class="fr"><span>Opening Float</span><strong>$${val(b.float)}</strong></div><div class="fr"><span>+ Cash Sales</span><strong>$${val(b.cash)}</strong></div><div class="fr"><span>− Total Payouts</span><strong>($${val(b.payouts)})</strong></div><div class="frt"><span>= Expected in Drawer</span><span>$${val(expected)}</span></div><div class="fra"><span>Actual Cash Counted</span><span>$${val(b.actual)}</span></div></div><div class="vb ${vc}"><div><div class="vl">${vl}</div><div class="vn">${vn}</div></div><div class="va">$${val(d.variance)}</div></div><div class="sigs"><div class="sig"><div class="sl"></div><div class="sg">Manager Signature</div></div><div class="sig"><div class="sl"></div><div class="sg">Date</div></div><div class="sig"><div class="sl"></div><div class="sg">Reviewed By</div></div></div><div class="foot">${brand} · ${d.store} · ${d.date} · Printed ${new Date().toLocaleDateString()}</div></body></html>`;
        const frame=document.createElement('iframe');
        frame.style.cssText='position:fixed;top:-9999px;left:-9999px;width:210mm;height:297mm;border:none';
        frame.srcdoc=html;
        document.body.appendChild(frame);
        frame.onload=()=>{setTimeout(()=>{frame.contentWindow.print();setTimeout(()=>{if(frame.parentNode)frame.parentNode.removeChild(frame);},3000);},400);};
    },
    setupCalControls: () => { const m=document.getElementById('calMonthSelect'); ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].forEach((x,i)=>m.innerHTML+=`<option value="${i}">${x}</option>`); app.updateCalView(); },
    updateCalView: () => { if(event&&event.target.id==='calMonthSelect')app.calDate.setMonth(parseInt(event.target.value)); if(event&&event.target.id==='calYearInput')app.calDate.setFullYear(parseInt(event.target.value)); document.getElementById('calMonthSelect').value=app.calDate.getMonth(); document.getElementById('calYearInput').value=app.calDate.getFullYear(); app.renderCalendar(); },
    renderCalendar: () => { const c=document.getElementById('calGrid'), dt=app.calDate, s=(app.role==='admin'||app.role==='super_admin')?document.getElementById('calStoreFilter').value:app.store, dim=new Date(dt.getFullYear(),dt.getMonth()+1,0).getDate(); c.innerHTML=''; for(let i=1;i<=dim;i++){ const ds=`${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(i).padStart(2,'0')}`, es=app.data.filter(x=>x.date===ds&&(s==='All'||x.store===s)); let g=0,v=0; es.forEach(x=>{g+=x.gross||0;v+=parseFloat(x.variance||0)}); c.innerHTML+=`<div style="background:${es.length>0?(v<0?'#fee2e2':'#dcfce7'):'rgba(255,255,255,0.7)'};border:1px solid #ddd;padding:5px;height:80px;cursor:pointer;border-radius:8px" onclick="app.tab('logs');document.getElementById('historyFilter').value='${ds}';document.getElementById('histRange').value='custom';app.filterHistory()"><div style="font-weight:bold">${i}</div>${es.length>0?`<div style="font-size:10px;margin-top:5px">$${g.toFixed(0)}<br>${v.toFixed(2)}</div>`:''}</div>`; } },
    
    toggleCustomRange: () => {
        const v = document.getElementById('anFilter').value;
        const cr = document.getElementById('customRange');
        cr.style.display = (v === 'custom') ? 'flex' : 'none';
        if (v !== 'custom') app.renderAnalytics();
    },

    renderAnalytics: () => { 
        if(!app.data.length) return; 
        const m = document.getElementById('anFilter').value;
        const s = (app.role !== 'staff') ? document.getElementById('anStoreFilter').value : app.store; 
        
        let rangeStart = new Date(); 
        let rangeEnd = new Date(); 
        rangeEnd.setHours(23,59,59,999); 

        if (m === 'custom') {
            const sVal = document.getElementById('startRange').value;
            const eVal = document.getElementById('endRange').value;
            if (!sVal || !eVal) return; 
            rangeStart = new Date(sVal);
            rangeEnd = new Date(eVal);
            rangeEnd.setHours(23,59,59,999);
        } else if (m === 'ytd') {
            rangeStart = new Date(new Date().getFullYear(), 0, 1);
        } else if (m !== 'all') {
            const days = parseInt(m) || 30;
            // Fix: "Last N Days" includes today. Reset to midnight.
            rangeStart.setDate(rangeStart.getDate() - (days - 1));
            rangeStart.setHours(0, 0, 0, 0);
        }

        let f = app.data;
        if (s !== 'All') f = f.filter(x => x.store === s);
        if (m !== 'all') f = f.filter(x => { const d = new Date(x.date); return d >= rangeStart && d <= rangeEnd; });

        let pStart, pEnd, pLabel;
        if (m === 'ytd') {
            pStart = new Date(rangeStart.getFullYear() - 1, 0, 1);
            pEnd = new Date(new Date().getFullYear() - 1, new Date().getMonth(), new Date().getDate()); 
            pEnd.setHours(23,59,59,999); // Fix 1: Force end of day
            pLabel = "vs last YTD";
        } else {
            const dayMs = 86400000;
            // Fix 2: Inclusive day count using floor + 1 ensures stability across time boundaries
            const days = Math.max(1, Math.floor((rangeEnd - rangeStart) / dayMs) + 1);
            
            pEnd = new Date(rangeStart);
            pEnd.setDate(pEnd.getDate() - 1);
            pEnd.setHours(23, 59, 59, 999);
            
            pStart = new Date(pEnd);
            pStart.setDate(pStart.getDate() - (days - 1));
            pStart.setHours(0, 0, 0, 0);
            
            pLabel = "vs prev";
        }

        let pData = app.data.filter(x => {
            const d = new Date(x.date);
            return d >= pStart && d <= pEnd && (s === 'All' || x.store === s);
        });

        let gross=0, net=0, count=0; f.forEach(x=>{gross+=x.gross||0; net+=x.net||0; count++;});
        let pGross=0, pNet=0; pData.forEach(x=>{pGross+=x.gross||0; pNet+=x.net||0});
        
        const calcGrowth = (curr, prev) => { if(prev===0) return '0%'; const p = ((curr-prev)/prev)*100; return (p>0?'+':'') + p.toFixed(1) + '%'; };
        const colorGrowth = (curr, prev) => (curr>=prev ? '#047857' : '#be123c');

        document.getElementById('kGross').innerText = '$'+gross.toLocaleString(undefined,{minimumFractionDigits:2}); 
        document.getElementById('tGross').innerText = (m!=='custom' && m!=='ytd' && !parseInt(m)) ? "" : calcGrowth(gross, pGross) + " " + pLabel;
        document.getElementById('tGross').style.color = colorGrowth(gross, pGross);

        document.getElementById('kNet').innerText = '$'+net.toLocaleString(undefined,{minimumFractionDigits:2});
        document.getElementById('tNet').innerText = (m!=='custom' && m!=='ytd' && !parseInt(m)) ? "" : calcGrowth(net, pNet) + " " + pLabel;
        document.getElementById('tNet').style.color = colorGrowth(net, pNet);

        const distinctDays = new Set(f.map(x=>x.date)).size; const avgDaily = distinctDays > 0 ? gross / distinctDays : 0;
        const daysInMonth = new Date(new Date().getFullYear(), new Date().getMonth()+1, 0).getDate();
        document.getElementById('kProj').innerText = '$'+(avgDaily * daysInMonth).toLocaleString(undefined,{minimumFractionDigits:0});
        document.getElementById('kAvg').innerText = '$'+(count>0?(gross/count):0).toLocaleString(undefined,{minimumFractionDigits:0});

        const srt=[...f].sort((a,b)=>b.gross-a.gross), b7=srt.slice(0,5), w7=srt.slice(-5).reverse(); 
        const renderRow = (x, tag, cls) => `<div class="lb-item"><span class="lb-date">${x.date}</span><div style="display:flex;align-items:center;gap:10px"><span class="lb-val">$${(x.gross||0).toFixed(0)}</span><span class="lb-tag ${cls}">${tag}</span></div></div>`;
        document.getElementById('leaderboardList').innerHTML = b7.map(x=>renderRow(x,'TOP','tag-green')).join('') + w7.map(x=>renderRow(x,'LOW','tag-red')).join('') || '<div style="padding:10px;text-align:center;color:#94a3b8">No Data</div>';
        
        Chart.register(ChartDataLabels);
        const commonOpt = { 
            plugins: { datalabels: { color:'black', align:'top', anchor:'end', formatter: (v)=>Math.round(v), font:{weight:'900', size:11} }, legend:{display:s==='All', position:'bottom', labels:{boxWidth:10, font:{size:10}, padding:20}} }, 
            layout: { padding: { top: 30, left:10, right:10, bottom:10 } }, maintainAspectRatio: false, 
            scales:{x:{grid:{display:false}, ticks:{font:{weight:'bold'}}}, y:{grid:{display:false}, beginAtZero:true, ticks:{font:{weight:'bold'}}}} 
        };
        
        const cl=document.getElementById('lineChart').getContext('2d'); if(window.lineC)window.lineC.destroy(); 
        const labels = [...new Set(f.map(x=>x.date))].sort();
        let datasets = [];
        const grad = cl.createLinearGradient(0,0,0,400); grad.addColorStop(0, 'rgba(0, 151, 178, 0.5)'); grad.addColorStop(1, 'rgba(0, 151, 178, 0.0)');

        if(s === 'All') {
            const stores = [...new Set(f.map(x=>x.store))];
            const colors = ['#0097b2', '#be123c', '#b45309', '#6366f1', '#0ea5e9'];
            datasets = stores.map((st, i) => ({ label: st, data: labels.map(l => f.filter(x=>x.date===l && x.store===st).reduce((s,x)=>s+(x.gross||0),0)), borderColor: colors[i%colors.length], tension: 0.4, pointRadius: 0, borderWidth:3 }));
        } else { datasets = [{label:'Revenue', data:labels.map(l => f.filter(x=>x.date===l).reduce((s,x)=>s+(x.gross||0),0)), borderColor:'#0097b2', tension:0.4, pointRadius:3, fill:true, backgroundColor:grad, borderWidth:3}]; }
        window.lineC=new Chart(cl,{type:'line', data:{labels:labels, datasets:datasets}, options: commonOpt }); 

        const dowMap = [0,0,0,0,0,0,0], dowCount=[0,0,0,0,0,0,0], days=['S','M','T','W','T','F','S'];
        f.forEach(x=>{ const d=new Date(x.date+'T12:00:00').getDay(); dowMap[d]+=x.gross||0; dowCount[d]++; });
        const cd=document.getElementById('dowChart').getContext('2d'); if(window.dowC)window.dowC.destroy();
        window.dowC=new Chart(cd, {type:'bar', data:{labels:days, datasets:[{data:dowMap.map((v,i) => dowCount[i]?v/dowCount[i]:0), backgroundColor:'#0097b2', borderRadius:4, maxBarThickness: 40}]}, options:{...commonOpt, plugins:{legend:{display:false}, datalabels:{display:false}}}});

        const regMap={}; f.forEach(x=>{ const rk=x.reg||'Unknown'; regMap[rk]=(regMap[rk]||0)+(x.gross||0); });
        const cr=document.getElementById('regChart').getContext('2d'); if(window.regC)window.regC.destroy();
        window.regC=new Chart(cr, {type:'bar', data:{labels:Object.keys(regMap), datasets:[{data:Object.values(regMap), backgroundColor:'#6366f1', borderRadius:4, maxBarThickness: 40}]}, options:{...commonOpt, plugins:{legend:{display:false}, datalabels:{display:false}}}});

        const payMap={}; f.forEach(x=>{ ((x.breakdown||{}).payoutList||[]).forEach(p=>{ payMap[p.r]=(payMap[p.r]||0)+p.a; }); });
        const sortPay = Object.entries(payMap).sort((a,b)=>b[1]-a[1]).slice(0,5);
        const cp2=document.getElementById('payoutChart').getContext('2d'); if(window.payC)window.payC.destroy();
        window.payC=new Chart(cp2, {type:'bar', indexAxis:'y', data:{labels:sortPay.map(x=>x[0]), datasets:[{data:sortPay.map(x=>x[1]), backgroundColor:'#be123c', borderRadius:4, maxBarThickness: 40}]}, options:{...commonOpt, plugins:{legend:{display:false}, datalabels:{display:false}}}});
    },
    
    fetchUsers: async () => { 
        app.showLoading();
        try {
            const u = await (await fetch('/api/users/list')).json(); 
            app.users=u; 
            document.getElementById('userTable').innerHTML='<table><tr><th>User</th><th>Role</th><th>Store</th><th>Pass</th><th>Actions</th></tr>'+u.map(x=>`<tr><td>${x.username}</td><td>${x.role}</td><td>${x.store}</td><td>${app.pwCell(x.username)}</td><td><button onclick="app.editUser('${x.username}')" class="action-btn btn-edit">✏️</button><button onclick="app.deleteUser('${x.username}')" class="action-btn btn-del">🗑</button></td></tr>`).join('')+'</table>'; 
        } catch(e) {
            console.error('Failed to fetch users:', e);
            alert('Failed to load users. Please refresh the page.');
        } finally {
            app.hideLoading();
        }
    },
    pwCell: (un) => {
        if (app.role !== 'super_admin') return '•••••';
        const pw = (app.users.find(u=>u.username===un)||{}).password||'';
        return '<span class="pass-reveal" data-pw="' + pw.replace(/&/g,'&amp;').replace(/"/g,'&quot;') + '" onclick="app.togglePass(this)" title="Click to reveal" style="cursor:pointer;letter-spacing:2px;color:#94a3b8">•••••</span>';
    },
    togglePass: (el) => {
        if (el.classList.contains('revealed')) {
            el.textContent='•••••'; el.classList.remove('revealed'); el.style.letterSpacing='2px'; el.style.color='#94a3b8';
        } else {
            el.textContent=el.dataset.pw; el.classList.add('revealed'); el.style.letterSpacing='0'; el.style.color='#ef4444';
        }
    },
    editUser: (n) => { const u=app.users.find(x=>x.username===n); if(!u)return; document.getElementById('u_name').value=u.username; document.getElementById('u_pass').value=u.password; document.getElementById('u_role').value=u.role; document.getElementById('u_store').value=u.store; const b=document.getElementById('userSaveBtn'); b.innerText="Update User"; b.style.background="#f59e0b"; window.scrollTo({top:0,behavior:'smooth'}); },
    saveUser: async () => { 
        app.showLoading();
        try {
            const u={username:document.getElementById('u_name').value,password:document.getElementById('u_pass').value,role:document.getElementById('u_role').value,store:document.getElementById('u_store').value}; 
            if(!u.username||!u.password)return alert('Fill all'); 
            if((await fetch('/api/users/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(u)})).ok){
                alert('Saved');
                app.fetchUsers();
                document.getElementById('userSaveBtn').innerText="Create User";
                document.getElementById('userSaveBtn').style.background="#0097b2";
            }else alert('Error'); 
        } catch(e) {
            console.error('Failed to save user:', e);
            alert('Failed to save user. Please try again.');
        } finally {
            app.hideLoading();
        }
    },
    deleteUser: async (n) => { if(confirm('Delete?')) { await fetch('/api/users/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:n})}); app.fetchUsers(); } }
};

// HTML escape helper - use on all server-provided strings before inserting into innerHTML
function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

app.zr = {
    _badge: (s) => {
        const colors = {PENDING_REVIEW:'#f59e0b',IN_REVIEW:'#3b82f6',FINAL_APPROVED:'#047857',REJECTED:'#ef4444',AMENDED:'#8b5cf6',NEEDS_ASSIGNMENT:'#64748b',DUPLICATE:'#64748b'};
        const labels = {PENDING_REVIEW:'Pending Review',IN_REVIEW:'In Review',FINAL_APPROVED:'Approved',REJECTED:'Rejected',AMENDED:'Amended',NEEDS_ASSIGNMENT:'Unassigned',DUPLICATE:'Duplicate'};
        return '<span style="background:' + (colors[s]||'#64748b') + ';color:white;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:800">' + esc(labels[s]||s.replace(/_/g,' ')) + '</span>';
    },
    fetchList: async () => {
        const status = document.getElementById('zrStatusFilter').value;
        try {
            const rows = await (await fetch('/api/z-reports' + (status ? '?status=' + encodeURIComponent(status) : ''))).json();
            if (!Array.isArray(rows)) { document.getElementById('zrList').textContent = 'Error loading list.'; return; }
            if (!rows.length) { document.getElementById('zrList').textContent = 'No records found.'; return; }
            const tbody = rows.map(r => {
                const canReview = ['PENDING_REVIEW','IN_REVIEW','NEEDS_ASSIGNMENT'].includes(r.review_status);
                return '<tr style="border-bottom:1px solid #f1f5f9;font-size:13px">'
                    + '<td style="padding:10px 8px;font-weight:700">' + esc(r.date) + '</td>'
                    + '<td style="padding:10px 8px">' + esc(r.store||'—') + '</td>'
                    + '<td style="padding:10px 8px">' + app.zr._badge(r.review_status) + '</td>'
                    + '<td style="padding:10px 8px;color:#64748b;font-size:11px">' + esc(r.review_locked_by||'—') + '</td>'
                    + '<td style="padding:10px 8px"><button onclick="app.zr.openModal(' + r.id + ')" class="action-btn btn-edit" style="font-size:11px">'
                    + (canReview ? '🔍 Review' : '👁 View') + '</button></td></tr>';
            }).join('');
            document.getElementById('zrList').innerHTML = '<table style="width:100%;border-collapse:collapse"><tr style="text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e2e8f0"><th style="padding:8px">Date</th><th>Store</th><th>Status</th><th>Locked By</th><th>Action</th></tr>' + tbody + '</table>';
        } catch(e) { document.getElementById('zrList').textContent = 'Failed to load.'; }
    },
    openModal: async (id) => {
        document.getElementById('zrModalTitle').textContent = 'Loading...';
        document.getElementById('zrModalBody').textContent = 'Loading...';
        document.getElementById('zrModal').style.display = 'flex';
        try {
            const d = await (await fetch('/api/z-reports/' + id)).json();
            if (d.error) { document.getElementById('zrModalBody').textContent = d.error; return; }
            app.zr._renderModal(d);
        } catch(e) { document.getElementById('zrModalBody').textContent = 'Failed to load detail.'; }
    },
    _renderModal: (d) => {
        const a = d.audit, rv = d.review;
        const bd = ((a.payload||{}).breakdown)||{};
        const gross = a.gross||0, net = a.net||0, variance = a.variance||0;
        const status = a.review_status;
        const me = localStorage.getItem('user')||'';
        const isAdmin = (app.role==='admin'||app.role==='super_admin');
        const canAct = status === 'IN_REVIEW' && a.review_locked_by === me;
        const canLock = ['PENDING_REVIEW','NEEDS_ASSIGNMENT'].includes(status) || (status==='IN_REVIEW' && a.review_locked_by !== me);
        const canUnlock = status === 'IN_REVIEW' && (a.review_locked_by === me || isAdmin);
        document.getElementById('zrModalTitle').textContent = 'Z Report #' + a.id + ' — ' + (a.store||'') + ' — ' + (a.date||'');
        // Build safe HTML with esc() on all dynamic strings
        let html = '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px">'
            + '<div class="kpi-card kpi-accent-teal"><div class="kpi-label">Gross</div><div class="kpi-val" style="font-size:20px">$' + gross.toFixed(2) + '</div></div>'
            + '<div class="kpi-card kpi-accent-green"><div class="kpi-label">Net</div><div class="kpi-val" style="font-size:20px">$' + net.toFixed(2) + '</div></div>'
            + '<div class="kpi-card ' + (variance<0?'kpi-accent-amber':'kpi-accent-green') + '"><div class="kpi-label">Variance</div><div class="kpi-val" style="font-size:20px;color:' + (variance<0?'#b45309':'#047857') + '">$' + parseFloat(variance).toFixed(2) + '</div></div></div>'
            + '<div style="margin-bottom:16px">Status: ' + app.zr._badge(status)
            + (a.review_locked_by ? ' &nbsp;<span style="font-size:12px;color:#64748b">Locked by <b>' + esc(a.review_locked_by) + '</b></span>' : '') + '</div>'
            + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px">';
        if(canLock) html += '<button onclick="app.zr.lock(' + a.id + ')" class="btn-main" style="padding:8px 16px;font-size:13px">🔒 Lock to Review</button>';
        if(canUnlock) html += '<button onclick="app.zr.unlock(' + a.id + ')" style="padding:8px 16px;font-size:13px;background:#64748b;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:700">🔓 Release Lock</button>';
        if(isAdmin && status==='FINAL_APPROVED') html += '<button onclick="app.zr.amendPrompt(' + a.id + ')" style="padding:8px 16px;font-size:13px;background:#8b5cf6;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:700">✏️ Amend</button>';
        html += '</div>';
        if(canAct) {
            html += '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin-bottom:16px">'
                + '<div style="font-weight:800;font-size:12px;text-transform:uppercase;color:#64748b;margin-bottom:12px">Review Form</div>'
                + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
                + '<div><label style="font-size:12px;font-weight:700;color:#64748b">Payouts Total ($)</label><input type="number" step="0.01" id="zrPayouts" value="0" style="margin-bottom:8px"></div>'
                + '<div><label style="font-size:12px;font-weight:700;color:#64748b">Cash in Register ($)</label><input type="number" step="0.01" id="zrCashActual" value="' + parseFloat(bd.actual||0).toFixed(2) + '" style="margin-bottom:8px"></div></div>'
                + '<label style="font-size:12px;font-weight:700;color:#64748b">Manager Notes (optional)</label>'
                + '<textarea id="zrNotes" style="width:100%;padding:8px;border:1.5px solid #cbd5e1;border-radius:8px;font-size:13px;margin-bottom:12px;resize:vertical" rows="2" placeholder="Notes..."></textarea>'
                + '<div style="display:flex;gap:8px">'
                + '<button onclick="app.zr.approve(' + a.id + ')" style="flex:1;padding:10px;background:#047857;color:white;border:none;border-radius:8px;font-weight:800;cursor:pointer;font-size:13px">✅ Approve</button>'
                + '<button onclick="app.zr.rejectPrompt(' + a.id + ')" style="flex:1;padding:10px;background:#ef4444;color:white;border:none;border-radius:8px;font-weight:800;cursor:pointer;font-size:13px">❌ Reject</button>'
                + '</div></div>';
        }
        if(rv) {
            html += '<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:12px;font-size:12px">'
                + '<b>Last Review:</b> ' + esc(rv.action) + ' by ' + esc(rv.reviewed_by)
                + ' — Gross: $' + parseFloat(rv.calculated_gross||0).toFixed(2)
                + ', Net: $' + parseFloat(rv.calculated_net||0).toFixed(2)
                + ', Var: $' + parseFloat(rv.calculated_variance||0).toFixed(2)
                + (rv.rejection_reason ? '<br><b>Rejection:</b> ' + esc(rv.rejection_reason) : '')
                + (rv.amendment_reason ? '<br><b>Amendment:</b> ' + esc(rv.amendment_reason) : '')
                + '</div>';
        }
        document.getElementById('zrModalBody').innerHTML = html;
    },
    lock: async (id) => {
        const r = await fetch('/api/z-reports/'+id+'/lock',{method:'POST'});
        const d = await r.json();
        if(r.ok) { app.zr.openModal(id); app.zr.fetchList(); } else alert('Lock failed: '+(d.error||r.status));
    },
    unlock: async (id) => {
        const r = await fetch('/api/z-reports/'+id+'/lock',{method:'DELETE'});
        const d = await r.json();
        if(r.ok) { app.zr.openModal(id); app.zr.fetchList(); } else alert('Unlock failed: '+(d.error||r.status));
    },
    approve: async (id) => {
        const payouts = parseFloat(document.getElementById('zrPayouts').value||0);
        const cashActual = parseFloat(document.getElementById('zrCashActual').value||0);
        const notes = document.getElementById('zrNotes').value;
        const r = await fetch('/api/z-reports/'+id+'/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payouts_total:payouts,cash_in_register_actual:cashActual,manager_notes:notes})});
        const d = await r.json();
        if(r.ok) { document.getElementById('zrModal').style.display='none'; app.zr.fetchList(); alert('Approved! Gross: $'+d.gross+', Net: $'+d.net+', Var: $'+d.variance); }
        else alert('Approve failed: '+(d.error||r.status));
    },
    rejectPrompt: async (id) => {
        const reason = prompt('Rejection reason (required):');
        if(!reason) return;
        const r = await fetch('/api/z-reports/'+id+'/reject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rejection_reason:reason})});
        const d = await r.json();
        if(r.ok) { document.getElementById('zrModal').style.display='none'; app.zr.fetchList(); alert('Rejected.'); }
        else alert('Reject failed: '+(d.error||r.status));
    },
    amendPrompt: async (id) => {
        const reason = prompt('Amendment reason (required):');
        if(!reason) return;
        const r = await fetch('/api/z-reports/'+id+'/amend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amendment_reason:reason})});
        const d = await r.json();
        if(r.ok) { document.getElementById('zrModal').style.display='none'; app.zr.fetchList(); alert('Audit reopened for amendment.'); }
        else alert('Amend failed: '+(d.error||r.status));
    }
};

app.init();
</script>
<!-- Z Report Image Modal -->
<div id="zreportModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:9999;align-items:center;justify-content:center;" onclick="if(event.target===this)this.style.display='none'">
  <div style="position:relative;max-width:90vw;max-height:90vh">
    <button onclick="document.getElementById('zreportModal').style.display='none'" style="position:absolute;top:-36px;right:0;background:none;border:none;color:white;font-size:28px;cursor:pointer">✕</button>
    <div style="position:relative;display:inline-block">
      <button id="zreportPrev" onclick="app.galleryNav(-1)" style="display:none;position:absolute;left:-44px;top:50%;transform:translateY(-50%);background:rgba(255,255,255,0.25);border:none;color:white;font-size:26px;cursor:pointer;border-radius:50%;width:36px;height:36px;line-height:36px">&#8249;</button>
      <img id="zreportImg" src="" style="max-width:90vw;max-height:72vh;border-radius:8px 8px 0 0;display:block">
      <button id="zreportNext" onclick="app.galleryNav(1)" style="display:none;position:absolute;right:-44px;top:50%;transform:translateY(-50%);background:rgba(255,255,255,0.25);border:none;color:white;font-size:26px;cursor:pointer;border-radius:50%;width:36px;height:36px;line-height:36px">&#8250;</button>
    </div>
    <div id="zreportMeta" style="background:rgba(255,255,255,0.95);padding:8px 14px;border-radius:0 0 8px 8px;font-size:12px;display:flex;gap:14px;flex-wrap:wrap;color:#1e293b;align-items:center">
      <span id="zreportCounter" style="font-weight:bold;color:#0097b2;min-width:40px"></span>
      <span>🏪 <span data-store></span></span>
      <span>🖩 <span data-register></span></span>
      <span>📅 <span data-date></span></span>
      <span>👤 <span data-by></span></span>
      <span>🕐 <span data-at></span></span>
      <button id="zreportDeleteBtn" onclick="app.deleteCurrentPhoto()" style="display:none;margin-left:auto;background:#fee2e2;border:1px solid #ef4444;color:#b91c1c;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;font-weight:700;">🗑 Delete</button>
    </div>
  </div>
</div>
</body></html>"""

def _send_eod_reminders() -> None:
    """Send 9 PM reminder to bot users whose store hasn't submitted today."""
    try:
        from zoneinfo import ZoneInfo
        pr_tz = ZoneInfo("America/Puerto_Rico")
        today = datetime.now(pr_tz).strftime("%Y-%m-%d")
        _db = supabase_admin or supabase
        if _db is None:
            return
        subs = _db.table("audits").select("store").eq("date", today).execute()
        submitted_stores = {s["store"] for s in (subs.data or [])}
        bot_users_resp = _db.table("bot_users").select("telegram_id, store").execute()
        if not bot_users_resp.data:
            return
        from telegram_bot import send_message
        notified = set()
        failed = []
        for bu in bot_users_resp.data:
            store = bu.get("store", "")
            tid = bu["telegram_id"]
            if store in ("All", "") or tid in notified:
                continue
            if store not in submitted_stores:
                try:
                    send_message(
                        tid,
                        f"⏰ Recordatorio: {store} no ha enviado el Reporte Z de hoy ({today}).\n"
                        f"Envía una foto del Reporte Z para registrarlo."
                    )
                    notified.add(tid)
                except Exception as exc:
                    logger.error("EOD reminder failed store=%s tid=%s: %s", store, tid, exc)
                    failed.append(store)
        logger.info("EOD reminders: sent=%d failed=%d for %s", len(notified), len(failed), today)
        if failed:
            logger.warning("EOD reminder failures for stores: %s", failed)
    except Exception as e:
        logger.warning(f"_send_eod_reminders failed: {e}")


# ── APScheduler: EOD submission reminder at 21:00 PR time ──────────────────────
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _send_eod_reminders,
        CronTrigger(hour=21, minute=0, timezone="America/Puerto_Rico"),
        id="eod_reminder",
        replace_existing=True,
    )
    _scheduler.start()
    import atexit
    atexit.register(lambda: _scheduler.shutdown(wait=False))
    logger.info("APScheduler started: EOD reminder at 21:00 PR time")
except ImportError:
    logger.warning("APScheduler not installed — EOD reminders disabled")
except Exception as _sched_e:
    logger.warning(f"APScheduler start failed: {_sched_e}")


# Register Telegram webhook on startup (idempotent — safe on every deploy)
try:
    from telegram_bot import register_webhook
    register_webhook()
except Exception as _e:
    logger.warning(f"Could not register Telegram webhook: {_e}")

if __name__ == '__main__':
    # Only open browser when running locally (not on a cloud server)
    import os as _os
    if not _os.getenv('RAILWAY_ENVIRONMENT') and not _os.getenv('RENDER'):
        Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host='0.0.0.0', port=PORT)