"""
APScheduler integration for EOD reminder job.
init_scheduler(app) is called by the app factory.
The scheduler is stored as app._scheduler for gunicorn.conf.py post_fork hook.
"""
import atexit
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _send_eod_reminders() -> None:
    """Send 9 PM reminder to bot users whose store hasn't submitted today."""
    try:
        from zoneinfo import ZoneInfo
        import extensions  # deferred — extensions is populated by the factory at startup
        pr_tz = ZoneInfo("America/Puerto_Rico")
        today = datetime.now(pr_tz).strftime("%Y-%m-%d")
        _db = extensions.get_db()
        if _db is None:
            logger.warning("_send_eod_reminders: DB unavailable at reminder time (%s) — skipping", today)
            return
        from helpers.supabase_types import rows
        subs = _db.table("audits").select("store").eq("date", today).execute()
        submitted_stores = {s["store"] for s in rows(subs)}
        bot_users = rows(_db.table("bot_users").select("telegram_id, store").execute())
        if not bot_users:
            return
        from telegram_bot import send_message
        notified = set()
        failed = []
        for bu in bot_users:
            store = bu.get("store", "")
            tid = bu["telegram_id"]
            if store in ("All", "") or tid in notified:
                continue
            if store not in submitted_stores:
                try:
                    send_message(
                        tid,
                        f"⏰ Recordatorio: {store} no ha enviado el Reporte Z de hoy ({today}).\n"
                        f"Envía una foto del Reporte Z para registrarlo."
                    )
                    notified.add(tid)
                except Exception as exc:
                    logger.error("EOD reminder failed store=%s tid=%s: %s", store, tid, exc)
                    failed.append(store)
        logger.info("EOD reminders: sent=%d failed=%d for %s", len(notified), len(failed), today)
        if failed:
            logger.warning("EOD reminder failures for stores: %s", failed)
    except Exception as e:
        logger.warning(f"_send_eod_reminders failed: {e}")


def _daily_ai_insights() -> None:
    """Run AI variance analysis for each store and alert admins/managers."""
    try:
        import extensions
        from telegram_bot import send_message
        from ai_assistant import analyze_variance_trend
        from config import Config

        _db = extensions.get_db()
        if _db is None:
            logger.warning("_daily_ai_insights: DB unavailable — skipping")
            return

        from helpers.supabase_types import rows as _rows
        bot_users = _rows(_db.table("bot_users").select("telegram_id, store").execute())
        if not bot_users:
            return

        # Build map: store → list of admin telegram IDs to notify
        store_admins: dict[str, list[int]] = {}
        for bu in bot_users:
            store = bu.get("store", "")
            tid = bu["telegram_id"]
            if store in ("", ):
                continue
            store_admins.setdefault(store, []).append(tid)

        # "All" store users get insights for every store
        all_store_users = [bu["telegram_id"] for bu in bot_users
                          if bu.get("store") == "All"]

        notified = 0
        for store in Config.STORES:
            try:
                insight = analyze_variance_trend(store, days=3)
                if not insight:
                    continue
                # Notify store-specific users + "All" users
                targets = set(store_admins.get(store, []) + all_store_users)
                for tid in targets:
                    try:
                        send_message(tid, f"📊 Alerta AI — {store}:\n{insight}")
                        notified += 1
                    except Exception as exc:
                        logger.error("AI insight send failed tid=%s: %s", tid, exc)
            except Exception as exc:
                logger.error("AI insight analysis failed store=%s: %s", store, exc)

        logger.info("Daily AI insights: %d notifications sent", notified)
    except Exception as e:
        logger.warning(f"_daily_ai_insights failed: {e}")


def _audit_integrity_check() -> None:
    """Weekly integrity check of the audit log hash chain."""
    try:
        from audit_log import get_audit_logger
        al = get_audit_logger()
        is_valid, errors = al.verify_integrity()
        if not is_valid:
            logger.error("AUDIT INTEGRITY FAILED: %s", errors)
        else:
            logger.info("Audit log integrity check passed")
    except Exception as e:
        logger.error("Audit integrity check error: %s", e)


def init_scheduler(app) -> None:
    """Start APScheduler in the current process. Stores instance as app._scheduler."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _send_eod_reminders,
            CronTrigger(hour=21, minute=0, timezone="America/Puerto_Rico"),
            id="eod_reminder",
            replace_existing=True,
            misfire_grace_time=300,
        )
        scheduler.add_job(
            _daily_ai_insights,
            CronTrigger(hour=22, minute=0, timezone="America/Puerto_Rico"),
            id="daily_ai_insights",
            replace_existing=True,
            misfire_grace_time=300,
        )
        scheduler.add_job(
            _audit_integrity_check,
            CronTrigger(day_of_week='sun', hour=6, minute=0, timezone="America/Puerto_Rico"),
            id="audit_integrity_check",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))
        app._scheduler = scheduler  # referenced by gunicorn.conf.py post_fork
        logger.info("APScheduler started: EOD reminder at 21:00, AI insights at 22:00 PR time")
    except ImportError:
        logger.warning("APScheduler not installed — EOD reminders disabled")
    except Exception as exc:
        logger.warning(f"APScheduler start failed: {exc}")
