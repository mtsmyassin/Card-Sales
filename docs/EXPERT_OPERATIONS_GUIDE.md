# Expert Operations Guide
## Pharmacy Sales Tracker - Enterprise Operations & Security

**Audience:** DevOps engineers, security engineers, system architects  
**Purpose:** Production deployment, security hardening, CI/CD, monitoring, and operational procedures

---

## ⚡ FASTEST PRODUCTION DEPLOYMENT (1 Minute)

```bash
# 1. Clone and setup
git clone https://github.com/mtsmyassin/Card-Sales.git
cd Card-Sales/Pharmacy_Arc

# 2. Production .env
cp .env.example .env
# EDIT: Set FLASK_DEBUG=false, REQUIRE_HTTPS=true, rotate SECRET_KEY

# 3. Install behind reverse proxy
# nginx config:
# proxy_pass http://127.0.0.1:5013;
# proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
# proxy_set_header X-Forwarded-Proto $scheme;

# 4. Run with production WSGI server
pip install gunicorn
gunicorn -w 4 -b 127.0.0.1:5013 app:app

# 5. Setup systemd service (see Section D)
```

---

## 🏗️ A. Architecture Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Browser                        │
│              (Vanilla JS Single-Page Application)            │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (nginx/Apache)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Reverse Proxy (nginx)                    │
│            - SSL/TLS termination                             │
│            - Request forwarding                              │
│            - Security headers                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP (localhost only)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Flask Application                        │
│                     (app.py on port 5013)                    │
│                                                              │
│  Components:                                                 │
│  ├─ Authentication (bcrypt password hashing)                 │
│  ├─ Session Management (Flask sessions)                     │
│  ├─ RBAC (Role-Based Access Control)                        │
│  ├─ Audit Logging (append-only JSONL)                       │
│  ├─ Brute-Force Protection (LoginAttemptTracker)            │
│  ├─ Input Validation (validate_audit_entry, validate_user_data)│
│  └─ Offline Queue (local JSON for network resilience)       │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ REST API (HTTPS)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Supabase (PostgreSQL)                    │
│                                                              │
│  Tables:                                                     │
│  ├─ users (username, password, role, store)                 │
│  └─ audits (sales records with JSONB payload)               │
└─────────────────────────────────────────────────────────────┘
```

---

### Trust Boundaries

1. **Client → Reverse Proxy:** HTTPS, public internet
2. **Reverse Proxy → Flask:** HTTP, localhost only (trusted)
3. **Flask → Supabase:** HTTPS, authenticated with anon key
4. **Admin → Supabase Direct:** (Optional) Admin tools, service_role key

**Key Security Layers:**
- TLS encryption (client ↔ proxy)
- Session cookies (HttpOnly, SameSite, Secure in prod)
- RBAC enforcement (server-side on every request)
- Input validation (before DB operations)
- Audit logging (tamper-evident hash chain)

---

### Data Flow: User Login

```
1. User submits credentials
   ↓
2. Flask: Check brute-force lockout
   ↓
3. Flask: Query Supabase users table
   ↓
4. Flask: bcrypt.verify(password, stored_hash)
   ↓
5. Flask: Create session (set cookie)
   ↓
6. Audit Log: Record LOGIN_SUCCESS
   ↓
7. Return dashboard HTML
```

---

### Data Flow: Edit Audit Entry

```
1. User clicks Edit button (client-side)
   ↓
2. JavaScript: Fetch record data, populate form
   ↓
3. User modifies field, clicks "Update Record"
   ↓
4. POST /api/update with JSON payload
   ↓
5. Flask: @require_auth() checks session
   ↓
6. Flask: RBAC check (staff cannot edit)
   ↓
7. Flask: validate_audit_entry() checks input
   ↓
8. Flask: Supabase UPDATE query
   ↓
9. Audit Log: Record UPDATE action
   ↓
10. Return 200 OK
   ↓
11. Client: Refresh list, show success message
```

---

## 🔒 B. Security Posture

### B1. Session Management

**Current Implementation:**

| Setting | Value | Location |
|---------|-------|----------|
| Cookie Name | `session` (Flask default) | Automatic |
| HttpOnly | `True` (always) | `app.py:44` |
| SameSite | `Lax` (always) | `app.py:45` |
| Secure | `True` if `REQUIRE_HTTPS=true` | `app.py:60` |
| Session Timeout | 30 minutes (configurable) | `.env:SESSION_TIMEOUT_MINUTES` |
| Secret Key | 64-char hex (required) | `.env:FLASK_SECRET_KEY` |

**Production Hardening:**

1. **Set REQUIRE_HTTPS=true in .env**
   ```ini
   REQUIRE_HTTPS=true
   ```

2. **Use reverse proxy with HTTPS**
   ```nginx
   # nginx config
   server {
       listen 443 ssl http2;
       ssl_certificate /etc/ssl/certs/cert.pem;
       ssl_certificate_key /etc/ssl/private/key.pem;
       
       location / {
           proxy_pass http://127.0.0.1:5013;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

3. **Trust proxy headers (if behind load balancer)**
   ```python
   # In app.py, after Flask initialization:
   from werkzeug.middleware.proxy_fix import ProxyFix
   app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
   ```

---

### B2. CSRF Protection

**Current Status:** Not implemented (SPA design mitigates some risk)

**Why it's not critical:**
- Application is a Single-Page App (SPA)
- No traditional form submissions
- All API calls use JavaScript fetch with JSON
- Session cookies use SameSite=Lax

**To Add CSRF Protection (recommended for production):**

1. **Install Flask-WTF:**
   ```bash
   pip install Flask-WTF
   ```

2. **Add to requirements.txt:**
   ```
   Flask-WTF==1.2.1
   ```

3. **Configure in app.py:**
   ```python
   from flask_wtf.csrf import CSRFProtect
   
   csrf = CSRFProtect(app)
   csrf.init_app(app)
   
   # Exempt API endpoints if needed
   @csrf.exempt
   @app.route('/api/login', methods=['POST'])
   def login():
       ...
   ```

4. **Client-side (add to HTML template):**
   ```javascript
   // Include CSRF token in all fetch requests
   const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
   
   fetch('/api/save', {
       method: 'POST',
       headers: {
           'Content-Type': 'application/json',
           'X-CSRFToken': csrfToken
       },
       body: JSON.stringify(data)
   });
   ```

**Verification:**
```bash
# Test that requests without token are rejected
curl -X POST http://localhost:5013/api/save -d '{"date":"2026-01-01"}' -H "Content-Type: application/json"
# Should return 400 CSRF token missing
```

---

### B3. Rate Limiting

**Current Status:** Brute-force protection on login only

**Recommendation:** Add global rate limiting with Flask-Limiter

**Implementation:**

1. **Install:**
   ```bash
   pip install Flask-Limiter
   ```

2. **Add to requirements.txt:**
   ```
   Flask-Limiter==3.5.0
   ```

3. **Configure in app.py:**
   ```python
   from flask_limiter import Limiter
   from flask_limiter.util import get_remote_address
   
   limiter = Limiter(
       app=app,
       key_func=get_remote_address,
       default_limits=["200 per day", "50 per hour"],
       storage_uri="memory://"  # Use Redis in production
   )
   
   # Apply to specific endpoints
   @app.route('/api/list')
   @require_auth()
   @limiter.limit("100 per hour")
   def list_audits():
       ...
   
   @app.route('/api/users/list')
   @require_auth()
   @limiter.limit("50 per hour")
   def list_users():
       ...
   ```

**Production Rate Limit Recommendations:**

| Endpoint | Limit | Reason |
|----------|-------|--------|
| `/api/login` | 5 per 15 min (existing) | Brute-force protection |
| `/api/list` | 100 per hour | Prevent enumeration |
| `/api/save` | 50 per hour | Prevent spam |
| `/api/update` | 30 per hour | Limit abuse |
| `/api/delete` | 20 per hour | Sensitive operation |
| `/api/users/*` | 50 per hour | Admin operations |

**Verification:**
```bash
# Test rate limit
for i in {1..60}; do curl http://localhost:5013/api/list; done
# Should eventually return 429 Too Many Requests
```

---

### B4. Secret Rotation Procedure

**⚠️ CRITICAL: Supabase keys exposed in git history**

**Issue:** Old backup files (`old.app.py.py`, `app_v41_fixed.py`) contained hardcoded Supabase credentials and were committed to git (commit `d88378b`).

**Rotation Steps:**

1. **Rotate Supabase Keys (IMMEDIATELY)**
   - Go to Supabase Dashboard → Settings → API
   - Click "Generate new anon key"
   - Update `.env` file with new key
   - Restart application

2. **Rotate Flask SECRET_KEY**
   ```bash
   # Generate new key
   python -c "import secrets; print(secrets.token_hex(32))"
   
   # Update .env
   FLASK_SECRET_KEY=<new_key>
   
   # Restart app (invalidates all sessions)
   ```

3. **Rotate Emergency Admin Passwords**
   ```python
   # Generate new hash
   from security import PasswordHasher
   p = PasswordHasher()
   print(p.hash_password('new_secure_password_here'))
   
   # Update .env
   EMERGENCY_ADMIN_SUPER=super:<new_bcrypt_hash>
   ```

4. **Audit git history (if private repo)**
   ```bash
   # Search for exposed secrets
   git log --all --full-history --source -- "**/old.app.py.py"
   git log --all --full-history --source -- "**/app_v41_fixed.py"
   ```

5. **Consider BFG Repo-Cleaner (if public repo)**
   ```bash
   # WARNING: Rewrites history
   bfg --delete-files "old.app.py.py"
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   git push --force
   ```

**Prevention:**
- Never commit `.env` files (already in `.gitignore`)
- Use `.env.example` templates only
- Run `git secrets` pre-commit hook
- Regular security audits

---

### B5. Input Validation Status

**Implemented (as of v41-VALIDATED):**

| Endpoint | Validation | Status |
|----------|------------|--------|
| `/api/save` | `validate_audit_entry()` | ✅ |
| `/api/update` | `validate_audit_entry()` | ✅ |
| `/api/users/save` | `validate_user_data()` | ✅ |
| `/api/users/delete` | Username format, self-deletion check | ✅ |
| `/api/get_logo` | Whitelist validation | ✅ |

**Validation Rules:**
- Date format: YYYY-MM-DD regex
- Numeric ranges: gross (0-1M), variance (±100K)
- String lengths: username (3-50), staff (max 100)
- Enum validation: roles, stores
- SQL injection: Safe (Supabase ORM parameterized queries)

**Test Validation:**
```bash
# Valid request
curl -X POST http://localhost:5013/api/save \
  -H "Cookie: session=..." \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-01-15","reg":"Reg1","staff":"Test","gross":100,"net":95,"variance":0}'
# Returns: 200 OK

# Invalid date
curl -X POST http://localhost:5013/api/save \
  -H "Cookie: session=..." \
  -H "Content-Type: application/json" \
  -d '{"date":"99-99-9999","reg":"Reg1","staff":"Test","gross":100,"net":95,"variance":0}'
# Returns: 400 "Invalid date format. Use YYYY-MM-DD"

# Negative gross
curl -X POST http://localhost:5013/api/save \
  -H "Cookie: session=..." \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-01-15","reg":"Reg1","staff":"Test","gross":-1000,"net":95,"variance":0}'
# Returns: 400 "Gross must be between 0 and 1,000,000"
```

---

## 🤖 C. CI/CD Integration

### C1. GitHub Actions Workflows

**Location:** `.github/workflows/e2e-tests.yml`

**Triggers:**
- Push to `main` branch
- Push to feature branches
- Pull requests

**Workflow Steps:**
1. Checkout code
2. Setup Python 3.11
3. Setup Node.js 18
4. Install Python dependencies
5. Install Playwright browsers
6. Create test `.env` file
7. Seed test data
8. Run Playwright E2E tests
9. Upload test artifacts
10. Cleanup test data

---

### C2. Required CI Secrets

**Configure in GitHub Repository Settings → Secrets:**

| Secret Name | Purpose | How to Get |
|-------------|---------|------------|
| `TEST_SUPABASE_URL` | Test database URL | Create separate Supabase project for testing |
| `TEST_SUPABASE_KEY` | Test database key | Supabase → Settings → API → anon key |
| `TEST_FLASK_SECRET_KEY` | Session secret for tests | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |

**⚠️ Never use production credentials in CI!**

---

### C3. Running Tests in CI

**Unit Tests (Python):**
```bash
cd Pharmacy_Arc
python -m pytest test_features.py test_security.py -v
```

**Expected output:**
```
test_features.py::test_edit_flow PASSED
test_features.py::test_users_sync PASSED
test_security.py::test_brute_force PASSED
...
22 passed in 5.2s
```

**E2E Tests (Playwright):**
```bash
cd ..  # Repository root
npm test
```

**Expected output:**
```
Running 5 tests using 1 worker
✓ tests/edit-flow.spec.js:4:1 › should navigate to edit view (2.5s)
✓ tests/edit-flow.spec.js:58:1 › should cancel edit (1.8s)
✓ tests/users-tab.spec.js:4:1 › should auto-fetch users (3.1s)
✓ tests/users-tab.spec.js:89:1 › should show users immediately (1.5s)
✓ tests/users-tab.spec.js:120:1 › should update user (2.2s)

5 passed (11.1s)
```

---

### C4. Test Reports & Artifacts

**Playwright HTML Report:**
- Location: `playwright-report/index.html`
- Uploaded as GitHub Actions artifact (30-day retention)
- View command: `npm run test:report`

**Test Results:**
- Location: `test-results/`
- Contains: screenshots (on failure), videos (on failure), traces
- Uploaded as GitHub Actions artifact

**Access in GitHub:**
1. Go to repository → Actions
2. Click on workflow run
3. Scroll to "Artifacts" section
4. Download `playwright-report.zip`

---

## 🚀 D. Production Deployment

### D1. Production Environment Variables

**Required Changes from Development:**

```ini
# .env for PRODUCTION

# Security (CRITICAL)
FLASK_SECRET_KEY=<rotate this - 64 char hex>
FLASK_DEBUG=false
REQUIRE_HTTPS=true

# Supabase (use production project)
SUPABASE_URL=https://your-prod-project.supabase.co
SUPABASE_KEY=<production anon key>

# Emergency accounts (rotate passwords)
EMERGENCY_ADMIN_SUPER=super:<new_bcrypt_hash>
EMERGENCY_ADMIN_BASIC=admin:<new_bcrypt_hash>

# Security settings
SESSION_TIMEOUT_MINUTES=30
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_DURATION_MINUTES=15

# Logging (reduce verbosity)
LOG_LEVEL=WARNING
LOG_FILE=/var/log/pharmacy/app.log
```

**Verification:**
```bash
# Check debug mode is OFF
python -c "from config import Config; print('DEBUG' if Config.DEBUG else 'PRODUCTION MODE ✓')"

# Check HTTPS is required
python -c "from config import Config; print('HTTPS REQUIRED ✓' if Config.REQUIRE_HTTPS else 'WARNING: HTTP ALLOWED')"
```

---

### D2. WSGI Server (Gunicorn)

**Why:** Flask development server is not production-ready

**Install Gunicorn:**
```bash
pip install gunicorn
echo "gunicorn==21.2.0" >> requirements.txt
```

**Run:**
```bash
cd Pharmacy_Arc
gunicorn -w 4 -b 127.0.0.1:5013 --access-logfile - --error-logfile - app:app
```

**Gunicorn Options:**
- `-w 4`: 4 worker processes (adjust based on CPU cores: 2-4 × cores)
- `-b 127.0.0.1:5013`: Bind to localhost only (reverse proxy will handle external)
- `--access-logfile -`: Log requests to stdout
- `--error-logfile -`: Log errors to stdout
- `app:app`: Module name : app instance

**Production Command (recommended):**
```bash
gunicorn \
  -w 4 \
  -b 127.0.0.1:5013 \
  --timeout 30 \
  --keep-alive 5 \
  --log-level warning \
  --access-logfile /var/log/pharmacy/access.log \
  --error-logfile /var/log/pharmacy/error.log \
  --pid /var/run/pharmacy/app.pid \
  app:app
```

---

### D3. Systemd Service

**Create service file:**
```bash
sudo nano /etc/systemd/system/pharmacy-tracker.service
```

**Content:**
```ini
[Unit]
Description=Pharmacy Sales Tracker
After=network.target

[Service]
Type=notify
User=pharmacy
Group=pharmacy
WorkingDirectory=/opt/pharmacy-tracker/Pharmacy_Arc
Environment="PATH=/opt/pharmacy-tracker/venv/bin"
ExecStart=/opt/pharmacy-tracker/venv/bin/gunicorn \
  -w 4 \
  -b 127.0.0.1:5013 \
  --timeout 30 \
  --log-level warning \
  --access-logfile /var/log/pharmacy/access.log \
  --error-logfile /var/log/pharmacy/error.log \
  --pid /var/run/pharmacy/app.pid \
  app:app

ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
KillSignal=SIGQUIT
PrivateTmp=true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable pharmacy-tracker
sudo systemctl start pharmacy-tracker
```

**Check status:**
```bash
sudo systemctl status pharmacy-tracker
```

**View logs:**
```bash
sudo journalctl -u pharmacy-tracker -f
```

**Control commands:**
```bash
sudo systemctl start pharmacy-tracker
sudo systemctl stop pharmacy-tracker
sudo systemctl restart pharmacy-tracker
sudo systemctl reload pharmacy-tracker  # Graceful reload
```

---

### D4. Reverse Proxy Configuration

**Nginx (recommended):**

```nginx
# /etc/nginx/sites-available/pharmacy-tracker

upstream pharmacy_backend {
    server 127.0.0.1:5013;
    keepalive 32;
}

server {
    listen 80;
    server_name pharmacy.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name pharmacy.example.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/pharmacy.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pharmacy.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:;" always;

    # Logging
    access_log /var/log/nginx/pharmacy-access.log;
    error_log /var/log/nginx/pharmacy-error.log;

    # Client body size (for uploads)
    client_max_body_size 10M;

    # Proxy settings
    location / {
        proxy_pass http://pharmacy_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Static files (if served separately)
    location /static/ {
        alias /opt/pharmacy-tracker/Pharmacy_Arc/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

**Enable site:**
```bash
sudo ln -s /etc/nginx/sites-available/pharmacy-tracker /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

**Apache (alternative):**

```apache
# /etc/apache2/sites-available/pharmacy-tracker.conf

<VirtualHost *:80>
    ServerName pharmacy.example.com
    Redirect permanent / https://pharmacy.example.com/
</VirtualHost>

<VirtualHost *:443>
    ServerName pharmacy.example.com

    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/pharmacy.example.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/pharmacy.example.com/privkey.pem

    # Security Headers
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
    Header always set X-Frame-Options "DENY"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-XSS-Protection "1; mode=block"

    # Proxy
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:5013/
    ProxyPassReverse / http://127.0.0.1:5013/

    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"

    ErrorLog ${APACHE_LOG_DIR}/pharmacy-error.log
    CustomLog ${APACHE_LOG_DIR}/pharmacy-access.log combined
</VirtualHost>
```

**Enable:**
```bash
sudo a2enmod ssl proxy proxy_http headers
sudo a2ensite pharmacy-tracker
sudo apache2ctl configtest
sudo systemctl reload apache2
```

---

## 💾 E. Backups & Restore

### E1. What to Back Up

| Data | Location | Frequency | Retention |
|------|----------|-----------|-----------|
| **Supabase Database** | Cloud (automatic) | Daily | 7 days (free tier) |
| **Audit Logs** | `Pharmacy_Arc/audit_log.jsonl` | Daily | 90 days |
| **Application Logs** | `Pharmacy_Arc/pharmacy_app.log` | Weekly | 30 days |
| **Configuration** | `Pharmacy_Arc/.env` | On change | Keep 3 versions |
| **Lockout State** | `Pharmacy_Arc/lockout_state.json` | Not needed | N/A (ephemeral) |
| **Offline Queue** | `Pharmacy_Arc/offline_queue.json` | Not needed | N/A (syncs to DB) |

---

### E2. Supabase Database Backup

**Automatic Backups:**
- Supabase provides daily automatic backups (7-day retention on free tier)
- Access: Supabase Dashboard → Database → Backups

**Manual Backup:**
```bash
# Export full database
pg_dump "postgresql://postgres:[password]@db.[project].supabase.co:5432/postgres" > backup_$(date +%Y%m%d).sql

# Or via Supabase CLI
supabase db dump > backup.sql
```

**Backup Script:**
```bash
#!/bin/bash
# backup-db.sh

BACKUP_DIR="/var/backups/pharmacy"
DATE=$(date +%Y%m%d_%H%M%S)
DB_URL="postgresql://postgres:${DB_PASSWORD}@db.${PROJECT}.supabase.co:5432/postgres"

mkdir -p $BACKUP_DIR

# Dump database
pg_dump "$DB_URL" | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# Keep only last 30 days
find $BACKUP_DIR -name "db_*.sql.gz" -mtime +30 -delete

echo "Backup completed: db_$DATE.sql.gz"
```

**Schedule with cron:**
```bash
crontab -e

# Daily at 2 AM
0 2 * * * /opt/pharmacy-tracker/backup-db.sh >> /var/log/pharmacy/backup.log 2>&1
```

---

### E3. Audit Log Backup

**Why:** Audit logs are tamper-evident and critical for security forensics

**Backup Script:**
```bash
#!/bin/bash
# backup-audit-log.sh

SOURCE="/opt/pharmacy-tracker/Pharmacy_Arc/audit_log.jsonl"
BACKUP_DIR="/var/backups/pharmacy/audit-logs"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Copy and compress
cp "$SOURCE" "$BACKUP_DIR/audit_log_$DATE.jsonl"
gzip "$BACKUP_DIR/audit_log_$DATE.jsonl"

# Keep 90 days
find $BACKUP_DIR -name "audit_log_*.jsonl.gz" -mtime +90 -delete

echo "Audit log backed up: audit_log_$DATE.jsonl.gz"
```

**Verify integrity before backup:**
```python
#!/usr/bin/env python3
# verify-audit-log.py

import sys
sys.path.insert(0, '/opt/pharmacy-tracker/Pharmacy_Arc')

from audit_log import get_audit_logger

logger = get_audit_logger()
valid, errors = logger.verify_integrity()

if valid:
    print("✅ Audit log integrity verified")
    sys.exit(0)
else:
    print("❌ Audit log integrity FAILED")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
```

**Daily cron:**
```bash
# Verify then backup at 3 AM
0 3 * * * /opt/pharmacy-tracker/verify-audit-log.py && /opt/pharmacy-tracker/backup-audit-log.sh >> /var/log/pharmacy/backup.log 2>&1
```

---

### E4. Restore Procedures

**Restore Database:**
```bash
# Stop application
sudo systemctl stop pharmacy-tracker

# Restore from backup
gunzip -c /var/backups/pharmacy/db_20260215.sql.gz | psql "$DB_URL"

# Or via Supabase Dashboard → Database → Backups → Restore

# Restart application
sudo systemctl start pharmacy-tracker
```

**Restore Audit Log:**
```bash
gunzip -c /var/backups/pharmacy/audit-logs/audit_log_20260215.jsonl.gz > /opt/pharmacy-tracker/Pharmacy_Arc/audit_log.jsonl

# Verify integrity
python /opt/pharmacy-tracker/verify-audit-log.py
```

**Test Restore (dry run):**
```bash
# Create test database
createdb pharmacy_test

# Restore backup to test DB
gunzip -c backup.sql.gz | psql postgresql://localhost/pharmacy_test

# Run queries to verify data
psql pharmacy_test -c "SELECT COUNT(*) FROM users;"
psql pharmacy_test -c "SELECT COUNT(*) FROM audits;"

# Drop test DB
dropdb pharmacy_test
```

---

## 📊 F. Monitoring & Observability

### F1. Log Format & Locations

**Application Log:**
- **Location:** `Pharmacy_Arc/pharmacy_app.log` (or `/var/log/pharmacy/app.log` in production)
- **Format:** `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- **Rotation:** Manually or via logrotate

**Example entries:**
```
2026-02-16 10:30:45,123 - __main__ - INFO - User super logged in successfully
2026-02-16 10:31:02,456 - __main__ - WARNING - Failed login attempt for user: admin
2026-02-16 10:31:15,789 - __main__ - ERROR - Error in save endpoint: ValueError
```

**Audit Log:**
- **Location:** `Pharmacy_Arc/audit_log.jsonl`
- **Format:** JSON Lines (one JSON object per line)
- **Append-only:** Never modified, only appended
- **Integrity:** Hash-chained to detect tampering

**Example entries:**
```json
{"timestamp":"2026-02-16T10:30:45.123456","action":"LOGIN_SUCCESS","actor":"super","role":"super_admin","entity_type":"SESSION","success":true,"context":{"ip":"127.0.0.1"},"hash":"abc123..."}
{"timestamp":"2026-02-16T10:31:02.456789","action":"CREATE","actor":"admin","role":"admin","entity_type":"AUDIT_ENTRY","entity_id":"123","after":{"date":"2026-02-15"},"success":true,"context":{"ip":"127.0.0.1"},"hash":"def456..."}
```

---

### F2. Log Rotation

**Create logrotate config:**
```bash
sudo nano /etc/logrotate.d/pharmacy-tracker
```

**Content:**
```
/var/log/pharmacy/app.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 pharmacy pharmacy
    sharedscripts
    postrotate
        systemctl reload pharmacy-tracker > /dev/null 2>&1 || true
    endscript
}

/var/log/pharmacy/audit_log.jsonl {
    weekly
    rotate 52
    compress
    delaycompress
    notifempty
    create 0600 pharmacy pharmacy
    nocreate
    # Audit log should never be rotated - use backup instead
    # This is here for reference only
}
```

**Test:**
```bash
sudo logrotate -d /etc/logrotate.d/pharmacy-tracker
```

---

### F3. Health Check Endpoint

**Add to app.py (if not exists):**
```python
@app.route('/health')
def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Check database connection
        supabase.table("users").select("count", count="exact").execute()
        
        return jsonify({
            "status": "healthy",
            "version": VERSION,
            "timestamp": datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 503
```

**Monitor with:**
```bash
# Simple check
curl http://127.0.0.1:5013/health

# Check from monitoring system
curl -f http://127.0.0.1:5013/health || echo "Service down"
```

**Nagios/Icinga check:**
```bash
#!/bin/bash
# check_pharmacy.sh

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5013/health)

if [ "$RESPONSE" = "200" ]; then
    echo "OK - Service healthy"
    exit 0
else
    echo "CRITICAL - Service returned $RESPONSE"
    exit 2
fi
```

---

### F4. Metrics to Monitor

| Metric | Method | Alert Threshold |
|--------|--------|-----------------|
| **Uptime** | systemctl status | < 99.5% |
| **Response time** | Nginx logs / APM | > 2 seconds p95 |
| **Error rate** | Application logs | > 1% of requests |
| **Failed logins** | Audit log | > 10 per hour |
| **Database connections** | Supabase dashboard | > 80% of limit |
| **Disk space** | df -h | > 80% used |
| **Memory usage** | free -m | > 90% used |
| **CPU usage** | top / htop | > 80% sustained |
| **Audit log integrity** | verify script | Any failure |

---

### F5. Recommended Monitoring Tools

**Application Performance Monitoring (APM):**
- New Relic (Python agent)
- Datadog (Python integration)
- Scout APM

**Log Aggregation:**
- ELK Stack (Elasticsearch, Logstash, Kibana)
- Loki + Grafana
- CloudWatch Logs (AWS)

**Infrastructure Monitoring:**
- Prometheus + Grafana
- Nagios / Icinga
- Zabbix

**Uptime Monitoring:**
- UptimeRobot
- Pingdom
- StatusCake

---

## ⚡ G. Performance & Load Testing

### G1. Seed Large Dataset

**Create 100k audit entries:**
```python
#!/usr/bin/env python3
# seed-large-dataset.py

import sys
from datetime import datetime, timedelta
sys.path.insert(0, 'Pharmacy_Arc')

from config import Config
from supabase import create_client

supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)

# Generate 100k entries (100 per day for 1000 days)
start_date = datetime(2023, 1, 1)
stores = ['Carimas #1', 'Carimas #2', 'Carimas #3', 'Carimas #4', 'Carthage']

print("Generating 100,000 audit entries...")
batch = []
for day in range(1000):
    date = (start_date + timedelta(days=day)).strftime('%Y-%m-%d')
    for i in range(100):
        entry = {
            "date": date,
            "store": stores[i % len(stores)],
            "reg": f"Reg {(i % 3) + 1}",
            "staff": f"Staff{i % 10}",
            "gross": 1000 + (i * 10),
            "net": 950 + (i * 10),
            "variance": (i % 20) - 10,
            "payload": {"test": True}
        }
        batch.append(entry)
        
        if len(batch) >= 1000:
            supabase.table("audits").insert(batch).execute()
            print(f"Inserted {len(batch)} entries...")
            batch = []

if batch:
    supabase.table("audits").insert(batch).execute()
    print(f"Inserted {len(batch)} entries...")

print("✅ Complete!")
```

**Run:**
```bash
python seed-large-dataset.py
```

**Verify:**
```sql
SELECT COUNT(*) FROM audits;
-- Should return: 100000
```

---

### G2. Load Testing with Apache Bench

**Install:**
```bash
# Ubuntu/Debian
sudo apt install apache2-utils

# macOS
brew install ab
```

**Test login endpoint:**
```bash
ab -n 1000 -c 10 -p login.json -T application/json http://127.0.0.1:5013/api/login

# Where login.json contains:
echo '{"username":"test","password":"test"}' > login.json
```

**Test list endpoint (with session cookie):**
```bash
# Get session cookie first
curl -c cookies.txt -X POST http://127.0.0.1:5013/api/login -d '{"username":"super","password":"password"}' -H "Content-Type: application/json"

# Load test with cookie
ab -n 1000 -c 10 -C "session=..." http://127.0.0.1:5013/api/list
```

**Interpret results:**
```
Requests per second:    250.32 [#/sec] (mean)
Time per request:       39.949 [ms] (mean)
Time per request:       3.995 [ms] (mean, across all concurrent requests)
```

**Good performance:**
- RPS > 100 for read endpoints
- RPS > 50 for write endpoints
- p95 latency < 500ms

---

### G3. Stress Testing with Locust

**Install:**
```bash
pip install locust
```

**Create test file:**
```python
# locustfile.py
from locust import HttpUser, task, between

class PharmacyUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        # Login
        response = self.client.post("/api/login", json={
            "username": "test",
            "password": "test"
        })
        # Session cookie automatically handled
    
    @task(10)
    def view_list(self):
        self.client.get("/api/list")
    
    @task(5)
    def view_users(self):
        self.client.get("/api/users/list")
    
    @task(3)
    def create_entry(self):
        self.client.post("/api/save", json={
            "date": "2026-02-16",
            "reg": "Reg 1",
            "staff": "LoadTest",
            "gross": 1000,
            "net": 950,
            "variance": 5,
            "store": "Carimas #1"
        })
```

**Run:**
```bash
locust -f locustfile.py --host=http://127.0.0.1:5013

# Open web UI: http://localhost:8089
# Set users: 50, spawn rate: 10
# Start test
```

**Monitor during test:**
```bash
# CPU/memory
htop

# Logs
tail -f /var/log/pharmacy/app.log

# Database connections
# In Supabase dashboard
```

---

### G4. Database Query Optimization

**Check slow queries:**
```sql
-- In Supabase SQL Editor
SELECT query, calls, mean_exec_time, max_exec_time
FROM pg_stat_statements
WHERE query LIKE '%audits%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

**Add missing indexes:**
```sql
-- If queries on reg are slow
CREATE INDEX idx_audits_reg ON audits(reg);

-- If queries on staff are slow
CREATE INDEX idx_audits_staff ON audits(staff);

-- Composite index for common filters
CREATE INDEX idx_audits_date_store ON audits(date, store);
```

**Verify index usage:**
```sql
EXPLAIN ANALYZE
SELECT * FROM audits
WHERE date >= '2026-01-01' AND store = 'Carimas #1';

-- Should show "Index Scan" not "Seq Scan"
```

---

## 📋 Final Production Checklist

### Pre-Deployment
- [ ] Rotate all secrets (SECRET_KEY, Supabase keys, admin passwords)
- [ ] Set `FLASK_DEBUG=false`
- [ ] Set `REQUIRE_HTTPS=true`
- [ ] Configure reverse proxy (nginx/Apache) with SSL
- [ ] Set up systemd service
- [ ] Configure log rotation
- [ ] Set up automated backups (database + audit logs)
- [ ] Configure monitoring/alerting
- [ ] Load test with expected traffic
- [ ] Security scan (OWASP ZAP, etc.)

### Deployment
- [ ] Deploy code to production server
- [ ] Create production `.env` with secure values
- [ ] Run database migrations (if any)
- [ ] Start systemd service
- [ ] Verify health check endpoint
- [ ] Smoke test all critical flows
- [ ] Monitor logs for errors

### Post-Deployment
- [ ] Verify backups are running
- [ ] Check monitoring dashboards
- [ ] Review security logs (failed logins, etc.)
- [ ] Performance baseline (response times, RPS)
- [ ] Document any issues

### Weekly Maintenance
- [ ] Review application logs for errors
- [ ] Check audit log integrity
- [ ] Review backup status
- [ ] Monitor disk space
- [ ] Check for Supabase/Python security updates

### Monthly Maintenance
- [ ] Rotate secrets
- [ ] Security audit
- [ ] Performance review
- [ ] Backup restore test
- [ ] Update dependencies (if security patches available)

---

## 📚 Additional Resources

- Beginner guide: `/docs/BEGINNER_QUICKSTART.md`
- Testing manual: `/docs/DETAILED_RUNBOOK.md`
- E2E tests: `/E2E_TESTING_README.md`
- Security audit: `/Pharmacy_Arc/SECURITY_FIXES_APPLIED.md`
- Enterprise gap analysis: `/Pharmacy_Arc/ENTERPRISE_GAP_REPORT_FINAL.md`

**For issues:** Create GitHub issue with logs and error details
