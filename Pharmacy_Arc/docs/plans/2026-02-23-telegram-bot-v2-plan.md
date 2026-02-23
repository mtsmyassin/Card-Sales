# Telegram Bot v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve the Carimas Telegram bot with 7 features: pharmacy knowledge base, inline keyboards, AI conversation memory, `/last` command, smarter OCR errors, payout entry, admin broadcast.

**Architecture:** All changes live in `telegram_bot.py` and `ai_assistant.py` (plus tests). Inline keyboards use Telegram's `callback_query` — requires adding a callback handler to `handle_update()` and adding `callback_query` to the webhook's `allowed_updates`. New conversation states: `AWAITING_PAYOUTS`, `AWAITING_ACTUAL_CASH`, `BROADCAST_CONFIRM`. AI memory is an in-memory dict cleared per session.

**Tech Stack:** Python, Flask, Telegram Bot API (raw HTTP), Anthropic Claude API, Supabase (PostgreSQL).

---

### Task 1: Pharmacy Knowledge Base

**Files:**
- Modify: `ai_assistant.py:16-28` (add PHARMACY_CONTEXT, inject into system prompt)
- Test: `tests/test_ai_assistant.py`

**Step 1: Write the failing test**

Add to `tests/test_ai_assistant.py`:

```python
def test_ask_ai_includes_pharmacy_context():
    """ask_ai includes PHARMACY_CONTEXT in the system prompt sent to Claude."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text = "Carimas #1 abre a las 8 AM.")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = None
        with patch("ai_assistant.anthropic.Anthropic", return_value=mock_client):
            from ai_assistant import ask_ai
            ask_ai("que hora abre carimas 1?", "Carimas #1", "staff", "maria")

    call_kwargs = mock_client.messages.create.call_args.kwargs
    system_text = call_kwargs["system"]
    assert "horario" in system_text.lower() or "pharmacy" in system_text.lower() or "PHARMACY_CONTEXT" not in system_text
    # The real check: system prompt is longer than original SYSTEM_PROMPT (has KB injected)
    from ai_assistant import SYSTEM_PROMPT
    assert len(system_text) > len(SYSTEM_PROMPT)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ai_assistant.py::test_ask_ai_includes_pharmacy_context -v`
Expected: FAIL — system prompt is just SYSTEM_PROMPT, no pharmacy context appended yet.

**Step 3: Write the implementation**

In `ai_assistant.py`, after `SYSTEM_PROMPT`, add:

```python
PHARMACY_CONTEXT = (
    "\n\n--- Información Operativa de Farmacia Carimas ---\n"
    "Tiendas:\n"
    "  Carimas #1 — [DIRECCIÓN] — Tel: [TELÉFONO] — Horario: L-S 8AM-9PM, D 9AM-5PM\n"
    "  Carimas #2 — [DIRECCIÓN] — Tel: [TELÉFONO] — Horario: L-S 8AM-9PM, D 9AM-5PM\n"
    "  Carimas #3 — [DIRECCIÓN] — Tel: [TELÉFONO] — Horario: L-S 8AM-9PM, D 9AM-5PM\n"
    "  Carimas #4 — [DIRECCIÓN] — Tel: [TELÉFONO] — Horario: L-S 8AM-9PM, D 9AM-5PM\n"
    "  Carthage   — [DIRECCIÓN] — Tel: [TELÉFONO] — Horario: L-S 8AM-9PM, D 9AM-5PM\n\n"
    "Procedimientos:\n"
    "  - Reporte Z: Imprimir al cierre de cada caja, tomar foto y enviar por Telegram.\n"
    "  - Payouts: Registrar todo desembolso de efectivo (cambio, pagos, etc.) antes del cierre.\n"
    "  - Varianza: Diferencia entre efectivo esperado y contado. Negativa = faltante.\n"
    "  - Si la varianza excede $5.00, reportar al supervisor inmediatamente.\n\n"
    "Contactos:\n"
    "  - Soporte técnico: [NOMBRE] — [TELÉFONO/EMAIL]\n"
    "  - Gerencia general: [NOMBRE] — [TELÉFONO]\n\n"
    "Usa esta información para responder preguntas operativas.\n"
    "Si el usuario pregunta algo que no está aquí ni en los datos de ventas, dilo claramente.\n"
)
```

Then modify `ask_ai()` to inject it into the system prompt:

```python
# In ask_ai(), change the client.messages.create call:
    system=SYSTEM_PROMPT + PHARMACY_CONTEXT,
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ai_assistant.py::test_ask_ai_includes_pharmacy_context -v`
Expected: PASS

**Step 5: Commit**

```bash
git add ai_assistant.py tests/test_ai_assistant.py
git commit -m "feat(bot): add pharmacy knowledge base to AI system prompt"
```

---

### Task 2: Inline Keyboards — Infrastructure

**Files:**
- Modify: `telegram_bot.py:164-178` (add `_tg_answer_callback`, inline keyboard helpers)
- Modify: `telegram_bot.py:582-589` (handle `callback_query` in `handle_update`)
- Modify: `telegram_bot.py:1030-1060` (add `callback_query` to webhook `allowed_updates`)
- Test: `tests/test_telegram_bot.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram_bot.py`:

```python
def make_callback_update(telegram_id: int, data: str, message_id: int = 1) -> dict:
    return {
        "callback_query": {
            "id": "cb_123",
            "from": {"id": telegram_id, "username": "testuser"},
            "message": {
                "message_id": message_id,
                "chat": {"id": telegram_id},
            },
            "data": data,
        }
    }


def test_callback_query_store_selection():
    """Inline button callback for store selection sets the store."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[900] = {
        "state": "AWAITING_STORE",
        "username": "admin1",
        "retry_count": 0,
    }
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot._tg") as mock_tg:
            mock_tg.return_value = {"ok": True}
            handle_update(make_callback_update(900, "store:2"))

    assert bot_state[900]["store"] == "Carimas #2"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py::test_callback_query_store_selection -v`
Expected: FAIL — `handle_update` ignores updates without `message` key.

**Step 3: Write the implementation**

In `telegram_bot.py`, add inline keyboard builder helpers after the existing `_kb_remove`:

```python
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
    [_inline_btn("✅ OK", "date:ok"), _inline_btn("✏️ Corregir", "date:edit")],
])

INLINE_CONFIRM_REG = _inline_kb([
    [_inline_btn("✅ OK", "reg:ok"), _inline_btn("✏️ Corregir", "reg:edit")],
])

INLINE_SAVE = _inline_kb([
    [_inline_btn("✅ SÍ Guardar", "save:yes"), _inline_btn("❌ NO Cancelar", "save:no")],
])

INLINE_PAYOUTS_ZERO = _inline_kb([
    [_inline_btn("Sin payouts ($0)", "payouts:0")],
])

INLINE_SKIP_CASH = _inline_kb([
    [_inline_btn("Omitir", "actual_cash:skip")],
])
```

Modify `handle_update()` to handle callbacks:

```python
def handle_update(update: dict) -> None:
    # Handle callback_query (inline button presses)
    cb = update.get("callback_query")
    if cb:
        _handle_callback(cb)
        return

    msg = update.get("message")
    if not msg:
        return
    # ... rest unchanged
```

Add the callback dispatcher:

```python
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
            send_message(chat_id, "Escribe el número de caja:")

    elif prefix == "save" and current_state == "AWAITING_CONFIRMATION":
        _handle_confirmation(telegram_id, chat_id, "YES" if value == "yes" else "NO", state)

    elif prefix == "payouts" and current_state == "AWAITING_PAYOUTS":
        _handle_payouts(telegram_id, chat_id, value, state)

    elif prefix == "actual_cash" and current_state == "AWAITING_ACTUAL_CASH":
        _handle_actual_cash(telegram_id, chat_id, value, state)

    elif prefix == "broadcast" and current_state == "BROADCAST_CONFIRM":
        _handle_broadcast_confirm(telegram_id, chat_id, value, state)
```

Update `register_webhook()` to include `callback_query`:

```python
    "allowed_updates": ["message", "callback_query"],
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_bot.py::test_callback_query_store_selection -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): add inline keyboard infrastructure and callback handler"
```

---

### Task 3: Inline Keyboards — Wire Into Existing Flow

**Files:**
- Modify: `telegram_bot.py` — update `_handle_photo`, `_handle_date`, `_handle_register`, `_handle_confirmation`, `AWAITING_STORE` to send inline keyboards alongside text messages

**Step 1: Write the failing test**

Add to `tests/test_telegram_bot.py`:

```python
def test_date_confirmation_shows_inline_keyboard():
    """After OCR, date confirmation includes inline keyboard."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[910] = {"state": "REGISTERED", "store": "Carimas #1", "username": "pedro", "retry_count": 0}
    markups = []

    def capture_msg(cid, txt, reply_markup=None, **kw):
        markups.append(reply_markup)

    good_ocr = {
        "register": 2, "date": "2026-02-22",
        "cash": 100.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": -1.5,
    }

    with patch("telegram_bot.send_message", side_effect=capture_msg):
        with patch("telegram_bot.download_photo", return_value=b"fake"):
            with patch("telegram_bot.extract_z_report", return_value=good_ocr):
                with patch("ocr.has_null_fields", return_value=False):
                    handle_update(make_photo_update(910))

    # Last message should have inline keyboard with OK/Corregir
    assert any(m and "inline_keyboard" in m for m in markups)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py::test_date_confirmation_shows_inline_keyboard -v`
Expected: FAIL — currently sends no inline_keyboard.

**Step 3: Modify the flow to include inline keyboards**

In `_handle_photo`, change the date confirmation send (around line 849):

```python
    send_message(chat_id, MSG_OCR_DATE.format(date=ocr_date), reply_markup=INLINE_CONFIRM_DATE)
```

In `_handle_date`, change the register confirmation send (around line 896):

```python
    send_message(chat_id, MSG_OCR_REG.format(reg=ocr_reg), reply_markup=INLINE_CONFIRM_REG)
```

In `_handle_register`, change the final confirmation send (around line 912):

```python
    send_message(chat_id, _format_preview(state["pending_data"]), reply_markup=INLINE_SAVE)
```

In `_handle_photo` for store selection (around line 802):

```python
    send_message(chat_id, STORE_MENU, reply_markup=INLINE_STORES)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): wire inline keyboards into OCR confirmation flow"
```

---

### Task 4: AI Conversation Memory

**Files:**
- Modify: `telegram_bot.py` (add `_ai_history` dict, update `_handle_ai_message`)
- Modify: `ai_assistant.py:76-107` (update `ask_ai` to accept `history` param)
- Test: `tests/test_ai_assistant.py`, `tests/test_telegram_bot.py`

**Step 1: Write the failing test**

Add to `tests/test_ai_assistant.py`:

```python
def test_ask_ai_with_history():
    """ask_ai sends conversation history as multi-turn messages."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="El martes fue $900.")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    history = [
        {"role": "user", "content": "cuanto fue el bruto ayer?"},
        {"role": "assistant", "content": "El bruto de ayer fue $1,200."},
    ]

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = None
        with patch("ai_assistant.anthropic.Anthropic", return_value=mock_client):
            from ai_assistant import ask_ai
            ask_ai("y el martes?", "Carimas #1", "staff", "maria", history=history)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    messages = call_kwargs["messages"]
    # Should have: context+history messages + new question = at least 3 messages
    assert len(messages) >= 3
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ai_assistant.py::test_ask_ai_with_history -v`
Expected: FAIL — `ask_ai` doesn't accept `history` param.

**Step 3: Write the implementation**

In `ai_assistant.py`, update `ask_ai` signature and body:

```python
def ask_ai(question: str, store: str, role: str, username: str,
           history: list[dict] | None = None) -> str:
    """Send a question to Claude with store context and return the response."""
    context = _fetch_store_context(store)

    context_block = (
        f"Usuario: {username} | Rol: {role} | Tienda: {store}\n"
        f"Datos últimos 7 días: {context['day_count']} días con reportes, "
        f"{len(context['entries'])} entradas.\n"
        f"Bruto total: ${context['total_gross']:.2f} | "
        f"Varianza promedio: ${context['avg_variance']:.2f}\n"
        f"Cajas activas: {', '.join(context['registers']) or 'ninguna'}\n\n"
        f"Detalle de entradas recientes:\n"
    )
    for entry in context["entries"][:15]:
        context_block += (
            f"  {entry.get('date')} | {entry.get('reg')} | "
            f"Bruto: ${entry.get('gross', 0):.2f} | "
            f"Varianza: ${entry.get('variance', 0):.2f}\n"
        )

    # Build message list: context as first user message, then history, then new question
    messages = [{"role": "user", "content": context_block + "\n(Contexto de datos — no es una pregunta.)"},
                {"role": "assistant", "content": "Entendido. Tengo el contexto de datos listo."}]
    if history:
        messages.extend(history[-10:])  # cap at last 10 messages (5 pairs)
    messages.append({"role": "user", "content": question})

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model=Config.AI_MODEL,
            max_tokens=Config.AI_MAX_TOKENS,
            system=SYSTEM_PROMPT + PHARMACY_CONTEXT,
            messages=messages,
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"ask_ai failed: {e}")
        return "Lo siento, ocurrió un error al procesar tu pregunta. Intenta de nuevo."
```

In `telegram_bot.py`, add the history dict near `bot_state`:

```python
# AI conversation history: { telegram_id: [{"role": "user", "content": ...}, ...] }
_ai_history: dict[int, list[dict]] = {}
```

Update `_handle_ai_message` to use history:

```python
def _handle_ai_message(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle a text message while in AI_CHAT state."""
    store = state.get("store", "")
    username = state.get("username", "")
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
```

Clear history when exiting AI mode — in the BTN_CANCEL handler and /cancel handler:

```python
    _ai_history.pop(telegram_id, None)
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_ai_assistant.py tests/test_telegram_bot.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add ai_assistant.py telegram_bot.py tests/test_ai_assistant.py tests/test_telegram_bot.py
git commit -m "feat(bot): add AI conversation memory for multi-turn follow-ups"
```

---

### Task 5: `/last` Command

**Files:**
- Modify: `telegram_bot.py:716-768` (add `/last` handler in `_handle_slash`)
- Test: `tests/test_telegram_bot.py`

**Step 1: Write the failing test**

```python
def test_slash_last_shows_recent_entry():
    """The /last command shows the most recent audit entry."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[920] = {"state": "REGISTERED", "store": "Carimas #1", "username": "maria", "retry_count": 0}
    replies = []

    mock_row = {"date": "2026-02-22", "reg": "Reg 1", "gross": 1500.0, "variance": -2.5, "staff": "pedro"}
    mock_result = MagicMock()
    mock_result.data = [mock_row]
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.extensions") as mock_ext:
            mock_ext.get_db.return_value = mock_db
            handle_update(make_text_update(920, "/last"))

    assert any("1500" in r or "1,500" in r for r in replies)
    assert any("2026-02-22" in r for r in replies)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py::test_slash_last_shows_recent_entry -v`
Expected: FAIL — `/last` falls through to "unknown command" → shows help.

**Step 3: Implement `/last`**

In `_handle_slash`, add before the `else` clause:

```python
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
```

Also update `MSG_HELP` to include `/last`:

```python
    "  /last   — Ver el último reporte enviado\n"
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_bot.py::test_slash_last_shows_recent_entry -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): add /last command to show most recent Z-report"
```

---

### Task 6: Smarter OCR Error Messages

**Files:**
- Modify: `telegram_bot.py:76-99` (update error messages)
- Modify: `telegram_bot.py:852-860` (`_handle_ocr_failure`)
- Test: `tests/test_telegram_bot.py`

**Step 1: Write the failing test**

```python
def test_ocr_null_fields_names_them():
    """When OCR can't read specific fields, the error message names them."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[930] = {"state": "REGISTERED", "store": "Carimas #1", "username": "ana", "retry_count": 0}
    replies = []
    partial_ocr = {
        "register": 2, "date": "2026-02-22",
        "cash": None, "ath": 50.0, "athm": 0.0, "visa": None,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": -1.5,
    }

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.download_photo", return_value=b"fake"):
            with patch("telegram_bot.extract_z_report", return_value=partial_ocr):
                handle_update(make_photo_update(930))

    # Should mention that those fields are visible
    assert any("cash" in r.lower() or "visa" in r.lower() for r in replies)
    assert any("visible" in r.lower() or "secciones" in r.lower() or "iluminación" in r.lower() for r in replies)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py::test_ocr_null_fields_names_them -v`
Expected: FAIL or check current message wording.

**Step 3: Update error messages**

Update `MSG_NULL_RETRY` and `MSG_NULL_FINAL` in `telegram_bot.py`:

```python
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
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): smarter OCR error messages with specific guidance"
```

---

### Task 7: Payout Entry Flow

**Files:**
- Modify: `telegram_bot.py` — add `AWAITING_PAYOUTS` and `AWAITING_ACTUAL_CASH` states, handlers, wire after AWAITING_REGISTER
- Test: `tests/test_telegram_bot.py`

**Step 1: Write the failing test**

```python
def test_payout_flow_zero():
    """After register confirmation, bot asks for payouts; zero skips to actual cash."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    good_ocr = {
        "register": 2, "date": "2026-02-22",
        "cash": 500.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": -1.5,
    }
    bot_state[940] = {
        "state": "AWAITING_REGISTER",
        "store": "Carimas #1",
        "username": "maria",
        "pending_data": good_ocr,
        "pending_image_bytes": b"fake",
        "retry_count": 0,
    }
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(940, "OK"))

    # Should now be in AWAITING_PAYOUTS, not AWAITING_CONFIRMATION
    assert bot_state[940]["state"] == "AWAITING_PAYOUTS"
    assert any("payout" in r.lower() or "desembolso" in r.lower() for r in replies)


def test_payout_then_actual_cash_calculates_variance():
    """Entering payouts and actual cash auto-calculates variance."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    good_ocr = {
        "register": 2, "date": "2026-02-22",
        "cash": 500.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": 0,
    }
    bot_state[941] = {
        "state": "AWAITING_PAYOUTS",
        "store": "Carimas #1",
        "username": "maria",
        "pending_data": good_ocr,
        "pending_image_bytes": b"fake",
        "retry_count": 0,
    }
    replies = []

    # Enter payouts = $50
    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(941, "50"))
    assert bot_state[941]["state"] == "AWAITING_ACTUAL_CASH"

    # Enter actual cash = $440 (expected: 500 - 50 = 450, so variance = 440 - 450 = -10)
    replies.clear()
    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(941, "440"))
    assert bot_state[941]["state"] == "AWAITING_CONFIRMATION"
    assert bot_state[941].get("pending_payouts") == 50.0
    assert bot_state[941].get("pending_actual_cash") == 440.0
    assert bot_state[941].get("pending_variance") == -10.0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py::test_payout_flow_zero tests/test_telegram_bot.py::test_payout_then_actual_cash_calculates_variance -v`
Expected: FAIL — states don't exist yet.

**Step 3: Implement payout flow**

Add messages:

```python
MSG_PAYOUTS = (
    "💵 ¿Cuánto fue el total de payouts/desembolsos?\n"
    "Escribe el monto (ej. 50.00) o toca el botón si no hubo."
)
MSG_ACTUAL_CASH = (
    "💰 ¿Cuánto efectivo hay en la caja?\n"
    "Escribe el monto contado, o toca Omitir para usar la varianza del OCR."
)
MSG_BAD_AMOUNT = "Ingresa un monto válido (ej. 50.00 o 0)."
```

Change `_handle_register` to go to `AWAITING_PAYOUTS` instead of `AWAITING_CONFIRMATION`:

```python
def _handle_register(telegram_id, chat_id, text, state):
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
```

Add handlers:

```python
def _handle_payouts(telegram_id, chat_id, text, state):
    """Handle AWAITING_PAYOUTS — parse payout amount."""
    text = text.strip().replace("$", "").replace(",", "")
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
    if text.strip().lower() == "skip" or _ascii_upper(text) in ("OMITIR", "SKIP"):
        # Keep OCR variance as-is
        state["pending_actual_cash"] = None
        state["pending_variance"] = None
    else:
        text = text.strip().replace("$", "").replace(",", "")
        try:
            actual_cash = float(text)
        except ValueError:
            send_message(chat_id, MSG_BAD_AMOUNT)
            return
        state["pending_actual_cash"] = round(actual_cash, 2)
        # variance = actual_cash - (ocr_cash - payouts)
        ocr_cash = state["pending_data"].get("cash") or 0
        payouts = state.get("pending_payouts", 0)
        state["pending_variance"] = round(actual_cash - (ocr_cash - payouts), 2)

    state["state"] = "AWAITING_CONFIRMATION"
    _set_state(telegram_id, state)
    send_message(chat_id, _format_preview(state["pending_data"]), reply_markup=INLINE_SAVE)
```

Wire in `handle_update` dispatcher (after the AWAITING_REGISTER block):

```python
    if current_state == "AWAITING_PAYOUTS":
        _handle_payouts(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_ACTUAL_CASH":
        _handle_actual_cash(telegram_id, chat_id, text, state)
        return
```

Update `_handle_confirmation` to pass payouts/variance to `save_audit_entry`:

```python
        # In the YES branch, before calling save_audit_entry:
        payouts = state.get("pending_payouts", 0.0)
        actual_cash = state.get("pending_actual_cash", 0.0)
        calc_variance = state.get("pending_variance")

        entry_id = save_audit_entry(
            ocr_data, store, username,
            payouts=payouts,
            actual_cash=actual_cash,
            variance=calc_variance,
        )
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: ALL PASS (including existing tests — existing tests that set state to AWAITING_CONFIRMATION directly should still work because they bypass the payout steps).

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): add payout entry and auto-calculated variance"
```

---

### Task 8: Admin Broadcast

**Files:**
- Modify: `telegram_bot.py` — add `/broadcast` handler, `BROADCAST_CONFIRM` state
- Test: `tests/test_telegram_bot.py`

**Step 1: Write the failing test**

```python
def test_broadcast_by_admin():
    """Admin can /broadcast a message to all bot users."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[950] = {"state": "REGISTERED", "store": "All", "username": "admin1", "retry_count": 0}
    replies = []
    call_args = []

    mock_users = MagicMock()
    mock_users.data = [
        {"telegram_id": 101, "store": "Carimas #1"},
        {"telegram_id": 102, "store": "Carimas #2"},
    ]
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.execute.return_value = mock_users

    def capture(cid, txt, **kw):
        call_args.append((cid, txt))

    with patch("telegram_bot.send_message", side_effect=capture):
        with patch("telegram_bot.get_bot_user", return_value={"role": "admin"}):
            with patch("telegram_bot.extensions") as mock_ext:
                mock_ext.get_db.return_value = mock_db
                handle_update(make_text_update(950, "/broadcast Cierre temprano hoy"))

    # Should ask for confirmation first
    assert bot_state[950]["state"] == "BROADCAST_CONFIRM"
    assert any("usuario" in t.lower() or "enviar" in t.lower() for _, t in call_args)


def test_broadcast_denied_for_staff():
    """Non-admin users cannot use /broadcast."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[951] = {"state": "REGISTERED", "store": "Carimas #1", "username": "staff1", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.get_bot_user", return_value={"role": "staff"}):
            handle_update(make_text_update(951, "/broadcast test"))

    assert any("permiso" in r.lower() or "admin" in r.lower() for r in replies)
    assert bot_state[951]["state"] == "REGISTERED"  # unchanged
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py::test_broadcast_by_admin tests/test_telegram_bot.py::test_broadcast_denied_for_staff -v`
Expected: FAIL — `/broadcast` falls through to help.

**Step 3: Implement broadcast**

Add messages:

```python
MSG_BROADCAST_CONFIRM = (
    "📢 Mensaje a enviar a {count} usuarios:\n\n"
    "{message}\n\n"
    "¿Confirmar envío?"
)
MSG_BROADCAST_SENT = "✅ Mensaje enviado a {sent} de {total} usuarios."
MSG_BROADCAST_CANCELLED = "Envío cancelado."
MSG_BROADCAST_NO_PERMISSION = "⛔ Solo administradores pueden usar /broadcast."

INLINE_BROADCAST_CONFIRM = _inline_kb([
    [_inline_btn("✅ Enviar", "broadcast:yes"), _inline_btn("❌ Cancelar", "broadcast:no")],
])
```

In `_handle_slash`, add `/broadcast`:

```python
    elif cmd == "/broadcast":
        # Admin-only check
        user_row = get_bot_user(telegram_id)
        role = user_row.get("role", "staff") if user_row else "staff"
        if role not in ("admin", "super_admin"):
            send_message(chat_id, MSG_BROADCAST_NO_PERMISSION)
            return
        # Extract message text after /broadcast
        parts = text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            send_message(chat_id, "Uso: /broadcast <mensaje>")
            return
        broadcast_msg = parts[1].strip()
        # Count recipients
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
```

Add the confirmation handler:

```python
def _handle_broadcast_confirm(telegram_id, chat_id, text, state):
    """Handle BROADCAST_CONFIRM — send or cancel the broadcast."""
    if _ascii_upper(text) in ("YES", "SI", "SÍ"):
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
```

Wire BROADCAST_CONFIRM in `handle_update`:

```python
    if current_state == "BROADCAST_CONFIRM":
        _handle_broadcast_confirm(telegram_id, chat_id, text, state)
        return
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(bot): add /broadcast command for admin announcements"
```

---

### Task 9: Run Full Test Suite and Deploy

**Step 1: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: ALL PASS (194+ existing + ~12 new = 206+ tests).

**Step 2: Bump version**

In `app.py`, update `APP_VERSION` to `"v44"`.

**Step 3: Commit and push**

```bash
git add -A
git commit -m "chore: bump version to v44"
git push origin main
```

**Step 4: Verify deployment**

Check Railway logs for clean startup. Test the bot on Telegram:
- Send a photo → verify inline buttons appear for date/register/save confirmation
- Tap "Preguntar AI" → ask an operational question ("que hora abre?")
- Ask a follow-up → verify conversation memory works
- Send `/last` → verify it shows the most recent report
- Admin: send `/broadcast test` → verify confirmation and delivery
