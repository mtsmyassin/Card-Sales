"""Bot update dispatcher, handlers, and keyboard builders."""

import logging
import os
import re
import threading
import time
import unicodedata
import uuid

import extensions
import requests as http
from ai_assistant import ask_ai
from config import Config
from helpers.supabase_types import rows
from ocr import OCRParseError, extract_z_report, has_null_fields, null_field_names

from telegram.client import (
    TelegramAPIError,
    _log_dead_letter,
    _notify_admin_if_needed,
    _tg,
    _token,
    download_photo,
    send_message,
    send_message_safe,
    send_photo,
    send_photo_safe,
)
from telegram.i18n import _STORE_CHOICE, KNOWN_STORES, MESSAGES, msg
from telegram.session import (
    _bot_state_lock,
    _set_state,
    bot_state,
    get_bot_user,
    is_registered,
    load_session,
    save_bot_user,
    verify_web_credentials,
)
from telegram.storage import (
    _format_register_id,
    save_audit_entry,
    save_photo_record,
    upload_image_to_storage,
)

logger = logging.getLogger(__name__)

BUTTON_TIMEOUT_SECONDS = 600  # 10 minutes

# AI conversation history
_ai_history: dict[int, list[dict]] = {}
_AI_HISTORY_MAX_AGE = 3600  # seconds
_ai_history_ts: dict[int, float] = {}
_ai_lock = threading.Lock()


def _is_button_expired(cb: dict) -> bool:
    """Check if the inline button's parent message is older than the timeout."""
    msg_date = cb.get("message", {}).get("date", 0)
    if msg_date == 0:
        return False
    return (time.time() - msg_date) > BUTTON_TIMEOUT_SECONDS


# ── Keyboard helpers ──────────────────────────────────────────────────────


def _kb_registered(tid: int) -> dict:
    return {
        "keyboard": [[msg(tid, "btn_ask_ai")]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def _kb_ai_chat(tid: int) -> dict:
    return {
        "keyboard": [[msg(tid, "btn_cancel")]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def _kb_remove() -> dict:
    return {"remove_keyboard": True}


def _inline_kb(buttons: list[list[dict]]) -> dict:
    return {"inline_keyboard": buttons}


def _inline_btn(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


INLINE_STORES = _inline_kb(
    [
        [_inline_btn(s, f"store:{i}") for i, s in enumerate(KNOWN_STORES, 1) if i <= 3],
        [_inline_btn(s, f"store:{i}") for i, s in enumerate(KNOWN_STORES, 1) if i > 3],
    ]
)


def _build_inline_confirm_date(tid: int) -> dict:
    return _inline_kb(
        [
            [_inline_btn(msg(tid, "btn_ok"), "date:ok"), _inline_btn(msg(tid, "btn_edit"), "date:edit")],
        ]
    )


def _build_inline_confirm_reg(tid: int) -> dict:
    return _inline_kb(
        [
            [_inline_btn(msg(tid, "btn_ok"), "reg:ok"), _inline_btn(msg(tid, "btn_edit"), "reg:edit")],
        ]
    )


def _build_inline_save(tid: int) -> dict:
    return _inline_kb(
        [
            [_inline_btn(msg(tid, "btn_save_yes"), "save:yes"), _inline_btn(msg(tid, "btn_save_no"), "save:no")],
        ]
    )


def _build_inline_payouts_zero(tid: int) -> dict:
    return _inline_kb(
        [
            [_inline_btn(msg(tid, "btn_no_payouts"), "payouts:0")],
        ]
    )


def _build_inline_skip_cash(tid: int) -> dict:
    return _inline_kb(
        [
            [_inline_btn(msg(tid, "btn_skip"), "actual_cash:skip")],
        ]
    )


def _build_inline_broadcast(tid: int) -> dict:
    return _inline_kb(
        [
            [_inline_btn(msg(tid, "btn_send"), "broadcast:yes"), _inline_btn(msg(tid, "btn_cancel"), "broadcast:no")],
        ]
    )


# ── Preview formatter ─────────────────────────────────────────────────────


def _format_preview(data: dict, telegram_id: int = 0) -> str:
    """Format OCR result as a bilingual confirmation message."""

    def fmt(v):
        return f"${v:.2f}" if v is not None else "?"

    header = msg(telegram_id, "preview_header")
    reg_line = msg(telegram_id, "preview_register", register=data.get("register", "?"), date=data.get("date", "?"))
    prompt = msg(telegram_id, "preview_save_prompt")

    return (
        f"{header}\n"
        f"{reg_line}\n"
        f"------------------------------\n"
        f"Efectivo:      {fmt(data.get('cash'))}\n"
        f"ATH:           {fmt(data.get('ath'))}\n"
        f"ATH Movil:     {fmt(data.get('athm'))}\n"
        f"VISA:          {fmt(data.get('visa'))}\n"
        f"Master Card:   {fmt(data.get('mc'))}\n"
        f"American Exp:  {fmt(data.get('amex'))}\n"
        f"Discover:      {fmt(data.get('disc'))}\n"
        f"WIC/EBT:       {fmt(data.get('wic'))}\n"
        f"MCS OTC:       {fmt(data.get('mcs'))}\n"
        f"Triple-S OTC:  {fmt(data.get('sss'))}\n"
        f"Sobre/Corto:   {fmt(data.get('variance'))}\n"
        f"------------------------------\n"
        f"{prompt}"
    )


# ── Utility ───────────────────────────────────────────────────────────────


def _ascii_upper(text: str) -> str:
    """Uppercase and strip accents so 'Si' == 'SI', etc."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper()


def _parse_date(text: str) -> str | None:
    """Accept MM/DD/YYYY, MM-DD-YYYY, or YYYY-MM-DD. Returns YYYY-MM-DD or None."""
    text = text.strip()
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return text
    return None


# ── State-specific handlers ──────────────────────────────────────────────


def _handle_ai_message(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle a text message while in AI_CHAT state."""
    store = state.get("store", "")
    username = state.get("username", "")
    user_row = get_bot_user(telegram_id)
    role = user_row.get("role", "staff") if user_row else "staff"

    now = time.time()
    with _ai_lock:
        stale = [tid for tid, ts in _ai_history_ts.items() if now - ts > _AI_HISTORY_MAX_AGE]
        for tid in stale:
            _ai_history.pop(tid, None)
            _ai_history_ts.pop(tid, None)
        _ai_history_ts[telegram_id] = now
        history = list(_ai_history.get(telegram_id, []))  # copy to avoid race

    try:
        response = ask_ai(text, store, role, username, history=history)
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        response = "Lo siento, ocurri\u00f3 un error. Intenta de nuevo."

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": response})
    with _ai_lock:
        _ai_history[telegram_id] = history[-10:]

    send_message(chat_id, response, reply_markup=_kb_ai_chat(telegram_id))


def _handle_payouts(telegram_id, chat_id, text, state):
    """Handle AWAITING_PAYOUTS — parse payout amount."""
    text = str(text).strip().replace("$", "").replace(",", "")
    try:
        payouts = float(text)
    except ValueError:
        send_message(chat_id, msg(telegram_id, "bad_amount"))
        return
    state["pending_payouts"] = round(payouts, 2)
    state["state"] = "AWAITING_ACTUAL_CASH"
    _set_state(telegram_id, state)
    send_message(chat_id, msg(telegram_id, "actual_cash"), reply_markup=_build_inline_skip_cash(telegram_id))


def _handle_actual_cash(telegram_id, chat_id, text, state):
    """Handle AWAITING_ACTUAL_CASH — parse cash amount or skip."""
    text_clean = str(text).strip()
    if text_clean.lower() in ("skip", "omitir"):
        state["pending_actual_cash"] = None
        state["pending_variance"] = None
    else:
        text_clean = text_clean.replace("$", "").replace(",", "")
        try:
            actual_cash = float(text_clean)
        except ValueError:
            send_message(chat_id, msg(telegram_id, "bad_amount"))
            return
        state["pending_actual_cash"] = round(actual_cash, 2)
        opening_float = Config.DEFAULT_OPENING_FLOAT
        ocr_cash = state.get("pending_data", {}).get("cash") or 0
        payouts = state.get("pending_payouts", 0)
        state["pending_variance"] = round((actual_cash - opening_float) - (ocr_cash - payouts), 2)

    state["state"] = "AWAITING_CONFIRMATION"
    _set_state(telegram_id, state)
    image_bytes = state.get("pending_image_bytes")
    if image_bytes:
        send_photo_safe(chat_id, image_bytes, caption=msg(telegram_id, "preview_header"))
    send_message(
        chat_id, _format_preview(state["pending_data"], telegram_id), reply_markup=_build_inline_save(telegram_id)
    )


def _handle_broadcast_confirm(telegram_id, chat_id, text, state):
    """Handle BROADCAST_CONFIRM — send or cancel the broadcast."""
    if _ascii_upper(str(text)) in ("YES", "SI", "S\u00cd"):
        broadcast_msg = state.get("pending_broadcast", "")
        sent, total = 0, 0
        try:
            db = extensions.get_db()
            if db is None:
                raise RuntimeError("DB unavailable")
            targets = rows(db.table("bot_users").select("telegram_id").execute())
            total = len(targets)
            for u in targets:
                tid = u["telegram_id"]
                if tid == telegram_id:
                    continue
                try:
                    send_message(tid, f"\U0001f4e2 {broadcast_msg}")
                    sent += 1
                except Exception as exc:
                    logger.error(f"Broadcast send failed tid={tid}: {exc}")
        except Exception as e:
            logger.error(f"Broadcast failed: {e}")
        new_state = {
            "state": "REGISTERED",
            "store": state.get("store"),
            "username": state.get("username"),
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        send_message(chat_id, msg(telegram_id, "broadcast_sent", sent=sent, total=total))
    else:
        new_state = {
            "state": "REGISTERED",
            "store": state.get("store"),
            "username": state.get("username"),
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        send_message(chat_id, msg(telegram_id, "broadcast_cancelled"))


def _handle_password(telegram_id, chat_id, tg_username, password, state):
    username = state.get("username", "")

    if extensions.login_tracker.is_locked_out(username):
        remaining = extensions.login_tracker.get_lockout_remaining(username)
        logger.warning(f"[BOT] Login blocked for locked-out account: {username!r}")
        state["state"] = "AWAITING_USERNAME"
        state.pop("username", None)
        _set_state(telegram_id, state)
        send_message(chat_id, f"Cuenta bloqueada por demasiados intentos. Intenta en {remaining}s.")
        return

    user_row = verify_web_credentials(username, password)
    if user_row is None:
        is_locked, remaining_attempts = extensions.login_tracker.record_failed_attempt(username)
        logger.warning(f"[BOT] Failed login for {username!r} (remaining: {remaining_attempts})")
        state["state"] = "AWAITING_USERNAME"
        state.pop("username", None)
        _set_state(telegram_id, state)
        if is_locked:
            lockout = extensions.login_tracker.get_lockout_remaining(username)
            send_message(chat_id, f"Demasiados intentos. Cuenta bloqueada por {lockout}s.")
        else:
            send_message(chat_id, msg(telegram_id, "bad_credentials"))
        return

    extensions.login_tracker.record_successful_login(username)
    save_bot_user(telegram_id, user_row["username"], tg_username, user_row["store"])
    new_state = {
        "state": "REGISTERED",
        "store": user_row["store"],
        "username": user_row["username"],
        "retry_count": 0,
    }
    _set_state(telegram_id, new_state)
    send_message(
        chat_id, msg(telegram_id, "registered", store=user_row["store"]), reply_markup=_kb_registered(telegram_id)
    )


def _handle_photo(telegram_id, chat_id, tg_username, photo_msg, state):
    if state.get("store") == "All":
        state["pending_photo_msg"] = photo_msg
        state["state"] = "AWAITING_STORE"
        _set_state(telegram_id, state)
        send_message(chat_id, msg(telegram_id, "store_prompt"), reply_markup=INLINE_STORES)
        return

    send_message(chat_id, msg(telegram_id, "processing"))
    file_id = photo_msg["photo"][-1]["file_id"]

    try:
        image_bytes = download_photo(file_id)
    except Exception as e:
        logger.error(f"Photo download failed: {e}")
        send_message(chat_id, msg(telegram_id, "photo_dl_error"))
        return

    _MAX_PHOTO_BYTES = 5 * 1024 * 1024
    if len(image_bytes) > _MAX_PHOTO_BYTES:
        logger.warning("Photo too large (%d bytes) from user %s", len(image_bytes), telegram_id)
        send_message(chat_id, msg(telegram_id, "photo_too_large"))
        return

    retry_count = state.get("retry_count", 0)

    try:
        ocr_data = extract_z_report(image_bytes)
    except OCRParseError as e:
        logger.warning(f"OCR parse error for user {telegram_id}: {e}")
        _handle_ocr_failure(telegram_id, chat_id, state, retry_count)
        return
    except Exception as e:
        logger.error(f"OCR unexpected error: {e}")
        send_message(chat_id, msg(telegram_id, "ocr_error"))
        return

    if has_null_fields(ocr_data):
        null_names = ", ".join(null_field_names(ocr_data))
        if retry_count >= 1:
            state["retry_count"] = 0
            _set_state(telegram_id, state)
            send_message(chat_id, msg(telegram_id, "null_final", fields=null_names))
            return
        state["retry_count"] = retry_count + 1
        _set_state(telegram_id, state)
        send_message(chat_id, msg(telegram_id, "null_retry", fields=null_names, attempt=retry_count + 1))
        return

    state["state"] = "AWAITING_DATE"
    state["pending_data"] = ocr_data
    state["pending_image_bytes"] = image_bytes
    state["retry_count"] = 0
    _set_state(telegram_id, state)
    ocr_date = ocr_data.get("date") or "desconocida"
    send_message(
        chat_id, msg(telegram_id, "ocr_date", date=ocr_date), reply_markup=_build_inline_confirm_date(telegram_id)
    )


def _handle_ocr_failure(telegram_id, chat_id, state, retry_count):
    if retry_count >= 1:
        state.pop("pending_image_bytes", None)
        state["retry_count"] = 0
        _set_state(telegram_id, state)
        send_message(chat_id, msg(telegram_id, "ocr_fail_final"))
    else:
        state["retry_count"] = retry_count + 1
        _set_state(telegram_id, state)
        send_message(chat_id, msg(telegram_id, "ocr_fail_retry", attempt=retry_count + 1))


def _handle_date(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle AWAITING_DATE — confirm or override OCR date."""
    if _ascii_upper(text) in ("OK", "YES", "SI", "S\u00cd", "CONFIRM"):
        pass
    else:
        parsed = _parse_date(text)
        if parsed is None:
            send_message(chat_id, msg(telegram_id, "bad_date"))
            return
        state["pending_data"]["date"] = parsed

    ocr_reg = state["pending_data"].get("register") or "desconocido"
    state["state"] = "AWAITING_REGISTER"
    _set_state(telegram_id, state)
    send_message(chat_id, msg(telegram_id, "ocr_reg", reg=ocr_reg), reply_markup=_build_inline_confirm_reg(telegram_id))


def _handle_register(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle AWAITING_REGISTER — confirm or override OCR register."""
    if _ascii_upper(text) not in ("OK", "YES", "SI", "S\u00cd", "CONFIRM"):
        text_stripped = text.strip()
        try:
            reg_num = int(text_stripped)
        except ValueError:
            send_message(chat_id, msg(telegram_id, "bad_reg"))
            return
        state["pending_data"]["register"] = reg_num

    state["state"] = "AWAITING_PAYOUTS"
    _set_state(telegram_id, state)
    send_message(chat_id, msg(telegram_id, "payouts"), reply_markup=_build_inline_payouts_zero(telegram_id))


def _handle_confirmation(telegram_id, chat_id, text, state):
    if _ascii_upper(text) in ("YES", "SI", "S\u00cd"):
        sid = uuid.uuid4().hex[:8]
        ocr_data = state["pending_data"]
        image_bytes = state.get("pending_image_bytes")
        store = state["store"]
        username = state["username"]

        logger.info(
            f"[BOT sid={sid}] Submission started: user={username!r} store={store!r} "
            f"date={ocr_data.get('date')!r} register={ocr_data.get('register')!r}"
        )

        storage_path = None
        if image_bytes:
            try:
                storage_path = upload_image_to_storage(
                    image_bytes,
                    store,
                    ocr_data.get("date", "unknown"),
                    ocr_data.get("register", 0),
                )
                logger.info(f"[BOT sid={sid}] Upload OK: path={storage_path!r}")
            except Exception as e:
                logger.error(f"[BOT sid={sid}] Image upload failed: {e}")
                send_message(chat_id, msg(telegram_id, "photo_warn"))

        payouts = state.get("pending_payouts", 0.0) or 0.0
        actual_cash = state.get("pending_actual_cash", 0.0) or 0.0
        calc_variance = state.get("pending_variance")

        try:
            entry_id = save_audit_entry(
                ocr_data,
                store,
                username,
                payouts=payouts,
                actual_cash=actual_cash,
                variance=calc_variance,
            )
        except ValueError as e:
            logger.warning(f"[BOT sid={sid}] Duplicate rejected: {e}")
            send_message(chat_id, f"\u26a0\ufe0f {e}")
            new_state = {
                "state": "REGISTERED",
                "store": state.get("store"),
                "username": state.get("username"),
                "retry_count": 0,
            }
            _set_state(telegram_id, new_state)
            return
        except Exception as e:
            logger.error(f"[BOT sid={sid}] save_audit_entry FAILED: {e}")
            send_message(chat_id, msg(telegram_id, "db_error"))
            return

        if storage_path and entry_id:
            try:
                save_photo_record(
                    entry_id=entry_id,
                    store=store,
                    business_date=ocr_data.get("date", ""),
                    register_id=_format_register_id(ocr_data.get("register")),
                    uploaded_by=username,
                    storage_path=storage_path,
                )
            except Exception as e:
                logger.error(f"[BOT sid={sid}] save_photo_record failed (entry still saved): {e}")

        gross = sum(
            ocr_data.get(f) or 0 for f in ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss"]
        )
        logger.info(
            f"[BOT sid={sid}] Submission complete: entry_id={entry_id} "
            f"photo={'yes path=' + storage_path if storage_path else 'no'} gross={gross:.2f}"
        )
        new_state = {
            "state": "REGISTERED",
            "store": state.get("store"),
            "username": state.get("username"),
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        saved_text = msg(
            telegram_id,
            "saved",
            reg=ocr_data.get("register", "?"),
            gross=gross,
        )

        variance = ocr_data.get("variance") or 0
        insight = ""
        if variance != 0:
            try:
                insight = ask_ai(
                    f"Varianza de ${variance:.2f} en Caja #{ocr_data.get('register', '?')}. "
                    f"Es normal o preocupante? Una oracion.",
                    store,
                    "system",
                    username,
                )
            except Exception as e:
                logger.debug(f"[BOT sid={sid}] AI insight skipped: {e}")

        if image_bytes and storage_path:
            photo_caption = saved_text
            if insight:
                photo_caption += f"\n\n{insight}"
            send_photo_safe(chat_id, image_bytes, caption=photo_caption)
            if insight:
                send_message(chat_id, insight, reply_markup=_kb_registered(telegram_id))
            else:
                send_message(chat_id, msg(telegram_id, "photo_send"), reply_markup=_kb_registered(telegram_id))
        else:
            if insight:
                saved_text += f"\n\n{insight}"
            send_message(chat_id, saved_text, reply_markup=_kb_registered(telegram_id))

    elif _ascii_upper(text) == "NO":
        new_state = {
            "state": "REGISTERED",
            "store": state.get("store"),
            "username": state.get("username"),
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        send_message(chat_id, msg(telegram_id, "cancelled"))
    else:
        send_message(chat_id, msg(telegram_id, "yes_no"))


# ── Callback query handler ────────────────────────────────────────────────


def _handle_callback(cb: dict) -> None:
    """Handle an inline keyboard button press with guaranteed spinner dismissal."""
    cb_id = cb["id"]
    telegram_id = cb["from"]["id"]
    chat_id = cb["message"]["chat"]["id"]
    data = cb.get("data", "")
    answered = False

    try:
        if _is_button_expired(cb):
            _tg(
                "answerCallbackQuery",
                callback_query_id=cb_id,
                text=msg(telegram_id, "error_button_expired"),
                show_alert=True,
            )
            answered = True
            return

        _tg("answerCallbackQuery", callback_query_id=cb_id)
        answered = True

        with _bot_state_lock:
            state = bot_state.get(telegram_id)
        if state is None:
            state = load_session(telegram_id) or {}
            if state:
                with _bot_state_lock:
                    bot_state[telegram_id] = state
        current_state = state.get("state")

        prefix, _, value = data.partition(":")

        if prefix == "store" and current_state == "AWAITING_STORE":
            chosen = _STORE_CHOICE.get(value)
            if chosen:
                state["store"] = chosen
                state["state"] = "REGISTERED"
                _set_state(telegram_id, state)
                saved_msg = state.pop("pending_photo_msg", None)
                if saved_msg:
                    _handle_photo(telegram_id, chat_id, "", saved_msg, state)
                else:
                    send_message(chat_id, msg(telegram_id, "store_confirm", store=chosen))

        elif prefix == "date" and current_state == "AWAITING_DATE":
            if value == "ok":
                _handle_date(telegram_id, chat_id, "OK", state)
            else:
                send_message(chat_id, msg(telegram_id, "bad_date"))

        elif prefix == "reg" and current_state == "AWAITING_REGISTER":
            if value == "ok":
                _handle_register(telegram_id, chat_id, "OK", state)
            else:
                send_message(chat_id, msg(telegram_id, "bad_reg"))

        elif prefix == "save" and current_state == "AWAITING_CONFIRMATION":
            _handle_confirmation(telegram_id, chat_id, "YES" if value == "yes" else "NO", state)

        elif prefix == "payouts" and current_state == "AWAITING_PAYOUTS":
            _handle_payouts(telegram_id, chat_id, value, state)

        elif prefix == "actual_cash" and current_state == "AWAITING_ACTUAL_CASH":
            _handle_actual_cash(telegram_id, chat_id, value, state)

        elif prefix == "broadcast" and current_state == "BROADCAST_CONFIRM":
            _handle_broadcast_confirm(telegram_id, chat_id, value, state)

        elif prefix == "lang":
            state["lang"] = value
            _set_state(telegram_id, state)
            send_message(chat_id, msg(telegram_id, "lang_set"))

        else:
            send_message_safe(chat_id, msg(telegram_id, "error_state_expired"))

    except TelegramAPIError as e:
        logger.error(f"Callback TG API error: {e}", exc_info=True)
        _notify_admin_if_needed(telegram_id, "TelegramAPIError", str(e))
        send_message_safe(chat_id, msg(telegram_id, "error_connection"))
        _log_dead_letter(telegram_id, data, e)
    except Exception as e:
        logger.error(f"Callback handler crash: {e}", exc_info=True)
        _notify_admin_if_needed(telegram_id, type(e).__name__, str(e))
        send_message_safe(chat_id, msg(telegram_id, "error_unknown"))
        _log_dead_letter(telegram_id, data, e)
    finally:
        if not answered:
            try:
                _tg("answerCallbackQuery", callback_query_id=cb_id, retries=1)
            except Exception:  # noqa: S110 — best-effort callback ack
                pass


# ── Main dispatcher ───────────────────────────────────────────────────────


def handle_update(update: dict) -> None:
    """Main entry point: dispatch an incoming Telegram update."""
    cb = update.get("callback_query")
    if cb:
        _handle_callback(cb)
        return

    tg_msg = update.get("message")
    if not tg_msg:
        return

    telegram_id = tg_msg["from"]["id"]
    tg_username = tg_msg["from"].get("username", "")
    chat_id = tg_msg["chat"]["id"]

    with _bot_state_lock:
        state = bot_state.get(telegram_id)
    if state is None:
        state = load_session(telegram_id) or {}
        if state:
            with _bot_state_lock:
                bot_state[telegram_id] = state
    current_state = state.get("state")

    # photo received
    if "photo" in tg_msg:
        if not current_state or current_state not in ("REGISTERED", "AI_CHAT"):
            if not is_registered(telegram_id):
                new_state = {"state": "AWAITING_USERNAME", "retry_count": 0}
                _set_state(telegram_id, new_state)
                send_message(chat_id, msg(telegram_id, "register_start"))
                return
            else:
                user_row = get_bot_user(telegram_id)
                if user_row is None:
                    return
                new_state = {
                    "state": "REGISTERED",
                    "store": user_row["store"],
                    "username": user_row["username"],
                    "retry_count": 0,
                }
                _set_state(telegram_id, new_state)
                state = new_state
                current_state = "REGISTERED"

        _handle_photo(telegram_id, chat_id, tg_username, tg_msg, state)
        return

    # text received
    text = (tg_msg.get("text") or "").strip()

    if text.startswith("/"):
        _handle_slash(telegram_id, chat_id, text, state)
        return

    if text in (MESSAGES["en"]["btn_ask_ai"], MESSAGES["es"]["btn_ask_ai"]) and current_state == "REGISTERED":
        state["state"] = "AI_CHAT"
        _set_state(telegram_id, state)
        send_message(chat_id, msg(telegram_id, "ai_welcome"), reply_markup=_kb_ai_chat(telegram_id))
        return

    if text in (MESSAGES["en"]["btn_cancel"], MESSAGES["es"]["btn_cancel"]) and current_state == "AI_CHAT":
        with _ai_lock:
            _ai_history.pop(telegram_id, None)
            _ai_history_ts.pop(telegram_id, None)
        state["state"] = "REGISTERED"
        _set_state(telegram_id, state)
        send_message(chat_id, msg(telegram_id, "ai_exit"), reply_markup=_kb_registered(telegram_id))
        return

    if current_state == "AI_CHAT":
        _handle_ai_message(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_DATE":
        _handle_date(telegram_id, chat_id, text, state)
        return
    if current_state == "AWAITING_REGISTER":
        _handle_register(telegram_id, chat_id, text, state)
        return
    if current_state == "AWAITING_PAYOUTS":
        _handle_payouts(telegram_id, chat_id, text, state)
        return
    if current_state == "AWAITING_ACTUAL_CASH":
        _handle_actual_cash(telegram_id, chat_id, text, state)
        return
    if current_state == "AWAITING_CONFIRMATION":
        _handle_confirmation(telegram_id, chat_id, text, state)
        return
    if current_state == "BROADCAST_CONFIRM":
        _handle_broadcast_confirm(telegram_id, chat_id, text, state)
        return

    if current_state == "AWAITING_STORE":
        chosen = _STORE_CHOICE.get(text)
        if not chosen:
            send_message(chat_id, msg(telegram_id, "invalid_store"))
            return
        state["store"] = chosen
        state["state"] = "REGISTERED"
        _set_state(telegram_id, state)
        saved_photo_msg = state.pop("pending_photo_msg", None)
        if saved_photo_msg:
            _handle_photo(telegram_id, chat_id, tg_username, saved_photo_msg, state)
        else:
            send_message(chat_id, msg(telegram_id, "store_confirm", store=chosen))
        return

    if current_state == "AWAITING_PASSWORD":
        _handle_password(telegram_id, chat_id, tg_username, text, state)
        return
    if current_state == "AWAITING_USERNAME":
        username = text.strip()[:50]
        if not re.match(r"^[a-zA-Z0-9_-]+$", username):
            send_message(chat_id, "Nombre de usuario invalido. Solo letras, numeros, _ y -.")
            return
        state["username"] = username
        state["state"] = "AWAITING_PASSWORD"
        _set_state(telegram_id, state)
        send_message(chat_id, msg(telegram_id, "enter_password"))
        return

    # default
    if is_registered(telegram_id):
        user_row = get_bot_user(telegram_id)
        if user_row is None:
            return
        new_state = {
            "state": "REGISTERED",
            "store": user_row["store"],
            "username": user_row["username"],
            "retry_count": 0,
        }
        _set_state(telegram_id, new_state)
        send_message(
            chat_id, msg(telegram_id, "welcome_back", store=user_row["store"]), reply_markup=_kb_registered(telegram_id)
        )
    else:
        new_state = {"state": "AWAITING_USERNAME", "retry_count": 0}
        _set_state(telegram_id, new_state)
        send_message(chat_id, msg(telegram_id, "register_start"))


# ── Slash command handler ─────────────────────────────────────────────────


def _handle_slash(telegram_id: int, chat_id: int, text: str, state: dict) -> None:
    """Handle /help, /status, /cancel, /last, /broadcast, /lang commands."""
    cmd = text.split()[0].lower().split("@")[0]

    if cmd in ("/start", "/help"):
        if is_registered(telegram_id):
            user_row = get_bot_user(telegram_id)
            if user_row is not None:
                new_state = {
                    "state": "REGISTERED",
                    "store": user_row["store"],
                    "username": user_row["username"],
                    "retry_count": 0,
                }
                _set_state(telegram_id, new_state)
                if cmd == "/start":
                    send_message(
                        chat_id,
                        msg(telegram_id, "welcome_back", store=user_row["store"]),
                        reply_markup=_kb_registered(telegram_id),
                    )
                    return
        send_message(chat_id, msg(telegram_id, "help"))

    elif cmd == "/status":
        current = state.get("state")
        if not current or current == "AWAITING_USERNAME":
            send_message(chat_id, msg(telegram_id, "status_unregistered"))
        elif current == "REGISTERED":
            send_message(
                chat_id,
                msg(
                    telegram_id,
                    "status_registered",
                    store=state.get("store", "?"),
                    username=state.get("username", "?"),
                ),
            )
        else:
            send_message(
                chat_id,
                msg(
                    telegram_id,
                    "status_midflow",
                    state=current,
                    username=state.get("username", "?"),
                ),
            )

    elif cmd == "/cancel":
        current = state.get("state")
        if not current or current in ("AWAITING_USERNAME", "AWAITING_PASSWORD"):
            if is_registered(telegram_id):
                user_row = get_bot_user(telegram_id)
                if user_row is not None:
                    new_state = {
                        "state": "REGISTERED",
                        "store": user_row["store"],
                        "username": user_row["username"],
                        "retry_count": 0,
                    }
                    _set_state(telegram_id, new_state)
                    send_message(
                        chat_id,
                        msg(telegram_id, "welcome_back", store=user_row["store"]),
                        reply_markup=_kb_registered(telegram_id),
                    )
            else:
                send_message(chat_id, msg(telegram_id, "cancel_nothing"))
        elif current == "AI_CHAT":
            with _ai_lock:
                _ai_history.pop(telegram_id, None)
                _ai_history_ts.pop(telegram_id, None)
            new_state = {
                "state": "REGISTERED",
                "store": state.get("store"),
                "username": state.get("username"),
                "retry_count": 0,
            }
            _set_state(telegram_id, new_state)
            send_message(chat_id, msg(telegram_id, "ai_exit"), reply_markup=_kb_registered(telegram_id))
        else:
            if state.get("username") and state.get("store") and current != "AWAITING_USERNAME":
                new_state = {
                    "state": "REGISTERED",
                    "store": state.get("store"),
                    "username": state.get("username"),
                    "retry_count": 0,
                }
            else:
                new_state = {"state": "AWAITING_USERNAME", "retry_count": 0}
            _set_state(telegram_id, new_state)
            send_message(chat_id, msg(telegram_id, "cancel_ok"))

    elif cmd == "/last":
        store = state.get("store")
        if not store or store == "All":
            send_message(chat_id, "Usa /last desde una tienda espec\u00edfica.")
            return
        try:
            db = extensions.get_db()
            if db is None:
                send_message(chat_id, "\u274c Base de datos no disponible.")
                return
            result_rows = rows(
                db.table("audits")
                .select("date, reg, gross, variance, staff")
                .eq("store", store)
                .is_("deleted_at", "null")
                .order("date", desc=True)
                .limit(1)
                .execute()
            )
            if not result_rows:
                send_message(chat_id, f"No hay reportes recientes para {store}.")
                return
            e = result_rows[0]
            send_message(
                chat_id,
                (
                    f"\U0001f4cb \u00daltimo reporte \u2014 {store}\n"
                    f"Fecha: {e.get('date', '?')}\n"
                    f"Caja: {e.get('reg', '?')}\n"
                    f"Bruto: ${e.get('gross', 0):,.2f}\n"
                    f"Varianza: ${e.get('variance', 0):,.2f}\n"
                    f"Enviado por: {e.get('staff', '?')}"
                ),
            )
        except Exception as ex:
            logger.error(f"/last failed: {ex}")
            send_message(chat_id, "\u274c Error consultando el \u00faltimo reporte.")

    elif cmd == "/broadcast":
        user_row = get_bot_user(telegram_id)
        if not user_row:
            send_message(chat_id, msg(telegram_id, "broadcast_no_permission"))
            return
        username = user_row.get("username")
        # Cross-reference the users table to get the actual role (bot_users has no role column)
        role = "staff"
        try:
            db = extensions.get_db()
            if db and username:
                user_data = rows(db.table("users").select("role").eq("username", username).execute())
                role = user_data[0]["role"] if user_data else "staff"
        except Exception:  # noqa: S110 — fallback to staff role if DB unavailable
            pass
        if role not in ("admin", "super_admin"):
            send_message(chat_id, msg(telegram_id, "broadcast_no_permission"))
            return
        parts = text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            send_message(chat_id, "Uso: /broadcast <mensaje>")
            return
        broadcast_text = parts[1].strip()
        try:
            db = extensions.get_db()
            if db is None:
                raise RuntimeError("DB unavailable")
            broadcast_users = rows(db.table("bot_users").select("telegram_id").execute())
            count: int | str = len(broadcast_users)
        except Exception:
            count = "?"
        state["state"] = "BROADCAST_CONFIRM"
        state["pending_broadcast"] = broadcast_text
        _set_state(telegram_id, state)
        send_message(
            chat_id,
            msg(telegram_id, "broadcast_confirm", count=count, message=broadcast_text),
            reply_markup=_build_inline_broadcast(telegram_id),
        )

    elif cmd == "/lang":
        lang_kb = _inline_kb(
            [
                [_inline_btn("English", "lang:en"), _inline_btn("Espanol", "lang:es")],
            ]
        )
        send_message(chat_id, msg(telegram_id, "lang_prompt"), reply_markup=lang_kb)

    else:
        send_message(chat_id, msg(telegram_id, "help"))


# ── Webhook registration ─────────────────────────────────────────────────


def register_webhook() -> None:
    """Register the Telegram webhook with Telegram's servers."""
    token = _token()
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
        return

    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("WEBHOOK_DOMAIN")
    if not domain:
        logger.error("Neither RAILWAY_PUBLIC_DOMAIN nor WEBHOOK_DOMAIN is set — cannot register webhook")
        return
    webhook_url = f"https://{domain}/api/telegram/webhook"

    secret = Config.TELEGRAM_WEBHOOK_SECRET
    if not secret:
        logger.error("TELEGRAM_WEBHOOK_SECRET not set — cannot register webhook securely")
        return
    resp = http.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"],
            "secret_token": secret,
        },
        timeout=10,
    )
    if resp.ok and resp.json().get("ok"):
        logger.info(f"Telegram webhook registered: {webhook_url}")
    else:
        logger.error(f"Telegram webhook registration failed: {resp.text}")
