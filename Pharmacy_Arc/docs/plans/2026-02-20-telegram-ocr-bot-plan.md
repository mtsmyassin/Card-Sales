# Telegram OCR Bot + Z Report Viewer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Staff photograph Z Reports and send them to a Telegram bot; Claude Vision API extracts the sales figures, staff confirm, the entry saves to Supabase, and the photo appears as a camera icon on the history page.

**Architecture:** A new `telegram_bot.py` module handles the full conversation state machine and Telegram API calls using raw `requests` (already installed — no new bot library needed). A new `ocr.py` module wraps the Anthropic API. Two new Flask routes in `app.py` handle the webhook and Z report image serving. The history page JS gets a camera button for bot-submitted rows.

**Tech Stack:** Python 3.11, Flask 3, `anthropic>=0.25` (new), `requests` (existing), Supabase Python SDK (existing), Telegram Bot API (REST, no library).

**Key files:**
- `app.py` — add imports, bot state dict, 2 new routes, webhook registration, JS camera button
- `ocr.py` — new: Claude Vision extraction
- `telegram_bot.py` — new: conversation state machine
- `tests/test_ocr.py` — new
- `tests/test_telegram_bot.py` — new
- `requirements.txt` — add anthropic
- `.env.example` — document new vars

---

## Pre-requisites (Manual Steps Before Coding)

**Step A — Create Telegram bot:**
1. Open Telegram, message `@BotFather`
2. Send `/newbot`, follow prompts, copy the token
3. Add `TELEGRAM_BOT_TOKEN=<token>` to your Railway Variables and local `.env`

**Step B — Get Anthropic API key:**
1. Go to https://console.anthropic.com → API Keys → Create key
2. Add `ANTHROPIC_API_KEY=<key>` to Railway Variables and local `.env`

**Step C — Create Supabase table (run in Supabase SQL Editor):**
```sql
create table bot_users (
  telegram_id   bigint primary key,
  username      text not null,
  store         text not null,
  registered_at timestamp default now(),
  active        boolean default true
);
```

**Step D — Create Supabase Storage bucket:**
1. In Supabase dashboard → Storage → New bucket
2. Name: `z-reports`
3. Public: NO (private)
4. No size limits needed for receipt photos (~200KB each)

---

## Task 1: Add `anthropic` dependency

**Files:**
- Modify: `Pharmacy_Arc/requirements.txt`

**Step 1: Add the package**

Add this line to `requirements.txt` (alphabetically near the top):
```
anthropic>=0.25,<1.0
```

**Step 2: Install locally**

```bash
cd C:/Users/mtsmy/Card-Sales/Pharmacy_Arc
.venv/Scripts/python.exe -m pip install "anthropic>=0.25,<1.0"
```
Expected: `Successfully installed anthropic-X.X.X`

**Step 3: Verify import works**

```bash
.venv/Scripts/python.exe -c "import anthropic; print(anthropic.__version__)"
```
Expected: prints a version number without error.

**Step 4: Commit**

```bash
git add Pharmacy_Arc/requirements.txt
git commit -m "deps: add anthropic>=0.25 for Claude Vision OCR"
```

---

## Task 2: Create `ocr.py` — Z Report extraction

**Files:**
- Create: `Pharmacy_Arc/ocr.py`
- Create: `Pharmacy_Arc/tests/test_ocr.py`

**Step 1: Create `tests/` directory if missing**

```bash
mkdir -p C:/Users/mtsmy/Card-Sales/Pharmacy_Arc/tests
```

**Step 2: Write the failing test first**

Create `Pharmacy_Arc/tests/test_ocr.py`:

```python
"""Tests for OCR extraction module."""
import json
import pytest
from unittest.mock import patch, MagicMock


def make_mock_anthropic_response(json_payload: dict):
    """Helper: build a fake Anthropic API response containing JSON."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].text = json.dumps(json_payload)
    return mock_resp


GOOD_OCR_RESULT = {
    "register": 3,
    "date": "2026-07-13",
    "cash": 356.85,
    "ath": 434.89,
    "athm": 0.0,
    "visa": 97.50,
    "mc": 102.95,
    "amex": 0.0,
    "disc": 0.0,
    "wic": 0.0,
    "mcs": 0.0,
    "sss": 0.0,
    "variance": -19.31,
}

PARTIAL_OCR_RESULT = {
    "register": 3,
    "date": "2026-07-13",
    "cash": 356.85,
    "ath": None,   # unreadable
    "athm": 0.0,
    "visa": None,  # unreadable
    "mc": 102.95,
    "amex": 0.0,
    "disc": 0.0,
    "wic": 0.0,
    "mcs": 0.0,
    "sss": 0.0,
    "variance": -19.31,
}


def test_extract_z_report_returns_dict():
    from ocr import extract_z_report
    with patch("ocr.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = (
            make_mock_anthropic_response(GOOD_OCR_RESULT)
        )
        result = extract_z_report(b"fake_image_bytes")
    assert isinstance(result, dict)
    assert result["cash"] == 356.85
    assert result["ath"] == 434.89
    assert result["date"] == "2026-07-13"
    assert result["register"] == 3


def test_extract_z_report_handles_markdown_code_block():
    """Claude sometimes wraps JSON in ```json ... ``` — must strip it."""
    from ocr import extract_z_report
    wrapped = "```json\n" + json.dumps(GOOD_OCR_RESULT) + "\n```"
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].text = wrapped
    with patch("ocr.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = extract_z_report(b"fake_image_bytes")
    assert result["cash"] == 356.85


def test_has_null_fields_detects_missing():
    from ocr import has_null_fields, NULL_FIELD_NAMES
    assert has_null_fields(PARTIAL_OCR_RESULT) is True
    assert "ath" in NULL_FIELD_NAMES(PARTIAL_OCR_RESULT)
    assert "visa" in NULL_FIELD_NAMES(PARTIAL_OCR_RESULT)


def test_has_null_fields_clean_record():
    from ocr import has_null_fields
    assert has_null_fields(GOOD_OCR_RESULT) is False


def test_extract_z_report_raises_on_bad_json():
    from ocr import extract_z_report, OCRParseError
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].text = "Sorry, I cannot read this image."
    with patch("ocr.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        with pytest.raises(OCRParseError):
            extract_z_report(b"fake_image_bytes")
```

**Step 3: Run test to confirm it fails**

```bash
cd C:/Users/mtsmy/Card-Sales/Pharmacy_Arc
.venv/Scripts/python.exe -m pytest tests/test_ocr.py -v
```
Expected: `ModuleNotFoundError: No module named 'ocr'` — good, that confirms the test is wired.

**Step 4: Create `ocr.py`**

```python
"""OCR extraction for pharmacy Z Reports using Claude Vision API."""
import os
import json
import base64
import anthropic

NUMERIC_FIELDS = ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss", "variance"]

EXTRACTION_PROMPT = """This is a pharmacy register Z Report (batch close printout).
Extract the following values ONLY from the (close) column — ignore the (shift) and (even) columns.
Return ONLY valid JSON with these exact keys. Use null for any value you cannot read clearly.

{
  "register": <integer register number from the header>,
  "date": "<YYYY-MM-DD from Report Date in header>",
  "cash": <float from CASH (close)>,
  "ath": <float from ATH (close)>,
  "athm": <float from ATH MOVIL (close)>,
  "visa": <float from VISA (close)>,
  "mc": <float from MASTER CARD (close)>,
  "amex": <float from AMERICAN EXPRESS (close)>,
  "disc": <float from DISCOVER (close)>,
  "wic": <float from EBT FOOD (close)>,
  "mcs": <float from MCS OTC (close)>,
  "sss": <float from TRIPLE-S OTC (close)>,
  "variance": <float from Over / Short — negative means cash short>
}

Return ONLY the JSON object, no explanation."""


class OCRParseError(Exception):
    """Raised when Claude's response cannot be parsed as valid JSON."""


def extract_z_report(image_bytes: bytes) -> dict:
    """
    Send receipt image to Claude Vision API and return extracted fields as dict.
    Raises OCRParseError if the response is not valid JSON.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_b64,
                    },
                },
                {"type": "text", "text": EXTRACTION_PROMPT},
            ],
        }],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude wraps the JSON
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise OCRParseError(f"Claude returned non-JSON: {raw!r}") from e


def has_null_fields(data: dict) -> bool:
    """Return True if any numeric payment field is None/null."""
    return any(data.get(f) is None for f in NUMERIC_FIELDS)


def NULL_FIELD_NAMES(data: dict) -> list:
    """Return list of field names that are null."""
    return [f for f in NUMERIC_FIELDS if data.get(f) is None]
```

**Step 5: Run tests again**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ocr.py -v
```
Expected: all 5 tests PASS.

**Step 6: Commit**

```bash
git add Pharmacy_Arc/ocr.py Pharmacy_Arc/tests/test_ocr.py
git commit -m "feat: add OCR extraction module using Claude Vision API"
```

---

## Task 3: Create `telegram_bot.py` — conversation state machine

**Files:**
- Create: `Pharmacy_Arc/telegram_bot.py`
- Create: `Pharmacy_Arc/tests/test_telegram_bot.py`

**Step 1: Write the failing tests**

Create `Pharmacy_Arc/tests/test_telegram_bot.py`:

```python
"""Tests for Telegram bot state machine."""
import pytest
from unittest.mock import patch, MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

def make_text_update(telegram_id: int, text: str) -> dict:
    return {
        "message": {
            "from": {"id": telegram_id, "username": "testuser"},
            "chat": {"id": telegram_id},
            "text": text,
        }
    }


def make_photo_update(telegram_id: int) -> dict:
    return {
        "message": {
            "from": {"id": telegram_id, "username": "testuser"},
            "chat": {"id": telegram_id},
            "photo": [
                {"file_id": "small_id", "width": 100},
                {"file_id": "large_id", "width": 800},
            ],
        }
    }


# ── registration flow tests ───────────────────────────────────────────────────

def test_unregistered_user_gets_welcome():
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        with patch("telegram_bot.is_registered", return_value=False):
            handle_update(make_text_update(111, "hola"))

    assert any("usuario" in r.lower() for r in replies)
    assert bot_state[111]["state"] == "AWAITING_USERNAME"


def test_registration_wrong_password():
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[111] = {"state": "AWAITING_USERNAME"}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        handle_update(make_text_update(111, "maria"))

    assert bot_state[111]["state"] == "AWAITING_PASSWORD"
    assert bot_state[111]["username"] == "maria"

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        with patch("telegram_bot.verify_web_credentials", return_value=None):  # None = bad creds
            handle_update(make_text_update(111, "wrongpass"))

    assert bot_state[111]["state"] == "AWAITING_USERNAME"
    assert any("incorrectos" in r.lower() for r in replies)


def test_registration_success():
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[222] = {"state": "AWAITING_PASSWORD", "username": "maria"}
    replies = []
    fake_user = {"username": "maria", "store": "Carimas #2"}

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        with patch("telegram_bot.verify_web_credentials", return_value=fake_user):
            with patch("telegram_bot.save_bot_user"):
                handle_update(make_text_update(222, "correctpass"))

    assert bot_state[222]["state"] == "REGISTERED"
    assert any("registrada" in r.lower() or "registrado" in r.lower() for r in replies)


def test_already_registered_photo_triggers_ocr():
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[333] = {"state": "REGISTERED", "store": "Carimas #1", "username": "pedro"}
    replies = []
    good_ocr = {
        "register": 2, "date": "2026-07-13",
        "cash": 100.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": -1.5,
    }

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        with patch("telegram_bot.download_photo", return_value=b"fake_bytes"):
            with patch("telegram_bot.extract_z_report", return_value=good_ocr):
                with patch("ocr.has_null_fields", return_value=False):
                    handle_update(make_photo_update(333))

    assert bot_state[333]["state"] == "AWAITING_CONFIRMATION"
    assert any("guardar" in r.lower() for r in replies)


def test_confirmation_si_saves_entry():
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    good_ocr = {
        "register": 2, "date": "2026-07-13",
        "cash": 100.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": -1.5,
    }
    bot_state[444] = {
        "state": "AWAITING_CONFIRMATION",
        "store": "Carimas #2",
        "username": "maria",
        "pending_data": good_ocr,
        "pending_image_bytes": b"fake_bytes",
        "retry_count": 0,
    }
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        with patch("telegram_bot.upload_image_to_storage", return_value="https://img.url/file.jpg"):
            with patch("telegram_bot.save_audit_entry"):
                handle_update(make_text_update(444, "SI"))

    assert bot_state[444]["state"] == "REGISTERED"
    assert any("guardado" in r.lower() for r in replies)


def test_confirmation_no_cancels():
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[555] = {
        "state": "AWAITING_CONFIRMATION",
        "store": "Carimas #1",
        "username": "juan",
        "pending_data": {},
        "pending_image_bytes": b"",
        "retry_count": 0,
    }
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        handle_update(make_text_update(555, "NO"))

    assert bot_state[555]["state"] == "REGISTERED"
    assert any("cancelado" in r.lower() for r in replies)


def test_ocr_failure_increments_retry():
    from telegram_bot import handle_update, bot_state
    from ocr import OCRParseError
    bot_state.clear()
    bot_state[666] = {"state": "REGISTERED", "store": "Carimas #1", "username": "ana", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        with patch("telegram_bot.download_photo", return_value=b"blurry"):
            with patch("telegram_bot.extract_z_report", side_effect=OCRParseError("bad")):
                handle_update(make_photo_update(666))

    assert bot_state[666]["retry_count"] == 1
    assert any("intenta de nuevo" in r.lower() for r in replies)


def test_ocr_failure_twice_tells_manual():
    from telegram_bot import handle_update, bot_state
    from ocr import OCRParseError
    bot_state.clear()
    bot_state[777] = {"state": "REGISTERED", "store": "Carimas #1", "username": "ana", "retry_count": 1}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt: replies.append(txt)):
        with patch("telegram_bot.download_photo", return_value=b"blurry"):
            with patch("telegram_bot.extract_z_report", side_effect=OCRParseError("bad")):
                handle_update(make_photo_update(777))

    assert bot_state[777]["retry_count"] == 0  # reset after max
    assert any("manualmente" in r.lower() for r in replies)
```

**Step 2: Run tests — confirm they all fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py -v
```
Expected: `ModuleNotFoundError: No module named 'telegram_bot'`

**Step 3: Create `telegram_bot.py`**

```python
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

    resp = http.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={
            "url": webhook_url,
            "allowed_updates": ["message"],
        },
        timeout=10,
    )
    if resp.ok and resp.json().get("ok"):
        logger.info(f"Telegram webhook registered: {webhook_url}")
    else:
        logger.error(f"Telegram webhook registration failed: {resp.text}")
```

**Step 4: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_telegram_bot.py -v
```
Expected: all 8 tests PASS.

**Step 5: Commit**

```bash
git add Pharmacy_Arc/telegram_bot.py Pharmacy_Arc/tests/test_telegram_bot.py
git commit -m "feat: add Telegram bot conversation state machine"
```

---

## Task 4: Add webhook route + startup registration to `app.py`

**Files:**
- Modify: `Pharmacy_Arc/app.py`

**Step 1: Add imports at the top of `app.py` (after existing imports, line ~7)**

Find:
```python
import json, webbrowser, os, sys, base64, re
```

Change to:
```python
import json, webbrowser, os, sys, base64, re, time
```

**Step 2: Add the webhook route and image route**

Find the last `@app.route` block before `if __name__ == '__main__':` (around line 907–930). Add these two routes after the last existing route:

```python
# ── TELEGRAM BOT WEBHOOK ──────────────────────────────────────────────────────

@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """Receive updates from Telegram and dispatch to bot state machine."""
    # Verify secret token to reject non-Telegram requests
    expected_secret = (Config.SECRET_KEY or "")[:32]
    incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if expected_secret and incoming_secret != expected_secret:
        logger.warning("Telegram webhook: invalid secret token")
        return jsonify(ok=False), 403

    update = request.json
    if not update:
        return jsonify(ok=False), 400

    try:
        from telegram_bot import handle_update
        handle_update(update)
    except Exception as e:
        logger.error(f"Telegram webhook handler error: {e}", exc_info=True)

    # Always return 200 to Telegram (prevents retries)
    return jsonify(ok=True)


# ── Z REPORT IMAGE ENDPOINT ───────────────────────────────────────────────────

@app.route('/api/audit/<int:audit_id>/zreport_image')
@require_auth()
def get_zreport_image(audit_id: int):
    """Return a short-lived signed URL for the Z report image of an audit entry."""
    try:
        result = supabase.table("audits").select("payload").eq("id", audit_id).execute()
        if not result.data:
            return jsonify(error="Not found"), 404

        payload = result.data[0].get("payload", {})
        image_path = payload.get("z_report_image_path")
        if not image_path:
            return jsonify(error="No image for this entry"), 404

        signed = supabase.storage.from_("z-reports").create_signed_url(image_path, 3600)
        return jsonify(url=signed["signedURL"])

    except Exception as e:
        logger.error(f"get_zreport_image error: {e}", exc_info=True)
        return jsonify(error="Internal server error"), 500
```

**Step 3: Register webhook on startup**

Find the `if __name__ == '__main__':` block at the bottom of `app.py`. Just BEFORE it (not inside it), add:

```python
# Register Telegram webhook on startup (idempotent — safe on every deploy)
try:
    from telegram_bot import register_webhook
    register_webhook()
except Exception as _e:
    logger.warning(f"Could not register Telegram webhook: {_e}")
```

**Step 4: Update `register_webhook` to include secret_token**

In `telegram_bot.py`, find the `register_webhook` function. Update the `json=` payload to include the secret_token so Telegram sends it in `X-Telegram-Bot-Api-Secret-Token`:

```python
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
```

**Step 5: Start app locally and verify no import errors**

```bash
cd C:/Users/mtsmy/Card-Sales/Pharmacy_Arc
PYTHONUTF8=1 .venv/Scripts/python.exe app.py
```
Expected: App starts normally. If `TELEGRAM_BOT_TOKEN` is not in `.env`, you should see:
`INFO - TELEGRAM_BOT_TOKEN not set — Telegram bot disabled`
No crash.

**Step 6: Commit**

```bash
git add Pharmacy_Arc/app.py Pharmacy_Arc/telegram_bot.py
git commit -m "feat: add Telegram webhook route and Z report image endpoint"
```

---

## Task 5: Add camera button to history page

**Files:**
- Modify: `Pharmacy_Arc/app.py` (MAIN_UI string — `renderTable` and `viewZReport`)

The `renderTable` function is a long one-liner at **line 1464**. It builds the actions column. We need to:
1. Add a camera button if `d.z_report_image_path` is set
2. Add a `viewZReport` function
3. Add the lightbox modal HTML to MAIN_UI

**Step 1: Add `viewZReport` JS function**

In `app.py`, find the JS object that contains `renderTable`. It's in the MAIN_UI string. Find the `renderTable:` definition and add `viewZReport` right after the closing of `renderTable`.

Find this pattern (end of renderTable, start of next function):
```javascript
    renderTable: (rows) => { ... },
    print: async (idx) => {
```

Insert after `renderTable`'s closing brace and comma:
```javascript
    viewZReport: async (auditId) => {
        try {
            const resp = await fetch(`/api/audit/${auditId}/zreport_image`);
            if (!resp.ok) { alert('No hay imagen para esta entrada.'); return; }
            const { url } = await resp.json();
            const modal = document.getElementById('zreportModal');
            document.getElementById('zreportImg').src = url;
            modal.style.display = 'flex';
        } catch(e) { alert('Error cargando imagen.'); }
    },
```

**Step 2: Modify `renderTable` to add camera button**

In the `renderTable` one-liner, find where `acts` is built:
```javascript
const acts=(app.role==='staff')?`<button onclick="app.print(${i})" class="action-btn btn-print">🖨 Print</button>`:`<button onclick="app.print(${i})" class="action-btn btn-print">🖨</button><button onclick="app.editAudit(${i})" class="action-btn btn-edit">✏️</button><button onclick="app.deleteAudit(${d.id})" class="action-btn btn-del">🗑</button>`;
```

Replace the non-staff branch to append a conditional camera button:
```javascript
const camBtn=d.z_report_image_path?`<button onclick="app.viewZReport(${d.id})" class="action-btn btn-cam" title="Ver Reporte Z">📷</button>`:'';
const acts=(app.role==='staff')?`<button onclick="app.print(${i})" class="action-btn btn-print">🖨 Print</button>`:`<button onclick="app.print(${i})" class="action-btn btn-print">🖨</button><button onclick="app.editAudit(${i})" class="action-btn btn-edit">✏️</button><button onclick="app.deleteAudit(${d.id})" class="action-btn btn-del">🗑</button>${camBtn}`;
```

**Step 3: Add modal HTML + CSS to MAIN_UI**

Find the closing `</body>` tag in MAIN_UI and insert the modal before it:
```html
<!-- Z Report Image Modal -->
<div id="zreportModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:9999;align-items:center;justify-content:center;" onclick="if(event.target===this)this.style.display='none'">
  <div style="position:relative;max-width:90vw;max-height:90vh">
    <button onclick="document.getElementById('zreportModal').style.display='none'" style="position:absolute;top:-36px;right:0;background:none;border:none;color:white;font-size:28px;cursor:pointer">✕</button>
    <img id="zreportImg" src="" style="max-width:90vw;max-height:85vh;border-radius:8px;display:block">
  </div>
</div>
```

**Step 4: Run the app and manually verify**

```bash
PYTHONUTF8=1 .venv/Scripts/python.exe app.py
```
Open http://localhost:5013, log in, go to the history tab. Entries without a Z report image should show no camera button. (All existing entries have no `z_report_image_path` so this is expected.)

**Step 5: Commit**

```bash
git add Pharmacy_Arc/app.py
git commit -m "feat: add Z report camera button and lightbox to history page"
```

---

## Task 6: Update `.env.example` and deploy to Railway

**Files:**
- Modify: `Pharmacy_Arc/.env.example`

**Step 1: Add new variables to `.env.example`**

Add after the Supabase block:
```
# Telegram Bot (OCR Z Report feature)
TELEGRAM_BOT_TOKEN=your-token-from-botfather
ANTHROPIC_API_KEY=your-anthropic-api-key
```

**Step 2: Add variables to Railway**

In the Railway dashboard for the `carimas` project:
1. Go to Variables tab
2. Add `TELEGRAM_BOT_TOKEN` = (your token from @BotFather)
3. Add `ANTHROPIC_API_KEY` = (your Anthropic key)

**Step 3: Push to GitHub to trigger Railway deploy**

```bash
git add Pharmacy_Arc/.env.example
git commit -m "docs: document TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY env vars"
git push origin main
```

**Step 4: Verify deployment in Railway logs**

In Railway dashboard → Deployments → latest → Logs. Look for:
```
INFO - Telegram webhook registered: https://carimas.up.railway.app/api/telegram/webhook
```
If you see `TELEGRAM_BOT_TOKEN not set` instead, the variable wasn't saved — recheck Railway Variables.

**Step 5: Test the bot end-to-end**

1. Open Telegram, find your bot by the username you set in @BotFather
2. Send any text message → bot should ask for your username
3. Enter your web platform username → bot asks for password
4. Enter your password → bot confirms registration with your store name
5. Send a photo of a Z report → bot replies "Procesando... ⏳" then shows the preview
6. Reply "SI" → bot confirms saved
7. Open https://carimas.up.railway.app, log in, go to History → find the new entry → camera icon should appear → click it → Z report photo opens in lightbox

---

## Task 7: Run full test suite

**Step 1: Run all tests**

```bash
cd C:/Users/mtsmy/Card-Sales/Pharmacy_Arc
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/ -v
```
Expected: all tests pass including existing `test_sales_math.py`, `test_features.py`, `test_fixes.py`, `test_ocr.py`, `test_telegram_bot.py`.

**Step 2: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "test: all tests passing after Telegram OCR bot feature"
git push origin main
```
