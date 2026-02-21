-- Migration 002: Schema Fixes — unique entry constraint + date column
-- Run in Supabase SQL Editor

-- ── 1. Unique constraint on (date, store, reg) ───────────────────────────────
-- Prevents duplicate audit entries via race condition, Telegram+web concurrent
-- submit, or offline sync. Application-level duplicate check is kept as user
-- feedback, but this is the authoritative enforcement.
--
-- If dirty duplicates already exist, run this first to find them:
--   SELECT date, store, reg, COUNT(*) FROM audits
--   GROUP BY date, store, reg HAVING COUNT(*) > 1;
-- Then delete the extras before adding the constraint.
ALTER TABLE audits
  ADD CONSTRAINT uq_audits_date_store_reg UNIQUE (date, store, reg);

-- ── 2. Generated DATE column for range queries ────────────────────────────────
-- audits.date is stored as TEXT (ISO 8601). This generated column allows proper
-- date-range filtering, date_trunc(), and indexed comparisons without casts.
-- Zero impact on existing write paths — value is always computed from `date`.
ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS audit_date DATE
    GENERATED ALWAYS AS (date::date) STORED;

CREATE INDEX IF NOT EXISTS idx_audits_audit_date
  ON audits (audit_date);

CREATE INDEX IF NOT EXISTS idx_audits_store_audit_date
  ON audits (store, audit_date DESC);

-- ── Verify ────────────────────────────────────────────────────────────────────
SELECT constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_name = 'audits'
  AND constraint_name = 'uq_audits_date_store_reg';
