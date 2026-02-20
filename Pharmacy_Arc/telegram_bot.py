"""
Telegram bot for Z Report submission.
Uses raw Telegram Bot API (via requests) — no python-telegram-bot library needed.
Conversation state is kept in-memory; bot_users registration is persisted in Supabase.
"""
import os
import io
import time
import logging
import requests as http

from ocr import extract_z_report, has_null_fields, NULL_FIELD_NAMES, OCRParseError

logger = logging.getLogger(__name__)

# In-memory conversation state: { telegram_id: { state, username, store, ... } }
bot_state: dict = {}

_BOT_TOKEN = None  # loaded lazily from env


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
    Verify username/password against the users table using bcrypt.
    Returns the user row dict if valid, None if invalid.
    """
    from app import supabase
    from security import PasswordHasher
    if supabase is None:
        return None
    try:
        result = supabase.table("users").select("*").eq("username", username).execute()
        if not result.data:
            return None
        user = result.data[0]
        hasher = PasswordHasher()
        if hasher.verify_password(password, user["password"]):
            return user
        return None
    except Exception as e:
        logger.error(f"verify_web_credentials failed: {e}")
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


def upload_image_to_storage(image_bytes: bytes, store: str, date: str, register: int) -> str:
    """Upload photo to Supabase Storage z-reports bucket. Returns public path."""
    from app import supabase
    if supabase is None:
        return ""
    store_slug = store.replace(" ", "_").replace("#", "")
    path = f"{store_slug}/{date}/reg{register}_{int(time.time())}.jpg"
    supabase.storage.from_("z-reports").upload(
        path,
        image_bytes,
        {"content-type": "image/jpeg"},
    )
    return path


def save_audit_entry(data: dict, store: str, username: str, image_path: str) -> None:
    """Save the extracted Z report data to the audits table."""
    from app import supabase, validate_audit_entry, save_to_queue
    if supabase is None:
        return

    # Build payload matching the existing app format
    reg_str = f"Reg {data['register']}"
    gross = (
        (data.get("cash") or 0) + (data.get("ath") or 0) + (data.get("athm") or 0) +
        (data.get("visa") or 0) + (data.get("mc") or 0) + (data.get("amex") or 0) +
        (data.get("disc") or 0) + (data.get("wic") or 0) + (data.get("mcs") or 0) +
        (data.get("sss") or 0)
    )
    net = gross  # no payout data from Z report
    variance = float(data.get("variance") or 0)

    payload = {
        "date": data["date"],
        "reg": reg_str,
        "staff": username,
        "store": store,
        "gross": gross,
        "net": net,
        "variance": variance,
        "source": "telegram_bot",
        "submitted_by_telegram": username,
        "z_report_image_path": image_path,
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
        },
    }

    record = {
        "date": data["date"],
        "reg": reg_str,
        "staff": username,
        "store": store,
        "gross": gross,
        "net": net,
        "variance": variance,
        "payload": payload,
    }

    try:
        supabase.table("audits").insert(record).execute()
    except Exception as e:
        logger.warning(f"DB save failed, queuing offline: {e}")
        save_to_queue(record)


def _format_preview(data: dict) -> str:
    """Format OCR result as a Spanish confirmation message."""
    def fmt(v):
        return f"${v:.2f}" if v is not None else "❓"

    return (
        f"📋 Reporte extraído:\n"
        f"Registro: #{data.get('register', '?')}  |  Fecha: {data.get('date', '?')}\n"
        f"─────────────────────────\n"
        f"Efectivo:      {fmt(data.get('cash'))}\n"
        f"ATH:           {fmt(data.get('ath'))}\n"
        f"ATH Móvil:     {fmt(data.get('athm'))}\n"
        f"VISA:          {fmt(data.get('visa'))}\n"
        f"Master Card:   {fmt(data.get('mc'))}\n"
        f"American Exp:  {fmt(data.get('amex'))}\n"
        f"Discover:      {fmt(data.get('disc'))}\n"
        f"WIC/EBT:       {fmt(data.get('wic'))}\n"
        f"MCS OTC:       {fmt(data.get('mcs'))}\n"
        f"Triple-S OTC:  {fmt(data.get('sss'))}\n"
        f"Over/Short:    {fmt(data.get('variance'))}\n"
        f"─────────────────────────\n"
        f"¿Guardar este reporte? Responde SI o NO"
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
                send_message(chat_id, "Para registrarte, introduce tu usuario:")
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
                current_state = "REGISTERED"

        _handle_photo(telegram_id, chat_id, tg_username, msg, state)
        return

    # ── text received ─────────────────────────────────────────────────────────
    text = (msg.get("text") or "").strip()

    if current_state == "AWAITING_CONFIRMATION":
        _handle_confirmation(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_PASSWORD":
        _handle_password(telegram_id, chat_id, tg_username, text, state)
        return

    if current_state == "AWAITING_USERNAME":
        state["username"] = text
        state["state"] = "AWAITING_PASSWORD"
        bot_state[telegram_id] = state
        send_message(chat_id, "Introduce tu contraseña:")
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
        send_message(chat_id, f"Ya estás registrado en {user_row['store']}. Envía una foto del Reporte Z para empezar.")
    else:
        bot_state[telegram_id] = {"state": "AWAITING_USERNAME", "retry_count": 0}
        send_message(chat_id, "Hola! Para registrarte, introduce tu usuario:")


def _handle_password(telegram_id, chat_id, tg_username, password, state):
    username = state.get("username", "")
    user_row = verify_web_credentials(username, password)
    if user_row is None:
        # Failed — reset to AWAITING_USERNAME (don't reveal which field was wrong)
        state["state"] = "AWAITING_USERNAME"
        state.pop("username", None)
        bot_state[telegram_id] = state
        send_message(chat_id, "Usuario o contraseña incorrectos. Introduce tu usuario:")
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
        f"✅ Registrado/a. Tienda: {user_row['store']}.\n"
        f"Ya puedes enviar fotos del Reporte Z."
    )


def _handle_photo(telegram_id, chat_id, tg_username, msg, state):
    send_message(chat_id, "Procesando... ⏳")

    # Pick the largest photo (last in array)
    file_id = msg["photo"][-1]["file_id"]

    try:
        image_bytes = download_photo(file_id)
    except Exception as e:
        logger.error(f"Photo download failed: {e}")
        send_message(chat_id, "No pude descargar la foto. Intenta de nuevo.")
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
        send_message(chat_id, "Error procesando la imagen. Intenta de nuevo.")
        return

    if has_null_fields(ocr_data):
        null_names = ", ".join(NULL_FIELD_NAMES(ocr_data))
        if retry_count >= 1:
            state["retry_count"] = 0
            bot_state[telegram_id] = state
            send_message(
                chat_id,
                f"No se pudo leer: {null_names}.\n"
                f"No se pudo procesar después de 2 intentos.\n"
                f"Por favor ingresa este reporte manualmente en el sistema."
            )
            return
        state["retry_count"] = retry_count + 1
        bot_state[telegram_id] = state
        send_message(
            chat_id,
            f"No pude leer algunos campos: {null_names}.\n"
            f"Toma la foto más cerca y con mejor iluminación e intenta de nuevo.\n"
            f"(Intento {retry_count + 1} de 2)"
        )
        return

    # All fields readable — show preview
    state["state"] = "AWAITING_CONFIRMATION"
    state["pending_data"] = ocr_data
    state["pending_image_bytes"] = image_bytes
    state["retry_count"] = 0
    bot_state[telegram_id] = state
    send_message(chat_id, _format_preview(ocr_data))


def _handle_ocr_failure(telegram_id, chat_id, state, retry_count):
    if retry_count >= 1:
        state["retry_count"] = 0
        bot_state[telegram_id] = state
        send_message(
            chat_id,
            "No se pudo procesar la foto después de 2 intentos.\n"
            "Por favor ingresa este reporte manualmente en el sistema."
        )
    else:
        state["retry_count"] = retry_count + 1
        bot_state[telegram_id] = state
        send_message(
            chat_id,
            "No pude leer este reporte. Toma la foto más cerca y con mejor "
            f"iluminación e intenta de nuevo. (Intento {retry_count + 1} de 2)"
        )


def _handle_confirmation(telegram_id, chat_id, text, state):
    if text.upper() == "SI":
        ocr_data = state["pending_data"]
        image_bytes = state["pending_image_bytes"]
        store = state["store"]
        username = state["username"]

        try:
            image_path = upload_image_to_storage(
                image_bytes, store,
                ocr_data.get("date", "unknown"),
                ocr_data.get("register", 0),
            )
        except Exception as e:
            logger.error(f"Image upload failed: {e}")
            image_path = ""

        try:
            save_audit_entry(ocr_data, store, username, image_path)
        except Exception as e:
            logger.error(f"save_audit_entry failed: {e}")
            send_message(chat_id, "Error guardando el reporte. Intenta de nuevo o ingresa manualmente.")
            return

        net = sum(ocr_data.get(f) or 0 for f in
                  ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss"])
        state["state"] = "REGISTERED"
        state.pop("pending_data", None)
        state.pop("pending_image_bytes", None)
        bot_state[telegram_id] = state
        send_message(chat_id, f"✅ Guardado. Reg #{ocr_data.get('register', '?')} — ${net:.2f} bruto.")

    elif text.upper() == "NO":
        state["state"] = "REGISTERED"
        state.pop("pending_data", None)
        state.pop("pending_image_bytes", None)
        bot_state[telegram_id] = state
        send_message(chat_id, "Cancelado. Envía otra foto cuando estés listo.")
    else:
        send_message(chat_id, "Responde SI para guardar o NO para cancelar.")


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
