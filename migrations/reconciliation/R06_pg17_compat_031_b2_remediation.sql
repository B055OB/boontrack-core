-- =============================================================================
-- Reconciliation Candidate R06: PG 17 Compatible Gate B2 Remediation Suite (031)
-- Replaces Core `031_b2_remediation_suite.sql` in clean shared-DB PG 17 replay
-- where Inbox `20261003_create_shop_subscriptions.sql` already created
-- `public.shop_subscriptions.tenant_id` as UUID (causing `uuid !~* text` operator
-- error in raw 031) and uses `invoice_id` alongside optional `xendit_invoice_id`.
-- CANDIDATE ONLY — DO NOT EXECUTE ON REMOTE DB BEFORE CTO SHARED-DB SIGN-OFF.
-- =============================================================================

BEGIN;

SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '5s';

-- Ensure legacy xendit_invoice_id column exists on shop_subscriptions before Stage 1/5
ALTER TABLE public.shop_subscriptions
    ADD COLUMN IF NOT EXISTS xendit_invoice_id TEXT;

LOCK TABLE
    public.tenants,
    public.affiliates,
    public.orders,
    public.product_orders,
    public.delivery_orders,
    public.attributions,
    public.attribution_sessions,
    public.shop_subscriptions,
    public.shop_commission_ledger,
    public.affiliate_commissions,
    public.migration_031_quarantined_affiliate_commissions,
    public.migration_031_identifier_dedup_map
IN ACCESS EXCLUSIVE MODE;

-- [STAGE 1] PRECONDITION AUDIT (uses ::text cast safe on both UUID and VARCHAR tenant_id)
DO $$
DECLARE
    v_orphan_count INT := 0;
    v_dup_count INT := 0;
    v_mismatch_count INT := 0;
    v_null_tenant_count INT := 0;
BEGIN
    SELECT COUNT(*) INTO v_null_tenant_count
    FROM (
        SELECT id::text FROM public.orders WHERE tenant_id IS NULL OR BTRIM(tenant_id::text) = ''
        UNION ALL
        SELECT id::text FROM public.product_orders WHERE tenant_id IS NULL OR BTRIM(tenant_id::text) = ''
        UNION ALL
        SELECT id::text FROM public.shop_commission_ledger WHERE tenant_id IS NULL OR BTRIM(tenant_id::text) = ''
    ) null_check;

    IF v_null_tenant_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: % NULL/empty tenant_id rows detected', v_null_tenant_count USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.shop_subscriptions
        WHERE tenant_id IS NOT NULL
          AND tenant_id::text !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ) OR EXISTS (
        SELECT 1 FROM public.shop_commission_ledger
        WHERE tenant_id IS NOT NULL
          AND tenant_id::text !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ) THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: invalid UUID string in tenant_id' USING ERRCODE = 'P0006';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.affiliate_commissions WHERE amount IS NOT NULL AND scale(amount) > 2
    ) OR EXISTS (
        SELECT 1 FROM public.affiliate_commissions WHERE amount IS NOT NULL AND abs(amount) >= 10^16
    ) THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: affiliate_commissions amount precision violation' USING ERRCODE = 'P0005';
    END IF;
END $$;

-- [STAGE 2] PHYSICAL COLUMN ADDITION
ALTER TABLE public.attributions ADD COLUMN IF NOT EXISTS order_id text;

-- [STAGE 3] ENFORCE 3 NOT NULL CONSTRAINTS
ALTER TABLE public.orders ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.product_orders ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.shop_commission_ledger ALTER COLUMN tenant_id SET NOT NULL;

-- [STAGE 4 & 5] COMPOSITE UNIQUE CONSTRAINTS (Idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_orders_tenant_id_id' AND conrelid = 'public.orders'::regclass) THEN
        ALTER TABLE public.orders ADD CONSTRAINT uq_orders_tenant_id_id UNIQUE (tenant_id, id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_shop_subscriptions_tenant_id_id' AND conrelid = 'public.shop_subscriptions'::regclass) THEN
        ALTER TABLE public.shop_subscriptions ADD CONSTRAINT uq_shop_subscriptions_tenant_id_id UNIQUE (tenant_id, id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_shop_subscriptions_tenant_invoice' AND conrelid = 'public.shop_subscriptions'::regclass) THEN
        ALTER TABLE public.shop_subscriptions ADD CONSTRAINT uq_shop_subscriptions_tenant_invoice UNIQUE (tenant_id, xendit_invoice_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_shop_commission_ledger_tenant_subscription' AND conrelid = 'public.shop_commission_ledger'::regclass) THEN
        ALTER TABLE public.shop_commission_ledger ADD CONSTRAINT uq_shop_commission_ledger_tenant_subscription UNIQUE (tenant_id, subscription_id);
    END IF;
END $$;

-- [STAGE 6] FINANCIAL PRECISION HANDLING
ALTER TABLE public.affiliate_commissions ALTER COLUMN amount TYPE numeric(18, 2);

-- [STAGE 7] TYPE ALIGNMENT FOR TENANCY ANCHOR (idempotent if already uuid)
ALTER TABLE public.shop_subscriptions DROP CONSTRAINT IF EXISTS fk_shop_subscriptions_affiliate_composite;
ALTER TABLE public.shop_commission_ledger DROP CONSTRAINT IF EXISTS fk_shop_commission_ledger_affiliate_composite;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'shop_subscriptions'
          AND column_name = 'tenant_id' AND data_type <> 'uuid'
    ) THEN
        ALTER TABLE public.shop_subscriptions ALTER COLUMN tenant_id TYPE uuid USING tenant_id::uuid;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'shop_commission_ledger'
          AND column_name = 'tenant_id' AND data_type <> 'uuid'
    ) THEN
        ALTER TABLE public.shop_commission_ledger ALTER COLUMN tenant_id TYPE uuid USING tenant_id::uuid;
    END IF;
END $$;

-- [STAGE 8] 8 CONTRACTUAL COMPOSITE FOREIGN KEYS
ALTER TABLE public.affiliate_commissions DROP CONSTRAINT IF EXISTS affiliate_commissions_affiliate_id_fkey;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_affiliate_commissions_affiliate_composite') THEN
        ALTER TABLE public.affiliate_commissions
            ADD CONSTRAINT fk_affiliate_commissions_affiliate_composite
            FOREIGN KEY (tenant_id, affiliate_id) REFERENCES public.affiliates (tenant_id, id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_affiliates_manager_composite') THEN
        ALTER TABLE public.affiliates
            ADD CONSTRAINT fk_affiliates_manager_composite
            FOREIGN KEY (tenant_id, manager_id) REFERENCES public.affiliates (tenant_id, id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_attribution_sessions_order_composite') THEN
        ALTER TABLE public.attribution_sessions
            ADD CONSTRAINT fk_attribution_sessions_order_composite
            FOREIGN KEY (tenant_id, order_id) REFERENCES public.orders (tenant_id, id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_attributions_order_composite') THEN
        ALTER TABLE public.attributions
            ADD CONSTRAINT fk_attributions_order_composite
            FOREIGN KEY (tenant_id, order_id) REFERENCES public.orders (tenant_id, id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_delivery_orders_order_composite') THEN
        ALTER TABLE public.delivery_orders
            ADD CONSTRAINT fk_delivery_orders_order_composite
            FOREIGN KEY (tenant_id, order_id) REFERENCES public.orders (tenant_id, id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_product_orders_order_composite') THEN
        ALTER TABLE public.product_orders
            ADD CONSTRAINT fk_product_orders_order_composite
            FOREIGN KEY (tenant_id, order_id) REFERENCES public.orders (tenant_id, id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_shop_commission_ledger_subscription_composite') THEN
        ALTER TABLE public.shop_commission_ledger
            ADD CONSTRAINT fk_shop_commission_ledger_subscription_composite
            FOREIGN KEY (tenant_id, subscription_id) REFERENCES public.shop_subscriptions (tenant_id, id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_shop_subscriptions_tenant_anchor') THEN
        ALTER TABLE public.shop_subscriptions
            ADD CONSTRAINT fk_shop_subscriptions_tenant_anchor
            FOREIGN KEY (tenant_id) REFERENCES public.tenants (id) ON DELETE RESTRICT;
    END IF;
END $$;

-- [STAGE 9] CONVALIDATION CHECK
DO $$
DECLARE
    v_fk_count INT;
BEGIN
    SELECT COUNT(*) INTO v_fk_count
    FROM pg_constraint
    WHERE conname IN (
        'fk_affiliate_commissions_affiliate_composite',
        'fk_affiliates_manager_composite',
        'fk_attribution_sessions_order_composite',
        'fk_attributions_order_composite',
        'fk_delivery_orders_order_composite',
        'fk_product_orders_order_composite',
        'fk_shop_commission_ledger_subscription_composite',
        'fk_shop_subscriptions_tenant_anchor'
    ) AND convalidated IS TRUE;

    IF v_fk_count <> 8 THEN
        RAISE EXCEPTION 'POST-MIGRATION CHECK FAILED: Expected 8 convalidated foreign keys, found %', v_fk_count USING ERRCODE = 'P0004';
    END IF;
END $$;

COMMIT;
