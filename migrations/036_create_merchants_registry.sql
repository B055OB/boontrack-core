-- =============================================================================
-- Migration 036: Transactional Merchants Registry (PR #29 Auth/Registration)
-- CANDIDATE ONLY — DO NOT EXECUTE ON REMOTE DB BEFORE SHARED-DB RECONCILIATION.
--
-- Purpose:
--   1. Idempotently create public.merchants matching app/routes/auth_routes.py
--      and scripts/init_test_postgres_schema.py.
--   2. Enforce strict P1 Row Level Security (ENABLE + FORCE ROW LEVEL SECURITY)
--      with zero wildcard USING (true) / WITH CHECK (true) policies.
--   3. Apply least-privilege grants (anon revoked, authenticated SELECT-only on
--      own tenant slug, service_role scoped/administrative access).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.merchants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR UNIQUE NOT NULL,
    store_name VARCHAR NOT NULL,
    business_category VARCHAR DEFAULT 'Retail / E-Commerce',
    owner_name VARCHAR NOT NULL,
    owner_whatsapp VARCHAR DEFAULT '',
    owner_email VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'ACTIVE',
    plan_tier VARCHAR DEFAULT 'STARTER',
    is_otp_verified BOOLEAN NOT NULL DEFAULT FALSE,
    active_until TIMESTAMPTZ,
    referral_code VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Additive idempotent column guards for environments with partial legacy tables
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS business_category VARCHAR DEFAULT 'Retail / E-Commerce';
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS owner_whatsapp VARCHAR DEFAULT '';
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS plan_tier VARCHAR DEFAULT 'STARTER';
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS is_otp_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS active_until TIMESTAMPTZ;
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS referral_code VARCHAR;
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS idx_merchants_slug_unique ON public.merchants (slug);
CREATE UNIQUE INDEX IF NOT EXISTS idx_merchants_slug_lower_unique ON public.merchants (lower(slug));
CREATE INDEX IF NOT EXISTS idx_merchants_status ON public.merchants (status);
CREATE INDEX IF NOT EXISTS idx_merchants_owner_email ON public.merchants (lower(owner_email));

-- Row Level Security (Strict P1, FORCE RLS, zero wildcard USING (true) policies)
ALTER TABLE public.merchants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.merchants FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS allow_all_merchants ON public.merchants;
DROP POLICY IF EXISTS public_read_merchants ON public.merchants;
DROP POLICY IF EXISTS authenticated_select_own_merchant ON public.merchants;
DROP POLICY IF EXISTS service_role_all_merchants ON public.merchants;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE POLICY authenticated_select_own_merchant ON public.merchants
            AS PERMISSIVE FOR SELECT TO authenticated
            USING (
                NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
                AND (
                    lower(slug) = lower(NULLIF(current_setting('app.current_tenant_id', true), ''))
                    OR EXISTS (
                        SELECT 1
                        FROM public.tenants t
                        WHERE lower(t.slug) = lower(public.merchants.slug)
                          AND (
                              t.id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                              OR lower(t.slug) = lower(NULLIF(current_setting('app.current_tenant_id', true), ''))
                          )
                    )
                )
            );
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE POLICY service_role_all_merchants ON public.merchants
            AS PERMISSIVE FOR ALL TO service_role
            USING (
                NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
                OR lower(slug) = lower(NULLIF(current_setting('app.current_tenant_id', true), ''))
                OR EXISTS (
                    SELECT 1
                    FROM public.tenants t
                    WHERE lower(t.slug) = lower(public.merchants.slug)
                      AND (
                          t.id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                          OR lower(t.slug) = lower(NULLIF(current_setting('app.current_tenant_id', true), ''))
                      )
                )
            )
            WITH CHECK (
                NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
                OR lower(slug) = lower(NULLIF(current_setting('app.current_tenant_id', true), ''))
                OR EXISTS (
                    SELECT 1
                    FROM public.tenants t
                    WHERE lower(t.slug) = lower(public.merchants.slug)
                      AND (
                          t.id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
                          OR lower(t.slug) = lower(NULLIF(current_setting('app.current_tenant_id', true), ''))
                      )
                )
            );
    END IF;
END
$$;

-- Least privilege grants (idempotent)
REVOKE ALL ON public.merchants FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON public.merchants FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON public.merchants FROM authenticated;
        GRANT SELECT ON public.merchants TO authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON public.merchants TO service_role;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_app_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.merchants TO bt_app_runtime;
    END IF;
END
$$;

COMMIT;
