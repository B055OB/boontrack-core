-- =============================================================================
-- BOONTRACK STAGING POPULATED WORKLOAD BENCHMARK RECOVERY (OPTION B - RUN B1)
-- =============================================================================
-- Classification: Lead DBRE & Principal Systems Architect
-- Target Database: Staging Supabase (xkhqirhurnjqglmajghn:5432)
-- Status: OPERATOR INDEPENDENT CRASH RECOVERY SCRIPT
-- Target Benchmark Tenant: '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
-- Mode: PURE DML (Zero DDL manipulation, ZERO DML on public.tenants)
-- Fixture Run ID: 'gate_i_b1' (Strict deterministic namespace 'bench_b1_')
-- Lock Strategy: SHARE ROW EXCLUSIVE MODE (500ms lock timeout with retry capability)
-- Execution Sequence: Reverse FK order (attributions -> commissions -> product_orders -> orders)
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- [STAGE 0] SESSION GUARDRAILS & DEFINITIVE CONCURRENCY LOCKING
-- Mode: SHARE ROW EXCLUSIVE
-- Lock Order: orders -> product_orders -> affiliate_commissions -> attributions
-- -----------------------------------------------------------------------------
SET LOCAL statement_timeout = '2000ms';
SET LOCAL lock_timeout = '500ms';

LOCK TABLE
    public.orders,
    public.product_orders,
    public.affiliate_commissions,
    public.attributions
IN SHARE ROW EXCLUSIVE MODE;

-- -----------------------------------------------------------------------------
-- [STAGE 1] DELETE BERURUTAN TERBALIK BERDASARKAN INTEGRITAS FK (4 TABEL)
-- Menggunakan predikat eksplisit namespace run 'bench_b1_' dengan ESCAPE '\'
-- -----------------------------------------------------------------------------

-- 1. Attributions (Child of orders and affiliates)
DELETE FROM public.attributions
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_b1\_%' ESCAPE '\';

-- 2. Affiliate Commissions (Child of affiliates, references order_id)
DELETE FROM public.affiliate_commissions
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_b1\_%' ESCAPE '\';

-- 3. Product Orders (Child of orders)
DELETE FROM public.product_orders
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_b1\_%' ESCAPE '\';

-- 4. Orders (Parent table)
DELETE FROM public.orders
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND id LIKE 'bench\_b1\_%' ESCAPE '\';

-- -----------------------------------------------------------------------------
-- [STAGE 2] ZERO RESIDUAL VERIFICATION ASSERTIONS (FAIL-CLOSED)
-- Query COUNT(*) pada keempat tabel yang harus mengembalikan 0 baris untuk bench\_b1\_%
-- Serta verifikasi zero-residual pada rentang PK negatif product_orders (-60200 s/d -60001)
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_att_count INT;
    v_com_count INT;
    v_po_count  INT;
    v_ord_count INT;
    v_po_neg_count INT;
    v_total_residual INT;
BEGIN
    SELECT COUNT(*) INTO v_att_count FROM public.attributions 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_b1\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_com_count FROM public.affiliate_commissions 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_b1\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_po_count FROM public.product_orders 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_b1\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_ord_count FROM public.orders 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND id LIKE 'bench\_b1\_%' ESCAPE '\';

    -- Validasi eksplisit rentang PK negatif (-60200 s/d -60001)
    SELECT COUNT(*) INTO v_po_neg_count FROM public.product_orders
    WHERE id BETWEEN -60200 AND -60001;

    v_total_residual := v_att_count + v_com_count + v_po_count + v_ord_count + v_po_neg_count;

    IF v_total_residual > 0 THEN
        RAISE EXCEPTION 'RECOVERY ZERO RESIDUAL FAIL: Found % residual rows! (attributions=%, commissions=%, product_orders=%, orders=%, product_orders_neg=%)',
            v_total_residual, v_att_count, v_com_count, v_po_count, v_ord_count, v_po_neg_count;
    END IF;

    RAISE NOTICE 'RECOVERY ZERO RESIDUAL PASS: Exactly 0 residual benchmark rows across all 4 tables and PK negative range clear.';
END $$;

COMMIT;
