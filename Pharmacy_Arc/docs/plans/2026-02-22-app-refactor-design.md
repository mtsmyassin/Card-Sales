# Design: app.py God-File Refactor

**Date:** 2026-02-22
**Status:** Approved
**Scope:** Pharmacy_Arc — Flask pharmacy sales auditor

---

## Problem

`app.py` is 3019 lines. It contains Flask app factory, middleware, Supabase init, inline HTML templates (LOGIN_UI, MAIN_UI ~1000 lines), validation helpers, offline queue, auth decorator, all route handlers (auth/audits/users/z-reports/telegram/diagnostics), and the APScheduler. This makes it hard to read, test individual domains in isolation, or onboard new contributors.

---

## Goals

1. app.py becomes a ~100-line pure factory
2. Routes split into Flask Blueprints by domain
3. Inline HTML extracted to `templates/login.html` and `templates/main.html`
4. Shared state (supabase clients, csrf, auth decorator) accessible without circular imports
5. All 135 currently-passing tests remain green after refactor

---

## File Structure

```
Pharmacy_Arc/
├── app.py                  (~100 lines — factory only)
├── extensions.py           (shared state: supabase, supabase_admin, csrf, password_hasher, login_tracker, EMERGENCY_ACCOUNTS)
│
├── helpers/
│   ├── __init__.py
│   ├── auth_utils.py       (require_auth decorator, _can_access_photo)
│   ├── validation.py       (validate_audit_entry, validate_user_data)
│   ├── offline_queue.py    (save_to_queue, load_queue, clear_queue, get_queue_path, OFFLINE_QUEUE_MAX_SIZE)
│   └── scheduler.py        (_send_eod_reminders, APScheduler init function)
│
├── routes/
│   ├── __init__.py
│   ├── main.py             (Blueprint "main": index, favicon)
│   ├── auth.py             (Blueprint "auth": login, logout, csrf_token, enforce_session_timeout)
│   ├── audits.py           (Blueprint "audits": save, sync, update, delete, list, _send_variance_alert)
│   ├── users.py            (Blueprint "users": list_users, save_user, delete_user)
│   ├── zreports.py         (Blueprint "zreports": lock, unlock, approve, reject, reopen, amend, history, audit-log, unlock-timed-out + helpers)
│   ├── telegram.py         (Blueprint "telegram": webhook, zreport_image, photos, signed_url, delete_photo)
│   └── diagnostics.py      (Blueprint "diagnostics": /api/diagnostics)
│
├── templates/
│   ├── login.html          (extracted from LOGIN_UI string)
│   └── main.html           (extracted from MAIN_UI string)
│
├── config.py               (unchanged)
├── audit_log.py            (unchanged)
├── security.py             (unchanged)
├── telegram_bot.py         (unchanged)
├── ocr.py                  (unchanged)
└── gunicorn.conf.py        (unchanged)
```

---

## Import Chain (no circular imports)

```
extensions.py   → flask_wtf.csrf, security (no project-internal imports)
helpers/*.py    → flask, extensions, config, audit_log
routes/*.py     → flask, extensions, helpers/*, config, audit_log
app.py          → flask, extensions, routes/*, config, helpers.scheduler
```

---

## Key Design Decisions

### 1. Shared State via extensions.py

`extensions.py` holds module-level attributes initialized to `None`:

```python
# extensions.py
from flask_wtf.csrf import CSRFProtect
from security import PasswordHasher, LoginAttemptTracker

csrf = CSRFProtect()
supabase = None
supabase_admin = None
EMERGENCY_ACCOUNTS: dict = {}
password_hasher = PasswordHasher()
login_tracker = LoginAttemptTracker(...)
```

`app.py` (factory) populates supabase clients after `create_client()`:
```python
import extensions
extensions.supabase = _init_supabase(url, key, "anon")
extensions.supabase_admin = _init_supabase(url, svc_key, "admin")
```

Routes access shared state as module attributes (not destructured):
```python
import extensions
db = extensions.supabase_admin or extensions.supabase
```

This avoids circular imports because `extensions.py` imports nothing from the project.

### 2. require_auth in helpers/auth_utils.py

```python
# helpers/auth_utils.py
from functools import wraps
from flask import session, request, jsonify
import logging

def require_auth(allowed_roles=None):
    ...  # same implementation, no app dependency
```

Routes import: `from helpers.auth_utils import require_auth`

### 3. Templates

`render_template_string(MAIN_UI if session.get('logged_in') else LOGIN_UI)` becomes:
```python
from flask import render_template, session
template = 'main.html' if session.get('logged_in') else 'login.html'
return render_template(template, logo=logo_data, pending=has_pending)
```

The HTML content is identical — just moved to files. Flask finds them automatically in `templates/`.

### 4. Blueprint URL Prefixes

| Blueprint | Prefix |
|-----------|--------|
| main | (none) |
| auth | (none — `/api/login`, `/api/logout` keep their paths) |
| audits | (none — `/api/save`, `/api/list` keep their paths) |
| users | (none — `/api/users/...` keep their paths) |
| zreports | (none — `/api/z-reports/...` keep their paths) |
| telegram | (none — `/api/telegram/...` keep their paths) |
| diagnostics | (none) |

No URL changes — zero impact on frontend JS or Telegram webhook registration.

### 5. enforce_session_timeout

Currently registered on `app` directly. After refactor, registered in `auth.py` blueprint using `bp.before_app_request` (fires for all routes, not just the auth blueprint).

### 6. set_security_headers after_request

Moves to `app.py` factory, registered on `app` after blueprints are registered.

### 7. Tests

Existing tests (`tests/`) import `app` as the entry point — this continues to work because `app.py` still exists and `create_app()` returns the Flask app. The test `_load_app()` helper calls `importlib.reload(app_module)` which triggers the factory. No test changes needed.

---

## app.py After Refactor (~100 lines)

```python
import os, time, hmac, io, json, sys, base64, re, webbrowser, logging
from datetime import datetime, timedelta, timezone
from flask import Flask
from config import Config
import extensions
from helpers.scheduler import init_scheduler

def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = Config.SECRET_KEY
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=Config.SESSION_TIMEOUT_MINUTES)
    app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken']
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Init extensions
    extensions.csrf.init_app(app)
    extensions.supabase = _init_supabase(Config.SUPABASE_URL, Config.SUPABASE_KEY, "anon")
    if Config.SUPABASE_SERVICE_KEY:
        extensions.supabase_admin = _init_supabase(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY, "admin")
    extensions.EMERGENCY_ACCOUNTS = Config.load_emergency_accounts()
    extensions.login_tracker.configure_db(extensions.supabase_admin or extensions.supabase)

    # Register blueprints
    from routes.main import bp as main_bp
    from routes.auth import bp as auth_bp
    from routes.audits import bp as audits_bp
    from routes.users import bp as users_bp
    from routes.zreports import bp as zreports_bp
    from routes.telegram import bp as telegram_bp
    from routes.diagnostics import bp as diag_bp
    for blueprint in [main_bp, auth_bp, audits_bp, users_bp, zreports_bp, telegram_bp, diag_bp]:
        app.register_blueprint(blueprint)

    # App-wide hooks and error handlers
    _register_middleware(app)
    init_scheduler(app)
    return app

app = create_app()  # module-level for gunicorn: gunicorn app:app
```

---

## Risk Mitigation

- **Test suite stays green**: No URL changes, no auth logic changes, same `app` module entry point
- **One blueprint at a time**: Implementation plan extracts one blueprint per step, running tests after each
- **Templates verified visually**: `render_template()` output must match current `render_template_string()` output pixel-for-pixel
- **Git worktree**: All work done on an isolated branch, merged to main only after full test pass

---

## Out of Scope

- No changes to HTML/JS content in templates (pure extraction, no edits)
- No changes to telegram_bot.py, ocr.py, security.py, audit_log.py, config.py
- No new features or route changes
- No changes to Supabase schema
