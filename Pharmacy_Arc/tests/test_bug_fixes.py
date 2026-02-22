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
        """app.py must use (supabase_admin or supabase) for audits INSERT in save()."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        # find the save() function block and confirm the insert uses admin
        save_block = src[src.index("def save():"):src.index("def sync():")]
        assert "(supabase_admin or supabase).table(\"audits\").insert" in save_block, (
            "save() must use (supabase_admin or supabase) for INSERT to bypass RLS"
        )


# ── BUG 2: sync() uses admin client for dup-check and INSERT ─────────────────

class TestSyncUsesAdminClient:
    def _get_sync_block(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        return src[src.index("def sync():"):src.index("def update():")]

    def test_sync_dup_check_uses_admin(self):
        block = self._get_sync_block()
        assert "_db = supabase_admin or supabase" in block, (
            "sync() must assign _db = supabase_admin or supabase before dup check"
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
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()

    def test_update_before_state_uses_admin(self):
        src = self._src()
        update_block = src[src.index("def update():"):src.index("def delete():")]
        assert "(supabase_admin or supabase).table(\"audits\").select" in update_block

    def test_update_write_uses_admin(self):
        src = self._src()
        update_block = src[src.index("def update():"):src.index("def delete():")]
        assert "(supabase_admin or supabase).table(\"audits\").update" in update_block

    def test_delete_before_state_uses_admin(self):
        src = self._src()
        # delete() block ends at next route
        delete_start = src.index("def delete():")
        delete_end = src.index("@app.route", delete_start)
        delete_block = src[delete_start:delete_end]
        assert "(supabase_admin or supabase).table(\"audits\").select" in delete_block

    def test_delete_write_uses_admin(self):
        src = self._src()
        delete_start = src.index("def delete():")
        delete_end = src.index("@app.route", delete_start)
        delete_block = src[delete_start:delete_end]
        assert "(supabase_admin or supabase).table(\"audits\").delete" in delete_block


# ── BUG 3: offline queue UTF-8 roundtrip ─────────────────────────────────────

class TestOfflineQueueEncoding:
    def test_utf8_roundtrip(self, tmp_path, monkeypatch):
        """Accented store names survive a save → load cycle on Windows."""
        app_module = _load_app()
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(app_module, "OFFLINE_FILE", "offline_queue.json")
        # patch get_queue_path to return our tmp file
        monkeypatch.setattr(app_module, "get_queue_path", lambda: q_file)

        payload = {"store": "Farmacía #1", "date": "01/01/2026", "gross": 100.0}
        app_module.save_to_queue(payload)
        result = app_module.load_queue()
        assert len(result) == 1
        assert result[0]["store"] == "Farmacía #1", (
            "Accented characters must survive UTF-8 queue roundtrip"
        )

    def test_queue_file_written_with_utf8(self, tmp_path, monkeypatch):
        """Queue file on disk must be valid UTF-8 (not cp1252-encoded)."""
        app_module = _load_app()
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(app_module, "get_queue_path", lambda: q_file)

        app_module.save_to_queue({"store": "Carimas Ñoño"})
        raw = open(q_file, "rb").read()
        # Must decode as UTF-8 without errors
        raw.decode("utf-8")


# ── BUG 4: sync() logs exceptions, doesn't swallow them ──────────────────────

class TestSyncLogsExceptions:
    def test_bare_except_replaced(self):
        """sync() must not have a bare 'except:' — only 'except Exception'."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        sync_block = src[src.index("def sync():"):src.index("def update():")]
        assert "except:" not in sync_block, (
            "sync() must not use bare except: — use except Exception as exc"
        )

    def test_sync_exception_logged(self):
        """sync() exception message must appear in warning log, not be swallowed."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        sync_block = src[src.index("def sync():"):src.index("def update():")]
        assert "logger.warning" in sync_block, (
            "sync() must log a warning when an insert fails"
        )


# ── BUG 5: APScheduler atexit shutdown registered ────────────────────────────

class TestAPSchedulerShutdown:
    def test_atexit_registered(self):
        """APScheduler block must register an atexit shutdown handler."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        sched_block = src[src.index("# ── APScheduler:"):]
        assert "atexit.register" in sched_block, (
            "APScheduler must register atexit shutdown to prevent thread leak on deploy"
        )
        assert "_scheduler.shutdown" in sched_block


# ── CSRF: protection wired up ─────────────────────────────────────────────────

class TestCSRFProtection:
    def test_csrf_token_endpoint_exists(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        assert "'/api/csrf-token'" in src, "/api/csrf-token endpoint must exist"
        assert "generate_csrf" in src

    def test_login_is_csrf_exempt(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        login_block = src[src.index("@app.route('/api/login'"):src.index("def login():") + 50]
        assert "@csrf.exempt" in login_block, "/api/login must be @csrf.exempt"

    def test_telegram_webhook_is_csrf_exempt(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        wh_block = src[src.index("@app.route('/api/telegram/webhook'"):
                       src.index("def telegram_webhook():") + 50]
        assert "@csrf.exempt" in wh_block, "/api/telegram/webhook must be @csrf.exempt"

    def test_csrf_protect_initialized(self):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        assert "csrf = CSRFProtect(app)" in src

    def test_frontend_fetch_patch_present(self):
        """Main UI JS must patch window.fetch to inject X-CSRFToken."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        assert "X-CSRFToken" in src
        assert "window._origFetch" in src
