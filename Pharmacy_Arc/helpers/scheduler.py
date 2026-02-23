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
            return
        subs = _db.table("audits").select("store").eq("date", today).execute()
        submitted_stores = {s["store"] for s in (subs.data or [])}
        bot_users_resp = _db.table("bot_users").select("telegram_id, store").execute()
        if not bot_users_resp.data:
            return
        from telegram_bot import send_message
        notified = set()
        failed = []
        for bu in bot_users_resp.data:
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
        )
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))
        app._scheduler = scheduler  # referenced by gunicorn.conf.py post_fork
        logger.info("APScheduler started: EOD reminder at 21:00 PR time")
    except ImportError:
        logger.warning("APScheduler not installed — EOD reminders disabled")
    except Exception as exc:
        logger.warning(f"APScheduler start failed: {exc}")
