-- =============================================================================
-- Reconciliation Candidate R01 (C-01): PostgreSQL 17 Payment Events Reconciliation
-- CANDIDATE ONLY — DO NOT EXECUTE ON REMOTE DB BEFORE CTO SHARED-DB SIGN-OFF.
--
-- Resolves Collision C-01:
--   1. Replaces PG 17 invalid `CREATE POLICY IF NOT EXISTS` syntax from Inbox
--      `20260921_create_payment_events.sql` with valid `DROP POLICY IF EXISTS`
--      + `CREATE POLICY`.
--   2. Reconciles `public.payment_events` column contract (`event_id`,
--      `provider_event_id`, `order_id`, `tenant_id`, `amount`, `payload`,
--      `raw_payload`) between Inbox `20260921` and Core Stage 3 `033a`–`033c`.
--   3. Enforces RLS + FORCE ROW LEVEL SECURITY with scoped policies (zero
--      wildcard USING (true) for anon/authenticated).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(64) NOT NULL,
    event_id VARCHAR(128) UNIQUE NOT NULL,
    provider_event_id VARCHAR(128),
    reference_id VARCHAR(128),
    order_id VARCHAR(128),
    tenant_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(64) NOT NULL DEFAULT 'PROCESSING',
    record_classification VARCHAR(64) NOT NULL DEFAULT 'STAGE3_SETTLEMENT',
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Harmonize columns if table was pre-created by either Inbox or Core
ALTER TABLE public.payment_events
    ADD COLUMN IF NOT EXISTS event_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS reference_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS order_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS status VARCHAR(64) NOT NULL DEFAULT 'PROCESSING',
    ADD COLUMN IF NOT EXISTS record_classification VARCHAR(64) NOT NULL DEFAULT 'STAGE3_SETTLEMENT',
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Drop narrow Inbox-only event_type check if present so Core & Inbox event names both work
ALTER TABLE public.payment_events
    DROP CONSTRAINT IF EXISTS payment_events_event_type_check;

-- Align order_id and tenant_id to VARCHAR so both UUID strings and Core order/slug IDs fit
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payment_events'
          AND column_name = 'order_id' AND data_type <> 'character varying'
    ) THEN
        ALTER TABLE public.payment_events
            ALTER COLUMN order_id TYPE VARCHAR(128) USING order_id::text;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payment_events'
          AND column_name = 'tenant_id'
          AND (data_type <> 'character varying' OR character_maximum_length IS DISTINCT FROM 100)
    ) THEN
        ALTER TABLE public.payment_events
            ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::text;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payment_events'
          AND column_name = 'amount' AND data_type = 'bigint'
    ) THEN
        ALTER TABLE public.payment_events
            ALTER COLUMN amount TYPE NUMERIC(14, 2) USING amount::numeric(14, 2);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS payment_events_order_id_idx
    ON public.payment_events (order_id)
    WHERE order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS payment_events_tenant_created_idx
    ON public.payment_events (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS payment_events_raw_payload_gin
    ON public.payment_events USING gin (raw_payload);

-- PG 17 valid idempotent RLS policies (DROP POLICY IF EXISTS + CREATE POLICY)
ALTER TABLE public.payment_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_full_access_payment_events" ON public.payment_events;
CREATE POLICY "service_role_full_access_payment_events"
    ON public.payment_events
    AS PERMISSIVE FOR ALL
    TO service_role
    USING (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
    )
    WITH CHECK (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
    );

DROP POLICY IF EXISTS "tenant_read_own_payment_events" ON public.payment_events;
CREATE POLICY "tenant_read_own_payment_events"
    ON public.payment_events
    AS PERMISSIVE FOR SELECT
    TO authenticated
    USING (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
        AND (
            tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
            OR tenant_id IN (
                SELECT id::text FROM public.tenants
                WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                UNION
                SELECT slug FROM public.tenants
                WHERE id::text = NULLIF(current_setting('app.current_tenant_id', true), '')
            )
        )
    );

COMMIT;
