#!/usr/bin/env python3
"""
Test script to verify CRITICAL and HIGH priority fixes.
"""
import sys
from pathlib import Path

print("=" * 80)
print("VERIFYING SECURITY FIXES")
print("=" * 80)

fixes_verified = []
issues_found = []

# Test 1: Verify /api/sync has @require_auth()
print("\n[TEST 1] Verifying /api/sync endpoint protection...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
    
    sync_pos = content.find("def sync():")
    if sync_pos > 0:
        section_before = content[max(0, sync_pos-100):sync_pos]
        if '@require_auth()' in section_before or '@require_auth(' in section_before:
            print("✅ FIXED: /api/sync now protected with @require_auth()")
            fixes_verified.append("CRITICAL-1: /api/sync protected")
        else:
            print("❌ NOT FIXED: /api/sync still missing @require_auth()")
            issues_found.append("CRITICAL-1: /api/sync not protected")
except Exception as e:
    print(f"Error: {e}")
    issues_found.append(f"CRITICAL-1: Could not verify - {e}")

# Test 2: Verify session regeneration on login
print("\n[TEST 2] Verifying session fixation fix...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
    
    # Check for session.clear() in login function
    if 'session.clear()' in content and 'Regenerate session' in content:
        count = content.count('session.clear()')
        if count >= 2:  # Should be at least 2 (emergency + database login)
            print(f"✅ FIXED: Session regenerated on login ({count} locations)")
            fixes_verified.append("HIGH-1: Session fixation fixed")
        else:
            print(f"⚠️  PARTIAL: Session clearing found but may not cover all paths")
            issues_found.append("HIGH-1: Session fixation partially fixed")
    else:
        print("❌ NOT FIXED: Session not regenerated on login")
        issues_found.append("HIGH-1: Session fixation not fixed")
except Exception as e:
    print(f"Error: {e}")
    issues_found.append(f"HIGH-1: Could not verify - {e}")

# Test 3: Verify lockout persistence
print("\n[TEST 3] Verifying lockout persistence...")
try:
    with open('security.py', 'r') as f:
        content = f.read()
    
    if '_save_state' in content and '_load_state' in content:
        if 'state_file' in content and 'json.dump' in content:
            print("✅ FIXED: Lockout state now persisted to file")
            fixes_verified.append("HIGH-2: Lockout persistence added")
        else:
            print("⚠️  PARTIAL: State methods exist but persistence unclear")
            issues_found.append("HIGH-2: Lockout persistence unclear")
    else:
        print("❌ NOT FIXED: No state persistence methods found")
        issues_found.append("HIGH-2: Lockout not persistent")
except Exception as e:
    print(f"Error: {e}")
    issues_found.append(f"HIGH-2: Could not verify - {e}")

# Test 4: Verify HTTPS enforcement
print("\n[TEST 4] Verifying HTTPS enforcement...")
try:
    with open('app.py', 'r') as f:
        content = f.read()
    
    if 'enforce_https' in content or 'request.is_secure' in content:
        if 'redirect' in content and 'https://' in content:
            print("✅ FIXED: HTTPS enforcement middleware added")
            fixes_verified.append("HIGH-3: HTTPS enforcement implemented")
        else:
            print("⚠️  PARTIAL: HTTPS check exists but redirect unclear")
            issues_found.append("HIGH-3: HTTPS enforcement unclear")
    else:
        print("❌ NOT FIXED: No HTTPS enforcement found")
        issues_found.append("HIGH-3: HTTPS not enforced")
except Exception as e:
    print(f"Error: {e}")
    issues_found.append(f"HIGH-3: Could not verify - {e}")

# Test 5: Verify lockout_state.json in gitignore
print("\n[TEST 5] Verifying lockout state file in .gitignore...")
try:
    with open('../.gitignore', 'r') as f:
        content = f.read()
    
    if 'lockout_state.json' in content:
        print("✅ FIXED: lockout_state.json added to .gitignore")
        fixes_verified.append("EXTRA: .gitignore updated")
    else:
        print("⚠️  WARNING: lockout_state.json not in .gitignore")
        issues_found.append("EXTRA: .gitignore not updated")
except Exception as e:
    print(f"Error: {e}")

# Summary
print("\n" + "=" * 80)
print("VERIFICATION SUMMARY")
print("=" * 80)
print(f"\nFixes Verified: {len(fixes_verified)}")
for fix in fixes_verified:
    print(f"  ✅ {fix}")

if issues_found:
    print(f"\nIssues Found: {len(issues_found)}")
    for issue in issues_found:
        print(f"  ❌ {issue}")
    sys.exit(1)
else:
    print("\n✅ ALL CRITICAL AND HIGH PRIORITY FIXES VERIFIED")
    sys.exit(0)
