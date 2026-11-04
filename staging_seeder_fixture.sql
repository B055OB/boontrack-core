-- =============================================================================
-- BOONTRACK STAGING SYNTHETIC SEEDER FIXTURE (REV 4.1.7)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Scope: 13 Synthetic Entities (Clean, Dedup Survivor/Loser, Quarantine, 8 FK Streams)
-- Isolation Invariant: Strictly namespaced IDs with 'seed_*' prefix or '5eed*' UUIDs.
-- Safety Invariant: Precondition asserts 0 collision with existing staging rows.
-- Zero-Touch Guarantee: Production DB and Cloudflare R2 strictly untouched.
-- =============================================================================

BEGIN;

SET LOCAL statement_timeout = '10s';
SET LOCAL lock_timeout = '2s';

-- -----------------------------------------------------------------------------
-- [STAGE 0] PRECONDITION AUDIT & ISOLATION ASSERTION
-- Memverifikasi bahwa lingkungan staging bersih dari artefak seeded sebelumnya
-- dan menjamin tidak ada tabrakan dengan 5 data afiliasi historis eksisting.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_colliding_count INT;
    v_historical_affiliates_count INT;
BEGIN
    -- 1. Periksa tabrakan ID terisolasi ('seed_%' atau '5eed%')
    SELECT (
        (SELECT COUNT(*) FROM public.tenants WHERE id::text LIKE '5eed%' OR slug LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.affiliates WHERE id::text LIKE '5eed%' OR name LIKE 'seed_%' OR referral_code LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.affiliate_commissions WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.orders WHERE id::text LIKE 'seed_%' OR id::text LIKE '5eed%') +
        (SELECT COUNT(*) FROM public.product_orders WHERE order_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.delivery_orders WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.attributions WHERE id::text LIKE '5eed%' OR session_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.attribution_sessions WHERE id::text LIKE '5eed%' OR order_id LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.shop_subscriptions WHERE id::text LIKE '5eed%' OR tenant_slug LIKE 'seed_%') +
        (SELECT COUNT(*) FROM public.shop_commission_ledger WHERE id::text LIKE '5eed%' OR tenant_slug LIKE 'seed_%')
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
-- [STAGE 1] TENANT ANCHOR
-- Tenant terisolasi khusus pengujian sintetis
-- -----------------------------------------------------------------------------
INSERT INTO public.tenants (id, slug)
VALUES ('5eed0000-0000-0000-0000-000000000001', 'seed_tenant_a')
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- [STAGE 2] AFFILIATES (3 Rows: 1 Clean, 1 Survivor, 1 Loser)
-- -----------------------------------------------------------------------------
INSERT INTO public.affiliates (
    id, tenant_id, name, phone_number, referral_code, commission_rate, status, role
)
VALUES 
  ('5eed1111-1111-1111-1111-111111111111', '5eed0000-0000-0000-0000-000000000001', 'seed_aff_clean_001', '081200000001', 'seed_clean_01', 10.00, 'ACTIVE', 'affiliate'),
  ('5eed2222-2222-2222-2222-222222222221', '5eed0000-0000-0000-0000-000000000001', 'seed_aff_surv_001',  '081200000002', 'seed_surv_01',  10.00, 'ACTIVE', 'affiliate'),
  ('5eed2222-2222-2222-2222-222222222222', '5eed0000-0000-0000-0000-000000000001', 'seed_aff_loser_001', '081200000003', 'seed_loser_01', 10.00, 'ACTIVE', 'affiliate');

-- -----------------------------------------------------------------------------
-- [STAGE 3] AFFILIATE COMMISSIONS (1 Clean Row)
-- -----------------------------------------------------------------------------
INSERT INTO public.affiliate_commissions (
    id, tenant_id, affiliate_id, order_id, order_amount, amount, status
)
VALUES 
  ('5eed3333-3333-3333-3333-333333333331', '5eed0000-0000-0000-0000-000000000001', '5eed1111-1111-1111-1111-111111111111', 'seed_ord_clean_001', 500000.00, 50000.00, 'PAID');

-- -----------------------------------------------------------------------------
-- [STAGE 4] QUARANTINED COMMISSIONS (1 Physically Isolated Row)
-- -----------------------------------------------------------------------------
INSERT INTO public.migration_031_quarantined_affiliate_commissions (
    id, migration_batch_id, tenant_id, original_tenant_id, affiliate_id, order_id, order_amount, amount, 
    commission_type, original_status, quarantine_reason, distinct_tenant_count, row_snapshot, approval_status
)
VALUES (
    '5eed4444-4444-4444-4444-444444444441', 'seed_batch_001', '5eed0000-0000-0000-0000-000000000001', 
    '5eed0000-0000-0000-0000-000000000001', '5eed1111-1111-1111-1111-111111111111', 'seed_ord_quar_001', 
    750000.00, 75000.00, 'PRODUCT_ORDER', 'PENDING', 'CROSS_TENANT_DISCREPANCY_DETECTED', 1, '{}'::jsonb, 'QUARANTINED_LOCKED'
);

-- -----------------------------------------------------------------------------
-- [STAGE 5] IDENTIFIER DEDUP GOVERNANCE MAP (2 Rows: Survivor rank=1 & Loser rank=2)
-- -----------------------------------------------------------------------------
INSERT INTO public.migration_031_identifier_dedup_map (
    map_id, migration_batch_id, table_name, column_name, tenant_id, 
    quarantined_row_id, canonical_survivor_id, original_identifier_value, 
    new_identifier_value, dedup_rank, new_status, resolution_reason, 
    requires_finance_reconciliation, downstream_references, row_snapshot, retry_count,
    created_at, last_reconciled_at
)
VALUES 
  ('5eed5555-5555-5555-5555-555555555551', 'seed_batch_001', 'affiliates', 'id', '5eed0000-0000-0000-0000-000000000001',
   '5eed2222-2222-2222-2222-222222222221', '5eed2222-2222-2222-2222-222222222221', '5eed2222-2222-2222-2222-222222222221',
   '5eed2222-2222-2222-2222-222222222221', 1, 'SURVIVOR', 'AUTHORITATIVE_PRIMARY_IDENTITY',
   false, '[]'::jsonb, '{}'::jsonb, 0, now(), now()),
  ('5eed5555-5555-5555-5555-555555555552', 'seed_batch_001', 'affiliates', 'id', '5eed0000-0000-0000-0000-000000000001',
   '5eed2222-2222-2222-2222-222222222222', '5eed2222-2222-2222-2222-222222222221', '5eed2222-2222-2222-2222-222222222222',
   '5eed2222-2222-2222-2222-222222222221', 2, 'SUPERSEDED_DUPLICATE', 'MERGED_TO_SURVIVOR',
   false, '[]'::jsonb, '{}'::jsonb, 0, now(), now());

-- -----------------------------------------------------------------------------
-- [STAGE 6] CHILD ENTITIES (7 Tables, 8 Streams repointed from Loser)
-- -----------------------------------------------------------------------------

-- 6.1 Orders (2 streams: affiliate_id and manager_id)
INSERT INTO public.orders (id, tenant_id, affiliate_id, manager_id, status, gross_amount)
VALUES 
  ('seed_ord_001', '5eed0000-0000-0000-0000-000000000001', '5eed2222-2222-2222-2222-222222222222'::uuid, NULL, 'PENDING', 100000.00),
  ('seed_ord_002', '5eed0000-0000-0000-0000-000000000001', NULL, '5eed2222-2222-2222-2222-222222222222'::uuid, 'PENDING', 150000.00);

-- 6.2 Product Orders
INSERT INTO public.product_orders (id, order_id, tenant_id, affiliate_id, status)
VALUES 
  (50001, 'seed_ord_001', '5eed0000-0000-0000-0000-000000000001', '5eed2222-2222-2222-2222-222222222222'::uuid, 'PENDING');

-- 6.3 Delivery Orders
INSERT INTO public.delivery_orders (id, tenant_id, order_id, provider, service_type, affiliate_id, status)
VALUES 
  ('5eed6666-6666-6666-6666-666666666661', '5eed0000-0000-0000-0000-000000000001', 'seed_ord_001', 'JNE', 'REG', '5eed2222-2222-2222-2222-222222222222'::uuid, 'PENDING');

-- 6.4 Attributions
INSERT INTO public.attributions (id, tenant_id, session_id, ip_hash, affiliate_id)
VALUES 
  ('5eed7777-7777-7777-7777-777777777771', '5eed0000-0000-0000-0000-000000000001', 'seed_sess_001', 'seed_ip_hash_001', '5eed2222-2222-2222-2222-222222222222'::uuid);

-- 6.5 Attribution Sessions
INSERT INTO public.attribution_sessions (id, tenant_id, ip_hash, affiliate_id, order_id, referral_code)
VALUES 
  ('5eed8888-8888-8888-8888-888888888881', '5eed0000-0000-0000-0000-000000000001', 'seed_ip_hash_001', '5eed2222-2222-2222-2222-222222222222'::uuid, 'seed_ord_001', 'seed_loser_01');

-- 6.6 Shop Subscriptions
INSERT INTO public.shop_subscriptions (
    id, tenant_slug, tenant_id, affiliate_id, status, amount, 
    current_period_ends_at, expires_at, xendit_invoice_id
)
VALUES 
  ('5eed9999-9999-9999-9999-999999999991', 'seed_tenant_a', '5eed0000-0000-0000-0000-000000000001', 
   '5eed2222-2222-2222-2222-222222222222'::uuid, 'ACTIVE', 299000.00, 
   now() + interval '30 days', now() + interval '30 days', 'seed_inv_001');

-- 6.7 Shop Commission Ledger
INSERT INTO public.shop_commission_ledger (
    id, subscription_id, tenant_slug, tenant_id, affiliate_id, 
    gross_amount, affiliate_amount, am_amount, platform_net_amount, status
)
VALUES 
  ('5eedaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '5eed9999-9999-9999-9999-999999999991', 
   'seed_tenant_a', '5eed0000-0000-0000-0000-000000000001', '5eed2222-2222-2222-2222-222222222222'::uuid, 
   299000.00, 29900.00, 0.00, 269100.00, 'COMPLETED');

-- -----------------------------------------------------------------------------
-- [STAGE 7] POSTCONDITION VALIDATION ASSERTIONS
-- Memverifikasi bahwa seluruh 13 entitas sintetis terinjeksi dengan benar
-- dan 100% menggunakan ID terisolasi ('seed_*' atau '5eed*').
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
    SELECT COUNT(*) INTO v_aff_cnt FROM public.affiliates WHERE id::text LIKE '5eed%';
    SELECT COUNT(*) INTO v_comm_cnt FROM public.affiliate_commissions WHERE id::text LIKE '5eed%';
    SELECT COUNT(*) INTO v_quar_cnt FROM public.migration_031_quarantined_affiliate_commissions WHERE id::text LIKE '5eed%';
    SELECT COUNT(*) INTO v_map_cnt FROM public.migration_031_identifier_dedup_map WHERE map_id::text LIKE '5eed%';
    SELECT COUNT(*) INTO v_ord_cnt FROM public.orders WHERE id LIKE 'seed_%';
    SELECT COUNT(*) INTO v_po_cnt FROM public.product_orders WHERE order_id LIKE 'seed_%';
    SELECT COUNT(*) INTO v_do_cnt FROM public.delivery_orders WHERE id::text LIKE '5eed%';
    SELECT COUNT(*) INTO v_attr_cnt FROM public.attributions WHERE id::text LIKE '5eed%';
    SELECT COUNT(*) INTO v_sess_cnt FROM public.attribution_sessions WHERE id::text LIKE '5eed%';
    SELECT COUNT(*) INTO v_sub_cnt FROM public.shop_subscriptions WHERE id::text LIKE '5eed%';
    SELECT COUNT(*) INTO v_ledg_cnt FROM public.shop_commission_ledger WHERE id::text LIKE '5eed%';

    IF v_aff_cnt <> 3 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 3 seeded affiliates, found %', v_aff_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_comm_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded clean commission, found %', v_comm_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_quar_cnt <> 1 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 1 seeded quarantined commission, found %', v_quar_cnt USING ERRCODE = 'P0003';
    END IF;
    IF v_map_cnt <> 2 THEN
        RAISE EXCEPTION 'POSTCONDITION ERROR: Expected 2 seeded dedup map rows, found %', v_map_cnt USING ERRCODE = 'P0003';
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
