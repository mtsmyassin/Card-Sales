"""Supabase storage and audit entry persistence for Telegram bot."""
import time
import logging

import extensions
from config import Config
from helpers.supabase_types import rows
from helpers.db import is_unique_violation
from audit_log import audit_log
from helpers.validation import validate_audit_entry

logger = logging.getLogger(__name__)


def _format_register_id(register) -> str:
    """Convert register number/string to 'Reg N' format."""
    if register is None:
        return "Reg ?"
    try:
        return f"Reg {int(register)}"
    except (TypeError, ValueError):
        return f"Reg {register}"


class StorageUploadError(Exception):
    """Raised when upload to Supabase Storage fails."""


def _ensure_bucket(admin_client) -> None:
    """Create z-reports bucket if it doesn't exist (requires service role key)."""
    try:
        existing = [b.name for b in admin_client.storage.list_buckets()]
        if "z-reports" not in existing:
            admin_client.storage.create_bucket("z-reports", options={"public": False})
            logger.info("Created z-reports storage bucket")
    except Exception as e:
        raise StorageUploadError(f"Could not ensure z-reports bucket: {e}") from e


def upload_image_to_storage(image_bytes: bytes, store: str, date: str, register) -> str:
    """Upload photo to Supabase Storage z-reports bucket. Returns storage path string."""
    if extensions.supabase_admin is None:
        raise StorageUploadError(
            "SUPABASE_SERVICE_KEY not configured — photo upload disabled"
        )
    _ensure_bucket(extensions.supabase_admin)
    store_slug = store.replace(" ", "_").replace("#", "")
    reg_num = int(register) if register else 0
    path = f"{store_slug}/{date}/reg{reg_num}_{int(time.time())}.jpg"
    try:
        extensions.supabase_admin.storage.from_("z-reports").upload(
            path,
            image_bytes,
            {"content-type": "image/jpeg"},
        )
    except Exception as e:
        raise StorageUploadError(f"Upload to z-reports failed: {e}") from e
    return path


def save_audit_entry(
    data: dict,
    store: str,
    username: str,
    payouts: float = 0.0,
    actual_cash: float = 0.0,
    variance: float | None = None,
) -> int | None:
    """Save the extracted Z report data to the audits table."""
    client = extensions.get_db()
    if client is None:
        return None

    reg_str = _format_register_id(data.get("register"))
    gross = sum(data.get(f) or 0 for f in
                ["cash", "ath", "athm", "visa", "mc", "amex", "disc", "wic", "mcs", "sss"])
    net = gross - payouts

    if variance is None:
        variance = float(data.get("variance") or 0)

    payload = {
        "date": data["date"],
        "reg": reg_str,
        "staff": username,
        "store": store,
        "gross": round(gross, 2),
        "net": round(net, 2),
        "variance": variance,
        "source": "telegram_bot",
        "submitted_by_telegram": username,
        "breakdown": {
            "cash": data.get("cash") or 0,
            "ath": data.get("ath") or 0,
            "athm": data.get("athm") or 0,
            "visa": data.get("visa") or 0,
            "mc": data.get("mc") or 0,
            "amex": data.get("amex") or 0,
            "disc": data.get("disc") or 0,
            "wic": data.get("wic") or 0,
            "mcs": data.get("mcs") or 0,
            "sss": data.get("sss") or 0,
            "payouts": payouts,
            "actual_cash": actual_cash,
        },
    }

    record = {
        "date": data["date"],
        "reg": reg_str,
        "staff": username,
        "store": store,
        "gross": round(gross, 2),
        "net": round(net, 2),
        "variance": round(variance, 2),
        "payload": payload,
    }

    is_valid, error_msg = validate_audit_entry(record)
    if not is_valid:
        logger.warning(f"[BOT] Validation failed for {store!r}/{record['date']!r}: {error_msg}")
        audit_log(
            action="CREATE",
            actor=username,
            role="bot_user",
            entity_type="AUDIT",
            success=False,
            error=f"Validation failed: {error_msg}",
            context={"source": "telegram_bot", "store": store, "date": record["date"]},
        )
        raise ValueError(f"Datos invalidos: {error_msg}")

    try:
        result_rows = rows(client.table("audits").insert(record).execute())
        entry_id = result_rows[0]["id"]
        logger.info(
            f"[BOT] audit saved: entry_id={entry_id} store={store!r} "
            f"date={record['date']!r} staff={username!r}"
        )
        audit_log(
            action="CREATE",
            actor=username,
            role="bot_user",
            entity_type="AUDIT",
            entity_id=str(entry_id),
            success=True,
            context={"source": "telegram_bot", "store": store, "date": record["date"], "reg": reg_str},
        )
        return entry_id
    except Exception as e:
        if is_unique_violation(e):
            logger.warning(
                f"[BOT] Duplicate rejected by DB constraint — "
                f"store={store!r} date={record['date']!r} reg={record['reg']!r}"
            )
            audit_log(
                action="CREATE",
                actor=username,
                role="bot_user",
                entity_type="AUDIT",
                success=False,
                error="Duplicate entry rejected by DB constraint",
                context={"source": "telegram_bot", "store": store, "date": record["date"], "reg": reg_str},
            )
            raise ValueError(
                f"Ya existe un reporte para {record['date']} / {store} / {record['reg']}"
            ) from e
        logger.error(
            f"[BOT] FATAL: DB insert failed — store={store!r} date={record['date']!r}: {e}",
            exc_info=True,
        )
        audit_log(
            action="CREATE",
            actor=username,
            role="bot_user",
            entity_type="AUDIT",
            success=False,
            error="DB insert failed",
            context={"source": "telegram_bot", "store": store, "date": record["date"]},
        )
        raise


def save_photo_record(
    entry_id: int,
    store: str,
    business_date: str,
    register_id: str,
    uploaded_by: str,
    storage_path: str,
    content_type: str = "image/jpeg",
) -> None:
    """Insert a photo record into z_report_photos, linked to an audit entry."""
    client = extensions.get_db()
    if client is None:
        logger.warning("save_photo_record: no supabase client available")
        return
    try:
        result_rows = rows(client.table("z_report_photos").insert({
            "entry_id": entry_id,
            "store": store,
            "business_date": business_date,
            "register_id": register_id,
            "uploaded_by": uploaded_by,
            "storage_path": storage_path,
            "content_type": content_type,
        }).execute())
        photo_id = result_rows[0]["id"] if result_rows else None
        logger.info(
            f"[BOT] photo record saved: photo_id={photo_id} entry_id={entry_id} "
            f"store={store!r} path={storage_path!r}"
        )
    except Exception as e:
        logger.error(
            f"[BOT] save_photo_record FAILED: entry_id={entry_id} path={storage_path!r}: {e}",
            exc_info=True,
        )
        raise
