"""Pytest configuration — adds Pharmacy_Arc root to sys.path for all tests."""
import os
import sys
import pytest

# Allow tests in tests/ to import modules from parent directory (app.py, telegram_bot.py, etc.)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def disable_csrf_and_ratelimit(monkeypatch):
    """Disable CSRF and rate limiting for all tests."""
    import app as flask_app
    flask_app.app.config["WTF_CSRF_ENABLED"] = False
    flask_app.app.config["RATELIMIT_ENABLED"] = False
    yield
    flask_app.app.config["WTF_CSRF_ENABLED"] = True
    flask_app.app.config["RATELIMIT_ENABLED"] = True
