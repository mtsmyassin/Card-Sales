"""Audits Blueprint — CRUD for pharmacy sales audit entries."""

import logging

import extensions
from audit_log import audit_log
from config import Config
from flask import Blueprint, jsonify, request, session
from helpers.auth_utils import is_admin_role, require_auth
from helpers.db import db_retry, is_unique_violation
from helpers.exceptions import AuditNotFoundError, DuplicateEntryError, StoreMismatchError
from helpers.offline_queue import _atomic_write_json, clear_queue, get_queue_path, load_queue, save_to_queue
from helpers.supabase_types import rows
from helpers.validation import validate_audit_entry
from services.audit_service import (
    check_duplicate,
    check_store_access,
    get_audit,
    insert_audit,
    soft_delete_audit,
    update_audit,
)

logger = logging.getLogger(__name__)
bp = Blueprint("audits", __name__)


def _send_variance_alert(store: str, date: str, reg: str, variance: float, gross: float, submitted_by: str) -> None:
    """Send Telegram alert to admin/manager bot users when |variance| > $5."""
    try:
        from telegram_bot import send_message

        _db = extensions.get_db()
        if _db is None:
            return
        bot_users = rows(_db.table("bot_users").select("telegram_id, username, store").execute())
        if not bot_users:
            return
        # Cross-reference roles
        unames = [u["username"] for u in bot_users if u.get("username")]
        role_map = {}
        if unames:
            users_resp = _db.table("users").select("username, role, store").in_("username", unames).execute()
            role_map = {u["username"]: (u.get("role", "staff"), u.get("store", "")) for u in rows(users_resp)}
        sign = "Corto" if variance < 0 else "Sobre"
        msg = (
            f"Varianza {sign}: ${abs(variance):.2f}\n"
            f"Tienda: {store} | Caja: {reg} | Fecha: {date}\n"
            f"Bruto: ${gross:.2f} | Enviado por: {submitted_by}"
        )
        for bu in bot_users:
            role, user_store = role_map.get(bu.get("username", ""), ("staff", ""))
            if role in ("admin", "super_admin", "manager") or user_store == store or user_store == "All":
                try:
                    send_message(bu["telegram_id"], msg)
                except Exception as send_err:
                    logger.warning(f"[variance_alert] Failed to notify {bu.get('username')}: {send_err}")
    except Exception as e:
        logger.warning(f"_send_variance_alert failed: {e}")


@bp.route("/api/save", methods=["POST"])
@require_auth()
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def save():
    """Create a new audit entry with audit logging and input validation."""
    try:
        d = request.json
        if not d:
            return jsonify(error="No data provided", code="BAD_REQUEST"), 400

        # Validate input
        is_valid, error_msg = validate_audit_entry(d)
        if not is_valid:
            logger.warning(f"Invalid audit entry data from {session.get('user')}: {error_msg}")
            return jsonify(error=error_msg, code="INVALID_INPUT"), 400

        # Duplicate check — use admin client so RLS doesn't hide existing entries
        try:
            check_duplicate(d["date"], d.get("store", "Main"), d["reg"])
        except DuplicateEntryError:
            logger.warning(
                f"[save] Duplicate entry rejected: user={session.get('user')!r} "
                f"date={d['date']} store={d.get('store')} reg={d['reg']}"
            )
            return jsonify(
                error=f"Duplicate: a record for {d['date']} / {d.get('store')} / {d['reg']} already exists.",
                code="DUPLICATE",
            ), 409
        except Exception as e:
            logger.error(f"[save] Duplicate check failed — aborting to prevent potential duplicate: {e}")
            return jsonify(error="Unable to verify uniqueness. Please retry.", code="DB_ERROR"), 503

        username = session.get("user")
        role = session.get("role")

        record = {
            "date": d["date"],
            "reg": d["reg"],
            "staff": d["staff"],
            "store": d.get("store", "Main"),
            "gross": float(d["gross"]),
            "net": float(d["net"]),
            "variance": float(d["variance"]),
            "payload": {
                "date": d["date"],
                "reg": d["reg"],
                "staff": d["staff"],
                "store": d.get("store", "Main"),
                "gross": float(d["gross"]),
                "net": float(d["net"]),
                "variance": float(d["variance"]),
                "breakdown": d.get("breakdown", {}),
                "notes": d.get("notes", ""),
            },
        }

        # S1: Enforce store from session for non-admin users (prevent store IDOR)
        if not is_admin_role(role):
            user_store = session.get("store")
            if user_store and user_store != "All":
                record["store"] = user_store
                record["payload"]["store"] = user_store

        try:
            inserted = insert_audit(record)
        except DuplicateEntryError:
            logger.warning(
                f"[save] DB duplicate rejected: user={username!r} "
                f"date={d['date']} store={d.get('store')} reg={d['reg']}"
            )
            return jsonify(
                error=f"Duplicate: a record for {d['date']} / {d.get('store')} / {d['reg']} already exists.",
                code="DUPLICATE",
            ), 409
        except Exception as e:
            logger.warning(f"Failed to save to database, attempting offline queue: {e}")
            try:
                if not save_to_queue(record):
                    logger.error("Offline queue full — record dropped")
                    return jsonify(error="Database unavailable and offline queue is full", code="QUEUE_FULL"), 503
            except RuntimeError as queue_err:
                # Ephemeral filesystem (Railway) — cannot safely queue offline
                logger.error(f"Offline queue unavailable: {queue_err}")
                return jsonify(
                    error="Database is currently unavailable and offline queuing is not supported on this server. Please try again shortly.",
                    code="DB_UNAVAILABLE",
                ), 503

            # Log offline save
            audit_log(
                action="CREATE_OFFLINE",
                actor=username,
                role=role,
                entity_type="AUDIT_ENTRY",
                after={"date": d["date"], "store": d.get("store"), "gross": d["gross"]},
                success=True,
                context={"ip": request.remote_addr, "reason": "database_unavailable"},
            )

            return jsonify(status="offline")

        # Log successful creation
        audit_log(
            action="CREATE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(inserted.get("id")) if inserted else None,
            after={"date": d["date"], "store": d.get("store"), "gross": d["gross"]},
            success=True,
            context={"ip": request.remote_addr},
        )

        logger.info(f"Audit entry created by {username}: date={d['date']}, store={d.get('store')}")
        # Variance alert — fire-and-forget, never block the response
        variance_val = float(d.get("variance", 0))
        if abs(variance_val) > Config.VARIANCE_ALERT_THRESHOLD:
            try:
                _send_variance_alert(
                    store=d.get("store", "Main"),
                    date=d["date"],
                    reg=d["reg"],
                    variance=variance_val,
                    gross=float(d["gross"]),
                    submitted_by=username,
                )
            except Exception as alert_err:
                logger.warning(f"[save] Variance alert failed (non-blocking): {alert_err}")
        return jsonify(status="success")

    except Exception as e:
        logger.error(f"Error in save endpoint: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route("/api/sync", methods=["POST"])
@require_auth()
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def sync():
    """Sync offline queue to database (authenticated users only)."""
    username = session.get("user")
    role = session.get("role")

    queue = load_queue()
    if not queue:
        return jsonify(status="empty")
    failed_items = []
    success_count = 0
    for item in queue:
        try:
            # S1: Enforce store from session for non-admin users (prevent store IDOR)
            if not is_admin_role(role):
                user_store = session.get("store")
                if user_store and user_store != "All":
                    item["store"] = user_store

            # Validate before inserting (offline entries skip the /api/save validation)
            ok, err = validate_audit_entry(item)
            if not ok:
                logger.warning(f"[sync] Skipping invalid queue item: {err} — {item}")
                failed_items.append(item)
                continue

            # Duplicate check — DB unique constraint on (date, store, reg)
            _db = extensions.get_db()
            date_val = item.get("date")
            store_val = item.get("store")
            reg_val = item.get("reg")
            dup = (
                _db.table("audits")
                .select("id")
                .eq("date", date_val)
                .eq("store", store_val)
                .eq("reg", reg_val)
                .is_("deleted_at", "null")
                .limit(1)
                .execute()
            )
            if rows(dup):
                logger.warning(f"[sync] Skipping duplicate: date={date_val} store={store_val} reg={reg_val}")
                success_count += 1  # Don't keep retrying a duplicate — remove from queue
                continue

            _item = item  # bind loop variable for lambda closure
            db_retry(lambda: extensions.get_db().table("audits").insert(_item).execute(), label="sync_audit")  # noqa: B023
            success_count += 1

            # Log successful sync
            audit_log(
                action="SYNC",
                actor=username,
                role=role,
                entity_type="OFFLINE_QUEUE",
                success=True,
                context={"ip": request.remote_addr, "records": 1},
            )
        except Exception as exc:
            if is_unique_violation(exc):
                logger.warning(
                    f"[sync] Skipping DB duplicate: date={item.get('date')} store={item.get('store')} reg={item.get('reg')}"
                )
                success_count += 1  # Remove from queue — don't retry duplicates
                continue
            logger.warning(f"[sync] Insert failed for item date={item.get('date')} store={item.get('store')}: {exc}")
            failed_items.append(item)
    if failed_items:
        q_path = get_queue_path()
        _atomic_write_json(q_path, failed_items)
    else:
        clear_queue()
    return jsonify(status="success", count=success_count, remaining=len(failed_items))


@bp.route("/api/update", methods=["POST"])
@require_auth()
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def update():
    """Update an audit entry with RBAC, input validation, and audit logging."""
    username = session.get("user")
    role = session.get("role")

    # Staff cannot edit
    if role == "staff":
        logger.warning(f"Staff user {username} attempted to edit entry")
        audit_log(
            action="UPDATE_DENIED",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            success=False,
            error="Staff role cannot edit entries",
            context={"ip": request.remote_addr},
        )
        return jsonify(error="Permission Denied: Staff cannot edit entries", code="FORBIDDEN"), 403

    uid = None
    try:
        d = request.json
        if not d:
            return jsonify(error="No data provided", code="BAD_REQUEST"), 400

        # Validate ID
        uid = d.get("id")
        if not uid:
            return jsonify(error="Missing entry ID", code="MISSING_PARAM"), 400

        # Validate input
        is_valid, error_msg = validate_audit_entry(d)
        if not is_valid:
            logger.warning(f"Invalid audit entry data from {username}: {error_msg}")
            return jsonify(error=error_msg, code="INVALID_INPUT"), 400

        # Get current record for audit trail + store-scoping check
        try:
            before_state = get_audit(uid)
        except AuditNotFoundError:
            return jsonify(error="Entry not found", code="NOT_FOUND"), 404

        try:
            check_store_access(before_state, role, session.get("store"))
        except StoreMismatchError:
            logger.warning(
                f"[update] IDOR attempt: user={username!r} (store={session.get('store')!r}) "
                f"tried to update entry {uid} (store={before_state.get('store')!r})"
            )
            audit_log(
                action="UPDATE_DENIED",
                actor=username,
                role=role,
                entity_type="AUDIT_ENTRY",
                entity_id=str(uid),
                success=False,
                error="Cross-store update denied",
                context={"ip": request.remote_addr, "entry_store": before_state.get("store")},
            )
            return jsonify(error="Not authorized to modify entries from another store", code="STORE_MISMATCH"), 403

        # Optimistic locking — reject if another user modified the record
        client_version = d.get("version")
        current_version = before_state.get("version", 1)
        if client_version is not None and current_version is not None:
            if int(client_version) != int(current_version):
                logger.warning(
                    f"Optimistic lock conflict on audit {uid}: client_version={client_version}, db_version={current_version}"
                )
                return jsonify(
                    error="Conflict: entry was modified by another user. Please reload and try again.", code="CONFLICT"
                ), 409

        record = {
            "date": d["date"],
            "reg": d["reg"],
            "staff": d["staff"],
            "store": d.get("store", "Main"),
            "gross": float(d["gross"]),
            "net": float(d["net"]),
            "variance": float(d["variance"]),
            "payload": {
                "date": d["date"],
                "reg": d["reg"],
                "staff": d["staff"],
                "store": d.get("store", "Main"),
                "gross": float(d["gross"]),
                "net": float(d["net"]),
                "variance": float(d["variance"]),
                "breakdown": d.get("breakdown", {}),
                "notes": d.get("notes", ""),
            },
            "version": (int(current_version) + 1) if current_version is not None else 1,
        }

        # F3: Non-admins cannot reassign store — force original store value
        if not is_admin_role(role):
            original_store = before_state.get("store", "Main")
            record["store"] = original_store
            record["payload"]["store"] = original_store

        update_audit(uid, record)

        # Log successful update
        audit_log(
            action="UPDATE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(uid),
            before={"date": before_state["date"], "gross": before_state["gross"]} if before_state else None,
            after={"date": d["date"], "gross": d["gross"]},
            success=True,
            context={"ip": request.remote_addr},
        )

        logger.info(f"Audit entry {uid} updated by {username}")
        return jsonify(status="success")

    except Exception as e:
        logger.error(f"Error updating entry {uid}: {e}", exc_info=True)

        audit_log(
            action="UPDATE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(uid) if uid else None,
            success=False,
            error="Audit entry update failed",
            context={"ip": request.remote_addr},
        )

        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route("/api/delete", methods=["POST"])
@require_auth()
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def delete():
    """Soft-delete an audit entry with RBAC and audit logging."""
    username = session.get("user")
    role = session.get("role")

    # Staff cannot delete
    if role == "staff":
        logger.warning(f"Staff user {username} attempted to delete entry")
        audit_log(
            action="DELETE_DENIED",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            success=False,
            error="Staff role cannot delete entries",
            context={"ip": request.remote_addr},
        )
        return jsonify(error="Permission Denied: Staff cannot delete entries", code="FORBIDDEN"), 403

    try:
        if not request.json or "id" not in request.json:
            return jsonify(error="Missing entry ID", code="MISSING_PARAM"), 400

        uid = request.json["id"]

        # Get current record for audit trail + store-scoping check
        try:
            before_state = get_audit(uid)
        except AuditNotFoundError:
            return jsonify(error="Entry not found", code="NOT_FOUND"), 404

        try:
            check_store_access(before_state, role, session.get("store"))
        except StoreMismatchError:
            logger.warning(
                f"[delete] IDOR attempt: user={username!r} (store={session.get('store')!r}) "
                f"tried to delete entry {uid} (store={before_state.get('store')!r})"
            )
            audit_log(
                action="DELETE_DENIED",
                actor=username,
                role=role,
                entity_type="AUDIT_ENTRY",
                entity_id=str(uid),
                success=False,
                error="Cross-store delete denied",
                context={"ip": request.remote_addr, "entry_store": before_state.get("store")},
            )
            return jsonify(error="Not authorized to delete entries from another store", code="STORE_MISMATCH"), 403

        # Soft delete — set deleted_at timestamp instead of removing the row
        soft_delete_audit(uid)

        # Log successful soft deletion
        audit_log(
            action="SOFT_DELETE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(uid),
            before={"date": before_state["date"], "gross": before_state["gross"], "store": before_state["store"]}
            if before_state
            else None,
            success=True,
            context={"ip": request.remote_addr},
        )

        logger.info(f"Audit entry {uid} soft-deleted by {username}")
        return jsonify(status="success")

    except Exception as e:
        logger.error(f"Error deleting entry: {e}", exc_info=True)

        audit_log(
            action="DELETE",
            actor=username,
            role=role,
            entity_type="AUDIT_ENTRY",
            entity_id=str(request.json.get("id")) if request.json and request.json.get("id") else None,
            success=False,
            error="Audit entry deletion failed",
            context={"ip": request.remote_addr},
        )

        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route("/api/list")
@require_auth()
@extensions.limiter.limit(Config.RATELIMIT_READ)
def list_audits():
    """List audit entries filtered by user's store access, with photo counts."""
    try:
        user_store = session.get("store")
        user_role = session.get("role")
        user = session.get("user")

        _db = extensions.get_db()
        logger.info(f"[list_audits] using_admin={extensions.has_admin_client()}")

        # Push store filter to DB for non-admin users — avoids fetching all rows.
        # Limit keeps response bounded; at ~5 audits/day this covers >1 year.
        # Frontend receives all rows and filters client-side (SPA pattern).
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(request.args.get("per_page", 2000, type=int), 2000)
        offset = (page - 1) * per_page
        query = (
            _db.table("audits")
            .select("*")
            .is_("deleted_at", "null")
            .order("date", desc=True)
            .range(offset, offset + per_page - 1)
        )
        if not is_admin_role(user_role):
            query = query.eq("store", user_store)
        response = db_retry(lambda: query.execute(), label="list_audits")
        allowed_rows = rows(response)

        logger.info(
            f"[list_audits] user={user!r} role={user_role!r} store={user_store!r} "
            f"using_admin={extensions.has_admin_client()} "
            f"rows_returned={len(allowed_rows)}"
        )

        # Batch-fetch photo counts using service-role client to bypass RLS
        photo_counts: dict = {}
        if allowed_rows:
            entry_ids = [r["id"] for r in allowed_rows]
            photo_rows = rows(_db.table("z_report_photos").select("entry_id").in_("entry_id", entry_ids).execute())
            for p in photo_rows:
                eid = p["entry_id"]
                photo_counts[eid] = photo_counts.get(eid, 0) + 1
            logger.info(
                f"[list_audits] photo_counts fetched: {len(photo_rows)} photo rows "
                f"for {len(entry_ids)} entries -> {len(photo_counts)} entries have photos"
            )

        clean_rows = []
        for r in allowed_rows:
            merged = dict(r["payload"])  # shallow copy to avoid mutating cached response
            merged["id"] = r["id"]
            merged["store"] = r.get("store", "Main")
            merged["photo_count"] = photo_counts.get(r["id"], 0)
            merged["version"] = r.get("version", 1)
            clean_rows.append(merged)

        return jsonify(clean_rows)
    except Exception as e:
        logger.error(f"[list_audits] Error: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="LIST_ERROR"), 500
