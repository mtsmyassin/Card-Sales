"""
Offline queue: persists audit entries to a local JSON file when Supabase is
unavailable. Path helpers and logo loader live in helpers/paths.py and are
re-exported here for backward compatibility.
"""
import os
import json
import logging
import threading
from config import Config
from helpers.paths import get_base_path, get_logo  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)

OFFLINE_QUEUE_MAX_SIZE = int(os.getenv('OFFLINE_QUEUE_MAX_SIZE', '2000'))
OFFLINE_FILE = Config.OFFLINE_FILE
_queue_lock = threading.Lock()


def _atomic_write_json(path: str, data) -> None:
    """Write JSON atomically using temp file + os.replace."""
    import tempfile
    dir_name = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

# Railway (and similar cloud platforms) use ephemeral filesystems — data written
# to disk is silently lost on every deploy. Detect this so save_to_queue can
# refuse to pretend data is safe when it isn't.
_IS_EPHEMERAL_FS = bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PUBLIC_DOMAIN'))


def get_queue_path() -> str:
    """Return the path to the offline queue JSON file.

    Uses the project root (same directory as app.py) — platform-independent.
    On Railway (ephemeral FS), save_to_queue() rejects writes before this path
    is ever used, so the path value is irrelevant in production.
    """
    return os.path.join(get_base_path(), OFFLINE_FILE)


def save_to_queue(payload: dict) -> bool:
    """Append payload to offline queue.

    Returns False if queue is full (record dropped).
    Raises RuntimeError on ephemeral filesystems (Railway) where data would be
    silently lost on the next deploy — callers must handle this and tell the
    user the truth instead of showing a false "Saved to Queue" message.
    """
    if _IS_EPHEMERAL_FS:
        raise RuntimeError(
            "Offline queue is disabled on Railway (ephemeral filesystem). "
            "Data would be lost on next deploy. Database is required."
        )
    with _queue_lock:
        q_path = get_queue_path()
        queue = []
        if os.path.exists(q_path):
            try:
                with open(q_path, encoding='utf-8') as fh:
                    queue = json.load(fh)
            except Exception as load_err:
                logger.warning(f"Corrupt offline queue at {q_path}, starting fresh: {load_err}")
                queue = []
        if len(queue) >= OFFLINE_QUEUE_MAX_SIZE:
            logger.error(
                "Offline queue FULL (%d/%d) — record dropped: date=%s store=%s",
                len(queue), OFFLINE_QUEUE_MAX_SIZE,
                payload.get('date'), payload.get('store'),
            )
            return False
        queue.append(payload)
        _atomic_write_json(q_path, queue)
        return True


def load_queue() -> list:
    """Load and return the offline queue list."""
    with _queue_lock:
        q_path = get_queue_path()
        if os.path.exists(q_path):
            try:
                with open(q_path, encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception as load_err:
                logger.warning(f"Corrupt offline queue at {q_path}: {load_err}")
                return []
        return []


def clear_queue() -> None:
    """Delete the offline queue file."""
    with _queue_lock:
        q_path = get_queue_path()
        if os.path.exists(q_path):
            os.remove(q_path)
