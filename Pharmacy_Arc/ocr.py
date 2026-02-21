"""OCR extraction for pharmacy Z Reports using Claude Vision API."""
import os
import json
import base64
import anthropic

NUMERIC_FIELDS = ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss", "variance"]

EXTRACTION_PROMPT = """You are extracting data from a Puerto Rico pharmacy cash register Z Report (end-of-day batch close printout).

CRITICAL RULES:
1. Extract values ONLY from the (close) column. Ignore (shift) and (even) columns entirely.
2. The report has three numeric columns per row — always take the LAST (rightmost) value on each line, which is the close total.
3. All monetary values are floats. Strip any $ signs or commas before returning.
4. Register number is a small integer (1–15) found in the report header, e.g. "Register: 3" or "Reg #3".
5. Date is in the header labeled "Report Date" — return as YYYY-MM-DD.
6. Over/Short (variance): negative = cash short, positive = cash over.
7. If a payment type is genuinely absent from this report (not just illegible), return 0.0 — not null.
8. Return null ONLY if the value is present but you cannot read it clearly.

Field mapping (label on receipt → JSON key):
  CASH             → cash
  ATH              → ath
  ATH MOVIL        → athm
  VISA             → visa
  MASTER CARD      → mc
  AMERICAN EXPRESS → amex
  DISCOVER         → disc
  EBT FOOD         → wic
  MCS OTC          → mcs
  TRIPLE-S OTC     → sss
  Over / Short     → variance

Return ONLY this JSON object, no explanation, no markdown:
{
  "register": <int>,
  "date": "<YYYY-MM-DD>",
  "cash": <float>,
  "ath": <float>,
  "athm": <float>,
  "visa": <float>,
  "mc": <float>,
  "amex": <float>,
  "disc": <float>,
  "wic": <float>,
  "mcs": <float>,
  "sss": <float>,
  "variance": <float>
}"""


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
        model="claude-sonnet-4-6",
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
