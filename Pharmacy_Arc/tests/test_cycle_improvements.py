"""
Regression guards for Cycle 4 + 5 improvements.

Cycle 4: diagnostics admin_client field, bot insert error handling
Cycle 5: UX fixes (password type, card labels, refresh button)
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_main_ui():
    """Load main.html template source with {% include %} directives resolved."""
    import re
    templates_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "templates",
    )
    with open(os.path.join(templates_dir, "main.html"), encoding="utf-8") as f:
        src = f.read()
    # Resolve {% include 'path' %} directives for structural HTML checks
    def _resolve(match):
        inc_path = os.path.join(templates_dir, match.group(1))
        if os.path.exists(inc_path):
            with open(inc_path, encoding="utf-8") as fh:
                return fh.read()
        return match.group(0)
    return re.sub(r"\{%\s*include\s+['\"]([^'\"]+)['\"]\s*%\}", _resolve, src)


def _app_source():
    # Diagnostics patterns live in routes/diagnostics.py after the refactor
    with open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes", "diagnostics.py"),
        encoding="utf-8",
    ) as f:
        return f.read()


# ── Cycle 5: UX regression guards ────────────────────────────────────────────

class TestUXFixes:
    """Structural HTML checks — prevent regressions on Cycle 5 UX fixes."""

    @pytest.fixture(scope="class")
    def ui(self):
        return _load_main_ui()

    def test_password_field_is_type_password(self, ui):
        """User creation password input must be type=password, not type=text."""
        assert 'id="u_pass"' in ui, "u_pass field missing from MAIN_UI"
        idx = ui.find('id="u_pass"')
        # Read 100 chars around the attribute to check the input tag
        snippet = ui[max(0, idx - 60) : idx + 100]
        assert 'type="password"' in snippet, (
            f"Password field must be type=password. Got: {snippet!r}"
        )

    def test_password_field_not_type_text(self, ui):
        """Regression: password field was previously type=text — must never return."""
        idx = ui.find('id="u_pass"')
        snippet = ui[max(0, idx - 60) : idx + 100]
        assert 'type="text"' not in snippet, (
            "Password field reverted to type=text — plaintext passwords visible!"
        )

    def test_card_inputs_have_labels(self, ui):
        """Each of the 9 card payment inputs must have a visible <label>."""
        expected = ["ATH", "ATHM", "Visa", "MC", "AmEx", "Disc", "WIC", "MCS", "Triple S"]
        missing = [lbl for lbl in expected if f"<label>{lbl}</label>" not in ui]
        assert not missing, f"Missing <label> wrappers for: {missing}"

    def test_all_card_field_ids_present(self, ui):
        """Card payment field IDs must survive the label-wrapping refactor."""
        for fid in ["ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss"]:
            assert f'id="{fid}"' in ui, f"Card input id={fid!r} missing from MAIN_UI"

    def test_refresh_button_has_btn_main_class(self, ui):
        """Refresh button in History tab must use the btn-main design class."""
        assert "app.fetch()" in ui
        idx = ui.find("app.fetch()")
        snippet = ui[max(0, idx - 80) : idx + 80]
        assert "btn-main" in snippet, (
            f"Refresh button missing btn-main class: {snippet!r}"
        )


# ── Cycle 4: Diagnostics admin_client field ───────────────────────────────────

class TestDiagnosticsAdminClientField:
    """diagnostics() response must expose admin_client status."""

    def test_admin_client_key_present_in_source(self):
        src = _app_source()
        assert '"admin_client"' in src, (
            "diagnostics response dict must include 'admin_client' key"
        )

    def test_admin_client_configured_message_present(self):
        src = _app_source()
        assert '"configured"' in src, (
            "diagnostics must report 'configured' when supabase_admin is set"
        )

    def test_admin_client_not_set_warning_present(self):
        src = _app_source()
        assert "NOT SET" in src, (
            "diagnostics must warn 'NOT SET' when SUPABASE_SERVICE_KEY is missing"
        )

    def test_storage_diagnostics_use_admin_client(self):
        """Storage bucket listing must prefer supabase_admin (bypass RLS)."""
        src = _app_source()
        # After Cycle 4 fix, storage diagnostics assign _storage_client = supabase_admin or supabase
        assert "_storage_client" in src, (
            "Storage diagnostics must use _storage_client (supabase_admin or supabase)"
        )


# ── Cycle 4: Bot insert error handling ───────────────────────────────────────

class TestBotInsertErrorHandling:
    """save_audit_entry must raise on DB failure and must use admin client."""

    _OCR = {
        "register": 2, "date": "2026-02-20",
        "cash": 100.0, "ath": 0.0, "athm": 0.0, "visa": 0.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0,
        "mcs": 0.0, "sss": 0.0, "variance": 0.0,
    }

    def test_raises_on_db_failure_does_not_queue(self):
        """DB insert failure must raise — must NOT fall back to offline queue."""
        failing_admin = MagicMock()
        failing_admin.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("DB insert rejected by RLS")
        )

        with patch("extensions.supabase_admin", failing_admin), \
             patch("extensions.supabase", None):
            from telegram_bot import save_audit_entry
            with pytest.raises(RuntimeError, match="DB insert rejected by RLS"):
                save_audit_entry(self._OCR, "Carimas #1", "maria")

    def test_prefers_admin_client_over_anon(self):
        """When supabase_admin is available it must be used; anon client untouched."""
        mock_admin = MagicMock()
        mock_admin.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": 99}
        ]
        mock_anon = MagicMock()

        with patch("extensions.supabase_admin", mock_admin), \
             patch("extensions.supabase", mock_anon):
            from telegram_bot import save_audit_entry
            entry_id = save_audit_entry(self._OCR, "Carimas #1", "pedro")

        assert entry_id == 99
        mock_admin.table.assert_called()
        mock_anon.table.assert_not_called()

    def test_falls_back_to_anon_when_admin_none(self):
        """When supabase_admin is None, anon supabase client is used as fallback."""
        mock_anon = MagicMock()
        mock_anon.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": 55}
        ]

        with patch("extensions.supabase_admin", None), \
             patch("extensions.supabase", mock_anon):
            from telegram_bot import save_audit_entry
            entry_id = save_audit_entry(self._OCR, "Carimas #2", "juan")

        assert entry_id == 55
        mock_anon.table.assert_called()
