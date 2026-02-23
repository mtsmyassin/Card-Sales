"""Tests for the z_report_photos system (updated for English bot, new state machine)."""
import pytest
from unittest.mock import patch, MagicMock


# ── Task 2: Bot helper functions ──────────────────────────────────────────────

class TestFormatRegisterId:
    def test_integer(self):
        from telegram_bot import _format_register_id
        assert _format_register_id(2) == "Reg 2"

    def test_string_integer(self):
        from telegram_bot import _format_register_id
        assert _format_register_id("3") == "Reg 3"

    def test_zero(self):
        from telegram_bot import _format_register_id
        assert _format_register_id(0) == "Reg 0"

    def test_float_truncates(self):
        from telegram_bot import _format_register_id
        assert _format_register_id(2.0) == "Reg 2"

    def test_none_returns_unknown(self):
        from telegram_bot import _format_register_id
        assert _format_register_id(None) == "Reg ?"


# ── Task 3: StorageUploadError ────────────────────────────────────────────────

class TestUploadImageToStorage:
    def test_raises_when_supabase_admin_none(self):
        from telegram_bot import upload_image_to_storage
        with patch("extensions.supabase_admin", None):
            with pytest.raises(Exception):
                upload_image_to_storage(b"bytes", "Carimas #1", "2026-02-20", 2)


# ── Task 4: save_audit_entry returns id ───────────────────────────────────────

class TestSaveAuditEntryReturnsId:
    def test_returns_entry_id_on_success(self):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{"id": 42}]

        with patch("extensions.supabase_admin", None), \
             patch("extensions.supabase", mock_supabase):
            from telegram_bot import save_audit_entry
            ocr = {
                "register": 2, "date": "2026-02-20",
                "cash": 100.0, "ath": 0.0, "athm": 0.0, "visa": 0.0,
                "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0,
                "mcs": 0.0, "sss": 0.0, "variance": -5.0,
            }
            entry_id = save_audit_entry(ocr, "Carimas #1", "maria", payouts=0.0, actual_cash=95.0, variance=-5.0)

        assert entry_id == 42


# ── Task 5: New state machine (AWAITING_DATE → AWAITING_REGISTER → AWAITING_CONFIRMATION) ──

def make_text_update(telegram_id: int, text: str) -> dict:
    return {"message": {"from": {"id": telegram_id, "username": "testuser"},
                        "chat": {"id": telegram_id}, "text": text}}

def make_photo_update(telegram_id: int) -> dict:
    return {"message": {"from": {"id": telegram_id, "username": "testuser"},
                        "chat": {"id": telegram_id},
                        "photo": [{"file_id": "small", "width": 100},
                                  {"file_id": "large", "width": 800}]}}

GOOD_OCR = {
    "register": 2, "date": "2026-02-20",
    "cash": 100.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
    "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
    "sss": 0.0, "variance": -1.5,
}


class TestNewBotFlow:
    def test_photo_leads_to_awaiting_date(self):
        """After OCR success, state should be AWAITING_DATE (date confirmation step)."""
        from telegram_bot import handle_update, bot_state
        bot_state.clear()
        bot_state[100] = {"state": "REGISTERED", "store": "Carimas #1",
                          "username": "manager", "retry_count": 0}
        replies = []

        with patch("telegram_bot.send_message", side_effect=lambda c, t: replies.append(t)):
            with patch("telegram_bot.download_photo", return_value=b"bytes"):
                with patch("telegram_bot.extract_z_report", return_value=GOOD_OCR):
                    with patch("ocr.has_null_fields", return_value=False):
                        handle_update(make_photo_update(100))

        assert bot_state[100]["state"] == "AWAITING_DATE"
        assert any("fecha" in r.lower() for r in replies)

    def test_date_ok_leads_to_awaiting_register(self):
        """Replying OK in AWAITING_DATE confirms the OCR date and moves to AWAITING_REGISTER."""
        from telegram_bot import handle_update, bot_state
        bot_state.clear()
        bot_state[101] = {
            "state": "AWAITING_DATE",
            "store": "Carimas #1", "username": "manager",
            "pending_data": GOOD_OCR.copy(), "pending_image_bytes": b"bytes",
            "retry_count": 0,
        }
        replies = []
        with patch("telegram_bot.send_message", side_effect=lambda c, t: replies.append(t)):
            handle_update(make_text_update(101, "OK"))

        assert bot_state[101]["state"] == "AWAITING_REGISTER"

    def test_date_override_leads_to_awaiting_register(self):
        """Typing a date in MM/DD/YYYY format overrides OCR date and moves to AWAITING_REGISTER."""
        from telegram_bot import handle_update, bot_state
        bot_state.clear()
        bot_state[102] = {
            "state": "AWAITING_DATE",
            "store": "Carimas #1", "username": "manager",
            "pending_data": GOOD_OCR.copy(), "pending_image_bytes": b"bytes",
            "retry_count": 0,
        }
        replies = []
        with patch("telegram_bot.send_message", side_effect=lambda c, t: replies.append(t)):
            handle_update(make_text_update(102, "02/25/2026"))

        assert bot_state[102]["state"] == "AWAITING_REGISTER"
        assert bot_state[102]["pending_data"]["date"] == "2026-02-25"

    def test_invalid_date_stays_in_awaiting_date(self):
        """An unrecognized date string keeps the user in AWAITING_DATE."""
        from telegram_bot import handle_update, bot_state
        bot_state.clear()
        bot_state[103] = {
            "state": "AWAITING_DATE",
            "store": "Carimas #1", "username": "manager",
            "pending_data": GOOD_OCR.copy(), "pending_image_bytes": b"bytes",
            "retry_count": 0,
        }
        with patch("telegram_bot.send_message"):
            handle_update(make_text_update(103, "not-a-date"))

        assert bot_state[103]["state"] == "AWAITING_DATE"

    def test_register_ok_leads_to_awaiting_confirmation(self):
        """Replying OK in AWAITING_REGISTER confirms OCR register and moves to AWAITING_CONFIRMATION."""
        from telegram_bot import handle_update, bot_state
        bot_state.clear()
        bot_state[104] = {
            "state": "AWAITING_REGISTER",
            "store": "Carimas #1", "username": "manager",
            "pending_data": GOOD_OCR.copy(), "pending_image_bytes": b"bytes",
            "retry_count": 0,
        }
        replies = []
        with patch("telegram_bot.send_message", side_effect=lambda c, t: replies.append(t)):
            handle_update(make_text_update(104, "OK"))

        assert bot_state[104]["state"] == "AWAITING_CONFIRMATION"
        assert any("guardar" in r.lower() for r in replies)

    def test_yes_confirmation_saves_entry_and_photo(self):
        """YES in AWAITING_CONFIRMATION calls save_audit_entry + save_photo_record."""
        from telegram_bot import handle_update, bot_state
        bot_state.clear()
        bot_state[105] = {
            "state": "AWAITING_CONFIRMATION",
            "store": "Carimas #2", "username": "maria",
            "pending_data": GOOD_OCR, "pending_image_bytes": b"bytes",
            "retry_count": 0,
        }
        replies = []

        with patch("telegram_bot.send_message", side_effect=lambda c, t: replies.append(t)):
            with patch("telegram_bot.upload_image_to_storage", return_value="Carimas2/2026-02-20/reg2_123.jpg"):
                with patch("telegram_bot.save_audit_entry", return_value=99):
                    with patch("telegram_bot.save_photo_record") as mock_photo:
                        handle_update(make_text_update(105, "YES"))

        assert bot_state[105]["state"] == "REGISTERED"
        assert any("guardado" in r.lower() for r in replies)
        mock_photo.assert_called_once_with(
            entry_id=99,
            store="Carimas #2",
            business_date="2026-02-20",
            register_id="Reg 2",
            uploaded_by="maria",
            storage_path="Carimas2/2026-02-20/reg2_123.jpg",
        )


# ── Task 6: IDOR helper ───────────────────────────────────────────────────────

class TestCanAccessPhoto:
    def test_staff_cannot_access_other_store(self):
        from helpers.auth_utils import can_access_photo as _can_access_photo
        assert _can_access_photo("Carimas #1", "staff", "Carimas #2") is False

    def test_staff_can_access_own_store(self):
        from helpers.auth_utils import can_access_photo as _can_access_photo
        assert _can_access_photo("Carimas #1", "staff", "Carimas #1") is True

    def test_manager_can_access_own_store(self):
        from helpers.auth_utils import can_access_photo as _can_access_photo
        assert _can_access_photo("Carimas #3", "manager", "Carimas #3") is True

    def test_admin_can_access_any_store(self):
        from helpers.auth_utils import can_access_photo as _can_access_photo
        assert _can_access_photo("Carimas #1", "admin", "All") is True

    def test_super_admin_can_access_any_store(self):
        from helpers.auth_utils import can_access_photo as _can_access_photo
        assert _can_access_photo("Carthage", "super_admin", "Carimas #1") is True


# ── Task 10: Regression guard ─────────────────────────────────────────────────

class TestRegressionNoHtmlInScript:
    def test_zreport_modal_is_outside_script_block(self):
        """
        Regression guard: the zreportModal div must appear AFTER </script>.
        This was the bug that caused 'SyntaxError: Unexpected token <' in the browser.
        """
        import sys
        import os
        import unittest.mock as mock

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        with mock.patch.dict(os.environ, {
            'FLASK_SECRET_KEY': 'test-key-minimum-32-chars-long-ok!!',
            'SUPABASE_URL': 'https://test.supabase.co',
            'SUPABASE_KEY': 'test-key',
        }):
            with mock.patch('supabase.create_client', return_value=mock.MagicMock()):
                with mock.patch('config.Config.startup_check'):
                    import importlib
                    import app as app_module
                    importlib.reload(app_module)
                    main_ui = app_module.MAIN_UI

        script_close = main_ui.rfind('</script>')
        modal_pos = main_ui.find('id="zreportModal"')
        assert script_close != -1, "No </script> found in MAIN_UI"
        assert modal_pos != -1, "zreportModal not found in MAIN_UI"
        assert script_close < modal_pos, (
            f"BUG: zreportModal HTML (pos {modal_pos}) is INSIDE </script> (pos {script_close}). "
            "This causes 'Unexpected token <' in the browser."
        )
