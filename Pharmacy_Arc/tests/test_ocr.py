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
