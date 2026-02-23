"""Database retry helper for transient Supabase failures."""
import time
import logging

logger = logging.getLogger(__name__)


def db_retry(operation, label="db_call", max_attempts=3, backoff_factor=2):
    """Execute a Supabase operation with exponential backoff retry.

    Args:
        operation: callable that performs the DB operation
        label: human-readable label for log messages
        max_attempts: max retries before raising
        backoff_factor: base for exponential wait (1s, 2s, 4s, ...)

    Returns:
        The result of operation()

    Raises:
        The last exception if all attempts fail
    """
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                wait = backoff_factor ** (attempt - 1)
                logger.warning(
                    "%s failed (attempt %d/%d): %s — retrying in %ds",
                    label, attempt, max_attempts, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error("%s failed after %d attempts: %s", label, max_attempts, e)
    raise last_err
