"""Bot session state management — in-memory cache + Supabase persistence."""
import logging
import threading

import extensions
from config import Config

logger = logging.getLogger(__name__)

# In-memory conversation state: { telegram_id: { state, username, store, ... } }
bot_state: dict = {}
_bot_state_lock = threading.Lock()


def persist_session(telegram_id: int, state: dict) -> None:
    """Upsert bot session state to Supabase bot_sessions table."""
    try:
        client = extensions.get_db()
        if client is None:
            return
        client.table("bot_sessions").upsert({
            "telegram_id": telegram_id,
            "state": state.get("state", "AWAITING_USERNAME"),
            "username": state.get("username"),
            "store": state.get("store"),
            "retry_count": state.get("retry_count", 0),
            "pending_data": state.get("pending_data"),
            "lang": state.get("lang", "es"),
        }).execute()
    except Exception as e:
        logger.warning(f"persist_session failed for {telegram_id}: {e}")


def load_session(telegram_id: int) -> dict | None:
    """Load bot session state from Supabase bot_sessions table."""
    try:
        client = extensions.get_db()
        if client is None:
            return None
        result = client.table("bot_sessions").select("*").eq("telegram_id", telegram_id).execute()
        if not result.data:
            return None
        row = result.data[0]
        return {
            "state": row.get("state", "AWAITING_USERNAME"),
            "username": row.get("username"),
            "store": row.get("store"),
            "retry_count": row.get("retry_count", 0),
            "pending_data": row.get("pending_data"),
            "lang": row.get("lang", "es"),
        }
    except Exception as e:
        logger.warning(f"load_session failed for {telegram_id}: {e}")
        return None


def _set_state(telegram_id: int, state: dict) -> None:
    """Update in-memory bot_state (under lock) and persist to Supabase synchronously."""
    with _bot_state_lock:
        bot_state[telegram_id] = state
    persist_session(telegram_id, state.copy())


def is_registered(telegram_id: int) -> bool:
    """Check if telegram_id exists in bot_users Supabase table."""
    client = extensions.get_db()
    if client is None:
        return False
    try:
        result = client.table("bot_users").select("telegram_id").eq(
            "telegram_id", telegram_id
        ).execute()
        return len(result.data) > 0
    except Exception as e:
        logger.error(f"bot_users lookup failed: {e}")
        return False


def get_bot_user(telegram_id: int) -> dict | None:
    """Return bot_users row for telegram_id, or None."""
    client = extensions.get_db()
    if client is None:
        return None
    try:
        result = client.table("bot_users").select("*").eq(
            "telegram_id", telegram_id
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"get_bot_user failed: {e}")
        return None


def verify_web_credentials(username: str, password: str) -> dict | None:
    """Verify username/password — mirrors the web app login exactly."""
    try:
        supabase = extensions.get_db()
        EMERGENCY_ACCOUNTS = extensions.EMERGENCY_ACCOUNTS
        password_hasher = extensions.password_hasher
    except Exception as e:
        logger.error(f"verify_web_credentials: extensions access failed: {e}")
        return None

    if supabase is None:
        logger.error("verify_web_credentials: supabase is None")
        return None
    try:
        if username in EMERGENCY_ACCOUNTS:
            stored_hash = EMERGENCY_ACCOUNTS[username]
            if password_hasher.verify_password(password, stored_hash):
                role = "super_admin" if username == "super" else "admin"
                return {"username": username, "role": role, "store": "All"}
            return None

        result = supabase.table("users").select("*").ilike("username", username).execute()
        if not result.data:
            return None
        user = result.data[0]
        stored = user.get("password", "")
        if stored.startswith("$2b$"):
            valid = password_hasher.verify_password(password, stored)
        else:
            logger.error(f"[bot] User {username!r} has unhashed password in DB — rejecting login")
            valid = False
        return user if valid else None
    except Exception as e:
        logger.error(f"verify_web_credentials failed: {e}", exc_info=True)
        return None


def save_bot_user(telegram_id: int, username: str, tg_username: str, store: str) -> None:
    """Upsert a row in bot_users."""
    client = extensions.get_db()
    if client is None:
        return
    client.table("bot_users").upsert({
        "telegram_id": telegram_id,
        "username": username,
        "store": store,
    }).execute()
