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
