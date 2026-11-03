-- =============================================================================
-- BOONTRACK SYNTHETIC FIXTURE TEARDOWN & CLEANUP SCRIPT (REV 4.1.6.2.11)
-- Target: Staging Database (xkhqirhurnjqglmajghn:5432)
-- Purpose: Provable, zero-residual deletion of the 13 synthetic UUIDs
-- Safety: Pre-snapshot, two-way EXCEPT, and postcondition guarantees 100% untouched historical production rows.
-- Ownership: Full payload verification with NULL-safe semantics (IS DISTINCT FROM) and row locking (FOR UPDATE).
-- Zero-Residual: Postcondition proves 0 residual fixture rows remain post-cleanup.
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
SELECT id::text, slug::text
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
-- TAHAP 1.5: VERIFIKASI KEPEMILIKAN & PAYLOAD LENGKAP DENGAN NULL-SAFE SEMANTICS & ROW LOCKING
-- Menggunakan SELECT ... FOR UPDATE untuk mencegah race condition bersamaan,
-- dan IS DISTINCT FROM untuk menangani NULL secara fail-closed pada seluruh kolom seed.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    -- 0. Row Locking: Kunci seluruh baris fixture yang ditemukan dalam transaksi ini
    PERFORM 1 FROM public.affiliates WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222') FOR UPDATE;
    PERFORM 1 FROM public.affiliate_commissions WHERE id = '11111111-1111-1111-1111-111111111112' FOR UPDATE;
    PERFORM 1 FROM public.migration_031_quarantined_affiliate_commissions WHERE id = '33333333-3333-3333-3333-333333333331' FOR UPDATE;
    PERFORM 1 FROM public.migration_031_identifier_dedup_map WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222') FOR UPDATE;
    PERFORM 1 FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442') FOR UPDATE;
    PERFORM 1 FROM public.product_orders WHERE id = 44444443 FOR UPDATE;
    PERFORM 1 FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444' FOR UPDATE;
    PERFORM 1 FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445' FOR UPDATE;
    PERFORM 1 FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446' FOR UPDATE;
    PERFORM 1 FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447' FOR UPDATE;
    PERFORM 1 FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448' FOR UPDATE;

    -- 1. Verifikasi Kepemilikan Affiliates (Seluruh 7 Kolom)
    IF EXISTS (
        SELECT 1 FROM public.affiliates 
        WHERE id = '11111111-1111-1111-1111-111111111111'
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR name IS DISTINCT FROM 'SYNTH_AFF_CLEAN_001' 
            OR phone_number IS DISTINCT FROM '081200000001' 
            OR referral_code IS DISTINCT FROM 'CLEAN01' 
            OR commission_rate::numeric IS DISTINCT FROM 0.10 
            OR status IS DISTINCT FROM 'ACTIVE')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Affiliate 11111111-1111-1111-1111-111111111111 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.affiliates 
        WHERE id = '22222222-2222-2222-2222-222222222221'
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR name IS DISTINCT FROM 'SYNTH_AFF_SURV_001' 
            OR phone_number IS DISTINCT FROM '081200000002' 
            OR referral_code IS DISTINCT FROM 'SURV01' 
            OR commission_rate::numeric IS DISTINCT FROM 0.10 
            OR status IS DISTINCT FROM 'ACTIVE')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Affiliate 22222222-2222-2222-2222-222222222221 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.affiliates 
        WHERE id = '22222222-2222-2222-2222-222222222222'
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR name IS DISTINCT FROM 'SYNTH_AFF_LOSER_001' 
            OR phone_number IS DISTINCT FROM '081200000003' 
            OR referral_code IS DISTINCT FROM 'LOSER01' 
            OR commission_rate::numeric IS DISTINCT FROM 0.10 
            OR status IS DISTINCT FROM 'ACTIVE')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Affiliate 22222222-2222-2222-2222-222222222222 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 2. Verifikasi Kepemilikan Komisi Bersih (Seluruh 7 Kolom)
    IF EXISTS (
        SELECT 1 FROM public.affiliate_commissions
        WHERE id = '11111111-1111-1111-1111-111111111112'
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR affiliate_id::text IS DISTINCT FROM '11111111-1111-1111-1111-111111111111' 
            OR order_id IS DISTINCT FROM 'ORD_CLEAN_001' 
            OR order_amount::numeric IS DISTINCT FROM 500000 
            OR amount::numeric IS DISTINCT FROM 50000 
            OR status IS DISTINCT FROM 'PAID')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Commission 11111111-1111-1111-1111-111111111112 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 3. Verifikasi Kepemilikan Komisi Karantina (Seluruh 12 Kolom Ditulis)
    IF EXISTS (
        SELECT 1 FROM public.migration_031_quarantined_affiliate_commissions
        WHERE id = '33333333-3333-3333-3333-333333333331'
          AND (migration_batch_id IS DISTINCT FROM 'BATCH_SYNTH_001'
            OR tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001'
            OR original_tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001'
            OR affiliate_id::text IS DISTINCT FROM '11111111-1111-1111-1111-111111111111'
            OR order_id IS DISTINCT FROM 'ORD_QUAR_001'
            OR order_amount::numeric IS DISTINCT FROM 750000
            OR amount::numeric IS DISTINCT FROM 75000
            OR original_status IS DISTINCT FROM 'PENDING'
            OR status IS DISTINCT FROM 'QUARANTINED'
            OR quarantine_reason IS DISTINCT FROM 'CROSS_TENANT_DISCREPANCY_DETECTED'
            OR approval_status IS DISTINCT FROM 'QUARANTINED_LOCKED'
            OR row_snapshot::text IS DISTINCT FROM '{}')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Quarantined commission 33333333-3333-3333-3333-333333333331 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 4. Verifikasi Kepemilikan Dedup Map (Seluruh 12 Kolom Ditulis: Rank 1 & 2)
    IF EXISTS (
        SELECT 1 FROM public.migration_031_identifier_dedup_map
        WHERE map_id = 'e1111111-1111-1111-1111-111111111111'
          AND (migration_batch_id IS DISTINCT FROM 'BATCH_SYNTH_001'
            OR table_name IS DISTINCT FROM 'affiliates'
            OR column_name IS DISTINCT FROM 'id'
            OR tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001'
            OR quarantined_row_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222221'
            OR canonical_survivor_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222221'
            OR original_identifier_value IS DISTINCT FROM '22222222-2222-2222-2222-222222222221'
            OR new_identifier_value IS DISTINCT FROM '22222222-2222-2222-2222-222222222221'
            OR dedup_rank IS DISTINCT FROM 1
            OR new_status IS DISTINCT FROM 'SURVIVOR'
            OR resolution_reason IS DISTINCT FROM 'AUTHORITATIVE_PRIMARY_IDENTITY'
            OR row_snapshot::text IS DISTINCT FROM '{}')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Dedup map e1111111-1111-1111-1111-111111111111 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.migration_031_identifier_dedup_map
        WHERE map_id = 'e2222222-2222-2222-2222-222222222222'
          AND (migration_batch_id IS DISTINCT FROM 'BATCH_SYNTH_001'
            OR table_name IS DISTINCT FROM 'affiliates'
            OR column_name IS DISTINCT FROM 'id'
            OR tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001'
            OR quarantined_row_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222'
            OR canonical_survivor_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222221'
            OR original_identifier_value IS DISTINCT FROM '22222222-2222-2222-2222-222222222222'
            OR new_identifier_value IS DISTINCT FROM '22222222-2222-2222-2222-222222222221'
            OR dedup_rank IS DISTINCT FROM 2
            OR new_status IS DISTINCT FROM 'SUPERSEDED_DUPLICATE'
            OR resolution_reason IS DISTINCT FROM 'MERGED_TO_SURVIVOR'
            OR row_snapshot::text IS DISTINCT FROM '{}')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Dedup map e2222222-2222-2222-2222-222222222222 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 5. Verifikasi Kepemilikan Orders (Seluruh 6 Kolom Ditulis)
    IF EXISTS (
        SELECT 1 FROM public.orders
        WHERE id = '44444444-4444-4444-4444-444444444441'
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001'
            OR affiliate_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222'
            OR manager_id IS NOT NULL
            OR gross_amount::numeric IS DISTINCT FROM 100000
            OR status IS DISTINCT FROM 'PENDING')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Order 44444444-4444-4444-4444-444444444441 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.orders
        WHERE id = '44444444-4444-4444-4444-444444444442'
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001'
            OR affiliate_id IS NOT NULL
            OR manager_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222'
            OR gross_amount::numeric IS DISTINCT FROM 150000
            OR status IS DISTINCT FROM 'PENDING')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Order 44444444-4444-4444-4444-444444444442 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 6. Verifikasi Kepemilikan Product Orders (Seluruh 5 Kolom Ditulis Termasuk Status)
    IF EXISTS (
        SELECT 1 FROM public.product_orders 
        WHERE id = 44444443 
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR order_id IS DISTINCT FROM 'PO_CHILD_001'
            OR affiliate_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222' 
            OR status IS DISTINCT FROM 'PENDING')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Product Order 44444443 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 7. Verifikasi Kepemilikan Delivery Orders (Seluruh 7 Kolom Ditulis Termasuk service_type & status)
    IF EXISTS (
        SELECT 1 FROM public.delivery_orders 
        WHERE id = '44444444-4444-4444-4444-444444444444' 
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR order_id IS DISTINCT FROM 'ORD_DO_001'
            OR provider IS DISTINCT FROM 'JNE' 
            OR service_type IS DISTINCT FROM 'REG'
            OR affiliate_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222' 
            OR status IS DISTINCT FROM 'PENDING')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Delivery Order 44444444-4444-4444-4444-444444444444 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 8. Verifikasi Kepemilikan Attributions (Seluruh 5 Kolom Ditulis Termasuk ip_hash)
    IF EXISTS (
        SELECT 1 FROM public.attributions 
        WHERE id = '44444444-4444-4444-4444-444444444445' 
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR session_id IS DISTINCT FROM 'SESS_001'
            OR ip_hash IS DISTINCT FROM 'HASH_001'
            OR affiliate_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Attribution 44444444-4444-4444-4444-444444444445 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 9. Verifikasi Kepemilikan Attribution Sessions (Seluruh 4 Kolom Ditulis Termasuk ip_hash)
    IF EXISTS (
        SELECT 1 FROM public.attribution_sessions 
        WHERE id = '44444444-4444-4444-4444-444444444446' 
          AND (tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR ip_hash IS DISTINCT FROM 'HASH_001'
            OR affiliate_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222')
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Attribution Session 44444444-4444-4444-4444-444444444446 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 10. Verifikasi Kepemilikan Shop Subscriptions (Seluruh 8 Kolom Ditulis Termasuk current_period_ends_at & expires_at)
    IF EXISTS (
        SELECT 1 FROM public.shop_subscriptions 
        WHERE id = '44444444-4444-4444-4444-444444444447' 
          AND (tenant_slug IS DISTINCT FROM '00000000-0000-0000-0000-000000000001'
            OR tenant_id::text IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR affiliate_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222' 
            OR status IS DISTINCT FROM 'ACTIVE'
            OR amount::numeric IS DISTINCT FROM 299000
            OR current_period_ends_at::timestamptz IS DISTINCT FROM '2026-12-03 10:00:00+00'::timestamptz
            OR expires_at::timestamptz IS DISTINCT FROM '2026-12-03 10:00:00+00'::timestamptz)
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Subscription 44444444-4444-4444-4444-444444444447 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;

    -- 11. Verifikasi Kepemilikan Shop Commission Ledger (Seluruh 7 Kolom Ditulis Termasuk am_amount & platform_net_amount)
    IF EXISTS (
        SELECT 1 FROM public.shop_commission_ledger 
        WHERE id = '44444444-4444-4444-4444-444444444448' 
          AND (tenant_slug IS DISTINCT FROM '00000000-0000-0000-0000-000000000001' 
            OR affiliate_id::text IS DISTINCT FROM '22222222-2222-2222-2222-222222222222' 
            OR gross_amount::numeric IS DISTINCT FROM 299000 
            OR affiliate_amount::numeric IS DISTINCT FROM 29900
            OR am_amount::numeric IS DISTINCT FROM 0
            OR platform_net_amount::numeric IS DISTINCT FROM 269100)
    ) THEN
        RAISE EXCEPTION 'CLEANUP OWNERSHIP VIOLATION: Ledger 44444444-4444-4444-4444-444444444448 payload mismatch!' USING ERRCODE = 'P0001';
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- TAHAP 2: PENGHAPUSAN EKSKLUSIF DENGAN KUALIFIKASI KEPEMILIKAN LENGKAP & EXECUTION AUDIT
-- Menggunakan predikat seluruh payload untuk menjamin atomic safety terhadap concurrency.
-- Mencatat diagnostik eksekusi eksak per tabel via GET DIAGNOSTICS ROW_COUNT untuk
-- membuktikan kardinalitas baris yang benar-benar terhapus vs yang sudah absen.
-- CATATAN: Tenant jangkar '00000000-0000-0000-0000-000000000001' TIDAK DIHAPUS.
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS pg_temp._cleanup_execution_audit;
CREATE TEMP TABLE pg_temp._cleanup_execution_audit (
    table_name text PRIMARY KEY,
    target_count int,
    found_count int,
    deleted_count int,
    status text
);

DO $$
DECLARE
    v_found int;
    v_deleted int;
    v_status text;
    v_del_sub int;
BEGIN
    -- 1. shop_commission_ledger (1 baris)
    SELECT count(*) INTO v_found FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448';
    DELETE FROM public.shop_commission_ledger 
    WHERE id = '44444444-4444-4444-4444-444444444448'
      AND tenant_slug = '00000000-0000-0000-0000-000000000001'
      AND affiliate_id = '22222222-2222-2222-2222-222222222222'
      AND gross_amount = 299000
      AND affiliate_amount = 29900
      AND am_amount = 0
      AND platform_net_amount = 269100;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.shop_commission_ledger', 1, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.shop_commission_ledger | Target: 1 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 2. shop_subscriptions (1 baris, seluruh 8 kolom termasuk timestamp)
    SELECT count(*) INTO v_found FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447';
    DELETE FROM public.shop_subscriptions 
    WHERE id = '44444444-4444-4444-4444-444444444447'
      AND tenant_slug = '00000000-0000-0000-0000-000000000001'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND affiliate_id = '22222222-2222-2222-2222-222222222222'
      AND status = 'ACTIVE'
      AND amount = 299000
      AND current_period_ends_at = '2026-12-03 10:00:00+00'::timestamptz
      AND expires_at = '2026-12-03 10:00:00+00'::timestamptz;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.shop_subscriptions', 1, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.shop_subscriptions | Target: 1 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 3. attribution_sessions (1 baris)
    SELECT count(*) INTO v_found FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446';
    DELETE FROM public.attribution_sessions 
    WHERE id = '44444444-4444-4444-4444-444444444446'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND ip_hash = 'HASH_001'
      AND affiliate_id = '22222222-2222-2222-2222-222222222222';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.attribution_sessions', 1, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.attribution_sessions | Target: 1 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 4. attributions (1 baris)
    SELECT count(*) INTO v_found FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445';
    DELETE FROM public.attributions 
    WHERE id = '44444444-4444-4444-4444-444444444445'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND session_id = 'SESS_001'
      AND ip_hash = 'HASH_001'
      AND affiliate_id = '22222222-2222-2222-2222-222222222222';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.attributions', 1, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.attributions | Target: 1 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 5. delivery_orders (1 baris)
    SELECT count(*) INTO v_found FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444';
    DELETE FROM public.delivery_orders 
    WHERE id = '44444444-4444-4444-4444-444444444444'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND order_id = 'ORD_DO_001'
      AND provider = 'JNE'
      AND service_type = 'REG'
      AND affiliate_id = '22222222-2222-2222-2222-222222222222'
      AND status = 'PENDING';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.delivery_orders', 1, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.delivery_orders | Target: 1 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 6. product_orders (1 baris)
    SELECT count(*) INTO v_found FROM public.product_orders WHERE id = 44444443;
    DELETE FROM public.product_orders 
    WHERE id = 44444443
      AND order_id = 'PO_CHILD_001'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND affiliate_id = '22222222-2222-2222-2222-222222222222'
      AND status = 'PENDING';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.product_orders', 1, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.product_orders | Target: 1 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 7. orders (2 baris: affiliate stream & manager stream)
    SELECT count(*) INTO v_found FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442');
    DELETE FROM public.orders 
    WHERE id = '44444444-4444-4444-4444-444444444441'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND affiliate_id = '22222222-2222-2222-2222-222222222222'
      AND manager_id IS NULL
      AND status = 'PENDING'
      AND gross_amount = 100000;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;

    DELETE FROM public.orders 
    WHERE id = '44444444-4444-4444-4444-444444444442'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND affiliate_id IS NULL
      AND manager_id = '22222222-2222-2222-2222-222222222222'
      AND status = 'PENDING'
      AND gross_amount = 150000;
    GET DIAGNOSTICS v_del_sub = ROW_COUNT;
    v_deleted := v_deleted + v_del_sub;

    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.orders', 2, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.orders | Target: 2 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 8. migration_031_identifier_dedup_map (2 baris: survivor rank 1 & loser rank 2)
    SELECT count(*) INTO v_found FROM public.migration_031_identifier_dedup_map WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222');
    DELETE FROM public.migration_031_identifier_dedup_map 
    WHERE map_id = 'e1111111-1111-1111-1111-111111111111'
      AND migration_batch_id = 'BATCH_SYNTH_001'
      AND table_name = 'affiliates'
      AND column_name = 'id'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND quarantined_row_id = '22222222-2222-2222-2222-222222222221'
      AND canonical_survivor_id = '22222222-2222-2222-2222-222222222221'
      AND dedup_rank = 1
      AND new_status = 'SURVIVOR';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;

    DELETE FROM public.migration_031_identifier_dedup_map 
    WHERE map_id = 'e2222222-2222-2222-2222-222222222222'
      AND migration_batch_id = 'BATCH_SYNTH_001'
      AND table_name = 'affiliates'
      AND column_name = 'id'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND quarantined_row_id = '22222222-2222-2222-2222-222222222222'
      AND canonical_survivor_id = '22222222-2222-2222-2222-222222222221'
      AND dedup_rank = 2
      AND new_status = 'SUPERSEDED_DUPLICATE';
    GET DIAGNOSTICS v_del_sub = ROW_COUNT;
    v_deleted := v_deleted + v_del_sub;

    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.migration_031_identifier_dedup_map', 2, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.migration_031_identifier_dedup_map | Target: 2 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 9. migration_031_quarantined_affiliate_commissions (1 baris)
    SELECT count(*) INTO v_found FROM public.migration_031_quarantined_affiliate_commissions WHERE id = '33333333-3333-3333-3333-333333333331';
    DELETE FROM public.migration_031_quarantined_affiliate_commissions 
    WHERE id = '33333333-3333-3333-3333-333333333331'
      AND migration_batch_id = 'BATCH_SYNTH_001'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND affiliate_id = '11111111-1111-1111-1111-111111111111'
      AND order_id = 'ORD_QUAR_001'
      AND amount = 75000
      AND status = 'QUARANTINED'
      AND quarantine_reason = 'CROSS_TENANT_DISCREPANCY_DETECTED';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.migration_031_quarantined_affiliate_commissions', 1, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.migration_031_quarantined_affiliate_commissions | Target: 1 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 10. affiliate_commissions (1 baris)
    SELECT count(*) INTO v_found FROM public.affiliate_commissions WHERE id = '11111111-1111-1111-1111-111111111112';
    DELETE FROM public.affiliate_commissions 
    WHERE id = '11111111-1111-1111-1111-111111111112'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND affiliate_id = '11111111-1111-1111-1111-111111111111'
      AND order_id = 'ORD_CLEAN_001'
      AND order_amount = 500000
      AND amount = 50000
      AND status = 'PAID';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.affiliate_commissions', 1, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.affiliate_commissions | Target: 1 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;

    -- 11. affiliates (3 baris: CLEAN, SURV, LOSER)
    SELECT count(*) INTO v_found FROM public.affiliates WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222');
    DELETE FROM public.affiliates 
    WHERE id = '11111111-1111-1111-1111-111111111111'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND name = 'SYNTH_AFF_CLEAN_001'
      AND phone_number = '081200000001'
      AND referral_code = 'CLEAN01'
      AND commission_rate = 0.10
      AND status = 'ACTIVE';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;

    DELETE FROM public.affiliates 
    WHERE id = '22222222-2222-2222-2222-222222222221'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND name = 'SYNTH_AFF_SURV_001'
      AND phone_number = '081200000002'
      AND referral_code = 'SURV01'
      AND commission_rate = 0.10
      AND status = 'ACTIVE';
    GET DIAGNOSTICS v_del_sub = ROW_COUNT;
    v_deleted := v_deleted + v_del_sub;

    DELETE FROM public.affiliates 
    WHERE id = '22222222-2222-2222-2222-222222222222'
      AND tenant_id = '00000000-0000-0000-0000-000000000001'
      AND name = 'SYNTH_AFF_LOSER_001'
      AND phone_number = '081200000003'
      AND referral_code = 'LOSER01'
      AND commission_rate = 0.10
      AND status = 'ACTIVE';
    GET DIAGNOSTICS v_del_sub = ROW_COUNT;
    v_deleted := v_deleted + v_del_sub;

    IF v_found = 0 THEN
        v_status := 'ALREADY_ABSENT';
    ELSIF v_deleted = v_found THEN
        v_status := 'CLEANLY_DELETED';
    ELSE
        v_status := 'PAYLOAD_MISMATCH_REJECTED';
    END IF;
    INSERT INTO pg_temp._cleanup_execution_audit VALUES ('public.affiliates', 3, v_found, v_deleted, v_status);
    RAISE NOTICE 'CLEANUP_AUDIT: public.affiliates | Target: 3 | Found: % | Deleted: % | Status: %', v_found, v_deleted, v_status;
END $$;

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
        SELECT id, slug FROM pg_temp._historical_tenant_pre_snapshot
        EXCEPT
        SELECT id::text, slug::text FROM public.tenants
    ) td;

    IF v_tenant_diff <> 0 THEN
        RAISE EXCEPTION 'CRITICAL INTEGRITY FAILURE: Tenant anchor modified or deleted during cleanup!' USING ERRCODE = 'P0001';
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- TAHAP 4: POST-CLEANUP ZERO RESIDUAL VERIFICATION (BUKTI ELIMINASI 100%)
-- Membuktikan secara matematis bahwa ke-13 entitas sintetis + 2 dedup map benar-benar
-- telah lenyap 100% tanpa sisa di seluruh 11 tabel database.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_residual_cnt INT;
BEGIN
    SELECT count(*) INTO v_residual_cnt FROM (
        SELECT id::text FROM public.affiliates WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', '22222222-2222-2222-2222-222222222222')
        UNION ALL
        SELECT id::text FROM public.affiliate_commissions WHERE id = '11111111-1111-1111-1111-111111111112'
        UNION ALL
        SELECT id::text FROM public.migration_031_quarantined_affiliate_commissions WHERE id = '33333333-3333-3333-3333-333333333331'
        UNION ALL
        SELECT map_id::text FROM public.migration_031_identifier_dedup_map WHERE map_id IN ('e1111111-1111-1111-1111-111111111111', 'e2222222-2222-2222-2222-222222222222')
        UNION ALL
        SELECT id::text FROM public.orders WHERE id IN ('44444444-4444-4444-4444-444444444441', '44444444-4444-4444-4444-444444444442')
        UNION ALL
        SELECT id::text FROM public.product_orders WHERE id = 44444443
        UNION ALL
        SELECT id::text FROM public.delivery_orders WHERE id = '44444444-4444-4444-4444-444444444444'
        UNION ALL
        SELECT id::text FROM public.attributions WHERE id = '44444444-4444-4444-4444-444444444445'
        UNION ALL
        SELECT id::text FROM public.attribution_sessions WHERE id = '44444444-4444-4444-4444-444444444446'
        UNION ALL
        SELECT id::text FROM public.shop_subscriptions WHERE id = '44444444-4444-4444-4444-444444444447'
        UNION ALL
        SELECT id::text FROM public.shop_commission_ledger WHERE id = '44444444-4444-4444-4444-444444444448'
    ) residual_check;

    IF v_residual_cnt <> 0 THEN
        RAISE EXCEPTION 'POST-CLEANUP RESIDUAL FAILURE: Expected 0 residual synthetic fixtures, found %!', v_residual_cnt USING ERRCODE = 'P0001';
    END IF;
END $$;
