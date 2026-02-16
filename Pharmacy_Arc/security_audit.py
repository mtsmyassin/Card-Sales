#!/usr/bin/env python3
"""
SECURITY AUDIT - Pharmacy Sales Tracker
Independent External Security Assessment

This script actively probes for vulnerabilities and weaknesses.
"""

import sys
import time
import json
from pathlib import Path

print("=" * 80)
print("SECURITY AUDIT - Pharmacy Sales Tracker v40-SECURE")
print("Independent External Security Assessment")
print("=" * 80)

findings = {
    "CRITICAL": [],
    "HIGH": [],
    "MEDIUM": [],
    "LOW": []
}

def add_finding(severity, title, impact, exploit, fix, location):
    findings[severity].append({
        "title": title,
        "impact": impact,
        "exploit": exploit,
        "fix": fix,
        "location": location
    })

# ============================================================================
# PHASE 1: PRIVILEGE ESCALATION TESTING
# ============================================================================
print("\n[PHASE 1] PRIVILEGE ESCALATION TESTING")
print("-" * 80)

# Test 1.1: Missing RBAC on /api/sync endpoint
print("\n[TEST 1.1] Checking /api/sync endpoint protection...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    sync_pos = content.find("@app.route('/api/sync'")
    if sync_pos > 0:
        section_before = content[max(0, sync_pos-200):sync_pos]
        if '@require_auth' not in section_before:
            add_finding(
                "CRITICAL",
                "Missing RBAC on /api/sync endpoint",
                "Any unauthenticated user can sync offline queue, potentially injecting malicious data",
                "curl -X POST http://localhost:5013/api/sync -H 'Content-Type: application/json'",
                "Add @require_auth() decorator to /api/sync endpoint",
                "app.py:371"
            )
            print("❌ CRITICAL: /api/sync endpoint not protected by @require_auth()")
        else:
            print("✓ /api/sync endpoint protected")
except Exception as e:
    print(f"Error checking sync endpoint: {e}")

# Test 1.2: Missing RBAC on /api/get_logo endpoint
print("\n[TEST 1.2] Checking /api/get_logo endpoint protection...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    if '@app.route(\'/api/get_logo\'' in content:
        # Check if decorator exists
        logo_pos = content.find('@app.route(\'/api/get_logo\'')
        section = content[max(0, logo_pos-100):logo_pos+200]
        
        if '@require_auth' not in section:
            add_finding(
                "LOW",
                "Missing authentication on /api/get_logo",
                "Minor information disclosure - logo selection reveals store names",
                "curl -X POST http://localhost:5013/api/get_logo -H 'Content-Type: application/json' -d '{\"store\":\"test\"}'",
                "Add @require_auth() if store names are considered sensitive",
                "app.py:110"
            )
            print("⚠️  LOW: /api/get_logo not protected (minor info disclosure)")
        else:
            print("✓ /api/get_logo endpoint protected")
except Exception as e:
    print(f"Error checking get_logo endpoint: {e}")

# Test 1.3: Session fixation vulnerability
print("\n[TEST 1.3] Checking for session fixation vulnerability...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    # Check if session is regenerated on login
    if 'session.regenerate()' not in content and 'session.new()' not in content:
        add_finding(
            "HIGH",
            "Session fixation vulnerability",
            "Attacker can set a known session ID before authentication and hijack session after user logs in",
            "1. Attacker gets session cookie\n2. Forces victim to use that session\n3. Victim logs in\n4. Attacker now has authenticated session",
            "Regenerate session ID after successful login: add session regeneration or use Flask-Session with regenerate",
            "app.py:154-158 (login function)"
        )
        print("❌ HIGH: Session fixation possible - session ID not regenerated on login")
    else:
        print("✓ Session ID regenerated on login")
except Exception as e:
    print(f"Error checking session fixation: {e}")

# Test 1.4: Role stored in session (client-side)
print("\n[TEST 1.4] Checking role storage security...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    if "session['role'] = " in content:
        add_finding(
            "MEDIUM",
            "Role stored in client-controlled session",
            "While Flask sessions are signed, storing role in session means role changes require re-login. Also increases attack surface.",
            "User could potentially manipulate session cookie if secret key is compromised",
            "Consider storing only user ID in session and fetching role from database on each request, or use server-side sessions",
            "app.py:156, 195, etc."
        )
        print("⚠️  MEDIUM: Role stored in session (not ideal but signed)")
except Exception as e:
    print(f"Error checking role storage: {e}")

# ============================================================================
# PHASE 2: AUTHENTICATION BYPASS TESTING
# ============================================================================
print("\n[PHASE 2] AUTHENTICATION BYPASS TESTING")
print("-" * 80)

# Test 2.1: Lockout persistence across restarts
print("\n[TEST 2.1] Checking lockout persistence...")
try:
    with open('security.py', 'r') as f:
        content = f.read()
        
    if 'self._attempts:' in content and 'self._lockouts:' in content:
        # Check if these are in-memory only
        if 'json.dump' not in content and 'pickle' not in content and 'file' not in content:
            add_finding(
                "HIGH",
                "Brute-force lockout not persistent across restarts",
                "Attacker can restart the application to bypass account lockout, enabling unlimited password attempts",
                "1. Trigger 5 failed logins\n2. Restart application (or wait for crash/deployment)\n3. Continue brute-force attack",
                "Persist lockout state to database or file with expiry timestamps",
                "security.py:43-48 (LoginAttemptTracker.__init__)"
            )
            print("❌ HIGH: Lockout state lost on restart (in-memory only)")
        else:
            print("✓ Lockout state persisted")
    else:
        print("⚠️  Cannot determine lockout persistence")
except Exception as e:
    print(f"Error checking lockout persistence: {e}")

# Test 2.2: Lockout per account vs per IP
print("\n[TEST 2.2] Checking lockout granularity...")
try:
    with open('security.py', 'r') as f:
        content = f.read()
        
    if 'def is_locked_out(self, username:' in content:
        # Lockout is per username, not per IP
        add_finding(
            "MEDIUM",
            "Lockout is per-account, not per-IP",
            "Attacker can attempt passwords against multiple accounts without being rate-limited globally. Enables account enumeration and distributed brute-force.",
            "1. Try 'admin' with 5 wrong passwords\n2. Try 'super' with 5 wrong passwords\n3. Try other usernames\n4. No global rate limit",
            "Add IP-based rate limiting in addition to account lockout. Use Flask-Limiter or similar.",
            "security.py:52 (is_locked_out method)"
        )
        print("⚠️  MEDIUM: Lockout is per-account only (should also limit per-IP)")
except Exception as e:
    print(f"Error checking lockout granularity: {e}")

# Test 2.3: Password timing attack
print("\n[TEST 2.3] Checking for password timing leaks...")
try:
    with open('security.py', 'r') as f:
        content = f.read()
        
    # bcrypt is constant-time, so this should be okay
    if 'bcrypt.checkpw' in content:
        print("✓ Using bcrypt (constant-time comparison)")
    else:
        add_finding(
            "HIGH",
            "Potential timing attack in password verification",
            "Variable-time password comparison could leak password length information",
            "Measure response times for different password lengths to infer correct password length",
            "Use constant-time comparison (bcrypt already does this)",
            "security.py:23-32"
        )
        print("❌ HIGH: Not using bcrypt for comparison")
except Exception as e:
    print(f"Error checking timing attacks: {e}")

# Test 2.4: bcrypt work factor
print("\n[TEST 2.4] Checking bcrypt work factor...")
try:
    with open('security.py', 'r') as f:
        content = f.read()
        
    if 'bcrypt.gensalt(rounds=12)' in content:
        print("✓ Using bcrypt rounds=12 (acceptable for 2026)")
        # Note: For 2026, rounds=12 might be considered weak
        add_finding(
            "LOW",
            "bcrypt work factor may be insufficient for 2026",
            "rounds=12 is acceptable but not optimal. In 2026, rounds=14-16 is recommended.",
            "Brute-force becomes more feasible with hardware improvements",
            "Increase to rounds=14 or 15 for new password hashes. Implement gradual upgrade strategy.",
            "security.py:17"
        )
    else:
        print("⚠️  Cannot determine bcrypt work factor")
except Exception as e:
    print(f"Error checking bcrypt config: {e}")

# ============================================================================
# PHASE 3: AUDIT LOG INTEGRITY TESTING
# ============================================================================
print("\n[PHASE 3] AUDIT LOG INTEGRITY TESTING")
print("-" * 80)

# Test 3.1: File permissions on audit log
print("\n[TEST 3.1] Checking audit log file permissions...")
audit_log_file = Path('audit_log.jsonl')
if audit_log_file.exists():
    import stat
    mode = audit_log_file.stat().st_mode
    if mode & stat.S_IWOTH:
        add_finding(
            "HIGH",
            "Audit log world-writable",
            "Any user on the system can modify audit logs, destroying forensic evidence",
            "chmod 666 audit_log.jsonl && echo 'fake log' >> audit_log.jsonl",
            "Set restrictive permissions: chmod 600 audit_log.jsonl (owner read/write only)",
            "audit_log.py:23 (file creation)"
        )
        print("❌ HIGH: Audit log has insecure permissions")
    else:
        print("✓ Audit log has appropriate permissions")
else:
    print("ℹ️  Audit log not yet created")

# Test 3.2: Automated integrity verification
print("\n[TEST 3.2] Checking automated audit log verification...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    # Check if audit log verification runs automatically
    if 'verify_integrity' not in content or 'startup' not in content.lower():
        add_finding(
            "MEDIUM",
            "No automated audit log integrity verification on startup",
            "Tampered logs may go undetected. Verification is manual-only.",
            "1. Tamper with audit log\n2. Restart application\n3. Application continues without warning",
            "Add audit log integrity check to startup_check() in config.py or app startup",
            "app.py (startup section)"
        )
        print("⚠️  MEDIUM: No automated audit log verification")
    else:
        print("✓ Automated audit verification enabled")
except Exception as e:
    print(f"Error checking audit verification: {e}")

# Test 3.3: Audit log rotation
print("\n[TEST 3.3] Checking audit log rotation...")
try:
    with open('audit_log.py', 'r') as f:
        content = f.read()
        
    if 'rotate' not in content.lower() and 'max_size' not in content.lower():
        add_finding(
            "MEDIUM",
            "No audit log rotation implemented",
            "Audit log grows indefinitely, eventually filling disk and crashing application",
            "Wait for audit log to fill disk -> application fails",
            "Implement log rotation with size/time limits. Use Python logging.handlers.RotatingFileHandler",
            "audit_log.py:18 (AuditLogger class)"
        )
        print("⚠️  MEDIUM: No audit log rotation")
    else:
        print("✓ Audit log rotation implemented")
except Exception as e:
    print(f"Error checking log rotation: {e}")

# ============================================================================
# PHASE 4: DATA INTEGRITY TESTING
# ============================================================================
print("\n[PHASE 4] DATA INTEGRITY TESTING")
print("-" * 80)

# Test 4.1: Transaction support
print("\n[TEST 4.1] Checking database transaction support...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    # Look for transaction handling
    if 'transaction' not in content.lower() and 'begin' not in content.lower():
        add_finding(
            "HIGH",
            "No database transactions for critical operations",
            "Concurrent operations or crashes can leave database in inconsistent state. Day-close operation is not atomic.",
            "1. Start day-close operation\n2. Kill application mid-operation\n3. Database left in partial state",
            "Wrap critical multi-step operations (day-close) in database transactions",
            "app.py (update, delete, day-close operations)"
        )
        print("❌ HIGH: No transaction support detected")
    else:
        print("✓ Transactions used")
except Exception as e:
    print(f"Error checking transactions: {e}")

# Test 4.2: Offline queue file locking
print("\n[TEST 4.2] Checking offline queue file locking...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    # Check for file locking
    if 'fcntl' not in content and 'msvcrt' not in content and 'FileLock' not in content:
        add_finding(
            "MEDIUM",
            "No file locking on offline queue",
            "Concurrent access to offline_queue.json can corrupt data if multiple instances run",
            "1. Start two instances of the app\n2. Both try to write offline queue\n3. JSON becomes corrupted",
            "Use file locking (fcntl on Unix, msvcrt on Windows) or use filelock package",
            "app.py:41-48 (save_to_queue, load_queue)"
        )
        print("⚠️  MEDIUM: No file locking on offline queue")
    else:
        print("✓ File locking implemented")
except Exception as e:
    print(f"Error checking file locking: {e}")

# Test 4.3: Backup verification
print("\n[TEST 4.3] Checking backup verification...")
try:
    # Look for backup scripts
    backup_files = list(Path('.').glob('*backup*'))
    restore_test = list(Path('.').glob('*restore*test*'))
    
    if not backup_files:
        add_finding(
            "MEDIUM",
            "No automated backup implementation",
            "While tools mention backups, no automated backup script exists. Data loss risk.",
            "Database fails -> no recent backup -> permanent data loss",
            "Implement automated backup script with: 1) Daily backups 2) Retention policy 3) Integrity verification 4) Restore testing",
            "Missing: backup.py script"
        )
        print("⚠️  MEDIUM: No automated backup script found")
    else:
        print("✓ Backup script exists")
        
    if not restore_test:
        add_finding(
            "LOW",
            "No automated restore testing",
            "Backups may be corrupted or incomplete but only discovered during emergency",
            "Need backups during emergency -> backups are corrupted -> data loss",
            "Add automated restore test to CI/CD pipeline",
            "CI/CD pipeline"
        )
        print("⚠️  LOW: No restore testing")
except Exception as e:
    print(f"Error checking backups: {e}")

# ============================================================================
# PHASE 5: PERFORMANCE ISSUES
# ============================================================================
print("\n[PHASE 5] PERFORMANCE ISSUES")
print("-" * 80)

# Test 5.1: N+1 query in list endpoint
print("\n[TEST 5.1] Checking for N+1 queries...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    # Look for list endpoint
    if '.limit(2000)' in content:
        add_finding(
            "MEDIUM",
            "No pagination on /api/list endpoint",
            "Loading 2000 records every time is inefficient. Will cause performance degradation with large datasets.",
            "1. Database grows to 100,000 records\n2. Each page load fetches 2000 records\n3. Slow load times, high memory usage",
            "Implement pagination: offset/limit or cursor-based pagination",
            "app.py:422 (list_audits)"
        )
        print("⚠️  MEDIUM: No pagination (limit 2000 but no offset)")
    else:
        print("✓ Query limits implemented")
except Exception as e:
    print(f"Error checking queries: {e}")

# Test 5.2: Memory leaks
print("\n[TEST 5.2] Checking for potential memory leaks...")
try:
    with open('security.py', 'r') as f:
        content = f.read()
        
    # Check if attempt tracking is cleaned up
    if 'self._attempts' in content and 'del self._attempts' not in content:
        # Look for cleanup logic
        if 'cutoff' in content:
            print("✓ Attempt tracking has cleanup logic")
        else:
            add_finding(
                "LOW",
                "LoginAttemptTracker may accumulate data",
                "Failed login attempts are stored but may not be cleaned up efficiently, causing gradual memory growth",
                "Run application for extended period with failed logins -> memory usage grows",
                "Ensure old entries are periodically cleaned from _attempts and _lockouts dictionaries",
                "security.py:74 (record_failed_attempt)"
            )
            print("⚠️  LOW: Check attempt cleanup logic")
except Exception as e:
    print(f"Error checking memory leaks: {e}")

# ============================================================================
# PHASE 6: OPERATIONAL ROBUSTNESS
# ============================================================================
print("\n[PHASE 6] OPERATIONAL ROBUSTNESS")
print("-" * 80)

# Test 6.1: Missing environment variables
print("\n[TEST 6.1] Testing missing environment variable handling...")
try:
    with open('config.py', 'r') as f:
        content = f.read()
        
    if 'sys.exit(1)' in content:
        print("✓ Application exits on missing config (good)")
    else:
        add_finding(
            "LOW",
            "Application may run with invalid config",
            "Missing environment variables might be ignored, causing runtime errors",
            "Remove required env vars -> application starts but fails at runtime",
            "Ensure config validation exits with clear error",
            "config.py:123 (startup_check)"
        )
        print("⚠️  LOW: Check config validation behavior")
except Exception as e:
    print(f"Error checking config validation: {e}")

# Test 6.2: Disk full handling
print("\n[TEST 6.2] Checking disk full handling...")
try:
    with open('audit_log.py', 'r') as f:
        content = f.read()
        
    # Check if disk full is handled
    if 'IOError' not in content and 'OSError' not in content:
        add_finding(
            "MEDIUM",
            "No specific disk full error handling",
            "Audit logging will crash if disk is full, potentially losing critical security events",
            "Fill disk -> application crashes when trying to write audit log",
            "Add try/except for OSError/IOError in audit logging. Alert admin but don't crash.",
            "audit_log.py:81 (log method)"
        )
        print("⚠️  MEDIUM: No disk full handling in audit log")
    else:
        print("✓ Disk errors handled")
except Exception as e:
    print(f"Error checking disk handling: {e}")

# Test 6.3: Database connection error handling
print("\n[TEST 6.3] Checking database error handling...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    # Check if database errors are handled gracefully
    if 'except Exception as e:' in content:
        # Count how many bare Exception catches exist
        bare_catches = content.count('except Exception as e:')
        if bare_catches > 5:
            add_finding(
                "LOW",
                "Overly broad exception handling",
                "Catching generic Exception can hide bugs and make debugging difficult",
                "Unexpected error occurs -> caught by generic handler -> root cause hidden",
                "Use specific exception types (e.g., supabase.exceptions.*)",
                "app.py (multiple locations)"
            )
            print(f"⚠️  LOW: {bare_catches} broad exception handlers")
        else:
            print("✓ Exception handling reasonable")
except Exception as e:
    print(f"Error checking exception handling: {e}")

# ============================================================================
# ADDITIONAL SECURITY CHECKS
# ============================================================================
print("\n[ADDITIONAL] SECURITY BEST PRACTICES")
print("-" * 80)

# Test: CSRF protection
print("\n[TEST A.1] Checking CSRF protection...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    if 'csrf' not in content.lower():
        add_finding(
            "MEDIUM",
            "No CSRF protection",
            "All POST endpoints vulnerable to Cross-Site Request Forgery if accessed via browser",
            "1. Attacker creates malicious page\n2. Victim visits while logged in\n3. Attacker makes requests on victim's behalf",
            "Add Flask-WTF CSRF protection or implement CSRF tokens manually",
            "app.py (all POST endpoints)"
        )
        print("⚠️  MEDIUM: No CSRF protection detected")
    else:
        print("✓ CSRF protection enabled")
except Exception as e:
    print(f"Error checking CSRF: {e}")

# Test: Rate limiting
print("\n[TEST A.2] Checking global rate limiting...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    if 'Flask-Limiter' not in content and 'RateLimiter' not in content and '@limiter' not in content:
        add_finding(
            "MEDIUM",
            "No global rate limiting",
            "No rate limiting on API endpoints allows DoS attacks and rapid data exfiltration",
            "curl http://localhost:5013/api/list in a loop -> server overload",
            "Implement Flask-Limiter with per-IP rate limits on all endpoints",
            "app.py (application initialization)"
        )
        print("⚠️  MEDIUM: No global rate limiting")
    else:
        print("✓ Rate limiting enabled")
except Exception as e:
    print(f"Error checking rate limiting: {e}")

# Test: Input validation
print("\n[TEST A.3] Checking input validation...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
        
    if 'pydantic' not in content.lower() and 'marshmallow' not in content.lower():
        add_finding(
            "MEDIUM",
            "No structured input validation",
            "Input validation is ad-hoc. Missing validation can lead to data corruption or injection attacks.",
            "POST malformed data to endpoints -> crashes or corrupted data",
            "Use Pydantic or Marshmallow for structured input validation schemas",
            "app.py (all endpoints receiving JSON)"
        )
        print("⚠️  MEDIUM: No structured input validation framework")
    else:
        print("✓ Input validation framework in use")
except Exception as e:
    print(f"Error checking input validation: {e}")

# Test: HTTPS enforcement
print("\n[TEST A.4] Checking HTTPS enforcement...")
try:
    with open('config.py', 'r') as f:
        content = f.read()
        
    if 'REQUIRE_HTTPS' in content:
        print("✓ HTTPS configuration option exists")
        
        with open('app.py', 'r') as f2:
            app_content = f2.read()
            
        if 'request.is_secure' not in app_content and 'SSLify' not in app_content:
            add_finding(
                "HIGH",
                "HTTPS not enforced even when REQUIRE_HTTPS=true",
                "Session cookies and passwords transmitted in plaintext over HTTP",
                "1. Set REQUIRE_HTTPS=true\n2. Access via HTTP\n3. Application works but transmits credentials in clear",
                "Implement HTTPS enforcement: check request.is_secure or use Flask-SSLify",
                "app.py (add middleware to enforce HTTPS)"
            )
            print("❌ HIGH: REQUIRE_HTTPS config exists but not enforced in code")
    else:
        add_finding(
            "HIGH",
            "No HTTPS enforcement option",
            "Credentials and session cookies can be intercepted over unencrypted HTTP",
            "Sniff network traffic -> capture passwords and session cookies",
            "Add HTTPS enforcement with Flask-SSLify or custom middleware",
            "app.py (application initialization)"
        )
        print("❌ HIGH: No HTTPS enforcement")
except Exception as e:
    print(f"Error checking HTTPS: {e}")

# ============================================================================
# GENERATE REPORT
# ============================================================================
print("\n" + "=" * 80)
print("AUDIT FINDINGS SUMMARY")
print("=" * 80)

total_findings = sum(len(findings[s]) for s in findings)
print(f"\nTotal findings: {total_findings}")
print(f"  CRITICAL: {len(findings['CRITICAL'])}")
print(f"  HIGH:     {len(findings['HIGH'])}")
print(f"  MEDIUM:   {len(findings['MEDIUM'])}")
print(f"  LOW:      {len(findings['LOW'])}")

# Save detailed report
report_file = Path('SECURITY_AUDIT_REPORT.md')
with open(report_file, 'w') as f:
    f.write("# SECURITY AUDIT REPORT\n\n")
    f.write("**Application:** Pharmacy Sales Tracker v40-SECURE\n")
    f.write("**Date:** 2026-02-16\n")
    f.write("**Auditor:** Independent External Security Assessor\n\n")
    f.write("---\n\n")
    
    f.write(f"## Executive Summary\n\n")
    f.write(f"Total findings: **{total_findings}**\n\n")
    f.write(f"- **CRITICAL**: {len(findings['CRITICAL'])}\n")
    f.write(f"- **HIGH**: {len(findings['HIGH'])}\n")
    f.write(f"- **MEDIUM**: {len(findings['MEDIUM'])}\n")
    f.write(f"- **LOW**: {len(findings['LOW'])}\n\n")
    
    f.write("---\n\n")
    
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        if findings[severity]:
            f.write(f"## {severity} Priority Findings\n\n")
            
            for i, finding in enumerate(findings[severity], 1):
                f.write(f"### {severity}-{i}: {finding['title']}\n\n")
                f.write(f"**Impact:** {finding['impact']}\n\n")
                f.write(f"**Exploit Scenario:**\n```\n{finding['exploit']}\n```\n\n")
                f.write(f"**Fix Recommendation:** {finding['fix']}\n\n")
                f.write(f"**Location:** `{finding['location']}`\n\n")
                f.write("---\n\n")

print(f"\n✓ Detailed report saved to: {report_file}")

# Exit with error if critical findings
if findings['CRITICAL']:
    print("\n❌ CRITICAL ISSUES FOUND - DO NOT DEPLOY TO PRODUCTION")
    sys.exit(1)
elif findings['HIGH']:
    print("\n⚠️  HIGH PRIORITY ISSUES FOUND - REVIEW BEFORE DEPLOYMENT")
    sys.exit(1)
else:
    print("\n✓ No critical issues found")
    sys.exit(0)
