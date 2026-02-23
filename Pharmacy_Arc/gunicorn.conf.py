"""
Gunicorn configuration for Farmacia Carimas.

--preload loads the app in the master process before forking workers.
The APScheduler (EOD reminders) starts in the master, so post_fork shuts
it down in every worker to prevent N duplicate reminder sends per tick.
"""
import logging

workers = 1
worker_class = "sync"
timeout = 120
preload_app = True

log = logging.getLogger("gunicorn.error")


def post_fork(server, worker):
    """Shut down APScheduler in forked workers — only the master runs it."""
    try:
        import app as _app
        flask_app = getattr(_app, 'app', None)       # the Flask app instance
        scheduler = getattr(flask_app, '_scheduler', None)
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
            log.info("APScheduler shut down in worker pid=%s (master handles scheduling)", worker.pid)
    except Exception as exc:
        log.warning("post_fork: could not shut down scheduler: %s", exc)
