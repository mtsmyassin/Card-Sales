# Telegram Bot Overhaul — Design Document

**Date:** 2026-02-23
**Status:** Approved

## Problem

All inline keyboard buttons (store selection, date confirmation, register confirmation, save/cancel, payouts, actual cash) are broken. When a user taps any button, the loading spinner appears and never dismisses, eventually showing a Telegram error. This happens every single time — 100% failure rate.

## Root Cause

The callback handler in `telegram_bot.py` has zero error resilience:

1. **`_tg()` (line 191-198)** — The raw Telegram API wrapper has no try-except, no retry, no response validation. Any network error, timeout, or bad response crashes the calling thread silently.

2. **`_handle_callback()` (line 736-793)** — Calls `_tg("answerCallbackQuery", ...)` with no error handling. If this call fails, the loading spinner is never dismissed. The entire function has no try-except — any exception in ANY downstream handler (date, register, payouts, etc.) crashes the daemon thread silently.

3. **Silent thread death** — The webhook dispatches processing to a daemon thread. If the thread crashes, the exception is logged but the user sees only a stuck spinner.

4. **No state mismatch handling** — If a button press arrives but the user's state doesn't match any `elif` branch, the handler silently returns without any response to the user.

## Approach

**Approach 2: Resilient Overhaul** — Fix the root cause while making the bot resilient to transient failures. Add bilingual support, button timeout, error messages, and admin alerts.

## Design — 10 Sections

### Section 1: `_tg()` Rewrite — Retry + Validation

Replace the current fire-and-forget `_tg()` with a resilient wrapper:

```python
class TelegramAPIError(Exception):
    """Raised when all retries to the Telegram API are exhausted."""
    def __init__(self, method, error, attempts):
        self.method = method
        self.error = error
        self.attempts = attempts
        super().__init__(f"Telegram API {method} failed after {attempts} attempt(s): {error}")

def _tg(method: str, *, retries: int = 2, **kwargs) -> dict:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = http.post(
                f"https://api.telegram.org/bot{_token()}/{method}",
                json=kwargs,
                timeout=15,
            )
            data = resp.json()
            if not data.get("ok"):
                raise TelegramAPIError(method, data.get("description", "unknown"), attempt)
            return data.get("result", data)
        except TelegramAPIError:
            raise
        except Exception as e:
            last_error = e
            logger.warning(f"_tg({method}) attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(1)
    raise TelegramAPIError(method, str(last_error), retries)
```

**Changes from current:**
- Retries once on network/timeout errors (2 attempts total)
- Validates Telegram's `{"ok": true}` response
- Returns `result` dict (not the full envelope)
- Raises typed `TelegramAPIError` on exhausted retries
- Logs each failed attempt with method name

### Section 2: `_handle_callback()` — Guaranteed Spinner Dismissal

Rewrite with try-except-finally to guarantee `answerCallbackQuery` is always called:

```python
def _handle_callback(cb: dict) -> None:
    cb_id = cb["id"]
    telegram_id = cb["from"]["id"]
    chat_id = cb["message"]["chat"]["id"]
    data = cb.get("data", "")
    answered = False

    try:
        _tg("answerCallbackQuery", callback_query_id=cb_id)
        answered = True

        # ... existing routing logic (state load, prefix matching, etc.) ...

    except TelegramAPIError as e:
        logger.error(f"Callback TG API error: {e}", exc_info=True)
        _notify_admin_if_needed(telegram_id, "TelegramAPIError", str(e))
        send_message_safe(chat_id, msg(telegram_id, "error_connection"))
    except Exception as e:
        logger.error(f"Callback handler crash: {e}", exc_info=True)
        _notify_admin_if_needed(telegram_id, type(e).__name__, str(e))
        send_message_safe(chat_id, msg(telegram_id, "error_unknown"))
        _log_dead_letter(telegram_id, data, e)
    finally:
        if not answered:
            try:
                _tg("answerCallbackQuery", callback_query_id=cb_id, retries=1)
            except Exception:
                pass  # best effort — spinner may still be stuck, but we tried
```

### Section 3: `send_message_safe()` — Non-Throwing Sender

```python
def send_message_safe(chat_id: int, text: str, reply_markup=None) -> bool:
    try:
        send_message(chat_id, text, reply_markup)
        return True
    except Exception as e:
        logger.error(f"send_message_safe({chat_id}) failed: {e}")
        return False
```

Used in error recovery paths only. Normal flow continues using `send_message()`.

### Section 4: State Mismatch Handling

Add an `else` clause at the bottom of the callback routing:

```python
    elif prefix == "broadcast" and current_state == "BROADCAST_CONFIRM":
        _handle_broadcast_confirm(telegram_id, chat_id, value, state)

    else:
        # No matching route — state expired or old button pressed
        send_message_safe(chat_id, msg(telegram_id, "error_state_expired"))
```

### Section 5: `/bot_health` Diagnostic Endpoint

New route in `routes/telegram.py`:

```python
@bp.route('/api/telegram/health')
@require_auth(['admin', 'super_admin'])
def bot_health():
    start = time.time()
    try:
        from telegram_bot import _tg
        result = _tg("getMe")
        latency = round((time.time() - start) * 1000)
        return jsonify(ok=True, bot_username=result.get("username"), latency_ms=latency)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 503
```

### Section 6: Dead Letter Logging

```python
def _log_dead_letter(telegram_id: int, callback_data: str, error: Exception) -> None:
    logger.error(
        f"DEAD_LETTER | telegram_id={telegram_id} | data={callback_data} | "
        f"error_type={type(error).__name__} | error={error}"
    )
```

Structured log line for easy grep in production logs.

### Section 7: Bilingual Support (English + Spanish)

**Message dictionary:**

```python
MESSAGES = {
    "en": {
        "register_start": "Welcome to Carimas Bot. Enter your username to register:",
        "enter_password": "Password:",
        "bad_credentials": "Wrong username or password. Enter your username:",
        "registered": "Registered. Store: {store}.\nSend a Z Report photo to begin.",
        "welcome_back": "Registered at {store}. Send the Z Report photo.",
        "photo_send": "Send the Z Report photo.",
        "processing": "Processing... please wait.",
        "ocr_date": "What is the report date?\nOCR: {date}\nType the date (MM/DD/YYYY) or tap OK to confirm.",
        "ocr_register": "Register number?\nOCR: {register}\nType the number or tap OK to confirm.",
        "confirm_save": "Ready to save:\n{summary}\nConfirm?",
        "saved": "Saved! Entry #{sid}",
        "cancelled": "Cancelled.",
        "enter_payouts": "Enter payout amount (or tap $0):",
        "enter_actual_cash": "Enter actual cash in register (or tap Skip):",
        "error_connection": "Connection error. Please try again.",
        "error_state_expired": "Your session expired. Send the photo again.",
        "error_button_expired": "This button expired. Send the photo again.",
        "error_database": "Could not save. Please try again in a moment.",
        "error_unknown": "Something went wrong. Try again or type /start.",
        "lang_prompt": "Choose your language:",
        "lang_set": "Language set to English.",
        "store_confirm": "Store set to {store}.",
        "store_prompt": "Which store is this report for?",
        "broadcast_confirm": "Send this to all users?\n{message}",
        "broadcast_sent": "Broadcast sent to {count} users.",
        "broadcast_cancelled": "Broadcast cancelled.",
        # Inline button labels
        "btn_ok": "OK",
        "btn_edit": "Edit",
        "btn_save_yes": "Yes, Save",
        "btn_save_no": "NO, Cancel",
        "btn_no_payouts": "No payouts ($0)",
        "btn_skip": "Skip",
    },
    "es": {
        "register_start": "Bienvenido a Carimas Bot. Ingresa tu usuario para registrarte:",
        "enter_password": "Contrasena:",
        "bad_credentials": "Usuario o contrasena incorrectos. Ingresa tu usuario:",
        "registered": "Registrado. Tienda: {store}.\nEnvia una foto del Reporte Z para comenzar.",
        "welcome_back": "Registrado en {store}. Envia la foto del Reporte Z.",
        "photo_send": "Envia la foto del Reporte Z.",
        "processing": "Procesando... por favor espera.",
        "ocr_date": "Cual es la fecha del reporte Z?\nOCR: {date}\nEscribe la fecha (MM/DD/AAAA) o responde OK para confirmar.",
        "ocr_register": "Numero de caja?\nOCR: {register}\nEscribe el numero o responde OK para confirmar.",
        "confirm_save": "Listo para guardar:\n{summary}\nConfirmar?",
        "saved": "Guardado! Entrada #{sid}",
        "cancelled": "Cancelado.",
        "enter_payouts": "Ingresa el monto de pagos (o toca $0):",
        "enter_actual_cash": "Ingresa el efectivo en caja (o toca Omitir):",
        "error_connection": "Error de conexion. Intenta de nuevo.",
        "error_state_expired": "Tu sesion expiro. Envia la foto de nuevo.",
        "error_button_expired": "Este boton expiro. Envia la foto de nuevo.",
        "error_database": "No se pudo guardar. Intenta en un momento.",
        "error_unknown": "Algo salio mal. Intenta de nuevo o escribe /start.",
        "lang_prompt": "Elige tu idioma:",
        "lang_set": "Idioma configurado a Espanol.",
        "store_confirm": "Tienda: {store}.",
        "store_prompt": "Para cual tienda es este reporte?",
        "broadcast_confirm": "Enviar esto a todos?\n{message}",
        "broadcast_sent": "Mensaje enviado a {count} usuarios.",
        "broadcast_cancelled": "Mensaje cancelado.",
        # Inline button labels
        "btn_ok": "OK",
        "btn_edit": "Corregir",
        "btn_save_yes": "Si, Guardar",
        "btn_save_no": "NO, Cancelar",
        "btn_no_payouts": "Sin payouts ($0)",
        "btn_skip": "Omitir",
    }
}
```

**Helper function:**

```python
def msg(telegram_id: int, key: str, **fmt) -> str:
    with _bot_state_lock:
        state = bot_state.get(telegram_id, {})
    lang = state.get("lang", "es")
    template = MESSAGES.get(lang, MESSAGES["es"]).get(key, key)
    return template.format(**fmt) if fmt else template
```

**Language command:** `/lang` shows inline keyboard `[English] [Espanol]`. Stores choice in `state["lang"]` and persists to DB.

**Inline keyboard labels:** Dynamically built using `msg()` so button text matches user's language.

**DB migration:** `ALTER TABLE bot_sessions ADD COLUMN lang TEXT DEFAULT 'es';`

### Section 8: Button Timeout Protection

```python
BUTTON_TIMEOUT_SECONDS = 600  # 10 minutes

def _is_button_expired(cb: dict) -> bool:
    """Check if the inline button's parent message is older than the timeout."""
    msg_date = cb.get("message", {}).get("date", 0)
    return (time.time() - msg_date) > BUTTON_TIMEOUT_SECONDS
```

Called at the top of `_handle_callback()`:

```python
if _is_button_expired(cb):
    _tg("answerCallbackQuery", callback_query_id=cb_id,
        text=msg(telegram_id, "error_button_expired"), show_alert=True)
    return
```

Uses `show_alert=True` to show a popup instead of a toast, making the expiry message noticeable.

### Section 9: Better Error Messages

Covered by the bilingual `MESSAGES` dict in Section 7. Five error categories:

| Key | When Used |
|-----|-----------|
| `error_connection` | `TelegramAPIError` or `ConnectionError` in callback handler |
| `error_state_expired` | State mismatch (no matching prefix + state) |
| `error_button_expired` | Button older than 10 minutes |
| `error_database` | Supabase write failure in save handler |
| `error_unknown` | Any other unhandled exception |

### Section 10: Admin Notification on Errors

```python
_ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0"))
_admin_last_notified: float = 0.0
_ADMIN_NOTIFY_COOLDOWN = 300  # 5 minutes

def _notify_admin_if_needed(telegram_id: int, error_type: str, error_msg: str) -> None:
    global _admin_last_notified
    if not _ADMIN_CHAT_ID:
        return
    now = time.time()
    if now - _admin_last_notified < _ADMIN_NOTIFY_COOLDOWN:
        return
    _admin_last_notified = now
    text = (
        f"Bot error alert\n"
        f"User: {telegram_id}\n"
        f"Error: {error_type}\n"
        f"Detail: {error_msg[:200]}"
    )
    send_message_safe(_ADMIN_CHAT_ID, text)
```

Requires new env var: `TELEGRAM_ADMIN_CHAT_ID`

## Files Changed

| File | Changes |
|------|---------|
| `telegram_bot.py` | Rewrite `_tg()` with retry + validation; add `TelegramAPIError`; add `send_message_safe()`; rewrite `_handle_callback()` with try-except-finally; add state mismatch `else` clause; add `MESSAGES` bilingual dict; add `msg()` helper; add `/lang` command; rebuild inline keyboards dynamically; add `_is_button_expired()`; add `_notify_admin_if_needed()`; add `_log_dead_letter()` |
| `routes/telegram.py` | Add `/api/telegram/health` endpoint |
| `tests/test_telegram_bot.py` | Add tests: retry logic, callback error handling, state mismatch, button timeout, bilingual messages, admin notification |

## DB Migration

```sql
ALTER TABLE bot_sessions ADD COLUMN lang TEXT DEFAULT 'es';
```

## New Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_ADMIN_CHAT_ID` | No | Chat ID to receive error alerts. If unset, admin alerts are disabled. |

## What Does NOT Change

- State machine flow (state transitions remain the same)
- Webhook registration logic
- Session persistence pattern (in-memory + Supabase)
- OCR and photo handling
- AI assistant integration
- Auth/registration flow
