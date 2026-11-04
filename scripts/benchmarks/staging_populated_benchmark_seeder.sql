-- =============================================================================
-- BOONTRACK STAGING POPULATED WORKLOAD BENCHMARK SEEDER (OPTION B - REVISED)
-- =============================================================================
-- Classification: Lead DBRE & Principal Systems Architect
-- Target Database: Staging Supabase (xkhqirhurnjqglmajghn:5432)
-- Status: PREPARATION ARTIFACT (STAGING WRITE PENDING AUTHORIZATION)
-- Target Benchmark Tenant: '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
-- Mode: PURE DML (Zero DDL manipulation, separation of concerns guaranteed)
-- Total Fixture Quota: Exactly 1,200 synthetic rows across 5 tables
--   - public.orders                : 200 rows (ID: bench_ord_001 .. bench_ord_200)
--   - public.product_orders        : 200 rows (180 COMPLETED, 20 PENDING)
--   - public.order_items           : 400 rows (2 items per product_order, FK product_order_id)
--   - public.affiliate_commissions : 200 rows (Rp 10.000 / Rp 25.000 deterministic)
--   - public.attributions          : 200 rows (FK-linked to orders and affiliates)
-- Security & Isolation: Strict 'bench\_%' prefix with ESCAPE '\'; zero collision guard.
-- Zero-Touch Guarantee: Production Supabase & Cloudflare R2 strictly untouched.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- [STAGE 0] SESSION GUARDRAILS & DEFINITIVE CONCURRENCY LOCKING
-- Mode: SHARE ROW EXCLUSIVE (Blocks concurrent INSERT/UPDATE/DELETE; allows concurrent SELECT)
-- Lock Order: orders -> product_orders -> order_items -> affiliate_commissions -> attributions
-- -----------------------------------------------------------------------------
SET LOCAL statement_timeout = '2000ms';
SET LOCAL lock_timeout = '500ms';

LOCK TABLE
    public.orders,
    public.product_orders,
    public.order_items,
    public.affiliate_commissions,
    public.attributions
IN SHARE ROW EXCLUSIVE MODE;

-- -----------------------------------------------------------------------------
-- [STAGE 1] PRECONDITION AUDIT & DETERMINISTIC COLLISION GUARD
-- Menggunakan pola LIKE 'bench\_%' ESCAPE '\' untuk mencegah anomali wildcard
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_aff_count INT;
    v_colliding_count INT;
BEGIN
    -- 1. Verifikasi kehadiran tenant target '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' di katalog affiliates
    SELECT COUNT(*) INTO v_aff_count
    FROM public.affiliates
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba';

    IF v_aff_count < 3 THEN
        RAISE EXCEPTION 'PRE-CHECK FAIL: Benchmark tenant 6b37fdf0-b1a2-49ad-bec5-7153b8a76fba has % affiliates (expected at least 3)', v_aff_count;
    END IF;

    -- Pastikan registrasi tenant id pada public.tenants terpenuhi (idempotent ON CONFLICT)
    INSERT INTO public.tenants (id, slug)
    VALUES ('6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'::uuid, 'staging-bench-tenant-6b37')
    ON CONFLICT (id) DO NOTHING;

    -- 2. Collision Guard Eksplisit: Pastikan tidak ada data eksisting dengan prefix 'bench\_'
    SELECT (
        (SELECT COUNT(*) FROM public.orders WHERE id LIKE 'bench\_%' ESCAPE '\') +
        (SELECT COUNT(*) FROM public.product_orders WHERE order_id LIKE 'bench\_%' ESCAPE '\') +
        (SELECT COUNT(*) FROM public.order_items WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND product_order_id BETWEEN 60001 AND 60200) +
        (SELECT COUNT(*) FROM public.affiliate_commissions WHERE order_id LIKE 'bench\_%' ESCAPE '\') +
        (SELECT COUNT(*) FROM public.attributions WHERE order_id LIKE 'bench\_%' ESCAPE '\')
    ) INTO v_colliding_count;

    IF v_colliding_count > 0 THEN
        RAISE EXCEPTION 'COLLISION GUARD FAIL: Found % colliding records with prefix bench\_!', v_colliding_count;
    END IF;

    RAISE NOTICE 'PRE-CHECK & COLLISION GUARD PASS: Tenant verified, 0 colliding rows.';
END $$;

-- -----------------------------------------------------------------------------
-- [STAGE 2] INJEKSI 200 ORDERS (PARENT ENTITY)
-- Mengisi order_number dan metadata JSONB
-- -----------------------------------------------------------------------------
WITH gen_series AS (
    SELECT generate_series(1, 200) AS i
),
affiliate_pool AS (
    SELECT 
        id, 
        ROW_NUMBER() OVER (ORDER BY id) - 1 AS pool_idx
    FROM public.affiliates
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
    LIMIT 3
)
INSERT INTO public.orders (
    id,
    tenant_id,
    affiliate_id,
    manager_id,
    status,
    order_status,
    payment_status,
    order_number,
    gross_amount,
    metadata,
    created_at,
    updated_at
)
SELECT
    'bench_ord_' || LPAD(s.i::text, 3, '0') AS id,
    '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AS tenant_id,
    a.id AS affiliate_id,
    NULL::uuid AS manager_id,
    CASE WHEN s.i <= 180 THEN 'COMPLETED' ELSE 'PENDING' END AS status,
    CASE WHEN s.i <= 180 THEN 'COMPLETED' ELSE 'PENDING' END AS order_status,
    CASE WHEN s.i <= 180 THEN 'PAID' ELSE 'PENDING' END AS payment_status,
    'EXT-BENCH-' || LPAD(s.i::text, 3, '0') AS order_number,
    CASE WHEN s.i % 2 = 0 THEN 100000.00 ELSE 250000.00 END AS gross_amount,
    jsonb_build_object(
        'external_order_id', 'EXT-BENCH-' || LPAD(s.i::text, 3, '0'),
        'benchmark_series', 'gate_i_option_b',
        'is_synthetic', true
    ) AS metadata,
    now() - (interval '1 hour' * (201 - s.i)) AS created_at,
    now() - (interval '1 hour' * (201 - s.i)) AS updated_at
FROM gen_series s
JOIN affiliate_pool a ON a.pool_idx = ((s.i - 1) % 3);

-- -----------------------------------------------------------------------------
-- [STAGE 3] INJEKSI 200 PRODUCT_ORDERS (CHILD ENTITY)
-- Rentang ID deterministik: 60001 .. 60200
-- Distribusi status: 180 COMPLETED, 20 PENDING
-- -----------------------------------------------------------------------------
WITH gen_series AS (
    SELECT generate_series(1, 200) AS i
),
affiliate_pool AS (
    SELECT 
        id, 
        ROW_NUMBER() OVER (ORDER BY id) - 1 AS pool_idx
    FROM public.affiliates
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
    LIMIT 3
)
INSERT INTO public.product_orders (
    id,
    order_id,
    tenant_id,
    affiliate_id,
    status,
    product_name,
    base_price,
    total_amount,
    fulfillment_status,
    created_at
)
SELECT
    60000 + s.i AS id,
    'bench_ord_' || LPAD(s.i::text, 3, '0') AS order_id,
    '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AS tenant_id,
    a.id AS affiliate_id,
    CASE WHEN s.i <= 180 THEN 'COMPLETED' ELSE 'PENDING' END AS status,
    'Benchmark SKU Item ' || LPAD(s.i::text, 3, '0') AS product_name,
    CASE WHEN s.i % 2 = 0 THEN 100000 ELSE 250000 END AS base_price,
    CASE WHEN s.i % 2 = 0 THEN 100000 ELSE 250000 END AS total_amount,
    CASE WHEN s.i <= 180 THEN 'FULFILLED' ELSE 'UNFULFILLED' END AS fulfillment_status,
    (now() - (interval '1 hour' * (201 - s.i)))::timestamp AS created_at
FROM gen_series s
JOIN affiliate_pool a ON a.pool_idx = ((s.i - 1) % 3);

-- -----------------------------------------------------------------------------
-- [STAGE 4] INJEKSI 400 ORDER_ITEMS (COMPOSITE RELATION TO PRODUCT_ORDERS)
-- Relasi FK: product_order_id merujuk ke public.product_orders(id) [60001..60200]
-- -----------------------------------------------------------------------------
WITH order_base AS (
    SELECT generate_series(1, 200) AS i
),
item_multiplier AS (
    SELECT 1 AS item_num, 'A' AS item_suffix, 0.5 AS price_ratio
    UNION ALL
    SELECT 2 AS item_num, 'B' AS item_suffix, 0.5 AS price_ratio
)
INSERT INTO public.order_items (
    id,
    tenant_id,
    order_id,
    product_order_id,
    item_sku,
    item_name,
    quantity,
    unit_price,
    created_at
)
SELECT
    gen_random_uuid() AS id,
    '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AS tenant_id,
    'bench_ord_' || LPAD(o.i::text, 3, '0') AS order_id,
    60000 + o.i AS product_order_id,
    'SKU-BENCH-' || LPAD(o.i::text, 3, '0') || '-' || m.item_suffix AS item_sku,
    'Benchmark Sub-Item ' || m.item_suffix || ' for Order ' || LPAD(o.i::text, 3, '0') AS item_name,
    1 AS quantity,
    (CASE WHEN o.i % 2 = 0 THEN 100000.00 ELSE 250000.00 END * m.price_ratio)::numeric(12, 2) AS unit_price,
    now() - (interval '1 hour' * (201 - o.i)) AS created_at
FROM order_base o
CROSS JOIN item_multiplier m;

-- -----------------------------------------------------------------------------
-- [STAGE 5] INJEKSI 200 AFFILIATE_COMMISSIONS (FINANCIAL LEDGER)
-- Terhubung ke 3 afiliasi historis staging, nominal deterministik Rp 10.000 / Rp 25.000
-- -----------------------------------------------------------------------------
WITH gen_series AS (
    SELECT generate_series(1, 200) AS i
),
affiliate_pool AS (
    SELECT 
        id, 
        ROW_NUMBER() OVER (ORDER BY id) - 1 AS pool_idx
    FROM public.affiliates
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
    LIMIT 3
)
INSERT INTO public.affiliate_commissions (
    id,
    tenant_id,
    affiliate_id,
    order_id,
    order_amount,
    amount,
    status,
    product_type,
    created_at,
    paid_at
)
SELECT
    gen_random_uuid() AS id,
    '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AS tenant_id,
    a.id AS affiliate_id,
    'bench_ord_' || LPAD(s.i::text, 3, '0') AS order_id,
    CASE WHEN s.i % 2 = 0 THEN 100000.00 ELSE 250000.00 END AS order_amount,
    CASE WHEN s.i % 2 = 0 THEN 10000.00 ELSE 25000.00 END AS amount,
    CASE WHEN s.i <= 180 THEN 'PAID'::commission_status_enum ELSE 'PENDING'::commission_status_enum END AS status,
    'SHOP' AS product_type,
    now() - (interval '1 hour' * (201 - s.i)) AS created_at,
    CASE WHEN s.i <= 180 THEN now() - (interval '1 hour' * (201 - s.i)) ELSE NULL END AS paid_at
FROM gen_series s
JOIN affiliate_pool a ON a.pool_idx = ((s.i - 1) % 3);

-- -----------------------------------------------------------------------------
-- [STAGE 6] INJEKSI 200 ATTRIBUTIONS (TRAFFIC & CAMPAIGN TRACEABILITY)
-- -----------------------------------------------------------------------------
WITH gen_series AS (
    SELECT generate_series(1, 200) AS i
),
affiliate_pool AS (
    SELECT 
        id, 
        ROW_NUMBER() OVER (ORDER BY id) - 1 AS pool_idx
    FROM public.affiliates
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
    LIMIT 3
)
INSERT INTO public.attributions (
    id,
    tenant_id,
    session_id,
    ip_hash,
    affiliate_id,
    order_id,
    utm_source,
    utm_medium,
    utm_campaign,
    created_at
)
SELECT
    gen_random_uuid() AS id,
    '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AS tenant_id,
    'bench_sess_' || LPAD(s.i::text, 3, '0') AS session_id,
    'bench_ip_hash_' || LPAD(s.i::text, 3, '0') AS ip_hash,
    a.id AS affiliate_id,
    'bench_ord_' || LPAD(s.i::text, 3, '0') AS order_id,
    'benchmark_suite' AS utm_source,
    'performance_test' AS utm_medium,
    'gate_i_option_b' AS utm_campaign,
    now() - (interval '1 hour' * (201 - s.i)) AS created_at
FROM gen_series s
JOIN affiliate_pool a ON a.pool_idx = ((s.i - 1) % 3);

-- -----------------------------------------------------------------------------
-- [STAGE 7] POSTCONDITION VALIDATION & EXACT QUOTA VERIFICATION
-- Memverifikasi bahwa seluruh baris sintetis tepat 1.200 baris
-- Pola matching menggunakan LIKE 'bench\_%' ESCAPE '\'
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_ord_cnt INT;
    v_po_cnt  INT;
    v_po_comp INT;
    v_po_pend INT;
    v_itm_cnt INT;
    v_com_cnt INT;
    v_att_cnt INT;
    v_total   INT;
BEGIN
    SELECT COUNT(*) INTO v_ord_cnt FROM public.orders 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*), 
           COUNT(*) FILTER (WHERE status = 'COMPLETED'),
           COUNT(*) FILTER (WHERE status = 'PENDING')
    INTO v_po_cnt, v_po_comp, v_po_pend 
    FROM public.product_orders 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_itm_cnt FROM public.order_items 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
      AND product_order_id BETWEEN 60001 AND 60200;

    SELECT COUNT(*) INTO v_com_cnt FROM public.affiliate_commissions 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_att_cnt FROM public.attributions 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    v_total := v_ord_cnt + v_po_cnt + v_itm_cnt + v_com_cnt + v_att_cnt;

    IF v_ord_cnt <> 200 THEN
        RAISE EXCEPTION 'POSTCONDITION FAIL: orders count = % (expected 200)', v_ord_cnt;
    END IF;

    IF v_po_cnt <> 200 OR v_po_comp <> 180 OR v_po_pend <> 20 THEN
        RAISE EXCEPTION 'POSTCONDITION FAIL: product_orders count = %, completed = %, pending = % (expected 200, 180, 20)', 
            v_po_cnt, v_po_comp, v_po_pend;
    END IF;

    IF v_itm_cnt <> 400 THEN
        RAISE EXCEPTION 'POSTCONDITION FAIL: order_items count = % (expected 400)', v_itm_cnt;
    END IF;

    IF v_com_cnt <> 200 THEN
        RAISE EXCEPTION 'POSTCONDITION FAIL: affiliate_commissions count = % (expected 200)', v_com_cnt;
    END IF;

    IF v_att_cnt <> 200 THEN
        RAISE EXCEPTION 'POSTCONDITION FAIL: attributions count = % (expected 200)', v_att_cnt;
    END IF;

    IF v_total <> 1200 THEN
        RAISE EXCEPTION 'POSTCONDITION FAIL: Total synthetic quota = % (expected 1200)', v_total;
    END IF;

    RAISE NOTICE 'POSTCONDITION PASS: Exactly 1,200 synthetic rows verified across all 5 tables.';
END $$;

COMMIT;
