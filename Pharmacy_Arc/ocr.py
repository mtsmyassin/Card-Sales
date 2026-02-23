"""OCR extraction for pharmacy Z Reports using Claude Vision API."""
import os
import json
import base64
import anthropic
from config import Config

NUMERIC_FIELDS = ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss", "variance"]

EXTRACTION_PROMPT = """You are extracting data from a Puerto Rico pharmacy cash register Z Report (Farmacia Carimas).

REPORT STRUCTURE — READ THIS CAREFULLY:
The payment section appears in blocks, each row ending with the block name in parentheses.
Blocks present vary by register — either 3 or 4 blocks:
  3-block format:  (shift) | (close) | (even)
  4-block format:  (open)  | (shift) | (close) | (even)  or  (short)

EXTRACT ONLY FROM THE (close) BLOCK.
Ignore (open), (shift), (even), and (short) blocks entirely.
If the (close) block is all $0.00, that is valid — return 0.0 for those fields, do NOT fall back to shift.

HEADER FIELDS:
- "Register #" line → register number (small integer 1–15). It is on its own labeled line. Do NOT use Batch #.
- "Report Date" line → date format is M/DD/YYYY (e.g. 2/19/2026) → return as YYYY-MM-DD (e.g. 2026-02-19).
  IMPORTANT: The digit before the first "/" is the MONTH (1–12). Cross-check it against the "Start Date"
  and "Date" fields also in the header — they must all share the same month.
  This pharmacy's thermal printer sometimes prints "2" with a font that resembles "7". If the month
  digit could be read as either 2 or 7, and the Start Date is exactly 1 day before the Report Date,
  prefer 2 (February) over 7 (July) when the year is 2026.

NEGATIVE VALUES:
- Values in parentheses are negative: ($19.31) → -19.31
- Over / Short is in the SUMMARY section (above the payment blocks). Negative = cash short.

FIELD MAPPING — (close) block only:
  CASH             → cash
  ATH              → ath        (NOT ATH MOVIL)
  ATH MOVIL        → athm
  VISA             → visa       (NOT MASTER CARD/ VISA)
  MASTER CARD      → mc         (NOT MASTER CARD/ VISA)
  AMERICAN EXPRESS → amex
  DISCOVER         → disc       (if DISCOVER appears twice, sum both values)
  EBT FOOD         → wic
  MCS OTC          → mcs
  TRIPLE-S OTC     → sss        (any capitalisation: Triple-S OTC, TRIPLE-S OTC)

IGNORE these rows (treat as 0.0, do not add to any field):
  MASTER CARD/ VISA, TARJETAS, TARJETA DE FAMILI, TARJETA DE FAMIL,
  EBT (non-food/non-FOOD label), EBT CASH, GIFT CARD, CHEQUE,
  duplicate ATH MOVIL rows

NUMERIC RULES:
- Strip $ signs, commas, and spaces before returning floats.
- Absent payment type → 0.0 (not null).
- Return null ONLY if a value is present in the (close) block but truly illegible.

Return ONLY this JSON object — no explanation, no markdown, no reasoning text:
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
        model=Config.AI_MODEL,
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
