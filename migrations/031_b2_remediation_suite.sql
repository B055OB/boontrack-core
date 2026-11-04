-- =============================================================================
-- MIGRATION 031: GATE B2 PHYSICAL SCHEMA REMEDIATION SUITE
-- =============================================================================
-- Specification: GATE_B2_VERIFICATION_PROTOCOL.md (REV 2.8, Commit a9ad768)
-- Invariant: Zero Mutation on Production / Strictly Governed Staging Execution
-- Scope:
--   1. Statement Timeout Enforcement (5s)
--   2. Comprehensive Precondition Audit (Zero Orphan, Zero Dup, Zero Mismatch)
--   3. Physical Column Addition: attributions.order_id
--   4. Enforcement of 3 NOT NULL Columns: orders, product_orders, shop_commission_ledger
--   5. Enforcement of 2 Contractual Unique Constraints: shop_subscriptions, shop_commission_ledger
--   6. Enforcement of Financial Precision: affiliate_commissions.amount NUMERIC(18,2)
--   7. Repointing to 8 Contractual Composite Foreign Keys
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- [SAFETY GUARD] STATEMENT TIMEOUT & LOCK TIMEOUT
-- -----------------------------------------------------------------------------
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '2s';

-- -----------------------------------------------------------------------------
-- [SAFETY GUARD] EXPLICIT TABLE LOCKING (CONCURRENT WRITES PROTECTION)
-- Memperoleh ACCESS EXCLUSIVE lock di awal transaksi sebelum precondition audit
-- untuk menjamin isolasi penuh dan mencegah race condition data baru yang menyusup
-- di antara proses audit prekondisi dan eksekusi DDL.
-- -----------------------------------------------------------------------------
LOCK TABLE 
    public.tenants,
    public.affiliate_commissions, 
    public.shop_subscriptions, 
    public.shop_commission_ledger, 
    public.orders, 
    public.product_orders, 
    public.delivery_orders, 
    public.attributions, 
    public.attribution_sessions, 
    public.affiliates 
IN ACCESS EXCLUSIVE MODE;

-- -----------------------------------------------------------------------------
-- [STAGE 1] COMPREHENSIVE PRECONDITION AUDIT
-- Validasi pra-eksekusi: pastikan 0 baris orphan, 0 duplicate unique key,
-- dan 0 tenant mismatch pada seluruh tabel yang akan diberi constraint.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_orphan_count INT := 0;
    v_dup_count INT := 0;
    v_mismatch_count INT := 0;
    v_null_tenant_count INT := 0;
BEGIN
    -- 1. NULL Tenant Check on columns to be made NOT NULL (SCH-02, SCH-03, SCH-08)
    SELECT COUNT(*) INTO v_null_tenant_count
    FROM (
        SELECT id::text FROM public.orders WHERE tenant_id IS NULL OR BTRIM(tenant_id) = ''
        UNION ALL
        SELECT id::text FROM public.product_orders WHERE tenant_id IS NULL OR BTRIM(tenant_id) = ''
        UNION ALL
        SELECT id::text FROM public.shop_commission_ledger WHERE tenant_id IS NULL OR BTRIM(tenant_id) = ''
    ) null_check;

    IF v_null_tenant_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: % NULL/empty tenant_id rows detected in target NOT NULL tables', v_null_tenant_count USING ERRCODE = 'P0001';
    END IF;

    -- 2. Tenancy UUID Format Precondition for shop_subscriptions and shop_commission_ledger
    IF EXISTS (
        SELECT 1 FROM public.shop_subscriptions 
        WHERE tenant_id IS NOT NULL 
          AND tenant_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ) OR EXISTS (
        SELECT 1 FROM public.shop_commission_ledger 
        WHERE tenant_id IS NOT NULL 
          AND tenant_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ) THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: shop_subscriptions or shop_commission_ledger contains invalid UUID string in tenant_id' USING ERRCODE = 'P0006';
    END IF;

    -- 3. Financial Amount Precision & Range Preconditions (SCH-09 Data Safety)
    IF EXISTS (
        SELECT 1 FROM public.affiliate_commissions 
        WHERE amount IS NOT NULL AND scale(amount) > 2
    ) THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: affiliate_commissions contains amount with scale > 2 (fractional truncation risk)' USING ERRCODE = 'P0005';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.affiliate_commissions 
        WHERE amount IS NOT NULL AND abs(amount) >= 10^16
    ) THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: affiliate_commissions contains amount exceeding numeric(18,2) range limit (abs >= 10^16)' USING ERRCODE = 'P0005';
    END IF;

    -- 4. Duplicate Unique Key Preconditions
    -- A. orders (tenant_id, id)
    SELECT COUNT(*) INTO v_dup_count
    FROM (
        SELECT tenant_id, id FROM public.orders GROUP BY tenant_id, id HAVING COUNT(*) > 1
    ) dup_orders;
    IF v_dup_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: Duplicate (tenant_id, id) detected in public.orders (count: %)', v_dup_count USING ERRCODE = 'P0002';
    END IF;

    -- B. shop_subscriptions (tenant_id, id)
    SELECT COUNT(*) INTO v_dup_count
    FROM (
        SELECT tenant_id, id FROM public.shop_subscriptions GROUP BY tenant_id, id HAVING COUNT(*) > 1
    ) dup_sub_id;
    IF v_dup_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: Duplicate (tenant_id, id) detected in public.shop_subscriptions (count: %)', v_dup_count USING ERRCODE = 'P0002';
    END IF;

    -- C. shop_subscriptions (tenant_id, xendit_invoice_id) [SCH-12]
    SELECT COUNT(*) INTO v_dup_count
    FROM (
        SELECT tenant_id, xendit_invoice_id FROM public.shop_subscriptions
        WHERE xendit_invoice_id IS NOT NULL
        GROUP BY tenant_id, xendit_invoice_id HAVING COUNT(*) > 1
    ) dup_sub_inv;
    IF v_dup_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: Duplicate (tenant_id, xendit_invoice_id) detected in public.shop_subscriptions (count: %)', v_dup_count USING ERRCODE = 'P0002';
    END IF;

    -- D. shop_commission_ledger (tenant_id, subscription_id) [SCH-13]
    SELECT COUNT(*) INTO v_dup_count
    FROM (
        SELECT tenant_id, subscription_id FROM public.shop_commission_ledger
        WHERE subscription_id IS NOT NULL
        GROUP BY tenant_id, subscription_id HAVING COUNT(*) > 1
    ) dup_ledger_sub;
    IF v_dup_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: Duplicate (tenant_id, subscription_id) detected in public.shop_commission_ledger (count: %)', v_dup_count USING ERRCODE = 'P0002';
    END IF;

    -- 5. Orphan & Tenant Mismatch Preconditions across all 8 FK relations
    -- A. affiliate_commissions -> affiliates
    SELECT 
        COUNT(*) FILTER (WHERE c.affiliate_id IS NOT NULL AND p.id IS NULL),
        COUNT(*) FILTER (WHERE c.affiliate_id IS NOT NULL AND p.id IS NOT NULL AND c.tenant_id::text IS DISTINCT FROM p.tenant_id::text)
    INTO v_orphan_count, v_mismatch_count
    FROM public.affiliate_commissions c
    LEFT JOIN public.affiliates p ON p.id::text = c.affiliate_id::text;

    IF v_orphan_count > 0 OR v_mismatch_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: affiliate_commissions -> affiliates has % orphans, % mismatches', v_orphan_count, v_mismatch_count USING ERRCODE = 'P0003';
    END IF;

    -- B. affiliates (manager_id) -> affiliates (id)
    SELECT 
        COUNT(*) FILTER (WHERE c.manager_id IS NOT NULL AND p.id IS NULL),
        COUNT(*) FILTER (WHERE c.manager_id IS NOT NULL AND p.id IS NOT NULL AND c.tenant_id::text IS DISTINCT FROM p.tenant_id::text)
    INTO v_orphan_count, v_mismatch_count
    FROM public.affiliates c
    LEFT JOIN public.affiliates p ON p.id = c.manager_id;

    IF v_orphan_count > 0 OR v_mismatch_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: affiliates manager hierarchy has % orphans, % mismatches', v_orphan_count, v_mismatch_count USING ERRCODE = 'P0003';
    END IF;

    -- C. attribution_sessions -> orders
    SELECT 
        COUNT(*) FILTER (WHERE c.order_id IS NOT NULL AND p.id IS NULL),
        COUNT(*) FILTER (WHERE c.order_id IS NOT NULL AND p.id IS NOT NULL AND c.tenant_id::text IS DISTINCT FROM p.tenant_id::text)
    INTO v_orphan_count, v_mismatch_count
    FROM public.attribution_sessions c
    LEFT JOIN public.orders p ON p.id::text = c.order_id::text;

    IF v_orphan_count > 0 OR v_mismatch_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: attribution_sessions -> orders has % orphans, % mismatches', v_orphan_count, v_mismatch_count USING ERRCODE = 'P0003';
    END IF;

    -- D. delivery_orders -> orders
    SELECT 
        COUNT(*) FILTER (WHERE c.order_id IS NOT NULL AND p.id IS NULL),
        COUNT(*) FILTER (WHERE c.order_id IS NOT NULL AND p.id IS NOT NULL AND c.tenant_id::text IS DISTINCT FROM p.tenant_id::text)
    INTO v_orphan_count, v_mismatch_count
    FROM public.delivery_orders c
    LEFT JOIN public.orders p ON p.id::text = c.order_id::text;

    IF v_orphan_count > 0 OR v_mismatch_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: delivery_orders -> orders has % orphans, % mismatches', v_orphan_count, v_mismatch_count USING ERRCODE = 'P0003';
    END IF;

    -- E. product_orders -> orders
    SELECT 
        COUNT(*) FILTER (WHERE c.order_id IS NOT NULL AND p.id IS NULL),
        COUNT(*) FILTER (WHERE c.order_id IS NOT NULL AND p.id IS NOT NULL AND c.tenant_id::text IS DISTINCT FROM p.tenant_id::text)
    INTO v_orphan_count, v_mismatch_count
    FROM public.product_orders c
    LEFT JOIN public.orders p ON p.id::text = c.order_id::text;

    IF v_orphan_count > 0 OR v_mismatch_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: product_orders -> orders has % orphans, % mismatches', v_orphan_count, v_mismatch_count USING ERRCODE = 'P0003';
    END IF;

    -- F. shop_commission_ledger -> shop_subscriptions
    SELECT 
        COUNT(*) FILTER (WHERE c.subscription_id IS NOT NULL AND p.id IS NULL),
        COUNT(*) FILTER (WHERE c.subscription_id IS NOT NULL AND p.id IS NOT NULL AND c.tenant_id::text IS DISTINCT FROM p.tenant_id::text)
    INTO v_orphan_count, v_mismatch_count
    FROM public.shop_commission_ledger c
    LEFT JOIN public.shop_subscriptions p ON p.id::text = c.subscription_id::text;

    IF v_orphan_count > 0 OR v_mismatch_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: shop_commission_ledger -> shop_subscriptions has % orphans, % mismatches', v_orphan_count, v_mismatch_count USING ERRCODE = 'P0003';
    END IF;

    -- G. shop_subscriptions -> tenants
    SELECT 
        COUNT(*) FILTER (WHERE c.tenant_id IS NOT NULL AND p.id IS NULL),
        COUNT(*) FILTER (WHERE c.tenant_id IS NOT NULL AND p.id IS NOT NULL AND c.tenant_id::text IS DISTINCT FROM p.id::text)
    INTO v_orphan_count, v_mismatch_count
    FROM public.shop_subscriptions c
    LEFT JOIN public.tenants p ON p.id::text = c.tenant_id::text;

    IF v_orphan_count > 0 OR v_mismatch_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION FAILED: shop_subscriptions -> tenants has % orphans, % mismatches', v_orphan_count, v_mismatch_count USING ERRCODE = 'P0003';
    END IF;

    RAISE NOTICE '[PRECONDITION AUDIT PASSED] 0 orphan rows, 0 duplicate keys, 0 tenant mismatches, 0 NULL tenants, 0 scale/range/uuid anomalies.';
END $$;

-- -----------------------------------------------------------------------------
-- [STAGE 2] PHYSICAL COLUMN ADDITION
-- -----------------------------------------------------------------------------
ALTER TABLE public.attributions ADD COLUMN IF NOT EXISTS order_id text;

-- -----------------------------------------------------------------------------
-- [STAGE 3] ENFORCE 3 NOT NULL CONSTRAINTS (SCH-02, SCH-03, SCH-08)
-- -----------------------------------------------------------------------------
ALTER TABLE public.orders ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.product_orders ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.shop_commission_ledger ALTER COLUMN tenant_id SET NOT NULL;

-- -----------------------------------------------------------------------------
-- [STAGE 4] SUPPORTING PARENT COMPOSITE UNIQUE CONSTRAINTS
-- -----------------------------------------------------------------------------
ALTER TABLE public.orders 
    ADD CONSTRAINT uq_orders_tenant_id_id UNIQUE (tenant_id, id);

ALTER TABLE public.shop_subscriptions 
    ADD CONSTRAINT uq_shop_subscriptions_tenant_id_id UNIQUE (tenant_id, id);

-- -----------------------------------------------------------------------------
-- [STAGE 5] ENFORCE 2 CONTRACTUAL UNIQUE CONSTRAINTS (SCH-12, SCH-13)
-- -----------------------------------------------------------------------------
ALTER TABLE public.shop_subscriptions 
    ADD CONSTRAINT uq_shop_subscriptions_tenant_invoice UNIQUE (tenant_id, xendit_invoice_id);

ALTER TABLE public.shop_commission_ledger 
    ADD CONSTRAINT uq_shop_commission_ledger_tenant_subscription UNIQUE (tenant_id, subscription_id);

-- -----------------------------------------------------------------------------
-- [STAGE 6] FINANCIAL PRECISION HANDLING (SCH-09)
-- -----------------------------------------------------------------------------
ALTER TABLE public.affiliate_commissions 
    ALTER COLUMN amount TYPE numeric(18, 2);

-- -----------------------------------------------------------------------------
-- [STAGE 7] TYPE ALIGNMENT FOR TENANCY ANCHOR
-- -----------------------------------------------------------------------------
ALTER TABLE public.shop_subscriptions 
    ALTER COLUMN tenant_id TYPE uuid USING tenant_id::uuid;

ALTER TABLE public.shop_commission_ledger 
    ALTER COLUMN tenant_id TYPE uuid USING tenant_id::uuid;

-- -----------------------------------------------------------------------------
-- [STAGE 8] 8 CONTRACTUAL COMPOSITE FOREIGN KEYS
-- -----------------------------------------------------------------------------

-- Drop legacy single-column FK on affiliate_commissions
ALTER TABLE public.affiliate_commissions 
    DROP CONSTRAINT IF EXISTS affiliate_commissions_affiliate_id_fkey;

-- 1. affiliate_commissions -> affiliates (tenant_id, id)
ALTER TABLE public.affiliate_commissions 
    ADD CONSTRAINT fk_affiliate_commissions_affiliate_composite 
    FOREIGN KEY (tenant_id, affiliate_id) 
    REFERENCES public.affiliates (tenant_id, id) 
    ON DELETE CASCADE;

-- 2. affiliates -> affiliates (tenant_id, id) [Manager Self-Reference]
ALTER TABLE public.affiliates 
    ADD CONSTRAINT fk_affiliates_manager_composite 
    FOREIGN KEY (tenant_id, manager_id) 
    REFERENCES public.affiliates (tenant_id, id) 
    ON DELETE RESTRICT;

-- 3. attribution_sessions -> orders (tenant_id, id)
ALTER TABLE public.attribution_sessions 
    ADD CONSTRAINT fk_attribution_sessions_order_composite 
    FOREIGN KEY (tenant_id, order_id) 
    REFERENCES public.orders (tenant_id, id) 
    ON DELETE CASCADE;

-- 4. attributions -> orders (tenant_id, id)
ALTER TABLE public.attributions 
    ADD CONSTRAINT fk_attributions_order_composite 
    FOREIGN KEY (tenant_id, order_id) 
    REFERENCES public.orders (tenant_id, id) 
    ON DELETE CASCADE;

-- 5. delivery_orders -> orders (tenant_id, id)
ALTER TABLE public.delivery_orders 
    ADD CONSTRAINT fk_delivery_orders_order_composite 
    FOREIGN KEY (tenant_id, order_id) 
    REFERENCES public.orders (tenant_id, id) 
    ON DELETE CASCADE;

-- 6. product_orders -> orders (tenant_id, id)
ALTER TABLE public.product_orders 
    ADD CONSTRAINT fk_product_orders_order_composite 
    FOREIGN KEY (tenant_id, order_id) 
    REFERENCES public.orders (tenant_id, id) 
    ON DELETE CASCADE;

-- 7. shop_commission_ledger -> shop_subscriptions (tenant_id, id)
ALTER TABLE public.shop_commission_ledger 
    ADD CONSTRAINT fk_shop_commission_ledger_subscription_composite 
    FOREIGN KEY (tenant_id, subscription_id) 
    REFERENCES public.shop_subscriptions (tenant_id, id) 
    ON DELETE CASCADE;

-- 8. shop_subscriptions -> tenants (id) [Tenancy Anchor]
ALTER TABLE public.shop_subscriptions 
    ADD CONSTRAINT fk_shop_subscriptions_tenant_anchor 
    FOREIGN KEY (tenant_id) 
    REFERENCES public.tenants (id) 
    ON DELETE RESTRICT;

-- -----------------------------------------------------------------------------
-- [STAGE 9] POST-MIGRATION CONVALIDATION & HEALTH CHECK
-- -----------------------------------------------------------------------------
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

    RAISE NOTICE '[POST-MIGRATION CHECK PASSED] All 8 contractual composite foreign keys created and convalidated.';
END $$;

COMMIT;

-- =============================================================================
-- ROLLBACK SPECIFICATION & RUNBOOK
-- =============================================================================
/*
-- FINANCIAL DATA REVERSIBILITY NOTICE:
--   1. Schema Type Reversibility: ALTER COLUMN amount TYPE numeric restores the unconstrained
--      numeric data type in PostgreSQL catalog metadata.
--   2. Precision & Truncation Boundary: During forward migration to numeric(18,2), if any values
--      had scale > 2, fractional rounding or truncation occurred upon cast. Rolling back to
--      numeric DOES NOT restore lost sub-cent fractional digits if they were altered.
--      The forward migration precondition audit guarantees 0 rows had scale > 2 prior to migration,
--      ensuring zero loss of precision under clean baseline conditions.
--   3. Transaction Boundary: If this rollback is executed within the migration failure window,
--      the entire forward transaction is rolled back via ROLLBACK, preserving bit-exact state.

BEGIN;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '2s';
LOCK TABLE public.tenants, public.affiliate_commissions, public.shop_subscriptions, public.shop_commission_ledger, public.orders, public.product_orders, public.delivery_orders, public.attributions, public.attribution_sessions, public.affiliates IN ACCESS EXCLUSIVE MODE;

-- 1. DROP ALL 8 COMPOSITE FOREIGN KEYS (7 NEW + 1 REPLACED)
ALTER TABLE public.shop_subscriptions DROP CONSTRAINT IF EXISTS fk_shop_subscriptions_tenant_anchor;
ALTER TABLE public.shop_commission_ledger DROP CONSTRAINT IF EXISTS fk_shop_commission_ledger_subscription_composite;
ALTER TABLE public.product_orders DROP CONSTRAINT IF EXISTS fk_product_orders_order_composite;
ALTER TABLE public.delivery_orders DROP CONSTRAINT IF EXISTS fk_delivery_orders_order_composite;
ALTER TABLE public.attributions DROP CONSTRAINT IF EXISTS fk_attributions_order_composite;
ALTER TABLE public.attribution_sessions DROP CONSTRAINT IF EXISTS fk_attribution_sessions_order_composite;
ALTER TABLE public.affiliates DROP CONSTRAINT IF EXISTS fk_affiliates_manager_composite;
ALTER TABLE public.affiliate_commissions DROP CONSTRAINT IF EXISTS fk_affiliate_commissions_affiliate_composite;

-- Restore legacy single-column FK on affiliate_commissions
ALTER TABLE public.affiliate_commissions 
    ADD CONSTRAINT affiliate_commissions_affiliate_id_fkey 
    FOREIGN KEY (affiliate_id) REFERENCES public.affiliates(id) ON DELETE CASCADE;

-- 2. DROP THE 2 CONTRACTUAL UNIQUE CONSTRAINTS (SCH-12, SCH-13) & SUPPORTING PARENT KEYS
ALTER TABLE public.shop_commission_ledger DROP CONSTRAINT IF EXISTS uq_shop_commission_ledger_tenant_subscription;
ALTER TABLE public.shop_subscriptions DROP CONSTRAINT IF EXISTS uq_shop_subscriptions_tenant_invoice;
ALTER TABLE public.shop_subscriptions DROP CONSTRAINT IF EXISTS uq_shop_subscriptions_tenant_id_id;
ALTER TABLE public.orders DROP CONSTRAINT IF EXISTS uq_orders_tenant_id_id;

-- 3. REVERSE 3 NOT NULL CONSTRAINTS (SCH-02, SCH-03, SCH-08)
ALTER TABLE public.orders ALTER COLUMN tenant_id DROP NOT NULL;
ALTER TABLE public.product_orders ALTER COLUMN tenant_id DROP NOT NULL;
ALTER TABLE public.shop_commission_ledger ALTER COLUMN tenant_id DROP NOT NULL;

-- 4. REVERSE FINANCIAL DATA TYPE (SCH-09)
ALTER TABLE public.affiliate_commissions ALTER COLUMN amount TYPE numeric;

-- 5. REVERT SHOP_SUBSCRIPTIONS AND SHOP_COMMISSION_LEDGER TENANT_ID TYPE TO VARCHAR
ALTER TABLE public.shop_commission_ledger ALTER COLUMN tenant_id TYPE character varying;
ALTER TABLE public.shop_subscriptions ALTER COLUMN tenant_id TYPE character varying;

-- 6. DROP ADDED SCHEMA COLUMN (attributions.order_id)
ALTER TABLE public.attributions DROP COLUMN IF EXISTS order_id;

COMMIT;
*/

