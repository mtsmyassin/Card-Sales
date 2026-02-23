"""Unit tests for helpers/ modules: auth_utils, validation, offline_queue, db, exceptions."""
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── helpers/auth_utils ────────────────────────────────────────────────────────

class TestRequireAuth:
    def _make_app(self):
        app = Flask(__name__)
        app.secret_key = "test-secret-key-that-is-32-chars!"
        return app

    def test_unauthenticated_returns_401(self):
        from helpers.auth_utils import require_auth
        app = self._make_app()

        @app.route('/test')
        @require_auth()
        def test_view():
            return "ok"

        with app.test_client() as c:
            resp = c.get('/test')
            assert resp.status_code == 401

    def test_wrong_role_returns_403(self):
        from helpers.auth_utils import require_auth
        app = self._make_app()

        @app.route('/test')
        @require_auth(allowed_roles=['admin'])
        def test_view():
            return "ok"

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['logged_in'] = True
                sess['user'] = 'testuser'
                sess['role'] = 'staff'
            resp = c.get('/test')
            assert resp.status_code == 403

    def test_correct_role_passes(self):
        from helpers.auth_utils import require_auth
        app = self._make_app()

        @app.route('/test')
        @require_auth(allowed_roles=['admin', 'super_admin'])
        def test_view():
            return "ok"

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['logged_in'] = True
                sess['user'] = 'admin1'
                sess['role'] = 'admin'
            resp = c.get('/test')
            assert resp.status_code == 200

    def test_no_role_restriction_passes_any_authenticated(self):
        from helpers.auth_utils import require_auth
        app = self._make_app()

        @app.route('/test')
        @require_auth()
        def test_view():
            return "ok"

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['logged_in'] = True
                sess['user'] = 'anyuser'
                sess['role'] = 'staff'
            resp = c.get('/test')
            assert resp.status_code == 200


class TestIsAdminRole:
    def test_admin_is_admin(self):
        from helpers.auth_utils import is_admin_role
        assert is_admin_role('admin') is True

    def test_super_admin_is_admin(self):
        from helpers.auth_utils import is_admin_role
        assert is_admin_role('super_admin') is True

    def test_staff_is_not_admin(self):
        from helpers.auth_utils import is_admin_role
        assert is_admin_role('staff') is False

    def test_manager_is_not_admin(self):
        from helpers.auth_utils import is_admin_role
        assert is_admin_role('manager') is False


class TestCanAccessPhoto:
    def test_admin_can_access_any(self):
        from helpers.auth_utils import can_access_photo
        assert can_access_photo("Carimas #1", "admin", "All") is True

    def test_staff_own_store(self):
        from helpers.auth_utils import can_access_photo
        assert can_access_photo("Carimas #1", "staff", "Carimas #1") is True

    def test_staff_other_store(self):
        from helpers.auth_utils import can_access_photo
        assert can_access_photo("Carimas #1", "staff", "Carimas #2") is False

    def test_null_photo_store_denied_for_non_admin(self):
        from helpers.auth_utils import can_access_photo
        assert can_access_photo(None, "staff", "Carimas #1") is False


# ── helpers/validation ────────────────────────────────────────────────────────

class TestValidateAuditEntry:
    def test_valid_entry(self):
        from helpers.validation import validate_audit_entry
        data = {"date": "2026-02-20", "reg": "Reg 1", "staff": "John",
                "gross": 100.0, "net": 90.0, "variance": -5.0}
        ok, msg = validate_audit_entry(data)
        assert ok is True
        assert msg == ""

    def test_missing_date(self):
        from helpers.validation import validate_audit_entry
        data = {"reg": "Reg 1", "staff": "John", "gross": 100.0, "net": 90.0, "variance": -5.0}
        ok, msg = validate_audit_entry(data)
        assert ok is False
        assert "date" in msg.lower()

    def test_invalid_date_format(self):
        from helpers.validation import validate_audit_entry
        data = {"date": "02/20/2026", "reg": "Reg 1", "staff": "John",
                "gross": 100.0, "net": 90.0, "variance": -5.0}
        ok, msg = validate_audit_entry(data)
        assert ok is False
        assert "date" in msg.lower()

    def test_negative_gross_rejected(self):
        from helpers.validation import validate_audit_entry
        data = {"date": "2026-02-20", "reg": "Reg 1", "staff": "John",
                "gross": -1.0, "net": 90.0, "variance": -5.0}
        ok, msg = validate_audit_entry(data)
        assert ok is False

    def test_invalid_store_rejected(self):
        from helpers.validation import validate_audit_entry
        data = {"date": "2026-02-20", "reg": "Reg 1", "staff": "John",
                "gross": 100.0, "net": 90.0, "variance": -5.0,
                "store": "BOGUS_STORE"}
        ok, msg = validate_audit_entry(data)
        assert ok is False
        assert "store" in msg.lower()

    def test_math_cross_check_catches_gross_mismatch(self):
        from helpers.validation import validate_audit_entry
        data = {"date": "2026-02-20", "reg": "Reg 1", "staff": "John",
                "gross": 999.0, "net": 90.0, "variance": -5.0,
                "breakdown": {"cash": 50.0, "ath": 10.0, "athm": 0.0,
                               "visa": 0.0, "mc": 0.0, "amex": 0.0,
                               "disc": 0.0, "wic": 0.0, "mcs": 0.0,
                               "sss": 0.0, "payouts": 0.0, "float": 100.0,
                               "actual": 95.0}}
        ok, msg = validate_audit_entry(data)
        assert ok is False
        assert "gross" in msg.lower()


class TestValidateUserData:
    def test_valid_new_user(self):
        from helpers.validation import validate_user_data
        data = {"username": "newuser", "password": "password123",
                "role": "staff", "store": "Carimas #1"}
        ok, msg = validate_user_data(data, is_update=False)
        assert ok is True

    def test_short_username_rejected(self):
        from helpers.validation import validate_user_data
        data = {"username": "ab", "password": "password123",
                "role": "staff", "store": "Carimas #1"}
        ok, msg = validate_user_data(data, is_update=False)
        assert ok is False
        assert "username" in msg.lower()

    def test_short_password_rejected(self):
        from helpers.validation import validate_user_data
        data = {"username": "newuser", "password": "short",
                "role": "staff", "store": "Carimas #1"}
        ok, msg = validate_user_data(data, is_update=False)
        assert ok is False
        assert "password" in msg.lower()

    def test_update_without_password_ok(self):
        from helpers.validation import validate_user_data
        data = {"username": "existuser", "role": "manager", "store": "Carimas #2"}
        ok, msg = validate_user_data(data, is_update=True)
        assert ok is True

    def test_invalid_role_rejected(self):
        from helpers.validation import validate_user_data
        data = {"username": "newuser", "password": "password123",
                "role": "superuser", "store": "Carimas #1"}
        ok, msg = validate_user_data(data, is_update=False)
        assert ok is False
        assert "role" in msg.lower()


# ── helpers/offline_queue ─────────────────────────────────────────────────────

class TestOfflineQueue:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        import helpers.offline_queue as oq
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(oq, "get_queue_path", lambda: q_file)
        monkeypatch.setattr(oq, "_IS_EPHEMERAL_FS", False)

        payload = {"date": "2026-02-20", "store": "Carimas #1", "gross": 100.0}
        oq.save_to_queue(payload)
        result = oq.load_queue()
        assert len(result) == 1
        assert result[0]["store"] == "Carimas #1"

    def test_clear_queue_removes_file(self, tmp_path, monkeypatch):
        import helpers.offline_queue as oq
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(oq, "get_queue_path", lambda: q_file)
        monkeypatch.setattr(oq, "_IS_EPHEMERAL_FS", False)

        oq.save_to_queue({"date": "2026-02-20"})
        assert os.path.exists(q_file)
        oq.clear_queue()
        assert not os.path.exists(q_file)

    def test_load_empty_returns_empty_list(self, tmp_path, monkeypatch):
        import helpers.offline_queue as oq
        monkeypatch.setattr(oq, "get_queue_path", lambda: str(tmp_path / "no_such_file.json"))
        assert oq.load_queue() == []

    def test_queue_full_returns_false(self, tmp_path, monkeypatch):
        import helpers.offline_queue as oq
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(oq, "get_queue_path", lambda: q_file)
        monkeypatch.setattr(oq, "_IS_EPHEMERAL_FS", False)
        monkeypatch.setattr(oq, "OFFLINE_QUEUE_MAX_SIZE", 1)

        assert oq.save_to_queue({"item": 1}) is True
        assert oq.save_to_queue({"item": 2}) is False

    def test_ephemeral_fs_raises_runtime_error(self, monkeypatch):
        import helpers.offline_queue as oq
        monkeypatch.setattr(oq, "_IS_EPHEMERAL_FS", True)

        with pytest.raises(RuntimeError):
            oq.save_to_queue({"item": 1})

    def test_corrupt_queue_starts_fresh(self, tmp_path, monkeypatch):
        import helpers.offline_queue as oq
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(oq, "get_queue_path", lambda: q_file)
        monkeypatch.setattr(oq, "_IS_EPHEMERAL_FS", False)

        with open(q_file, 'w') as f:
            f.write("NOT VALID JSON{{{")
        result = oq.load_queue()
        assert result == []


# ── helpers/db ────────────────────────────────────────────────────────────────

class TestDbRetry:
    def test_succeeds_on_first_try(self):
        from helpers.db import db_retry
        result = db_retry(lambda: "ok", label="test", max_attempts=3)
        assert result == "ok"

    def test_retries_and_succeeds(self):
        from helpers.db import db_retry
        call_count = [0]
        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("transient")
            return "recovered"

        with patch("time.sleep"):
            result = db_retry(flaky, label="test", max_attempts=3)
        assert result == "recovered"
        assert call_count[0] == 3

    def test_raises_after_max_attempts(self):
        from helpers.db import db_retry
        def always_fail():
            raise ConnectionError("down")

        with patch("time.sleep"):
            with pytest.raises(ConnectionError):
                db_retry(always_fail, label="test", max_attempts=2)


# ── helpers/exceptions ────────────────────────────────────────────────────────

class TestExceptions:
    def test_app_error_fields(self):
        from helpers.exceptions import AppError
        e = AppError("something went wrong", code="BAD", status=400)
        assert str(e) == "something went wrong"
        assert e.code == "BAD"
        assert e.status == 400

    def test_audit_not_found_defaults(self):
        from helpers.exceptions import AuditNotFoundError
        e = AuditNotFoundError(42)
        assert e.status == 404
        assert e.code == "NOT_FOUND"
        assert "42" in str(e)

    def test_duplicate_entry_error(self):
        from helpers.exceptions import DuplicateEntryError
        e = DuplicateEntryError(date="2026-02-20", store="Carimas #1", reg="Reg 1")
        assert e.status == 409
        assert "Duplicate" in str(e)

    def test_store_mismatch_error(self):
        from helpers.exceptions import StoreMismatchError
        e = StoreMismatchError(user_store="Carimas #1", target_store="Carimas #2")
        assert e.status == 403
        assert e.code == "STORE_MISMATCH"

    def test_validation_error(self):
        from helpers.exceptions import ValidationError
        e = ValidationError("bad input")
        assert e.status == 400
        assert e.code == "INVALID_INPUT"

    def test_database_unavailable(self):
        from helpers.exceptions import DatabaseUnavailableError
        e = DatabaseUnavailableError()
        assert e.status == 503

    def test_review_conflict(self):
        from helpers.exceptions import ReviewConflictError
        e = ReviewConflictError("already locked")
        assert e.status == 409
        assert e.code == "CONFLICT"
