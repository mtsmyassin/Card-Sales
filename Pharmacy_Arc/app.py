import json, webbrowser, os, sys, base64
from functools import wraps
from threading import Timer
from flask import Flask, render_template_string, request, jsonify, session
from supabase import create_client, Client

# --- FORCE NEW PORT TO KILL CACHE ---
PORT = 5013
print(f"--- LAUNCHING VERSION 39 (MATH PERFECT) ON PORT {PORT} ---")

app = Flask(__name__)
app.secret_key = 'carimas_v39_final_math'

# --- 1. CLOUD & LOCAL CONFIGURATION ---
SUPABASE_URL = "https://nnvksawtfthbrcijwbpk.supabase.co"
SUPABASE_KEY = "sb_publishable_oBnDva4802DVrBagVX05Fw_40ZVEPiJ"
OFFLINE_FILE = 'offline_queue.json'

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"CRITICAL ERROR: Cloud Client Init Failed. {e}")

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
    return base64.b64encode(open(p, "rb").read()).decode() if os.path.exists(p) else ""

# --- 3. OFFLINE HANDLERS ---
def save_to_queue(payload):
    q_path = get_queue_path()
    queue = []
    if os.path.exists(q_path):
        try: queue = json.load(open(q_path))
        except: pass
    queue.append(payload)
    with open(q_path, 'w') as f: json.dump(queue, f)

def load_queue():
    q_path = get_queue_path()
    if os.path.exists(q_path):
        try: return json.load(open(q_path))
        except: return []
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

@app.route('/api/get_logo', methods=['POST'])
def api_get_logo():
    return jsonify(logo=get_logo(request.json.get('store')))

@app.route('/api/login', methods=['POST'])
def login():
    u = request.json.get('username')
    p = request.json.get('password')
    
    # --- HARDCODED BACKDOORS ---
    if u == 'super' and p == '9517535m3N@':
        session['logged_in'] = True; session['user'] = u; session['role'] = 'super_admin'; session['store'] = 'All'
        return jsonify(status="ok", role='super_admin', store='All')

    if u == 'admin' and p == '1q2w3e4rM3n@':
        session['logged_in'] = True; session['user'] = u; session['role'] = 'admin'; session['store'] = 'All'
        return jsonify(status="ok", role='admin', store='All')

    try:
        res = supabase.table("users").select("*").eq("username", u).execute()
        if res.data:
            user = res.data[0]
            if user['password'] == p:
                session['logged_in'] = True
                session['user'] = u
                session['role'] = user['role']
                session['store'] = user['store']
                return jsonify(status="ok", role=user['role'], store=user['store'])
    except: pass

    return jsonify(status="fail"), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify(status="ok")

@app.route('/api/save', methods=['POST'])
def save():
    if not session.get('logged_in'): return "Auth Required", 401
    d = request.json
    record = {
        "date": d['date'], "reg": d['reg'], "staff": d['staff'], "store": d.get('store', 'Main'),
        "gross": d['gross'], "net": d['net'], "variance": float(d['variance']), "payload": d
    }
    try:
        supabase.table("audits").insert(record).execute()
        return jsonify(status="success")
    except:
        save_to_queue(record)
        return jsonify(status="offline")

@app.route('/api/sync', methods=['POST'])
def sync():
    queue = load_queue()
    if not queue: return jsonify(status="empty")
    failed_items = []
    success_count = 0
    for item in queue:
        try:
            supabase.table("audits").insert(item).execute()
            success_count += 1
        except:
            failed_items.append(item)
    if failed_items:
        q_path = get_queue_path()
        with open(q_path, 'w') as f: json.dump(failed_items, f)
    else:
        clear_queue()
    return jsonify(status="success", count=success_count, remaining=len(failed_items))

@app.route('/api/update', methods=['POST'])
def update():
    if not session.get('logged_in'): return "Auth Required", 401
    if session['role'] == 'staff': return "Permission Denied", 403
    d = request.json
    uid = d.get('id')
    record = {
        "date": d['date'], "reg": d['reg'], "staff": d['staff'], "store": d.get('store', 'Main'),
        "gross": d['gross'], "net": d['net'], "variance": float(d['variance']), "payload": d
    }
    try:
        supabase.table("audits").update(record).eq("id", uid).execute()
        return jsonify(status="success")
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/api/delete', methods=['POST'])
def delete():
    if not session.get('logged_in'): return "Auth Required", 401
    if session['role'] == 'staff': return "Permission Denied", 403
    try:
        supabase.table("audits").delete().eq("id", request.json['id']).execute()
        return jsonify(status="success")
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/api/list')
def list_audits():
    try:
        response = supabase.table("audits").select("*").order("date", desc=True).limit(2000).execute()
        clean_rows = []
        user_store = session.get('store')
        user_role = session.get('role')
        for r in response.data:
            if user_role not in ['admin', 'super_admin'] and r.get('store') != user_store: continue
            merged = r['payload']
            merged['id'] = r['id']
            merged['store'] = r.get('store', 'Main')
            clean_rows.append(merged)
        return jsonify(clean_rows)
    except: return jsonify([])

@app.route('/api/users/list')
def list_users():
    if session.get('role') not in ['admin', 'super_admin']: return jsonify([])
    try: return jsonify(supabase.table("users").select("*").execute().data)
    except: return jsonify([])

@app.route('/api/users/save', methods=['POST'])
def save_user():
    if session.get('role') not in ['admin', 'super_admin']: return "Denied", 403
    u = request.json
    try:
        supabase.table("users").upsert({"username": u['username'], "password": u['password'], "role": u['role'], "store": u['store']}).execute()
        return jsonify(status="success")
    except Exception as e: return jsonify(error=str(e)), 500

@app.route('/api/users/delete', methods=['POST'])
def delete_user():
    if session.get('role') not in ['admin', 'super_admin']: return "Denied", 403
    try:
        supabase.table("users").delete().eq("username", request.json['username']).execute()
        return jsonify(status="success")
    except: return jsonify(status="error"), 500

# --- 4. FRONTEND UI ---
LOGIN_UI = """<!DOCTYPE html><html><body style="background:#0f172a;color:white;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;">
<div style="background:#1e293b;padding:40px;border-radius:20px;text-align:center;width:320px;border:1px solid #334155;">
{% if logo %}<img src="data:image/png;base64,{{logo}}" style="max-width:140px;margin-bottom:20px">{% endif %}
<h2>System Login</h2><small style="color:#0097b2;font-weight:900;font-size:14px">v39 (PORT 5013)</small><br><br>
<input type="text" id="u" placeholder="Username" style="width:90%;padding:12px;margin-bottom:10px;border-radius:8px;border:none;text-align:center;font-weight:bold;font-size:16px;">
<input type="password" id="p" placeholder="Password" style="width:90%;padding:12px;margin-bottom:20px;border-radius:8px;border:none;text-align:center;font-weight:bold;font-size:16px;">
<button onclick="l()" style="width:100%;padding:12px;background:#0097b2;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:bold;font-size:16px;">Login</button>
</div><script>function l(){fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('u').value,password:document.getElementById('p').value})}).then(r=>r.json()).then(d=>{if(d.status==='ok'){localStorage.setItem('role',d.role);localStorage.setItem('store',d.store);location.reload()}else{alert('Invalid Credentials')}})}</script></body></html>"""

MAIN_UI = """<!DOCTYPE html><html><head><title>Pharmacy Director</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.0.0"></script>
<style>
/* TURQUOISE BRANDING */
:root{--p:#0097b2;--bg:#f8fafc;--danger:#ef4444;--success:#047857;--txt:#1e293b;--warn:#f59e0b;}
*{box-sizing:border-box; font-family: 'Segoe UI', system-ui, sans-serif;} 
body{
    background-color: var(--bg);
    margin:0; padding:15px; color:var(--txt);
    position: relative;
    min-height: 100vh;
}
/* WATERMARK: Full Color, Visible */
.watermark {
    position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
    width: 500px; opacity: 0.15; z-index: -1; pointer-events: none;
}

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

.view{display:none;} .view.active{display:block;}
.grid-form{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;}
input,select{width:100%;padding:12px;border:1px solid #e2e8f0;border-radius:8px;margin-bottom:15px;color:#1e293b;background:rgba(255,255,255,0.9);font-weight:700;}
.btn-main{background:var(--p);color:white;width:100%;padding:14px;border:none;border-radius:10px;cursor:pointer;font-size:15px;font-weight:800;}

.section{font-size:12px;color:#64748b;text-transform:uppercase;margin:20px 0 10px;border-bottom:2px solid #e2e8f0;padding-bottom:5px;display:flex;justify-content:space-between;letter-spacing:1px;font-weight:900;}

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

table{width:100%;border-collapse:collapse;} th,td{padding:12px;text-align:left;border-bottom:1px solid #f1f5f9; font-weight:600;}
.hidden{display:none !important;}
</style></head><body>

<img src="data:image/png;base64,{{logo}}" class="watermark">

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

<div id="dash" class="view active">
    <div class="panel" id="dashPanel">
        <input type="hidden" id="editId" value="">
        <div class="section" style="margin-top:0">1. Store & Metadata</div>
        <div class="grid-form">
            <div><label>Store Location</label><select id="storeLoc" onchange="app.checkStore()"><option>Carimas #1</option><option>Carimas #2</option><option>Carimas #3</option><option>Carimas #4</option><option>Carthage</option></select></div>
            <div><label>Date</label><input type="date" id="date"></div>
            <div><label>Register</label><select id="reg"><option>Reg 1</option><option>Reg 2</option><option>Reg 3</option><option>Reg 4</option><option>Reg 5</option><option>Reg 6</option><option>Reg 7</option><option>Reg 8</option></select></div>
            <div><label>Staff Name</label><input type="text" id="staff" list="staffList" placeholder="Name"><datalist id="staffList"><option>Manager</option><option>Pharmacist</option><option>Clerk</option></datalist></div>
        </div>
        <div class="section">2. Revenue</div>
        <div style="display:grid;grid-template-columns:1fr 4fr;gap:20px">
            <div><label>Cash Sales</label><input type="number" id="cash" placeholder="0.00"></div>
            <div class="grid-form">
                <input type="number" id="ath" placeholder="ATH"><input type="number" id="athm" placeholder="ATHM"><input type="number" id="visa" placeholder="Visa">
                <input type="number" id="mc" placeholder="MC"><input type="number" id="amex" placeholder="AmEx"><input type="number" id="disc" placeholder="Disc">
                <input type="number" id="wic" placeholder="WIC"><input type="number" id="mcs" placeholder="MCS"><input type="number" id="sss" placeholder="Triple S" style="border:2px solid var(--p)">
            </div>
        </div>
        <div id="tipsSection" class="hidden" style="margin-top:5px;background:#ecfdf5;padding:10px;border:1px solid #10b981;border-radius:8px;">
            <div style="color:#047857;font-weight:800;font-size:12px">Carthage Tip Tracker</div><input type="number" id="ccTips" placeholder="Total CC Tips" style="margin:0;width:150px">
        </div>
        <div class="section">3. Deductions <button onclick="app.calcTax()" style="cursor:pointer;font-size:10px;padding:2px 6px;">Auto 11.5%</button></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px"><div><label>State (10.5%)</label><input type="number" id="taxState"></div><div><label>City (1%)</label><input type="number" id="taxCity"></div></div>
        <div class="section">4. Payouts <button onclick="app.addPayout()" style="cursor:pointer;padding:2px 6px;">+ Add</button></div><div id="payoutList"></div>
        <div class="section">5. Reconciliation</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px"><div><label>Opening Float</label><input type="number" id="float" value="150.00"></div><div><label>Actual Cash</label><input type="number" id="actual" onclick="app.openCount()"></div></div>
        <div style="display:flex;gap:10px;margin-top:20px"><button id="saveBtn" class="btn-main" onclick="app.save()">Finalize & Upload</button><button id="cancelBtn" class="btn-main" onclick="app.resetForm()" style="background:#64748b;display:none;">Cancel</button></div>
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
                        <div class="kpi-label">Net Profit (Est)</div>
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
                <select id="histRange" onchange="app.filterHistory()" style="margin:0;width:120px"><option value="30">Last 30 Days</option><option value="7">Last 7 Days</option><option value="0">Today</option><option value="custom">Custom</option></select>
                <input type="date" id="historyFilter" onchange="document.getElementById('histRange').value='custom';app.filterHistory()" style="margin:0;padding:5px;">
                <select id="histStoreFilter" onchange="app.filterHistory()" style="margin:0;width:120px"><option value="All">All Stores</option><option>Carimas #1</option><option>Carimas #2</option><option>Carimas #3</option><option>Carimas #4</option><option>Carthage</option></select>
                <button onclick="app.fetch()">Refresh</button>
            </div>
        </div>
        <div id="logTable" style="max-height:600px;overflow-y:auto"></div>
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
            <input type="text" id="u_pass" placeholder="Password">
            <select id="u_role"><option value="staff">Staff</option><option value="manager">Manager</option><option value="admin">Admin</option><option value="super_admin">Super Admin</option></select>
            <select id="u_store"><option value="All">All (Admin)</option><option>Carimas #1</option><option>Carimas #2</option><option>Carimas #3</option><option>Carimas #4</option><option>Carthage</option></select>
        </div>
        <button id="userSaveBtn" class="btn-main" onclick="app.saveUser()" style="margin-top:10px">Create User</button>
        <br><br><div id="userTable"></div>
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
const app = {
    data: [], users: [], calDate: new Date(), role: '', store: '',
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
            ['tab-calendar','tab-analytics','tab-users'].forEach(x=>document.getElementById(x).style.display='none');
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
    sync: async () => {
        document.getElementById('syncBtn').innerText = "Syncing...";
        const d = await (await fetch('/api/sync', {method:'POST'})).json();
        if(d.status === 'success') { alert(`Synced ${d.count} records!`); if(d.remaining === 0) document.getElementById('syncBtn').style.display = 'none'; app.fetch(); } 
        else { alert('Sync failed. Check internet.'); document.getElementById('syncBtn').innerText = "⚠️ Sync"; }
    },
    checkStore: () => {
        const s = document.getElementById('storeLoc').value;
        if(s === 'Carthage') document.getElementById('tipsSection').classList.remove('hidden'); else { document.getElementById('tipsSection').classList.add('hidden'); document.getElementById('ccTips').value = ''; }
        fetch('/api/get_logo', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({store:s})}).then(r=>r.json()).then(d=>{if(d.logo)document.getElementById('appLogo').src='data:image/png;base64,'+d.logo});
    },
    save: async () => {
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
    },
    logout: () => fetch('/api/logout', {method:'POST'}).then(()=>location.reload()),
    tab: (id) => { 
        if(app.role==='staff' && (id!=='dash' && id!=='logs')) return;
        if(app.role==='manager' && (id!=='dash' && id!=='logs' && id!=='calendar')) return;
        document.querySelectorAll('.view,.tab-btn').forEach(e=>e.classList.remove('active')); 
        document.getElementById(id).classList.add('active'); document.getElementById('tab-'+id).classList.add('active'); 
        if(id==='analytics')app.renderAnalytics(); if(id==='calendar')app.renderCalendar(); if(id==='logs')app.fetch(); 
    },
    setupBill: () => { const d=document.getElementById('billRows'); [100,50,20,10,5,1,0.25,0.1,0.05,0.01].forEach(v=>{d.innerHTML+=`<div style="display:flex;justify-content:space-between;margin-bottom:5px"><span>$${v}</span><input type="number" class="bi" data-v="${v}" style="width:70px;padding:5px"></div>`}); d.addEventListener('input',()=>{let t=0;document.querySelectorAll('.bi').forEach(i=>t+=i.value*i.dataset.v);document.getElementById('billTotal').innerText='$'+t.toFixed(2)}) },
    addPayout: (r='',a='') => { const d=document.createElement('div');d.className='payout-row';d.innerHTML=`<div style="display:flex;gap:5px;margin-bottom:5px"><input class="p-reason" placeholder="Reason" value="${r}" style="flex:2"><input type="number" class="p-amt" placeholder="Amt" value="${a}" style="flex:1"><button onclick="this.parentElement.remove()" style="background:#fee2e2;border:1px solid #ef4444;cursor:pointer">X</button></div>`;document.getElementById('payoutList').appendChild(d)},
    calcTax: () => { const c=parseFloat(document.getElementById('cash').value||0); document.getElementById('taxState').value=(c*0.105).toFixed(2); document.getElementById('taxCity').value=(c*0.01).toFixed(2); },
    openCount: () => document.getElementById('modalCount').style.display='flex',
    applyCount: () => { document.getElementById('actual').value=document.getElementById('billTotal').innerText.replace('$',''); document.getElementById('modalCount').style.display='none'; },
    resetForm: () => { document.getElementById('editId').value=''; document.getElementById('saveBtn').innerText="Finalize & Upload"; document.getElementById('saveBtn').style.background="#0097b2"; document.getElementById('cancelBtn').style.display="none"; document.getElementById('dashPanel').classList.remove('edit-mode'); document.getElementById('modeLabel').innerText="1. Store & Metadata"; document.querySelectorAll('input[type="number"]').forEach(i=>i.value=''); document.getElementById('float').value='150.00'; document.getElementById('payoutList').innerHTML=''; app.checkStore(); },
    editAudit: (idx) => { const d=app.data[idx], b=d.breakdown; document.getElementById('editId').value=d.id; document.getElementById('date').value=d.date; document.getElementById('storeLoc').value=d.store; app.checkStore(); document.getElementById('reg').value=d.reg; document.getElementById('staff').value=d.staff; Object.keys(b).forEach(k=>{if(document.getElementById(k))document.getElementById(k).value=b[k]}); document.getElementById('payoutList').innerHTML=''; (b.payoutList||[]).forEach(p=>app.addPayout(p.r,p.a)); document.getElementById('saveBtn').innerText="Update Record"; document.getElementById('saveBtn').style.background="#f59e0b"; document.getElementById('cancelBtn').style.display="inline-block"; document.getElementById('dashPanel').classList.add('edit-mode'); document.getElementById('modeLabel').innerText="EDITING RECORD #"+d.id; app.tab('dash'); },
    deleteAudit: async (id) => { if(confirm("Permanently Delete?")) { await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})}); app.fetch(); } },
    fetch: async () => { app.data = await (await fetch('/api/list')).json(); app.renderLogs(); },
    filterHistory: () => { const r=document.getElementById('histRange').value, d=document.getElementById('historyFilter').value, s=(app.role!=='staff')?document.getElementById('histStoreFilter').value:app.store; let f=app.data; if(s&&s!=='All')f=f.filter(x=>x.store===s); if(r==='custom'){if(d)f=f.filter(x=>x.date===d)}else{const days=parseInt(r), cut=new Date(); cut.setDate(cut.getDate()-days); if(days===0)f=f.filter(x=>x.date===new Date().toISOString().split('T')[0]); else if(days!==9999)f=f.filter(x=>new Date(x.date)>=cut);} app.renderTable(f); },
    renderTable: (rows) => { let h='<table><tr><th>Date</th><th>Store</th><th>Gross</th><th>Var</th><th>Actions</th></tr>'; rows.forEach(d=>{ const i=app.data.indexOf(d), acts=(app.role==='staff')?`<button onclick="app.print(${i})" class="action-btn btn-print">🖨 Print</button>`:`<button onclick="app.print(${i})" class="action-btn btn-print">🖨</button><button onclick="app.editAudit(${i})" class="action-btn btn-edit">✏️</button><button onclick="app.deleteAudit(${d.id})" class="action-btn btn-del">🗑</button>`; h+=`<tr><td>${d.date}</td><td>${d.store}</td><td>$${(d.gross||0).toFixed(2)}</td><td style="color:${d.variance<0?'#be123c':'#047857'};font-weight:800">$${d.variance}</td><td>${acts}</td></tr>`;}); document.getElementById('logTable').innerHTML=h+'</table>'; },
    print: async (idx) => { const d=app.data[idx], b=d.breakdown||{}, val=v=>(v||0).toFixed(2), logo='data:image/png;base64,'+(await(await fetch('/api/get_logo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({store:d.store})})).json()).logo; const w=window.open('','','height=700,width=500'); w.document.write(`<html><head><style>body{font-family:monospace;padding:20px;font-weight:bold}.row{display:flex;justify-content:space-between;border-bottom:1px dotted #ccc;padding:5px 0}h2,h4{text-align:center;margin:5px 0}</style></head><body><div style="text-align:center;margin-bottom:10px"><img src="${logo}" style="max-height:80px;display:block;margin:0 auto"></div><h2>${d.store==='Carthage'?'Carthage Express':'Farmacia Carimas'}</h2><h4>${d.store} Audit</h4><br><div class="row"><span>Date:</span><span>${d.date}</span></div><div class="row"><span>Staff:</span><span>${d.staff||'N/A'}</span></div><br><div class="row"><strong>Cash Sales:</strong><span>$${val(b.cash)}</span></div><div class="row"><span>Cards (Combined):</span><span>$${val((d.gross||0)-(b.cash||0))}</span></div><br><div class="row"><span>State Tax:</span><span>$${val(b.taxState)}</span></div><div class="row"><span>City Tax:</span><span>$${val(b.taxCity)}</span></div>${(b.payoutList||[]).map(p=>`<div class="row"><span>${p.r}</span><span>$${val(p.a)}</span></div>`).join('')}<br><div class="row"><strong>Total Payouts:</strong><span>$${val(b.payouts)}</span></div><div class="row"><strong>Actual Cash:</strong><span>$${val(b.actual)}</span></div><br><div class="row" style="border-top:2px solid black;font-size:1.2em"><strong>VARIANCE:</strong><strong>$${d.variance}</strong></div><br><br><br><div style="text-align:center">________________________<br>Manager Signature</div></body></html>`); w.document.close(); setTimeout(()=>w.print(),500); },
    setupCalControls: () => { const m=document.getElementById('calMonthSelect'); ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].forEach((x,i)=>m.innerHTML+=`<option value="${i}">${x}</option>`); app.updateCalView(); },
    updateCalView: () => { if(event&&event.target.id==='calMonthSelect')app.calDate.setMonth(parseInt(event.target.value)); if(event&&event.target.id==='calYearInput')app.calDate.setFullYear(parseInt(event.target.value)); document.getElementById('calMonthSelect').value=app.calDate.getMonth(); document.getElementById('calYearInput').value=app.calDate.getFullYear(); app.renderCalendar(); },
    renderCalendar: () => { const c=document.getElementById('calGrid'), dt=app.calDate, s=(app.role!=='staff')?document.getElementById('calStoreFilter').value:app.store, dim=new Date(dt.getFullYear(),dt.getMonth()+1,0).getDate(); c.innerHTML=''; for(let i=1;i<=dim;i++){ const ds=`${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(i).padStart(2,'0')}`, es=app.data.filter(x=>x.date===ds&&(s==='All'||x.store===s)); let g=0,v=0; es.forEach(x=>{g+=x.gross||0;v+=parseFloat(x.variance||0)}); c.innerHTML+=`<div style="background:${es.length>0?(v<0?'#fee2e2':'#dcfce7'):'rgba(255,255,255,0.7)'};border:1px solid #ddd;padding:5px;height:80px;cursor:pointer;border-radius:8px" onclick="app.tab('logs');document.getElementById('historyFilter').value='${ds}';document.getElementById('histRange').value='custom';app.filterHistory()"><div style="font-weight:bold">${i}</div>${es.length>0?`<div style="font-size:10px;margin-top:5px">$${g.toFixed(0)}<br>${v.toFixed(2)}</div>`:''}</div>`; } },
    
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
        } else {
            const days = parseInt(m) || 30;
            // Fix: "Last N Days" includes today. Reset to midnight.
            rangeStart.setDate(rangeStart.getDate() - (days - 1));
            rangeStart.setHours(0, 0, 0, 0);
        }

        let f = app.data; 
        if (s !== 'All') f = f.filter(x => x.store === s);
        f = f.filter(x => { const d = new Date(x.date); return d >= rangeStart && d <= rangeEnd; });

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

        const avgDaily = count > 0 ? gross / count : 0; 
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
            datasets = stores.map((st, i) => ({ label: st, data: labels.map(l => { const r=f.find(x=>x.date===l && x.store===st); return r?r.gross:0; }), borderColor: colors[i%colors.length], tension: 0.4, pointRadius: 0, borderWidth:3 }));
        } else { datasets = [{label:'Revenue', data:labels.map(l => { const r=f.find(x=>x.date===l); return r?r.gross:0; }), borderColor:'#0097b2', tension:0.4, pointRadius:3, fill:true, backgroundColor:grad, borderWidth:3}]; }
        window.lineC=new Chart(cl,{type:'line', data:{labels:labels, datasets:datasets}, options: commonOpt }); 

        const dowMap = [0,0,0,0,0,0,0], dowCount=[0,0,0,0,0,0,0], days=['S','M','T','W','T','F','S'];
        f.forEach(x=>{ const d=new Date(x.date).getDay(); dowMap[d]+=x.gross||0; dowCount[d]++; });
        const cd=document.getElementById('dowChart').getContext('2d'); if(window.dowC)window.dowC.destroy();
        window.dowC=new Chart(cd, {type:'bar', data:{labels:days, datasets:[{data:dowMap.map((v,i) => dowCount[i]?v/dowCount[i]:0), backgroundColor:'#0097b2', borderRadius:4, maxBarThickness: 40}]}, options:{...commonOpt, plugins:{legend:{display:false}, datalabels:{display:false}}}});

        const regMap={}; f.forEach(x=>{ regMap[x.reg]=(regMap[x.reg]||0)+x.gross; });
        const cr=document.getElementById('regChart').getContext('2d'); if(window.regC)window.regC.destroy();
        window.regC=new Chart(cr, {type:'bar', data:{labels:Object.keys(regMap), datasets:[{data:Object.values(regMap), backgroundColor:'#6366f1', borderRadius:4, maxBarThickness: 40}]}, options:{...commonOpt, plugins:{legend:{display:false}, datalabels:{display:false}}}});

        const payMap={}; f.forEach(x=>{ (x.breakdown.payoutList||[]).forEach(p=>{ payMap[p.r]=(payMap[p.r]||0)+p.a; }); });
        const sortPay = Object.entries(payMap).sort((a,b)=>b[1]-a[1]).slice(0,5);
        const cp2=document.getElementById('payoutChart').getContext('2d'); if(window.payC)window.payC.destroy();
        window.payC=new Chart(cp2, {type:'bar', indexAxis:'y', data:{labels:sortPay.map(x=>x[0]), datasets:[{data:sortPay.map(x=>x[1]), backgroundColor:'#be123c', borderRadius:4, maxBarThickness: 40}]}, options:{...commonOpt, plugins:{legend:{display:false}, datalabels:{display:false}}}});
    },
    
    fetchUsers: async () => { const u = await (await fetch('/api/users/list')).json(); app.users=u; document.getElementById('userTable').innerHTML='<table><tr><th>User</th><th>Role</th><th>Store</th><th>Pass</th><th>Actions</th></tr>'+u.map(x=>`<tr><td>${x.username}</td><td>${x.role}</td><td>${x.store}</td><td>${app.role==='super_admin'?x.password:'••••'}</td><td><button onclick="app.editUser('${x.username}')" class="action-btn btn-edit">✏️</button><button onclick="app.deleteUser('${x.username}')" class="action-btn btn-del">🗑</button></td></tr>`).join('')+'</table>'; },
    editUser: (n) => { const u=app.users.find(x=>x.username===n); if(!u)return; document.getElementById('u_name').value=u.username; document.getElementById('u_pass').value=u.password; document.getElementById('u_role').value=u.role; document.getElementById('u_store').value=u.store; const b=document.getElementById('userSaveBtn'); b.innerText="Update User"; b.style.background="#f59e0b"; window.scrollTo({top:0,behavior:'smooth'}); },
    saveUser: async () => { const u={username:document.getElementById('u_name').value,password:document.getElementById('u_pass').value,role:document.getElementById('u_role').value,store:document.getElementById('u_store').value}; if(!u.username||!u.password)return alert('Fill all'); if((await fetch('/api/users/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(u)})).ok){alert('Saved');app.fetchUsers();document.getElementById('userSaveBtn').innerText="Create User";document.getElementById('userSaveBtn').style.background="#0097b2";}else alert('Error'); },
    deleteUser: async (n) => { if(confirm('Delete?')) { await fetch('/api/users/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:n})}); app.fetchUsers(); } }
};
app.init();
</script></body></html>"""

if __name__ == '__main__':
    Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(port=PORT)