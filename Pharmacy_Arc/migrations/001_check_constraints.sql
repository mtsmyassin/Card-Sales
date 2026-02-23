-- Migration 001: CHECK constraints + idempotency support
-- Run in Supabase SQL Editor (Dashboard → SQL)
-- Safe to run multiple times (IF NOT EXISTS / ADD IF NOT EXISTS)

-- ============================================================
-- AUDITS TABLE: Numeric sanity checks
-- ============================================================
ALTER TABLE audits
  ADD CONSTRAINT chk_gross_non_negative CHECK (gross >= 0);

-- Net can be negative (payouts exceed gross), so no constraint there.

-- Idempotency column for offline sync deduplication (S4)
ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS idempotency_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_audits_idempotency
  ON audits (idempotency_id)
  WHERE idempotency_id IS NOT NULL;

-- ============================================================
-- USERS TABLE: Role and store enum constraints
-- ============================================================
ALTER TABLE users
  ADD CONSTRAINT chk_role_enum
    CHECK (role IN ('staff', 'manager', 'admin', 'super_admin'));

ALTER TABLE users
  ADD CONSTRAINT chk_store_enum
    CHECK (store IN ('Carimas #1', 'Carimas #2', 'Carimas #3', 'Carthage', 'Main', 'All'));

-- ============================================================
-- AUDITS TABLE: Store enum constraint (same values)
-- ============================================================
ALTER TABLE audits
  ADD CONSTRAINT chk_audit_store_enum
    CHECK (store IN ('Carimas #1', 'Carimas #2', 'Carimas #3', 'Carthage', 'Main', 'All'));

-- ============================================================
-- AUDITS TABLE: Date format constraint (YYYY-MM-DD)
-- ============================================================
ALTER TABLE audits
  ADD CONSTRAINT chk_date_format
    CHECK (date ~ '^\d{4}-\d{2}-\d{2}$');
