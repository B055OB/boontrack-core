-- =============================================================================
-- BOONTRACK STAGING POPULATED WORKLOAD BENCHMARK CLEANUP (OPTION B - 800 ROWS)
-- =============================================================================
-- Classification: Lead DBRE & Principal Systems Architect
-- Target Database: Staging Supabase (xkhqirhurnjqglmajghn:5432)
-- Status: PREPARATION ARTIFACT (STAGING WRITE PENDING AUTHORIZATION)
-- Target Benchmark Tenant: '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
-- Mode: PURE DML (Zero DDL manipulation, non-existent order_items pruned)
-- Target Predicate: Strict 'bench\_%' pattern with ESCAPE '\'
-- Execution Sequence: Strict reverse foreign key dependency order (4 tables):
--   1. public.attributions
--   2. public.affiliate_commissions
--   3. public.product_orders
--   4. public.orders
-- Zero-Touch Guarantee: Production Supabase & Cloudflare R2 strictly untouched.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- [STAGE 0] SESSION GUARDRAILS & DEFINITIVE CONCURRENCY LOCKING
-- Mode: SHARE ROW EXCLUSIVE (Blocks concurrent INSERT/UPDATE/DELETE; allows concurrent SELECT)
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
-- Menggunakan predikat eksplisit dengan ESCAPE '\'
-- -----------------------------------------------------------------------------

-- 1. Attributions (Child of orders and affiliates)
DELETE FROM public.attributions
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_%' ESCAPE '\';

-- 2. Affiliate Commissions (Child of affiliates, references order_id)
DELETE FROM public.affiliate_commissions
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_%' ESCAPE '\';

-- 3. Product Orders (Child of orders)
DELETE FROM public.product_orders
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_%' ESCAPE '\';

-- 4. Orders (Parent table)
DELETE FROM public.orders
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND id LIKE 'bench\_%' ESCAPE '\';

-- -----------------------------------------------------------------------------
-- [STAGE 2] ZERO RESIDUAL VERIFICATION ASSERTIONS (FAIL-CLOSED)
-- Query COUNT(*) pada keempat tabel yang harus mengembalikan 0 baris untuk bench\_%
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_att_count INT;
    v_com_count INT;
    v_po_count  INT;
    v_ord_count INT;
    v_total_residual INT;
BEGIN
    SELECT COUNT(*) INTO v_att_count FROM public.attributions 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_com_count FROM public.affiliate_commissions 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_po_count FROM public.product_orders 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_ord_count FROM public.orders 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND id LIKE 'bench\_%' ESCAPE '\';

    v_total_residual := v_att_count + v_com_count + v_po_count + v_ord_count;

    IF v_total_residual > 0 THEN
        RAISE EXCEPTION 'ZERO RESIDUAL VERIFICATION FAIL: Found % residual rows! (attributions=%, commissions=%, product_orders=%, orders=%)',
            v_total_residual, v_att_count, v_com_count, v_po_count, v_ord_count;
    END IF;

    RAISE NOTICE 'ZERO RESIDUAL PASS: Exactly 0 residual benchmark rows across all 4 tables.';
END $$;

COMMIT;
