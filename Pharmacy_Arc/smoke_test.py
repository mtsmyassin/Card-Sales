#!/usr/bin/env python3
"""
E2E smoke test for Farmacia Carimas.

Usage:
    python smoke_test.py                          # local (http://localhost:5000)
    python smoke_test.py https://carimas.up.railway.app
    python smoke_test.py --railway               # shorthand for Railway URL

Tests:
  1. App loads (HTTP 200, HTML contains 'app.init')
  2. Login API returns session cookie
  3. /api/list returns a JSON array
  4. /api/diagnostics returns JSON with database.status == 'connected'
  5. /api/zreport/photos?entry_id=9999 returns 404 JSON (not HTML crash)
  6. /api/zreport/signed_url?photo_id=9999 returns 404 JSON (not HTML crash)

Exit code 0 = all passed. Non-zero = failures.
"""
import sys
import json
import os
import requests

RAILWAY_URL = "https://carimas.up.railway.app"
DEFAULT_URL  = "http://localhost:5000"


def check(label, condition, detail=""):
    mark = "✅" if condition else "❌"
    print(f"  {mark} {label}" + (f"  →  {detail}" if detail else ""))
    return condition


def run_smoke(base_url: str) -> int:
    base_url = base_url.rstrip("/")
    print(f"\n🔬 Smoke test: {base_url}\n")
    failures = 0
    session = requests.Session()

    # --- 1. App loads ---
    try:
        r = session.get(base_url, timeout=10)
        ok = r.status_code == 200 and "app.init" in r.text
        if not check("App loads (200, app.init present)", ok, f"status={r.status_code}"):
            failures += 1
    except Exception as e:
        check("App loads", False, str(e))
        failures += 1
        print("  ⚠️  Cannot reach server — aborting remaining tests.")
        return failures

    # --- 2. Login ---
    username = os.environ.get("SMOKE_USER", "")
    password = os.environ.get("SMOKE_PASS", "")
    if not username or not password:
        print("  ⚠️  SMOKE_USER / SMOKE_PASS not set — skipping authenticated tests.")
        print("     Set them and re-run to get full coverage.\n")
        return failures

    try:
        r = session.post(
            f"{base_url}/api/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        login_ok = r.status_code == 200 and r.json().get("status") == "success"
        if not check("Login succeeds", login_ok, f"status={r.status_code} body={r.text[:80]}"):
            failures += 1
            print("  ⚠️  Cannot authenticate — skipping auth-required tests.")
            return failures
    except Exception as e:
        check("Login succeeds", False, str(e))
        failures += 1
        return failures

    # --- 3. /api/list returns array ---
    try:
        r = session.get(f"{base_url}/api/list", timeout=15)
        data = r.json()
        ok = r.status_code == 200 and isinstance(data, list)
        if not check("/api/list → JSON array", ok, f"status={r.status_code} type={type(data).__name__} len={len(data) if isinstance(data, list) else '?'}"):
            failures += 1
    except Exception as e:
        check("/api/list → JSON array", False, str(e))
        failures += 1

    # --- 4. /api/diagnostics ---
    try:
        r = session.get(f"{base_url}/api/diagnostics", timeout=10)
        if r.status_code == 403:
            check("/api/diagnostics (admin only — non-admin user)", True, "403 as expected")
        else:
            data = r.json()
            db_ok = data.get("database", {}).get("status") == "connected"
            bucket_ok = data.get("storage", {}).get("z_reports_bucket") == "exists"
            if not check("/api/diagnostics DB connected", db_ok, str(data.get("database", {}))):
                failures += 1
            if not check("/api/diagnostics bucket exists", bucket_ok, str(data.get("storage", {}))):
                failures += 1
    except Exception as e:
        check("/api/diagnostics", False, str(e))
        failures += 1

    # --- 5. /api/zreport/photos with bad entry_id → JSON 404, not crash ---
    try:
        r = session.get(f"{base_url}/api/zreport/photos?entry_id=999999999", timeout=10)
        is_json = "application/json" in r.headers.get("Content-Type", "")
        ok = r.status_code in (404, 403) and is_json
        if not check("/api/zreport/photos?entry_id=999999999 → JSON 404", ok,
                     f"status={r.status_code} ct={r.headers.get('Content-Type','')}"):
            failures += 1
    except Exception as e:
        check("/api/zreport/photos (bad id)", False, str(e))
        failures += 1

    # --- 6. /api/zreport/signed_url with bad photo_id → JSON 404, not crash ---
    try:
        r = session.get(f"{base_url}/api/zreport/signed_url?photo_id=999999999", timeout=10)
        is_json = "application/json" in r.headers.get("Content-Type", "")
        ok = r.status_code in (404, 403) and is_json
        if not check("/api/zreport/signed_url?photo_id=999999999 → JSON 404", ok,
                     f"status={r.status_code} ct={r.headers.get('Content-Type','')}"):
            failures += 1
    except Exception as e:
        check("/api/zreport/signed_url (bad id)", False, str(e))
        failures += 1

    # --- 7. Legacy IDOR route returns JSON on bad id ---
    try:
        r = session.get(f"{base_url}/api/audit/999999999/zreport_image", timeout=10)
        is_json = "application/json" in r.headers.get("Content-Type", "")
        ok = r.status_code in (404, 403) and is_json
        if not check("/api/audit/999999999/zreport_image → JSON 404", ok,
                     f"status={r.status_code}"):
            failures += 1
    except Exception as e:
        check("/api/audit/id/zreport_image (bad id)", False, str(e))
        failures += 1

    print()
    if failures:
        print(f"❌  {failures} check(s) FAILED.")
    else:
        print("✅  All checks passed.")
    return failures


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--railway" in args:
        url = RAILWAY_URL
    elif args and not args[0].startswith("--"):
        url = args[0]
    else:
        url = DEFAULT_URL

    sys.exit(run_smoke(url))
