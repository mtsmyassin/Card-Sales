"""Tests for AI assistant module and AI_CHAT bot state."""
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


# ── _fetch_store_context tests ───────────────────────────────────────────────

def test_fetch_store_context_no_db():
    """Returns empty context when DB is unavailable."""
    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = None
        from ai_assistant import _fetch_store_context
        result = _fetch_store_context("Carimas #1")
    assert result["entries"] == []
    assert result["total_gross"] == 0
    assert result["day_count"] == 0


def test_fetch_store_context_with_data():
    """Returns correct aggregates from mock DB data."""
    mock_rows = [
        {"date": "2026-02-22", "reg": "Reg 1", "gross": 1000.0, "variance": -2.5, "store": "Carimas #1"},
        {"date": "2026-02-21", "reg": "Reg 2", "gross": 800.0, "variance": 1.0, "store": "Carimas #1"},
    ]
    mock_result = MagicMock()
    mock_result.data = mock_rows
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = mock_result

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = mock_db
        from ai_assistant import _fetch_store_context
        result = _fetch_store_context("Carimas #1")

    assert result["total_gross"] == 1800.0
    assert result["avg_variance"] == -0.75
    assert result["day_count"] == 2
    assert len(result["entries"]) == 2


def test_fetch_store_context_db_error():
    """Returns empty context on DB query failure."""
    mock_db = MagicMock()
    mock_db.table.return_value.select.side_effect = Exception("connection lost")

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = mock_db
        from ai_assistant import _fetch_store_context
        result = _fetch_store_context("Carimas #1")

    assert result["entries"] == []


# ── ask_ai tests ─────────────────────────────────────────────────────────────

def test_ask_ai_returns_response():
    """ask_ai returns Claude's response text."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="El bruto de ayer fue $1,200.00")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = None  # skip DB fetch
        with patch("ai_assistant.anthropic.Anthropic", return_value=mock_client):
            from ai_assistant import ask_ai
            result = ask_ai("cuanto fue el bruto de ayer?", "Carimas #1", "staff", "maria")

    assert "1,200" in result
    mock_client.messages.create.assert_called_once()


def test_ask_ai_includes_pharmacy_context():
    """ask_ai includes PHARMACY_CONTEXT in the system prompt sent to Claude."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Carimas #1 abre a las 8 AM.")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = None
        with patch("ai_assistant.anthropic.Anthropic", return_value=mock_client):
            from ai_assistant import ask_ai
            ask_ai("que hora abre carimas 1?", "Carimas #1", "staff", "maria")

    call_kwargs = mock_client.messages.create.call_args.kwargs
    system_text = call_kwargs["system"]
    from ai_assistant import SYSTEM_PROMPT
    assert len(system_text) > len(SYSTEM_PROMPT)
    assert "Carimas #1" in system_text
    assert "Horario" in system_text or "horario" in system_text


def test_ask_ai_error_returns_friendly_message():
    """ask_ai returns error message on API failure."""
    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = None
        with patch("ai_assistant.anthropic.Anthropic", side_effect=Exception("API down")):
            from ai_assistant import ask_ai
            result = ask_ai("test", "Carimas #1", "staff", "user")

    assert "error" in result.lower() or "intenta" in result.lower()


def test_ask_ai_uses_config_model():
    """ask_ai passes Config.AI_MODEL and AI_MAX_TOKENS to Claude."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="respuesta")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = None
        with patch("ai_assistant.anthropic.Anthropic", return_value=mock_client):
            with patch("ai_assistant.Config") as mock_cfg:
                mock_cfg.AI_MODEL = "claude-sonnet-4-6"
                mock_cfg.AI_MAX_TOKENS = 500
                mock_cfg.VARIANCE_ALERT_THRESHOLD = 5.0
                from ai_assistant import ask_ai
                ask_ai("test", "Carimas #1", "staff", "user")

    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "claude-sonnet-4-6"
    assert call_kwargs.kwargs["max_tokens"] == 500


# ── analyze_variance_trend tests ─────────────────────────────────────────────

def test_analyze_variance_trend_insufficient_data():
    """Returns None when fewer than 2 entries."""
    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = None
        from ai_assistant import analyze_variance_trend
        result = analyze_variance_trend("Carimas #1", days=3)
    assert result is None


def test_analyze_variance_trend_no_high_variance():
    """Returns None when variance is within threshold."""
    mock_rows = [
        {"date": "2026-02-22", "reg": "Reg 1", "gross": 1000.0, "variance": -1.0, "store": "Carimas #1"},
        {"date": "2026-02-21", "reg": "Reg 2", "gross": 800.0, "variance": 2.0, "store": "Carimas #1"},
    ]
    mock_result = MagicMock()
    mock_result.data = mock_rows
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = mock_result

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = mock_db
        from ai_assistant import analyze_variance_trend
        result = analyze_variance_trend("Carimas #1", days=3)
    assert result is None


def test_analyze_variance_trend_detects_pattern():
    """Returns insight when multiple high-variance entries found."""
    mock_rows = [
        {"date": "2026-02-22", "reg": "Reg 1", "gross": 1000.0, "variance": -10.0, "store": "Carimas #1"},
        {"date": "2026-02-21", "reg": "Reg 1", "gross": 900.0, "variance": -8.0, "store": "Carimas #1"},
    ]
    mock_result = MagicMock()
    mock_result.data = mock_rows
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = mock_result

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Alerta: Caja 1 muestra varianza alta por 2 días consecutivos.")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("ai_assistant.extensions") as mock_ext:
        mock_ext.get_db.return_value = mock_db
        with patch("ai_assistant.anthropic.Anthropic", return_value=mock_client):
            from ai_assistant import analyze_variance_trend
            result = analyze_variance_trend("Carimas #1", days=3)

    assert result is not None
    assert "varianza" in result.lower() or "alerta" in result.lower()


# ── AI_CHAT state transitions in telegram_bot ────────────────────────────────

def test_preguntar_ai_button_enters_ai_chat():
    """Tapping 'Preguntar AI' button transitions to AI_CHAT."""
    from telegram_bot import handle_update, bot_state, MESSAGES
    bot_state.clear()
    bot_state[800] = {"state": "REGISTERED", "store": "Carimas #1", "username": "maria", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(800, MESSAGES["es"]["btn_ask_ai"]))

    assert bot_state[800]["state"] == "AI_CHAT"
    assert any("asistente ai" in r.lower() or "modo" in r.lower() for r in replies)


def test_cancel_button_exits_ai_chat():
    """Tapping 'Cancelar' button from AI_CHAT returns to REGISTERED."""
    from telegram_bot import handle_update, bot_state, MESSAGES
    bot_state.clear()
    bot_state[801] = {"state": "AI_CHAT", "store": "Carimas #1", "username": "maria", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(801, MESSAGES["es"]["btn_cancel"]))

    assert bot_state[801]["state"] == "REGISTERED"
    assert any("desactivado" in r.lower() for r in replies)


def test_slash_cancel_exits_ai_chat():
    """/cancel from AI_CHAT returns to REGISTERED."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[802] = {"state": "AI_CHAT", "store": "Carimas #1", "username": "maria", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        handle_update(make_text_update(802, "/cancel"))

    assert bot_state[802]["state"] == "REGISTERED"


def test_ai_chat_routes_text_to_ai():
    """Text in AI_CHAT state calls ask_ai and returns response."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[803] = {"state": "AI_CHAT", "store": "Carimas #1", "username": "maria", "retry_count": 0}
    replies = []

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.ask_ai", return_value="El bruto fue $1,200.00"):
            with patch("telegram_bot.get_bot_user", return_value={"role": "staff"}):
                handle_update(make_text_update(803, "cuanto fue el bruto?"))

    assert bot_state[803]["state"] == "AI_CHAT"  # stays in AI_CHAT
    assert any("1,200" in r for r in replies)


def test_photo_in_ai_chat_still_triggers_ocr():
    """Photos sent while in AI_CHAT state still go through OCR flow."""
    from telegram_bot import handle_update, bot_state
    bot_state.clear()
    bot_state[804] = {"state": "AI_CHAT", "store": "Carimas #1", "username": "pedro", "retry_count": 0}
    replies = []
    good_ocr = {
        "register": 2, "date": "2026-02-22",
        "cash": 100.0, "ath": 50.0, "athm": 0.0, "visa": 25.0,
        "mc": 0.0, "amex": 0.0, "disc": 0.0, "wic": 0.0, "mcs": 0.0,
        "sss": 0.0, "variance": -1.5,
    }

    with patch("telegram_bot.send_message", side_effect=lambda cid, txt, **kw: replies.append(txt)):
        with patch("telegram_bot.download_photo", return_value=b"fake_bytes"):
            with patch("telegram_bot.extract_z_report", return_value=good_ocr):
                with patch("ocr.has_null_fields", return_value=False):
                    handle_update(make_photo_update(804))

    assert bot_state[804]["state"] == "AWAITING_DATE"
    assert any("fecha" in r.lower() for r in replies)


# ── ask_ai with history test ─────────────────────────────────────────────────

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
    # Should have: context msg + ack + 2 history + new question = 5 messages
    assert len(messages) >= 5
