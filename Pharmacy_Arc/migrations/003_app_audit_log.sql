-- Migration 003: App-level audit log table
-- Persists AuditLogger entries to Supabase so logs survive Railway redeploys.
-- Run in Supabase SQL Editor before deploying the matching app.py changes.

-- ── 1. Create table ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS app_audit_log (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    action       TEXT        NOT NULL,
    actor        TEXT,
    role         TEXT,
    entity_type  TEXT,
    entity_id    TEXT,
    success      BOOLEAN     NOT NULL DEFAULT true,
    error        TEXT,
    before_val   JSONB,
    after_val    JSONB,
    context      JSONB,
    entry_hash   TEXT
);

-- ── 2. Indexes for common query patterns ───────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_app_audit_log_ts
    ON app_audit_log (ts DESC);

CREATE INDEX IF NOT EXISTS idx_app_audit_log_actor
    ON app_audit_log (actor, ts DESC);

CREATE INDEX IF NOT EXISTS idx_app_audit_log_action
    ON app_audit_log (action, ts DESC);

-- ── 3. Row-Level Security ──────────────────────────────────────────────────────
-- Only the service role (SUPABASE_SERVICE_KEY) may read or write.
-- The anon key used by the web front-end has no access.
ALTER TABLE app_audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON app_audit_log
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ── Verify ─────────────────────────────────────────────────────────────────────
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'app_audit_log'
ORDER BY ordinal_position;
