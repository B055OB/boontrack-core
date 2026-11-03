-- =============================================================================
-- BOONTRACK SYNTHETIC FIXTURE TEARDOWN & CLEANUP SCRIPT (REV 4.1.6.2.11)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Purpose: Unconditional, idempotent deletion of the 13 synthetic UUIDs
-- Safety: Pre-snapshot and post-comparison guarantees 100% untouched historical production rows.
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
-- TAHAP 2: PENGHAPUSAN EKSKLUSIF FIXTURE SINTETIS (STRICT ID-TARGETED ONLY)
-- CATATAN KEAMANAN CTO: Tenant jangkar '00000000-0000-0000-0000-000000000001'
-- TIDAK DIHAPUS untuk mencegah penghapusan dependensi yang bukan milik eksklusif seed.
-- -----------------------------------------------------------------------------
DELETE FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448';
DELETE FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447';
DELETE FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446';
DELETE FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445';
DELETE FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444';
DELETE FROM public.product_orders WHERE id = 44444443;
DELETE FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442');

DELETE FROM public.migration_031_identifier_dedup_map 
WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222');

DELETE FROM public.migration_031_quarantined_affiliate_commissions 
WHERE id = '33333333-3333-3333-3333-333333333331';

DELETE FROM public.affiliate_commissions 
WHERE id = '11111111-1111-1111-1111-111111111112';

DELETE FROM public.affiliates 
WHERE id IN (
  '11111111-1111-1111-1111-111111111111',
  '22222222-2222-2222-2222-222222222221',
  '22222222-2222-2222-2222-222222222222'
);

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
        RAISE EXCEPTION 'CRITICAL INTEGRITY FAILURE: Tenant anchor modified or deleted during cleanup!', USING ERRCODE = 'P0001';
    END IF;
END $$;
