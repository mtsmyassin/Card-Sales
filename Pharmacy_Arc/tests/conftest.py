"""Pytest configuration — adds Pharmacy_Arc root to sys.path for all tests."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Allow tests in tests/ to import modules from parent directory (app.py, telegram_bot.py, etc.)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test environment variables — set BEFORE importing app to prevent
# Config.startup_check() → sys.exit(1) when no .env file exists.
_TEST_ENV = {
    "FLASK_SECRET_KEY": "test-secret-key-minimum-32-characters-long!!",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_KEY": "test-key",
    "TELEGRAM_WEBHOOK_SECRET": "test-webhook-secret",
}
os.environ.update(_TEST_ENV)

# Patch supabase.create_client and startup_check during the app module import.
# After the `with` blocks exit the patches are removed, but by then create_app()
# has already finished and app.app is a fully initialised Flask instance.
with patch("supabase.create_client", return_value=MagicMock()):
    with patch("config.Config.startup_check"):
        import app as _app_module

_flask_app = _app_module.app


@pytest.fixture(autouse=True)
def disable_csrf_and_ratelimit():
    """Disable CSRF and rate limiting for all tests."""
    _flask_app.config["WTF_CSRF_ENABLED"] = False
    _flask_app.config["RATELIMIT_ENABLED"] = False
    yield
    _flask_app.config["WTF_CSRF_ENABLED"] = True
    _flask_app.config["RATELIMIT_ENABLED"] = True
