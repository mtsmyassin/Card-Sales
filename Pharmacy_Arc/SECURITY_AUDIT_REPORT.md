# SECURITY AUDIT REPORT

**Application:** Pharmacy Sales Tracker v40-SECURE
**Date:** 2026-02-16
**Auditor:** Independent External Security Assessor

---

## Executive Summary

Total findings: **18**

- **CRITICAL**: 1
- **HIGH**: 3
- **MEDIUM**: 10
- **LOW**: 4

---

## CRITICAL Priority Findings

### CRITICAL-1: Missing RBAC on /api/sync endpoint

**Impact:** Any unauthenticated user can sync offline queue, potentially injecting malicious data

**Exploit Scenario:**
```
curl -X POST http://localhost:5013/api/sync -H 'Content-Type: application/json'
```

**Fix Recommendation:** Add @require_auth() decorator to /api/sync endpoint

**Location:** `app.py:371`

---

## HIGH Priority Findings

### HIGH-1: Session fixation vulnerability

**Impact:** Attacker can set a known session ID before authentication and hijack session after user logs in

**Exploit Scenario:**
```
1. Attacker gets session cookie
2. Forces victim to use that session
3. Victim logs in
4. Attacker now has authenticated session
```

**Fix Recommendation:** Regenerate session ID after successful login: add session regeneration or use Flask-Session with regenerate

**Location:** `app.py:154-158 (login function)`

---

### HIGH-2: Brute-force lockout not persistent across restarts

**Impact:** Attacker can restart the application to bypass account lockout, enabling unlimited password attempts

**Exploit Scenario:**
```
1. Trigger 5 failed logins
2. Restart application (or wait for crash/deployment)
3. Continue brute-force attack
```

**Fix Recommendation:** Persist lockout state to database or file with expiry timestamps

**Location:** `security.py:43-48 (LoginAttemptTracker.__init__)`

---

### HIGH-3: HTTPS not enforced even when REQUIRE_HTTPS=true

**Impact:** Session cookies and passwords transmitted in plaintext over HTTP

**Exploit Scenario:**
```
1. Set REQUIRE_HTTPS=true
2. Access via HTTP
3. Application works but transmits credentials in clear
```

**Fix Recommendation:** Implement HTTPS enforcement: check request.is_secure or use Flask-SSLify

**Location:** `app.py (add middleware to enforce HTTPS)`

---

## MEDIUM Priority Findings

### MEDIUM-1: Role stored in client-controlled session

**Impact:** While Flask sessions are signed, storing role in session means role changes require re-login. Also increases attack surface.

**Exploit Scenario:**
```
User could potentially manipulate session cookie if secret key is compromised
```

**Fix Recommendation:** Consider storing only user ID in session and fetching role from database on each request, or use server-side sessions

**Location:** `app.py:156, 195, etc.`

---

### MEDIUM-2: Lockout is per-account, not per-IP

**Impact:** Attacker can attempt passwords against multiple accounts without being rate-limited globally. Enables account enumeration and distributed brute-force.

**Exploit Scenario:**
```
1. Try 'admin' with 5 wrong passwords
2. Try 'super' with 5 wrong passwords
3. Try other usernames
4. No global rate limit
```

**Fix Recommendation:** Add IP-based rate limiting in addition to account lockout. Use Flask-Limiter or similar.

**Location:** `security.py:52 (is_locked_out method)`

---

### MEDIUM-3: No audit log rotation implemented

**Impact:** Audit log grows indefinitely, eventually filling disk and crashing application

**Exploit Scenario:**
```
Wait for audit log to fill disk -> application fails
```

**Fix Recommendation:** Implement log rotation with size/time limits. Use Python logging.handlers.RotatingFileHandler

**Location:** `audit_log.py:18 (AuditLogger class)`

---

### MEDIUM-4: No file locking on offline queue

**Impact:** Concurrent access to offline_queue.json can corrupt data if multiple instances run

**Exploit Scenario:**
```
1. Start two instances of the app
2. Both try to write offline queue
3. JSON becomes corrupted
```

**Fix Recommendation:** Use file locking (fcntl on Unix, msvcrt on Windows) or use filelock package

**Location:** `app.py:41-48 (save_to_queue, load_queue)`

---

### MEDIUM-5: No automated backup implementation

**Impact:** While tools mention backups, no automated backup script exists. Data loss risk.

**Exploit Scenario:**
```
Database fails -> no recent backup -> permanent data loss
```

**Fix Recommendation:** Implement automated backup script with: 1) Daily backups 2) Retention policy 3) Integrity verification 4) Restore testing

**Location:** `Missing: backup.py script`

---

### MEDIUM-6: No pagination on /api/list endpoint

**Impact:** Loading 2000 records every time is inefficient. Will cause performance degradation with large datasets.

**Exploit Scenario:**
```
1. Database grows to 100,000 records
2. Each page load fetches 2000 records
3. Slow load times, high memory usage
```

**Fix Recommendation:** Implement pagination: offset/limit or cursor-based pagination

**Location:** `app.py:422 (list_audits)`

---

### MEDIUM-7: No specific disk full error handling

**Impact:** Audit logging will crash if disk is full, potentially losing critical security events

**Exploit Scenario:**
```
Fill disk -> application crashes when trying to write audit log
```

**Fix Recommendation:** Add try/except for OSError/IOError in audit logging. Alert admin but don't crash.

**Location:** `audit_log.py:81 (log method)`

---

### MEDIUM-8: No CSRF protection

**Impact:** All POST endpoints vulnerable to Cross-Site Request Forgery if accessed via browser

**Exploit Scenario:**
```
1. Attacker creates malicious page
2. Victim visits while logged in
3. Attacker makes requests on victim's behalf
```

**Fix Recommendation:** Add Flask-WTF CSRF protection or implement CSRF tokens manually

**Location:** `app.py (all POST endpoints)`

---

### MEDIUM-9: No global rate limiting

**Impact:** No rate limiting on API endpoints allows DoS attacks and rapid data exfiltration

**Exploit Scenario:**
```
curl http://localhost:5013/api/list in a loop -> server overload
```

**Fix Recommendation:** Implement Flask-Limiter with per-IP rate limits on all endpoints

**Location:** `app.py (application initialization)`

---

### MEDIUM-10: No structured input validation

**Impact:** Input validation is ad-hoc. Missing validation can lead to data corruption or injection attacks.

**Exploit Scenario:**
```
POST malformed data to endpoints -> crashes or corrupted data
```

**Fix Recommendation:** Use Pydantic or Marshmallow for structured input validation schemas

**Location:** `app.py (all endpoints receiving JSON)`

---

## LOW Priority Findings

### LOW-1: Missing authentication on /api/get_logo

**Impact:** Minor information disclosure - logo selection reveals store names

**Exploit Scenario:**
```
curl -X POST http://localhost:5013/api/get_logo -H 'Content-Type: application/json' -d '{"store":"test"}'
```

**Fix Recommendation:** Add @require_auth() if store names are considered sensitive

**Location:** `app.py:110`

---

### LOW-2: bcrypt work factor may be insufficient for 2026

**Impact:** rounds=12 is acceptable but not optimal. In 2026, rounds=14-16 is recommended.

**Exploit Scenario:**
```
Brute-force becomes more feasible with hardware improvements
```

**Fix Recommendation:** Increase to rounds=14 or 15 for new password hashes. Implement gradual upgrade strategy.

**Location:** `security.py:17`

---

### LOW-3: No automated restore testing

**Impact:** Backups may be corrupted or incomplete but only discovered during emergency

**Exploit Scenario:**
```
Need backups during emergency -> backups are corrupted -> data loss
```

**Fix Recommendation:** Add automated restore test to CI/CD pipeline

**Location:** `CI/CD pipeline`

---

### LOW-4: Overly broad exception handling

**Impact:** Catching generic Exception can hide bugs and make debugging difficult

**Exploit Scenario:**
```
Unexpected error occurs -> caught by generic handler -> root cause hidden
```

**Fix Recommendation:** Use specific exception types (e.g., supabase.exceptions.*)

**Location:** `app.py (multiple locations)`

---

