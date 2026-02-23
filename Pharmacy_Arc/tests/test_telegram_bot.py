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
