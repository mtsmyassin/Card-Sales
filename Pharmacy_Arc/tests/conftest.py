"""Pytest configuration — adds Pharmacy_Arc root to sys.path for all tests."""
import os
import sys
import pytest

# Allow tests in tests/ to import modules from parent directory (app.py, telegram_bot.py, etc.)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def disable_csrf(monkeypatch):
    """Disable CSRF for all tests — avoids having to pass tokens in every POST request."""
    import app as flask_app
    flask_app.app.config["WTF_CSRF_ENABLED"] = False
    yield
    flask_app.app.config["WTF_CSRF_ENABLED"] = True
