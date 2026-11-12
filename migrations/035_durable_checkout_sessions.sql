-- =============================================================================
-- Migration 035: Durable Checkout Sessions Store (Review-Only Remediation Artifact)
-- Workstream: BT-CORE-CHECKOUT-RECOVERY-001 (Workstream B & D)
--
-- Purpose:
--   1. Move checkout session authority, QR payload, unique_code lock, expiry,
--      and revocation state from process RAM into PostgreSQL.
--   2. Enable cross-worker & post-restart invoice polling without touching or
--      locking public.orders DDL.
--   3. Prevent concurrent unique-code (100-999) collisions per
--      (tenant_id, base_amount, unique_code) while ACTIVE and unrevoked.
--   4. Enforce strict P1 RLS (FORCE ROW LEVEL SECURITY, zero wildcard policies)
--      and least-privilege grants.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.checkout_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id VARCHAR(128) NOT NULL UNIQUE REFERENCES public.orders(id) ON DELETE CASCADE,
    tenant_id VARCHAR(100) NOT NULL,
    canonical_tenant_id VARCHAR(100) NOT NULL,
    tenant_slug VARCHAR(128) NOT NULL,
    sku_id VARCHAR(255) NOT NULL,
    base_amount BIGINT NOT NULL,
    unique_code INT NOT NULL DEFAULT 0,
    total_amount BIGINT NOT NULL,
    qr_string TEXT NOT NULL,
    session_state VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    jti VARCHAR(128) NOT NULL,
    cs_key_id VARCHAR(64) NOT NULL,
    iat_epoch BIGINT NOT NULL,
    exp_epoch BIGINT NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,
    revocation_reason VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    settled_at TIMESTAMPTZ,
    CONSTRAINT uq_checkout_sessions_jti UNIQUE (jti),
    CONSTRAINT chk_checkout_sessions_non_blank CHECK (
        BTRIM(order_id) <> ''
        AND BTRIM(tenant_id) <> ''
        AND BTRIM(canonical_tenant_id) <> ''
        AND BTRIM(tenant_slug) <> ''
        AND BTRIM(sku_id) <> ''
        AND BTRIM(jti) <> ''
        AND BTRIM(cs_key_id) <> ''
    ),
    CONSTRAINT chk_checkout_sessions_amounts CHECK (
        base_amount >= 0
        AND total_amount > 0
        AND total_amount = base_amount + unique_code
    ),
    CONSTRAINT chk_checkout_sessions_unique_code CHECK (
        unique_code = 0 OR (unique_code >= 100 AND unique_code <= 999)
    ),
    CONSTRAINT chk_checkout_sessions_state CHECK (
        session_state IN ('ACTIVE', 'SETTLED', 'EXPIRED', 'REVOKED', 'CANCELLED')
    ),
    CONSTRAINT chk_checkout_sessions_epoch_bounds CHECK (
        iat_epoch > 0 AND exp_epoch >= iat_epoch
    )
);

-- DB-enforced exclusion of duplicate active unique codes for the same (tenant_id, base_amount)
CREATE UNIQUE INDEX IF NOT EXISTS uq_checkout_sessions_active_unique_amount
ON public.checkout_sessions (tenant_id, base_amount, unique_code)
WHERE (session_state = 'ACTIVE' AND revoked = FALSE AND unique_code > 0);

-- Fast amount-based lookup for inbound mutasi / unkeyed reconciliation
CREATE INDEX IF NOT EXISTS idx_checkout_sessions_total_amount_active
ON public.checkout_sessions (total_amount, created_at DESC)
WHERE (session_state = 'ACTIVE' AND revoked = FALSE);

-- Expiry / cleanup index
CREATE INDEX IF NOT EXISTS idx_checkout_sessions_tenant_state_expires
ON public.checkout_sessions (tenant_id, session_state, expires_at);

-- Row Level Security (Strict P1, zero USING (true) / WITH CHECK (true) wildcards)
ALTER TABLE public.checkout_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkout_sessions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p1_tenant_isolation_checkout_sessions ON public.checkout_sessions;
CREATE POLICY p1_tenant_isolation_checkout_sessions ON public.checkout_sessions
    AS PERMISSIVE FOR SELECT TO authenticated
    USING (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
        AND (
            tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR canonical_tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR (
                current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                AND canonical_tenant_id = LOWER(current_setting('app.current_tenant_id', true))
            )
        )
    );

DROP POLICY IF EXISTS service_role_all_checkout_sessions ON public.checkout_sessions;
CREATE POLICY service_role_all_checkout_sessions ON public.checkout_sessions
    AS PERMISSIVE FOR ALL TO service_role
    USING (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR canonical_tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR (
            current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            AND canonical_tenant_id = LOWER(current_setting('app.current_tenant_id', true))
        )
    )
    WITH CHECK (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR canonical_tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR (
            current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            AND canonical_tenant_id = LOWER(current_setting('app.current_tenant_id', true))
        )
    );

-- Least privilege grants (idempotent; tolerate environments without anon/authenticated if run standalone)
REVOKE ALL ON public.checkout_sessions FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.checkout_sessions FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.checkout_sessions FROM authenticated;
        GRANT SELECT ON public.checkout_sessions TO authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON public.checkout_sessions TO service_role;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_app_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.checkout_sessions TO bt_app_runtime;
    END IF;
END
$$;

COMMIT;

