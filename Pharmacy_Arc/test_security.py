#!/usr/bin/env python3
"""
Security Test Suite for Pharmacy Management System

Tests authentication, RBAC, brute-force protection, and audit logging.
"""

import sys
from pathlib import Path

try:
    from audit_log import AuditLogger
    from config import Config
    from security import LoginAttemptTracker, PasswordHasher
except ImportError:
    print("Error: Required modules not found. Please run: pip install -r requirements.txt")
    sys.exit(1)


class TestResult:
    """Store test results."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def add_pass(self, name):
        self.passed += 1
        self.tests.append((name, True, None))
        print(f"  ✅ {name}")

    def add_fail(self, name, error):
        self.failed += 1
        self.tests.append((name, False, error))
        print(f"  ❌ {name}: {error}")

    def summary(self):
        total = self.passed + self.failed
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        print(f"Total Tests: {total}")
        print(f"Passed: {self.passed} ({self.passed / total * 100:.1f}%)" if total > 0 else "Passed: 0")
        print(f"Failed: {self.failed} ({self.failed / total * 100:.1f}%)" if total > 0 else "Failed: 0")

        if self.failed > 0:
            print("\nFailed Tests:")
            for name, passed, error in self.tests:
                if not passed:
                    print(f"  - {name}: {error}")

        return self.failed == 0


def test_password_hashing(results):
    """Test password hashing and verification."""
    print("\n[Test Suite 1] Password Hashing")
    print("-" * 70)

    hasher = PasswordHasher()

    # Test 1: Hash generation
    password = "TestPassword123!"  # noqa: S105 — test fixture
    hash1 = ""
    try:
        hash1 = hasher.hash_password(password)

        if not hash1.startswith("$2b$"):
            results.add_fail("Hash generation format", "Hash doesn't start with $2b$")
        elif len(hash1) < 50:
            results.add_fail("Hash generation length", f"Hash too short: {len(hash1)}")
        else:
            results.add_pass("Hash generation")
    except Exception as e:
        results.add_fail("Hash generation", str(e))

    # Test 2: Different hashes for same password (salt randomization)
    try:
        hash2 = hasher.hash_password(password)
        if hash1 == hash2:
            results.add_fail("Salt randomization", "Same password produced identical hashes")
        else:
            results.add_pass("Salt randomization")
    except Exception as e:
        results.add_fail("Salt randomization", str(e))

    # Test 3: Correct password verification
    try:
        if hasher.verify_password(password, hash1):
            results.add_pass("Correct password verification")
        else:
            results.add_fail("Correct password verification", "Failed to verify correct password")
    except Exception as e:
        results.add_fail("Correct password verification", str(e))

    # Test 4: Incorrect password rejection
    try:
        if not hasher.verify_password("WrongPassword", hash1):
            results.add_pass("Incorrect password rejection")
        else:
            results.add_fail("Incorrect password rejection", "Accepted wrong password")
    except Exception as e:
        results.add_fail("Incorrect password rejection", str(e))

    # Test 5: Empty password handling
    try:
        if not hasher.verify_password("", hash1):
            results.add_pass("Empty password rejection")
        else:
            results.add_fail("Empty password rejection", "Accepted empty password")
    except Exception as e:
        results.add_fail("Empty password rejection", str(e))


def test_brute_force_protection(results):
    """Test login attempt tracking and lockout."""
    print("\n[Test Suite 2] Brute-Force Protection")
    print("-" * 70)

    tracker = LoginAttemptTracker(max_attempts=3, lockout_duration_minutes=1)
    test_user = "test_user_brute_force"

    # Test 1: Not locked initially
    try:
        if not tracker.is_locked_out(test_user):
            results.add_pass("Initial state not locked")
        else:
            results.add_fail("Initial state not locked", "User locked without attempts")
    except Exception as e:
        results.add_fail("Initial state not locked", str(e))

    # Test 2: Record failed attempts
    try:
        for i in range(2):
            is_locked, remaining = tracker.record_failed_attempt(test_user)
            if is_locked:
                results.add_fail(f"Failed attempt {i + 1}", f"Locked after {i + 1} attempts")
                break
        else:
            results.add_pass("Failed attempts recorded correctly")
    except Exception as e:
        results.add_fail("Failed attempts recorded", str(e))

    # Test 3: Lockout after max attempts
    try:
        is_locked, remaining = tracker.record_failed_attempt(test_user)
        if is_locked and remaining == 0:
            results.add_pass("Lockout after max attempts")
        else:
            results.add_fail("Lockout after max attempts", f"Not locked: {is_locked}, remaining: {remaining}")
    except Exception as e:
        results.add_fail("Lockout after max attempts", str(e))

    # Test 4: Locked state persists
    try:
        if tracker.is_locked_out(test_user):
            results.add_pass("Locked state persists")
        else:
            results.add_fail("Locked state persists", "User not locked after lockout")
    except Exception as e:
        results.add_fail("Locked state persists", str(e))

    # Test 5: Get lockout remaining time
    try:
        remaining = tracker.get_lockout_remaining(test_user)
        if remaining is not None and remaining > 0:
            results.add_pass("Get lockout remaining time")
        else:
            results.add_fail("Get lockout remaining time", f"Invalid remaining time: {remaining}")
    except Exception as e:
        results.add_fail("Get lockout remaining time", str(e))

    # Test 6: Successful login clears attempts
    try:
        tracker2 = LoginAttemptTracker(max_attempts=3, lockout_duration_minutes=1)
        test_user2 = "test_user_success"

        tracker2.record_failed_attempt(test_user2)
        tracker2.record_successful_login(test_user2)

        if tracker2.get_attempt_count(test_user2) == 0:
            results.add_pass("Successful login clears attempts")
        else:
            results.add_fail("Successful login clears attempts", "Attempts not cleared")
    except Exception as e:
        results.add_fail("Successful login clears attempts", str(e))


def test_audit_logging(results):
    """Test audit logging functionality."""
    print("\n[Test Suite 3] Audit Logging")
    print("-" * 70)

    # Use a test log file
    test_log = Path("test_audit_log.jsonl")
    if test_log.exists():
        test_log.unlink()

    logger = AuditLogger(str(test_log))

    # Test 1: Log creation
    try:
        logger.log(
            action="CREATE",
            actor="test_user",
            role="admin",
            entity_type="TEST_ENTITY",
            entity_id="123",
            after={"value": "test"},
            success=True,
        )

        if test_log.exists():
            results.add_pass("Create audit log entry")
        else:
            results.add_fail("Create audit log entry", "Log file not created")
    except Exception as e:
        results.add_fail("Create audit log entry", str(e))

    # Test 2: Read entries
    entries: list = []
    try:
        entries = logger.get_entries(limit=10)
        if len(entries) > 0:
            results.add_pass("Read audit log entries")
        else:
            results.add_fail("Read audit log entries", "No entries found")
    except Exception as e:
        results.add_fail("Read audit log entries", str(e))

    # Test 3: Entry structure
    try:
        entry = entries[0]
        required_fields = [
            "timestamp",
            "action",
            "actor",
            "role",
            "entity_type",
            "success",
            "previous_hash",
            "entry_hash",
        ]

        missing = [f for f in required_fields if f not in entry]
        if not missing:
            results.add_pass("Entry has required fields")
        else:
            results.add_fail("Entry has required fields", f"Missing: {missing}")
    except Exception as e:
        results.add_fail("Entry has required fields", str(e))

    # Test 4: Hash chain integrity
    try:
        logger.log(
            action="UPDATE",
            actor="test_user",
            role="admin",
            entity_type="TEST_ENTITY",
            entity_id="123",
            before={"value": "test"},
            after={"value": "updated"},
            success=True,
        )

        is_valid, errors = logger.verify_integrity()
        if is_valid:
            results.add_pass("Hash chain integrity")
        else:
            results.add_fail("Hash chain integrity", f"Integrity check failed: {errors}")
    except Exception as e:
        results.add_fail("Hash chain integrity", str(e))

    # Test 5: Filtering by actor
    try:
        logger.log(
            action="DELETE",
            actor="other_user",
            role="manager",
            entity_type="TEST_ENTITY",
            entity_id="456",
            success=True,
        )

        filtered = logger.get_entries(actor="test_user")
        if all(e["actor"] == "test_user" for e in filtered):
            results.add_pass("Filter entries by actor")
        else:
            results.add_fail("Filter entries by actor", "Filter returned wrong entries")
    except Exception as e:
        results.add_fail("Filter entries by actor", str(e))

    # Test 6: Filtering by action
    try:
        filtered = logger.get_entries(action="CREATE")
        if all(e["action"] == "CREATE" for e in filtered):
            results.add_pass("Filter entries by action")
        else:
            results.add_fail("Filter entries by action", "Filter returned wrong entries")
    except Exception as e:
        results.add_fail("Filter entries by action", str(e))

    # Cleanup
    if test_log.exists():
        test_log.unlink()


def test_configuration(results):
    """Test configuration loading and validation."""
    print("\n[Test Suite 4] Configuration")
    print("-" * 70)

    # Test 1: Config loaded
    try:
        if Config.PORT and Config.SECRET_KEY:
            results.add_pass("Configuration loaded")
        else:
            results.add_fail("Configuration loaded", "Missing required config")
    except Exception as e:
        results.add_fail("Configuration loaded", str(e))

    # Test 2: Secret key strength
    try:
        if len(Config.SECRET_KEY) >= 32:
            results.add_pass("Secret key strength")
        else:
            results.add_fail("Secret key strength", f"Key too short: {len(Config.SECRET_KEY)}")
    except Exception as e:
        results.add_fail("Secret key strength", str(e))

    # Test 3: Port range
    try:
        if 1024 <= Config.PORT <= 65535:
            results.add_pass("Port range valid")
        else:
            results.add_fail("Port range valid", f"Invalid port: {Config.PORT}")
    except Exception as e:
        results.add_fail("Port range valid", str(e))

    # Test 4: Emergency accounts format
    try:
        accounts = Config.load_emergency_accounts()
        if isinstance(accounts, dict):
            results.add_pass("Emergency accounts format")
        else:
            results.add_fail("Emergency accounts format", f"Wrong type: {type(accounts)}")
    except Exception as e:
        results.add_fail("Emergency accounts format", str(e))

    # Test 5: Security settings
    try:
        if (
            Config.MAX_LOGIN_ATTEMPTS >= 1
            and Config.LOCKOUT_DURATION_MINUTES >= 1
            and Config.SESSION_TIMEOUT_MINUTES >= 5
        ):
            results.add_pass("Security settings valid")
        else:
            results.add_fail("Security settings valid", "Invalid security parameters")
    except Exception as e:
        results.add_fail("Security settings valid", str(e))


def main():
    """Run all test suites."""
    print("\n" + "=" * 70)
    print("PHARMACY MANAGEMENT SYSTEM - SECURITY TEST SUITE")
    print("=" * 70)
    print("\nRunning comprehensive security tests...")

    results = TestResult()

    try:
        test_configuration(results)
        test_password_hashing(results)
        test_brute_force_protection(results)
        test_audit_logging(results)

        success = results.summary()

        if success:
            print("\n✅ ALL TESTS PASSED!")
            return 0
        else:
            print("\n❌ SOME TESTS FAILED")
            print("Please review the failures above and fix the issues.")
            return 1

    except Exception as e:
        print(f"\n\n❌ Test suite crashed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
