"""
Regression tests for the Feb 2026 bug-fix batch.

Covers:
- BUG 1/2/6: admin client used for all audits table writes & reads
- BUG 3: offline queue UTF-8 roundtrip
- BUG 4: sync() exception is logged, not swallowed
- BUG 5: APScheduler atexit shutdown registered
- CSRF: protection initialised; login + webhook exempt; token endpoint exists
"""
import os
import sys
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENV = {
    "FLASK_SECRET_KEY": "test-key-minimum-32-chars-long-ok!!",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_KEY": "test-key",
}


def _load_app():
    with patch.dict(os.environ, ENV):
        with patch("supabase.create_client", return_value=MagicMock()):
            with patch("config.Config.startup_check"):
                import importlib
                import app as app_module
                importlib.reload(app_module)
                return app_module


# ── BUG 1: save() uses admin client for INSERT ────────────────────────────────

class TestSaveUsesAdminClient:
    def test_save_insert_line_uses_admin_or_supabase(self):
        """routes/audits.py must use insert_audit() or get_db() for audits INSERT in save()."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "audits.py"),
            encoding="utf-8",
        ).read()
        # find the save() function block and confirm the insert uses service layer or admin
        save_block = src[src.index("def save():"):src.index("def sync():")]
        assert "insert_audit" in save_block or "extensions.get_db()" in save_block, (
            "save() must use insert_audit() or extensions.get_db() for INSERT to bypass RLS"
        )
        assert "insert_audit" in save_block or ".table(\"audits\").insert" in save_block, (
            "save() must use insert_audit() or inline INSERT into audits table"
        )


# ── BUG 2: sync() uses admin client for dup-check and INSERT ─────────────────

class TestSyncUsesAdminClient:
    def _get_sync_block(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "audits.py"),
            encoding="utf-8",
        ).read()
        return src[src.index("def sync():"):src.index("def update():")]

    def test_sync_dup_check_uses_admin(self):
        block = self._get_sync_block()
        assert "_db = extensions.get_db()" in block, (
            "sync() must assign _db = extensions.get_db() before dup check"
        )

    def test_sync_insert_uses_db_variable(self):
        block = self._get_sync_block()
        assert "_db.table(\"audits\").insert" in block, (
            "sync() must use _db (admin client) for INSERT"
        )


# ── BUG 6: update() and delete() use admin client ────────────────────────────

class TestUpdateDeleteUseAdminClient:
    def _src(self):
        return open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "audits.py"),
            encoding="utf-8",
        ).read()

    def test_update_before_state_uses_admin(self):
        src = self._src()
        update_block = src[src.index("def update():"):src.index("def delete():")]
        # After service-layer refactor, update() uses get_audit() (which calls get_db() internally)
        assert "get_audit" in update_block or "extensions.get_db().table(\"audits\").select" in update_block

    def test_update_write_uses_admin(self):
        src = self._src()
        update_block = src[src.index("def update():"):src.index("def delete():")]
        # After service-layer refactor, update() uses update_audit() (which calls get_db() internally)
        assert "update_audit" in update_block or "extensions.get_db().table(\"audits\").update" in update_block

    def test_delete_before_state_uses_admin(self):
        src = self._src()
        # delete() block ends at next route
        delete_start = src.index("def delete():")
        delete_end = src.index("@bp.route", delete_start)
        delete_block = src[delete_start:delete_end]
        # After service-layer refactor, delete() uses get_audit() (which calls get_db() internally)
        assert "get_audit" in delete_block or "extensions.get_db().table(\"audits\").select" in delete_block

    def test_delete_write_uses_admin(self):
        """delete() soft-delete must use soft_delete_audit() or get_db() with deleted_at."""
        src = self._src()
        delete_start = src.index("def delete():")
        delete_end = src.index("@bp.route", delete_start)
        delete_block = src[delete_start:delete_end]
        # After service-layer refactor, delete() uses soft_delete_audit() (which calls get_db() internally)
        assert "soft_delete_audit" in delete_block or "extensions.get_db().table(\"audits\")" in delete_block


# ── BUG 3: offline queue UTF-8 roundtrip ─────────────────────────────────────

class TestOfflineQueueEncoding:
    def test_utf8_roundtrip(self, tmp_path, monkeypatch):
        """Accented store names survive a save → load cycle on Windows."""
        import helpers.offline_queue as oq
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(oq, "get_queue_path", lambda: q_file)
        monkeypatch.setattr(oq, "_IS_EPHEMERAL_FS", False)

        payload = {"store": "Farmacía #1", "date": "01/01/2026", "gross": 100.0}
        oq.save_to_queue(payload)
        result = oq.load_queue()
        assert len(result) == 1
        assert result[0]["store"] == "Farmacía #1", (
            "Accented characters must survive UTF-8 queue roundtrip"
        )

    def test_queue_file_written_with_utf8(self, tmp_path, monkeypatch):
        """Queue file on disk must be valid UTF-8 (not cp1252-encoded)."""
        import helpers.offline_queue as oq
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(oq, "get_queue_path", lambda: q_file)
        monkeypatch.setattr(oq, "_IS_EPHEMERAL_FS", False)

        oq.save_to_queue({"store": "Carimas Ñoño"})
        raw = open(q_file, "rb").read()
        # Must decode as UTF-8 without errors
        raw.decode("utf-8")


# ── BUG 4: sync() logs exceptions, doesn't swallow them ──────────────────────

class TestSyncLogsExceptions:
    def test_bare_except_replaced(self):
        """sync() must not have a bare 'except:' — only 'except Exception'."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "audits.py"),
            encoding="utf-8",
        ).read()
        sync_block = src[src.index("def sync():"):src.index("def update():")]
        assert "except:" not in sync_block, (
            "sync() must not use bare except: — use except Exception as exc"
        )

    def test_sync_exception_logged(self):
        """sync() exception message must appear in warning log, not be swallowed."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "audits.py"),
            encoding="utf-8",
        ).read()
        sync_block = src[src.index("def sync():"):src.index("def update():")]
        assert "logger.warning" in sync_block, (
            "sync() must log a warning when an insert fails"
        )


# ── BUG 5: APScheduler atexit shutdown registered ────────────────────────────

class TestAPSchedulerShutdown:
    def test_atexit_registered(self):
        """APScheduler init_scheduler must register an atexit shutdown handler."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "helpers", "scheduler.py"),
            encoding="utf-8",
        ).read()
        assert "atexit.register" in src, (
            "APScheduler must register atexit shutdown to prevent thread leak on deploy"
        )
        assert "scheduler.shutdown" in src


# ── CSRF: protection wired up ─────────────────────────────────────────────────

class TestCSRFProtection:
    def test_csrf_token_endpoint_exists(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "auth.py"),
            encoding="utf-8",
        ).read()
        assert "'/api/csrf-token'" in src, "/api/csrf-token endpoint must exist"
        assert "generate_csrf" in src

    def test_login_is_csrf_exempt(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "auth.py"),
            encoding="utf-8",
        ).read()
        login_block = src[src.index("@bp.route('/api/login'"):src.index("def login():") + 50]
        assert "@extensions.csrf.exempt" in login_block, "/api/login must be @csrf.exempt"

    def test_telegram_webhook_is_csrf_exempt(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "telegram.py"),
            encoding="utf-8",
        ).read()
        wh_block = src[src.index("@bp.route('/api/telegram/webhook'"):
                       src.index("def telegram_webhook():") + 50]
        assert "@extensions.csrf.exempt" in wh_block, "/api/telegram/webhook must be @csrf.exempt"

    def test_csrf_protect_initialized(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        assert "csrf.init_app(app)" in src, "CSRF must be initialised via csrf.init_app(app)"

    def test_frontend_fetch_patch_present(self):
        """Main UI JS must patch window.fetch to inject X-CSRFToken."""
        import re
        templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        with open(os.path.join(templates_dir, "main.html"), encoding="utf-8") as f:
            src = f.read()
        # Resolve {% include %} directives so we can check included JS content
        def _resolve(match):
            inc_path = os.path.join(templates_dir, match.group(1))
            if os.path.exists(inc_path):
                with open(inc_path, encoding="utf-8") as fh:
                    return fh.read()
            return match.group(0)
        src = re.sub(r"\{%\s*include\s+['\"]([^'\"]+)['\"]\s*%\}", _resolve, src)
        assert "X-CSRFToken" in src
        assert "window._origFetch" in src
