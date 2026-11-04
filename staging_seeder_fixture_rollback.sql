-- =============================================================================
-- BOONTRACK STAGING SYNTHETIC SEEDER FIXTURE ROLLBACK / CLEANUP SCRIPT (REV 4.1.7)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Purpose: Provable, zero-residual deletion of seeded synthetic entities.
-- Safety Invariant: Deletes ONLY isolated 'seed_*' and '5eed*' identifiers.
-- Historical Protection: Preserves 100% untouched historical production rows.
-- Postcondition: Proves exactly 0 residual fixture rows remain post-cleanup.
-- =============================================================================

BEGIN;

SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';

-- -----------------------------------------------------------------------------
-- [STAGE 1] CHILD TABLES TEARDOWN (TOPOLOGICAL REVERSE ORDER)
-- -----------------------------------------------------------------------------

-- 1.1 Shop Commission Ledger
DELETE FROM public.shop_commission_ledger 
WHERE id::text LIKE '5eed%' OR tenant_slug = 'seed_tenant_a' OR tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 1.2 Shop Subscriptions
DELETE FROM public.shop_subscriptions 
WHERE id::text LIKE '5eed%' OR tenant_slug = 'seed_tenant_a' OR tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 1.3 Attribution Sessions
DELETE FROM public.attribution_sessions 
WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%' OR referral_code LIKE 'seed_%';

-- 1.4 Attributions
DELETE FROM public.attributions 
WHERE id::text LIKE '5eed%' OR session_id LIKE 'seed_%';

-- 1.5 Delivery Orders
DELETE FROM public.delivery_orders 
WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%';

-- 1.6 Product Orders
DELETE FROM public.product_orders 
WHERE order_id LIKE 'seed_%';

-- 1.7 Orders
DELETE FROM public.orders 
WHERE id LIKE 'seed_%';

-- -----------------------------------------------------------------------------
-- [STAGE 2] DEDUP GOVERNANCE & QUARANTINE LEDGER TEARDOWN
-- -----------------------------------------------------------------------------

-- 2.1 Identifier Dedup Map
DELETE FROM public.migration_031_identifier_dedup_map 
WHERE map_id::text LIKE '5eed%' OR migration_batch_id = 'seed_batch_001';

-- 2.2 Quarantined Affiliate Commissions
DELETE FROM public.migration_031_quarantined_affiliate_commissions 
WHERE id::text LIKE '5eed%' OR migration_batch_id = 'seed_batch_001';

-- -----------------------------------------------------------------------------
-- [STAGE 3] PARENT COMMISSIONS & AFFILIATES TEARDOWN
-- -----------------------------------------------------------------------------

-- 3.1 Affiliate Commissions
DELETE FROM public.affiliate_commissions 
WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%';

-- 3.2 Affiliates
DELETE FROM public.affiliates 
WHERE id::text LIKE '5eed%' OR referral_code LIKE 'seed_%';

-- 3.3 Tenant Anchor
DELETE FROM public.tenants 
WHERE id = '5eed0000-0000-0000-0000-000000000001';

-- -----------------------------------------------------------------------------
-- [STAGE 4] POST-CLEANUP PROVABLE ASSERTIONS
-- Memverifikasi:
-- 1. 0 baris residual seeded tersisa di seluruh tabel.
-- 2. Tepat 5 afiliasi historis staging tetap utuh dan terlindungi.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_residual_cnt INT;
    v_historical_affiliates_count INT;
BEGIN
    -- 1. Asersi Zero-Residual
    SELECT (
        (SELECT COUNT(*) FROM public.tenants WHERE id::text LIKE '5eed%' OR slug = 'seed_tenant_a') +
        (SELECT COUNT(*) FROM public.affiliates WHERE id::text LIKE '5eed%' OR referral_code LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.affiliate_commissions WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.orders WHERE id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.product_orders WHERE order_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.delivery_orders WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.attributions WHERE id::text LIKE '5eed%' OR session_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.attribution_sessions WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.shop_subscriptions WHERE id::text LIKE '5eed%' OR tenant_slug = 'seed_tenant_a') +
        (SELECT COUNT(*) FROM public.shop_commission_ledger WHERE id::text LIKE '5eed%' OR tenant_slug = 'seed_tenant_a') +
        (SELECT COUNT(*) FROM public.migration_031_quarantined_affiliate_commissions WHERE id::text LIKE '5eed%' OR migration_batch_id = 'seed_batch_001') +
        (SELECT COUNT(*) FROM public.migration_031_identifier_dedup_map WHERE map_id::text LIKE '5eed%' OR migration_batch_id = 'seed_batch_001')
    ) INTO v_residual_cnt;

    IF v_residual_cnt > 0 THEN
        RAISE EXCEPTION 'POST-ROLLBACK ERROR: Found % residual seeded rows in Staging tables!', v_residual_cnt
            USING ERRCODE = 'P0004';
    END IF;

    -- 2. Asersi Integritas Afiliasi Historis (Wajib tepat 5 baris)
    SELECT COUNT(*) INTO v_historical_affiliates_count
    FROM public.affiliates
    WHERE id IN (
        '25305f9c-ed1b-4e84-8771-325b5dde23ee',
        '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae',
        '43e48443-dcfa-47a6-818c-5144e3a34db4',
        'b92b0929-1dbd-4f80-b875-94e9ab92b189',
        'f5b98eaa-cfde-49cf-a497-491221c1cda9'
    );

    IF v_historical_affiliates_count <> 5 THEN
        RAISE EXCEPTION 'POST-ROLLBACK ERROR: Historical affiliates count corrupted! Expected 5, found %', v_historical_affiliates_count
            USING ERRCODE = 'P0005';
    END IF;
END $$;

COMMIT;
