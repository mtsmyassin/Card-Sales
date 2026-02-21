"""Pytest configuration — adds Pharmacy_Arc root to sys.path for all tests."""
import os
import sys

# Allow tests in tests/ to import modules from parent directory (app.py, telegram_bot.py, etc.)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
