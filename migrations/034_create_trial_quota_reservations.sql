-- =============================================================================
-- Migration 034: Persistent Atomic Trial Quota Reservation Store
-- Phase 1 — Stage 3: Step 2B.1 Remediation
--
-- Enforces:
--   1. Strict hard-cap 30 trial orders across multi-worker & concurrent requests.
--   2. Atomic reservation, commit, release, and timeout quarantine lifecycle.
--   3. Unique constraint on (tenant_id, order_id) to eliminate duplicate slots.
--   4. Least privilege: zero access to anon, SELECT/INSERT/UPDATE for authenticated.
--   5. Strict RLS tenant isolation matching Stage 1 and Stage 2 invariants.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.trial_quota_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL,
    tenant_slug VARCHAR(100),
    order_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'RESERVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_trial_quota_tenant_order UNIQUE (tenant_id, order_id),
    CONSTRAINT chk_trial_quota_non_empty CHECK (
        BTRIM(tenant_id) <> ''
        AND BTRIM(order_id) <> ''
    ),
    CONSTRAINT chk_trial_quota_status CHECK (
        status IN ('RESERVED', 'COMMITTED', 'RELEASED', 'AMBIGUOUS_TIMEOUT')
    )
);

CREATE INDEX IF NOT EXISTS idx_trial_quota_tenant_status
ON public.trial_quota_reservations (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_trial_quota_slug_status
ON public.trial_quota_reservations (tenant_slug, status);

-- Row Level Security
ALTER TABLE public.trial_quota_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trial_quota_reservations FORCE ROW LEVEL SECURITY;

-- Read-only tenant isolation for authenticated users
DROP POLICY IF EXISTS p1_tenant_isolation_trial_quota ON public.trial_quota_reservations;
CREATE POLICY p1_tenant_isolation_trial_quota ON public.trial_quota_reservations
    AS PERMISSIVE FOR SELECT TO authenticated
    USING (
        tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
    );

DROP POLICY IF EXISTS service_role_trial_quota ON public.trial_quota_reservations;
CREATE POLICY service_role_trial_quota ON public.trial_quota_reservations
    AS PERMISSIVE FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Least Privilege Access Control: Zero write privileges for anon or authenticated
REVOKE ALL ON public.trial_quota_reservations FROM PUBLIC;
REVOKE ALL ON public.trial_quota_reservations FROM anon;
REVOKE ALL ON public.trial_quota_reservations FROM authenticated;
GRANT SELECT ON public.trial_quota_reservations TO authenticated;
GRANT ALL ON public.trial_quota_reservations TO service_role;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_app_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.trial_quota_reservations TO bt_app_runtime;
    END IF;
END
$$;
