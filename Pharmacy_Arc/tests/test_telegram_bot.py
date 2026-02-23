"""Tests for Telegram bot state machine (Spanish UI, AWAITING_DATE/REGISTER flow)."""
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

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.is_registered", return_value=False):
            with patch("telegram_bot.load_session", return_value=None):
                handle_update(make_text_update(111, "hello"))

    assert any("usuario" in r.lower() for r in replies)
    assert bot_state[111]["state"] == "AWAITING_USERNAME"


def test_registration_wrong_password():
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[111] = {"state": "AWAITING_USERNAME"}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(111, "maria"))

    assert bot_state[111]["state"] == "AWAITING_PASSWORD"
    assert bot_state[111]["username"] == "maria"

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
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

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.verify_web_credentials", return_value=fake_user):
            with patch("telegram_bot.save_bot_user"):
                handle_update(make_text_update(222, "correctpass"))

    assert bot_state[222]["state"] == "REGISTERED"
    assert any("registrado" in r.lower() for r in replies)


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

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.download_photo", return_value=b"fake_bytes"):
            with patch("telegram_bot.extract_z_report", return_value=good_ocr):
                with patch("ocr.has_null_fields", return_value=False):
                    handle_update(make_photo_update(333))

    assert bot_state[333]["state"] == "AWAITING_DATE"
    assert any("fecha" in r.lower() for r in replies)


def test_confirmation_yes_saves_entry():
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

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.upload_image_to_storage", return_value="https://img.url/file.jpg"):
            with patch("telegram_bot.save_audit_entry", return_value=99):
                with patch("telegram_bot.save_photo_record"):
                    handle_update(make_text_update(444, "YES"))

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

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(555, "NO"))

    assert bot_state[555]["state"] == "REGISTERED"
    assert any("cancelado" in r.lower() for r in replies)


def test_ocr_failure_increments_retry():
    from telegram_bot import handle_update, bot_state
    from ocr import OCRParseError
    bot_state.clear()
    bot_state[666] = {"state": "REGISTERED", "store": "Carimas #1", "username": "ana", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.download_photo", return_value=b"blurry"):
            with patch("telegram_bot.extract_z_report", side_effect=OCRParseError("bad")):
                handle_update(make_photo_update(666))

    assert bot_state[666]["retry_count"] == 1
    assert any("intento" in r.lower() for r in replies)


def test_ocr_failure_twice_tells_manual():
    from telegram_bot import handle_update, bot_state
    from ocr import OCRParseError
    bot_state.clear()
    bot_state[777] = {"state": "REGISTERED", "store": "Carimas #1", "username": "ana", "retry_count": 1}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.download_photo", return_value=b"blurry"):
            with patch("telegram_bot.extract_z_report", side_effect=OCRParseError("bad")):
                handle_update(make_photo_update(777))

    assert bot_state[777]["retry_count"] == 0  # reset after max
    assert any("manualmente" in r.lower() for r in replies)


# ── callback query helpers & tests ───────────────────────────────────────────

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


def test_callback_date_ok():
    """Inline date OK button progresses to register confirmation."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[901] = {
        "state": "AWAITING_DATE",
        "store": "Carimas #1",
        "username": "maria",
        "pending_data": {"date": "2026-02-22", "register": 2},
        "pending_image_bytes": b"fake",
        "retry_count": 0,
    }
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot._tg") as mock_tg:
            mock_tg.return_value = {"ok": True}
            handle_update(make_callback_update(901, "date:ok"))

    assert bot_state[901]["state"] == "AWAITING_REGISTER"


def test_callback_save_yes():
    """Inline save:yes button saves the entry."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    good_ocr = {
        "register": 2, "date": "2026-02-22",
        "cash": 100.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": -1.5,
    }
    bot_state[902] = {
        "state": "AWAITING_CONFIRMATION",
        "store": "Carimas #2",
        "username": "maria",
        "pending_data": good_ocr,
        "pending_image_bytes": b"fake",
        "retry_count": 0,
    }
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot._tg") as mock_tg:
            mock_tg.return_value = {"ok": True}
            with patch("telegram_bot.upload_image_to_storage", return_value="path/file.jpg"):
                with patch("telegram_bot.save_audit_entry", return_value=99):
                    with patch("telegram_bot.save_photo_record"):
                        handle_update(make_callback_update(902, "save:yes"))

    assert bot_state[902]["state"] == "REGISTERED"
    assert any("guardado" in r.lower() for r in replies)


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


# ── AI conversation memory tests ────────────────────────────────────────────

def test_ai_chat_builds_history():
    """AI chat accumulates conversation history."""
    from telegram_bot import handle_update, bot_state, _ai_history
    bot_state.clear()
    _ai_history.clear()
    bot_state[920] = {"state": "AI_CHAT", "store": "Carimas #1", "username": "maria", "retry_count": 0}

    with patch("telegram_bot.send_message"):
        with patch("telegram_bot.ask_ai", return_value="Respuesta 1"):
            with patch("telegram_bot.get_bot_user", return_value={"role": "staff"}):
                handle_update(make_text_update(920, "pregunta 1"))

    assert 920 in _ai_history
    assert len(_ai_history[920]) == 2  # user + assistant

    with patch("telegram_bot.send_message"):
        with patch("telegram_bot.ask_ai", return_value="Respuesta 2"):
            with patch("telegram_bot.get_bot_user", return_value={"role": "staff"}):
                handle_update(make_text_update(920, "pregunta 2"))

    assert len(_ai_history[920]) == 4  # 2 pairs


def test_ai_history_cleared_on_cancel_button():
    """AI history is cleared when user taps Cancel button."""
    from telegram_bot import handle_update, bot_state, _ai_history, BTN_CANCEL
    bot_state.clear()
    _ai_history.clear()
    _ai_history[921] = [
        {"role": "user", "content": "test"},
        {"role": "assistant", "content": "response"},
    ]
    bot_state[921] = {"state": "AI_CHAT", "store": "Carimas #1", "username": "maria", "retry_count": 0}

    with patch("telegram_bot.send_message"):
        handle_update(make_text_update(921, BTN_CANCEL))

    assert 921 not in _ai_history
    assert bot_state[921]["state"] == "REGISTERED"


def test_ai_history_cleared_on_slash_cancel():
    """AI history is cleared when user sends /cancel."""
    from telegram_bot import handle_update, bot_state, _ai_history
    bot_state.clear()
    _ai_history.clear()
    _ai_history[922] = [
        {"role": "user", "content": "test"},
        {"role": "assistant", "content": "response"},
    ]
    bot_state[922] = {"state": "AI_CHAT", "store": "Carimas #1", "username": "maria", "retry_count": 0}

    with patch("telegram_bot.send_message"):
        handle_update(make_text_update(922, "/cancel"))

    assert 922 not in _ai_history
    assert bot_state[922]["state"] == "REGISTERED"


# ── /last command tests ──────────────────────────────────────────────────────

def test_slash_last_shows_recent_entry():
    """The /last command shows the most recent audit entry."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[925] = {"state": "REGISTERED", "store": "Carimas #1", "username": "maria", "retry_count": 0}
    replies = []

    mock_row = {"date": "2026-02-22", "reg": "Reg 1", "gross": 1500.0, "variance": -2.5, "staff": "pedro"}
    mock_result = MagicMock()
    mock_result.data = [mock_row]
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.extensions") as mock_ext:
            mock_ext.get_db.return_value = mock_db
            handle_update(make_text_update(925, "/last"))

    assert any("1,500" in r or "1500" in r for r in replies)
    assert any("2026-02-22" in r for r in replies)


def test_slash_last_no_store():
    """The /last command for 'All' store shows an appropriate message."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[926] = {"state": "REGISTERED", "store": "All", "username": "admin1", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(926, "/last"))

    assert any("específica" in r.lower() for r in replies)


# ── payout entry flow tests ──────────────────────────────────────────────────

def test_register_ok_goes_to_payouts():
    """After register confirmation, bot asks for payouts (not direct to confirmation)."""
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

    assert bot_state[940]["state"] == "AWAITING_PAYOUTS"
    assert any("payout" in r.lower() or "desembolso" in r.lower() for r in replies)


def test_payout_then_cash_calculates_variance():
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
    assert bot_state[941]["pending_payouts"] == 50.0

    # Enter actual cash = $440 (expected: 500 - 50 = 450, variance = 440 - 450 = -10)
    replies.clear()
    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(941, "440"))
    assert bot_state[941]["state"] == "AWAITING_CONFIRMATION"
    assert bot_state[941]["pending_actual_cash"] == 440.0
    assert bot_state[941]["pending_variance"] == -10.0


def test_payout_skip_actual_cash():
    """User can skip actual cash entry to keep OCR variance."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    good_ocr = {
        "register": 2, "date": "2026-02-22",
        "cash": 500.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": -3.0,
    }
    bot_state[942] = {
        "state": "AWAITING_ACTUAL_CASH",
        "store": "Carimas #1",
        "username": "maria",
        "pending_data": good_ocr,
        "pending_payouts": 0.0,
        "pending_image_bytes": b"fake",
        "retry_count": 0,
    }
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(942, "omitir"))
    assert bot_state[942]["state"] == "AWAITING_CONFIRMATION"
    assert bot_state[942]["pending_variance"] is None  # OCR variance kept


def test_ocr_null_fields_gives_specific_guidance():
    """When OCR can't read specific fields, error gives specific tips."""
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

    # Should mention the fields and give specific guidance
    assert any("cash" in r.lower() or "visa" in r.lower() for r in replies)
    assert any("secciones" in r.lower() or "visibles" in r.lower() for r in replies)


# ── broadcast command tests ──────────────────────────────────────────────────

def test_broadcast_by_admin():
    """Admin can /broadcast a message; enters BROADCAST_CONFIRM state."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[950] = {"state": "REGISTERED", "store": "All", "username": "admin1", "retry_count": 0}
    replies = []

    mock_users = MagicMock()
    mock_users.data = [
        {"telegram_id": 101, "store": "Carimas #1"},
        {"telegram_id": 102, "store": "Carimas #2"},
    ]
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.execute.return_value = mock_users

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.get_bot_user", return_value={"role": "admin"}):
            with patch("telegram_bot.extensions") as mock_ext:
                mock_ext.get_db.return_value = mock_db
                handle_update(make_text_update(950, "/broadcast Cierre temprano hoy"))

    assert bot_state[950]["state"] == "BROADCAST_CONFIRM"
    assert bot_state[950]["pending_broadcast"] == "Cierre temprano hoy"
    assert any("enviar" in r.lower() or "confirmar" in r.lower() for r in replies)


def test_broadcast_denied_for_staff():
    """Non-admin users cannot use /broadcast."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[951] = {"state": "REGISTERED", "store": "Carimas #1", "username": "staff1", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.get_bot_user", return_value={"role": "staff"}):
            handle_update(make_text_update(951, "/broadcast test"))

    assert any("administradores" in r.lower() or "admin" in r.lower() for r in replies)
    assert bot_state[951]["state"] == "REGISTERED"


def test_broadcast_confirm_sends_to_users():
    """Confirming broadcast sends message to all bot users except self."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[952] = {
        "state": "BROADCAST_CONFIRM",
        "store": "All",
        "username": "admin1",
        "pending_broadcast": "Cierre a las 5pm",
        "retry_count": 0,
    }
    sent_to = []

    mock_users = MagicMock()
    mock_users.data = [
        {"telegram_id": 101},
        {"telegram_id": 102},
        {"telegram_id": 952},  # self — should be skipped
    ]
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.execute.return_value = mock_users

    def capture(cid, txt, **kw):
        sent_to.append((cid, txt))

    with patch("telegram_bot.send_message", side_effect=capture):
        with patch("telegram_bot.extensions") as mock_ext:
            mock_ext.get_db.return_value = mock_db
            handle_update(make_text_update(952, "YES"))

    assert bot_state[952]["state"] == "REGISTERED"
    # Should have sent to 101 and 102 (not 952/self), plus confirmation to admin
    broadcast_msgs = [(cid, txt) for cid, txt in sent_to if "\U0001f4e2" in txt]
    assert len(broadcast_msgs) == 2
    assert all(cid != 952 for cid, _ in broadcast_msgs)
