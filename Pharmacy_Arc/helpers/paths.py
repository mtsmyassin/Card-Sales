"""Path helpers and logo loader — extracted from helpers/offline_queue.py."""

import base64
import os
import sys


def get_base_path() -> str:
    """Return directory for data files (PyInstaller-safe)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    # Always use the project root (one level above helpers/)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_logo(store_name=None) -> str:
    """Return base64-encoded logo PNG for the given store name."""
    filename = "logo.png"
    if store_name == "Carthage":
        filename = "carthage.png"
    p = os.path.join(get_base_path(), filename)
    if not os.path.exists(p):
        p = os.path.join(get_base_path(), "logo.png")
    if not os.path.exists(p):
        return ""
    with open(p, "rb") as fh:
        return base64.b64encode(fh.read()).decode()
