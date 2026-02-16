# Detailed Runbook
## Pharmacy Sales Tracker - Complete Testing & Operations Manual

**Audience:** QA testers, developers, system administrators  
**Purpose:** Step-by-step instructions for setup, testing, and troubleshooting

---

## ⚡ FASTEST RUN (Copy/Paste Commands)

```bash
# Clone repo
git clone https://github.com/mtsmyassin/Card-Sales.git
cd Card-Sales/Pharmacy_Arc

# Setup environment
cp .env.example .env
# EDIT .env WITH YOUR SUPABASE CREDENTIALS

# Install dependencies
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run application
python app.py

# Open in browser: http://127.0.0.1:5013
# Login: super / password
```

---

## 📋 A. Full Prerequisites & Version Checks

### Required Software

| Component | Minimum Version | Recommended | Check Command |
|-----------|----------------|-------------|---------------|
| Python | 3.8 | 3.11+ | `python --version` |
| pip | 20.0+ | Latest | `pip --version` |
| Git | 2.0+ | Latest | `git --version` |
| Node.js (optional) | 18.0 | 20+ LTS | `node --version` |
| npm (optional) | 9.0+ | Latest | `npm --version` |

### Version Check Commands & Expected Output

**Python:**
```bash
python --version
# or
python3 --version
```
**Expected:** `Python 3.11.5` (or higher)

**pip:**
```bash
pip --version
# or
pip3 --version
```
**Expected:** `pip 23.2.1 from /usr/lib/python3.11/site-packages/pip (python 3.11)`

**Git:**
```bash
git --version
```
**Expected:** `git version 2.39.0` (or higher)

**Node.js (for E2E tests):**
```bash
node --version
```
**Expected:** `v20.10.0` (or v18+)

---

## 🧹 B. Clean Setup Process

### Step 1: Clone Repository

**Windows PowerShell:**
```powershell
git clone https://github.com/mtsmyassin/Card-Sales.git
cd Card-Sales
```

**macOS/Linux Bash:**
```bash
git clone https://github.com/mtsmyassin/Card-Sales.git
cd Card-Sales
```

**Verify:**
```bash
ls -la
# Should see: Pharmacy_Arc/, docs/, tests/, package.json, etc.
```

---

### Step 2: Create Python Virtual Environment

**Why:** Isolates dependencies from system Python

**Windows:**
```powershell
cd Pharmacy_Arc
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux:**
```bash
cd Pharmacy_Arc
python3 -m venv venv
source venv/bin/activate
```

**Verify (should show venv prefix):**
```bash
which python  # macOS/Linux
# or
where python  # Windows

# Expected: /path/to/Card-Sales/Pharmacy_Arc/venv/bin/python
```

---

### Step 3: Install Python Dependencies

**With venv activated:**
```bash
pip install -r requirements.txt
```

**Expected packages installed:**
- flask==3.0.0
- supabase==2.3.0
- python-dotenv==1.0.0
- bcrypt==4.1.2
- pydantic==2.5.3
- psycopg2-binary==2.9.9

**Verify installation:**
```bash
pip list
```

**Check specific package:**
```bash
python -c "import flask; print(flask.__version__)"
# Expected: 3.0.0
```

---

### Step 4: Install Node Dependencies (Optional - for E2E tests)

**From repository root (not Pharmacy_Arc):**
```bash
cd ..  # Back to Card-Sales root
npm install
```

**Install Playwright browsers:**
```bash
npx playwright install chromium
```

**Expected output:**
```
Downloading Chromium 120.0.6099.28...
...
Chromium 120.0.6099.28 downloaded to /home/user/.cache/ms-playwright/chromium-1108
```

---

## 🔐 C. Environment Variables - Complete Reference

### Environment Variable Table

| Variable | Purpose | Format/Example | Required | Where to Get |
|----------|---------|----------------|----------|--------------|
| `FLASK_SECRET_KEY` | Session encryption key | 64-char hex string | ✅ Yes | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FLASK_PORT` | HTTP port for Flask | Integer (1024-65535) | No | Default: 5013 |
| `FLASK_DEBUG` | Enable debug mode | `true` or `false` | No | Use `false` in production |
| `SUPABASE_URL` | Supabase project URL | `https://xxxxx.supabase.co` | ✅ Yes | Supabase Dashboard → Settings → API |
| `SUPABASE_KEY` | Supabase anon/public key | `eyJhbGci...` (JWT) | ✅ Yes | Supabase Dashboard → Settings → API |
| `EMERGENCY_ADMIN_SUPER` | Super admin emergency account | `username:bcrypt_hash` | No | Pre-configured or generate |
| `EMERGENCY_ADMIN_BASIC` | Basic admin emergency account | `username:bcrypt_hash` | No | Pre-configured or generate |
| `SESSION_TIMEOUT_MINUTES` | Session expiration time | Integer (5-1440) | No | Default: 30 |
| `MAX_LOGIN_ATTEMPTS` | Failed login threshold | Integer (1-50) | No | Default: 5 |
| `LOCKOUT_DURATION_MINUTES` | Account lockout duration | Integer (1-60) | No | Default: 15 |
| `REQUIRE_HTTPS` | Force HTTPS redirect | `true` or `false` | No | Use `true` in production |
| `LOG_LEVEL` | Logging verbosity | `DEBUG`, `INFO`, `WARNING`, `ERROR` | No | Default: INFO |
| `LOG_FILE` | Log file path | Filename or path | No | Default: `pharmacy_app.log` |

---

### Creating .env File

**Method 1: Copy template**
```bash
cd Pharmacy_Arc
cp .env.example .env
```

**Method 2: Create from scratch**
```bash
cat > .env << 'EOF'
FLASK_SECRET_KEY=your_64_character_hex_string_here
FLASK_PORT=5013
FLASK_DEBUG=false

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key_here

EMERGENCY_ADMIN_SUPER=super:$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5NU7hlZiOXE4u
EMERGENCY_ADMIN_BASIC=admin:$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5NU7hlZiOXE4u

SESSION_TIMEOUT_MINUTES=30
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_DURATION_MINUTES=15
REQUIRE_HTTPS=false

LOG_LEVEL=INFO
LOG_FILE=pharmacy_app.log
EOF
```

**Then edit with your actual values:**
```bash
nano .env
# or: code .env (VS Code)
# or: vim .env
```

---

### Generating SECRET_KEY

**Method 1: Python one-liner**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Method 2: OpenSSL (if available)**
```bash
openssl rand -hex 32
```

**Expected output format:**
```
a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890
```

**Use this entire string in .env:**
```ini
FLASK_SECRET_KEY=a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890
```

---

### Emergency Admin Account Passwords

**Pre-configured hashes in .env.example:**

| Username | Password | Hash (bcrypt) |
|----------|----------|---------------|
| `super` | `password` | `$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5NU7hlZiOXE4u` |
| `admin` | `password` | `$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5NU7hlZiOXE4u` |

**To generate your own:**
```python
python -c "from security import PasswordHasher; p = PasswordHasher(); print(p.hash_password('YourPasswordHere'))"
```

---

## 🗄️ D. Supabase Setup Verification

### Database Tables Required

**1. Users Table**
```sql
create table users (
  username text primary key,
  password text not null,
  role text not null,
  store text
);
```

**2. Audits Table**
```sql
create table audits (
  id bigint generated by default as identity primary key,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  date text not null,
  store text not null,
  reg text not null,
  staff text,
  gross numeric default 0,
  net numeric default 0,
  variance numeric default 0,
  payload jsonb
);
```

**3. Indexes**
```sql
create index idx_audits_date on audits(date);
create index idx_audits_store on audits(store);
```

---

### Verify Tables Exist

**In Supabase SQL Editor:**
```sql
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public';
```

**Expected output:**
```
 table_name 
------------
 users
 audits
```

---

### Check Table Structure

**Users table:**
```sql
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'users';
```

**Expected:**
```
 column_name | data_type 
-------------+-----------
 username    | text
 password    | text
 role        | text
 store       | text
```

**Audits table:**
```sql
\d audits  -- PostgreSQL command

-- Or:
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'audits';
```

---

### Test Connectivity from Application

**Create test script:**
```bash
cat > test_connection.py << 'EOF'
import sys
sys.path.insert(0, '.')
from config import Config
from supabase import create_client

try:
    supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    result = supabase.table("users").select("count", count="exact").execute()
    print(f"✅ Connected! Users table has {result.count} rows")
except Exception as e:
    print(f"❌ Connection failed: {e}")
EOF

python test_connection.py
```

**Expected output:**
```
✅ Connected! Users table has 1 rows
```

---

## 🚀 E. Start/Stop Commands & Logs

### Starting the Application

**Standard run:**
```bash
cd Pharmacy_Arc
python app.py
```

**Run in background (Linux/macOS):**
```bash
nohup python app.py > app.log 2>&1 &
echo $! > app.pid
```

**Run in background (Windows PowerShell):**
```powershell
Start-Process python -ArgumentList "app.py" -RedirectStandardOutput "app.log" -RedirectStandardError "app_error.log" -WindowStyle Hidden
```

---

### Expected Startup Output

```
--- LAUNCHING v40-SECURE ON PORT 5013 ---
Successfully connected to Supabase
Loaded 2 emergency admin account(s)
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment.
 * Running on http://127.0.0.1:5013
Press CTRL+C to quit
```

---

### Stopping the Application

**Interactive mode:** Press `Ctrl+C`

**Background process (Linux/macOS):**
```bash
# If you saved PID
kill $(cat app.pid)

# Or find and kill
lsof -ti:5013 | xargs kill -9
```

**Background process (Windows):**
```powershell
# Find process
Get-Process python | Where-Object {$_.MainWindowTitle -eq ""}

# Kill by port
netstat -ano | findstr :5013
taskkill /PID <PID> /F
```

---

### Log Locations

| Log Type | Location | Purpose |
|----------|----------|---------|
| Application log | `Pharmacy_Arc/pharmacy_app.log` | Main application events |
| Audit log | `Pharmacy_Arc/audit_log.jsonl` | Security audit trail (append-only) |
| Lockout state | `Pharmacy_Arc/lockout_state.json` | Brute-force protection state |
| Offline queue | `Pharmacy_Arc/offline_queue.json` | Pending sync operations |
| Playwright logs | `test-results/` | E2E test outputs |
| Playwright reports | `playwright-report/` | HTML test reports |

---

### Viewing Logs

**Tail application log (real-time):**
```bash
tail -f Pharmacy_Arc/pharmacy_app.log
```

**View audit log:**
```bash
cat Pharmacy_Arc/audit_log.jsonl | jq .
```

**Check log level:**
```bash
grep "level" Pharmacy_Arc/pharmacy_app.log | head -5
```

---

## 🧪 F. Manual Test Plan

### Test Suite 1: Authentication & Authorization

#### Test 1.1: Successful Login (Emergency Admin)

**Steps:**
1. Navigate to http://127.0.0.1:5013
2. Enter username: `super`
3. Enter password: `password`
4. Click "Login"

**Expected Results:**
- ✅ Redirects to dashboard
- ✅ Username "super" appears in top-right
- ✅ All tabs visible (Audit Entry, Calendar, Command Center, History, Users)
- ✅ Log shows: `INFO - User super logged in successfully`

---

#### Test 1.2: Failed Login

**Steps:**
1. Navigate to login page
2. Enter username: `super`
3. Enter password: `wrongpassword`
4. Click "Login"

**Expected Results:**
- ❌ Stays on login page
- ❌ Alert: "Invalid credentials"
- ✅ Log shows: `WARNING - Failed login attempt for user: super`

---

#### Test 1.3: Account Lockout

**Steps:**
1. Attempt login with wrong password 5 times
2. Try to login with correct password on 6th attempt

**Expected Results:**
- ❌ Alert: "Account locked for 15 minutes"
- ✅ File created: `lockout_state.json`
- ✅ Log shows: `WARNING - Account super is locked out`

**Unlock:**
```bash
rm lockout_state.json
# Restart app or wait 15 minutes
```

---

#### Test 1.4: Session Timeout

**Steps:**
1. Login successfully
2. Wait 31 minutes (SESSION_TIMEOUT_MINUTES=30)
3. Try to navigate to another tab or refresh page

**Expected Results:**
- ❌ Redirects to login page
- ✅ Session expired

---

#### Test 1.5: Logout

**Steps:**
1. Login successfully
2. Click "Log Out" button

**Expected Results:**
- ✅ Redirects to login page
- ✅ Cannot access dashboard without re-login
- ✅ Log shows: `INFO - User super logged out`

---

### Test Suite 2: RBAC (Role-Based Access Control)

#### Test 2.1: Staff Role Restrictions

**Setup:** Create staff user or login as `test_staff`

**Steps:**
1. Login as staff user
2. Check visible tabs

**Expected Results:**
- ✅ Can see: Audit Entry, History
- ❌ Cannot see: Calendar, Command Center, Users
- ❌ Edit buttons don't appear in History tab (only print)

---

#### Test 2.2: Manager Role Permissions

**Setup:** Login as `test_manager` or manager account

**Expected Results:**
- ✅ Can see: Audit Entry, Calendar, History
- ❌ Cannot see: Command Center, Users
- ✅ Can edit records in History tab

---

#### Test 2.3: Admin Role Permissions

**Setup:** Login as admin

**Expected Results:**
- ✅ Can see: All tabs (Audit Entry, Calendar, Command Center, History, Users)
- ✅ Full CRUD permissions on all resources

---

### Test Suite 3: Edit Flow

#### Test 3.1: Navigate to Edit View

**Steps:**
1. Login as admin/manager
2. Go to "History" tab
3. Create a test entry if list is empty:
   - Go to "Audit Entry"
   - Fill: Date=today, Reg=Reg1, Staff=TestUser, Cash=100
   - Click "Finalize & Upload"
   - Return to "History"
4. Click ✏️ (edit) button on any entry

**Expected Results:**
- ✅ App switches to "Audit Entry" tab
- ✅ Form fields pre-populated with entry data
- ✅ Button text changes to "Update Record" (orange color)
- ✅ "Cancel" button appears
- ✅ Hidden field `editId` contains the record ID

**Verify in DOM (F12 console):**
```javascript
document.getElementById('editId').value
// Should return: "123" (some number)

document.getElementById('saveBtn').innerText
// Should return: "Update Record"
```

---

#### Test 3.2: Save Edited Entry

**Steps:**
1. After entering edit mode (Test 3.1)
2. Change "Cash Sales" from 100 to 150
3. Click "Update Record"

**Expected Results:**
- ✅ Alert: "Saved!"
- ✅ App returns to "History" tab
- ✅ Entry shows updated value (150 instead of 100)
- ✅ Network tab shows POST to `/api/update` with 200 status
- ✅ Log shows: `INFO - Audit entry updated by admin`

**Verify in Supabase:**
```sql
SELECT * FROM audits WHERE id = <your_entry_id>;
-- Should show updated cash value in payload
```

---

#### Test 3.3: Cancel Edit

**Steps:**
1. Enter edit mode
2. Change some values
3. Click "Cancel" button

**Expected Results:**
- ✅ Form clears/resets
- ✅ Button returns to "Finalize & Upload" (blue)
- ✅ "Cancel" button disappears
- ✅ Hidden field `editId` is empty

---

### Test Suite 4: Users Tab Auto-Sync

#### Test 4.1: Auto-Fetch on Tab Open

**Steps:**
1. Login as admin
2. Start on "Audit Entry" tab
3. Click "Users" tab

**Expected Results:**
- ✅ User table loads **automatically** (no manual refresh)
- ✅ Network tab shows GET to `/api/users/list` fired immediately
- ✅ Table displays existing users

**Verify timing (F12 Network tab):**
- Request to `/api/users/list` should fire within 500ms of tab click

---

#### Test 4.2: Auto-Refresh After User Creation

**Steps:**
1. On "Users" tab
2. Fill form:
   - Username: `tempuser`
   - Password: `TempPass123!`
   - Role: Staff
   - Store: Carimas #1
3. Click "Create User"

**Expected Results:**
- ✅ Alert: "Saved"
- ✅ User table refreshes **automatically**
- ✅ New user `tempuser` appears in table
- ✅ Form clears
- ✅ Button remains "Create User"

**Verify (no manual refresh needed!):**
```javascript
// In console, check table content
document.getElementById('userTable').innerText.includes('tempuser')
// Should return: true
```

---

#### Test 4.3: Auto-Refresh After User Deletion

**Steps:**
1. Find user `tempuser` in table
2. Click 🗑️ (delete) button
3. Confirm deletion

**Expected Results:**
- ✅ User disappears from table **automatically**
- ✅ No manual refresh needed
- ✅ Network shows POST to `/api/users/delete` with 200

---

#### Test 4.4: Edit User

**Steps:**
1. Click ✏️ (edit) button next to a user
2. Form pre-populates
3. Change role from "staff" to "manager"
4. Click "Update User"

**Expected Results:**
- ✅ Alert: "Saved"
- ✅ Table refreshes automatically
- ✅ User's role updated in table

---

### Test Suite 5: Sync Endpoint

#### Test 5.1: Sync Requires Auth

**Steps:**
1. Logout
2. Try to POST to `/api/sync` directly:
   ```bash
   curl -X POST http://127.0.0.1:5013/api/sync
   ```

**Expected Results:**
- ❌ Returns 401 Unauthorized
- ✅ Error: "Authentication required"

---

#### Test 5.2: Offline Queue Sync

**Setup:**
1. Stop Flask app
2. Create offline queue file:
   ```bash
   echo '[{"date":"2026-01-15","store":"Test","reg":"Reg1","staff":"TestUser","gross":100,"net":95,"variance":0,"payload":{}}]' > offline_queue.json
   ```
3. Restart Flask app
4. Login and navigate to any page

**Expected:**
- ✅ "⚠️ Sync" button appears in navigation
- ✅ Click it to trigger sync
- ✅ Alert: "Synced 1 record(s)"
- ✅ Queue file clears
- ✅ Data appears in Supabase

---

### Test Suite 6: Audit Logs

#### Test 6.1: Audit Log File Exists

**Check:**
```bash
ls -la Pharmacy_Arc/audit_log.jsonl
```

**Expected:**
```
-rw-r--r-- 1 user user 1234 Feb 16 10:30 audit_log.jsonl
```

---

#### Test 6.2: Audit Log Integrity

**Run integrity check:**
```bash
cd Pharmacy_Arc
python -c "from audit_log import get_audit_logger; logger = get_audit_logger(); valid, errors = logger.verify_integrity(); print('Valid' if valid else 'Invalid'); print(errors if errors else 'No errors')"
```

**Expected output:**
```
Valid
No errors
```

---

#### Test 6.3: Audit Log Entries

**View recent entries:**
```bash
tail -5 Pharmacy_Arc/audit_log.jsonl | jq .
```

**Expected format:**
```json
{
  "timestamp": "2026-02-16T10:30:45.123456",
  "action": "LOGIN_SUCCESS",
  "actor": "super",
  "role": "super_admin",
  "entity_type": "SESSION",
  "success": true,
  "context": {"ip": "127.0.0.1"},
  "hash": "abc123..."
}
```

---

## 🔧 G. Troubleshooting Matrix

### Symptom → Root Cause → Fix

| Symptom | Root Cause | Fix |
|---------|------------|-----|
| **Port already in use** | Flask running in another process | Kill process: `lsof -ti:5013 \| xargs kill -9` (Linux/Mac) or `netstat -ano \| findstr :5013` then `taskkill /PID <PID> /F` (Windows) |
| **ModuleNotFoundError: flask** | Dependencies not installed | `pip install -r requirements.txt` |
| **CRITICAL ERROR: Cloud Client Init Failed** | Wrong Supabase credentials | Check `SUPABASE_URL` and `SUPABASE_KEY` in `.env` |
| **Invalid credentials** on login | Emergency account not configured or wrong password | Check `.env` has `EMERGENCY_ADMIN_SUPER` set, or try `super`/`password` |
| **Account locked** | Too many failed login attempts | Delete `lockout_state.json` or wait 15 minutes |
| **Table doesn't exist** | Database not initialized | Run SQL schema in Supabase |
| **Session expires immediately** | SECRET_KEY too short or not set | Generate new 64-char key with `python -c "import secrets; print(secrets.token_hex(32))"` |
| **Users tab empty** | Auto-fetch not working | Check browser console for errors; verify `/api/users/list` endpoint |
| **Edit button doesn't navigate** | JavaScript error | Check browser console; clear cache and refresh |
| **No edit button in History** | Logged in as staff role | Staff can only print, not edit. Login as manager/admin |
| **Can't see Users tab** | Not admin role | Only admin/super_admin can access Users tab |
| **Audit log integrity fails** | Log file corrupted or tampered | Restore from backup or investigate security incident |
| **Offline queue not syncing** | Network issue or auth expired | Check logs; re-login; verify Supabase reachable |

---

### Common Environment Issues

**Python not found:**
```bash
# Check if python or python3
which python python3

# Use the one that works
python3 app.py
```

**pip not found:**
```bash
# Use python -m pip instead
python -m pip install -r requirements.txt
```

**Virtual environment not activating:**
```bash
# Windows
.\venv\Scripts\activate

# If execution policy blocks, run as admin:
Set-ExecutionPolicy RemoteSigned

# Linux/Mac
source venv/bin/activate

# If permission denied:
chmod +x venv/bin/activate
```

---

## 🔄 H. Reset Procedures

### Reset Admin Password

**Method 1: Via emergency account**
1. Login as `super`
2. Go to Users tab
3. Edit the admin user
4. Set new password
5. Click Update

**Method 2: Direct SQL**
```sql
-- Generate hash for "newpassword123"
-- In Python:
-- from security import PasswordHasher
-- print(PasswordHasher().hash_password('newpassword123'))

UPDATE users 
SET password = '$2b$12$...' -- paste your hash here
WHERE username = 'admin';
```

---

### Clear Login Lockouts

**Remove lockout state:**
```bash
cd Pharmacy_Arc
rm lockout_state.json
```

**Restart application** (lockout state will be fresh)

---

### Wipe Test Data Safely

**Remove test users:**
```bash
cd ..  # Back to repo root
python seed-test-data.py cleanup
```

**Or manually in SQL:**
```sql
DELETE FROM users 
WHERE username IN ('test_admin', 'test_manager', 'test_staff', 'playwright_user', 'tempuser');
```

**Remove test audit entries:**
```sql
DELETE FROM audits 
WHERE staff = 'TestUser' 
OR store = 'Test';
```

**⚠️ WARNING: Be careful with DELETE. Consider using WHERE clauses to target specific test data only.**

---

### Reset Database Completely

**⚠️ DESTRUCTIVE - This deletes all data:**

```sql
DROP TABLE audits CASCADE;
DROP TABLE users CASCADE;

-- Then recreate (see Section D for CREATE statements)
```

---

### Clear All Application State

```bash
cd Pharmacy_Arc

# Remove logs
rm -f pharmacy_app.log
rm -f audit_log.jsonl

# Remove state files
rm -f lockout_state.json
rm -f lockout_state.json.tmp
rm -f offline_queue.json

# Restart app
python app.py
```

---

## ✅ Complete Test Execution Checklist

**Use this checklist for full manual verification:**

### Prerequisites
- [ ] Python 3.8+ installed and verified
- [ ] Git installed and verified
- [ ] Supabase project created
- [ ] Database tables created
- [ ] `.env` file configured with valid credentials

### Setup
- [ ] Repository cloned
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Application starts without errors
- [ ] Can access http://127.0.0.1:5013

### Authentication Tests
- [ ] Can login with emergency admin (`super`/`password`)
- [ ] Failed login shows error message
- [ ] Account locks after 5 failed attempts
- [ ] Lockout clears after 15 minutes or manual reset
- [ ] Logout works and clears session

### RBAC Tests
- [ ] Staff role: Can only see Audit Entry + History
- [ ] Manager role: Can see Audit Entry + Calendar + History
- [ ] Admin role: Can see all tabs including Users

### Edit Flow Tests
- [ ] Click edit button navigates to Audit Entry tab
- [ ] Form pre-populates with correct data
- [ ] Button changes to "Update Record" (orange)
- [ ] Can save changes successfully
- [ ] List refreshes after save
- [ ] Cancel button resets form

### Users Tab Tests
- [ ] Users tab auto-loads data on open
- [ ] Create user: table refreshes automatically
- [ ] Delete user: table refreshes automatically
- [ ] Edit user: table refreshes automatically
- [ ] No manual refresh needed

### Sync Tests
- [ ] Sync endpoint requires authentication
- [ ] Offline queue syncs when back online
- [ ] Sync button appears when queue has items

### Audit Log Tests
- [ ] Audit log file exists and is append-only
- [ ] Log integrity verification passes
- [ ] Entries have correct format (JSON lines)

### Error Handling
- [ ] Invalid credentials handled gracefully
- [ ] Network errors don't crash app
- [ ] Input validation prevents bad data

**All checked? System is fully functional! ✅**

---

## 📚 Additional Resources

**For more details:**
- Beginner guide: `/docs/BEGINNER_QUICKSTART.md`
- Operations guide: `/docs/EXPERT_OPERATIONS_GUIDE.md`
- E2E testing: `/E2E_TESTING_README.md`
- Security fixes: `/Pharmacy_Arc/SECURITY_FIXES_APPLIED.md`

**Need help?** Check existing documentation in `/Pharmacy_Arc/` for specific topics.
