"""Z-Report Review Blueprint — lock/unlock/approve/reject/amend/history."""
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, session
import extensions
from helpers.auth_utils import require_auth, is_admin_role
from config import Config

logger = logging.getLogger(__name__)
bp = Blueprint('zreports', __name__)

_ZR_PAYMENT_FIELDS = ['cash', 'ath', 'athm', 'visa', 'mc', 'amex', 'disc', 'wic', 'mcs', 'sss']

VALID_REVIEW_STATUSES = (
    'NEEDS_ASSIGNMENT', 'PENDING_REVIEW', 'IN_REVIEW',
    'FINAL_APPROVED', 'REJECTED', 'DUPLICATE', 'AMENDED'
)


def _zr_recalculate(breakdown: dict, payouts_total: float, cash_actual: float) -> dict:
    """Recalculate gross, net, variance from raw breakdown. Raises ValueError on bad data."""
    opening_float = float(breakdown.get('float', Config.DEFAULT_OPENING_FLOAT))
    cash = float(breakdown.get('cash', 0))
    gross = sum(float(breakdown.get(f, 0)) for f in _ZR_PAYMENT_FIELDS)
    net = gross - payouts_total
    variance = (cash_actual - opening_float) - (cash - payouts_total)
    if payouts_total > gross + 0.01:
        raise ValueError(f"payouts_total {payouts_total:.2f} exceeds gross {gross:.2f}")
    return {
        'gross': round(gross, 2),
        'net': round(net, 2),
        'variance': round(variance, 2),
        'opening_float': round(opening_float, 2),
    }


def _zr_validate_breakdown(payouts_total: float, payouts_breakdown: dict | None) -> None:
    """Assert payouts_breakdown values sum to payouts_total. Raises ValueError on mismatch."""
    if not payouts_breakdown:
        return
    total = sum(float(v) for v in payouts_breakdown.values())
    if abs(total - payouts_total) > 0.01:
        raise ValueError(
            f"payouts_breakdown sum {total:.2f} != payouts_total {payouts_total:.2f}"
        )


def _zr_log(db_client, audit_id: int, action: str, actor: str,
            ip: str = None, old_val: dict = None, new_val: dict = None,
            reason: str = None) -> None:
    """Append a row to z_report_audit_log. Swallows errors to avoid blocking main flow."""
    try:
        db_client.table('z_report_audit_log').insert({
            'audit_id': audit_id,
            'action': action,
            'actor_username': actor,
            'actor_ip': ip,
            'old_val': old_val,
            'new_val': new_val,
            'reason': reason,
        }).execute()
    except Exception as e:
        logger.error(f"[zr_log] Failed to write audit log for audit_id={audit_id}: {e}")


def _check_manager_store(audit_data: dict) -> tuple[bool, str]:
    """Check if a manager user is allowed to access this audit's store.

    Returns (ok, error_message). ok=True means access is allowed.
    """
    if session.get('role') == 'manager' and audit_data.get('store') != session.get('store'):
        return False, "You can only review entries for your store"
    return True, ""


def _zr_compensate(db, audit_id: int, old_status: str,
                   old_locked_by, old_locked_at,
                   completed_steps: list) -> None:
    """Best-effort compensating rollback for a failed multi-step Z-report operation.

    Iterates completed_steps in reverse and undoes each one.
    Logs CRITICAL if any rollback step itself fails (manual intervention needed).
    """
    for step_name, step_id in reversed(completed_steps):
        try:
            if step_name == 'update_audit_status':
                db.table('audits').update({
                    'review_status': old_status,
                    'review_locked_by': old_locked_by,
                    'review_locked_at': old_locked_at,
                }).eq('id', audit_id).execute()
            elif step_name == 'insert_review' and step_id is not None:
                db.table('z_report_reviews').delete().eq('id', step_id).execute()
            elif step_name == 'deactivate_old_review':
                # Re-activate the most recent review that was deactivated
                latest = db.table('z_report_reviews').select('id').eq(
                    'audit_id', audit_id).order('version', desc=True).limit(1).execute()
                if latest.data:
                    db.table('z_report_reviews').update({'is_current': True}).eq(
                        'id', latest.data[0]['id']).execute()
            logger.info("[zr_compensate] Rolled back step %s for audit_id=%d", step_name, audit_id)
        except Exception as rollback_err:
            logger.critical(
                "[zr_compensate] ROLLBACK FAILED for step %s audit_id=%d: %s — MANUAL INTERVENTION REQUIRED",
                step_name, audit_id, rollback_err,
            )


def _zr_next_version(db, audit_id: int) -> int:
    """Return the next review version number for an audit."""
    existing = db.table('z_report_reviews').select('version').eq(
        'audit_id', audit_id).order('version', desc=True).limit(1).execute()
    return (existing.data[0]['version'] + 1) if existing.data else 1


@bp.route('/api/z-reports')
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_READ)
def zr_list():
    """List audits with review status, optional ?status= filter."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    status_filter = request.args.get('status')
    try:
        q = db.table('audits').select(
            'id,store,date,review_status,review_locked_by,review_locked_at'
        ).order('date', desc=True)
        if status_filter and status_filter in VALID_REVIEW_STATUSES:
            q = q.eq('review_status', status_filter)
        # Store-scoping: managers only see their own store's audits
        if session.get('role') == 'manager':
            q = q.eq('store', session.get('store'))
        result = q.execute()
        return jsonify(result.data)
    except Exception as e:
        logger.error(f"[zr_list] {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>')
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_READ)
def zr_detail(audit_id: int):
    """Return audit row plus current review record."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    try:
        audit = db.table('audits').select('*').eq('id', audit_id).single().execute()
        ok, err = _check_manager_store(audit.data)
        if not ok:
            return jsonify(error=err, code="STORE_MISMATCH"), 403
        review = db.table('z_report_reviews').select('*').eq(
            'audit_id', audit_id).eq('is_current', True).maybe_single().execute()
        return jsonify({'audit': audit.data, 'review': review.data if review else None})
    except Exception as e:
        logger.error(f"[zr_detail] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>/lock', methods=['POST'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def zr_lock(audit_id: int):
    """Lock an audit for review by the current user."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    actor = session['user']
    ip = request.remote_addr
    try:
        audit = db.table('audits').select(
            'id,store,review_status,review_locked_by,review_locked_at'
        ).eq('id', audit_id).single().execute().data

        ok, err = _check_manager_store(audit)
        if not ok:
            return jsonify(error=err, code="STORE_MISMATCH"), 403

        status = audit['review_status']
        locked_by = audit.get('review_locked_by')
        locked_at = audit.get('review_locked_at')

        if status in ('PENDING_REVIEW', 'NEEDS_ASSIGNMENT'):
            pass  # always lockable
        elif status == 'IN_REVIEW':
            if locked_by == actor:
                pass  # re-locking own audit is fine
            else:
                # Another user holds the lock — check if it's expired
                lock_time = datetime.fromisoformat(
                    locked_at.replace('Z', '+00:00')
                ) if locked_at else None
                if lock_time and datetime.now(timezone.utc) - lock_time < timedelta(minutes=Config.ZREPORT_LOCK_TIMEOUT_MINUTES):
                    return jsonify(
                        error=f"Audit is locked by {locked_by}",
                        code="CONFLICT",
                    ), 409
                # Lock expired — allow stealing it
        else:
            return jsonify(error=f"Cannot lock audit in status '{status}'", code="CONFLICT"), 409

        old_status = audit['review_status']
        db.table('audits').update({
            'review_status': 'IN_REVIEW',
            'review_locked_by': actor,
            'review_locked_at': datetime.now(timezone.utc).isoformat(),
        }).eq('id', audit_id).execute()

        _zr_log(db, audit_id, 'LOCK', actor, ip=ip,
                old_val={'review_status': old_status},
                new_val={'review_status': 'IN_REVIEW', 'locked_by': actor})
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_lock] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>/lock', methods=['DELETE'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def zr_unlock(audit_id: int):
    """Release the review lock on an audit."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    actor = session['user']
    role = session.get('role')
    ip = request.remote_addr
    try:
        audit = db.table('audits').select(
            'id,review_status,review_locked_by'
        ).eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'IN_REVIEW':
            return jsonify(error="Audit is not IN_REVIEW", code="CONFLICT"), 409

        if audit['review_locked_by'] != actor and not is_admin_role(role):
            return jsonify(error="You do not hold the lock on this audit", code="FORBIDDEN"), 403

        db.table('audits').update({
            'review_status': 'PENDING_REVIEW',
            'review_locked_by': None,
            'review_locked_at': None,
        }).eq('id', audit_id).execute()

        _zr_log(db, audit_id, 'UNLOCK', actor, ip=ip,
                old_val={'locked_by': audit['review_locked_by']},
                new_val={'review_status': 'PENDING_REVIEW'})
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_unlock] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>/approve', methods=['POST'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def zr_approve(audit_id: int):
    """Approve a Z Report. Recalculates figures server-side."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    actor = session['user']
    ip = request.remote_addr
    body = request.get_json(force=True) or {}

    payouts_total = float(body.get('payouts_total', 0))
    cash_actual = float(body.get('cash_in_register_actual', 0))
    payouts_breakdown = body.get('payouts_breakdown')
    manager_notes = body.get('manager_notes', '')

    try:
        _zr_validate_breakdown(payouts_total, payouts_breakdown)
    except ValueError as e:
        return jsonify(error=str(e), code="INVALID_INPUT"), 400

    try:
        audit = db.table('audits').select('*').eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'IN_REVIEW':
            return jsonify(error=f"Audit is not IN_REVIEW (status: {audit['review_status']})", code="CONFLICT"), 409
        if audit.get('review_locked_by') != actor:
            return jsonify(error="You do not hold the lock on this audit", code="FORBIDDEN"), 403
        ok, err = _check_manager_store(audit)
        if not ok:
            return jsonify(error=err, code="STORE_MISMATCH"), 403

        breakdown = (audit.get('payload') or {}).get('breakdown', {})
        try:
            calc = _zr_recalculate(breakdown, payouts_total, cash_actual)
        except ValueError as e:
            return jsonify(error=str(e), code="INVALID_INPUT"), 400

        old_status = audit['review_status']
        completed_steps = []

        try:
            # Step 1: Mark previous review as not current
            db.table('z_report_reviews').update({'is_current': False}).eq(
                'audit_id', audit_id).eq('is_current', True).execute()
            completed_steps.append(('deactivate_old_review', audit_id))

            next_version = _zr_next_version(db, audit_id)

            # Step 2: Insert new review
            new_review = db.table('z_report_reviews').insert({
                'audit_id': audit_id,
                'payouts_total': payouts_total,
                'cash_in_register_actual': cash_actual,
                'payouts_breakdown': payouts_breakdown,
                'manager_notes': manager_notes,
                'calculated_gross': calc['gross'],
                'calculated_net': calc['net'],
                'calculated_variance': calc['variance'],
                'opening_float_used': calc['opening_float'],
                'reviewed_by': actor,
                'approved_ip': ip,
                'action': 'APPROVED',
                'version': next_version,
                'is_current': True,
            }).execute()
            new_review_id = new_review.data[0]['id'] if new_review.data else None
            completed_steps.append(('insert_review', new_review_id))

            # Step 3: Update audit status
            db.table('audits').update({
                'review_status': 'FINAL_APPROVED',
                'review_locked_by': None,
                'review_locked_at': None,
            }).eq('id', audit_id).execute()
            completed_steps.append(('update_audit_status', audit_id))

        except Exception as step_err:
            logger.error(f"[zr_approve] Failed mid-transaction audit_id={audit_id}: {step_err}", exc_info=True)
            _zr_compensate(db, audit_id, old_status, audit.get('review_locked_by'),
                           audit.get('review_locked_at'), completed_steps)
            return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500

        _zr_log(db, audit_id, 'APPROVE', actor, ip=ip,
                old_val={'review_status': old_status},
                new_val={'review_status': 'FINAL_APPROVED', 'gross': calc['gross'],
                         'net': calc['net'], 'variance': calc['variance']})
        return jsonify(ok=True, **calc)
    except Exception as e:
        logger.error(f"[zr_approve] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>/reject', methods=['POST'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def zr_reject(audit_id: int):
    """Reject a Z Report with a mandatory reason."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    actor = session['user']
    ip = request.remote_addr
    body = request.get_json(force=True) or {}
    reason = (body.get('rejection_reason') or '').strip()
    if not reason:
        return jsonify(error="rejection_reason is required", code="MISSING_PARAM"), 400

    try:
        audit = db.table('audits').select(
            'id,store,review_status,review_locked_by,review_locked_at'
        ).eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'IN_REVIEW':
            return jsonify(error=f"Audit is not IN_REVIEW (status: {audit['review_status']})", code="CONFLICT"), 409
        if audit.get('review_locked_by') != actor:
            return jsonify(error="You do not hold the lock on this audit", code="FORBIDDEN"), 403
        ok, err = _check_manager_store(audit)
        if not ok:
            return jsonify(error=err, code="STORE_MISMATCH"), 403

        old_status = audit['review_status']
        completed_steps = []

        try:
            next_version = _zr_next_version(db, audit_id)

            # Step 1: Deactivate old review
            db.table('z_report_reviews').update({'is_current': False}).eq(
                'audit_id', audit_id).eq('is_current', True).execute()
            completed_steps.append(('deactivate_old_review', audit_id))

            # Step 2: Insert new review
            new_review = db.table('z_report_reviews').insert({
                'audit_id': audit_id,
                'payouts_total': 0,
                'cash_in_register_actual': 0,
                'calculated_gross': 0,
                'calculated_net': 0,
                'calculated_variance': 0,
                'opening_float_used': Config.DEFAULT_OPENING_FLOAT,
                'reviewed_by': actor,
                'approved_ip': ip,
                'action': 'REJECTED',
                'rejection_reason': reason,
                'version': next_version,
                'is_current': True,
            }).execute()
            new_review_id = new_review.data[0]['id'] if new_review.data else None
            completed_steps.append(('insert_review', new_review_id))

            # Step 3: Update audit status
            db.table('audits').update({
                'review_status': 'REJECTED',
                'review_locked_by': None,
                'review_locked_at': None,
            }).eq('id', audit_id).execute()
            completed_steps.append(('update_audit_status', audit_id))

        except Exception as step_err:
            logger.error(f"[zr_reject] Failed mid-transaction audit_id={audit_id}: {step_err}", exc_info=True)
            _zr_compensate(db, audit_id, old_status, audit.get('review_locked_by'),
                           audit.get('review_locked_at'), completed_steps)
            return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500

        _zr_log(db, audit_id, 'REJECT', actor, ip=ip,
                old_val={'review_status': old_status},
                new_val={'review_status': 'REJECTED'},
                reason=reason)
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_reject] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>/reopen', methods=['POST'])
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def zr_reopen(audit_id: int):
    """Reopen a REJECTED audit back to PENDING_REVIEW so it can be re-reviewed."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    actor = session['user']
    ip = request.remote_addr
    body = request.get_json(force=True) or {}
    reason = (body.get('reason') or '').strip()
    if not reason:
        return jsonify(error="reason is required", code="MISSING_PARAM"), 400

    try:
        audit = db.table('audits').select(
            'id,store,review_status'
        ).eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'REJECTED':
            return jsonify(error=f"Audit is not REJECTED (status: {audit['review_status']})", code="CONFLICT"), 409
        ok, err = _check_manager_store(audit)
        if not ok:
            return jsonify(error=err, code="STORE_MISMATCH"), 403

        db.table('audits').update({
            'review_status': 'PENDING_REVIEW',
            'review_locked_by': None,
            'review_locked_at': None,
        }).eq('id', audit_id).execute()

        _zr_log(db, audit_id, 'REOPEN', actor, ip=ip,
                old_val={'review_status': 'REJECTED'},
                new_val={'review_status': 'PENDING_REVIEW'},
                reason=reason)
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_reopen] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>/amend', methods=['POST'])
@require_auth(allowed_roles=['admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def zr_amend(audit_id: int):
    """Reopen a FINAL_APPROVED audit for amendment (admin only)."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    actor = session['user']
    ip = request.remote_addr
    body = request.get_json(force=True) or {}
    reason = (body.get('amendment_reason') or '').strip()
    if not reason:
        return jsonify(error="amendment_reason is required", code="MISSING_PARAM"), 400

    try:
        audit = db.table('audits').select(
            'id,review_status,review_locked_by,review_locked_at'
        ).eq('id', audit_id).single().execute().data

        if audit['review_status'] != 'FINAL_APPROVED':
            return jsonify(
                error=f"Can only amend FINAL_APPROVED audits (status: {audit['review_status']})",
                code="CONFLICT"
            ), 409

        # Get current review row to link amendment chain
        current = db.table('z_report_reviews').select('id,version').eq(
            'audit_id', audit_id).eq('is_current', True).maybe_single().execute()
        current_data = current.data if current else None
        amendment_of_id = current_data['id'] if current_data else None
        next_version = (current_data['version'] + 1) if current_data else 1

        old_status = audit['review_status']
        completed_steps = []

        try:
            # Step 1: Deactivate old review
            db.table('z_report_reviews').update({'is_current': False}).eq(
                'audit_id', audit_id).eq('is_current', True).execute()
            completed_steps.append(('deactivate_old_review', audit_id))

            # Step 2: Insert new review
            new_review = db.table('z_report_reviews').insert({
                'audit_id': audit_id,
                'payouts_total': 0,
                'cash_in_register_actual': 0,
                'calculated_gross': 0,
                'calculated_net': 0,
                'calculated_variance': 0,
                'opening_float_used': Config.DEFAULT_OPENING_FLOAT,
                'reviewed_by': actor,
                'approved_ip': ip,
                'action': 'AMENDED',
                'amendment_reason': reason,
                'amendment_of_id': amendment_of_id,
                'version': next_version,
                'is_current': True,
            }).execute()
            new_review_id = new_review.data[0]['id'] if new_review.data else None
            completed_steps.append(('insert_review', new_review_id))

            # Step 3: Update audit status
            db.table('audits').update({
                'review_status': 'PENDING_REVIEW',
                'review_locked_by': None,
                'review_locked_at': None,
            }).eq('id', audit_id).execute()
            completed_steps.append(('update_audit_status', audit_id))

        except Exception as step_err:
            logger.error(f"[zr_amend] Failed mid-transaction audit_id={audit_id}: {step_err}", exc_info=True)
            _zr_compensate(db, audit_id, old_status, audit.get('review_locked_by'),
                           audit.get('review_locked_at'), completed_steps)
            return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500

        _zr_log(db, audit_id, 'AMEND', actor, ip=ip,
                old_val={'review_status': 'FINAL_APPROVED'},
                new_val={'review_status': 'PENDING_REVIEW'},
                reason=reason)
        return jsonify(ok=True)
    except Exception as e:
        logger.error(f"[zr_amend] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>/history')
@require_auth(allowed_roles=['manager', 'admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_READ)
def zr_history(audit_id: int):
    """Return all review records for an audit, newest first."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    try:
        # Store-scoping: managers can only view history for their own store's audits
        audit = db.table('audits').select('id,store').eq('id', audit_id).maybe_single().execute()
        if not audit.data:
            return jsonify(error="Audit not found", code="NOT_FOUND"), 404
        ok, err = _check_manager_store(audit.data)
        if not ok:
            return jsonify(error=err, code="STORE_MISMATCH"), 403

        result = db.table('z_report_reviews').select('*').eq(
            'audit_id', audit_id).order('version', desc=True).execute()
        return jsonify(result.data)
    except Exception as e:
        logger.error(f"[zr_history] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/<int:audit_id>/audit-log')
@require_auth(allowed_roles=['admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_READ)
def zr_audit_log(audit_id: int):
    """Return the audit trail for a Z Report (admin only)."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    try:
        result = db.table('z_report_audit_log').select('*').eq(
            'audit_id', audit_id).order('ts', desc=True).execute()
        return jsonify(result.data)
    except Exception as e:
        logger.error(f"[zr_audit_log] audit_id={audit_id}: {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500


@bp.route('/api/z-reports/unlock-timed-out', methods=['POST'])
@require_auth(allowed_roles=['admin', 'super_admin'])
@extensions.limiter.limit(Config.RATELIMIT_WRITE)
def zr_unlock_timed_out():
    """Release all locks older than the configured timeout (admin cron / manual trigger)."""
    db = extensions.get_db()
    if db is None:
        return jsonify(error="Z-report review service unavailable", code="SERVICE_UNAVAILABLE"), 503
    actor = session['user']
    ip = request.remote_addr
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=Config.ZREPORT_LOCK_TIMEOUT_MINUTES)).isoformat()
    try:
        stale = db.table('audits').select('id,review_locked_by').eq(
            'review_status', 'IN_REVIEW').lt('review_locked_at', cutoff).execute()
        count = 0
        for row in stale.data:
            db.table('audits').update({
                'review_status': 'PENDING_REVIEW',
                'review_locked_by': None,
                'review_locked_at': None,
            }).eq('id', row['id']).execute()
            _zr_log(db, row['id'], 'UNLOCK', actor, ip=ip,
                    old_val={'locked_by': row['review_locked_by']},
                    new_val={'review_status': 'PENDING_REVIEW'},
                    reason='lock_timeout')
            count += 1
        return jsonify(ok=True, unlocked=count)
    except Exception as e:
        logger.error(f"[zr_unlock_timed_out] {e}", exc_info=True)
        return jsonify(error="Internal server error", code="INTERNAL_ERROR"), 500
