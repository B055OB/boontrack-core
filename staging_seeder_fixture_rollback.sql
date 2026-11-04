-- =============================================================================
-- BOONTRACK STAGING SYNTHETIC SEEDER FIXTURE ROLLBACK / CLEANUP SCRIPT (REV 4.1.8)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Purpose: Provable, zero-residual deletion of seeded synthetic entities.
-- Isolation Invariant: Strictly explicit fixture ID predicates (Zero Overreach).
-- Safety Invariant: Deletes ONLY explicit '5eed*' / 'seed_*' fixture IDs.
-- Historical Protection: Preserves 100% untouched historical production rows.
-- Postcondition: Proves exactly 0 residual fixture rows remain post-cleanup.
-- =============================================================================

BEGIN;

SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';

-- -----------------------------------------------------------------------------
-- [STAGE 0] EXPLICIT CONCURRENCY LOCKING
-- Memperoleh ACCESS EXCLUSIVE lock di awal transaksi teardown pada 12 tabel
-- untuk menjamin isolasi mutlak selama pembersihan entitas sintetis.
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- [STAGE 1] CHILD TABLES TEARDOWN (TOPOLOGICAL REVERSE ORDER)
-- Catatan DBRE: Klausa DELETE di bawah HANYA menargetkan ID spesifik fixture
-- dan tenant_id fixture secara konjungtif (AND), MENGHILANGKAN seluruh klausa
-- longgar 'OR tenant_id = ...' untuk menjamin nol overreach ke data lain.
-- -----------------------------------------------------------------------------

-- 1.1 Shop Commission Ledger (1 Fixture Row)
DELETE FROM public.shop_commission_ledger 
WHERE id = '5eedaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'::uuid 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 1.2 Shop Subscriptions (1 Fixture Row)
DELETE FROM public.shop_subscriptions 
WHERE id = '5eed9999-9999-9999-9999-999999999991'::uuid 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 1.3 Attribution Sessions (1 Fixture Row)
DELETE FROM public.attribution_sessions 
WHERE id = '5eed8888-8888-8888-8888-888888888881'::uuid 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 1.4 Attributions (1 Fixture Row)
DELETE FROM public.attributions 
WHERE id = '5eed7777-7777-7777-7777-777777777771'::uuid 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 1.5 Delivery Orders (1 Fixture Row)
DELETE FROM public.delivery_orders 
WHERE id = '5eed6666-6666-6666-6666-666666666661'::uuid 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 1.6 Product Orders (1 Fixture Row)
DELETE FROM public.product_orders 
WHERE id = 50001 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 1.7 Orders (2 Fixture Rows)
DELETE FROM public.orders 
WHERE id IN ('seed_ord_001', 'seed_ord_002') 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- -----------------------------------------------------------------------------
-- [STAGE 2] DEDUP GOVERNANCE & QUARANTINE LEDGER TEARDOWN
-- -----------------------------------------------------------------------------

-- 2.1 Identifier Dedup Map (3 Fixture Rows)
DELETE FROM public.migration_031_identifier_dedup_map 
WHERE map_id IN ('5eed5555-5555-5555-5555-555555555551'::uuid, 
                 '5eed5555-5555-5555-5555-555555555552'::uuid,
                 '5eed5555-5555-5555-5555-555555555553'::uuid) 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 2.2 Quarantined Affiliate Commissions (1 Fixture Row)
DELETE FROM public.migration_031_quarantined_affiliate_commissions 
WHERE id = '5eed4444-4444-4444-4444-444444444441'::uuid 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- -----------------------------------------------------------------------------
-- [STAGE 3] PARENT COMMISSIONS & AFFILIATES TEARDOWN
-- -----------------------------------------------------------------------------

-- 3.1 Affiliate Commissions (1 Clean Row)
DELETE FROM public.affiliate_commissions 
WHERE id = '5eed3333-3333-3333-3333-333333333331'::uuid 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 3.2 Affiliates (3 Fixture Rows: Clean, Surv, Loser)
DELETE FROM public.affiliates 
WHERE id IN ('5eed1111-1111-1111-1111-111111111111'::uuid, 
             '5eed2222-2222-2222-2222-222222222221'::uuid, 
             '5eed2222-2222-2222-2222-222222222222'::uuid) 
  AND tenant_id = '5eed0000-0000-0000-0000-000000000001';

-- 3.3 Tenant Anchor (1 Fixture Row)
DELETE FROM public.tenants 
WHERE id = '5eed0000-0000-0000-0000-000000000001'::uuid 
  AND slug = 'seed_tenant_a';

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
    -- 1. Asersi Zero-Residual Terhadap Seluruh ID Fixture Eksplisit
    SELECT (
        (SELECT COUNT(*) FROM public.tenants 
         WHERE id = '5eed0000-0000-0000-0000-000000000001'::uuid) +
        (SELECT COUNT(*) FROM public.affiliates 
         WHERE id IN ('5eed1111-1111-1111-1111-111111111111'::uuid, 
                      '5eed2222-2222-2222-2222-222222222221'::uuid, 
                      '5eed2222-2222-2222-2222-222222222222'::uuid)) +
        (SELECT COUNT(*) FROM public.affiliate_commissions 
         WHERE id = '5eed3333-3333-3333-3333-333333333331'::uuid) +
        (SELECT COUNT(*) FROM public.orders 
         WHERE id IN ('seed_ord_001', 'seed_ord_002')) +
        (SELECT COUNT(*) FROM public.product_orders 
         WHERE id = 50001) +
        (SELECT COUNT(*) FROM public.delivery_orders 
         WHERE id = '5eed6666-6666-6666-6666-666666666661'::uuid) +
        (SELECT COUNT(*) FROM public.attributions 
         WHERE id = '5eed7777-7777-7777-7777-777777777771'::uuid) +
        (SELECT COUNT(*) FROM public.attribution_sessions 
         WHERE id = '5eed8888-8888-8888-8888-888888888881'::uuid) +
        (SELECT COUNT(*) FROM public.shop_subscriptions 
         WHERE id = '5eed9999-9999-9999-9999-999999999991'::uuid) +
        (SELECT COUNT(*) FROM public.shop_commission_ledger 
         WHERE id = '5eedaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'::uuid) +
        (SELECT COUNT(*) FROM public.migration_031_quarantined_affiliate_commissions 
         WHERE id = '5eed4444-4444-4444-4444-444444444441'::uuid) +
        (SELECT COUNT(*) FROM public.migration_031_identifier_dedup_map 
         WHERE map_id IN ('5eed5555-5555-5555-5555-555555555551'::uuid, 
                          '5eed5555-5555-5555-5555-555555555552'::uuid,
                          '5eed5555-5555-5555-5555-555555555553'::uuid))
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
