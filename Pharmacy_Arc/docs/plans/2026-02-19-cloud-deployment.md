# Cloud Deployment (Railway) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy the Farmacia Carimas Flask app to Railway so it runs 24/7 in the cloud and is accessible from any browser, with all data syncing through the existing Supabase connection.

**Architecture:** The Flask app is pushed to GitHub (repo already exists: `mtsmyassin/Card-Sales`). Railway pulls from that repo, runs gunicorn as the production WSGI server, and injects all secrets as environment variables. No `.env` file ships to the server — all config comes from Railway's dashboard.

**Tech Stack:** Flask 3, Gunicorn, Supabase 2.28, Python 3.11, Railway (PaaS), GitHub

---

## Pre-flight context

| Item | Value |
|---|---|
| Project root | `C:\Users\mtsmy\Card-Sales\Pharmacy_Arc\` |
| GitHub remote | `https://github.com/mtsmyassin/Card-Sales.git` (branch: `main`) |
| Current PORT env var | `FLASK_PORT=5013` in `.env` — Railway will inject its own `PORT` |
| Supabase URL/KEY | Already in `.env` — must be pasted into Railway dashboard |
| Emergency accounts | `super` and `admin` hashes already in `.env` |
| Python | 3.11.9 |

---

### Task 1: Create `.gitignore`

**Why:** There is currently NO `.gitignore`. The `.env` file (containing Supabase keys and bcrypt hashes) would be pushed to GitHub. This is a critical security risk.

**Files:**
- Create: `C:\Users\mtsmy\Card-Sales\Pharmacy_Arc\.gitignore`

**Step 1: Create the file**

```
# Secrets — never commit
.env

# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python

# Virtual environment
.venv/
venv/
env/

# Build artifacts
build/
dist/
*.spec
*.egg-info/

# Logs and data
*.log
offline_queue.json

# OS
desktop.ini
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
```

**Step 2: Verify `.env` is not already tracked by git**

```bash
cd C:\Users\mtsmy\Card-Sales\Pharmacy_Arc
git ls-files .env
```

Expected output: *(empty — meaning .env is not tracked)*

If `.env` IS listed, run:
```bash
git rm --cached .env
```

**Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore to protect secrets and exclude venv"
```

---

### Task 2: Update `requirements.txt`

**Why:** `requirements.txt` still lists `supabase==2.3.0` (broken). We already upgraded to `2.28.0` locally. Gunicorn (production server) is missing. Railway will install from this file.

**Files:**
- Modify: `C:\Users\mtsmy\Card-Sales\Pharmacy_Arc\requirements.txt`

**Step 1: Freeze the current working venv**

```bash
cd C:\Users\mtsmy\Card-Sales\Pharmacy_Arc
.venv\Scripts\pip freeze > requirements.txt
```

**Step 2: Add gunicorn (not in venv yet since it's Windows)**

Open `requirements.txt` and add this line at the top:
```
gunicorn==23.0.0
```

**Step 3: Verify the file contains the right supabase version**

```bash
grep supabase requirements.txt
```

Expected: `supabase==2.28.0`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: update requirements to supabase 2.28 and add gunicorn"
```

---

### Task 3: Create `runtime.txt`

**Why:** Tells Railway which Python version to use.

**Files:**
- Create: `C:\Users\mtsmy\Card-Sales\Pharmacy_Arc\runtime.txt`

**Step 1: Create the file**

```
python-3.11.9
```

**Step 2: Commit**

```bash
git add runtime.txt
git commit -m "chore: pin Python 3.11.9 for Railway deployment"
```

---

### Task 4: Create `Procfile`

**Why:** Tells Railway how to start the app using gunicorn (not the dev server).

**Files:**
- Create: `C:\Users\mtsmy\Card-Sales\Pharmacy_Arc\Procfile`

**Step 1: Create the file**

```
web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

**Step 2: Commit**

```bash
git add Procfile
git commit -m "chore: add Procfile for Railway/gunicorn deployment"
```

---

### Task 5: Fix `app.py` for cloud production

Three problems in `app.py` that break cloud deployment:

1. **PORT**: reads `FLASK_PORT` but Railway injects `PORT` — app won't bind on the right port
2. **Host binding**: `app.run(port=PORT)` binds to `127.0.0.1` only — unreachable from outside
3. **Browser auto-open**: `Timer(1.5, lambda: webbrowser.open(...))` will crash on a headless server
4. **`supabase` undefined**: if Supabase init fails, `supabase` is never set to `None`, causing `NameError` on non-emergency logins

**Files:**
- Modify: `C:\Users\mtsmy\Card-Sales\Pharmacy_Arc\app.py`

**Step 1: Fix PORT to respect Railway's env var**

Find line 75:
```python
PORT = Config.PORT
```

Replace with:
```python
# Railway (and most PaaS) inject $PORT — fall back to FLASK_PORT for local dev
PORT = int(os.getenv('PORT', str(Config.PORT)))
```

**Step 2: Add `supabase = None` fallback**

Find lines 123-128:
```python
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Successfully connected to Supabase")
except Exception as e:
    logger.critical(f"Cloud Client Init Failed: {e}")
    print(f"CRITICAL ERROR: Cloud Client Init Failed. {e}")
```

Replace with:
```python
supabase = None
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Successfully connected to Supabase")
except Exception as e:
    logger.critical(f"Cloud Client Init Failed: {e}")
    print(f"CRITICAL ERROR: Cloud Client Init Failed. {e}")
```

**Step 3: Fix `app.run` to bind to all interfaces and guard browser open**

Find lines 1616-1618:
```python
if __name__ == '__main__':
    Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(port=PORT)
```

Replace with:
```python
if __name__ == '__main__':
    # Only open browser when running locally (not on a cloud server)
    import os as _os
    if not _os.getenv('RAILWAY_ENVIRONMENT') and not _os.getenv('RENDER'):
        Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host='0.0.0.0', port=PORT)
```

**Step 4: Commit**

```bash
git add app.py
git commit -m "fix: bind to 0.0.0.0, use Railway PORT, guard browser open, fix supabase=None"
```

---

### Task 6: Push to GitHub

**Step 1: Push all commits**

```bash
cd C:\Users\mtsmy\Card-Sales\Pharmacy_Arc
git push origin main
```

**Step 2: Verify on GitHub**

Open `https://github.com/mtsmyassin/Card-Sales` and confirm:
- `.env` is NOT visible in the file list
- `Procfile`, `runtime.txt`, and updated `requirements.txt` are present

---

### Task 7: Deploy on Railway

**Step 1: Create Railway account**

Go to `https://railway.app` → Sign up with GitHub (same account as the repo).

**Step 2: Create a new project**

- Click **"New Project"**
- Choose **"Deploy from GitHub repo"**
- Select `mtsmyassin/Card-Sales`
- Railway will detect the `Procfile` and start building

**Step 3: Set the root directory**

The repo has the app inside `Pharmacy_Arc/`, not at the root. In Railway project settings:
- Go to **Settings → Source**
- Set **Root Directory** to `Pharmacy_Arc`

**Step 4: Wait for first build**

Railway will install dependencies from `requirements.txt` and try to start. The first deploy will FAIL (missing env vars) — that's expected. Proceed to Task 8.

---

### Task 8: Set environment variables on Railway

In Railway project → **Variables** tab, add ALL of the following (copy values from local `.env`):

| Variable | Value |
|---|---|
| `FLASK_SECRET_KEY` | *(generate a new one: `python -c "import secrets; print(secrets.token_hex(32))"`)* |
| `SUPABASE_URL` | `https://nnvksawtfthbrcijwbpk.supabase.co` |
| `SUPABASE_KEY` | *(the long JWT from .env)* |
| `EMERGENCY_ADMIN_SUPER` | `super:$2b$12$KaxXYGm...` *(full value from .env)* |
| `EMERGENCY_ADMIN_BASIC` | `admin:$2b$12$.AtHIXZ...` *(full value from .env)* |
| `SESSION_TIMEOUT_MINUTES` | `30` |
| `MAX_LOGIN_ATTEMPTS` | `5` |
| `LOCKOUT_DURATION_MINUTES` | `15` |
| `REQUIRE_HTTPS` | `true` |
| `FLASK_DEBUG` | `false` |
| `LOG_LEVEL` | `INFO` |

**NOTE:** Do NOT set `FLASK_PORT` or `PORT` — Railway manages the port automatically.

After adding variables, Railway will automatically redeploy.

---

### Task 9: Get the public URL and test

**Step 1: Get the URL**

In Railway → **Settings → Networking** → click **"Generate Domain"**. You'll get a URL like `https://card-sales-production.up.railway.app`.

**Step 2: Test login**

Open the URL in any browser → login with `admin` / `92789278`.

**Step 3: Test from a different device**

Open the URL on your phone or another PC — confirms it works from anywhere.

**Step 4: Update the desktop batch file**

Once the cloud URL is confirmed working, the local `.bat` is only needed as a backup. Optionally update it to just open the cloud URL:

```bat
start https://your-railway-url.up.railway.app
```

---

## Cost

Railway **Hobby plan** = $5/month flat. Covers this app with room to spare. No sleep, no cold starts. First month free with $5 credit.

## Security notes after going live

- Enable **REQUIRE_HTTPS=true** (already in Task 8) — Railway always serves HTTPS
- Consider adding a custom domain via Railway → Networking → Custom Domain
- The `.env` file stays LOCAL only — never pushed to GitHub
