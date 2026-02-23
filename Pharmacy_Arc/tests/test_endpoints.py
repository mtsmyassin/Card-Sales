"""Endpoint integration tests — validates routes, RBAC, error codes, and edge cases."""
import importlib
import json
import os
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

ENV = {
    "FLASK_SECRET_KEY": "a" * 64,
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "fake-anon-key",
    "SUPABASE_SERVICE_KEY": "fake-service-key",
    "TELEGRAM_WEBHOOK_SECRET": "test-secret",
}


def _load_app():
    """Reload the Flask app with mocked Supabase clients."""
    with patch.dict(os.environ, ENV):
        with patch("supabase.create_client", return_value=MagicMock()):
            with patch("config.Config.startup_check"):
                import app as app_module
                importlib.reload(app_module)
                app_module.app.config["TESTING"] = True
                app_module.app.config["WTF_CSRF_ENABLED"] = False
                app_module.app.config["RATELIMIT_ENABLED"] = False
                return app_module


@pytest.fixture
def flask_app():
    app_mod = _load_app()
    yield app_mod


@pytest.fixture
def client(flask_app):
    return flask_app.app.test_client()


def _set_session(client, role="admin", store="Main", user="testadmin"):
    """Helper to set up an authenticated session."""
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["user"] = user
        sess["role"] = role
        sess["store"] = store
        sess["last_active"] = "2099-01-01T00:00:00+00:00"


def _mock_db():
    """Create a mock DB client with chainable Supabase methods."""
    mock = MagicMock()
    # By default, .execute() returns empty result
    mock.table.return_value.select.return_value.execute.return_value = MagicMock(data=[], count=0)
    return mock


# ── Main Blueprint ────────────────────────────────────────────────────────────


class TestMainBlueprint:
    def test_index_unauthenticated_shows_login(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_favicon_returns_ok_or_204(self, client):
        r = client.get("/favicon.ico")
        assert r.status_code in (200, 204)

    def test_health_returns_json(self, client, flask_app):
        import extensions
        db = MagicMock()
        db.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"username": "x"}])
        with patch.object(extensions, "supabase_admin", db), \
             patch.object(extensions, "supabase", db):
            r = client.get("/health")
        data = r.get_json()
        assert "status" in data
        assert "admin_client" in data

    def test_metrics_requires_admin(self, client):
        _set_session(client, role="staff")
        r = client.get("/metrics")
        assert r.status_code == 403

    def test_metrics_returns_data_for_admin(self, client, flask_app):
        _set_session(client, role="admin")
        r = client.get("/metrics")
        assert r.status_code == 200
        data = r.get_json()
        assert "version" in data
        assert "offline_queue_depth" in data
        assert "admin_client_available" in data


# ── Auth Blueprint ────────────────────────────────────────────────────────────


class TestAuthBlueprint:
    def test_login_missing_credentials(self, client):
        r = client.post("/api/login", json={"username": "", "password": ""})
        data = r.get_json()
        assert r.status_code == 400
        assert data.get("code") == "BAD_REQUEST"

    def test_get_logo_requires_auth(self, client):
        r = client.post("/api/get_logo", json={"store": "Carimas"})
        assert r.status_code == 401
        assert r.get_json().get("code") == "AUTH_REQUIRED"

    def test_get_logo_authenticated(self, client, flask_app):
        _set_session(client)
        r = client.post("/api/get_logo", json={"store": "Carimas"})
        assert r.status_code == 200


# ── Audits Blueprint ─────────────────────────────────────────────────────────


class TestAuditsBlueprintSave:
    def test_save_requires_auth(self, client):
        r = client.post("/api/save", json={"date": "2025-01-01"})
        assert r.status_code == 401

    def test_save_missing_body(self, client):
        _set_session(client)
        r = client.post("/api/save", content_type="application/json", data="null")
        data = r.get_json()
        assert r.status_code == 400
        assert data.get("code") == "BAD_REQUEST"

    def test_save_invalid_entry(self, client):
        _set_session(client)
        r = client.post("/api/save", json={"date": "bad"})
        data = r.get_json()
        assert r.status_code == 400
        assert data.get("code") == "INVALID_INPUT"

    def test_save_duplicate_returns_409(self, client, flask_app):
        _set_session(client)
        import extensions
        db = _mock_db()
        # Duplicate check returns existing record
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
        with patch.object(extensions, "supabase_admin", db), \
             patch.object(extensions, "supabase", db):
            r = client.post("/api/save", json={
                "date": "2025-01-01", "reg": "R1", "staff": "Alice",
                "gross": 100, "net": 90, "variance": 0, "store": "Main",
            })
        assert r.status_code == 409
        assert r.get_json().get("code") == "DUPLICATE"


class TestAuditsBlueprintUpdate:
    def test_update_staff_denied(self, client):
        _set_session(client, role="staff", user="staffuser")
        r = client.post("/api/update", json={"id": 1})
        assert r.status_code == 403
        assert r.get_json().get("code") == "FORBIDDEN"

    def test_update_missing_id(self, client):
        _set_session(client, role="manager")
        r = client.post("/api/update", json={"date": "2025-01-01"})
        data = r.get_json()
        assert r.status_code == 400
        assert data.get("code") == "MISSING_PARAM"


class TestAuditsBlueprintDelete:
    def test_delete_staff_denied(self, client):
        _set_session(client, role="staff", user="staffuser")
        r = client.post("/api/delete", json={"id": 1})
        assert r.status_code == 403
        assert r.get_json().get("code") == "FORBIDDEN"

    def test_delete_missing_id(self, client):
        _set_session(client, role="admin")
        r = client.post("/api/delete", json={})
        data = r.get_json()
        assert r.status_code == 400
        assert data.get("code") == "MISSING_PARAM"

    def test_delete_not_found(self, client, flask_app):
        _set_session(client, role="admin")
        import extensions
        db = _mock_db()
        # Fetch for before-state returns nothing
        db.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(extensions, "supabase_admin", db), \
             patch.object(extensions, "supabase", db):
            r = client.post("/api/delete", json={"id": 9999})
        assert r.status_code == 404
        assert r.get_json().get("code") == "NOT_FOUND"


class TestAuditsBlueprintList:
    def test_list_requires_auth(self, client):
        r = client.get("/api/list")
        assert r.status_code == 401

    def test_list_success(self, client, flask_app):
        _set_session(client, role="admin")
        import extensions
        db = _mock_db()
        db.table.return_value.select.return_value.is_.return_value.order.return_value.range.return_value.execute.return_value = MagicMock(data=[])
        db.table.return_value.select.return_value.in_.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(extensions, "supabase_admin", db), \
             patch.object(extensions, "supabase", db):
            r = client.get("/api/list")
        assert r.status_code == 200


# ── Users Blueprint ───────────────────────────────────────────────────────────


class TestUsersBlueprint:
    def test_list_users_staff_denied(self, client):
        _set_session(client, role="staff")
        r = client.get("/api/users/list")
        assert r.status_code == 403
        assert r.get_json().get("code") == "FORBIDDEN"

    def test_save_user_missing_data(self, client):
        _set_session(client, role="admin")
        r = client.post("/api/users/save", content_type="application/json", data="null")
        assert r.status_code == 400
        assert r.get_json().get("code") == "BAD_REQUEST"

    def test_save_user_missing_username(self, client):
        _set_session(client, role="admin")
        r = client.post("/api/users/save", json={"password": "x"})
        assert r.status_code == 400
        assert r.get_json().get("code") == "MISSING_PARAM"

    def test_delete_user_self_forbidden(self, client, flask_app):
        _set_session(client, role="admin", user="testadmin")
        import extensions
        db = _mock_db()
        with patch.object(extensions, "supabase_admin", db), \
             patch.object(extensions, "supabase", db):
            r = client.post("/api/users/delete", json={"username": "testadmin"})
        assert r.status_code == 403
        assert r.get_json().get("code") == "FORBIDDEN"

    def test_delete_user_not_found(self, client, flask_app):
        _set_session(client, role="admin", user="admin1")
        import extensions
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        with patch.object(extensions, "supabase_admin", db), \
             patch.object(extensions, "supabase", db):
            r = client.post("/api/users/delete", json={"username": "ghost"})
        assert r.status_code == 404
        assert r.get_json().get("code") == "NOT_FOUND"


# ── Telegram Blueprint ────────────────────────────────────────────────────────


class TestTelegramBlueprint:
    def test_webhook_missing_secret(self, client):
        r = client.post("/api/telegram/webhook", json={"update_id": 1},
                        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
        assert r.status_code == 403

    def test_webhook_empty_body(self, client):
        from config import Config
        with patch.object(Config, "TELEGRAM_WEBHOOK_SECRET", "test-secret"):
            r = client.post("/api/telegram/webhook",
                            content_type="application/json", data="null",
                            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"})
        assert r.status_code == 400

    def test_photos_missing_entry_id(self, client):
        _set_session(client)
        r = client.get("/api/zreport/photos")
        assert r.status_code == 400
        assert r.get_json().get("code") == "MISSING_PARAM"

    def test_signed_url_missing_photo_id(self, client):
        _set_session(client)
        r = client.get("/api/zreport/signed_url")
        assert r.status_code == 400
        assert r.get_json().get("code") == "MISSING_PARAM"

    def test_delete_photo_staff_denied(self, client):
        _set_session(client, role="staff")
        r = client.delete("/api/zreport/photo/1")
        assert r.status_code == 403

    def test_delete_photo_not_found(self, client, flask_app):
        _set_session(client, role="admin")
        import extensions
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=None)
        with patch.object(extensions, "supabase_admin", db), \
             patch.object(extensions, "supabase", db):
            r = client.delete("/api/zreport/photo/999")
        assert r.status_code == 404
        assert r.get_json().get("code") == "NOT_FOUND"


# ── Diagnostics Blueprint ────────────────────────────────────────────────────


class TestDiagnosticsBlueprint:
    def test_diagnostics_staff_denied(self, client):
        _set_session(client, role="staff")
        r = client.get("/api/diagnostics")
        assert r.status_code == 403

    def test_diagnostics_admin_ok(self, client, flask_app):
        _set_session(client, role="admin")
        import extensions
        from audit_log import get_audit_logger

        db = _mock_db()
        db.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"username": "x"}])
        db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[], count=0)
        db.storage.from_.return_value.list.return_value = []

        audit_logger = MagicMock()
        audit_logger.verify_integrity.return_value = (True, [])
        audit_logger.get_entries.return_value = []

        with patch.object(extensions, "supabase_admin", db), \
             patch.object(extensions, "supabase", db), \
             patch("routes.diagnostics.get_audit_logger", return_value=audit_logger):
            r = client.get("/api/diagnostics")
        assert r.status_code == 200
        data = r.get_json()
        assert "version" in data
        assert "database" in data


# ── Error Code Consistency ────────────────────────────────────────────────────


class TestErrorCodes:
    """Verify that error responses include the 'code' field (Step 2 validation)."""

    def test_404_has_code(self, client):
        r = client.get("/nonexistent-endpoint-xyz")
        data = r.get_json()
        assert r.status_code == 404
        assert data.get("code") == "NOT_FOUND"

    def test_405_has_code(self, client):
        r = client.delete("/api/login")
        data = r.get_json()
        assert r.status_code == 405
        assert data.get("code") == "METHOD_NOT_ALLOWED"

    def test_401_has_code(self, client):
        r = client.get("/api/list")
        data = r.get_json()
        assert r.status_code == 401
        assert data.get("code") == "AUTH_REQUIRED"
