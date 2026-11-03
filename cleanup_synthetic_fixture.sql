-- =============================================================================
-- BOONTRACK SYNTHETIC FIXTURE TEARDOWN & CLEANUP SCRIPT (REV 4.1.6.2.11)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Purpose: Unconditional, idempotent deletion of the 13 synthetic UUIDs
-- Safety: Pre-snapshot and post-comparison guarantees 100% untouched historical production rows.
-- Ownership: Pre-deletion verification proves every targeted row belongs strictly to the synthetic seed run.
-- Tenant Policy: Tenant anchor '00000000-0000-0000-0000-000000000001' is PRESERVED (NOT DELETED).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- TAHAP 1: PRE-OPERATION SNAPSHOT NILAI RELEVAN 5 BARIS HISTORIS & TENANT JANGKAR
-- Menyimpan seluruh 7 kolom data affiliates + kolom tenant anchor
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS pg_temp._historical_affiliates_pre_snapshot;
CREATE TEMP TABLE pg_temp._historical_affiliates_pre_snapshot AS
SELECT 
    id::text, 
    tenant_id::text, 
    name::text, 
    phone_number::text, 
    referral_code::text, 
    commission_rate::numeric, 
    status::text
FROM public.affiliates
WHERE id IN (
    '25305f9c-ed1b-4e84-8771-325b5dde23ee',
    '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae',
    '43e48443-dcfa-47a6-818c-5144e3a34db4',
    'b92b0929-1dbd-4f80-b875-94e9ab92b189',
    'f5b98eaa-cfde-49cf-a497-491221c1cda9'
);

-- Snapshot Tenant Jangkar (Jika ada sebelum cleanup)
DROP TABLE IF EXISTS pg_temp._historical_tenant_pre_snapshot;
CREATE TEMP TABLE pg_temp._historical_tenant_pre_snapshot AS
SELECT id::text, name::text, slug::text
FROM public.tenants
WHERE id = '00000000-0000-0000-0000-000000000001';

-- Asersi Pre-Snapshot: Wajib tepat 5 baris affiliates
DO $$
DECLARE
    v_pre_cnt INT;
BEGIN
    SELECT count(*) INTO v_pre_cnt FROM pg_temp._historical_affiliates_pre_snapshot;
    IF v_pre_cnt <> 5 THEN
        RAISE EXCEPTION 'PRE-CLEANUP PREFLIGHT ERROR: Expected 5 historical affiliates in snapshot, found %', v_pre_cnt USING ERRCODE = 'P0001';
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- TAHAP 1.5: VERIFIKASI KEPEMILIKAN & PAYLOAD FIXTURE SEBELUM PENGHAPUSAN (OWNERSHIP PROOF)
-- Membuktikan secara deterministik bahwa seluruh baris yang akan dihapus adalah murni
-- milik seed run sintetis, bukan data produksi atau data lain yang kebetulan bertabrakan ID.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_mismatch_desc TEXT;
BEGIN
    -- 1. Verifikasi Kepemilikan Affiliates Sintetis
    IF EXISTS (
        SELECT 1 FROM public.affiliates 
        WHERE id = '11111111-1111-1111-1111-111111111111'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR name <> 'SYNTH_AFF_CLEAN_001' OR phone_number <> '081200000001' OR referral_code <> 'CLEAN01' OR commission_rate <> 0.10 OR status <> 'ACTIVE')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Affiliate 11111111-1111-1111-1111-111111111111 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.affiliates 
        WHERE id = '22222222-2222-2222-2222-222222222221'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR name <> 'SYNTH_AFF_SURV_001' OR phone_number <> '081200000002' OR referral_code <> 'SURV01' OR commission_rate <> 0.10 OR status <> 'ACTIVE')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Affiliate 22222222-2222-2222-2222-222222222221 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.affiliates 
        WHERE id = '22222222-2222-2222-2222-222222222222'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR name <> 'SYNTH_AFF_LOSER_001' OR phone_number <> '081200000003' OR referral_code <> 'LOSER01' OR commission_rate <> 0.10 OR status <> 'ACTIVE')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Affiliate 22222222-2222-2222-2222-222222222222 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 2. Verifikasi Kepemilikan Komisi Bersih
    IF EXISTS (
        SELECT 1 FROM public.affiliate_commissions
        WHERE id = '11111111-1111-1111-1111-111111111112'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '11111111-1111-1111-1111-111111111111' OR order_id <> 'ORD_CLEAN_001' OR order_amount <> 500000 OR amount <> 50000 OR status <> 'PAID')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Commission 11111111-1111-1111-1111-111111111112 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 3. Verifikasi Kepemilikan Komisi Karantina
    IF EXISTS (
        SELECT 1 FROM public.migration_031_quarantined_affiliate_commissions
        WHERE id = '33333333-3333-3333-3333-333333333331'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '11111111-1111-1111-1111-111111111111' OR order_id <> 'ORD_QUAR_001' OR amount <> 75000 OR status <> 'QUARANTINED' OR quarantine_reason <> 'CROSS_TENANT_DISCREPANCY_DETECTED')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Quarantined commission 33333333-3333-3333-3333-333333333331 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 4. Verifikasi Kepemilikan Dedup Map
    IF EXISTS (
        SELECT 1 FROM public.migration_031_identifier_dedup_map
        WHERE map_id = 'e1111111-1111-1111-1111-111111111111'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR dedup_rank <> 1 OR new_status <> 'SURVIVOR')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Dedup map e1111111-1111-1111-1111-111111111111 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.migration_031_identifier_dedup_map
        WHERE map_id = 'e2222222-2222-2222-2222-222222222222'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR dedup_rank <> 2 OR new_status <> 'SUPERSEDED_DUPLICATE')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Dedup map e2222222-2222-2222-2222-222222222222 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 5. Verifikasi Kepemilikan Orders
    IF EXISTS (
        SELECT 1 FROM public.orders
        WHERE id = '44444444-4444-4444-4444-444444444441'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '22222222-2222-2222-2222-222222222222' OR manager_id IS NOT NULL OR gross_amount <> 100000 OR status <> 'PENDING')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Order 44444444-4444-4444-4444-444444444441 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.orders
        WHERE id = '44444444-4444-4444-4444-444444444442'
          AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id IS NOT NULL OR manager_id <> '22222222-2222-2222-2222-222222222222' OR gross_amount <> 150000 OR status <> 'PENDING')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Order 44444444-4444-4444-4444-444444444442 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 6. Verifikasi Kepemilikan Child Tables
    IF EXISTS (SELECT 1 FROM public.product_orders WHERE id = 44444443 AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '22222222-2222-2222-2222-222222222222' OR order_id <> 'PO_CHILD_001')) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Product Order 44444443 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (SELECT 1 FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444' AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '22222222-2222-2222-2222-222222222222' OR provider <> 'JNE' OR order_id <> 'ORD_DO_001')) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Delivery Order 44444444-4444-4444-4444-444444444444 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (SELECT 1 FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445' AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '22222222-2222-2222-2222-222222222222' OR session_id <> 'SESS_001')) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Attribution 44444444-4444-4444-4444-444444444445 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (SELECT 1 FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446' AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '22222222-2222-2222-2222-222222222222' OR ip_hash <> 'HASH_001')) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Attribution Session 44444444-4444-4444-4444-444444444446 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (SELECT 1 FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447' AND (tenant_id <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '22222222-2222-2222-2222-222222222222' OR amount <> 299000)) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Subscription 44444444-4444-4444-4444-444444444447 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (SELECT 1 FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448' AND (tenant_slug <> '00000000-0000-0000-0000-000000000001' OR affiliate_id <> '22222222-2222-2222-2222-222222222222' OR gross_amount <> 299000 OR affiliate_amount <> 29900)) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Ledger 44444444-4444-4444-4444-444444444448 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- TAHAP 2: PENGHAPUSAN EKSKLUSIF DENGAN KUALIFIKASI KEPEMILIKAN LENGKAP
-- Menghapus hanya baris yang memenuhi ID dan seluruh atribut kepemilikan sintetis.
-- CATATAN: Tenant jangkar '00000000-0000-0000-0000-000000000001' TIDAK DIHAPUS.
-- -----------------------------------------------------------------------------
DELETE FROM public.shop_commission_ledger 
WHERE id = '44444444-4444-4444-4444-444444444448'
  AND tenant_slug = '00000000-0000-0000-0000-000000000001'
  AND affiliate_id = '22222222-2222-2222-2222-222222222222';

DELETE FROM public.shop_subscriptions 
WHERE id = '44444444-4444-4444-4444-444444444447'
  AND tenant_id = '00000000-0000-0000-0000-000000000001'
  AND affiliate_id = '22222222-2222-2222-2222-222222222222';

DELETE FROM public.attribution_sessions 
WHERE id = '44444444-4444-4444-4444-444444444446'
  AND tenant_id = '00000000-0000-0000-0000-000000000001'
  AND affiliate_id = '22222222-2222-2222-2222-222222222222';

DELETE FROM public.attributions 
WHERE id = '44444444-4444-4444-4444-444444444445'
  AND tenant_id = '00000000-0000-0000-0000-000000000001'
  AND affiliate_id = '22222222-2222-2222-2222-222222222222';

DELETE FROM public.delivery_orders 
WHERE id = '44444444-4444-4444-4444-444444444444'
  AND tenant_id = '00000000-0000-0000-0000-000000000001'
  AND affiliate_id = '22222222-2222-2222-2222-222222222222';

DELETE FROM public.product_orders 
WHERE id = 44444443
  AND tenant_id = '00000000-0000-0000-0000-000000000001'
  AND affiliate_id = '22222222-2222-2222-2222-222222222222';

DELETE FROM public.orders 
WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442')
  AND tenant_id = '00000000-0000-0000-0000-000000000001';

DELETE FROM public.migration_031_identifier_dedup_map 
WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222')
  AND tenant_id = '00000000-0000-0000-0000-000000000001';

DELETE FROM public.migration_031_quarantined_affiliate_commissions 
WHERE id = '33333333-3333-3333-3333-333333333331'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';

DELETE FROM public.affiliate_commissions 
WHERE id = '11111111-1111-1111-1111-111111111112'
  AND tenant_id = '00000000-0000-0000-0000-000000000001';

DELETE FROM public.affiliates 
WHERE id IN (
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222221',
  '22222222-2222-2222-2222-222222222222'
)
AND tenant_id = '00000000-0000-0000-0000-000000000001';

-- -----------------------------------------------------------------------------
-- TAHAP 3: VERIFIKASI POST-CLEANUP: EXACT-VALUE TWO-WAY EXCEPT RECONCILIATION
-- Membuktikan secara matematis bahwa tidak ada satu kolom pun yang bermutasi pada 5 baris historis.
-- Membuktikan pula bahwa tenant jangkar tetap utuh.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_forward_diff INT;
    v_reverse_diff INT;
    v_post_cnt INT;
    v_tenant_diff INT;
BEGIN
    -- 1. Forward Difference: Snapshot EXCEPT Current (Harus 0)
    SELECT COUNT(*) INTO v_forward_diff FROM (
        SELECT id, tenant_id, name, phone_number, referral_code, commission_rate, status 
        FROM pg_temp._historical_affiliates_pre_snapshot
        EXCEPT
        SELECT id::text, tenant_id::text, name::text, phone_number::text, referral_code::text, commission_rate::numeric, status::text 
        FROM public.affiliates
    ) fwd;

    IF v_forward_diff <> 0 THEN
        RAISE EXCEPTION 'CRITICAL CORRUPTION: Historical production rows modified or missing after cleanup (forward diff = %)!', v_forward_diff USING ERRCODE = 'P0001';
    END IF;

    -- 2. Reverse Difference: Current EXCEPT Snapshot (Harus 0)
    SELECT COUNT(*) INTO v_reverse_diff FROM (
        SELECT id::text, tenant_id::text, name::text, phone_number::text, referral_code::text, commission_rate::numeric, status::text 
        FROM public.affiliates
        WHERE id IN (
            '25305f9c-ed1b-4e84-8771-325b5dde23ee',
            '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae',
            '43e48443-dcfa-47a6-818c-5144e3a34db4',
            'b92b0929-1dbd-4f80-b875-94e9ab92b189',
            'f5b98eaa-cfde-49cf-a497-491221c1cda9'
        )
        EXCEPT
        SELECT id, tenant_id, name, phone_number, referral_code, commission_rate, status 
        FROM pg_temp._historical_affiliates_pre_snapshot
    ) rev;

    IF v_reverse_diff <> 0 THEN
        RAISE EXCEPTION 'CRITICAL CORRUPTION: Historical production rows altered after cleanup (reverse diff = %)!', v_reverse_diff USING ERRCODE = 'P0001';
    END IF;

    -- 3. Cardinality Equality Check Affiliates
    SELECT count(*) INTO v_post_cnt 
    FROM public.affiliates 
    WHERE id IN (
        '25305f9c-ed1b-4e84-8771-325b5dde23ee',
        '2ad6fc0a-1a11-4e52-8d94-65997d5ad9ae',
        '43e48443-dcfa-47a6-818c-5144e3a34db4',
        'b92b0929-1dbd-4f80-b875-94e9ab92b189',
        'f5b98eaa-cfde-49cf-a497-491221c1cda9'
    );

    IF v_post_cnt <> 5 THEN
        RAISE EXCEPTION 'CRITICAL INTEGRITY FAILURE: Expected 5 historical affiliates post-cleanup, found %', v_post_cnt USING ERRCODE = 'P0001';
    END IF;

    -- 4. Verifikasi Tenant Jangkar (Tidak Boleh Terhapus atau Bermutasi)
    SELECT COUNT(*) INTO v_tenant_diff FROM (
        SELECT id, name, slug FROM pg_temp._historical_tenant_pre_snapshot
        EXCEPT
        SELECT id::text, name::text, slug::text FROM public.tenants
    ) td;

    IF v_tenant_diff <> 0 THEN
        RAISE EXCEPTION 'CRITICAL INTEGRITY FAILURE: Tenant anchor modified or deleted during cleanup!' USING ERRCODE = 'P0001';
    END IF;
END $$;
