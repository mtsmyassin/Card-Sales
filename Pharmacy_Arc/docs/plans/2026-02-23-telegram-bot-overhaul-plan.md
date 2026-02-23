# Telegram Bot Overhaul Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix broken inline keyboard buttons and make the Telegram bot resilient, bilingual (EN/ES), with button timeouts, better error messages, and admin error alerts.

**Architecture:** Keep the existing raw Telegram Bot API approach (no library migration). Harden `_tg()` with retry + validation, wrap `_handle_callback()` with try-except-finally for guaranteed spinner dismissal, replace hardcoded Spanish strings with a bilingual `MESSAGES` dict keyed by `msg(telegram_id, key)`, and add button expiry + admin notification.

**Tech Stack:** Python 3.11, Flask, requests, Supabase, Telegram Bot API (raw HTTP)

**Design doc:** `docs/plans/2026-02-23-telegram-bot-overhaul-design.md`

---

### Task 1: Add `TelegramAPIError` and Rewrite `_tg()` with Retry + Validation

**Files:**
- Modify: `telegram_bot.py:191-198` (replace `_tg()`)
- Test: `tests/test_telegram_bot.py`

**Step 1: Write failing tests for `_tg()` retry and validation**

Add to `tests/test_telegram_bot.py`:

```python
# ── _tg() resilience tests ──────────────────────────────────────────────────

def test_tg_retries_on_network_error():
    """_tg retries once on network error before raising TelegramAPIError."""
    from telegram_bot import _tg, TelegramAPIError
    import requests

    with patch("telegram_bot.http.post", side_effect=requests.ConnectionError("timeout")):
        with pytest.raises(TelegramAPIError) as exc_info:
            _tg("getMe")
        assert exc_info.value.attempts == 2


def test_tg_returns_result_on_success():
    """_tg returns the 'result' key from a successful Telegram response."""
    from telegram_bot import _tg

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"id": 123, "is_bot": True}}

    with patch("telegram_bot.http.post", return_value=mock_resp):
        result = _tg("getMe")
    assert result == {"id": 123, "is_bot": True}


def test_tg_raises_on_telegram_error_response():
    """_tg raises TelegramAPIError when Telegram returns ok=false."""
    from telegram_bot import _tg, TelegramAPIError

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "description": "Bad Request: query is too old"}

    with patch("telegram_bot.http.post", return_value=mock_resp):
        with pytest.raises(TelegramAPIError) as exc_info:
            _tg("answerCallbackQuery", callback_query_id="expired")
        assert "Bad Request" in str(exc_info.value)


def test_tg_succeeds_on_second_attempt():
    """_tg retries and succeeds on the second attempt after a network error."""
    from telegram_bot import _tg
    import requests

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 1}}

    with patch("telegram_bot.http.post", side_effect=[
        requests.ConnectionError("first attempt"),
        mock_resp,
    ]):
        result = _tg("sendMessage", chat_id=123, text="hi")
    assert result == {"message_id": 1}
```

**Step 2: Run tests to verify they fail**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_tg_retries_on_network_error tests/test_telegram_bot.py::test_tg_returns_result_on_success tests/test_telegram_bot.py::test_tg_raises_on_telegram_error_response tests/test_telegram_bot.py::test_tg_succeeds_on_second_attempt -v --tb=short`
Expected: FAIL — `TelegramAPIError` doesn't exist yet, `_tg()` doesn't retry.

**Step 3: Implement `TelegramAPIError` and rewrite `_tg()`**

In `telegram_bot.py`, add after the imports (around line 18):

```python
class TelegramAPIError(Exception):
    """Raised when all retries to the Telegram Bot API are exhausted."""
    def __init__(self, method: str, error: str, attempts: int):
        self.method = method
        self.error = error
        self.attempts = attempts
        super().__init__(f"Telegram API {method} failed after {attempts} attempt(s): {error}")
```

Replace lines 191-198 (`_tg()`) with:

```python
def _tg(method: str, *, retries: int = 2, **kwargs) -> dict:
    """Call a Telegram Bot API method with retry and validation."""
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
                raise TelegramAPIError(method, data.get("description", "unknown error"), attempt)
            return data.get("result", data)
        except TelegramAPIError:
            raise  # don't retry Telegram-level errors (bad params, expired queries)
        except Exception as e:
            last_error = e
            logger.warning(f"_tg({method}) attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(1)
    raise TelegramAPIError(method, str(last_error), retries)
```

**Step 4: Fix callers that depend on old `_tg()` return shape**

The old `_tg()` returned the full `{"ok": true, "result": {...}}` envelope. The new one returns just `result`. Fix callers:

- `download_photo()` at line ~210: change `info["result"]["file_path"]` to `info["file_path"]` (since `_tg` now returns `result` directly).
- Scan for any other `["result"]` access after `_tg()` calls — update them.

**Step 5: Run tests to verify they pass**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_tg_retries_on_network_error tests/test_telegram_bot.py::test_tg_returns_result_on_success tests/test_telegram_bot.py::test_tg_raises_on_telegram_error_response tests/test_telegram_bot.py::test_tg_succeeds_on_second_attempt -v --tb=short`
Expected: 4 PASS

**Step 6: Run full test suite to check for regressions**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest --tb=short -q`
Expected: Existing tests pass (10 pre-existing failures may remain — that's expected).

**Step 7: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): rewrite _tg() with retry, validation, and TelegramAPIError"
```

---

### Task 2: Add `send_message_safe()` and `_log_dead_letter()`

**Files:**
- Modify: `telegram_bot.py:201-205` (add new functions after `send_message`)
- Test: `tests/test_telegram_bot.py`

**Step 1: Write failing tests**

```python
def test_send_message_safe_returns_true_on_success():
    from telegram_bot import send_message_safe

    with patch("telegram_bot.send_message"):
        assert send_message_safe(123, "hello") is True


def test_send_message_safe_returns_false_on_error():
    from telegram_bot import send_message_safe

    with patch("telegram_bot.send_message", side_effect=Exception("network")):
        assert send_message_safe(123, "hello") is False
```

**Step 2: Run tests to verify they fail**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_send_message_safe_returns_true_on_success tests/test_telegram_bot.py::test_send_message_safe_returns_false_on_error -v --tb=short`
Expected: FAIL — `send_message_safe` doesn't exist.

**Step 3: Implement `send_message_safe()` and `_log_dead_letter()`**

Add after `send_message()` in `telegram_bot.py`:

```python
def send_message_safe(chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Send a message, swallowing any exception. Returns True on success."""
    try:
        send_message(chat_id, text, reply_markup)
        return True
    except Exception as e:
        logger.error(f"send_message_safe({chat_id}) failed: {e}")
        return False


def _log_dead_letter(telegram_id: int, callback_data: str, error: Exception) -> None:
    """Log a structured dead-letter entry for failed callback processing."""
    logger.error(
        f"DEAD_LETTER | telegram_id={telegram_id} | data={callback_data} | "
        f"error_type={type(error).__name__} | error={error}"
    )
```

**Step 4: Run tests to verify they pass**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_send_message_safe_returns_true_on_success tests/test_telegram_bot.py::test_send_message_safe_returns_false_on_error -v --tb=short`
Expected: 2 PASS

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): add send_message_safe() and dead letter logging"
```

---

### Task 3: Bilingual Message System

**Files:**
- Modify: `telegram_bot.py:46-168` (replace `MSG_*` constants with `MESSAGES` dict)
- Modify: `telegram_bot.py:218-244` (add `lang` to `persist_session` and `load_session`)
- Test: `tests/test_telegram_bot.py`

**Step 1: Write failing tests**

```python
def test_msg_returns_spanish_by_default():
    from telegram_bot import msg, bot_state
    bot_state.clear()
    bot_state[999] = {"lang": "es"}
    result = msg(999, "processing")
    assert "espera" in result.lower()


def test_msg_returns_english_when_set():
    from telegram_bot import msg, bot_state
    bot_state.clear()
    bot_state[999] = {"lang": "en"}
    result = msg(999, "processing")
    assert "wait" in result.lower()


def test_msg_formats_placeholders():
    from telegram_bot import msg, bot_state
    bot_state.clear()
    bot_state[999] = {"lang": "en"}
    result = msg(999, "registered", store="Test Store")
    assert "Test Store" in result


def test_msg_defaults_to_spanish_for_unknown_user():
    from telegram_bot import msg, bot_state
    bot_state.clear()
    result = msg(0, "processing")
    assert "espera" in result.lower()
```

**Step 2: Run tests to verify they fail**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_msg_returns_spanish_by_default tests/test_telegram_bot.py::test_msg_returns_english_when_set tests/test_telegram_bot.py::test_msg_formats_placeholders tests/test_telegram_bot.py::test_msg_defaults_to_spanish_for_unknown_user -v --tb=short`
Expected: FAIL — `msg` function doesn't exist.

**Step 3: Implement `MESSAGES` dict and `msg()` helper**

Replace lines 46-168 (the `MSG_*` constants) with:

```python
# ── Bilingual messages (EN / ES) ─────────────────────────────────────────────

MESSAGES = {
    "en": {
        "register_start": "Welcome to Carimas Bot. Enter your username to register:",
        "enter_password": "Password:",
        "bad_credentials": "Wrong username or password. Enter your username:",
        "registered": "Registered. Store: {store}.\nSend a Z Report photo to begin.",
        "welcome_back": "Registered at {store}. Send the Z Report photo.",
        "photo_send": "Send the Z Report photo.",
        "processing": "Processing... please wait.",
        "ocr_date": (
            "What is the report date?\n"
            "OCR: {date}\n"
            "Type the date (MM/DD/YYYY) or tap OK to confirm."
        ),
        "ocr_reg": (
            "Register number?\n"
            "OCR: {reg}\n"
            "Type the number or tap OK to confirm."
        ),
        "bad_date": "Could not read the date. Use MM/DD/YYYY (e.g. 02/20/2026) or tap OK.",
        "bad_reg": "Enter a register number (e.g. 1) or tap OK to keep the OCR value.",
        "yes_no": "Tap YES to save or NO to cancel.",
        "saved": "Saved{photo_note}. Register #{reg} - ${gross:.2f} gross.\nIf you don't see it in the app, select the 'All' filter.",
        "cancelled": "Cancelled. Send another photo when ready.",
        "invalid_store": "Tap a store button to select.",
        "store_confirm": "Store: {store}. Send the Z Report photo.",
        "ocr_fail_retry": (
            "Could not read the report.\n"
            "Tips: hold the camera directly above the receipt, "
            "with good lighting and no shadows. (Attempt {attempt} of 2)"
        ),
        "ocr_fail_final": (
            "Could not process the photo after 2 attempts.\n"
            "Tips:\n"
            "  - Flat surface, camera directly above\n"
            "  - Good lighting, no direct flash\n"
            "  - Entire receipt visible in the photo\n"
            "Enter this report manually in the web app."
        ),
        "null_retry": (
            "Could not read: {fields}.\n"
            "Make sure those sections of the receipt are visible.\n"
            "Take the photo closer, with good lighting and no shadows. (Attempt {attempt} of 2)"
        ),
        "null_final": (
            "Could not read: {fields}.\n"
            "Failed after 2 attempts. Tips:\n"
            "  - Place the receipt on a flat surface\n"
            "  - Hold the camera directly above\n"
            "  - Use good lighting, no direct flash\n"
            "Enter this report manually in the web app."
        ),
        "photo_warn": "Could not upload the photo. The report will be saved without it.",
        "db_error": "Error saving the report. Please enter it manually in the web app.",
        "photo_dl_error": "Could not download the photo. Try again.",
        "ocr_error": "Error processing the image. Try again.",
        "session_reset": "Your session was restored after a system restart.\nPlease send the Z Report photo again.",
        "help": (
            "Carimas Bot - Help\n\n"
            "Available commands:\n"
            "  /help      - Show this help\n"
            "  /status    - Show your current status\n"
            "  /cancel    - Cancel current operation\n"
            "  /last      - Show last submitted report\n"
            "  /lang      - Change language\n"
            "  /broadcast - Send message to all (admin only)\n\n"
            "How to submit a Z Report:\n"
            "  1. Register with your system username and password\n"
            "  2. Send a clear, well-lit photo of the Z Report\n"
            "  3. Confirm the date and register number\n"
            "  4. Tap YES to save the report\n\n"
            "AI Assistant:\n"
            "  Tap 'Ask AI' to query sales data and variances."
        ),
        "status_registered": "Status: Registered\nStore: {store}\nUser: {username}\nReady to receive Z Report photos.",
        "status_unregistered": "Status: Not registered\nSend any message to start registration.",
        "status_midflow": "Status: In progress ({state})\nUser: {username}\nUse /cancel to restart.",
        "cancel_ok": "Operation cancelled. Send a Z Report photo when ready.",
        "cancel_nothing": "No active operation at the moment.",
        "ai_welcome": (
            "AI Assistant mode activated.\n\n"
            "You can ask me about sales, variances, or any data from your store.\n"
            "Examples:\n"
            "  - What was yesterday's gross?\n"
            "  - Which register has the most variance?\n"
            "  - Summarize this week's sales\n\n"
            "Send /cancel to exit AI mode.\n"
            "Sending a photo still works normally."
        ),
        "ai_exit": "AI mode deactivated. Send a Z Report photo when ready.",
        "payouts": "How much in payouts/disbursements?\nEnter the amount (e.g. 50.00) or tap the button if none.",
        "actual_cash": "How much cash is in the register?\nEnter the counted amount, or tap Skip to use OCR variance.",
        "bad_amount": "Enter a valid amount (e.g. 50.00 or 0).",
        "broadcast_confirm": "Send this to {count} users?\n\n{message}\n\nConfirm?",
        "broadcast_sent": "Message sent to {sent} of {total} users.",
        "broadcast_cancelled": "Broadcast cancelled.",
        "broadcast_no_permission": "Only administrators can use /broadcast.",
        "error_connection": "Connection error. Please try again.",
        "error_state_expired": "Your session expired. Send the photo again.",
        "error_button_expired": "This button expired. Send the photo again.",
        "error_database": "Could not save. Please try again in a moment.",
        "error_unknown": "Something went wrong. Try again or type /start.",
        "lang_prompt": "Choose your language:",
        "lang_set": "Language set to English.",
        "store_prompt": "Which store is this report for?",
        # Inline button labels
        "btn_ok": "OK",
        "btn_edit": "Edit",
        "btn_save_yes": "Yes, Save",
        "btn_save_no": "NO, Cancel",
        "btn_no_payouts": "No payouts ($0)",
        "btn_skip": "Skip",
        "btn_send": "Send",
        "btn_cancel": "Cancel",
        "btn_ask_ai": "Ask AI",
    },
    "es": {
        "register_start": "Bienvenido a Carimas Bot. Ingresa tu usuario para registrarte:",
        "enter_password": "Contrasena:",
        "bad_credentials": "Usuario o contrasena incorrectos. Ingresa tu usuario:",
        "registered": "Registrado. Tienda: {store}.\nEnvia una foto del Reporte Z para comenzar.",
        "welcome_back": "Registrado en {store}. Envia la foto del Reporte Z.",
        "photo_send": "Envia la foto del Reporte Z.",
        "processing": "Procesando... por favor espera.",
        "ocr_date": (
            "Cual es la fecha del reporte Z?\n"
            "OCR: {date}\n"
            "Escribe la fecha (MM/DD/AAAA) o responde OK para confirmar."
        ),
        "ocr_reg": (
            "Numero de caja registradora?\n"
            "OCR: {reg}\n"
            "Escribe el numero o responde OK para confirmar."
        ),
        "bad_date": "No se pudo leer la fecha. Usa MM/DD/AAAA (ej. 02/20/2026) o responde OK.",
        "bad_reg": "Ingresa un numero de caja (ej. 1) o responde OK para mantener el valor del OCR.",
        "yes_no": "Responde SI para guardar o NO para cancelar.",
        "saved": "Guardado{photo_note}. Caja #{reg} - ${gross:.2f} bruto.\nSi no lo ves en la app, selecciona el filtro 'Todos'.",
        "cancelled": "Cancelado. Envia otra foto cuando estes listo.",
        "invalid_store": "Toca un boton de tienda para seleccionar.",
        "store_confirm": "Tienda: {store}. Envia la foto del Reporte Z.",
        "ocr_fail_retry": (
            "No se pudo leer el reporte.\n"
            "Consejos: sosten la camara directamente encima del recibo, "
            "con buena iluminacion y sin sombras. (Intento {attempt} de 2)"
        ),
        "ocr_fail_final": (
            "No se pudo procesar la foto despues de 2 intentos.\n"
            "Consejos:\n"
            "  - Superficie plana, camara directamente encima\n"
            "  - Buena iluminacion, sin flash directo\n"
            "  - Todo el recibo visible en la foto\n"
            "Ingresa este reporte manualmente en la app web."
        ),
        "null_retry": (
            "No se pudo leer: {fields}.\n"
            "Asegurate de que esas secciones del recibo esten visibles.\n"
            "Toma la foto mas cerca, con buena iluminacion y sin sombras. (Intento {attempt} de 2)"
        ),
        "null_final": (
            "No se pudo leer: {fields}.\n"
            "Fallo tras 2 intentos. Consejos:\n"
            "  - Coloca el recibo en una superficie plana\n"
            "  - Sosten la camara directamente encima\n"
            "  - Usa buena iluminacion, sin flash directo\n"
            "Ingresa este reporte manualmente en la app web."
        ),
        "photo_warn": "No se pudo subir la foto. El reporte se guardara sin ella.",
        "db_error": "Error guardando el reporte. Por favor ingresalo manualmente en la app web.",
        "photo_dl_error": "No se pudo descargar la foto. Intentalo de nuevo.",
        "ocr_error": "Error procesando la imagen. Intentalo de nuevo.",
        "session_reset": "Tu sesion fue restaurada despues de un reinicio del sistema.\nPor favor envia la foto del Reporte Z de nuevo.",
        "help": (
            "Carimas Bot - Ayuda\n\n"
            "Comandos disponibles:\n"
            "  /help      - Ver esta ayuda\n"
            "  /status    - Ver tu estado actual\n"
            "  /cancel    - Cancelar la operacion en curso\n"
            "  /last      - Ver el ultimo reporte enviado\n"
            "  /lang      - Cambiar idioma\n"
            "  /broadcast - Enviar mensaje a todos (solo admin)\n\n"
            "Como enviar un Reporte Z:\n"
            "  1. Registrate con tu usuario y contrasena del sistema\n"
            "  2. Envia una foto clara y bien iluminada del Reporte Z\n"
            "  3. Confirma la fecha y numero de caja\n"
            "  4. Responde SI para guardar el reporte\n\n"
            "Asistente AI:\n"
            "  Toca 'Preguntar AI' para consultar datos de ventas y varianzas."
        ),
        "status_registered": "Estado: Registrado\nTienda: {store}\nUsuario: {username}\nListo para recibir fotos de Reporte Z.",
        "status_unregistered": "Estado: No registrado\nEnvia cualquier mensaje para comenzar el registro.",
        "status_midflow": "Estado: En proceso ({state})\nUsuario: {username}\nUsa /cancel para reiniciar.",
        "cancel_ok": "Operacion cancelada. Envia una foto del Reporte Z cuando estes listo.",
        "cancel_nothing": "No hay ninguna operacion activa en este momento.",
        "ai_welcome": (
            "Modo Asistente AI activado.\n\n"
            "Puedes preguntarme sobre ventas, varianzas, o cualquier dato de tu tienda.\n"
            "Ejemplos:\n"
            "  - Cuanto fue el bruto de ayer?\n"
            "  - Cual caja tiene mas varianza?\n"
            "  - Resume las ventas de esta semana\n\n"
            "Envia /cancel para salir del modo AI.\n"
            "Enviar una foto sigue funcionando normalmente."
        ),
        "ai_exit": "Modo AI desactivado. Envia una foto del Reporte Z cuando estes listo.",
        "payouts": "Cuanto fue el total de payouts/desembolsos?\nEscribe el monto (ej. 50.00) o toca el boton si no hubo.",
        "actual_cash": "Cuanto efectivo hay en la caja?\nEscribe el monto contado, o toca Omitir para usar la varianza del OCR.",
        "bad_amount": "Ingresa un monto valido (ej. 50.00 o 0).",
        "broadcast_confirm": "Mensaje a enviar a {count} usuarios:\n\n{message}\n\nConfirmar envio?",
        "broadcast_sent": "Mensaje enviado a {sent} de {total} usuarios.",
        "broadcast_cancelled": "Envio cancelado.",
        "broadcast_no_permission": "Solo administradores pueden usar /broadcast.",
        "error_connection": "Error de conexion. Intenta de nuevo.",
        "error_state_expired": "Tu sesion expiro. Envia la foto de nuevo.",
        "error_button_expired": "Este boton expiro. Envia la foto de nuevo.",
        "error_database": "No se pudo guardar. Intenta en un momento.",
        "error_unknown": "Algo salio mal. Intenta de nuevo o escribe /start.",
        "lang_prompt": "Elige tu idioma:",
        "lang_set": "Idioma configurado a Espanol.",
        "store_prompt": "Para cual tienda es este reporte?",
        # Inline button labels
        "btn_ok": "OK",
        "btn_edit": "Corregir",
        "btn_save_yes": "Si, Guardar",
        "btn_save_no": "NO, Cancelar",
        "btn_no_payouts": "Sin payouts ($0)",
        "btn_skip": "Omitir",
        "btn_send": "Enviar",
        "btn_cancel": "Cancelar",
        "btn_ask_ai": "Preguntar AI",
    },
}


def msg(telegram_id: int, key: str, **fmt) -> str:
    """Return a message string in the user's preferred language."""
    with _bot_state_lock:
        state = bot_state.get(telegram_id, {})
    lang = state.get("lang", "es")
    template = MESSAGES.get(lang, MESSAGES["es"]).get(key, key)
    return template.format(**fmt) if fmt else template
```

**Step 4: Run tests to verify they pass**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_msg_returns_spanish_by_default tests/test_telegram_bot.py::test_msg_returns_english_when_set tests/test_telegram_bot.py::test_msg_formats_placeholders tests/test_telegram_bot.py::test_msg_defaults_to_spanish_for_unknown_user -v --tb=short`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): add bilingual message system (EN/ES) with msg() helper"
```

---

### Task 4: Replace All MSG_* References with msg() Calls

**Files:**
- Modify: `telegram_bot.py` (every function that uses `MSG_*` constants)

**Step 1: Search-and-replace all MSG_ usages**

This is a mechanical replacement. Every `MSG_FOO` becomes `msg(telegram_id, "foo")`. The key mapping:

| Old Constant | New Key |
|---|---|
| `MSG_REGISTER_START` | `msg(telegram_id, "register_start")` |
| `MSG_ENTER_PASSWORD` | `msg(telegram_id, "enter_password")` |
| `MSG_BAD_CREDENTIALS` | `msg(telegram_id, "bad_credentials")` |
| `MSG_REGISTERED` | `msg(telegram_id, "registered", store=...)` |
| `MSG_WELCOME_BACK` | `msg(telegram_id, "welcome_back", store=...)` |
| `MSG_PHOTO_SEND` | `msg(telegram_id, "photo_send")` |
| `MSG_PROCESSING` | `msg(telegram_id, "processing")` |
| `MSG_OCR_DATE` | `msg(telegram_id, "ocr_date", date=...)` |
| `MSG_OCR_REG` | `msg(telegram_id, "ocr_reg", reg=...)` |
| `MSG_BAD_DATE` | `msg(telegram_id, "bad_date")` |
| `MSG_BAD_REG` | `msg(telegram_id, "bad_reg")` |
| `MSG_YES_NO` | `msg(telegram_id, "yes_no")` |
| `MSG_SAVED` | `msg(telegram_id, "saved", photo_note=..., reg=..., gross=...)` |
| `MSG_CANCELLED` | `msg(telegram_id, "cancelled")` |
| `MSG_INVALID_STORE` | `msg(telegram_id, "invalid_store")` |
| `MSG_STORE_CONFIRM` | `msg(telegram_id, "store_confirm", store=...)` |
| `MSG_OCR_FAIL_RETRY` | `msg(telegram_id, "ocr_fail_retry", attempt=...)` |
| `MSG_OCR_FAIL_FINAL` | `msg(telegram_id, "ocr_fail_final")` |
| `MSG_NULL_RETRY` | `msg(telegram_id, "null_retry", fields=..., attempt=...)` |
| `MSG_NULL_FINAL` | `msg(telegram_id, "null_final", fields=...)` |
| `MSG_PHOTO_WARN` | `msg(telegram_id, "photo_warn")` |
| `MSG_DB_ERROR` | `msg(telegram_id, "db_error")` |
| `MSG_PHOTO_DL_ERROR` | `msg(telegram_id, "photo_dl_error")` |
| `MSG_OCR_ERROR` | `msg(telegram_id, "ocr_error")` |
| `MSG_SESSION_RESET` | `msg(telegram_id, "session_reset")` |
| `MSG_HELP` | `msg(telegram_id, "help")` |
| `MSG_STATUS_REGISTERED` | `msg(telegram_id, "status_registered", store=..., username=...)` |
| `MSG_STATUS_UNREGISTERED` | `msg(telegram_id, "status_unregistered")` |
| `MSG_STATUS_MIDFLOW` | `msg(telegram_id, "status_midflow", state=..., username=...)` |
| `MSG_CANCEL_OK` | `msg(telegram_id, "cancel_ok")` |
| `MSG_CANCEL_NOTHING` | `msg(telegram_id, "cancel_nothing")` |
| `MSG_AI_WELCOME` | `msg(telegram_id, "ai_welcome")` |
| `MSG_AI_EXIT` | `msg(telegram_id, "ai_exit")` |
| `MSG_PAYOUTS` | `msg(telegram_id, "payouts")` |
| `MSG_ACTUAL_CASH` | `msg(telegram_id, "actual_cash")` |
| `MSG_BAD_AMOUNT` | `msg(telegram_id, "bad_amount")` |
| `MSG_BROADCAST_CONFIRM` | `msg(telegram_id, "broadcast_confirm", count=..., message=...)` |
| `MSG_BROADCAST_SENT` | `msg(telegram_id, "broadcast_sent", sent=..., total=...)` |
| `MSG_BROADCAST_CANCELLED` | `msg(telegram_id, "broadcast_cancelled")` |
| `MSG_BROADCAST_NO_PERMISSION` | `msg(telegram_id, "broadcast_no_permission")` |

**Important:** Some functions receive `chat_id` but not `telegram_id`. In `_handle_callback`, both are available. In `handle_update`, `telegram_id` comes from `msg["from"]["id"]`. Ensure each call site has access to `telegram_id`.

Also replace `STORE_MENU` with a dynamic call: use `msg(telegram_id, "store_prompt")` and build the numbered list dynamically.

**Step 2: Replace inline keyboard button text with `msg()` calls**

Convert the static `INLINE_*` keyboards to functions that accept `telegram_id`:

```python
def _build_inline_confirm_date(tid: int) -> dict:
    return _inline_kb([
        [_inline_btn(msg(tid, "btn_ok"), "date:ok"),
         _inline_btn(msg(tid, "btn_edit"), "date:edit")],
    ])

def _build_inline_confirm_reg(tid: int) -> dict:
    return _inline_kb([
        [_inline_btn(msg(tid, "btn_ok"), "reg:ok"),
         _inline_btn(msg(tid, "btn_edit"), "reg:edit")],
    ])

def _build_inline_save(tid: int) -> dict:
    return _inline_kb([
        [_inline_btn(msg(tid, "btn_save_yes"), "save:yes"),
         _inline_btn(msg(tid, "btn_save_no"), "save:no")],
    ])

def _build_inline_payouts_zero(tid: int) -> dict:
    return _inline_kb([
        [_inline_btn(msg(tid, "btn_no_payouts"), "payouts:0")],
    ])

def _build_inline_skip_cash(tid: int) -> dict:
    return _inline_kb([
        [_inline_btn(msg(tid, "btn_skip"), "actual_cash:skip")],
    ])

def _build_inline_broadcast(tid: int) -> dict:
    return _inline_kb([
        [_inline_btn(msg(tid, "btn_send"), "broadcast:yes"),
         _inline_btn(msg(tid, "btn_cancel"), "broadcast:no")],
    ])
```

`INLINE_STORES` stays static (store names don't change by language). Also replace `BTN_AI` and `BTN_CANCEL` reply keyboard buttons:

```python
def _kb_registered(tid: int) -> dict:
    return {
        "keyboard": [[msg(tid, "btn_ask_ai")]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

def _kb_ai_chat(tid: int) -> dict:
    return {
        "keyboard": [[msg(tid, "btn_cancel")]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }
```

**Step 3: Update all call sites that use old keyboards/constants**

Find every `INLINE_CONFIRM_DATE`, `INLINE_CONFIRM_REG`, `INLINE_SAVE`, `INLINE_PAYOUTS_ZERO`, `INLINE_SKIP_CASH`, `INLINE_BROADCAST_CONFIRM` reference and replace with `_build_inline_*(telegram_id)`.

Find every `_kb_registered()`, `_kb_ai_chat()` and add `telegram_id` argument.

Find every `BTN_AI` and `BTN_CANCEL` string comparison in `handle_update` and update to check both languages (or use `msg()`).

**Step 4: Run the full test suite**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest --tb=short -q`
Expected: Tests pass. Some existing tests may need updating since they assert on Spanish text — update assertions to check for `msg()` output or check both languages.

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): replace all MSG_* constants with bilingual msg() calls"
```

---

### Task 5: Rewrite `_handle_callback()` with Error Resilience + Button Timeout

**Files:**
- Modify: `telegram_bot.py:736-793` (rewrite `_handle_callback`)
- Test: `tests/test_telegram_bot.py`

**Step 1: Write failing tests**

```python
import time as time_module

def test_callback_guarantees_answer_on_crash():
    """answerCallbackQuery is called even when the handler crashes."""
    from telegram_bot import handle_update, bot_state, _tg
    bot_state.clear()
    bot_state[901] = {"state": "AWAITING_DATE", "lang": "es"}
    tg_calls = []

    def mock_tg(method, **kwargs):
        tg_calls.append(method)
        if method == "answerCallbackQuery":
            return {"ok": True}
        raise Exception("simulated crash")

    with patch("telegram_bot._tg", side_effect=mock_tg):
        with patch("telegram_bot.send_message_safe"):
            handle_update(make_callback_update(901, "date:ok"))

    assert "answerCallbackQuery" in tg_calls


def test_callback_expired_button_shows_alert():
    """Expired buttons get answered with show_alert=True and no processing."""
    from telegram_bot import handle_update, bot_state, BUTTON_TIMEOUT_SECONDS
    bot_state.clear()
    bot_state[901] = {"state": "AWAITING_DATE", "lang": "es"}
    tg_calls = []

    old_time = int(time_module.time()) - BUTTON_TIMEOUT_SECONDS - 60
    update = make_callback_update(901, "date:ok")
    update["callback_query"]["message"]["date"] = old_time

    def mock_tg(method, **kwargs):
        tg_calls.append((method, kwargs))
        return {"ok": True}

    with patch("telegram_bot._tg", side_effect=mock_tg):
        handle_update(update)

    answer_calls = [(m, kw) for m, kw in tg_calls if m == "answerCallbackQuery"]
    assert len(answer_calls) == 1
    assert answer_calls[0][1].get("show_alert") is True


def test_callback_state_mismatch_sends_expired_message():
    """When state doesn't match any route, user gets an expiry message."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[901] = {"state": "REGISTERED", "lang": "en"}  # wrong state for date:ok
    messages = []

    with patch("telegram_bot._tg", return_value={"ok": True}):
        with patch("telegram_bot.send_message_safe", side_effect=lambda cid, txt, **kw: messages.append(txt)):
            update = make_callback_update(901, "date:ok")
            update["callback_query"]["message"]["date"] = int(time_module.time())
            handle_update(update)

    assert any("expired" in m.lower() or "expir" in m.lower() for m in messages)
```

**Step 2: Run tests to verify they fail**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_callback_guarantees_answer_on_crash tests/test_telegram_bot.py::test_callback_expired_button_shows_alert tests/test_telegram_bot.py::test_callback_state_mismatch_sends_expired_message -v --tb=short`
Expected: FAIL

**Step 3: Add button timeout constant and helper**

Add near the top of `telegram_bot.py` (after `_STORE_CHOICE`):

```python
BUTTON_TIMEOUT_SECONDS = 600  # 10 minutes — buttons older than this are rejected

def _is_button_expired(cb: dict) -> bool:
    """Check if the inline button's parent message is older than the timeout."""
    msg_date = cb.get("message", {}).get("date", 0)
    if msg_date == 0:
        return False  # can't determine age, allow it
    return (time.time() - msg_date) > BUTTON_TIMEOUT_SECONDS
```

**Step 4: Rewrite `_handle_callback()`**

Replace lines 736-793 with:

```python
def _handle_callback(cb: dict) -> None:
    """Handle an inline keyboard button press with guaranteed spinner dismissal."""
    cb_id = cb["id"]
    telegram_id = cb["from"]["id"]
    chat_id = cb["message"]["chat"]["id"]
    data = cb.get("data", "")
    answered = False

    try:
        # Check button expiry FIRST
        if _is_button_expired(cb):
            _tg("answerCallbackQuery", callback_query_id=cb_id,
                text=msg(telegram_id, "error_button_expired"), show_alert=True)
            answered = True
            return

        # Acknowledge the callback to dismiss the loading spinner
        _tg("answerCallbackQuery", callback_query_id=cb_id)
        answered = True

        # Load state
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
                    send_message(chat_id, msg(telegram_id, "store_confirm", store=chosen))

        elif prefix == "date" and current_state == "AWAITING_DATE":
            if value == "ok":
                _handle_date(telegram_id, chat_id, "OK", state)
            else:
                send_message(chat_id, msg(telegram_id, "bad_date"))

        elif prefix == "reg" and current_state == "AWAITING_REGISTER":
            if value == "ok":
                _handle_register(telegram_id, chat_id, "OK", state)
            else:
                send_message(chat_id, msg(telegram_id, "bad_reg"))

        elif prefix == "save" and current_state == "AWAITING_CONFIRMATION":
            _handle_confirmation(telegram_id, chat_id, "YES" if value == "yes" else "NO", state)

        elif prefix == "payouts" and current_state == "AWAITING_PAYOUTS":
            _handle_payouts(telegram_id, chat_id, value, state)

        elif prefix == "actual_cash" and current_state == "AWAITING_ACTUAL_CASH":
            _handle_actual_cash(telegram_id, chat_id, value, state)

        elif prefix == "broadcast" and current_state == "BROADCAST_CONFIRM":
            _handle_broadcast_confirm(telegram_id, chat_id, value, state)

        elif prefix == "lang":
            # Language selection callback
            state["lang"] = value
            _set_state(telegram_id, state)
            send_message(chat_id, msg(telegram_id, "lang_set"))

        else:
            # No matching route — state expired or stale button
            send_message_safe(chat_id, msg(telegram_id, "error_state_expired"))

    except TelegramAPIError as e:
        logger.error(f"Callback TG API error: {e}", exc_info=True)
        _notify_admin_if_needed(telegram_id, "TelegramAPIError", str(e))
        send_message_safe(chat_id, msg(telegram_id, "error_connection"))
        _log_dead_letter(telegram_id, data, e)
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
                pass  # best effort
```

**Step 5: Run tests to verify they pass**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_callback_guarantees_answer_on_crash tests/test_telegram_bot.py::test_callback_expired_button_shows_alert tests/test_telegram_bot.py::test_callback_state_mismatch_sends_expired_message -v --tb=short`
Expected: 3 PASS

**Step 6: Run full test suite**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest --tb=short -q`
Expected: No new failures.

**Step 7: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): resilient callback handler with button timeout and state mismatch handling"
```

---

### Task 6: Admin Error Notification

**Files:**
- Modify: `telegram_bot.py` (add `_notify_admin_if_needed` near module-level config)
- Test: `tests/test_telegram_bot.py`

**Step 1: Write failing test**

```python
def test_admin_notification_sends_on_first_error():
    from telegram_bot import _notify_admin_if_needed, _ADMIN_CHAT_ID
    import telegram_bot

    original_admin = telegram_bot._ADMIN_CHAT_ID
    original_last = telegram_bot._admin_last_notified
    try:
        telegram_bot._ADMIN_CHAT_ID = 99999
        telegram_bot._admin_last_notified = 0.0
        messages = []

        with patch("telegram_bot.send_message_safe", side_effect=lambda cid, txt, **kw: messages.append((cid, txt))):
            _notify_admin_if_needed(123, "TestError", "something broke")

        assert len(messages) == 1
        assert messages[0][0] == 99999
        assert "TestError" in messages[0][1]
    finally:
        telegram_bot._ADMIN_CHAT_ID = original_admin
        telegram_bot._admin_last_notified = original_last


def test_admin_notification_respects_cooldown():
    from telegram_bot import _notify_admin_if_needed
    import telegram_bot

    original_admin = telegram_bot._ADMIN_CHAT_ID
    original_last = telegram_bot._admin_last_notified
    try:
        telegram_bot._ADMIN_CHAT_ID = 99999
        telegram_bot._admin_last_notified = time_module.time()  # just notified
        messages = []

        with patch("telegram_bot.send_message_safe", side_effect=lambda cid, txt, **kw: messages.append((cid, txt))):
            _notify_admin_if_needed(123, "TestError", "something broke")

        assert len(messages) == 0  # cooldown not elapsed
    finally:
        telegram_bot._ADMIN_CHAT_ID = original_admin
        telegram_bot._admin_last_notified = original_last
```

**Step 2: Run tests to verify they fail**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_admin_notification_sends_on_first_error tests/test_telegram_bot.py::test_admin_notification_respects_cooldown -v --tb=short`
Expected: FAIL

**Step 3: Implement admin notification**

Add near module-level config (after `_STORE_CHOICE`):

```python
# ── Admin error notification ─────────────────────────────────────────────────
_ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0"))
_admin_last_notified: float = 0.0
_ADMIN_NOTIFY_COOLDOWN = 300  # seconds — max 1 alert per 5 minutes


def _notify_admin_if_needed(telegram_id: int, error_type: str, error_msg: str) -> None:
    """Send an error alert to the admin chat, rate-limited to avoid spam."""
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

**Step 4: Run tests to verify they pass**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_admin_notification_sends_on_first_error tests/test_telegram_bot.py::test_admin_notification_respects_cooldown -v --tb=short`
Expected: 2 PASS

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): add admin error notification with 5-minute cooldown"
```

---

### Task 7: `/lang` Command and Language Persistence

**Files:**
- Modify: `telegram_bot.py` — add `/lang` handler in `handle_update()`
- Modify: `telegram_bot.py:218-244` — add `lang` to `persist_session` and `load_session`
- Test: `tests/test_telegram_bot.py`

**Step 1: Write failing test**

```python
def test_lang_command_shows_language_keyboard():
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[901] = {"state": "REGISTERED", "store": "Test", "username": "u", "lang": "es"}
    messages = []

    with patch("telegram_bot._tg", return_value={"ok": True}):
        with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: messages.append((txt, kw))):
            handle_update(make_text_update(901, "/lang"))

    assert len(messages) >= 1
    # Should have inline keyboard with language options
    assert any("reply_markup" in kw for _, kw in messages)


def test_lang_persisted_in_session():
    from telegram_bot import persist_session
    persisted = {}

    def mock_upsert(data):
        persisted.update(data)
        mock_exec = MagicMock()
        mock_exec.execute.return_value = None
        return mock_exec

    mock_client = MagicMock()
    mock_client.table.return_value.upsert.side_effect = mock_upsert

    with patch("telegram_bot.extensions.get_db", return_value=mock_client):
        persist_session(123, {"state": "REGISTERED", "lang": "en", "username": "test", "store": "S1"})

    assert persisted.get("lang") == "en"
```

**Step 2: Run tests to verify they fail**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_lang_command_shows_language_keyboard tests/test_telegram_bot.py::test_lang_persisted_in_session -v --tb=short`
Expected: FAIL

**Step 3: Implement `/lang` command**

In `handle_update()`, add a handler for `/lang` in the text command section (alongside `/help`, `/status`, `/cancel`, `/last`):

```python
    elif text == "/lang":
        lang_kb = _inline_kb([
            [_inline_btn("English", "lang:en"), _inline_btn("Espanol", "lang:es")],
        ])
        send_message(chat_id, msg(telegram_id, "lang_prompt"), reply_markup=lang_kb)
        return
```

The callback handler for `lang:` prefix is already in the rewritten `_handle_callback()` from Task 5.

**Step 4: Add `lang` to `persist_session` and `load_session`**

In `persist_session`, add `"lang"` to the upsert dict:

```python
client.table("bot_sessions").upsert({
    "telegram_id": telegram_id,
    "state": state.get("state", "AWAITING_USERNAME"),
    "username": state.get("username"),
    "store": state.get("store"),
    "retry_count": state.get("retry_count", 0),
    "pending_data": state.get("pending_data"),
    "lang": state.get("lang", "es"),
}).execute()
```

In `load_session`, add `"lang"` to the returned dict:

```python
return {
    "state": row.get("state", "AWAITING_USERNAME"),
    "username": row.get("username"),
    "store": row.get("store"),
    "retry_count": row.get("retry_count", 0),
    "pending_data": row.get("pending_data"),
    "lang": row.get("lang", "es"),
}
```

**Step 5: Run tests to verify they pass**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py::test_lang_command_shows_language_keyboard tests/test_telegram_bot.py::test_lang_persisted_in_session -v --tb=short`
Expected: 2 PASS

**Step 6: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): add /lang command with language persistence in bot_sessions"
```

---

### Task 8: `/bot_health` Diagnostic Endpoint

**Files:**
- Modify: `routes/telegram.py` (add new route)
- Test: `tests/test_telegram_bot.py` (or new test file)

**Step 1: Write failing test**

```python
def test_bot_health_endpoint_returns_ok(client):
    """The /api/telegram/health endpoint returns bot info when API works."""
    # This test needs the Flask test client — add to existing test infrastructure
    # If test client fixture doesn't exist, test manually after implementation
    pass  # Skip automated test — verify manually
```

**Step 2: Implement the endpoint**

Add to `routes/telegram.py` after the existing routes:

```python
import time as time_module

@bp.route('/api/telegram/health')
@require_auth(['admin', 'super_admin'])
def bot_health():
    """Check Telegram Bot API connectivity and return bot info."""
    start = time_module.time()
    try:
        from telegram_bot import _tg
        result = _tg("getMe")
        latency = round((time_module.time() - start) * 1000)
        return jsonify(ok=True, bot_username=result.get("username"), latency_ms=latency)
    except Exception as e:
        latency = round((time_module.time() - start) * 1000)
        logger.error(f"bot_health check failed: {e}")
        return jsonify(ok=False, error=str(e), latency_ms=latency), 503
```

**Step 3: Commit**

```bash
git add routes/telegram.py
git commit -m "feat(bot): add /api/telegram/health diagnostic endpoint"
```

---

### Task 9: DB Migration — Add `lang` Column

**Files:**
- No code file — SQL migration on Supabase

**Step 1: Run migration in Supabase SQL editor**

```sql
ALTER TABLE bot_sessions ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'es';
```

**Step 2: Verify**

```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'bot_sessions' AND column_name = 'lang';
```

Expected: Returns one row with `lang | text | 'es'::text`

**Step 3: Commit a migration note**

Create `docs/migrations/002-bot-sessions-lang.sql`:

```sql
-- Migration 002: Add language preference to bot_sessions
-- Run in Supabase SQL editor
ALTER TABLE bot_sessions ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'es';
```

```bash
git add docs/migrations/002-bot-sessions-lang.sql
git commit -m "docs: add migration for bot_sessions lang column"
```

---

### Task 10: Final Integration Test and Cleanup

**Files:**
- Modify: `tests/test_telegram_bot.py` (update any broken existing tests)
- Modify: `telegram_bot.py` (remove dead MSG_* constants if any remain)

**Step 1: Run full test suite**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest --tb=short -q`

**Step 2: Fix any broken existing tests**

Existing tests assert on Spanish strings like `"usuario"`. Since `msg()` defaults to Spanish, most should still pass. If any break due to the new return shape from `_tg()` (returns `result` not envelope), fix them.

The `make_callback_update` helper needs a `date` field in the message dict for button timeout checks. Update it:

```python
def make_callback_update(telegram_id: int, data: str, message_id: int = 1) -> dict:
    return {
        "callback_query": {
            "id": "cb_123",
            "from": {"id": telegram_id, "username": "testuser"},
            "message": {
                "message_id": message_id,
                "chat": {"id": telegram_id},
                "date": int(time_module.time()),  # ADD THIS — current time so buttons aren't expired
            },
            "data": data,
        }
    }
```

**Step 3: Delete any remaining MSG_* constants**

Search for `^MSG_` in `telegram_bot.py`. All should be removed. If any remain, delete them.

**Step 4: Run full test suite again**

Run: `cd /d C:\Users\mtsmy\Card-Sales\Pharmacy_Arc && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest --tb=short -q`
Expected: Same pass count as before (145), same 10 pre-existing failures.

**Step 5: Final commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "chore(bot): cleanup dead constants and fix test helpers for overhaul"
```

---

## New Environment Variables (add to Railway)

| Variable | Required | Value |
|----------|----------|-------|
| `TELEGRAM_ADMIN_CHAT_ID` | No | Your Telegram chat ID (get it from @userinfobot). If unset, admin alerts are disabled. |

## Post-Deployment Verification

1. Open Telegram, send a photo to the bot
2. Verify the date confirmation buttons (OK / Edit) work — spinner should dismiss instantly
3. Complete a full audit flow: photo -> date -> register -> payouts -> cash -> save
4. Test `/lang` command — switch to English, verify all messages change
5. Test expired button: wait 11 minutes after a button message, tap it, verify alert popup
6. Check `/api/telegram/health` in browser (must be logged in as admin)
