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
    "¿Para qué tienda es este reporte?\n"
    "1 — Carimas #1\n"
    "2 — Carimas #2\n"
    "3 — Carimas #3\n"
    "4 — Carthage\n"
    "Responde con el número."
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


def _calculate_variance(actual_cash: float, cash_sales: float, payouts: float) -> float:
    """
    variance = actual_cash - (cash_sales - payouts)
    Positive = over (more cash than expected)
    Negative = short (less cash than expected)
    """
    return round(actual_cash - (cash_sales - payouts), 2)


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


def upload_image_to_storage(image_bytes: bytes, store: str, date: str, register) -> str:
    """
    Upload photo to Supabase Storage z-reports bucket.
    Returns storage path string.
    Raises StorageUploadError on any failure — never returns empty string.
    """
    from app import supabase
    if supabase is None:
        raise StorageUploadError("Supabase client not initialized")
    store_slug = store.replace(" ", "_").replace("#", "")
    reg_num = int(register) if register else 0
    path = f"{store_slug}/{date}/reg{reg_num}_{int(time.time())}.jpg"
    try:
        supabase.storage.from_("z-reports").upload(
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
    from app import supabase
    if supabase is None:
        logger.warning("save_photo_record: supabase not available")
        return
    try:
        supabase.table("z_report_photos").insert({
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


def _format_full_summary(
    ocr_data: dict, payouts: float, actual_cash: float, variance: float
) -> str:
    """Format the confirmation summary shown before manager says SI/NO."""
    cash = ocr_data.get("cash") or 0
    cards = sum(ocr_data.get(f) or 0 for f in
                ["ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss"])
    gross = cash + cards
    var_sign = "+" if variance >= 0 else ""
    return (
        f"📋 Resumen del Reporte:\n"
        f"Registro: #{ocr_data.get('register', '?')}  |  Fecha: {ocr_data.get('date', '?')}\n"
        f"─────────────────────────\n"
        f"💵 Ventas efectivo:  ${cash:.2f}\n"
        f"💳 Ventas tarjetas:  ${cards:.2f}\n"
        f"📊 Total bruto:      ${gross:.2f}\n"
        f"─────────────────────────\n"
        f"💸 Retiros:          ${payouts:.2f}\n"
        f"🏦 Efectivo real:    ${actual_cash:.2f}\n"
        f"📐 Varianza:         {var_sign}${abs(variance):.2f}\n"
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

    if current_state == "AWAITING_PAYOUTS":
        _handle_payouts(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_CASH":
        _handle_cash(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_CONFIRMATION":
        _handle_confirmation(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_STORE":
        chosen = _STORE_CHOICE.get(text)
        if not chosen:
            send_message(chat_id, "Responde con 1, 2, 3 o 4.")
            return
        state["store"] = chosen
        state["state"] = "REGISTERED"
        bot_state[telegram_id] = state
        # Now process the saved photo
        saved_msg = state.pop("pending_photo_msg", None)
        if saved_msg:
            _handle_photo(telegram_id, chat_id, tg_username, saved_msg, state)
        else:
            send_message(chat_id, f"Tienda: {chosen}. Envía la foto del Reporte Z.")
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
    # If user has "All" store access, ask which store before processing
    if state.get("store") == "All":
        state["pending_photo_msg"] = msg
        state["state"] = "AWAITING_STORE"
        bot_state[telegram_id] = state
        send_message(chat_id, STORE_MENU)
        return

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

    # All fields readable — begin reconciliation flow
    state["state"] = "AWAITING_PAYOUTS"
    state["pending_data"] = ocr_data
    state["pending_image_bytes"] = image_bytes
    state["retry_count"] = 0
    bot_state[telegram_id] = state
    send_message(
        chat_id,
        f"✅ Reporte leído: Reg #{ocr_data.get('register', '?')}, {ocr_data.get('date', '?')}\n"
        f"💸 ¿Hubo retiros del cajón? Ingresa el monto o 0:"
    )


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


def _handle_payouts(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle AWAITING_PAYOUTS state — parse payout amount from manager input."""
    try:
        payouts = float(text.replace(",", ".").strip())
        if payouts < 0:
            raise ValueError("negative value")
    except ValueError:
        send_message(chat_id, "Por favor ingresa un número válido (ej: 25.50 o 0):")
        return

    state["pending_payouts"] = payouts
    state["state"] = "AWAITING_CASH"
    bot_state[telegram_id] = state
    send_message(chat_id, "💵 ¿Cuánto efectivo real hay en el cajón?")


def _handle_cash(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle AWAITING_CASH state — parse actual cash, calculate variance, show summary."""
    try:
        actual_cash = float(text.replace(",", ".").strip())
        if actual_cash < 0:
            raise ValueError("negative value")
    except ValueError:
        send_message(chat_id, "Por favor ingresa un número válido (ej: 150.00):")
        return

    ocr_data = state["pending_data"]
    payouts = state.get("pending_payouts", 0.0)
    cash_sales = ocr_data.get("cash") or 0
    variance = _calculate_variance(actual_cash, cash_sales, payouts)

    state["pending_actual_cash"] = actual_cash
    state["pending_variance"] = variance
    state["state"] = "AWAITING_CONFIRMATION"
    bot_state[telegram_id] = state

    send_message(chat_id, _format_full_summary(ocr_data, payouts, actual_cash, variance))


def _ascii_upper(text: str) -> str:
    """Uppercase and strip accents so 'Sí' == 'SI', 'No' == 'NO', etc."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper()


def _handle_confirmation(telegram_id, chat_id, text, state):
    if _ascii_upper(text) == "SI":
        ocr_data = state["pending_data"]
        image_bytes = state["pending_image_bytes"]
        store = state["store"]
        username = state["username"]
        payouts = state.get("pending_payouts", 0.0)
        actual_cash = state.get("pending_actual_cash", 0.0)
        # Use stored variance; fall back to calculation if coming from old flow
        variance = state.get("pending_variance")
        if variance is None:
            variance = _calculate_variance(
                actual_cash, ocr_data.get("cash") or 0, payouts
            )

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
            send_message(chat_id, "⚠️ No se pudo subir la imagen. El reporte se guardará sin foto.")

        # 2. Save audit entry → get entry_id
        try:
            entry_id = save_audit_entry(
                ocr_data, store, username,
                payouts=payouts, actual_cash=actual_cash, variance=variance,
            )
        except Exception as e:
            logger.error(f"save_audit_entry failed: {e}")
            send_message(chat_id, "Error guardando el reporte. Intenta de nuevo o ingresa manualmente.")
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
        for key in ["pending_data", "pending_image_bytes", "pending_payouts",
                    "pending_actual_cash", "pending_variance"]:
            state.pop(key, None)
        bot_state[telegram_id] = state
        send_message(
            chat_id,
            f"✅ Guardado. Reg #{ocr_data.get('register', '?')} — "
            f"${gross:.2f} bruto, varianza ${variance:+.2f}."
        )

    elif _ascii_upper(text) == "NO":
        state["state"] = "REGISTERED"
        for key in ["pending_data", "pending_image_bytes", "pending_payouts",
                    "pending_actual_cash", "pending_variance"]:
            state.pop(key, None)
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
