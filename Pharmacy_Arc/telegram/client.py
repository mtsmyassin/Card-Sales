"""Telegram Bot API transport — low-level HTTP calls and message helpers."""

import logging
import os
import threading
import time

import requests as http

logger = logging.getLogger(__name__)


class TelegramAPIError(Exception):
    """Raised when all retries to the Telegram Bot API are exhausted."""

    def __init__(self, method: str, error: str, attempts: int):
        self.method = method
        self.error = error
        self.attempts = attempts
        super().__init__(f"Telegram API {method} failed after {attempts} attempt(s): {error}")


_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not _BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN is not set — Telegram bot will refuse all requests")


def _token() -> str:
    if not _BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set — add it to Railway Variables")
    return _BOT_TOKEN


def _tg(method: str, *, retries: int = 2, **kwargs) -> dict:
    """Call a Telegram Bot API method with retry and validation."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = http.post(
                f"https://api.telegram.org/bot{_token()}/{method}",
                json=kwargs,
                timeout=15,
            )
            data = resp.json()
            if not data.get("ok"):
                raise TelegramAPIError(method, data.get("description", "unknown error"), attempt)
            return data.get("result", data)
        except TelegramAPIError:
            raise  # don't retry Telegram-level errors (bad params, expired queries)
        except Exception as e:
            last_error = e
            logger.warning(f"_tg({method}) attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(1)
    raise TelegramAPIError(method, str(last_error), retries)


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    kwargs = {"chat_id": chat_id, "text": text}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    _tg("sendMessage", **kwargs)


def send_message_safe(chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Send a message, swallowing any exception. Returns True on success."""
    try:
        send_message(chat_id, text, reply_markup)
        return True
    except Exception as e:
        logger.error(f"send_message_safe({chat_id}) failed: {e}")
        return False


def _log_dead_letter(telegram_id: int, callback_data: str, error: Exception) -> None:
    """Log a structured dead-letter entry for failed callback processing."""
    logger.error(
        f"DEAD_LETTER | telegram_id={telegram_id} | data={callback_data} | "
        f"error_type={type(error).__name__} | error={error}"
    )


_ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0"))
_admin_last_notified: float = 0.0
_ADMIN_NOTIFY_COOLDOWN = 300  # seconds — max 1 alert per 5 minutes
_admin_notify_lock = threading.Lock()


def _notify_admin_if_needed(telegram_id: int, error_type: str, error_msg: str) -> None:
    """Send an error alert to the admin chat, rate-limited to avoid spam."""
    global _admin_last_notified
    if not _ADMIN_CHAT_ID:
        return
    now = time.time()
    with _admin_notify_lock:
        if now - _admin_last_notified < _ADMIN_NOTIFY_COOLDOWN:
            return
        _admin_last_notified = now
    text = f"Bot error alert\nUser: {telegram_id}\nError: {error_type}\nDetail: {error_msg[:200]}"
    send_message_safe(_ADMIN_CHAT_ID, text)


def download_photo(file_id: str) -> bytes:
    """Download a photo from Telegram by file_id, return raw bytes."""
    info = _tg("getFile", file_id=file_id)
    file_path = info["file_path"]
    url = f"https://api.telegram.org/file/bot{_token()}/{file_path}"
    resp = http.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content
