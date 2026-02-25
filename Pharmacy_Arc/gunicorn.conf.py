"""
Gunicorn configuration for Farmacia Carimas.

--preload loads the app in the master process before forking workers.
The APScheduler (EOD reminders) starts in the master, so post_fork shuts
it down in every worker to prevent N duplicate reminder sends per tick.
"""

import logging
import os

workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "sync"
timeout = 30
preload_app = True
max_requests = 1000
max_requests_jitter = 50

log = logging.getLogger("gunicorn.error")


def post_fork(server, worker):
    """Shut down APScheduler in forked workers — only the master runs it."""
    try:
        import app as _app

        flask_app = getattr(_app, "app", None)  # the Flask app instance
        scheduler = getattr(flask_app, "_scheduler", None)
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
            log.info("APScheduler shut down in worker pid=%s (master handles scheduling)", worker.pid)
        elif scheduler is None:
            log.warning(
                "post_fork: no _scheduler attribute found on app — scheduler may run in worker pid=%s", worker.pid
            )
    except ImportError as exc:
        log.error("post_fork: cannot import app module: %s", exc)
    except Exception as exc:
        log.warning("post_fork: could not shut down scheduler: %s", exc)
