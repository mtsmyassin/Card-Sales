-- Migration 003: Soft deletes + updated_at tracking
-- Run in Supabase SQL Editor (Dashboard → SQL)

-- Track when records were last modified
ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

-- Soft delete: NULL means active, non-NULL means deleted
ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS deleted_at timestamptz DEFAULT NULL;

-- Auto-update updated_at on any row change
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audits_updated_at ON audits;
CREATE TRIGGER trg_audits_updated_at
  BEFORE UPDATE ON audits
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at();

-- Index for filtering out soft-deleted records efficiently
CREATE INDEX IF NOT EXISTS idx_audits_not_deleted
  ON audits (id) WHERE deleted_at IS NULL;
