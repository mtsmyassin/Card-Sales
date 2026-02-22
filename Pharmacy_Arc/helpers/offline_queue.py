"""
Offline queue: persists audit entries to a local JSON file when Supabase is
unavailable. Also contains path helpers and logo loader used by routes/main.py.
"""
import os
import sys
import json
import base64
import logging
from config import Config

logger = logging.getLogger(__name__)

OFFLINE_QUEUE_MAX_SIZE = int(os.getenv('OFFLINE_QUEUE_MAX_SIZE', '2000'))
OFFLINE_FILE = Config.OFFLINE_FILE


def get_base_path() -> str:
    """Return directory for data files (PyInstaller-safe)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    # Always use the project root (one level above helpers/)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_queue_path() -> str:
    """Return the path to the offline queue JSON file."""
    onedrive = os.environ.get('OneDrive') or os.environ.get('OneDriveConsumer')
    target = onedrive if onedrive and os.path.exists(onedrive) else os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(target, OFFLINE_FILE)


def get_logo(store_name=None) -> str:
    """Return base64-encoded logo PNG for the given store name."""
    filename = 'logo.png'
    if store_name == 'Carthage':
        filename = 'carthage.png'
    p = os.path.join(get_base_path(), filename)
    if not os.path.exists(p):
        p = os.path.join(get_base_path(), 'logo.png')
    if not os.path.exists(p):
        return ""
    with open(p, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def save_to_queue(payload: dict) -> bool:
    """Append payload to offline queue. Returns False if queue is full (record dropped)."""
    q_path = get_queue_path()
    queue = []
    if os.path.exists(q_path):
        try:
            with open(q_path, encoding='utf-8') as fh:
                queue = json.load(fh)
        except Exception:
            pass
    if len(queue) >= OFFLINE_QUEUE_MAX_SIZE:
        logger.error(
            "Offline queue FULL (%d/%d) — record dropped: date=%s store=%s",
            len(queue), OFFLINE_QUEUE_MAX_SIZE,
            payload.get('date'), payload.get('store'),
        )
        return False
    queue.append(payload)
    with open(q_path, 'w', encoding='utf-8') as f:
        json.dump(queue, f, ensure_ascii=False)
    return True


def load_queue() -> list:
    """Load and return the offline queue list."""
    q_path = get_queue_path()
    if os.path.exists(q_path):
        try:
            with open(q_path, encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            return []
    return []


def clear_queue() -> None:
    """Delete the offline queue file."""
    q_path = get_queue_path()
    if os.path.exists(q_path):
        os.remove(q_path)
