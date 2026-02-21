-- Migration 001: Z Report Review & Approval
-- Run in Supabase SQL Editor

-- ── 1. Extend audits ──────────────────────────────────────────────────────────
ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS review_status    TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
  ADD COLUMN IF NOT EXISTS review_locked_by TEXT,
  ADD COLUMN IF NOT EXISTS review_locked_at TIMESTAMPTZ;

ALTER TABLE audits
  ADD CONSTRAINT chk_audits_review_status
  CHECK (review_status IN (
    'NEEDS_ASSIGNMENT','PENDING_REVIEW','IN_REVIEW',
    'FINAL_APPROVED','REJECTED','DUPLICATE','AMENDED'
  ));

CREATE INDEX IF NOT EXISTS idx_audits_review_status ON audits (review_status);
CREATE INDEX IF NOT EXISTS idx_audits_store_date    ON audits (store, date);
CREATE INDEX IF NOT EXISTS idx_audits_locked_at     ON audits (review_locked_at)
  WHERE review_status = 'IN_REVIEW';

-- ── 2. z_report_reviews ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS z_report_reviews (
  id                      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id                INTEGER       NOT NULL REFERENCES audits(id) ON DELETE RESTRICT,
  payouts_total           NUMERIC(12,2) NOT NULL CHECK (payouts_total >= 0),
  cash_in_register_actual NUMERIC(12,2) NOT NULL CHECK (cash_in_register_actual >= 0),
  payouts_breakdown       JSONB,
  manager_notes           TEXT,
  calculated_gross        NUMERIC(12,2) NOT NULL,
  calculated_net          NUMERIC(12,2) NOT NULL,
  calculated_variance     NUMERIC(12,2) NOT NULL,
  opening_float_used      NUMERIC(12,2) NOT NULL,
  reviewed_by             TEXT          NOT NULL,
  reviewed_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
  approved_ip             TEXT,
  action                  TEXT          NOT NULL
    CHECK (action IN ('APPROVED','REJECTED','AMENDED')),
  rejection_reason        TEXT,
  amendment_reason        TEXT,
  amendment_of_id         UUID          REFERENCES z_report_reviews(id),
  version                 INTEGER       NOT NULL DEFAULT 1,
  is_current              BOOLEAN       NOT NULL DEFAULT true,
  CONSTRAINT chk_no_self_ref   CHECK (amendment_of_id IS DISTINCT FROM id),
  CONSTRAINT chk_reject_reason CHECK (action != 'REJECTED' OR rejection_reason IS NOT NULL),
  CONSTRAINT chk_amend_reason  CHECK (action != 'AMENDED'  OR amendment_reason IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_zrr_one_current
  ON z_report_reviews (audit_id) WHERE is_current = true;
CREATE INDEX IF NOT EXISTS idx_zrr_audit_current ON z_report_reviews (audit_id, is_current);
CREATE INDEX IF NOT EXISTS idx_zrr_audit_version ON z_report_reviews (audit_id, version DESC);

-- ── 3. z_report_audit_log ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS z_report_audit_log (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type    TEXT        NOT NULL DEFAULT 'audit',
  audit_id       INTEGER     NOT NULL,
  action         TEXT        NOT NULL
    CHECK (action IN ('CREATE','STATUS_CHANGE','APPROVE','REJECT','AMEND','ASSIGN','LOCK','UNLOCK')),
  actor_username TEXT,
  actor_ip       TEXT,
  ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
  old_val        JSONB,
  new_val        JSONB,
  reason         TEXT
);

CREATE INDEX IF NOT EXISTS idx_zral_audit_ts  ON z_report_audit_log (audit_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_zral_action_ts ON z_report_audit_log (action, ts DESC);

-- ── 4. RLS ────────────────────────────────────────────────────────────────────
ALTER TABLE z_report_reviews  ENABLE ROW LEVEL SECURITY;
ALTER TABLE z_report_audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_reviews"
  ON z_report_reviews FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all_log"
  ON z_report_audit_log FOR ALL USING (auth.role() = 'service_role');

-- ── 5. Verify ─────────────────────────────────────────────────────────────────
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('z_report_reviews','z_report_audit_log')
ORDER BY table_name;
