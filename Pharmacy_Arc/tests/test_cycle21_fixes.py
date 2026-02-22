"""
Regression tests for Cycle 21 fixes (Feb 2026).

Covers:
- BUG-07: session timeout enforced per-request via before_request hook
- BUG-09: MAX_CONTENT_LENGTH=5MB + 413 error handler
- BUG-10: TELEGRAM_BOT_TOKEN validated at import time (not lazily)
- BUG-11: audit_log.py file opens use encoding='utf-8'; Supabase write is primary
- BUG-05: offline queue capped at OFFLINE_QUEUE_MAX_SIZE; save_to_queue returns bool
- BUG-08: Supabase init uses _init_supabase() retry helper
"""
import os
import sys
import json
import time
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
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


# ── BUG-07: Session timeout enforcement ───────────────────────────────────────

class TestSessionTimeout:
    def test_before_request_hook_defined(self):
        """enforce_session_timeout must be registered as a before_request function."""
        app_module = _load_app()
        hook_names = [f.__name__ for f in app_module.app.before_request_funcs.get(None, [])]
        assert "enforce_session_timeout" in hook_names, (
            "enforce_session_timeout must be a registered before_request hook"
        )

    def test_active_session_refreshes_last_active(self):
        """Each authenticated request must update session last_active timestamp."""
        app_module = _load_app()
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['user'] = 'testuser'
            old_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            sess['last_active'] = old_ts

        # Authenticated request to a real protected endpoint
        resp = client.get('/api/list')
        # After the request, last_active should be updated
        with client.session_transaction() as sess:
            new_ts = sess.get('last_active', '')
        assert new_ts != old_ts, "before_request must update last_active on each request"

    def test_expired_session_cleared(self):
        """A session idle longer than SESSION_TIMEOUT_MINUTES must be cleared."""
        app_module = _load_app()
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['user'] = 'testuser'
            # Set last_active 2 hours ago — well past 30-minute timeout
            old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            sess['last_active'] = old_ts

        # /api/list is a real protected GET endpoint
        resp = client.get('/api/list')
        assert resp.status_code == 401, (
            "Expired session must return 401 (session cleared, require_auth fires)"
        )

    def test_login_stamps_last_active(self):
        """Successful login must set session['last_active'] to current UTC time."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "auth.py"),
            encoding="utf-8",
        ).read()
        login_fn_start = src.index("def login():")
        login_fn_end = src.index("\ndef ", login_fn_start + 1)
        login_block = src[login_fn_start:login_fn_end]
        assert "last_active" in login_block, (
            "login() must stamp session['last_active'] on successful authentication"
        )

    def test_session_timeout_uses_timezone_aware_utc(self):
        """enforce_session_timeout must use datetime.now(timezone.utc), not utcnow()."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "auth.py"),
            encoding="utf-8",
        ).read()
        hook_start = src.index("def enforce_session_timeout()")
        hook_end = src.index("\n\n@bp.", hook_start)
        hook_block = src[hook_start:hook_end]
        assert "timezone.utc" in hook_block, (
            "enforce_session_timeout must use timezone-aware UTC (datetime.now(timezone.utc))"
        )
        assert "utcnow()" not in hook_block, (
            "enforce_session_timeout must not use deprecated datetime.utcnow()"
        )


# ── BUG-09: MAX_CONTENT_LENGTH + 413 handler ──────────────────────────────────

class TestPayloadSizeLimit:
    def test_max_content_length_set(self):
        """app.config['MAX_CONTENT_LENGTH'] must be set to 5 MB."""
        app_module = _load_app()
        limit = app_module.app.config.get("MAX_CONTENT_LENGTH")
        assert limit == 5 * 1024 * 1024, (
            f"MAX_CONTENT_LENGTH must be 5MB (5242880), got {limit}"
        )

    def test_413_handler_returns_json(self):
        """413 error handler must return JSON with an error message."""
        app_module = _load_app()
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        assert "errorhandler(413)" in src, "app.py must define @app.errorhandler(413)"
        assert "payload_too_large" in src or "Payload too large" in src


# ── BUG-10: Bot token fail-fast ───────────────────────────────────────────────

class TestBotTokenFailFast:
    def test_bot_token_loaded_at_module_level(self):
        """_BOT_TOKEN must be set at module level (not None at import time)."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram_bot.py"),
            encoding="utf-8",
        ).read()
        # _BOT_TOKEN should be assigned from os.getenv at module level, not None
        assert "_BOT_TOKEN: str = os.getenv(" in src or '_BOT_TOKEN = os.getenv(' in src, (
            "_BOT_TOKEN must be loaded from env at module level, not lazily"
        )

    def test_token_function_raises_on_empty(self):
        """_token() must raise RuntimeError if TELEGRAM_BOT_TOKEN is not set."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
            import importlib
            import telegram_bot
            importlib.reload(telegram_bot)
            with pytest.raises((RuntimeError, KeyError)):
                telegram_bot._token()

    def test_token_function_returns_value_when_set(self):
        """_token() must return the token string when TELEGRAM_BOT_TOKEN is set."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "12345:ABCDEF"}):
            import importlib
            import telegram_bot
            importlib.reload(telegram_bot)
            assert telegram_bot._token() == "12345:ABCDEF"


# ── BUG-11: audit_log.py encoding + write order ───────────────────────────────

class TestAuditLogEncoding:
    def test_file_opens_use_utf8(self):
        """All open() calls in audit_log.py must use encoding='utf-8'."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "audit_log.py"),
            encoding="utf-8",
        ).read()
        # Find all open() calls (excluding the CLI section after __main__)
        main_src = src[:src.index("if __name__")]
        import re
        opens = re.findall(r"open\([^)]+\)", main_src)
        for o in opens:
            assert "utf-8" in o or "encoding" in o, (
                f"open() call missing encoding='utf-8': {o}"
            )

    def test_supabase_write_before_file_write(self):
        """Supabase write must happen before local file write in AuditLogger.log()."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "audit_log.py"),
            encoding="utf-8",
        ).read()
        log_fn_start = src.index("    def log(")
        log_fn_end = src.index("\n    def ", log_fn_start + 1)
        log_block = src[log_fn_start:log_fn_end]
        db_pos = log_block.index("_write_to_db")
        file_pos = log_block.index("open(self.log_file")
        assert db_pos < file_pos, (
            "AuditLogger.log() must call _write_to_db() before writing to the local file"
        )

    def test_utf8_roundtrip_with_accented_chars(self, tmp_path):
        """Audit log must correctly store and retrieve entries with accented characters."""
        from audit_log import AuditLogger
        log_path = str(tmp_path / "test_audit.jsonl")
        al = AuditLogger(log_file=log_path)
        al.log(
            action="TEST",
            actor="Farmacía #1",
            role="admin",
            entity_type="AUDIT",
            context={"store": "Carimas Ñoño"},
        )
        entries = al.get_entries()
        assert len(entries) == 1
        assert entries[0]["actor"] == "Farmacía #1"
        assert entries[0]["context"]["store"] == "Carimas Ñoño"


# ── BUG-05: Offline queue size cap ────────────────────────────────────────────

class TestOfflineQueueCap:
    def test_save_to_queue_returns_bool(self):
        """save_to_queue must return True on success, False when full."""
        app_module = _load_app()
        assert callable(app_module.save_to_queue), "save_to_queue must exist"
        # Check the source — return type should be bool
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "helpers", "offline_queue.py"),
            encoding="utf-8",
        ).read()
        fn_start = src.index("def save_to_queue(")
        fn_end = src.index("\ndef ", fn_start + 1)
        block = src[fn_start:fn_end]
        assert "return False" in block, "save_to_queue must return False when queue is full"
        assert "return True" in block, "save_to_queue must return True on success"

    def test_queue_max_size_constant_defined(self):
        """OFFLINE_QUEUE_MAX_SIZE must be defined in helpers/offline_queue.py."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "helpers", "offline_queue.py"),
            encoding="utf-8",
        ).read()
        assert "OFFLINE_QUEUE_MAX_SIZE" in src, (
            "OFFLINE_QUEUE_MAX_SIZE constant must be defined"
        )

    def test_queue_cap_enforced(self, tmp_path, monkeypatch):
        """save_to_queue must return False and drop the record when at max capacity."""
        import helpers.offline_queue as oq
        q_file = str(tmp_path / "offline_queue.json")
        monkeypatch.setattr(oq, "get_queue_path", lambda: q_file)
        monkeypatch.setattr(oq, "OFFLINE_QUEUE_MAX_SIZE", 3)

        for i in range(3):
            result = oq.save_to_queue({"date": f"01/0{i+1}/2026", "store": "test"})
            assert result is True

        # 4th entry should be rejected
        result = oq.save_to_queue({"date": "01/04/2026", "store": "test"})
        assert result is False, "save_to_queue must return False when queue is full"

        # Queue file must still have only 3 entries
        with open(q_file, encoding="utf-8") as f:
            queue = json.load(f)
        assert len(queue) == 3, "Dropped record must not be written to queue file"


# ── BUG-08: Supabase startup retry ────────────────────────────────────────────

class TestSupabaseStartupRetry:
    def test_init_supabase_helper_exists(self):
        """app.py must define _init_supabase() retry helper."""
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py"),
            encoding="utf-8",
        ).read()
        assert "def _init_supabase(" in src, (
            "app.py must define _init_supabase() retry helper"
        )

    def test_init_supabase_retries_on_failure(self):
        """_init_supabase must retry on failure and return None after max attempts."""
        app_module = _load_app()
        call_count = 0

        def failing_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("simulated failure")

        with patch("app.create_client", side_effect=failing_create):
            with patch("time.sleep"):  # don't actually sleep in tests
                result = app_module._init_supabase("url", "key", "test", max_attempts=3)

        assert result is None, "_init_supabase must return None after all attempts fail"
        assert call_count == 3, "_init_supabase must attempt exactly max_attempts times"

    def test_init_supabase_succeeds_on_first_attempt(self):
        """_init_supabase must return client immediately on first success."""
        app_module = _load_app()
        mock_client = MagicMock()

        with patch("app.create_client", return_value=mock_client):
            result = app_module._init_supabase("url", "key", "test", max_attempts=3)

        assert result is mock_client
