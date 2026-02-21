"""
Telegram bot for Z Report submission.
Uses raw Telegram Bot API (via requests) — no python-telegram-bot library needed.
Conversation state is kept in-memory; bot_users registration is persisted in Supabase.
"""
import os
import io
import time
import logging
import unicodedata
import requests as http

from ocr import extract_z_report, has_null_fields, NULL_FIELD_NAMES, OCRParseError

logger = logging.getLogger(__name__)

# In-memory conversation state: { telegram_id: { state, username, store, ... } }
bot_state: dict = {}

_BOT_TOKEN = None  # loaded lazily from env

KNOWN_STORES = ["Carimas #1", "Carimas #2", "Carimas #3", "Carthage"]
STORE_MENU = (
    "Which store is this report for?\n"
    "1 — Carimas #1\n"
    "2 — Carimas #2\n"
    "3 — Carimas #3\n"
    "4 — Carthage\n"
    "Reply with the number."
)
_STORE_CHOICE = {"1": "Carimas #1", "2": "Carimas #2", "3": "Carimas #3", "4": "Carthage"}


# ── Photo system helpers ───────────────────────────────────────────────────────

def _format_register_id(register) -> str:
    """Convert register number/string to 'Reg N' format."""
    if register is None:
        return "Reg ?"
    try:
        return f"Reg {int(register)}"
    except (TypeError, ValueError):
        return f"Reg {register}"


def _token() -> str:
    global _BOT_TOKEN
    if _BOT_TOKEN is None:
        _BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    return _BOT_TOKEN


def _tg(method: str, **kwargs) -> dict:
    """Call a Telegram Bot API method."""
    resp = http.post(
        f"https://api.telegram.org/bot{_token()}/{method}",
        json=kwargs,
        timeout=15,
    )
    return resp.json()


def send_message(chat_id: int, text: str) -> None:
    _tg("sendMessage", chat_id=chat_id, text=text)


def download_photo(file_id: str) -> bytes:
    """Download a photo from Telegram by file_id, return raw bytes."""
    info = _tg("getFile", file_id=file_id)
    file_path = info["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{_token()}/{file_path}"
    return http.get(url, timeout=30).content


def is_registered(telegram_id: int) -> bool:
    """Check if telegram_id exists in bot_users Supabase table."""
    from app import supabase  # imported here to avoid circular import at module load
    if supabase is None:
        return False
    try:
        result = supabase.table("bot_users").select("telegram_id").eq(
            "telegram_id", telegram_id
        ).execute()
        return len(result.data) > 0
    except Exception as e:
        logger.error(f"bot_users lookup failed: {e}")
        return False


def get_bot_user(telegram_id: int) -> dict | None:
    """Return bot_users row for telegram_id, or None."""
    from app import supabase
    if supabase is None:
        return None
    try:
        result = supabase.table("bot_users").select("*").eq(
            "telegram_id", telegram_id
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"get_bot_user failed: {e}")
        return None


def verify_web_credentials(username: str, password: str) -> dict | None:
    """
    Verify username/password — mirrors the web app login exactly:
    1. Check emergency admin accounts first
    2. Check DB users, supporting both bcrypt and legacy plaintext passwords
    Returns the user row dict if valid, None if invalid.
    """
    try:
        from app import supabase, EMERGENCY_ACCOUNTS, password_hasher
    except Exception as e:
        logger.error(f"verify_web_credentials: import from app failed: {e}")
        return None

    if supabase is None:
        logger.error("verify_web_credentials: supabase is None")
        return None
    try:
        # Check emergency admin accounts
        if username in EMERGENCY_ACCOUNTS:
            stored_hash = EMERGENCY_ACCOUNTS[username]
            if password_hasher.verify_password(password, stored_hash):
                role = "super_admin" if username == "super" else "admin"
                return {"username": username, "role": role, "store": "All"}
            return None

        # Check database accounts
        result = supabase.table("users").select("*").eq("username", username).execute()
        if not result.data:
            return None
        user = result.data[0]
        stored = user.get("password", "")
        if stored.startswith("$2b$"):
            valid = password_hasher.verify_password(password, stored)
        else:
            valid = (stored == password)
        return user if valid else None
    except Exception as e:
        logger.error(f"verify_web_credentials failed: {e}", exc_info=True)
        return None


def save_bot_user(telegram_id: int, username: str, tg_username: str, store: str) -> None:
    """Upsert a row in bot_users."""
    from app import supabase
    if supabase is None:
        return
    supabase.table("bot_users").upsert({
        "telegram_id": telegram_id,
        "username": username,
        "store": store,
    }).execute()


class StorageUploadError(Exception):
    """Raised when upload to Supabase Storage fails."""


def _ensure_bucket(admin_client) -> None:
    """Create z-reports bucket if it doesn't exist (requires service role key)."""
    try:
        existing = [b.name for b in admin_client.storage.list_buckets()]
        if "z-reports" not in existing:
            admin_client.storage.create_bucket("z-reports", options={"public": False})
            logger.info("Created z-reports storage bucket")
    except Exception as e:
        raise StorageUploadError(f"Could not ensure z-reports bucket: {e}") from e


def upload_image_to_storage(image_bytes: bytes, store: str, date: str, register) -> str:
    """
    Upload photo to Supabase Storage z-reports bucket.
    Returns storage path string.
    Raises StorageUploadError on any failure — never returns empty string.
    Requires SUPABASE_SERVICE_KEY to be set (service role key bypasses RLS).
    """
    from app import supabase_admin
    if supabase_admin is None:
        raise StorageUploadError(
            "SUPABASE_SERVICE_KEY not configured — photo upload disabled"
        )
    _ensure_bucket(supabase_admin)
    store_slug = store.replace(" ", "_").replace("#", "")
    reg_num = int(register) if register else 0
    path = f"{store_slug}/{date}/reg{reg_num}_{int(time.time())}.jpg"
    try:
        supabase_admin.storage.from_("z-reports").upload(
            path,
            image_bytes,
            {"content-type": "image/jpeg"},
        )
    except Exception as e:
        raise StorageUploadError(f"Upload to z-reports failed: {e}") from e
    return path


def save_audit_entry(
    data: dict,
    store: str,
    username: str,
    payouts: float = 0.0,
    actual_cash: float = 0.0,
    variance: float = None,
) -> int | None:
    """
    Save the extracted Z report data to the audits table.
    Returns the new entry id (int), or None if saved to offline queue.
    No longer stores z_report_image_path — photos go in z_report_photos table.
    """
    from app import supabase, validate_audit_entry, save_to_queue
    if supabase is None:
        return None

    reg_str = _format_register_id(data.get("register"))
    gross = sum(data.get(f) or 0 for f in
                ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss"])
    net = gross - payouts

    # Use provided variance if given; fall back to OCR-extracted variance
    if variance is None:
        variance = float(data.get("variance") or 0)

    payload = {
        "date": data["date"],
        "reg": reg_str,
        "staff": username,
        "store": store,
        "gross": round(gross, 2),
        "net": round(net, 2),
        "variance": variance,
        "source": "telegram_bot",
        "submitted_by_telegram": username,
        "breakdown": {
            "cash": data.get("cash") or 0,
            "ath": data.get("ath") or 0,
            "athm": data.get("athm") or 0,
            "visa": data.get("visa") or 0,
            "mc": data.get("mc") or 0,
            "amex": data.get("amex") or 0,
            "disc": data.get("disc") or 0,
            "wic": data.get("wic") or 0,
            "mcs": data.get("mcs") or 0,
            "sss": data.get("sss") or 0,
            "payouts": payouts,
            "actual_cash": actual_cash,
        },
    }

    record = {
        "date": data["date"],
        "reg": reg_str,
        "staff": username,
        "store": store,
        "gross": round(gross, 2),
        "net": round(net, 2),
        "variance": variance,
        "payload": payload,
    }

    try:
        result = supabase.table("audits").insert(record).execute()
        return result.data[0]["id"]
    except Exception as e:
        logger.warning(f"DB save failed, queuing offline: {e}")
        save_to_queue(record)
        return None


def save_photo_record(
    entry_id: int,
    store: str,
    business_date: str,
    register_id: str,
    uploaded_by: str,
    storage_path: str,
    content_type: str = "image/jpeg",
    source: str = "telegram",
) -> None:
    """Insert a photo record into z_report_photos, linked to an audit entry."""
    from app import supabase, supabase_admin
    # Prefer service-role client so RLS doesn't block the insert
    client = supabase_admin or supabase
    if client is None:
        logger.warning("save_photo_record: no supabase client available")
        return
    try:
        client.table("z_report_photos").insert({
            "entry_id": entry_id,
            "store": store,
            "business_date": business_date,
            "register_id": register_id,
            "uploaded_by": uploaded_by,
            "storage_path": storage_path,
            "content_type": content_type,
            "source": source,
        }).execute()
    except Exception as e:
        logger.error(f"save_photo_record failed for entry {entry_id}: {e}")
        raise


def _format_preview(data: dict) -> str:
    """Format OCR result as a confirmation message."""
    def fmt(v):
        return f"${v:.2f}" if v is not None else "?"

    return (
        f"Z Report read:\n"
        f"Register: #{data.get('register', '?')}  |  Date: {data.get('date', '?')}\n"
        f"─────────────────────────\n"
        f"Cash:          {fmt(data.get('cash'))}\n"
        f"ATH:           {fmt(data.get('ath'))}\n"
        f"ATH Mobile:    {fmt(data.get('athm'))}\n"
        f"VISA:          {fmt(data.get('visa'))}\n"
        f"Master Card:   {fmt(data.get('mc'))}\n"
        f"American Exp:  {fmt(data.get('amex'))}\n"
        f"Discover:      {fmt(data.get('disc'))}\n"
        f"WIC/EBT:       {fmt(data.get('wic'))}\n"
        f"MCS OTC:       {fmt(data.get('mcs'))}\n"
        f"Triple-S OTC:  {fmt(data.get('sss'))}\n"
        f"Over/Short:    {fmt(data.get('variance'))}\n"
        f"─────────────────────────\n"
        f"Save this report? Reply YES or NO"
    )


def handle_update(update: dict) -> None:
    """
    Main entry point: dispatch an incoming Telegram update to the correct handler.
    Called from the Flask webhook route.
    """
    msg = update.get("message")
    if not msg:
        return  # ignore non-message updates (e.g., edited_message)

    telegram_id = msg["from"]["id"]
    tg_username = msg["from"].get("username", "")
    chat_id = msg["chat"]["id"]

    state = bot_state.get(telegram_id, {})
    current_state = state.get("state")

    # ── photo received ────────────────────────────────────────────────────────
    if "photo" in msg:
        if not current_state or current_state not in ("REGISTERED",):
            # Not registered yet — nudge them to register first
            if not is_registered(telegram_id):
                bot_state[telegram_id] = {"state": "AWAITING_USERNAME", "retry_count": 0}
                send_message(chat_id, "To register, enter your username:")
                return
            else:
                # Reload state from DB on bot restart
                user_row = get_bot_user(telegram_id)
                bot_state[telegram_id] = {
                    "state": "REGISTERED",
                    "store": user_row["store"],
                    "username": user_row["username"],
                    "retry_count": 0,
                }
                state = bot_state[telegram_id]  # use the new dict, not the old empty one
                current_state = "REGISTERED"

        _handle_photo(telegram_id, chat_id, tg_username, msg, state)
        return

    # ── text received ─────────────────────────────────────────────────────────
    text = (msg.get("text") or "").strip()

    if current_state == "AWAITING_DATE":
        _handle_date(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_REGISTER":
        _handle_register(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_CONFIRMATION":
        _handle_confirmation(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_STORE":
        chosen = _STORE_CHOICE.get(text)
        if not chosen:
            send_message(chat_id, "Reply with 1, 2, 3, or 4.")
            return
        state["store"] = chosen
        state["state"] = "REGISTERED"
        bot_state[telegram_id] = state
        # Now process the saved photo
        saved_msg = state.pop("pending_photo_msg", None)
        if saved_msg:
            _handle_photo(telegram_id, chat_id, tg_username, saved_msg, state)
        else:
            send_message(chat_id, f"Store: {chosen}. Send the Z Report photo.")
        return

    if current_state == "AWAITING_PASSWORD":
        _handle_password(telegram_id, chat_id, tg_username, text, state)
        return

    if current_state == "AWAITING_USERNAME":
        state["username"] = text
        state["state"] = "AWAITING_PASSWORD"
        bot_state[telegram_id] = state
        send_message(chat_id, "Enter your password:")
        return

    # ── default: start registration or show help ──────────────────────────────
    if is_registered(telegram_id):
        user_row = get_bot_user(telegram_id)
        bot_state[telegram_id] = {
            "state": "REGISTERED",
            "store": user_row["store"],
            "username": user_row["username"],
            "retry_count": 0,
        }
        send_message(chat_id, f"You are registered at {user_row['store']}. Send a Z Report photo to get started.")
    else:
        bot_state[telegram_id] = {"state": "AWAITING_USERNAME", "retry_count": 0}
        send_message(chat_id, "Hello! To register, enter your username:")


def _handle_password(telegram_id, chat_id, tg_username, password, state):
    username = state.get("username", "")
    user_row = verify_web_credentials(username, password)
    if user_row is None:
        # Failed — reset to AWAITING_USERNAME (don't reveal which field was wrong)
        state["state"] = "AWAITING_USERNAME"
        state.pop("username", None)
        bot_state[telegram_id] = state
        send_message(chat_id, "Incorrect username or password. Enter your username:")
        return

    # Success — register
    save_bot_user(telegram_id, user_row["username"], tg_username, user_row["store"])
    bot_state[telegram_id] = {
        "state": "REGISTERED",
        "store": user_row["store"],
        "username": user_row["username"],
        "retry_count": 0,
    }
    send_message(
        chat_id,
        f"Registered. Store: {user_row['store']}.\n"
        f"You can now send Z Report photos."
    )


def _handle_photo(telegram_id, chat_id, tg_username, msg, state):
    # If user has "All" store access, ask which store before processing
    if state.get("store") == "All":
        state["pending_photo_msg"] = msg
        state["state"] = "AWAITING_STORE"
        bot_state[telegram_id] = state
        send_message(chat_id, STORE_MENU)
        return

    send_message(chat_id, "Processing... please wait.")

    # Pick the largest photo (last in array)
    file_id = msg["photo"][-1]["file_id"]

    try:
        image_bytes = download_photo(file_id)
    except Exception as e:
        logger.error(f"Photo download failed: {e}")
        send_message(chat_id, "Could not download the photo. Please try again.")
        return

    retry_count = state.get("retry_count", 0)

    try:
        ocr_data = extract_z_report(image_bytes)
    except OCRParseError as e:
        logger.warning(f"OCR parse error for user {telegram_id}: {e}")
        _handle_ocr_failure(telegram_id, chat_id, state, retry_count)
        return
    except Exception as e:
        logger.error(f"OCR unexpected error: {e}")
        send_message(chat_id, "Error processing the image. Please try again.")
        return

    if has_null_fields(ocr_data):
        null_names = ", ".join(NULL_FIELD_NAMES(ocr_data))
        if retry_count >= 1:
            state["retry_count"] = 0
            bot_state[telegram_id] = state
            send_message(
                chat_id,
                f"Could not read: {null_names}.\n"
                f"Failed to process after 2 attempts.\n"
                f"Please enter this report manually in the system."
            )
            return
        state["retry_count"] = retry_count + 1
        bot_state[telegram_id] = state
        send_message(
            chat_id,
            f"Could not read some fields: {null_names}.\n"
            f"Take the photo closer with better lighting and try again.\n"
            f"(Attempt {retry_count + 1} of 2)"
        )
        return

    # All fields readable — ask for date confirmation
    state["state"] = "AWAITING_DATE"
    state["pending_data"] = ocr_data
    state["pending_image_bytes"] = image_bytes
    state["retry_count"] = 0
    bot_state[telegram_id] = state
    ocr_date = ocr_data.get("date") or "unknown"
    send_message(
        chat_id,
        f"What is the date of this Z report?\n"
        f"OCR read: {ocr_date}\n"
        f"Type the date (MM/DD/YYYY) or reply OK to confirm."
    )


def _handle_ocr_failure(telegram_id, chat_id, state, retry_count):
    if retry_count >= 1:
        state["retry_count"] = 0
        bot_state[telegram_id] = state
        send_message(
            chat_id,
            "Could not process the photo after 2 attempts.\n"
            "Please enter this report manually in the system."
        )
    else:
        state["retry_count"] = retry_count + 1
        bot_state[telegram_id] = state
        send_message(
            chat_id,
            "Could not read this report. Take the photo closer with better "
            f"lighting and try again. (Attempt {retry_count + 1} of 2)"
        )


def _parse_date(text: str) -> str | None:
    """
    Accept MM/DD/YYYY, MM-DD-YYYY, or YYYY-MM-DD.
    Returns YYYY-MM-DD string or None if unrecognised.
    """
    import re
    text = text.strip()
    # MM/DD/YYYY or MM-DD-YYYY
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    # YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return text
    return None


def _handle_date(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle AWAITING_DATE — let user confirm or override the OCR-read date."""
    if _ascii_upper(text) in ("OK", "YES", "SI", "CONFIRM"):
        # Keep OCR date as-is
        pass
    else:
        parsed = _parse_date(text)
        if parsed is None:
            send_message(
                chat_id,
                "Could not read that date. Please use MM/DD/YYYY (e.g. 02/20/2026) or reply OK to keep the OCR date."
            )
            return
        state["pending_data"]["date"] = parsed

    ocr_reg = state["pending_data"].get("register") or "unknown"
    state["state"] = "AWAITING_REGISTER"
    bot_state[telegram_id] = state
    send_message(
        chat_id,
        f"What is the cash register number?\n"
        f"OCR read: {ocr_reg}\n"
        f"Type the number or reply OK to confirm."
    )


def _handle_register(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle AWAITING_REGISTER — let user confirm or override the OCR-read register."""
    if _ascii_upper(text) not in ("OK", "YES", "SI", "CONFIRM"):
        text_stripped = text.strip()
        try:
            reg_num = int(text_stripped)
        except ValueError:
            send_message(
                chat_id,
                "Please enter a register number (e.g. 1) or reply OK to keep the OCR value."
            )
            return
        state["pending_data"]["register"] = reg_num

    state["state"] = "AWAITING_CONFIRMATION"
    bot_state[telegram_id] = state
    send_message(chat_id, _format_preview(state["pending_data"]))


def _ascii_upper(text: str) -> str:
    """Uppercase and strip accents so 'Yes' == 'YES', etc."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper()


def _handle_confirmation(telegram_id, chat_id, text, state):
    if _ascii_upper(text) == "YES":
        ocr_data = state["pending_data"]
        image_bytes = state["pending_image_bytes"]
        store = state["store"]
        username = state["username"]

        # 1. Upload image (log error but don't block the save)
        storage_path = None
        try:
            storage_path = upload_image_to_storage(
                image_bytes, store,
                ocr_data.get("date", "unknown"),
                ocr_data.get("register", 0),
            )
        except Exception as e:
            logger.error(f"Image upload failed: {e}")
            send_message(chat_id, "Warning: Could not upload the photo. The report will be saved without it.")

        # 2. Save audit entry → get entry_id
        try:
            entry_id = save_audit_entry(ocr_data, store, username)
        except Exception as e:
            logger.error(f"save_audit_entry failed: {e}")
            send_message(chat_id, "Error saving the report. Please try again or enter it manually.")
            return

        # 3. Save photo record (only if upload succeeded and we have an entry_id)
        if storage_path and entry_id:
            try:
                save_photo_record(
                    entry_id=entry_id,
                    store=store,
                    business_date=ocr_data.get("date", ""),
                    register_id=_format_register_id(ocr_data.get("register")),
                    uploaded_by=username,
                    storage_path=storage_path,
                )
            except Exception as e:
                logger.error(f"save_photo_record failed (entry still saved): {e}")

        gross = sum(ocr_data.get(f) or 0 for f in
                    ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss"])
        state["state"] = "REGISTERED"
        for key in ["pending_data", "pending_image_bytes"]:
            state.pop(key, None)
        bot_state[telegram_id] = state
        send_message(
            chat_id,
            f"Saved. Reg #{ocr_data.get('register', '?')} — "
            f"${gross:.2f} gross."
        )

    elif _ascii_upper(text) == "NO":
        state["state"] = "REGISTERED"
        for key in ["pending_data", "pending_image_bytes"]:
            state.pop(key, None)
        bot_state[telegram_id] = state
        send_message(chat_id, "Cancelled. Send another photo when ready.")
    else:
        send_message(chat_id, "Reply YES to save or NO to cancel.")


def register_webhook() -> None:
    """Register the Telegram webhook with Telegram's servers. Call on app startup."""
    token = _token()
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
        return

    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "carimas.up.railway.app")
    webhook_url = f"https://{domain}/api/telegram/webhook"

    from app import Config as _Config
    secret = (_Config.SECRET_KEY or "")[:32]
    resp = http.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={
            "url": webhook_url,
            "allowed_updates": ["message"],
            "secret_token": secret,
        },
        timeout=10,
    )
    if resp.ok and resp.json().get("ok"):
        logger.info(f"Telegram webhook registered: {webhook_url}")
    else:
        logger.error(f"Telegram webhook registration failed: {resp.text}")
