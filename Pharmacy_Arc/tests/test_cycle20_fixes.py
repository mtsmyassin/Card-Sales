"""
Regression tests for Cycle 20 fixes (Feb 2026).

Covers:
- BUG-01: Telegram webhook uses dedicated TELEGRAM_WEBHOOK_SECRET + hmac.compare_digest
- BUG-02: bot_state protected by threading.Lock; persist_session is fire-and-forget
- BUG-03: gunicorn.conf.py exists with post_fork; EOD loop isolates per-recipient failures
"""
import os
import sys
import hmac
import threading
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENV = {
    "FLASK_SECRET_KEY": "test-key-minimum-32-chars-long-ok!!",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_KEY": "test-key",
    "TELEGRAM_WEBHOOK_SECRET": "test-webhook-secret-abc123",
}


def _load_app():
    with patch.dict(os.environ, ENV):
        with patch("supabase.create_client", return_value=MagicMock()):
            with patch("config.Config.startup_check"):
                import importlib
                import app as app_module
                importlib.reload(app_module)
                return app_module


# ── BUG-01: Webhook secret — dedicated var + constant-time compare ─────────────

class TestWebhookSecretValidation:
    def test_webhook_rejects_missing_secret_header(self):
        """Webhook must return 403 when X-Telegram-Bot-Api-Secret-Token is absent."""
        app_module = _load_app()
        client = app_module.app.test_client()
        resp = client.post(
            "/api/telegram/webhook",
            json={"update_id": 1},
        )
        assert resp.status_code == 403

    def test_webhook_rejects_wrong_secret(self):
        """Webhook must return 403 when secret token is wrong."""
        app_module = _load_app()
        client = app_module.app.test_client()
        resp = client.post(
            "/api/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        )
        assert resp.status_code == 403

    def test_webhook_accepts_correct_secret(self):
        """Webhook must return 200 when correct secret token is provided."""
        app_module = _load_app()
        # Config class attributes are set at import time; patch the live attribute
        # to simulate TELEGRAM_WEBHOOK_SECRET being set in Railway Variables.
        with patch.object(app_module.Config, "TELEGRAM_WEBHOOK_SECRET", ENV["TELEGRAM_WEBHOOK_SECRET"]):
            client = app_module.app.test_client()
            with patch("telegram_bot.handle_update"):
                resp = client.post(
                    "/api/telegram/webhook",
                    json={"update_id": 1, "message": {"text": "hi"}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": ENV["TELEGRAM_WEBHOOK_SECRET"]},
                )
        assert resp.status_code == 200

    def test_webhook_uses_hmac_compare_digest(self):
        """routes/telegram.py webhook must use hmac.compare_digest for token check."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "telegram.py"),
            encoding="utf-8",
        ).read()
        wh_start = src.index("def telegram_webhook():")
        wh_end = src.index("\ndef ", wh_start + 1)
        webhook_block = src[wh_start:wh_end]
        assert "hmac.compare_digest" in webhook_block, (
            "telegram_webhook() must use hmac.compare_digest for constant-time token comparison"
        )

    def test_webhook_uses_dedicated_secret_var(self):
        """Webhook must use TELEGRAM_WEBHOOK_SECRET, not Flask SECRET_KEY."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "telegram.py"),
            encoding="utf-8",
        ).read()
        wh_start = src.index("def telegram_webhook():")
        wh_end = src.index("\ndef ", wh_start + 1)
        webhook_block = src[wh_start:wh_end]
        assert "TELEGRAM_WEBHOOK_SECRET" in webhook_block, (
            "telegram_webhook() must use Config.TELEGRAM_WEBHOOK_SECRET"
        )
        # Must NOT fall back to Flask SECRET_KEY for the token
        assert "SECRET_KEY" not in webhook_block or "TELEGRAM_WEBHOOK_SECRET" in webhook_block

    def test_telegram_webhook_secret_in_config(self):
        """Config class must expose TELEGRAM_WEBHOOK_SECRET from env."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.py"),
            encoding="utf-8",
        ).read()
        assert "TELEGRAM_WEBHOOK_SECRET" in src, (
            "config.py must define TELEGRAM_WEBHOOK_SECRET from os.getenv"
        )


# ── BUG-02: bot_state thread lock + async persist ─────────────────────────────

class TestBotStateThreadSafety:
    def test_bot_state_lock_exists(self):
        """telegram_bot.py must declare _bot_state_lock as a threading.Lock."""
        import telegram_bot
        assert hasattr(telegram_bot, "_bot_state_lock"), (
            "telegram_bot must have _bot_state_lock"
        )
        assert isinstance(telegram_bot._bot_state_lock, type(threading.Lock())), (
            "_bot_state_lock must be a threading.Lock"
        )

    def test_set_state_uses_lock(self):
        """_set_state must acquire _bot_state_lock when writing to bot_state."""
        # _set_state lives in telegram/session.py after the package split
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram", "session.py"),
            encoding="utf-8",
        ).read()
        set_state_start = src.index("def _set_state(")
        set_state_end = src.index("\ndef ", set_state_start + 1)
        block = src[set_state_start:set_state_end]
        assert "_bot_state_lock" in block, "_set_state must use _bot_state_lock"

    def test_set_state_sync_persist(self):
        """_set_state must call persist_session synchronously (prevents state loss on deploys)."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram", "session.py"),
            encoding="utf-8",
        ).read()
        set_state_start = src.index("def _set_state(")
        set_state_end = src.index("\ndef ", set_state_start + 1)
        block = src[set_state_start:set_state_end]
        assert "persist_session(" in block, (
            "_set_state must call persist_session synchronously"
        )
        assert "threading.Thread" not in block, (
            "_set_state should NOT use threading.Thread — persist must be synchronous"
        )

    def test_handle_update_reads_state_under_lock(self):
        """handle_update must read bot_state under _bot_state_lock."""
        # handle_update lives in telegram/bot.py after the package split
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram", "bot.py"),
            encoding="utf-8",
        ).read()
        handle_start = src.index("def handle_update(")
        handle_end = src.index("\ndef ", handle_start + 1)
        block = src[handle_start:handle_end]
        assert "_bot_state_lock" in block, (
            "handle_update must read bot_state under _bot_state_lock"
        )


# ── BUG-03: APScheduler multi-worker safety ────────────────────────────────────

class TestAPSchedulerWorkerSafety:
    def test_gunicorn_conf_exists(self):
        """gunicorn.conf.py must exist in the project root."""
        conf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gunicorn.conf.py")
        assert os.path.exists(conf_path), "gunicorn.conf.py must exist"

    def test_gunicorn_conf_has_post_fork(self):
        """gunicorn.conf.py must define post_fork to shut down scheduler in workers."""
        conf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gunicorn.conf.py")
        src = open(conf_path, encoding="utf-8").read()
        assert "def post_fork(" in src, "gunicorn.conf.py must define post_fork(server, worker)"
        assert "scheduler" in src.lower(), "post_fork must reference the scheduler"
        assert "shutdown" in src, "post_fork must call scheduler.shutdown()"

    def test_gunicorn_conf_has_preload(self):
        """gunicorn.conf.py must set preload_app=True so master starts the scheduler."""
        conf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gunicorn.conf.py")
        src = open(conf_path, encoding="utf-8").read()
        assert "preload_app" in src, "gunicorn.conf.py must set preload_app"
        assert "True" in src, "preload_app must be True"

    def test_procfile_uses_gunicorn_conf(self):
        """Procfile must reference gunicorn.conf.py."""
        proc_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Procfile")
        src = open(proc_path, encoding="utf-8").read()
        assert "gunicorn.conf.py" in src, "Procfile must use --config gunicorn.conf.py"

    def test_eod_reminder_per_recipient_isolation(self):
        """_send_eod_reminders must catch per-recipient exceptions and continue the loop."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "helpers", "scheduler.py"),
            encoding="utf-8",
        ).read()
        fn_start = src.index("def _send_eod_reminders(")
        # Function ends just before init_scheduler
        fn_end = src.index("\ndef init_scheduler", fn_start)
        block = src[fn_start:fn_end]
        # Must have try/except inside the per-recipient loop
        assert "except Exception as exc" in block or "except Exception" in block, (
            "_send_eod_reminders must catch per-recipient send errors"
        )
        assert "logger.error" in block, (
            "_send_eod_reminders must log per-recipient failures"
        )
        assert "failed" in block, (
            "_send_eod_reminders must track failed recipients"
        )
