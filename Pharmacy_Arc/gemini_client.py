"""Lightweight Gemini API client using REST (no SDK dependencies)."""

import logging
import os

import requests as http

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _api_key() -> str:
    return os.getenv("GOOGLE_API_KEY", "")


def generate_text(
    model: str, contents: list, system_instruction: str = "", max_output_tokens: int = 500, timeout: int = 30
) -> str:
    """Call Gemini generateContent REST API and return the text response.

    Args:
        model: Model name (e.g. 'gemini-2.5-flash', 'gemini-3-pro-preview').
        contents: List of message dicts with 'role' and 'parts' keys.
        system_instruction: Optional system prompt.
        max_output_tokens: Max tokens in the response.
        timeout: HTTP timeout in seconds.

    Returns:
        The generated text string.

    Raises:
        RuntimeError: If the API call fails or returns no text.
    """
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={_api_key()}"

    body = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
        },
    }
    if system_instruction:
        body["system_instruction"] = {
            "parts": [{"text": system_instruction}],
        }

    resp = http.post(url, json=body, timeout=timeout)
    if not resp.ok:
        raise RuntimeError(f"Gemini API {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {data}")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"Gemini returned empty parts: {candidates[0]}")

    return parts[0].get("text", "")


def generate_with_image(
    model: str, image_b64: str, mime_type: str, prompt: str, max_output_tokens: int = 1024, timeout: int = 30
) -> str:
    """Call Gemini generateContent with an image + text prompt.

    Args:
        model: Model name (e.g. 'gemini-3-pro-preview').
        image_b64: Base64-encoded image data.
        mime_type: Image MIME type (e.g. 'image/jpeg').
        prompt: Text prompt to accompany the image.
        max_output_tokens: Max tokens in the response.
        timeout: HTTP timeout in seconds.

    Returns:
        The generated text string.
    """
    contents = [
        {
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                {"text": prompt},
            ],
        }
    ]
    return generate_text(model, contents, max_output_tokens=max_output_tokens, timeout=timeout)
