"""Tests for OCR extraction module."""
import json
import pytest
from unittest.mock import patch, MagicMock


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
    with patch("ocr.generate_with_image", return_value=json.dumps(GOOD_OCR_RESULT)):
        result = extract_z_report(b"fake_image_bytes")
    assert isinstance(result, dict)
    assert result["cash"] == 356.85
    assert result["ath"] == 434.89
    assert result["date"] == "2026-07-13"
    assert result["register"] == 3


def test_extract_z_report_handles_markdown_code_block():
    """Gemini sometimes wraps JSON in ```json ... ``` — must strip it."""
    from ocr import extract_z_report
    wrapped = "```json\n" + json.dumps(GOOD_OCR_RESULT) + "\n```"
    with patch("ocr.generate_with_image", return_value=wrapped):
        result = extract_z_report(b"fake_image_bytes")
    assert result["cash"] == 356.85


def test_has_null_fields_detects_missing():
    from ocr import has_null_fields, null_field_names
    assert has_null_fields(PARTIAL_OCR_RESULT) is True
    assert "ath" in null_field_names(PARTIAL_OCR_RESULT)
    assert "visa" in null_field_names(PARTIAL_OCR_RESULT)


def test_has_null_fields_clean_record():
    from ocr import has_null_fields
    assert has_null_fields(GOOD_OCR_RESULT) is False


def test_extract_z_report_raises_on_bad_json():
    from ocr import extract_z_report, OCRParseError
    with patch("ocr.generate_with_image", return_value="Sorry, I cannot read this image."):
        with pytest.raises(OCRParseError):
            extract_z_report(b"fake_image_bytes")
