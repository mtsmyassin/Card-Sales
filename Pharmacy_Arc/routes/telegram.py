"""Telegram Blueprint — bot webhook and Z-report photo endpoints."""
import hmac
import logging
from threading import Thread
from flask import Blueprint, request, jsonify, session
import extensions
from helpers.auth_utils import require_auth, can_access_photo
from config import Config

logger = logging.getLogger(__name__)
bp = Blueprint('telegram', __name__)


@bp.route('/api/telegram/webhook', methods=['POST'])
@extensions.csrf.exempt
def telegram_webhook():
    """Receive updates from Telegram and dispatch to bot state machine."""
    # Verify secret token set via TELEGRAM_WEBHOOK_SECRET env var.
    # Use constant-time compare to prevent timing-oracle attacks.
    expected_secret = Config.TELEGRAM_WEBHOOK_SECRET
    incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected_secret:
        logger.warning("Telegram webhook: TELEGRAM_WEBHOOK_SECRET not set — rejecting all requests")
        return jsonify(ok=False), 403
    if not hmac.compare_digest(incoming_secret, expected_secret):
        logger.warning("Telegram webhook: invalid secret token from %s",
                       request.headers.get("X-Forwarded-For", request.remote_addr))
        return jsonify(ok=False), 403

    update = request.json
    if not update:
        return jsonify(ok=False), 400

    def _dispatch():
        try:
            from telegram_bot import handle_update
            handle_update(update)
        except Exception as e:
            logger.error(f"Telegram webhook handler error: {e}", exc_info=True)

    t = Thread(target=_dispatch, daemon=True)
    t.start()

    # Return 200 immediately — Telegram requires a response within 5 seconds
    return jsonify(ok=True)


@bp.route('/api/audit/<int:audit_id>/zreport_image')
@require_auth()
@extensions.limiter.limit(Config.RATELIMIT_READ)
def get_zreport_image(audit_id: int):
    """Return a short-lived signed URL for the Z report image of an audit entry (legacy)."""
    try:
        result = extensions.get_db().table("audits").select("payload,store").eq("id", audit_id).execute()
        if not result.data:
            return jsonify(error="Not found", code="NOT_FOUND"), 404

        row = result.data[0]
        entry_store = row.get('store')
        if not can_access_photo(entry_store, session.get('role'), session.get('store')):
            logger.warning(
                f"[get_zreport_image] IDOR attempt: user={session.get('user')!r} "
                f"tried audit_id={audit_id} (store={entry_store!r})"
            )
            return jsonify(error="Not authorized", code="FORBIDDEN"), 403

        payload = row.get("payload", {})
        image_path = payload.get("z_report_image_path")
        if not image_path:
            return jsonify(error="No image for this entry", code="NOT_FOUND"), 404

        signed = extensions.get_db().storage.from_(Config.STORAGE_BUCKET).create_signed_url(image_path, Config.STORAGE_URL_EXPIRY_SECONDS)
        return jsonify(url=signed["signedURL"])

    except Exception as e:
        logger.error(f"get_zreport_image error: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/zreport/photos')
@require_auth()
@extensions.limiter.limit(Config.RATELIMIT_READ)
def get_entry_photos():
    """Return photo metadata (no URLs) for an audit entry. Store-scoped."""
    entry_id = request.args.get('entry_id', type=int)
    if not entry_id:
        return jsonify(error="entry_id required", code="MISSING_PARAM"), 400

    try:
        # Use service-role client so RLS doesn't block server-side reads
        _db = extensions.get_db()
        using_admin = extensions.supabase_admin is not None
        logger.info(f"[get_entry_photos] entry_id={entry_id} using_admin={using_admin}")

        entry_resp = _db.table("audits").select("store").eq("id", entry_id).execute()
        if not entry_resp.data:
            logger.warning(f"[get_entry_photos] entry_id={entry_id} not found in audits")
            return jsonify(error="Not found", code="NOT_FOUND"), 404

        entry_store = entry_resp.data[0].get('store')
        if not can_access_photo(entry_store, session.get('role'), session.get('store')):
            logger.warning(
                f"[get_entry_photos] Access denied: user={session.get('user')!r} "
                f"(store={session.get('store')!r}) tried entry_id={entry_id} (store={entry_store!r})"
            )
            return jsonify(error="Not authorized", code="FORBIDDEN"), 403

        photos = _db.table("z_report_photos") \
            .select("id, store, business_date, register_id, uploaded_by, uploaded_at, storage_path") \
            .eq("entry_id", entry_id) \
            .order("uploaded_at") \
            .execute()

        logger.info(
            f"[get_entry_photos] entry_id={entry_id} store={entry_store!r} "
            f"using_admin={using_admin} → {len(photos.data)} photo(s)"
        )
        return jsonify(photos.data)

    except Exception as e:
        logger.error(f"[get_entry_photos] entry_id={entry_id} EXCEPTION: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="FETCH_ERROR"), 500


@bp.route('/api/zreport/signed_url')
@require_auth()
@extensions.limiter.limit(Config.RATELIMIT_READ)
def get_photo_signed_url():
    """Return a 1-hour signed URL for a specific photo. Store-scoped IDOR check."""
    photo_id = request.args.get('photo_id', type=int)
    if not photo_id:
        return jsonify(error="photo_id required", code="MISSING_PARAM"), 400

    try:
        # Use service-role client so RLS doesn't block server-side reads
        _db = extensions.get_db()

        photo_resp = _db.table("z_report_photos").select("*").eq("id", photo_id).execute()
        if not photo_resp.data:
            logger.warning(f"[signed_url] photo_id={photo_id} not found in z_report_photos")
            return jsonify(error="Photo record not found", code="NOT_FOUND"), 404

        photo = photo_resp.data[0]
        storage_path = photo.get('storage_path', '')
        photo_store = photo.get('store')

        if not can_access_photo(photo_store, session.get('role'), session.get('store')):
            logger.warning(
                f"[signed_url] IDOR attempt: user={session.get('user')!r} "
                f"(store={session.get('store')!r}) tried photo_id={photo_id} "
                f"(store={photo_store!r})"
            )
            return jsonify(error="Not authorized", code="FORBIDDEN"), 403

        if not storage_path:
            logger.error(f"[signed_url] photo_id={photo_id} has empty storage_path")
            return jsonify(error="Photo has no storage path", code="NO_PATH"), 500

        storage_client = extensions.get_db()
        logger.info(
            f"[signed_url] Generating URL: photo_id={photo_id} "
            f"bucket=z-reports path={storage_path!r} "
            f"user={session.get('user')!r} using_admin={extensions.supabase_admin is not None}"
        )
        signed = storage_client.storage.from_(Config.STORAGE_BUCKET).create_signed_url(
            storage_path, Config.STORAGE_URL_EXPIRY_SECONDS
        )
        # storage3 v2.x returns a SignedURLResponse object; older versions returned a dict
        url = signed.signed_url if hasattr(signed, 'signed_url') else signed["signedURL"]
        if not url:
            raise ValueError("create_signed_url returned empty URL")
        logger.info(f"[signed_url] Success: photo_id={photo_id} url_prefix={url[:60]!r}")
        return jsonify(url=url)

    except Exception as e:
        logger.error(
            f"[signed_url] FAILED photo_id={photo_id}: {e}",
            exc_info=True
        )
        return jsonify(error="Internal server error", code="STORAGE_ERROR"), 500


@bp.route('/api/zreport/photo/<int:photo_id>', methods=['DELETE'])
@require_auth(['manager', 'admin', 'super_admin'])
def delete_photo(photo_id):
    """Delete a Z-report photo from storage and DB (manager/admin only)."""
    try:
        _db = extensions.get_db()
        photo_resp = _db.table("z_report_photos").select("*") \
            .eq("id", photo_id).maybe_single().execute()

        if not photo_resp.data:
            return jsonify(error="Photo not found", code="NOT_FOUND"), 404

        # IDOR check — non-admins can only delete photos from their own store
        photo_store = photo_resp.data.get('store')
        user_store = session.get('store')
        user_role = session.get('role')
        if user_role not in ('admin', 'super_admin') and photo_store != user_store:
            logger.warning(
                f"[delete_photo] IDOR attempt: user={session.get('user')!r} "
                f"(store={user_store!r}) tried photo_id={photo_id} (store={photo_store!r})"
            )
            return jsonify(error="Not authorized", code="FORBIDDEN"), 403

        # Remove from Supabase Storage (non-fatal if file already gone)
        storage_path = photo_resp.data.get('storage_path', '')
        if storage_path:
            try:
                extensions.get_db().storage.from_(Config.STORAGE_BUCKET).remove([storage_path])
                logger.info(f"[delete_photo] Removed storage file: {storage_path!r}")
            except Exception as e:
                logger.warning(f"[delete_photo] Storage removal failed (continuing): {e}")

        # Delete DB record
        _db.table("z_report_photos").delete().eq("id", photo_id).execute()
        logger.info(
            f"[delete_photo] photo_id={photo_id} deleted by {session.get('user')!r}"
        )
        return jsonify(status="deleted")

    except Exception as e:
        logger.error(f"[delete_photo] Error: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="DELETE_ERROR"), 500
