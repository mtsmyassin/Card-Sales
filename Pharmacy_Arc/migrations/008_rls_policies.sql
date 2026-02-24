-- Migration 005: Row Level Security policies
-- Run in Supabase SQL Editor (Dashboard → SQL)
-- NOTE: This app uses the service_key (admin client), so RLS is bypassed by default.
-- These policies apply when using the anon/user key (e.g., direct client access).

-- ============================================================
-- Enable RLS on both tables
-- ============================================================
ALTER TABLE audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- AUDITS: Admins see all, others see only their store
-- ============================================================

-- Policy for SELECT: staff/manager see only their store
CREATE POLICY audits_select_own_store ON audits
    FOR SELECT
    USING (
        -- Allow if user's JWT store matches OR user is admin/super_admin
        (current_setting('request.jwt.claims', true)::json->>'role') IN ('admin', 'super_admin')
        OR store = (current_setting('request.jwt.claims', true)::json->>'store')
    );

-- Policy for INSERT: any authenticated user can insert to their own store
CREATE POLICY audits_insert_own_store ON audits
    FOR INSERT
    WITH CHECK (
        (current_setting('request.jwt.claims', true)::json->>'role') IN ('admin', 'super_admin')
        OR store = (current_setting('request.jwt.claims', true)::json->>'store')
    );

-- Policy for UPDATE: managers+ can update their store, admins can update all
CREATE POLICY audits_update_own_store ON audits
    FOR UPDATE
    USING (
        (current_setting('request.jwt.claims', true)::json->>'role') IN ('admin', 'super_admin')
        OR (
            (current_setting('request.jwt.claims', true)::json->>'role') = 'manager'
            AND store = (current_setting('request.jwt.claims', true)::json->>'store')
        )
    );

-- Policy for DELETE (soft delete = UPDATE): same as UPDATE
CREATE POLICY audits_delete_own_store ON audits
    FOR DELETE
    USING (
        (current_setting('request.jwt.claims', true)::json->>'role') IN ('admin', 'super_admin')
        OR (
            (current_setting('request.jwt.claims', true)::json->>'role') = 'manager'
            AND store = (current_setting('request.jwt.claims', true)::json->>'store')
        )
    );

-- ============================================================
-- USERS: Only admins can read/modify users
-- ============================================================
CREATE POLICY users_admin_only ON users
    FOR ALL
    USING (
        (current_setting('request.jwt.claims', true)::json->>'role') IN ('admin', 'super_admin')
    );

-- ============================================================
-- SERVICE ROLE BYPASS
-- ============================================================
-- The service_key (used by our Flask app) bypasses RLS by default.
-- These policies are defense-in-depth for any direct API/client access.
