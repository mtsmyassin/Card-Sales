"""
AI Assistant module for Carimas Telegram bot.
Provides natural-language querying of sales data and variance analysis.
Uses Google Gemini via REST API (no SDK dependencies).
"""
import os
import logging
from datetime import datetime, timedelta, timezone

from gemini_client import generate_text

import extensions
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the AI assistant for Farmacia Carimas. You are concise and professional. "
    "Your job is to help pharmacy staff understand their sales data (Z-Reports), "
    "detect variance anomalies, and answer operational questions.\n\n"
    "Language rule:\n"
    "- Reply in the SAME language the user writes in. "
    "If they write in Spanish, reply in Spanish. If they write in English, reply in English.\n\n"
    "Rules:\n"
    "- Be brief (max 3-4 sentences per response).\n"
    "- If you don't have enough data, say so clearly.\n"
    "- Use currency format with $ and two decimals.\n"
    "- Negative variance = cash short (faltante). Positive = overage (sobrante).\n"
    "- Never make up data. Only use the information provided.\n"
)

PHARMACY_CONTEXT = (
    "\n\n--- Farmacia Carimas Operational Info ---\n"
    "Stores:\n"
    "  Carimas #1 — [ADDRESS] — Tel: [PHONE] — Hours: M-S 8AM-9PM, Sun 9AM-5PM\n"
    "  Carimas #2 — [ADDRESS] — Tel: [PHONE] — Hours: M-S 8AM-9PM, Sun 9AM-5PM\n"
    "  Carimas #3 — [ADDRESS] — Tel: [PHONE] — Hours: M-S 8AM-9PM, Sun 9AM-5PM\n"
    "  Carimas #4 — [ADDRESS] — Tel: [PHONE] — Hours: M-S 8AM-9PM, Sun 9AM-5PM\n"
    "  Carthage   — [ADDRESS] — Tel: [PHONE] — Hours: M-S 8AM-9PM, Sun 9AM-5PM\n\n"
    "Procedures:\n"
    "  - Z-Report: Print at register close, take photo, send via Telegram.\n"
    "  - Payouts: Record all cash disbursements (change, payments, etc.) before close.\n"
    "  - Variance: Difference between expected and counted cash. Negative = short.\n"
    "  - If variance exceeds $5.00, report to supervisor immediately.\n\n"
    "Contacts:\n"
    "  - Tech support: [NAME] — [PHONE/EMAIL]\n"
    "  - General management: [NAME] — [PHONE]\n\n"
    "Use this info to answer operational questions.\n"
    "If the user asks about something not covered here or in the sales data, say so clearly.\n"
)


def _fetch_store_context(store: str, days: int = 7) -> dict:
    """Query recent audits for a store and return a summary dict.

    Returns dict with keys: entries (list of dicts), total_gross, avg_variance,
    registers (set of register IDs), day_count.
    """
    db = extensions.get_db()
    if db is None:
        return {"entries": [], "total_gross": 0, "avg_variance": 0,
                "registers": [], "day_count": 0}

    try:
        from zoneinfo import ZoneInfo
        pr_tz = ZoneInfo("America/Puerto_Rico")
        today = datetime.now(pr_tz).date()
    except Exception:
        today = datetime.now(timezone.utc).date()

    since = (today - timedelta(days=days)).isoformat()

    try:
        result = db.table("audits").select(
            "date, reg, gross, variance, store"
        ).eq("store", store).is_("deleted_at", "null").gte("date", since).order(
            "date", desc=True
        ).execute()
        from helpers.supabase_types import rows as _rows
        rows = _rows(result)
    except Exception as e:
        logger.warning(f"_fetch_store_context query failed: {e}")
        rows = []

    total_gross = sum(r.get("gross", 0) or 0 for r in rows)
    variances = [r.get("variance", 0) or 0 for r in rows]
    avg_var = sum(variances) / len(variances) if variances else 0
    registers = list({r.get("reg", "") for r in rows})

    return {
        "entries": rows,
        "total_gross": round(total_gross, 2),
        "avg_variance": round(avg_var, 2),
        "registers": registers,
        "day_count": len({r.get("date") for r in rows}),
    }


def ask_ai(question: str, store: str, role: str, username: str,
           history: list[dict] | None = None) -> str:
    """Send a question to Gemini with store context and return the response.

    Args:
        question: The user's question text.
        store: Store name (e.g. "Carimas #1").
        role: User role (e.g. "staff", "admin").
        username: The user's username.
        history: Optional list of previous {"role": ..., "content": ...} messages
                 for multi-turn conversation. Capped at last 10 messages (5 pairs).
    """
    context = _fetch_store_context(store)

    context_block = (
        f"User: {username} | Role: {role} | Store: {store}\n"
        f"Last 7 days: {context['day_count']} days with reports, "
        f"{len(context['entries'])} entries.\n"
        f"Total gross: ${context['total_gross']:.2f} | "
        f"Avg variance: ${context['avg_variance']:.2f}\n"
        f"Active registers: {', '.join(context['registers']) or 'none'}\n\n"
        f"Recent entries:\n"
    )
    for entry in context["entries"][:15]:  # cap to keep tokens low
        context_block += (
            f"  {entry.get('date')} | {entry.get('reg')} | "
            f"Gross: ${entry.get('gross', 0):.2f} | "
            f"Variance: ${entry.get('variance', 0):.2f}\n"
        )

    # Build Gemini contents: context as first user message, then history, then question
    contents = [
        {"role": "user", "parts": [{"text": context_block + "\n(Data context — not a question.)"}]},
        {"role": "model", "parts": [{"text": "Got it. I have the data context ready."}]},
    ]
    if history:
        for msg_item in history[-10:]:  # cap at last 10 messages (5 pairs)
            gemini_role = "model" if msg_item["role"] == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": msg_item["content"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})

    try:
        text = generate_text(
            model=Config.AI_ASSISTANT_MODEL,
            contents=contents,
            system_instruction=SYSTEM_PROMPT + PHARMACY_CONTEXT,
            max_output_tokens=Config.AI_MAX_TOKENS,
            timeout=30,
        )
        return text.strip()
    except Exception as e:
        logger.error(f"ask_ai failed: {e}")
        return "Sorry, an error occurred processing your question. Please try again. / Lo siento, ocurrió un error. Intenta de nuevo."


def analyze_variance_trend(store: str, days: int = 3) -> str | None:
    """Check if variance is trending badly for a store.

    Returns an insight string if a concerning pattern is found, None otherwise.
    """
    context = _fetch_store_context(store, days=days)
    entries = context["entries"]
    if len(entries) < 2:
        return None

    threshold = Config.VARIANCE_ALERT_THRESHOLD
    high_variance = [
        e for e in entries
        if abs(e.get("variance", 0) or 0) > threshold
    ]

    if len(high_variance) < 2:
        return None

    # Build a mini-prompt for AI analysis
    detail = "\n".join(
        f"  {e.get('date')} {e.get('reg')}: variance ${e.get('variance', 0):.2f}"
        for e in high_variance
    )
    prompt = (
        f"Store: {store}\n"
        f"The following entries have high variance (threshold ${threshold:.2f}):\n"
        f"{detail}\n\n"
        f"Generate a brief alert (2-3 sentences) for the administrator "
        f"explaining the pattern and suggesting action. "
        f"Write in Spanish."
    )

    try:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        text = generate_text(
            model=Config.AI_ASSISTANT_MODEL,
            contents=contents,
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=200,
            timeout=30,
        )
        return text.strip()
    except Exception as e:
        logger.error(f"analyze_variance_trend failed for {store}: {e}")
        return None
