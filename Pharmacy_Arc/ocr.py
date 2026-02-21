"""OCR extraction for pharmacy Z Reports using Claude Vision API."""
import os
import json
import base64
import anthropic

NUMERIC_FIELDS = ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss", "variance"]

EXTRACTION_PROMPT = """You are extracting data from a Puerto Rico pharmacy cash register Z Report.

REPORT STRUCTURE — READ THIS CAREFULLY:
The payment section appears THREE times in the report:
  Block 1: every row ends with (shift)
  Block 2: every row ends with (close)   ← EXTRACT FROM THIS BLOCK ONLY
  Block 3: every row ends with (even)
Ignore blocks 1 and 3 entirely.

HEADER FIELDS:
- "Register #" line → register number (small integer 1–15). Do NOT use Batch #.
- "Report Date" line → date in header (format M/D/YYYY or M/DD/YYYY) → return as YYYY-MM-DD.

NEGATIVE VALUES:
- Values in parentheses are negative: ($19.31) → -19.31
- Over / Short is in the SUMMARY section (before the payment blocks). Negative = cash short.

FIELD MAPPING — (close) block only:
  CASH             → cash
  ATH              → ath        (NOT ATH MOVIL)
  ATH MOVIL        → athm
  VISA             → visa       (NOT MASTER CARD/ VISA)
  MASTER CARD      → mc         (NOT MASTER CARD/ VISA — that row → ignore, add to 0.0)
  AMERICAN EXPRESS → amex
  DISCOVER         → disc       (if DISCOVER appears twice, sum both)
  EBT FOOD         → wic
  MCS OTC          → mcs
  TRIPLE-S OTC     → sss        (any capitalisation)

IGNORE these rows entirely (return 0.0 for their fields):
  MASTER CARD/ VISA, TARJETAS, TARJETA DE FAMILI, EBT (non-food),
  EBT CASH, GIFT CARD, CHEQUE, ATH MOVIL duplicate rows

NUMERIC RULES:
- Strip $ signs, commas, and spaces before returning floats.
- Absent payment type → 0.0 (not null).
- Return null ONLY if a value is present in the (close) block but truly illegible.

Return ONLY this JSON, no explanation, no markdown:
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
        max_tokens=1024,
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

    # Extract JSON object — handles preamble text, code fences, or bare JSON
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]

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
