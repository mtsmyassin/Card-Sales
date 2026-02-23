"""
AI Assistant module for Carimas Telegram bot.
Provides natural-language querying of sales data and variance analysis.
"""
import os
import logging
from datetime import datetime, timedelta

import anthropic

import extensions
from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Eres el asistente de IA de Farmacia Carimas. Respondes en español, "
    "de forma concisa y profesional. Tu trabajo es ayudar al personal de la farmacia "
    "a entender sus datos de ventas (Reportes Z), detectar anomalías en varianzas, "
    "y responder preguntas operativas.\n\n"
    "Reglas:\n"
    "- Responde siempre en español.\n"
    "- Sé breve (máximo 3-4 oraciones por respuesta).\n"
    "- Si no tienes datos suficientes, dilo claramente.\n"
    "- Usa formato de moneda con $ y dos decimales.\n"
    "- Varianza negativa = efectivo corto (faltante). Positiva = sobrante.\n"
    "- No inventes datos. Solo usa la información proporcionada.\n"
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
        today = datetime.utcnow().date()

    since = (today - timedelta(days=days)).isoformat()

    try:
        result = db.table("audits").select(
            "date, reg, gross, variance, store"
        ).eq("store", store).gte("date", since).order(
            "date", desc=True
        ).execute()
        rows = result.data or []
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


def ask_ai(question: str, store: str, role: str, username: str) -> str:
    """Send a question to Claude with store context and return the response."""
    context = _fetch_store_context(store)

    context_block = (
        f"Usuario: {username} | Rol: {role} | Tienda: {store}\n"
        f"Datos últimos 7 días: {context['day_count']} días con reportes, "
        f"{len(context['entries'])} entradas.\n"
        f"Bruto total: ${context['total_gross']:.2f} | "
        f"Varianza promedio: ${context['avg_variance']:.2f}\n"
        f"Cajas activas: {', '.join(context['registers']) or 'ninguna'}\n\n"
        f"Detalle de entradas recientes:\n"
    )
    for entry in context["entries"][:15]:  # cap to keep tokens low
        context_block += (
            f"  {entry.get('date')} | {entry.get('reg')} | "
            f"Bruto: ${entry.get('gross', 0):.2f} | "
            f"Varianza: ${entry.get('variance', 0):.2f}\n"
        )

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model=Config.AI_MODEL,
            max_tokens=Config.AI_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"{context_block}\nPregunta: {question}",
            }],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"ask_ai failed: {e}")
        return "Lo siento, ocurrió un error al procesar tu pregunta. Intenta de nuevo."


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
        f"  {e.get('date')} {e.get('reg')}: varianza ${e.get('variance', 0):.2f}"
        for e in high_variance
    )
    prompt = (
        f"Tienda: {store}\n"
        f"Las siguientes entradas tienen varianza alta (umbral ${threshold:.2f}):\n"
        f"{detail}\n\n"
        f"Genera una alerta breve (2-3 oraciones) para el administrador "
        f"explicando el patrón y sugiriendo acción."
    )

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model=Config.AI_MODEL,
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"analyze_variance_trend failed for {store}: {e}")
        return None
