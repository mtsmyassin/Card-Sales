"""
Telegram bot for Z Report submission.
Uses raw Telegram Bot API (via requests) — no python-telegram-bot library needed.
Conversation state is kept in-memory and persisted to Supabase bot_sessions table.
"""
import os
import io
import time
import logging
import threading
import unicodedata
import requests as http

from ocr import extract_z_report, has_null_fields, null_field_names, OCRParseError
from ai_assistant import ask_ai
import extensions
from config import Config
from helpers.db import is_unique_violation

logger = logging.getLogger(__name__)

# In-memory conversation state: { telegram_id: { state, username, store, ... } }
# NOTE: This dict is per-process — not shared across Gunicorn workers.
# On cache miss, state is loaded from the Supabase bot_sessions table (see load_session).
# For single-worker deployments (Railway default) this is fine.  For multi-worker,
# the DB fallback handles it but adds one extra read per first message per worker.
bot_state: dict = {}
_bot_state_lock = threading.Lock()

# AI conversation history: { telegram_id: [{"role": "user", "content": ...}, ...] }
_ai_history: dict[int, list[dict]] = {}

# Load bot token at import time so a missing token is caught at startup, not on the first message.
_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not _BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN is not set — Telegram bot will refuse all requests")

KNOWN_STORES = Config.STORES
STORE_MENU = (
    "¿Para cuál tienda es este reporte?\n"
    + "\n".join(f"{i} — {s}" for i, s in enumerate(KNOWN_STORES, 1))
    + "\nResponde con el número."
)
_STORE_CHOICE = {str(i): s for i, s in enumerate(KNOWN_STORES, 1)}

# ── Messages (Spanish) ─────────────────────────────────────────────────────────
MSG_REGISTER_START = "Bienvenido a Carimas Bot. Ingresa tu usuario para registrarte:"
MSG_ENTER_PASSWORD = "Contraseña:"
MSG_BAD_CREDENTIALS = "Usuario o contraseña incorrectos. Ingresa tu usuario:"
MSG_REGISTERED = "✅ Registrado. Tienda: {store}.\nEnvía una foto del Reporte Z para comenzar."
MSG_WELCOME_BACK = "Registrado en {store}. Envía la foto del Reporte Z."
MSG_PHOTO_SEND = "Envía la foto del Reporte Z."
MSG_PROCESSING = "Procesando... por favor espera."
MSG_OCR_DATE = (
    "¿Cuál es la fecha del reporte Z?\n"
    "OCR: {date}\n"
    "Escribe la fecha (MM/DD/AAAA) o responde OK para confirmar."
)
MSG_OCR_REG = (
    "¿Número de caja registradora?\n"
    "OCR: {reg}\n"
    "Escribe el número o responde OK para confirmar."
)
MSG_BAD_DATE = "No se pudo leer la fecha. Usa MM/DD/AAAA (ej. 02/20/2026) o responde OK."
MSG_BAD_REG = "Ingresa un número de caja (ej. 1) o responde OK para mantener el valor del OCR."
MSG_YES_NO = "Responde SÍ para guardar o NO para cancelar."
MSG_SAVED = (
    "✅ Guardado{photo_note}. Caja #{reg} — ${gross:.2f} bruto.\n"
    "Si no lo ves en la app, selecciona el filtro 'Todos'."
)
MSG_CANCELLED = "Cancelado. Envía otra foto cuando estés listo."
MSG_INVALID_STORE = "Responde con 1, 2, 3, 4 o 5."
MSG_STORE_CONFIRM = "Tienda: {store}. Envía la foto del Reporte Z."
MSG_OCR_FAIL_RETRY = (
    "⚠️ No se pudo leer el reporte.\n"
    "Consejos: sostén la cámara directamente encima del recibo, "
    "con buena iluminación y sin sombras. (Intento {attempt} de 2)"
)
MSG_OCR_FAIL_FINAL = (
    "⚠️ No se pudo procesar la foto después de 2 intentos.\n"
    "Consejos:\n"
    "  • Superficie plana, cámara directamente encima\n"
    "  • Buena iluminación, sin flash directo\n"
    "  • Todo el recibo visible en la foto\n"
    "Ingresa este reporte manualmente en la app web."
)
MSG_NULL_RETRY = (
    "⚠️ No se pudo leer: {fields}.\n"
    "Asegúrate de que esas secciones del recibo estén visibles.\n"
    "Toma la foto más cerca, con buena iluminación y sin sombras. (Intento {attempt} de 2)"
)
MSG_NULL_FINAL = (
    "⚠️ No se pudo leer: {fields}.\n"
    "Fallo tras 2 intentos. Consejos:\n"
    "  • Coloca el recibo en una superficie plana\n"
    "  • Sostén la cámara directamente encima\n"
    "  • Usa buena iluminación, sin flash directo\n"
    "Ingresa este reporte manualmente en la app web."
)
MSG_PHOTO_WARN = "⚠️ No se pudo subir la foto. El reporte se guardará sin ella."
MSG_DB_ERROR = "❌ Error guardando el reporte. Por favor ingrésalo manualmente en la app web."
MSG_PHOTO_DL_ERROR = "No se pudo descargar la foto. Inténtalo de nuevo."
MSG_OCR_ERROR = "Error procesando la imagen. Inténtalo de nuevo."
MSG_SESSION_RESET = (
    "Tu sesión fue restaurada después de un reinicio del sistema.\n"
    "Por favor envía la foto del Reporte Z de nuevo."
)
MSG_HELP = (
    "📋 Carimas Bot — Ayuda\n\n"
    "Comandos disponibles:\n"
    "  /help      — Ver esta ayuda\n"
    "  /status    — Ver tu estado actual\n"
    "  /cancel    — Cancelar la operación en curso\n"
    "  /last      — Ver el último reporte enviado\n"
    "  /broadcast — Enviar mensaje a todos (solo admin)\n\n"
    "Cómo enviar un Reporte Z:\n"
    "  1. Regístrate con tu usuario y contraseña del sistema\n"
    "  2. Envía una foto clara y bien iluminada del Reporte Z\n"
    "  3. Confirma la fecha y número de caja\n"
    "  4. Responde SÍ para guardar el reporte\n\n"
    "🤖 Asistente AI:\n"
    "  Toca 'Preguntar AI' para consultar datos de ventas y varianzas."
)
MSG_STATUS_REGISTERED = (
    "Estado: ✅ Registrado\n"
    "Tienda: {store}\n"
    "Usuario: {username}\n"
    "Listo para recibir fotos de Reporte Z."
)
MSG_STATUS_UNREGISTERED = (
    "Estado: ❌ No registrado\n"
    "Envía cualquier mensaje para comenzar el registro."
)
MSG_STATUS_MIDFLOW = (
    "Estado: En proceso ({state})\n"
    "Usuario: {username}\n"
    "Usa /cancel para reiniciar."
)
MSG_CANCEL_OK = "Operación cancelada. Envía una foto del Reporte Z cuando estés listo."
MSG_CANCEL_NOTHING = "No hay ninguna operación activa en este momento."
MSG_AI_WELCOME = (
    "🤖 Modo Asistente AI activado.\n\n"
    "Puedes preguntarme sobre ventas, varianzas, o cualquier dato de tu tienda.\n"
    "Ejemplos:\n"
    "  • ¿Cuánto fue el bruto de ayer?\n"
    "  • ¿Cuál caja tiene más varianza?\n"
    "  • Resume las ventas de esta semana\n\n"
    "Envía /cancel para salir del modo AI.\n"
    "Enviar una foto sigue funcionando normalmente."
)
MSG_AI_EXIT = "Modo AI desactivado. Envía una foto del Reporte Z cuando estés listo."
MSG_PAYOUTS = (
    "💵 ¿Cuánto fue el total de payouts/desembolsos?\n"
    "Escribe el monto (ej. 50.00) o toca el botón si no hubo."
)
MSG_ACTUAL_CASH = (
    "💰 ¿Cuánto efectivo hay en la caja?\n"
    "Escribe el monto contado, o toca Omitir para usar la varianza del OCR."
)
MSG_BAD_AMOUNT = "Ingresa un monto válido (ej. 50.00 o 0)."
MSG_BROADCAST_CONFIRM = (
    "📢 Mensaje a enviar a {count} usuarios:\n\n"
    "{message}\n\n"
    "¿Confirmar envío?"
)
MSG_BROADCAST_SENT = "✅ Mensaje enviado a {sent} de {total} usuarios."
MSG_BROADCAST_CANCELLED = "Envío cancelado."
MSG_BROADCAST_NO_PERMISSION = "⛔ Solo administradores pueden usar /broadcast."


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
    if not _BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set — add it to Railway Variables"
        )
    return _BOT_TOKEN


def _tg(method: str, **kwargs) -> dict:
    """Call a Telegram Bot API method."""
    resp = http.post(
        f"https://api.telegram.org/bot{_token()}/{method}",
        json=kwargs,
        timeout=15,
    )
    return resp.json()


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    kwargs = {"chat_id": chat_id, "text": text}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    _tg("sendMessage", **kwargs)


def download_photo(file_id: str) -> bytes:
    """Download a photo from Telegram by file_id, return raw bytes."""
    info = _tg("getFile", file_id=file_id)
    file_path = info["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{_token()}/{file_path}"
    return http.get(url, timeout=30).content


# ── State persistence ──────────────────────────────────────────────────────────

def persist_session(telegram_id: int, state: dict) -> None:
    """Upsert bot session state to Supabase bot_sessions table.

    Required table (run once in Supabase SQL editor):
        CREATE TABLE IF NOT EXISTS bot_sessions (
            telegram_id  BIGINT PRIMARY KEY,
            state        TEXT    DEFAULT 'AWAITING_USERNAME',
            username     TEXT,
            store        TEXT,
            retry_count  INT     DEFAULT 0,
            pending_data JSONB,
            updated_at   TIMESTAMPTZ DEFAULT now()
        );
    """
    try:
        client = extensions.get_db()
        if client is None:
            return
        # Exclude image bytes (binary, too large) and pending_photo_msg (Telegram dict)
        client.table("bot_sessions").upsert({
            "telegram_id": telegram_id,
            "state": state.get("state", "AWAITING_USERNAME"),
            "username": state.get("username"),
            "store": state.get("store"),
            "retry_count": state.get("retry_count", 0),
            "pending_data": state.get("pending_data"),
        }).execute()
    except Exception as e:
        logger.warning(f"persist_session failed for {telegram_id}: {e}")


def load_session(telegram_id: int) -> dict | None:
    """Load bot session state from Supabase bot_sessions table.
    Returns None if not found or DB unavailable.
    """
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
        }
    except Exception as e:
        logger.warning(f"load_session failed for {telegram_id}: {e}")
        return None


def _set_state(telegram_id: int, state: dict) -> None:
    """Update in-memory bot_state (under lock) and fire-and-forget persist to Supabase."""
    with _bot_state_lock:
        bot_state[telegram_id] = state
    # Persist asynchronously so the dispatch thread is never blocked by a slow DB write.
    # Copy state to avoid race conditions — the caller may mutate the dict after this call.
    t = threading.Thread(target=persist_session, args=(telegram_id, state.copy()), daemon=True)
    t.start()


# ── User helpers ───────────────────────────────────────────────────────────────

def is_registered(telegram_id: int) -> bool:
    """Check if telegram_id exists in bot_users Supabase table."""
    if extensions.supabase is None:
        return False
    try:
        result = extensions.supabase.table("bot_users").select("telegram_id").eq(
            "telegram_id", telegram_id
        ).execute()
        return len(result.data) > 0
    except Exception as e:
        logger.error(f"bot_users lookup failed: {e}")
        return False


def get_bot_user(telegram_id: int) -> dict | None:
    """Return bot_users row for telegram_id, or None."""
    if extensions.supabase is None:
        return None
    try:
        result = extensions.supabase.table("bot_users").select("*").eq(
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
        supabase = extensions.supabase
        EMERGENCY_ACCOUNTS = extensions.EMERGENCY_ACCOUNTS
        password_hasher = extensions.password_hasher
    except Exception as e:
        logger.error(f"verify_web_credentials: extensions access failed: {e}")
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
            logger.error(f"[bot] User {username!r} has unhashed password in DB — rejecting login")
            valid = False
        return user if valid else None
    except Exception as e:
        logger.error(f"verify_web_credentials failed: {e}", exc_info=True)
        return None


def save_bot_user(telegram_id: int, username: str, tg_username: str, store: str) -> None:
    """Upsert a row in bot_users."""
    if extensions.supabase is None:
        return
    extensions.supabase.table("bot_users").upsert({
        "telegram_id": telegram_id,
        "username": username,
        "store": store,
    }).execute()


# ── Storage helpers ────────────────────────────────────────────────────────────

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
    if extensions.supabase_admin is None:
        raise StorageUploadError(
            "SUPABASE_SERVICE_KEY not configured — photo upload disabled"
        )
    _ensure_bucket(extensions.supabase_admin)
    store_slug = store.replace(" ", "_").replace("#", "")
    reg_num = int(register) if register else 0
    path = f"{store_slug}/{date}/reg{reg_num}_{int(time.time())}.jpg"
    try:
        extensions.supabase_admin.storage.from_("z-reports").upload(
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
    # Use service-role client so RLS doesn't block bot inserts
    client = extensions.get_db()
    if client is None:
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
        result = client.table("audits").insert(record).execute()
        entry_id = result.data[0]["id"]
        logger.info(
            f"[BOT] audit saved: entry_id={entry_id} store={store!r} "
            f"date={record['date']!r} staff={username!r}"
        )
        return entry_id
    except Exception as e:
        if is_unique_violation(e):
            logger.warning(
                f"[BOT] Duplicate rejected by DB constraint — "
                f"store={store!r} date={record['date']!r} reg={record['reg']!r}"
            )
            raise ValueError(
                f"Ya existe un reporte para {record['date']} / {store} / {record['reg']}"
            ) from e
        # Do NOT fall back to the filesystem queue — it is ephemeral on Railway
        # and will be silently lost on every redeploy.  Raise loudly instead.
        logger.error(
            f"[BOT] FATAL: DB insert failed — store={store!r} date={record['date']!r}: {e}",
            exc_info=True,
        )
        raise


def save_photo_record(
    entry_id: int,
    store: str,
    business_date: str,
    register_id: str,
    uploaded_by: str,
    storage_path: str,
    content_type: str = "image/jpeg",
) -> None:
    """Insert a photo record into z_report_photos, linked to an audit entry."""
    # Prefer service-role client so RLS doesn't block the insert
    client = extensions.get_db()
    if client is None:
        logger.warning("save_photo_record: no supabase client available")
        return
    try:
        result = client.table("z_report_photos").insert({
            "entry_id": entry_id,
            "store": store,
            "business_date": business_date,
            "register_id": register_id,
            "uploaded_by": uploaded_by,
            "storage_path": storage_path,
            "content_type": content_type,
        }).execute()
        photo_id = result.data[0]["id"] if result.data else None
        logger.info(
            f"[BOT] photo record saved: photo_id={photo_id} entry_id={entry_id} "
            f"store={store!r} path={storage_path!r}"
        )
    except Exception as e:
        logger.error(
            f"[BOT] save_photo_record FAILED: entry_id={entry_id} path={storage_path!r}: {e}",
            exc_info=True,
        )
        raise


def _format_preview(data: dict) -> str:
    """Format OCR result as a Spanish confirmation message."""
    def fmt(v):
        return f"${v:.2f}" if v is not None else "?"

    return (
        f"Reporte Z leído:\n"
        f"Caja: #{data.get('register', '?')}  |  Fecha: {data.get('date', '?')}\n"
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
        f"Sobre/Corto:   {fmt(data.get('variance'))}\n"
        f"─────────────────────────\n"
        f"¿Guardar este reporte? Responde SÍ o NO"
    )


# ── Keyboard helpers ──────────────────────────────────────────────────────

BTN_AI = "🤖 Preguntar AI"
BTN_CANCEL = "❌ Cancelar"

def _kb_registered() -> dict:
    """Reply keyboard for REGISTERED state — includes AI button."""
    return {
        "keyboard": [[BTN_AI]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

def _kb_ai_chat() -> dict:
    """Reply keyboard for AI_CHAT state — shows cancel button."""
    return {
        "keyboard": [[BTN_CANCEL]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

def _kb_remove() -> dict:
    """Remove the custom keyboard."""
    return {"remove_keyboard": True}


def _inline_kb(buttons: list[list[dict]]) -> dict:
    """Build an inline keyboard markup."""
    return {"inline_keyboard": buttons}


def _inline_btn(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


INLINE_STORES = _inline_kb([
    [_inline_btn(s, f"store:{i}") for i, s in enumerate(KNOWN_STORES, 1)
     if i <= 3],
    [_inline_btn(s, f"store:{i}") for i, s in enumerate(KNOWN_STORES, 1)
     if i > 3],
])

INLINE_CONFIRM_DATE = _inline_kb([
    [_inline_btn("\u2705 OK", "date:ok"), _inline_btn("\u270f\ufe0f Corregir", "date:edit")],
])

INLINE_CONFIRM_REG = _inline_kb([
    [_inline_btn("\u2705 OK", "reg:ok"), _inline_btn("\u270f\ufe0f Corregir", "reg:edit")],
])

INLINE_SAVE = _inline_kb([
    [_inline_btn("\u2705 S\u00cd Guardar", "save:yes"), _inline_btn("\u274c NO Cancelar", "save:no")],
])

INLINE_PAYOUTS_ZERO = _inline_kb([
    [_inline_btn("Sin payouts ($0)", "payouts:0")],
])

INLINE_SKIP_CASH = _inline_kb([
    [_inline_btn("Omitir", "actual_cash:skip")],
])

INLINE_BROADCAST_CONFIRM = _inline_kb([
    [_inline_btn("✅ Enviar", "broadcast:yes"), _inline_btn("❌ Cancelar", "broadcast:no")],
])


def _handle_ai_message(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle a text message while in AI_CHAT state."""
    store = state.get("store", "")
    username = state.get("username", "")
    # Get role from bot_users if available
    user_row = get_bot_user(telegram_id)
    role = user_row.get("role", "staff") if user_row else "staff"

    history = _ai_history.get(telegram_id, [])

    try:
        response = ask_ai(text, store, role, username, history=history)
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        response = "Lo siento, ocurrió un error. Intenta de nuevo."

    # Append to history (cap at 10 messages = 5 pairs)
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": response})
    _ai_history[telegram_id] = history[-10:]

    send_message(chat_id, response, reply_markup=_kb_ai_chat())


# ── Placeholder stubs (implemented in later tasks) ───────────────────────────

def _handle_payouts(telegram_id, chat_id, text, state):
    """Handle AWAITING_PAYOUTS — parse payout amount."""
    text = str(text).strip().replace("$", "").replace(",", "")
    try:
        payouts = float(text)
    except ValueError:
        send_message(chat_id, MSG_BAD_AMOUNT)
        return
    state["pending_payouts"] = round(payouts, 2)
    state["state"] = "AWAITING_ACTUAL_CASH"
    _set_state(telegram_id, state)
    send_message(chat_id, MSG_ACTUAL_CASH, reply_markup=INLINE_SKIP_CASH)

def _handle_actual_cash(telegram_id, chat_id, text, state):
    """Handle AWAITING_ACTUAL_CASH — parse cash amount or skip."""
    text_clean = str(text).strip()
    if text_clean.lower() in ("skip", "omitir"):
        # Keep OCR variance as-is
        state["pending_actual_cash"] = None
        state["pending_variance"] = None
    else:
        text_clean = text_clean.replace("$", "").replace(",", "")
        try:
            actual_cash = float(text_clean)
        except ValueError:
            send_message(chat_id, MSG_BAD_AMOUNT)
            return
        state["pending_actual_cash"] = round(actual_cash, 2)
        # variance = actual_cash - (ocr_cash - payouts)
        ocr_cash = state.get("pending_data", {}).get("cash") or 0
        payouts = state.get("pending_payouts", 0)
        state["pending_variance"] = round(actual_cash - (ocr_cash - payouts), 2)

    state["state"] = "AWAITING_CONFIRMATION"
    _set_state(telegram_id, state)
    send_message(chat_id, _format_preview(state["pending_data"]), reply_markup=INLINE_SAVE)

def _handle_broadcast_confirm(telegram_id, chat_id, text, state):
    """Handle BROADCAST_CONFIRM — send or cancel the broadcast."""
    if _ascii_upper(str(text)) in ("YES", "SI", "SÍ"):
        broadcast_msg = state.get("pending_broadcast", "")
        sent, total = 0, 0
        try:
            db = extensions.get_db()
            users_resp = db.table("bot_users").select("telegram_id").execute()
            targets = users_resp.data or []
            total = len(targets)
            for u in targets:
                tid = u["telegram_id"]
                if tid == telegram_id:
                    continue  # don't send to self
                try:
                    send_message(tid, f"📢 {broadcast_msg}")
                    sent += 1
                except Exception as exc:
                    logger.error(f"Broadcast send failed tid={tid}: {exc}")
        except Exception as e:
            logger.error(f"Broadcast failed: {e}")
        new_state = {
            "state": "REGISTERED",
            "store": state.get("store"),
            "username": state.get("username"),
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        send_message(chat_id, MSG_BROADCAST_SENT.format(sent=sent, total=total))
    else:
        new_state = {
            "state": "REGISTERED",
            "store": state.get("store"),
            "username": state.get("username"),
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        send_message(chat_id, MSG_BROADCAST_CANCELLED)


# ── Callback query handler ────────────────────────────────────────────────────

def _handle_callback(cb: dict) -> None:
    """Handle an inline keyboard button press."""
    cb_id = cb["id"]
    telegram_id = cb["from"]["id"]
    chat_id = cb["message"]["chat"]["id"]
    data = cb.get("data", "")

    # Acknowledge the callback to dismiss the loading spinner
    _tg("answerCallbackQuery", callback_query_id=cb_id)

    with _bot_state_lock:
        state = bot_state.get(telegram_id)
    if state is None:
        state = load_session(telegram_id) or {}
        if state:
            with _bot_state_lock:
                bot_state[telegram_id] = state
    current_state = state.get("state")

    # Route by callback data prefix
    prefix, _, value = data.partition(":")

    if prefix == "store" and current_state == "AWAITING_STORE":
        chosen = _STORE_CHOICE.get(value)
        if chosen:
            state["store"] = chosen
            state["state"] = "REGISTERED"
            _set_state(telegram_id, state)
            saved_msg = state.pop("pending_photo_msg", None)
            if saved_msg:
                _handle_photo(telegram_id, chat_id, "", saved_msg, state)
            else:
                send_message(chat_id, MSG_STORE_CONFIRM.format(store=chosen))

    elif prefix == "date" and current_state == "AWAITING_DATE":
        if value == "ok":
            _handle_date(telegram_id, chat_id, "OK", state)
        else:
            send_message(chat_id, "Escribe la fecha (MM/DD/AAAA):")

    elif prefix == "reg" and current_state == "AWAITING_REGISTER":
        if value == "ok":
            _handle_register(telegram_id, chat_id, "OK", state)
        else:
            send_message(chat_id, "Escribe el n\u00famero de caja:")

    elif prefix == "save" and current_state == "AWAITING_CONFIRMATION":
        _handle_confirmation(telegram_id, chat_id, "YES" if value == "yes" else "NO", state)

    elif prefix == "payouts" and current_state == "AWAITING_PAYOUTS":
        _handle_payouts(telegram_id, chat_id, value, state)

    elif prefix == "actual_cash" and current_state == "AWAITING_ACTUAL_CASH":
        _handle_actual_cash(telegram_id, chat_id, value, state)

    elif prefix == "broadcast" and current_state == "BROADCAST_CONFIRM":
        _handle_broadcast_confirm(telegram_id, chat_id, value, state)


# ── Main dispatcher ────────────────────────────────────────────────────────────

def handle_update(update: dict) -> None:
    """
    Main entry point: dispatch an incoming Telegram update to the correct handler.
    Called from the Flask webhook route.
    """
    # Handle callback_query (inline button presses)
    cb = update.get("callback_query")
    if cb:
        _handle_callback(cb)
        return

    msg = update.get("message")
    if not msg:
        return  # ignore non-message updates (e.g., edited_message)

    telegram_id = msg["from"]["id"]
    tg_username = msg["from"].get("username", "")
    chat_id = msg["chat"]["id"]

    # Load state: prefer in-memory (under lock), fall back to DB on cache miss.
    with _bot_state_lock:
        state = bot_state.get(telegram_id)
    if state is None:
        state = load_session(telegram_id) or {}
        if state:
            with _bot_state_lock:
                bot_state[telegram_id] = state  # populate cache; no re-persist
    current_state = state.get("state")

    # ── photo received ────────────────────────────────────────────────────────
    if "photo" in msg:
        if not current_state or current_state not in ("REGISTERED", "AI_CHAT"):
            # Not registered yet — nudge them to register first
            if not is_registered(telegram_id):
                new_state = {"state": "AWAITING_USERNAME", "retry_count": 0}
                _set_state(telegram_id, new_state)
                send_message(chat_id, MSG_REGISTER_START)
                return
            else:
                # Reload state from DB on bot restart
                user_row = get_bot_user(telegram_id)
                new_state = {
                    "state": "REGISTERED",
                    "store": user_row["store"],
                    "username": user_row["username"],
                    "retry_count": 0,
                }
                _set_state(telegram_id, new_state)
                state = new_state
                current_state = "REGISTERED"

        _handle_photo(telegram_id, chat_id, tg_username, msg, state)
        return

    # ── text received ─────────────────────────────────────────────────────────
    text = (msg.get("text") or "").strip()

    # Slash commands — handled regardless of current state
    if text.startswith("/"):
        _handle_slash(telegram_id, chat_id, text, state)
        return

    # ── "Preguntar AI" button press ──────────────────────────────────────────
    if text == BTN_AI and current_state == "REGISTERED":
        state["state"] = "AI_CHAT"
        _set_state(telegram_id, state)
        send_message(chat_id, MSG_AI_WELCOME, reply_markup=_kb_ai_chat())
        return

    # ── "Cancelar" button press from AI_CHAT ─────────────────────────────────
    if text == BTN_CANCEL and current_state == "AI_CHAT":
        _ai_history.pop(telegram_id, None)
        state["state"] = "REGISTERED"
        _set_state(telegram_id, state)
        send_message(chat_id, MSG_AI_EXIT, reply_markup=_kb_registered())
        return

    # ── AI_CHAT state — route text to AI ─────────────────────────────────────
    if current_state == "AI_CHAT":
        _handle_ai_message(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_DATE":
        _handle_date(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_REGISTER":
        _handle_register(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_PAYOUTS":
        _handle_payouts(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_ACTUAL_CASH":
        _handle_actual_cash(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_CONFIRMATION":
        _handle_confirmation(telegram_id, chat_id, text, state)
        return

    if current_state == "BROADCAST_CONFIRM":
        _handle_broadcast_confirm(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_STORE":
        chosen = _STORE_CHOICE.get(text)
        if not chosen:
            send_message(chat_id, MSG_INVALID_STORE)
            return
        state["store"] = chosen
        state["state"] = "REGISTERED"
        _set_state(telegram_id, state)
        # Now process the saved photo
        saved_msg = state.pop("pending_photo_msg", None)
        if saved_msg:
            _handle_photo(telegram_id, chat_id, tg_username, saved_msg, state)
        else:
            send_message(chat_id, MSG_STORE_CONFIRM.format(store=chosen))
        return

    if current_state == "AWAITING_PASSWORD":
        _handle_password(telegram_id, chat_id, tg_username, text, state)
        return

    if current_state == "AWAITING_USERNAME":
        state["username"] = text
        state["state"] = "AWAITING_PASSWORD"
        _set_state(telegram_id, state)
        send_message(chat_id, MSG_ENTER_PASSWORD)
        return

    # ── default: start registration or show welcome ───────────────────────────
    if is_registered(telegram_id):
        user_row = get_bot_user(telegram_id)
        new_state = {
            "state": "REGISTERED",
            "store": user_row["store"],
            "username": user_row["username"],
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        send_message(chat_id, MSG_WELCOME_BACK.format(store=user_row["store"]),
                     reply_markup=_kb_registered())
    else:
        new_state = {"state": "AWAITING_USERNAME", "retry_count": 0}
        _set_state(telegram_id, new_state)
        send_message(chat_id, MSG_REGISTER_START)


# ── Slash command handler ──────────────────────────────────────────────────────

def _handle_slash(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle /help, /status, /cancel commands."""
    cmd = text.split()[0].lower().split("@")[0]  # strip bot name suffix if present

    if cmd == "/help":
        send_message(chat_id, MSG_HELP)

    elif cmd == "/status":
        current = state.get("state")
        if not current or current == "AWAITING_USERNAME":
            send_message(chat_id, MSG_STATUS_UNREGISTERED)
        elif current == "REGISTERED":
            send_message(chat_id, MSG_STATUS_REGISTERED.format(
                store=state.get("store", "?"),
                username=state.get("username", "?"),
            ))
        else:
            send_message(chat_id, MSG_STATUS_MIDFLOW.format(
                state=current,
                username=state.get("username", "?"),
            ))

    elif cmd == "/cancel":
        current = state.get("state")
        if not current or current in ("AWAITING_USERNAME", "AWAITING_PASSWORD"):
            send_message(chat_id, MSG_CANCEL_NOTHING)
        elif current == "AI_CHAT":
            _ai_history.pop(telegram_id, None)
            new_state = {
                "state": "REGISTERED",
                "store": state.get("store"),
                "username": state.get("username"),
                "retry_count": 0,
            }
            _set_state(telegram_id, new_state)
            send_message(chat_id, MSG_AI_EXIT, reply_markup=_kb_registered())
        else:
            # Reset to REGISTERED if we have a username/store, else fresh start
            if state.get("username") and state.get("store") and current != "AWAITING_USERNAME":
                new_state = {
                    "state": "REGISTERED",
                    "store": state.get("store"),
                    "username": state.get("username"),
                    "retry_count": 0,
                }
            else:
                new_state = {"state": "AWAITING_USERNAME", "retry_count": 0}
            _set_state(telegram_id, new_state)
            send_message(chat_id, MSG_CANCEL_OK)

    elif cmd == "/last":
        store = state.get("store")
        if not store or store == "All":
            send_message(chat_id, "Usa /last desde una tienda específica.")
            return
        try:
            db = extensions.get_db()
            if db is None:
                send_message(chat_id, "❌ Base de datos no disponible.")
                return
            result = db.table("audits").select(
                "date, reg, gross, variance, staff"
            ).eq("store", store).order("date", desc=True).limit(1).execute()
            if not result.data:
                send_message(chat_id, f"No hay reportes recientes para {store}.")
                return
            e = result.data[0]
            send_message(chat_id, (
                f"📋 Último reporte — {store}\n"
                f"Fecha: {e.get('date', '?')}\n"
                f"Caja: {e.get('reg', '?')}\n"
                f"Bruto: ${e.get('gross', 0):,.2f}\n"
                f"Varianza: ${e.get('variance', 0):,.2f}\n"
                f"Enviado por: {e.get('staff', '?')}"
            ))
        except Exception as ex:
            logger.error(f"/last failed: {ex}")
            send_message(chat_id, "❌ Error consultando el último reporte.")

    elif cmd == "/broadcast":
        user_row = get_bot_user(telegram_id)
        role = user_row.get("role", "staff") if user_row else "staff"
        if role not in ("admin", "super_admin"):
            send_message(chat_id, MSG_BROADCAST_NO_PERMISSION)
            return
        parts = text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            send_message(chat_id, "Uso: /broadcast <mensaje>")
            return
        broadcast_msg = parts[1].strip()
        try:
            db = extensions.get_db()
            users_resp = db.table("bot_users").select("telegram_id").execute()
            count = len(users_resp.data) if users_resp.data else 0
        except Exception:
            count = "?"
        state["state"] = "BROADCAST_CONFIRM"
        state["pending_broadcast"] = broadcast_msg
        _set_state(telegram_id, state)
        send_message(chat_id,
            MSG_BROADCAST_CONFIRM.format(count=count, message=broadcast_msg),
            reply_markup=INLINE_BROADCAST_CONFIRM,
        )

    else:
        # Unknown command — show help
        send_message(chat_id, MSG_HELP)


# ── State-specific handlers ────────────────────────────────────────────────────

def _handle_password(telegram_id, chat_id, tg_username, password, state):
    username = state.get("username", "")
    user_row = verify_web_credentials(username, password)
    if user_row is None:
        # Failed — reset to AWAITING_USERNAME (don't reveal which field was wrong)
        state["state"] = "AWAITING_USERNAME"
        state.pop("username", None)
        _set_state(telegram_id, state)
        send_message(chat_id, MSG_BAD_CREDENTIALS)
        return

    # Success — register
    save_bot_user(telegram_id, user_row["username"], tg_username, user_row["store"])
    new_state = {
        "state": "REGISTERED",
        "store": user_row["store"],
        "username": user_row["username"],
        "retry_count": 0,
    }
    _set_state(telegram_id, new_state)
    send_message(chat_id, MSG_REGISTERED.format(store=user_row["store"]),
                 reply_markup=_kb_registered())


def _handle_photo(telegram_id, chat_id, tg_username, msg, state):
    # If user has "All" store access, ask which store before processing
    if state.get("store") == "All":
        state["pending_photo_msg"] = msg
        state["state"] = "AWAITING_STORE"
        _set_state(telegram_id, state)
        send_message(chat_id, STORE_MENU, reply_markup=INLINE_STORES)
        return

    send_message(chat_id, MSG_PROCESSING)

    # Pick the largest photo (last in array)
    file_id = msg["photo"][-1]["file_id"]

    try:
        image_bytes = download_photo(file_id)
    except Exception as e:
        logger.error(f"Photo download failed: {e}")
        send_message(chat_id, MSG_PHOTO_DL_ERROR)
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
        send_message(chat_id, MSG_OCR_ERROR)
        return

    if has_null_fields(ocr_data):
        null_names = ", ".join(null_field_names(ocr_data))
        if retry_count >= 1:
            state["retry_count"] = 0
            _set_state(telegram_id, state)
            send_message(chat_id, MSG_NULL_FINAL.format(fields=null_names))
            return
        state["retry_count"] = retry_count + 1
        _set_state(telegram_id, state)
        send_message(chat_id, MSG_NULL_RETRY.format(fields=null_names, attempt=retry_count + 1))
        return

    # All fields readable — ask for date confirmation
    state["state"] = "AWAITING_DATE"
    state["pending_data"] = ocr_data
    state["pending_image_bytes"] = image_bytes
    state["retry_count"] = 0
    _set_state(telegram_id, state)
    ocr_date = ocr_data.get("date") or "desconocida"
    send_message(chat_id, MSG_OCR_DATE.format(date=ocr_date), reply_markup=INLINE_CONFIRM_DATE)


def _handle_ocr_failure(telegram_id, chat_id, state, retry_count):
    if retry_count >= 1:
        state["retry_count"] = 0
        _set_state(telegram_id, state)
        send_message(chat_id, MSG_OCR_FAIL_FINAL)
    else:
        state["retry_count"] = retry_count + 1
        _set_state(telegram_id, state)
        send_message(chat_id, MSG_OCR_FAIL_RETRY.format(attempt=retry_count + 1))


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
    if _ascii_upper(text) in ("OK", "YES", "SI", "SÍ", "CONFIRM"):
        # Keep OCR date as-is
        pass
    else:
        parsed = _parse_date(text)
        if parsed is None:
            send_message(chat_id, MSG_BAD_DATE)
            return
        state["pending_data"]["date"] = parsed

    ocr_reg = state["pending_data"].get("register") or "desconocido"
    state["state"] = "AWAITING_REGISTER"
    _set_state(telegram_id, state)
    send_message(chat_id, MSG_OCR_REG.format(reg=ocr_reg), reply_markup=INLINE_CONFIRM_REG)


def _handle_register(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle AWAITING_REGISTER — let user confirm or override the OCR-read register."""
    if _ascii_upper(text) not in ("OK", "YES", "SI", "SÍ", "CONFIRM"):
        text_stripped = text.strip()
        try:
            reg_num = int(text_stripped)
        except ValueError:
            send_message(chat_id, MSG_BAD_REG)
            return
        state["pending_data"]["register"] = reg_num

    state["state"] = "AWAITING_PAYOUTS"
    _set_state(telegram_id, state)
    send_message(chat_id, MSG_PAYOUTS, reply_markup=INLINE_PAYOUTS_ZERO)


def _ascii_upper(text: str) -> str:
    """Uppercase and strip accents so 'Sí' == 'SI', etc."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper()


def _handle_confirmation(telegram_id, chat_id, text, state):
    if _ascii_upper(text) in ("YES", "SI", "SÍ"):
        sid = f"{int(time.time()) % 100000}"  # short correlation ID for log tracing
        ocr_data = state["pending_data"]
        image_bytes = state.get("pending_image_bytes")
        store = state["store"]
        username = state["username"]

        logger.info(
            f"[BOT sid={sid}] Submission started: user={username!r} store={store!r} "
            f"date={ocr_data.get('date')!r} register={ocr_data.get('register')!r}"
        )

        # 1. Upload image (log error but don't block the audit save)
        storage_path = None
        if image_bytes:
            try:
                storage_path = upload_image_to_storage(
                    image_bytes, store,
                    ocr_data.get("date", "unknown"),
                    ocr_data.get("register", 0),
                )
                logger.info(f"[BOT sid={sid}] Upload OK: path={storage_path!r}")
            except Exception as e:
                logger.error(f"[BOT sid={sid}] Image upload failed: {e}")
                send_message(chat_id, MSG_PHOTO_WARN)

        # 2. Save audit entry → get entry_id (raises on DB failure — do NOT swallow)
        payouts = state.get("pending_payouts", 0.0) or 0.0
        actual_cash = state.get("pending_actual_cash", 0.0) or 0.0
        calc_variance = state.get("pending_variance")

        try:
            entry_id = save_audit_entry(
                ocr_data, store, username,
                payouts=payouts,
                actual_cash=actual_cash,
                variance=calc_variance,
            )
        except ValueError as e:
            # Duplicate entry rejected by DB unique constraint
            logger.warning(f"[BOT sid={sid}] Duplicate rejected: {e}")
            send_message(chat_id, f"⚠️ {e}")
            new_state = {
                "state": "REGISTERED",
                "store": state.get("store"),
                "username": state.get("username"),
                "retry_count": 0,
            }
            _set_state(telegram_id, new_state)
            return
        except Exception as e:
            logger.error(f"[BOT sid={sid}] save_audit_entry FAILED: {e}")
            send_message(chat_id, MSG_DB_ERROR)
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
                logger.error(f"[BOT sid={sid}] save_photo_record failed (entry still saved): {e}")

        gross = sum(ocr_data.get(f) or 0 for f in
                    ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss"])
        logger.info(
            f"[BOT sid={sid}] Submission complete: entry_id={entry_id} "
            f"photo={'yes path='+storage_path if storage_path else 'no'} gross={gross:.2f}"
        )
        new_state = {
            "state": "REGISTERED",
            "store": state.get("store"),
            "username": state.get("username"),
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        photo_note = " (foto adjunta)" if storage_path and entry_id else ""
        saved_msg = MSG_SAVED.format(
            photo_note=photo_note,
            reg=ocr_data.get("register", "?"),
            gross=gross,
        )

        # 4. Optional AI insight on variance (non-blocking, swallow errors)
        variance = ocr_data.get("variance") or 0
        if variance != 0:
            try:
                insight = ask_ai(
                    f"Varianza de ${variance:.2f} en Caja #{ocr_data.get('register', '?')}. "
                    f"¿Es normal o preocupante? Una oración.",
                    store, "system", username,
                )
                saved_msg += f"\n\n💡 {insight}"
            except Exception as e:
                logger.debug(f"[BOT sid={sid}] AI insight skipped: {e}")

        send_message(chat_id, saved_msg, reply_markup=_kb_registered())

    elif _ascii_upper(text) == "NO":
        new_state = {
            "state": "REGISTERED",
            "store": state.get("store"),
            "username": state.get("username"),
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        send_message(chat_id, MSG_CANCELLED)
    else:
        send_message(chat_id, MSG_YES_NO)


def register_webhook() -> None:
    """Register the Telegram webhook with Telegram's servers. Call on app startup."""
    token = _token()
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
        return

    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("WEBHOOK_DOMAIN")
    if not domain:
        logger.error("Neither RAILWAY_PUBLIC_DOMAIN nor WEBHOOK_DOMAIN is set — cannot register webhook")
        return
    webhook_url = f"https://{domain}/api/telegram/webhook"

    secret = Config.TELEGRAM_WEBHOOK_SECRET
    if not secret:
        logger.error("TELEGRAM_WEBHOOK_SECRET not set — cannot register webhook securely")
        return
    resp = http.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"],
            "secret_token": secret,
        },
        timeout=10,
    )
    if resp.ok and resp.json().get("ok"):
        logger.info(f"Telegram webhook registered: {webhook_url}")
    else:
        logger.error(f"Telegram webhook registration failed: {resp.text}")
