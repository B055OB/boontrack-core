-- =============================================================================
-- BOONTRACK STAGING SYNTHETIC SEEDER FIXTURE (REV 4.1.8)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Scope: 14 Synthetic Entities (Clean, Dedup Survivor/Loser, Quarantine Commission & Dedup Map Pair, 8 FK Streams)
-- Isolation Invariant: Strictly namespaced explicit IDs with symmetric predicates.
-- Safety Invariant: Precondition asserts 0 collision with existing staging rows.
-- Concurrency Invariant: ACCESS EXCLUSIVE locking acquired before collision audit.
-- Zero-Touch Guarantee: Production DB and Cloudflare R2 strictly untouched.
-- =============================================================================

BEGIN;

SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';

-- -----------------------------------------------------------------------------
-- [STAGE 0] EXPLICIT CONCURRENCY LOCKING (RACE CONDITION PROTECTION)
-- Memperoleh ACCESS EXCLUSIVE lock di awal transaksi sebelum collision audit
-- untuk mencegah concurrent insert menyusup di antara audit dan injeksi.
-- Menjangkau SELURUH 12 tabel yang terlibat dalam audit tabrakan dan seeder.
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
-- [STAGE 1] PRECONDITION AUDIT & SYMMETRIC COLLISION GUARD
-- Memverifikasi bahwa seluruh ID dan predicate eksplisit yang akan dipakai
-- belum ada di database, dan 5 afiliasi historis staging terlindungi penuh.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_colliding_count INT;
    v_historical_affiliates_count INT;
BEGIN
    -- 1. Periksa tabrakan ID dan kriteria eksplisit fixture
    SELECT (
        (SELECT COUNT(*) FROM public.tenants 
         WHERE id = '5eed0000-0000-0000-0000-000000000001'::uuid OR slug = 'seed_tenant_a') +
        (SELECT COUNT(*) FROM public.affiliates 
         WHERE id IN ('5eed1111-1111-1111-1111-111111111111'::uuid, 
                      '5eed2222-2222-2222-2222-222222222221'::uuid, 
                      '5eed2222-2222-2222-2222-222222222222'::uuid) 
            OR referral_code IN ('seed_clean_01', 'seed_surv_01', 'seed_loser_01')) +
        (SELECT COUNT(*) FROM public.affiliate_commissions 
         WHERE id = '5eed3333-3333-3333-3333-333333333331'::uuid OR order_id = 'seed_ord_clean_001') +
        (SELECT COUNT(*) FROM public.migration_031_quarantined_affiliate_commissions 
         WHERE id = '5eed4444-4444-4444-4444-444444444441'::uuid OR order_id = 'seed_ord_quar_001') +
        (SELECT COUNT(*) FROM public.migration_031_identifier_dedup_map 
         WHERE map_id IN ('5eed5555-5555-5555-5555-555555555551'::uuid, 
                          '5eed5555-5555-5555-5555-555555555552'::uuid,
                          '5eed5555-5555-5555-5555-555555555553'::uuid)
            OR (table_name = 'affiliate_commissions' 
                AND column_name = 'tenant_id' 
                AND quarantined_row_id = '5eed4444-4444-4444-4444-444444444441')) +
        (SELECT COUNT(*) FROM public.orders 
         WHERE id IN ('seed_ord_001', 'seed_ord_002')) +
        (SELECT COUNT(*) FROM public.product_orders 
         WHERE id = 50001 OR order_id = 'seed_ord_001') +
        (SELECT COUNT(*) FROM public.delivery_orders 
         WHERE id = '5eed6666-6666-6666-6666-666666666661'::uuid OR order_id = 'seed_ord_001') +
        (SELECT COUNT(*) FROM public.attributions 
         WHERE id = '5eed7777-7777-7777-7777-777777777771'::uuid OR session_id = 'seed_sess_001') +
        (SELECT COUNT(*) FROM public.attribution_sessions 
         WHERE id = '5eed8888-8888-8888-8888-888888888881'::uuid OR order_id = 'seed_ord_001') +
        (SELECT COUNT(*) FROM public.shop_subscriptions 
         WHERE id = '5eed9999-9999-9999-9999-999999999991'::uuid OR xendit_invoice_id = 'seed_inv_001') +
        (SELECT COUNT(*) FROM public.shop_commission_ledger 
         WHERE id = '5eedaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'::uuid)
    ) INTO v_colliding_count;

    IF v_colliding_count > 0 THEN
        RAISE EXCEPTION 'PRECONDITION VIOLATION: Detected % pre-existing colliding seeded entities in Staging! Run staging_seeder_fixture_rollback.sql first.', v_colliding_count
            USING ERRCODE = 'P0001';
    END IF;

    -- 2. Verifikasi 5 afiliasi historis staging tetap utuh
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
        RAISE EXCEPTION 'PRECONDITION VIOLATION: Expected 5 historical affiliates in Staging, found %', v_historical_affiliates_count
            USING ERRCODE = 'P0002';
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- [STAGE 2] TENANT ANCHOR
-- -----------------------------------------------------------------------------
INSERT INTO public.tenants (id, slug)
VALUES ('5eed0000-0000-0000-0000-000000000001'::uuid, 'seed_tenant_a')
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- [STAGE 3] AFFILIATES (3 Rows: 1 Clean, 1 Survivor, 1 Loser)
-- -----------------------------------------------------------------------------
INSERT INTO public.affiliates (
    id, tenant_id, name, phone_number, referral_code, commission_rate, status, role
)
VALUES 
  ('5eed1111-1111-1111-1111-111111111111'::uuid, '5eed0000-0000-0000-0000-000000000001', 'seed_aff_clean_001', '081200000001', 'seed_clean_01', 10.00, 'ACTIVE', 'affiliate'),
  ('5eed2222-2222-2222-2222-222222222221'::uuid, '5eed0000-0000-0000-0000-000000000001', 'seed_aff_surv_001',  '081200000002', 'seed_surv_01',  10.00, 'ACTIVE', 'affiliate'),
  ('5eed2222-2222-2222-2222-222222222222'::uuid, '5eed0000-0000-0000-0000-000000000001', 'seed_aff_loser_001', '081200000003', 'seed_loser_01', 10.00, 'ACTIVE', 'affiliate');

-- -----------------------------------------------------------------------------
-- [STAGE 4] AFFILIATE COMMISSIONS (1 Clean Row)
-- -----------------------------------------------------------------------------
INSERT INTO public.affiliate_commissions (
    id, tenant_id, affiliate_id, order_id, order_amount, amount, status
)
VALUES 
  ('5eed3333-3333-3333-3333-333333333331'::uuid, '5eed0000-0000-0000-0000-000000000001', '5eed1111-1111-1111-1111-111111111111'::uuid, 'seed_ord_clean_001', 500000.00, 50000.00, 'PAID');

-- -----------------------------------------------------------------------------
-- [STAGE 5] QUARANTINED COMMISSIONS (1 Physically Isolated Row)
-- -----------------------------------------------------------------------------
INSERT INTO public.migration_031_quarantined_affiliate_commissions (
    id, migration_batch_id, tenant_id, original_tenant_id, affiliate_id, order_id, 
    order_amount, amount, commission_type, original_status, quarantine_reason, distinct_tenant_count, row_snapshot, approval_status
)
VALUES (
    '5eed4444-4444-4444-4444-444444444441'::uuid, 'seed_batch_001', NULL, 
    NULL, '5eed1111-1111-1111-1111-111111111111', 'seed_ord_quar_001', 
    750000.00, 75000.00, 'PRODUCT_ORDER', 'PENDING', 'QUARANTINE_NULL_TENANT_LEGACY', 1, '{}'::jsonb, 'QUARANTINED_LOCKED'
);

-- -----------------------------------------------------------------------------
-- [STAGE 6] IDENTIFIER DEDUP GOVERNANCE MAP (3 Rows: Survivor rank=1, Loser rank=2, Quarantined Commission)
-- -----------------------------------------------------------------------------
INSERT INTO public.migration_031_identifier_dedup_map (
    map_id, migration_batch_id, table_name, column_name, tenant_id, 
    quarantined_row_id, canonical_survivor_id, original_identifier_value, 
    new_identifier_value, dedup_rank, new_status, resolution_reason, 
    requires_finance_reconciliation, downstream_references, row_snapshot, retry_count,
    created_at, last_reconciled_at
)
VALUES 
  ('5eed5555-5555-5555-5555-555555555551'::uuid, 'seed_batch_001', 'affiliates', 'id', '5eed0000-0000-0000-0000-000000000001',
   '5eed2222-2222-2222-2222-222222222221', '5eed2222-2222-2222-2222-222222222221', '5eed2222-2222-2222-2222-222222222221',
   '5eed2222-2222-2222-2222-222222222221', 1, 'SURVIVOR', 'AUTHORITATIVE_PRIMARY_IDENTITY',
   false, '[]'::jsonb, '{}'::jsonb, 0, now(), now()),
  ('5eed5555-5555-5555-5555-555555555552'::uuid, 'seed_batch_001', 'affiliates', 'id', '5eed0000-0000-0000-0000-000000000001',
   '5eed2222-2222-2222-2222-222222222222', '5eed2222-2222-2222-2222-222222222221', '5eed2222-2222-2222-2222-222222222222',
   '5eed2222-2222-2222-2222-222222222221', 2, 'SUPERSEDED_DUPLICATE', 'MERGED_TO_SURVIVOR',
   false, '[]'::jsonb, '{}'::jsonb, 0, now(), now()),
  ('5eed5555-5555-5555-5555-555555555553'::uuid, 'seed_batch_001', 'affiliate_commissions', 'tenant_id', NULL,
   '5eed4444-4444-4444-4444-444444444441', '5eed4444-4444-4444-4444-444444444441', NULL,
   'MOVED_TO_QUARANTINE_TABLE', 1, 'QUARANTINED', 'QUARANTINE_NULL_TENANT_LEGACY',
   false, '[]'::jsonb, '{}'::jsonb, 0, now(), now());

-- -----------------------------------------------------------------------------
-- [STAGE 7] CHILD ENTITIES (7 Tables, 8 Streams repointed from Loser)
-- -----------------------------------------------------------------------------

-- 7.1 Orders (2 streams: affiliate_id and manager_id)
INSERT INTO public.orders (id, tenant_id, affiliate_id, manager_id, status, gross_amount)
VALUES 
  ('seed_ord_001', '5eed0000-0000-0000-0000-000000000001', '5eed2222-2222-2222-2222-222222222221'::uuid, NULL, 'PENDING', 100000.00),
  ('seed_ord_002', '5eed0000-0000-0000-0000-000000000001', NULL, '5eed2222-2222-2222-2222-222222222221'::uuid, 'PENDING', 150000.00);

-- 7.2 Product Orders
INSERT INTO public.product_orders (id, order_id, tenant_id, affiliate_id, status)
VALUES 
  (50001, 'seed_ord_001', '5eed0000-0000-0000-0000-000000000001', '5eed2222-2222-2222-2222-222222222221'::uuid, 'PENDING');

-- 7.3 Delivery Orders
INSERT INTO public.delivery_orders (id, tenant_id, order_id, provider, service_type, affiliate_id, status)
VALUES 
  ('5eed6666-6666-6666-6666-666666666661'::uuid, '5eed0000-0000-0000-0000-000000000001', 'seed_ord_001', 'JNE', 'REG', '5eed2222-2222-2222-2222-222222222221'::uuid, 'PENDING');

-- 7.4 Attributions
INSERT INTO public.attributions (id, tenant_id, session_id, ip_hash, affiliate_id)
VALUES 
  ('5eed7777-7777-7777-7777-777777777771'::uuid, '5eed0000-0000-0000-0000-000000000001', 'seed_sess_001', 'seed_ip_hash_001', '5eed2222-2222-2222-2222-222222222221'::uuid);

-- 7.5 Attribution Sessions
INSERT INTO public.attribution_sessions (id, tenant_id, ip_hash, affiliate_id, order_id, referral_code)
VALUES 
  ('5eed8888-8888-8888-8888-888888888881'::uuid, '5eed0000-0000-0000-0000-000000000001', 'seed_ip_hash_001', '5eed2222-2222-2222-2222-222222222221'::uuid, 'seed_ord_001', 'seed_surv_01');

-- 7.6 Shop Subscriptions
INSERT INTO public.shop_subscriptions (
    id, tenant_slug, tenant_id, affiliate_id, status, amount, 
    current_period_ends_at, expires_at, xendit_invoice_id
)
VALUES 
  ('5eed9999-9999-9999-9999-999999999991'::uuid, 'seed_tenant_a', '5eed0000-0000-0000-0000-000000000001', 
   '5eed2222-2222-2222-2222-222222222221'::uuid, 'ACTIVE', 299000.00, 
   now() + interval '30 days', now() + interval '30 days', 'seed_inv_001');

-- 7.7 Shop Commission Ledger
INSERT INTO public.shop_commission_ledger (
    id, subscription_id, tenant_slug, tenant_id, affiliate_id, 
    gross_amount, affiliate_amount, am_amount, platform_net_amount, status
)
VALUES 
  ('5eedaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'::uuid, '5eed9999-9999-9999-9999-999999999991'::uuid, 
   'seed_tenant_a', '5eed0000-0000-0000-0000-000000000001', '5eed2222-2222-2222-2222-222222222221'::uuid, 
   299000.00, 29900.00, 0.00, 269100.00, 'COMPLETED');

-- -----------------------------------------------------------------------------
-- [STAGE 8] POSTCONDITION VALIDATION ASSERTIONS
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_aff_cnt INT;
    v_comm_cnt INT;
    v_quar_cnt INT;
    v_map_cnt INT;
    v_ord_cnt INT;
    v_po_cnt INT;
    v_do_cnt INT;
    v_attr_cnt INT;
    v_sess_cnt INT;
    v_sub_cnt INT;
    v_ledg_cnt INT;
BEGIN
    SELECT COUNT(*) INTO v_aff_cnt FROM public.affiliates 
    WHERE id IN ('5eed1111-1111-1111-1111-111111111111'::uuid, 
                 '5eed2222-2222-2222-2222-222222222221'::uuid, 
                 '5eed2222-2222-2222-2222-222222222222'::uuid);
                 
    SELECT COUNT(*) INTO v_comm_cnt FROM public.affiliate_commissions 
    WHERE id = '5eed3333-3333-3333-3333-333333333331'::uuid;
    
    SELECT COUNT(*) INTO v_quar_cnt FROM public.migration_031_quarantined_affiliate_commissions 
    WHERE id = '5eed4444-4444-4444-4444-444444444441'::uuid;
    
    SELECT COUNT(*) INTO v_map_cnt FROM public.migration_031_identifier_dedup_map 
    WHERE map_id IN ('5eed5555-5555-5555-5555-555555555551'::uuid, 
                     '5eed5555-5555-5555-5555-555555555552'::uuid,
                     '5eed5555-5555-5555-5555-555555555553'::uuid);
                     
    SELECT COUNT(*) INTO v_ord_cnt FROM public.orders 
    WHERE id IN ('seed_ord_001', 'seed_ord_002');
    
    SELECT COUNT(*) INTO v_po_cnt FROM public.product_orders 
    WHERE id = 50001;
    
    SELECT COUNT(*) INTO v_do_cnt FROM public.delivery_orders 
    WHERE id = '5eed6666-6666-6666-6666-666666666661'::uuid;
    
    SELECT COUNT(*) INTO v_attr_cnt FROM public.attributions 
    WHERE id = '5eed7777-7777-7777-7777-777777777771'::uuid;
    
    SELECT COUNT(*) INTO v_sess_cnt FROM public.attribution_sessions 
    WHERE id = '5eed8888-8888-8888-8888-888888888881'::uuid;
    
    SELECT COUNT(*) INTO v_sub_cnt FROM public.shop_subscriptions 
    WHERE id = '5eed9999-9999-9999-9999-999999999991'::uuid;
    
    SELECT COUNT(*) INTO v_ledg_cnt FROM public.shop_commission_ledger 
    WHERE id = '5eedaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'::uuid;

    IF v_aff_cnt <> 3 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 3 seeded affiliates, found %', v_aff_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_comm_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded clean commission, found %', v_comm_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_quar_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded quarantined commission, found %', v_quar_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_map_cnt <> 3 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 3 seeded dedup map rows, found %', v_map_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_ord_cnt <> 2 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 2 seeded orders, found %', v_ord_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_po_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded product_order, found %', v_po_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_do_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded delivery_order, found %', v_do_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_attr_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded attribution, found %', v_attr_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_sess_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded attribution_session, found %', v_sess_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_sub_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded shop_subscription, found %', v_sub_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_ledg_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded shop_commission_ledger, found %', v_ledg_cnt USING ERRCODE = 'P0003';
    END IF;
END $$;

COMMIT;
