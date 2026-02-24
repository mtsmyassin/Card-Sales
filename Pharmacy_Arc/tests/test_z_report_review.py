"""Tests for Z Report Review utility functions and API endpoints."""
import json
import pytest
from unittest.mock import MagicMock, patch, call


# ── 1. Pure utility tests (no Flask, no DB) ───────────────────────────────────

class TestRecalculate:
    """_zr_recalculate: server-side math must match pharmacy-sales-math spec."""

    def _calc(self, breakdown, payouts=0.0, actual=0.0):
        from routes.zreports import _zr_recalculate
        return _zr_recalculate(breakdown, payouts, actual)

    def test_gross_sums_all_payment_fields(self):
        bd = {'cash': 100, 'ath': 50, 'athm': 25, 'visa': 0, 'mc': 0,
              'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0}
        r = self._calc(bd)
        assert r['gross'] == 175.0

    def test_net_equals_gross_minus_payouts(self):
        bd = {'cash': 200, 'ath': 0, 'athm': 0, 'visa': 0, 'mc': 0,
              'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0}
        r = self._calc(bd, payouts=30.0)
        assert r['net'] == 170.0

    def test_variance_formula(self):
        # variance = (actual - float) - (cash - payouts)
        bd = {'cash': 500, 'ath': 0, 'athm': 0, 'visa': 0, 'mc': 0,
              'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0, 'float': 100}
        r = self._calc(bd, payouts=20.0, actual=475.0)
        # (475 - 100) - (500 - 20) = 375 - 480 = -105
        assert r['variance'] == -105.0

    def test_default_float_is_100(self):
        bd = {'cash': 200, 'ath': 0, 'athm': 0, 'visa': 0, 'mc': 0,
              'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0}
        r = self._calc(bd, actual=200.0)
        assert r['opening_float'] == 100.0

    def test_missing_payment_fields_default_to_zero(self):
        bd = {'cash': 50}
        r = self._calc(bd)
        assert r['gross'] == 50.0

    def test_cards_excluded_from_variance_cash_calc(self):
        # variance is a cash-only check: cards don't affect it
        bd = {'cash': 300, 'visa': 999, 'ath': 0, 'athm': 0, 'mc': 0,
              'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0, 'float': 100}
        r = self._calc(bd, actual=300.0)
        # (300 - 100) - (300 - 0) = 200 - 300 = -100
        assert r['variance'] == -100.0

    def test_payouts_exceed_gross_raises(self):
        from routes.zreports import _zr_recalculate
        bd = {'cash': 10, 'ath': 0, 'athm': 0, 'visa': 0, 'mc': 0,
              'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0}
        with pytest.raises(ValueError, match="exceeds gross"):
            _zr_recalculate(bd, payouts_total=999.0, cash_actual=0.0)

    def test_values_rounded_to_two_decimals(self):
        bd = {'cash': 0.001, 'ath': 0, 'athm': 0, 'visa': 0, 'mc': 0,
              'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0}
        r = self._calc(bd)
        assert r['gross'] == round(0.001, 2)

    def test_zero_all_fields(self):
        bd = {'cash': 0, 'ath': 0, 'athm': 0, 'visa': 0, 'mc': 0,
              'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0}
        r = self._calc(bd)
        assert r == {'gross': 0.0, 'net': 0.0, 'variance': -100.0, 'opening_float': 100.0}


class TestValidateBreakdown:
    """_zr_validate_breakdown: breakdown values must sum to payouts_total."""

    def _validate(self, payouts_total, breakdown):
        from routes.zreports import _zr_validate_breakdown
        return _zr_validate_breakdown(payouts_total, breakdown)

    def test_none_breakdown_passes(self):
        self._validate(50.0, None)

    def test_empty_breakdown_passes(self):
        self._validate(50.0, {})

    def test_matching_sum_passes(self):
        self._validate(50.0, {'supplies': 30.0, 'cleaning': 20.0})

    def test_mismatched_sum_raises(self):
        from routes.zreports import _zr_validate_breakdown
        with pytest.raises(ValueError, match="breakdown sum"):
            _zr_validate_breakdown(50.0, {'supplies': 10.0})

    def test_tolerance_within_one_cent_passes(self):
        self._validate(50.0, {'a': 49.995})


# ── 2. API endpoint tests ─────────────────────────────────────────────────────

@pytest.fixture
def flask_app():
    """Create a test Flask app with Supabase clients mocked via create_client."""
    import os
    import importlib
    from config import Config
    os.environ.setdefault('SUPABASE_URL', 'https://fake.supabase.co')
    os.environ.setdefault('SUPABASE_KEY', 'fake-key')
    os.environ.setdefault('SECRET_KEY', 'test-secret')

    mock_client = MagicMock()
    with patch('supabase.create_client', return_value=mock_client), \
         patch.object(Config, 'SUPABASE_SERVICE_KEY', 'fake-service-key'), \
         patch.object(Config, 'startup_check'):
        import app as _app
        importlib.reload(_app)
        import extensions
        _app.app.config['TESTING'] = True
        _app.app.config['SECRET_KEY'] = 'test-secret'
        _app.app.config['WTF_CSRF_ENABLED'] = False
        # Routes use extensions.supabase_admin directly.
        # Exposing it on _app means tests can configure mock return values
        # via flask_app.supabase_admin and routes will see the same mock.
        _app.supabase_admin = extensions.supabase_admin
        _app.supabase = extensions.supabase
        yield _app


@pytest.fixture
def client(flask_app):
    return flask_app.app.test_client()


@pytest.fixture
def manager_session(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['user'] = 'testmanager'
        sess['role'] = 'manager'
        sess['store'] = 'Main'


@pytest.fixture
def admin_session(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['user'] = 'testadmin'
        sess['role'] = 'admin'
        sess['store'] = 'Main'


class TestZReportList:
    def test_requires_auth(self, client):
        r = client.get('/api/z-reports')
        assert r.status_code == 401

    def test_cashier_denied(self, client):
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['user'] = 'cashier1'
            sess['role'] = 'cashier'
        r = client.get('/api/z-reports')
        assert r.status_code == 403

    def test_manager_can_list(self, client, flask_app, manager_session):
        mock_result = MagicMock()
        mock_result.data = [{'id': 1, 'review_status': 'PENDING_REVIEW'}]
        # Chain: .select().is_('deleted_at', 'null').order().eq(store) for managers
        flask_app.supabase_admin.table.return_value.select.return_value \
            .is_.return_value.order.return_value.eq.return_value.execute.return_value = mock_result
        r = client.get('/api/z-reports')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data[0]['id'] == 1

    def test_status_filter_applied(self, client, flask_app, manager_session):
        mock_result = MagicMock()
        mock_result.data = []
        # Chain: .select().is_().order().eq(status_filter).eq(store) for managers
        chain = flask_app.supabase_admin.table.return_value.select.return_value \
            .is_.return_value.order.return_value
        chain.eq.return_value.eq.return_value.execute.return_value = mock_result
        r = client.get('/api/z-reports?status=FINAL_APPROVED')
        assert r.status_code == 200
        # First .eq() call should be the status filter
        chain.eq.assert_called_with('review_status', 'FINAL_APPROVED')

    def test_invalid_status_filter_ignored(self, client, flask_app, manager_session):
        mock_result = MagicMock()
        mock_result.data = []
        # No status filter, but store-scoping .eq() still added for managers
        flask_app.supabase_admin.table.return_value.select.return_value \
            .is_.return_value.order.return_value.eq.return_value.execute.return_value = mock_result
        r = client.get('/api/z-reports?status=BADSTATUS')
        assert r.status_code == 200


class TestZReportLock:
    def _audit(self, status='PENDING_REVIEW', locked_by=None, locked_at=None):
        return {
            'id': 42,
            'store': 'Main',
            'review_status': status,
            'review_locked_by': locked_by,
            'review_locked_at': locked_at,
        }

    def _setup_mock_audit(self, flask_app, audit_dict):
        mock = MagicMock()
        mock.data = audit_dict
        flask_app.supabase_admin.table.return_value.select.return_value \
            .eq.return_value.is_.return_value.single.return_value.execute.return_value = mock

    def test_lock_pending_review(self, client, flask_app, manager_session):
        self._setup_mock_audit(flask_app, self._audit())
        flask_app.supabase_admin.table.return_value.update.return_value \
            .eq.return_value.execute.return_value = MagicMock()
        flask_app.supabase_admin.table.return_value.insert.return_value \
            .execute.return_value = MagicMock()
        r = client.post('/api/z-reports/42/lock')
        assert r.status_code == 200
        assert json.loads(r.data)['ok'] is True

    def test_lock_already_approved_rejected(self, client, flask_app, manager_session):
        self._setup_mock_audit(flask_app, self._audit(status='FINAL_APPROVED'))
        r = client.post('/api/z-reports/42/lock')
        assert r.status_code == 409

    def test_lock_held_by_other_user_unexpired(self, client, flask_app, manager_session):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self._setup_mock_audit(flask_app, self._audit(
            status='IN_REVIEW', locked_by='othermanager', locked_at=recent
        ))
        r = client.post('/api/z-reports/42/lock')
        assert r.status_code == 409
        assert 'locked by' in json.loads(r.data)['error']

    def test_lock_held_by_other_expired_succeeds(self, client, flask_app, manager_session):
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        self._setup_mock_audit(flask_app, self._audit(
            status='IN_REVIEW', locked_by='othermanager', locked_at=old
        ))
        flask_app.supabase_admin.table.return_value.update.return_value \
            .eq.return_value.execute.return_value = MagicMock()
        flask_app.supabase_admin.table.return_value.insert.return_value \
            .execute.return_value = MagicMock()
        r = client.post('/api/z-reports/42/lock')
        assert r.status_code == 200

    def test_re_lock_own_audit_allowed(self, client, flask_app, manager_session):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self._setup_mock_audit(flask_app, self._audit(
            status='IN_REVIEW', locked_by='testmanager', locked_at=recent
        ))
        flask_app.supabase_admin.table.return_value.update.return_value \
            .eq.return_value.execute.return_value = MagicMock()
        flask_app.supabase_admin.table.return_value.insert.return_value \
            .execute.return_value = MagicMock()
        r = client.post('/api/z-reports/42/lock')
        assert r.status_code == 200


class TestZReportApprove:
    def _setup(self, flask_app, status='IN_REVIEW', locked_by='testmanager'):
        audit_mock = MagicMock()
        audit_mock.data = {
            'id': 1, 'store': 'Main', 'review_status': status, 'review_locked_by': locked_by,
            'payload': {'breakdown': {
                'cash': 500, 'ath': 0, 'athm': 0, 'visa': 0, 'mc': 0,
                'amex': 0, 'disc': 0, 'wic': 0, 'mcs': 0, 'sss': 0, 'float': 100
            }}
        }
        flask_app.supabase_admin.table.return_value.select.return_value \
            .eq.return_value.is_.return_value.single.return_value.execute.return_value = audit_mock
        flask_app.supabase_admin.table.return_value.update.return_value \
            .eq.return_value.execute.return_value = MagicMock()
        existing_mock = MagicMock()
        existing_mock.data = []
        flask_app.supabase_admin.table.return_value.select.return_value \
            .eq.return_value.order.return_value.limit.return_value.execute.return_value = existing_mock
        flask_app.supabase_admin.table.return_value.insert.return_value \
            .execute.return_value = MagicMock()

    def test_approve_success(self, client, flask_app, manager_session):
        self._setup(flask_app)
        r = client.post('/api/z-reports/1/approve',
                        data=json.dumps({'payouts_total': 20.0, 'cash_in_register_actual': 480.0}),
                        content_type='application/json')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data['ok'] is True
        assert data['gross'] == 500.0

    def test_approve_not_in_review(self, client, flask_app, manager_session):
        self._setup(flask_app, status='PENDING_REVIEW')
        r = client.post('/api/z-reports/1/approve',
                        data=json.dumps({}),
                        content_type='application/json')
        assert r.status_code == 409

    def test_approve_wrong_lock_holder(self, client, flask_app, manager_session):
        self._setup(flask_app, locked_by='someone_else')
        r = client.post('/api/z-reports/1/approve',
                        data=json.dumps({}),
                        content_type='application/json')
        assert r.status_code == 403

    def test_approve_breakdown_mismatch(self, client, flask_app, manager_session):
        self._setup(flask_app)
        r = client.post('/api/z-reports/1/approve',
                        data=json.dumps({
                            'payouts_total': 50.0,
                            'cash_in_register_actual': 450.0,
                            'payouts_breakdown': {'supplies': 10.0}  # sum=10, not 50
                        }),
                        content_type='application/json')
        assert r.status_code == 400
        assert 'breakdown sum' in json.loads(r.data)['error']

    def test_approve_payouts_exceed_gross(self, client, flask_app, manager_session):
        self._setup(flask_app)
        r = client.post('/api/z-reports/1/approve',
                        data=json.dumps({'payouts_total': 9999.0, 'cash_in_register_actual': 0.0}),
                        content_type='application/json')
        assert r.status_code == 400
        assert 'exceeds gross' in json.loads(r.data)['error']

    def test_cashier_cannot_approve(self, client, flask_app):
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['user'] = 'cashier1'
            sess['role'] = 'cashier'
        r = client.post('/api/z-reports/1/approve',
                        data=json.dumps({}),
                        content_type='application/json')
        assert r.status_code == 403


class TestZReportRejectAmend:
    def _setup_audit(self, flask_app, status, locked_by='testmanager'):
        m = MagicMock()
        m.data = {'id': 1, 'store': 'Main', 'review_status': status, 'review_locked_by': locked_by}
        flask_app.supabase_admin.table.return_value.select.return_value \
            .eq.return_value.is_.return_value.single.return_value.execute.return_value = m
        flask_app.supabase_admin.table.return_value.update.return_value \
            .eq.return_value.execute.return_value = MagicMock()
        existing = MagicMock()
        existing.data = []
        flask_app.supabase_admin.table.return_value.select.return_value \
            .eq.return_value.order.return_value.limit.return_value.execute.return_value = existing
        flask_app.supabase_admin.table.return_value.insert.return_value \
            .execute.return_value = MagicMock()

    def test_reject_requires_reason(self, client, flask_app, manager_session):
        self._setup_audit(flask_app, 'IN_REVIEW')
        r = client.post('/api/z-reports/1/reject',
                        data=json.dumps({}),
                        content_type='application/json')
        assert r.status_code == 400
        assert 'rejection_reason' in json.loads(r.data)['error']

    def test_reject_success(self, client, flask_app, manager_session):
        self._setup_audit(flask_app, 'IN_REVIEW')
        r = client.post('/api/z-reports/1/reject',
                        data=json.dumps({'rejection_reason': 'Cash figure wrong'}),
                        content_type='application/json')
        assert r.status_code == 200

    def test_amend_requires_admin(self, client, flask_app, manager_session):
        r = client.post('/api/z-reports/1/amend',
                        data=json.dumps({'amendment_reason': 'Fix entry'}),
                        content_type='application/json')
        assert r.status_code == 403

    def test_amend_only_final_approved(self, client, flask_app, admin_session):
        self._setup_audit(flask_app, 'PENDING_REVIEW')
        r = client.post('/api/z-reports/1/amend',
                        data=json.dumps({'amendment_reason': 'Fix entry'}),
                        content_type='application/json')
        assert r.status_code == 409
