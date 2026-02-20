# UI Redesign — Sidebar Layout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the flat horizontal-tab layout with a fixed dark-teal left sidebar and card-based content area that feels official, fast, and branded to Farmacia Carimas.

**Architecture:** All HTML/CSS lives inside the `MAIN_UI` string in `app.py` (starts line 1022). No separate template files. Changes are: (1) replace the CSS block, (2) replace the header+tabs HTML with a sidebar div, (3) wrap all `.view` divs in a `.main-content` div. Zero JS changes needed — the tab switcher already works by toggling `.active` on `id="tab-*"` elements and `.view` divs.

**Tech Stack:** Pure HTML/CSS embedded in Python string in `app.py`. Flask, no template engine (uses `render_template_string`).

---

## Critical context before starting

- File: `C:\Users\mtsmy\Card-Sales\Pharmacy_Arc\app.py`
- Always open with `encoding='utf-8'` — file contains non-ASCII characters
- Never use `sed` on Windows — use the Edit tool only
- The JS tab switcher does: `document.querySelectorAll('.view,.tab-btn').forEach(e=>e.classList.remove('active'))` — sidebar nav buttons MUST keep class `tab-btn` and ids `tab-dash`, `tab-calendar`, `tab-analytics`, `tab-logs`, `tab-users`
- Test locally: `PYTHONUTF8=1 .venv/Scripts/python.exe app.py` then open `http://127.0.0.1:5013`

---

### Task 1: Update CSS variables, body, and remove old header/tabs styles

**Files:**
- Modify: `app.py` lines 1027–1065

**What to replace:**

Find this exact block (lines 1027–1065):
```css
:root{--p:#0097b2;--bg:#f8fafc;--danger:#ef4444;--success:#047857;--txt:#1e293b;--warn:#f59e0b;}
*{box-sizing:border-box; font-family: 'Segoe UI', system-ui, sans-serif;}
body{
    background-color: var(--bg);
    margin:0; padding:15px; color:var(--txt);
    position: relative;
    min-height: 100vh;
}
```

Replace with:
```css
:root{--p:#0097b2;--sidebar:#00697d;--sidebar-dark:#00525f;--bg:#f0f4f8;--card:#ffffff;--danger:#ef4444;--success:#047857;--txt:#1e293b;--muted:#64748b;--warn:#f59e0b;}
*{box-sizing:border-box; font-family: 'Segoe UI', system-ui, sans-serif;}
body{background-color:var(--bg);margin:0;padding:0;color:var(--txt);min-height:100vh;display:flex;}
```

Then find:
```css
.header{
    background:rgba(255,255,255,0.85); backdrop-filter:blur(15px);
    padding:12px 25px; border-radius:12px;
    display:flex; justify-content:space-between; align-items:center;
    box-shadow:0 4px 20px -5px rgba(0,0,0,0.05); border:1px solid rgba(255,255,255,0.6);
    margin-bottom:20px;
}
.panel{
    background:rgba(255,255,255,0.85); backdrop-filter:blur(15px);
    padding:25px; border-radius:16px;
    box-shadow:0 10px 25px -5px rgba(0,0,0,0.05); border:1px solid rgba(255,255,255,0.5);
    height:100%;
}

.tabs{display:flex;gap:8px;margin-bottom:20px;}
.tab-btn{
    padding:10px 24px; background:rgba(255,255,255,0.5);
    border-radius:10px; cursor:pointer; border:1px solid transparent;
    transition:0.3s; color:#64748b; font-weight:700; font-size:13px;
}
.tab-btn:hover{background:white; color:var(--p);}
.tab-btn.active{
    background:white; color:var(--p); border-color:#e2e8f0;
    box-shadow:0 4px 6px -1px rgba(0,0,0,0.05); font-weight:800;
}
```

Replace with:
```css
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
.sidebar-logo img{max-width:120px;}
.sidebar-logo h2{
    margin:0; color:white; font-size:14px; font-weight:900;
    text-align:center; letter-spacing:0.3px; line-height:1.3;
}
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
```

**Step 2: Verify the file still has valid Python syntax**

```bash
cd C:\Users\mtsmy\Card-Sales\Pharmacy_Arc
PYTHONUTF8=1 .venv/Scripts/python.exe -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"
```

Expected: `OK`

**Step 3: Commit**
```bash
git add app.py
git commit -m "style: update CSS variables and add sidebar/main-content styles"
```

---

### Task 2: Replace section header styles for card look

**Files:**
- Modify: `app.py` — find and replace `.section` CSS rule (around line 1072)

Find:
```css
.section{font-size:12px;color:#64748b;text-transform:uppercase;margin:20px 0 10px;border-bottom:2px solid #e2e8f0;padding-bottom:5px;display:flex;justify-content:space-between;letter-spacing:1px;font-weight:900;}
```

Replace with:
```css
.section{font-size:11px;color:var(--sidebar);text-transform:uppercase;margin:24px 0 14px;padding-bottom:8px;border-bottom:2px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;letter-spacing:1.2px;font-weight:900;}
.section-badge{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;background:var(--sidebar);color:white;border-radius:50%;font-size:11px;font-weight:900;margin-right:8px;flex-shrink:0;}
```

Also find and replace the input/select styles:
```css
input,select{width:100%;padding:12px;border:1px solid #e2e8f0;border-radius:8px;margin-bottom:15px;color:#1e293b;background:rgba(255,255,255,0.9);font-weight:700;}
```

Replace with:
```css
input,select{width:100%;padding:11px 13px;border:1.5px solid #cbd5e1;border-radius:8px;margin-bottom:15px;color:#1e293b;background:#fff;font-weight:600;transition:border-color 0.2s,box-shadow 0.2s;}
input:focus,select:focus{outline:none;border-color:var(--p);box-shadow:0 0 0 3px rgba(0,151,178,0.12);}
```

Also find and replace `.btn-main`:
```css
.btn-main{background:var(--p);color:white;width:100%;padding:14px;border:none;border-radius:10px;cursor:pointer;font-size:15px;font-weight:800;}
```

Replace with:
```css
.btn-main{background:var(--p);color:white;padding:13px 32px;border:none;border-radius:10px;cursor:pointer;font-size:14px;font-weight:800;transition:background 0.2s;width:auto;}
.btn-main:hover{background:var(--sidebar);}
```

**Step 2: Verify syntax**
```bash
PYTHONUTF8=1 .venv/Scripts/python.exe -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"
```

**Step 3: Commit**
```bash
git add app.py
git commit -m "style: update section, input, and button styles for card look"
```

---

### Task 3: Replace header + tabs HTML with sidebar

**Files:**
- Modify: `app.py` lines 1164–1182

Find this exact HTML block:
```html
<div class="header">
    <div style="display:flex;align-items:center;gap:15px">
        <div><h1 style="margin:0;font-weight:900;color:#1e293b;font-size:24px;letter-spacing:-0.5px">Farmacia Carimas</h1></div>
        <button id="syncBtn" style="background:#f59e0b;color:white;border:none;padding:6px 12px;border-radius:6px;font-weight:bold;display:none">⚠️ Sync</button>
    </div>
    <div style="display:flex;gap:15px;align-items:center">
        <span id="userDisplay" style="color:var(--p);font-size:12px;font-weight:800;text-transform:uppercase"></span>
        <button onclick="app.logout()" style="padding:8px 16px;cursor:pointer;background:#ef4444;color:white;border:none;border-radius:8px;font-size:12px;font-weight:800">Log Out</button>
        <img id="appLogo" src="data:image/png;base64,{{logo}}" style="height:48px; opacity:1">
    </div>
</div>

<div class="tabs">
    <div id="tab-dash" class="tab-btn active" onclick="app.tab('dash')">Audit Entry</div>
    <div id="tab-calendar" class="tab-btn" onclick="app.tab('calendar')">Calendar</div>
    <div id="tab-analytics" class="tab-btn" onclick="app.tab('analytics')">Command Center</div>
    <div id="tab-logs" class="tab-btn" onclick="app.tab('logs')">History</div>
    <div id="tab-users" class="tab-btn" onclick="app.tab('users')">Users</div>
</div>
```

Replace with:
```html
<div class="sidebar">
    <div class="sidebar-logo">
        <img src="data:image/png;base64,{{logo}}" alt="Farmacia Carimas">
        <h2>Farmacia Carimas</h2>
    </div>
    <nav class="sidebar-nav">
        <div id="tab-dash" class="tab-btn active" onclick="app.tab('dash')"><span class="tab-icon">📋</span>Audit Entry</div>
        <div id="tab-calendar" class="tab-btn" onclick="app.tab('calendar')"><span class="tab-icon">📅</span>Calendar</div>
        <div id="tab-analytics" class="tab-btn" onclick="app.tab('analytics')"><span class="tab-icon">📊</span>Command Center</div>
        <div id="tab-logs" class="tab-btn" onclick="app.tab('logs')"><span class="tab-icon">📜</span>History</div>
        <div id="tab-users" class="tab-btn" onclick="app.tab('users')"><span class="tab-icon">👥</span>Users</div>
    </nav>
    <div class="sidebar-footer">
        <div class="sidebar-user" id="userDisplay"></div>
        <button id="syncBtn" style="background:#f59e0b;color:white;border:none;padding:6px 10px;border-radius:6px;font-weight:bold;font-size:12px;display:none;cursor:pointer">⚠️ Sync</button>
        <button onclick="app.logout()" style="padding:9px 14px;cursor:pointer;background:#ef4444;color:white;border:none;border-radius:8px;font-size:12px;font-weight:800;width:100%">Log Out</button>
    </div>
</div>
```

**Step 2: Verify syntax**
```bash
PYTHONUTF8=1 .venv/Scripts/python.exe -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"
```

**Step 3: Commit**
```bash
git add app.py
git commit -m "feat: replace header+tabs with dark teal sidebar"
```

---

### Task 4: Wrap all view divs in `.main-content`

**Files:**
- Modify: `app.py` — find the line right after the sidebar closing tag

The views start at the line after `</div>` (end of old tabs div, now end of sidebar div). Find this line:

```html
<div id="dash" class="view active">
```

Insert before it:
```html
<div class="main-content">
```

Then find the very last view div's closing tag. Look for the end of the users view — it ends with something like `</div>\n</div>` before the `<script>` tags. The closing structure near the end of the HTML (around line 1610) will look like:

```html
    </div><!-- end users view -->
</div><!-- this is the end of something -->
<script>
```

You need to add one more `</div>` before the `<script>` tag to close `.main-content`. Find the last `</div>` before `<script>` and add `</div>` after it:

Find:
```html
</div>
<script>
const app = {
```

Replace with:
```html
</div>
</div><!-- end .main-content -->
<script>
const app = {
```

**Step 2: Start app and visually verify layout**
```bash
PYTHONUTF8=1 .venv/Scripts/python.exe app.py
```
Open `http://127.0.0.1:5013` — you should see:
- Dark teal sidebar on the left with logo, nav links, user + logout
- Content area to the right with the audit form

**Step 3: Fix the save button row** — the Finalize & Upload button currently uses `width:100%` inline style. Find:
```html
<div style="display:flex;gap:10px;margin-top:20px"><button id="saveBtn" class="btn-main" onclick="app.save()">Finalize & Upload</button><button id="cancelBtn" class="btn-main" onclick="app.resetForm()" style="background:#64748b;display:none;">Cancel</button></div>
```

Replace with:
```html
<div style="display:flex;gap:12px;margin-top:24px;justify-content:flex-start"><button id="saveBtn" class="btn-main" onclick="app.save()">Finalize & Upload</button><button id="cancelBtn" class="btn-main" onclick="app.resetForm()" style="background:#64748b;display:none;">Cancel</button></div>
```

**Step 4: Verify syntax**
```bash
PYTHONUTF8=1 .venv/Scripts/python.exe -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"
```

**Step 5: Commit**
```bash
git add app.py
git commit -m "feat: wrap views in main-content div for sidebar layout"
```

---

### Task 5: Deploy to Railway and verify live

**Step 1: Push to GitHub**
```bash
cd C:\Users\mtsmy\Card-Sales\Pharmacy_Arc
git push origin main
```

**Step 2: Watch Railway deploy**
Go to `https://railway.app` → your project → Deployments tab. Wait for green checkmark.

**Step 3: Open live URL**
```
https://carimas.up.railway.app
```

**Step 4: Verify**
- [ ] Sidebar visible on left, dark teal
- [ ] Logo shows in sidebar
- [ ] All 5 nav links work (click each one)
- [ ] Active tab highlighted in white
- [ ] Form fills the right side properly
- [ ] Login/logout works
- [ ] "Finalize & Upload" button is auto-width, not stretched

---

## Rollback

If anything breaks, revert to last working commit:
```bash
git revert HEAD~1
git push origin main
```
