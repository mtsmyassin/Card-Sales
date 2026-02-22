# app.py God-File Refactor — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split 3019-line app.py into Flask Blueprints, helper modules, and HTML template files, resulting in a ~100-line pure factory with zero behaviour changes.

**Architecture:** `extensions.py` holds shared state (supabase clients, csrf, etc.) to avoid circular imports. Seven Flask Blueprints cover each domain. Templates extracted to `templates/`. All 135 currently-passing tests must remain green after every task.

**Tech Stack:** Flask, Flask-WTF, Supabase-py, APScheduler, pytest

---

## Pre-flight checks

Before starting, verify baseline:
```bash
cd Pharmacy_Arc
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
# Expected: 135 passed, 10 failed (pre-existing), 1 skipped
```

All work happens on an isolated git branch:
```bash
git checkout -b refactor/split-app-py
```

---

## Task 1: Create `extensions.py` — shared state module

**Files:**
- Create: `Pharmacy_Arc/extensions.py`

**What it does:** Holds supabase clients, csrf, password_hasher, login_tracker, and EMERGENCY_ACCOUNTS as module-level attributes. Routes import from here instead of from `app.py`, breaking the circular import chain.

**Step 1: Create the file**

```python
# extensions.py
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
```

**Step 2: Verify it imports cleanly**

```bash
PYTHONUTF8=1 python -c "import extensions; print('ok')"
# Expected: ok
```

**Step 3: Run tests to confirm nothing broke**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
# Expected: 135 passed, 10 failed, 1 skipped (unchanged)
```

**Step 4: Commit**

```bash
git add extensions.py
git commit -m "refactor: add extensions.py shared state module"
```

---

## Task 2: Create `helpers/auth_utils.py` — require_auth decorator

**Files:**
- Create: `Pharmacy_Arc/helpers/__init__.py`
- Create: `Pharmacy_Arc/helpers/auth_utils.py`

**What it does:** Moves `require_auth` and `_can_access_photo` out of `app.py` into a helper with no dependency on `app.py`. Routes will `from helpers.auth_utils import require_auth`.

**Step 1: Create helpers package**

```bash
mkdir -p Pharmacy_Arc/helpers
touch Pharmacy_Arc/helpers/__init__.py
```

**Step 2: Create `helpers/auth_utils.py`**

Copy the `require_auth` and `_can_access_photo` functions from `app.py` (lines ~36–78) verbatim:

```python
# helpers/auth_utils.py
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
    allowed_roles: list of roles allowed (None = any authenticated user).
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
    if photo_store is None:
        return False
    return photo_store == user_store
```

> NOTE: `_can_access_photo` is renamed to `can_access_photo` (public) since it's now in its own module.

**Step 3: Verify it imports cleanly**

```bash
PYTHONUTF8=1 python -c "from helpers.auth_utils import require_auth, can_access_photo; print('ok')"
# Expected: ok
```

**Step 4: Run tests**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
# Expected: 135 passed, 10 failed, 1 skipped
```

**Step 5: Commit**

```bash
git add helpers/__init__.py helpers/auth_utils.py
git commit -m "refactor: add helpers/auth_utils.py (require_auth, can_access_photo)"
```

---

## Task 3: Create `helpers/validation.py`

**Files:**
- Create: `Pharmacy_Arc/helpers/validation.py`

**Step 1: Create the file**

Copy `validate_audit_entry` (app.py ~230–300) and `validate_user_data` (app.py ~301–341) verbatim:

```python
# helpers/validation.py
"""Input validation helpers for audit entries and user data."""
import re
from datetime import datetime


def validate_audit_entry(data: dict) -> tuple[bool, str]:
    """
    Validate a sales audit entry dictionary.
    Returns (True, "") on success or (False, error_message) on failure.
    """
    # [copy the full body of validate_audit_entry from app.py here]
    ...


def validate_user_data(data: dict, is_update: bool = False) -> tuple[bool, str]:
    """
    Validate user creation/update payload.
    Returns (True, "") on success or (False, error_message) on failure.
    """
    # [copy the full body of validate_user_data from app.py here]
    ...
```

> IMPORTANT: Copy the function bodies exactly from app.py. Do NOT rewrite them.

**Step 2: Verify**

```bash
PYTHONUTF8=1 python -c "from helpers.validation import validate_audit_entry, validate_user_data; print('ok')"
```

**Step 3: Run tests**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
# Expected: 135 passed, 10 failed, 1 skipped
```

**Step 4: Commit**

```bash
git add helpers/validation.py
git commit -m "refactor: add helpers/validation.py (validate_audit_entry, validate_user_data)"
```

---

## Task 4: Create `helpers/offline_queue.py`

**Files:**
- Create: `Pharmacy_Arc/helpers/offline_queue.py`

**Step 1: Create the file**

Copy `get_base_path`, `get_queue_path`, `get_logo`, `save_to_queue`, `load_queue`, `clear_queue`, and `OFFLINE_QUEUE_MAX_SIZE` from app.py (lines ~343–398):

```python
# helpers/offline_queue.py
"""
Offline queue: persists audit entries to a local JSON file when Supabase is
unavailable. Also contains path helpers and logo loader used by routes/main.py.
"""
import os, sys, json, base64, logging
from config import Config

logger = logging.getLogger(__name__)

OFFLINE_QUEUE_MAX_SIZE = int(os.getenv('OFFLINE_QUEUE_MAX_SIZE', '2000'))
OFFLINE_FILE = Config.OFFLINE_FILE


def get_base_path() -> str:
    """Return directory for data files (PyInstaller-safe)."""
    return sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__ if not getattr(sys, 'frozen', False) else sys.executable))


def get_queue_path() -> str:
    """Return the path to the offline queue JSON file."""
    # [copy exact body from app.py]
    ...


def get_logo(store_name=None) -> str:
    """Return base64-encoded logo PNG for the given store name."""
    # [copy exact body from app.py]
    ...


def save_to_queue(payload: dict) -> bool:
    """Append payload to offline queue. Returns False if queue is full."""
    # [copy exact body from app.py]
    ...


def load_queue() -> list:
    """Load and return the offline queue list."""
    # [copy exact body from app.py]
    ...


def clear_queue() -> None:
    """Delete the offline queue file."""
    # [copy exact body from app.py]
    ...
```

> IMPORTANT: `get_base_path()` in app.py uses `os.path.abspath(__file__)` which resolves to `app.py`'s directory. After moving to `helpers/offline_queue.py`, `__file__` will point to `helpers/`, not the project root. Fix this:
>
> ```python
> def get_base_path() -> str:
>     if getattr(sys, 'frozen', False):
>         return sys._MEIPASS
>     # Always use the project root (one level above helpers/)
>     return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
> ```

**Step 2: Verify**

```bash
PYTHONUTF8=1 python -c "from helpers.offline_queue import save_to_queue, load_queue, get_logo; print('ok')"
```

**Step 3: Run tests (including queue roundtrip tests)**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
# Expected: 135 passed, 10 failed, 1 skipped
```

**Step 4: Commit**

```bash
git add helpers/offline_queue.py
git commit -m "refactor: add helpers/offline_queue.py (queue + path + logo helpers)"
```

---

## Task 5: Create `helpers/scheduler.py`

**Files:**
- Create: `Pharmacy_Arc/helpers/scheduler.py`

**Step 1: Create the file**

```python
# helpers/scheduler.py
"""
APScheduler integration for EOD reminder job.
init_scheduler(app) is called by the app factory.
The scheduler is stored as app._scheduler for gunicorn.conf.py post_fork hook.
"""
import atexit
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _send_eod_reminders() -> None:
    """Send 9 PM reminder to bot users whose store hasn't submitted today."""
    import extensions  # deferred — extensions is populated by the factory at startup
    from telegram_bot import send_message
    # [copy exact body of _send_eod_reminders from app.py]
    ...


def init_scheduler(app) -> None:
    """Start APScheduler in the current process. Stores instance as app._scheduler."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _send_eod_reminders,
            CronTrigger(hour=21, minute=0, timezone="America/Puerto_Rico"),
            id="eod_reminder",
            replace_existing=True,
        )
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))
        app._scheduler = scheduler  # referenced by gunicorn.conf.py post_fork
        logger.info("APScheduler started: EOD reminder at 21:00 PR time")
    except ImportError:
        logger.warning("APScheduler not installed — EOD reminders disabled")
    except Exception as exc:
        logger.warning(f"APScheduler start failed: {exc}")
```

**Step 2: Update `gunicorn.conf.py`** — the `post_fork` hook currently does `getattr(_app, '_scheduler', None)`. After refactor, `_scheduler` lives on the Flask app instance (`_app.app._scheduler`), not on the module:

```python
# gunicorn.conf.py — update post_fork
def post_fork(server, worker):
    """Shut down APScheduler in forked workers — only the master runs it."""
    try:
        import app as _app
        flask_app = getattr(_app, 'app', None)       # the Flask app instance
        scheduler = getattr(flask_app, '_scheduler', None)
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
            log.info("APScheduler shut down in worker pid=%s", worker.pid)
    except Exception as exc:
        log.warning("post_fork: could not shut down scheduler: %s", exc)
```

**Step 3: Verify**

```bash
PYTHONUTF8=1 python -c "from helpers.scheduler import init_scheduler; print('ok')"
```

**Step 4: Run tests**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
# Expected: 135 passed, 10 failed, 1 skipped
```

**Step 5: Commit**

```bash
git add helpers/scheduler.py gunicorn.conf.py
git commit -m "refactor: add helpers/scheduler.py; update gunicorn.conf.py post_fork reference"
```

---

## Task 6: Extract HTML templates

**Files:**
- Create: `Pharmacy_Arc/templates/login.html`
- Create: `Pharmacy_Arc/templates/main.html`

**Step 1: Create templates directory**

```bash
mkdir -p Pharmacy_Arc/templates
```

**Step 2: Extract `login.html`**

Find `LOGIN_UI = """` in app.py (line ~1953). Copy everything between the triple-quotes into `templates/login.html`. Do not include the Python assignment or the closing `"""`.

**Step 3: Extract `main.html`**

Find `MAIN_UI = """` in app.py (line ~2003). Copy everything between the triple-quotes into `templates/main.html`.

**Step 4: Verify templates parse as Jinja2**

```bash
PYTHONUTF8=1 python -c "
from flask import Flask
app = Flask(__name__)
with app.app_context():
    from flask import render_template
    # This will raise TemplateNotFound or TemplateSyntaxError if broken
    try:
        # render with dummy vars
        r = render_template('login.html', logo='')
        print('login.html OK, length:', len(r))
        r = render_template('main.html', logo='', pending=False)
        print('main.html OK, length:', len(r))
    except Exception as e:
        print('ERROR:', e)
"
```

**Step 5: Run tests**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
# Expected: 135 passed, 10 failed, 1 skipped
# (app.py still uses render_template_string — templates not used yet)
```

**Step 6: Commit**

```bash
git add templates/login.html templates/main.html
git commit -m "refactor: extract LOGIN_UI and MAIN_UI to templates/login.html and templates/main.html"
```

---

## Task 7: Create `routes/__init__.py` and `routes/main.py`

**Files:**
- Create: `Pharmacy_Arc/routes/__init__.py`
- Create: `Pharmacy_Arc/routes/main.py`

**Step 1: Create routes package**

```bash
mkdir -p Pharmacy_Arc/routes
touch Pharmacy_Arc/routes/__init__.py
```

**Step 2: Create `routes/main.py`**

```python
# routes/main.py
"""Main UI Blueprint — serves the SPA shell and favicon."""
import io
import os
from flask import Blueprint, render_template, session, send_file
from helpers.offline_queue import get_logo, get_base_path, load_queue

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    current_store = session.get('store', 'Carimas #1')
    logo_data = get_logo(current_store)
    has_pending = len(load_queue()) > 0
    template = 'main.html' if session.get('logged_in') else 'login.html'
    return render_template(template, logo=logo_data, pending=has_pending)


@bp.route('/favicon.ico')
def favicon():
    logo_path = os.path.join(get_base_path(), 'logo.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as fh:
            return send_file(io.BytesIO(fh.read()), mimetype='image/png')
    return '', 204
```

**Step 3: Verify import**

```bash
PYTHONUTF8=1 python -c "from routes.main import bp; print('ok')"
```

**Step 4: Run tests**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
# Expected: 135 passed
```

**Step 5: Commit**

```bash
git add routes/__init__.py routes/main.py
git commit -m "refactor: add routes/main.py Blueprint (index, favicon)"
```

---

## Task 8: Create `routes/auth.py`

**Files:**
- Create: `Pharmacy_Arc/routes/auth.py`

**Step 1: Create the file**

Move `login()`, `logout()`, `csrf_token()`, `api_get_logo()`, and `enforce_session_timeout` from app.py. Note: `enforce_session_timeout` uses `bp.before_app_request` (not `bp.before_request`) so it fires for ALL routes, not just auth routes.

```python
# routes/auth.py
"""Auth Blueprint — login, logout, CSRF token, session timeout."""
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, session, redirect, url_for
from audit_log import audit_log
import extensions
from helpers.auth_utils import require_auth
from helpers.offline_queue import get_logo
from config import Config

logger = logging.getLogger(__name__)

bp = Blueprint('auth', __name__)

_SESSION_SKIP_ENDPOINTS = frozenset({
    'auth.login', 'auth.csrf_token', 'telegram.telegram_webhook',
    'static', 'main.favicon', 'main.index', 'diagnostics.health',
})


@bp.before_app_request
def enforce_session_timeout():
    """Expire sessions idle longer than SESSION_TIMEOUT_MINUTES."""
    if not session.get('logged_in'):
        return
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
                return
        except (ValueError, TypeError):
            session.clear()
            return

    session['last_active'] = now.isoformat()
    session.modified = True


@bp.route('/api/csrf-token', methods=['GET'])
def csrf_token():
    from flask_wtf.csrf import generate_csrf
    return jsonify(token=generate_csrf())


@bp.route('/api/login', methods=['POST'])
@extensions.csrf.exempt
def login():
    # [copy full login() body from app.py verbatim]
    # Replace: supabase → extensions.supabase
    # Replace: supabase_admin → extensions.supabase_admin
    # Replace: EMERGENCY_ACCOUNTS → extensions.EMERGENCY_ACCOUNTS
    # Replace: password_hasher → extensions.password_hasher
    # Replace: login_tracker → extensions.login_tracker
    ...


@bp.route('/api/logout', methods=['POST'])
def logout():
    # [copy full logout() body from app.py verbatim]
    ...


@bp.route('/api/get_logo', methods=['POST'])
@require_auth()
def api_get_logo():
    # [copy full api_get_logo() body from app.py verbatim]
    # Replace get_logo() call — already imported from helpers.offline_queue
    ...
```

> SUBSTITUTION GUIDE for all route files:
> - `supabase` → `extensions.supabase`
> - `supabase_admin` → `extensions.supabase_admin`
> - `EMERGENCY_ACCOUNTS` → `extensions.EMERGENCY_ACCOUNTS`
> - `password_hasher` → `extensions.password_hasher`
> - `login_tracker` → `extensions.login_tracker`
> - `_can_access_photo` → `can_access_photo` (from helpers.auth_utils)
> - `validate_audit_entry` → import from helpers.validation
> - `validate_user_data` → import from helpers.validation
> - `save_to_queue / load_queue / clear_queue` → import from helpers.offline_queue

**Step 2: Verify import**

```bash
PYTHONUTF8=1 python -c "from routes.auth import bp; print('ok')"
```

**Step 3: Run tests**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
```

**Step 4: Commit**

```bash
git add routes/auth.py
git commit -m "refactor: add routes/auth.py Blueprint (login, logout, csrf, session timeout)"
```

---

## Task 9: Create `routes/audits.py`

**Files:**
- Create: `Pharmacy_Arc/routes/audits.py`

**Step 1: Create the file**

Move `_send_variance_alert`, `save()`, `sync()`, `update()`, `delete()`, `list_audits()` from app.py. Apply the substitution guide from Task 8.

```python
# routes/audits.py
"""Audits Blueprint — CRUD for pharmacy sales audit entries."""
import logging
from threading import Thread
from flask import Blueprint, request, jsonify, session
from audit_log import audit_log
import extensions
from helpers.auth_utils import require_auth
from helpers.validation import validate_audit_entry
from helpers.offline_queue import save_to_queue, load_queue, clear_queue

logger = logging.getLogger(__name__)
bp = Blueprint('audits', __name__)


def _send_variance_alert(...):
    # [copy exact body from app.py]
    ...

@bp.route('/api/save', methods=['POST'])
@require_auth()
def save():
    # [copy exact body, apply substitutions]
    ...

@bp.route('/api/sync', methods=['POST'])
@require_auth()
def sync():
    ...

@bp.route('/api/update', methods=['POST'])
@require_auth()
def update():
    ...

@bp.route('/api/delete', methods=['POST'])
@require_auth()
def delete():
    ...

@bp.route('/api/list')
@require_auth()
def list_audits():
    ...
```

**Step 2: Verify + test + commit**

```bash
PYTHONUTF8=1 python -c "from routes.audits import bp; print('ok')"
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
git add routes/audits.py
git commit -m "refactor: add routes/audits.py Blueprint (save, sync, update, delete, list)"
```

---

## Task 10: Create `routes/users.py`

**Files:**
- Create: `Pharmacy_Arc/routes/users.py`

Move `list_users()`, `save_user()`, `delete_user()` from app.py. Apply substitution guide.

```python
# routes/users.py
"""Users Blueprint — user management (admin only)."""
import logging
from flask import Blueprint, request, jsonify, session
from audit_log import audit_log
import extensions
from helpers.auth_utils import require_auth
from helpers.validation import validate_user_data

logger = logging.getLogger(__name__)
bp = Blueprint('users', __name__)

@bp.route('/api/users/list')
@require_auth(allowed_roles=['admin', 'super_admin'])
def list_users():
    ...

@bp.route('/api/users/save', methods=['POST'])
@require_auth(allowed_roles=['admin', 'super_admin'])
def save_user():
    ...

@bp.route('/api/users/delete', methods=['POST'])
@require_auth(allowed_roles=['admin', 'super_admin'])
def delete_user():
    ...
```

**Verify + test + commit:**

```bash
PYTHONUTF8=1 python -c "from routes.users import bp; print('ok')"
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
git add routes/users.py
git commit -m "refactor: add routes/users.py Blueprint (list, save, delete users)"
```

---

## Task 11: Create `routes/zreports.py`

**Files:**
- Create: `Pharmacy_Arc/routes/zreports.py`

Move all Z-report review routes (app.py lines ~1481–1951): `_zr_recalculate`, `_zr_validate_breakdown`, `_zr_log`, `zr_list`, `zr_detail`, `zr_lock`, `zr_unlock`, `zr_approve`, `zr_reject`, `zr_reopen`, `zr_amend`, `zr_history`, `zr_audit_log`, `zr_unlock_timed_out`. Apply substitution guide.

```python
# routes/zreports.py
"""Z-Report Review Blueprint — lock/unlock/approve/reject/amend/history."""
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, session
from audit_log import audit_log
import extensions
from helpers.auth_utils import require_auth

logger = logging.getLogger(__name__)
bp = Blueprint('zreports', __name__)

# [copy all _zr_* helpers and route functions verbatim, apply substitutions]
```

**Verify + test + commit:**

```bash
PYTHONUTF8=1 python -c "from routes.zreports import bp; print('ok')"
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
git add routes/zreports.py
git commit -m "refactor: add routes/zreports.py Blueprint (Z-report review API)"
```

---

## Task 12: Create `routes/telegram.py`

**Files:**
- Create: `Pharmacy_Arc/routes/telegram.py`

Move `telegram_webhook()`, `get_zreport_image()`, `get_entry_photos()`, `get_photo_signed_url()`, `delete_photo()` from app.py. Apply substitution guide.

```python
# routes/telegram.py
"""Telegram Blueprint — bot webhook and Z-report photo endpoints."""
import logging
from threading import Thread
from flask import Blueprint, request, jsonify, session, send_file
import hmac
import extensions
from helpers.auth_utils import require_auth, can_access_photo
from config import Config

logger = logging.getLogger(__name__)
bp = Blueprint('telegram', __name__)


@bp.route('/api/telegram/webhook', methods=['POST'])
@extensions.csrf.exempt
def telegram_webhook():
    # [copy exact body, apply substitutions]
    ...

@bp.route('/api/audit/<int:audit_id>/zreport_image')
@require_auth()
def get_zreport_image(audit_id: int):
    # [copy exact body]
    # Replace _can_access_photo → can_access_photo
    ...

@bp.route('/api/zreport/photos')
@require_auth()
def get_entry_photos():
    ...

@bp.route('/api/zreport/signed_url')
@require_auth()
def get_photo_signed_url():
    ...

@bp.route('/api/zreport/photo/<int:photo_id>', methods=['DELETE'])
@require_auth()
def delete_photo(photo_id):
    ...
```

**Verify + test + commit:**

```bash
PYTHONUTF8=1 python -c "from routes.telegram import bp; print('ok')"
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
git add routes/telegram.py
git commit -m "refactor: add routes/telegram.py Blueprint (webhook + photo endpoints)"
```

---

## Task 13: Create `routes/diagnostics.py`

**Files:**
- Create: `Pharmacy_Arc/routes/diagnostics.py`

Move `diagnostics()` from app.py (line ~1011). Apply substitution guide.

```python
# routes/diagnostics.py
"""Diagnostics Blueprint — /api/diagnostics health and status endpoint."""
import logging
from flask import Blueprint, request, jsonify, session
import extensions
from helpers.auth_utils import require_auth
from helpers.offline_queue import load_queue
from config import Config

logger = logging.getLogger(__name__)
bp = Blueprint('diagnostics', __name__)


@bp.route('/api/diagnostics')
@require_auth(allowed_roles=['admin', 'super_admin'])
def diagnostics():
    # [copy exact body, apply substitutions]
    ...
```

**Verify + test + commit:**

```bash
PYTHONUTF8=1 python -c "from routes.diagnostics import bp; print('ok')"
PYTHONUTF8=1 python -m pytest tests/ --tb=no -q
git add routes/diagnostics.py
git commit -m "refactor: add routes/diagnostics.py Blueprint (/api/diagnostics)"
```

---

## Task 14: Rewrite `app.py` as pure factory

**Files:**
- Modify: `Pharmacy_Arc/app.py` (full rewrite)

This is the critical step. Replace the entire 3019-line file with a ~120-line factory. Run tests immediately after.

**Step 1: Write the new app.py**

```python
# app.py
"""
Pharmacy Auditor — Flask application factory.

Entry point for gunicorn: gunicorn app:app
Entry point for tests:    import app; app.app (the Flask instance)
"""
import os, sys, time, hmac, io, json, base64, logging
from datetime import datetime, timedelta, timezone
from threading import Timer, Thread
from flask import Flask, request, jsonify, redirect
from supabase import create_client
from config import Config
import extensions

logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

VERSION = "v41-REFACTOR"
PORT = int(os.getenv('PORT', str(Config.PORT)))


def _init_supabase(url: str, key: str, label: str, max_attempts: int = 3):
    """Create a Supabase client with exponential backoff retry."""
    for attempt in range(1, max_attempts + 1):
        try:
            client = create_client(url, key)
            logger.info("Supabase %s client connected (attempt %d)", label, attempt)
            return client
        except Exception as exc:
            if attempt == max_attempts:
                logger.critical("Supabase %s: all %d attempts failed: %s", label, max_attempts, exc)
                return None
            delay = 2 ** (attempt - 1)
            logger.warning("Supabase %s: attempt %d failed, retrying in %ds: %s", label, attempt, delay, exc)
            time.sleep(delay)
    return None


def create_app() -> Flask:
    print(f"--- LAUNCHING {VERSION} ON PORT {PORT} ---")

    app = Flask(__name__)
    app.secret_key = Config.SECRET_KEY
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=Config.SESSION_TIMEOUT_MINUTES)
    app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken']
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # ── Extensions ──────────────────────────────────────────────────────────────
    extensions.csrf.init_app(app)

    extensions.supabase = _init_supabase(Config.SUPABASE_URL, Config.SUPABASE_KEY, "anon")
    if extensions.supabase is None:
        print("CRITICAL ERROR: Supabase anon client unavailable — app running in offline mode")

    if Config.SUPABASE_SERVICE_KEY:
        extensions.supabase_admin = _init_supabase(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY, "admin")
        if extensions.supabase_admin is None:
            logger.warning("Supabase admin client unavailable — photo uploads and RLS bypass disabled")

    extensions.EMERGENCY_ACCOUNTS = Config.load_emergency_accounts()
    logger.info("Loaded %d emergency admin account(s)", len(extensions.EMERGENCY_ACCOUNTS))

    _lockout_db = extensions.supabase_admin or extensions.supabase
    if _lockout_db:
        extensions.login_tracker.configure_db(_lockout_db)
        from audit_log import get_audit_logger
        get_audit_logger().configure_db(_lockout_db)

    # ── HTTPS enforcement ───────────────────────────────────────────────────────
    if Config.REQUIRE_HTTPS:
        app.config['SESSION_COOKIE_SECURE'] = True

        @app.before_request
        def enforce_https():
            if not request.is_secure and request.url.startswith('http://'):
                if not (request.host.startswith('127.0.0.1') or request.host.startswith('localhost')):
                    return redirect(request.url.replace('http://', 'https://', 1), code=301)
    else:
        app.config['SESSION_COOKIE_SECURE'] = False
        logger.warning("⚠️  SESSION_COOKIE_SECURE disabled - HTTPS not required. Enable for production!")

    # ── Blueprints ──────────────────────────────────────────────────────────────
    from routes.main import bp as main_bp
    from routes.auth import bp as auth_bp
    from routes.audits import bp as audits_bp
    from routes.users import bp as users_bp
    from routes.zreports import bp as zreports_bp
    from routes.telegram import bp as telegram_bp
    from routes.diagnostics import bp as diag_bp

    for blueprint in [main_bp, auth_bp, audits_bp, users_bp, zreports_bp, telegram_bp, diag_bp]:
        app.register_blueprint(blueprint)

    # ── App-wide hooks ──────────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
        if Config.REQUIRE_HTTPS:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    @app.errorhandler(413)
    def payload_too_large(e):
        return jsonify(error="Payload too large (máximo 5 MB)"), 413

    # ── Scheduler ───────────────────────────────────────────────────────────────
    from helpers.scheduler import init_scheduler
    init_scheduler(app)

    return app


# Module-level instance for gunicorn: gunicorn app:app
# Also used by tests: import app; client = app.app.test_client()
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=Config.DEBUG)
```

**Step 2: Run the full test suite immediately**

```bash
PYTHONUTF8=1 python -m pytest tests/ -v 2>&1 | tail -20
# Expected: 135 passed, 10 failed (pre-existing), 1 skipped
# If any NEW failures appear, revert and debug before continuing.
```

**Step 3: Smoke test — verify the app starts**

```bash
PYTHONUTF8=1 python -c "import app; print('App created OK, blueprints:', [bp.name for bp in app.app.blueprints.values()])"
```

**Step 4: Commit**

```bash
git add app.py
git commit -m "refactor: rewrite app.py as pure factory (~120 lines); all routes in blueprints"
```

---

## Task 15: Final verification and merge

**Step 1: Full test suite — must match baseline exactly**

```bash
PYTHONUTF8=1 python -m pytest tests/ --tb=short -q
# Required: same 135 passing, same 10 failing as before refactor
```

**Step 2: Check app.py line count**

```bash
wc -l app.py
# Expected: < 150 lines
```

**Step 3: Verify no old MAIN_UI/LOGIN_UI strings remain in app.py**

```bash
grep -c "MAIN_UI\|LOGIN_UI" app.py
# Expected: 0
```

**Step 4: Verify all route endpoints are registered**

```bash
PYTHONUTF8=1 python -c "
import app
rules = sorted(str(r) for r in app.app.url_map.iter_rules())
for r in rules:
    print(r)
"
# Expected: all routes that existed before refactor are present
```

**Step 5: Merge to main**

```bash
git checkout main
git merge --no-ff refactor/split-app-py -m "refactor(cycle22): split 3019-line app.py into blueprints + helpers + templates"
git push
railway up --detach
```

---

## Troubleshooting

**"No application found" from gunicorn:**
The Procfile uses `app:app`. After refactor, `app.py` still defines `app = create_app()` at module level — so `gunicorn app:app` still works.

**"ImportError: cannot import name X from app":**
Tests that do `from app import supabase` will fail because `supabase` is now `extensions.supabase`. Fix by updating the test or using `import extensions; extensions.supabase`.

**"TemplateNotFound: login.html":**
Flask looks for templates in a `templates/` directory relative to the app's root. If Flask's root is not the project root, set it explicitly: `Flask(__name__, template_folder='templates')`.

**"AttributeError: 'NoneType' object has no attribute X" in route:**
A route accessed `extensions.supabase` at module import time (got None). Move the access inside the function body.

**Endpoint name changed:**
After Blueprint registration, endpoint names become `blueprint_name.function_name` (e.g., `auth.login` instead of `login`). If any frontend JS calls `url_for('login')`, update to `url_for('auth.login')`. Check `redirect(url_for(...))` calls in route code.
