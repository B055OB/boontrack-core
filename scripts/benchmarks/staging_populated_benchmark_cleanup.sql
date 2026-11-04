-- =============================================================================
-- BOONTRACK STAGING POPULATED WORKLOAD BENCHMARK CLEANUP (OPTION B - REVISED)
-- =============================================================================
-- Classification: Lead DBRE & Principal Systems Architect
-- Target Database: Staging Supabase (xkhqirhurnjqglmajghn:5432)
-- Status: PREPARATION ARTIFACT (STAGING WRITE PENDING AUTHORIZATION)
-- Target Benchmark Tenant: '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
-- Mode: PURE DML (Zero DDL manipulation)
-- Target Predicate: Strict 'bench\_%' pattern with ESCAPE '\' and FK id range
-- Execution Sequence: Strict reverse foreign key dependency order:
--   1. public.attributions
--   2. public.affiliate_commissions
--   3. public.order_items
--   4. public.product_orders
--   5. public.orders
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
-- [STAGE 1] DELETE BERURUTAN TERBALIK BERDASARKAN INTEGRITAS FK
-- Menggunakan predikat eksplisit dengan ESCAPE '\' dan rentang FK deterministik
-- -----------------------------------------------------------------------------

-- 1. Attributions (Child of orders and affiliates)
DELETE FROM public.attributions
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_%' ESCAPE '\';

-- 2. Affiliate Commissions (Child of affiliates, references order_id)
DELETE FROM public.affiliate_commissions
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_%' ESCAPE '\';

-- 3. Order Items (Relasi relasional deterministik berbasis FK fisik ke product_orders)
DELETE FROM public.order_items oi
WHERE oi.tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND oi.product_order_id IN (
      SELECT po.id FROM public.product_orders po
      WHERE po.tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
        AND po.id BETWEEN 60001 AND 60200
  );

-- 4. Product Orders (Child of orders)
DELETE FROM public.product_orders
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND order_id LIKE 'bench\_%' ESCAPE '\';

-- 5. Orders (Parent table)
DELETE FROM public.orders
WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
  AND id LIKE 'bench\_%' ESCAPE '\';

-- -----------------------------------------------------------------------------
-- [STAGE 2] ZERO RESIDUAL VERIFICATION ASSERTIONS (FAIL-CLOSED)
-- Query COUNT(*) pada kelima tabel yang harus mengembalikan 0 baris untuk bench\_%
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_att_count INT;
    v_com_count INT;
    v_itm_count INT;
    v_po_count  INT;
    v_ord_count INT;
    v_total_residual INT;
BEGIN
    SELECT COUNT(*) INTO v_att_count FROM public.attributions 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_com_count FROM public.affiliate_commissions 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_itm_count FROM public.order_items 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
      AND product_order_id IN (
          SELECT po.id FROM public.product_orders po
          WHERE po.tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba'
            AND po.id BETWEEN 60001 AND 60200
      );

    SELECT COUNT(*) INTO v_po_count FROM public.product_orders 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND order_id LIKE 'bench\_%' ESCAPE '\';

    SELECT COUNT(*) INTO v_ord_count FROM public.orders 
    WHERE tenant_id = '6b37fdf0-b1a2-49ad-bec5-7153b8a76fba' AND id LIKE 'bench\_%' ESCAPE '\';

    v_total_residual := v_att_count + v_com_count + v_itm_count + v_po_count + v_ord_count;

    IF v_total_residual > 0 THEN
        RAISE EXCEPTION 'ZERO RESIDUAL VERIFICATION FAIL: Found % residual rows! (attributions=%, commissions=%, order_items=%, product_orders=%, orders=%)',
            v_total_residual, v_att_count, v_com_count, v_itm_count, v_po_count, v_ord_count;
    END IF;

    RAISE NOTICE 'ZERO RESIDUAL PASS: Exactly 0 residual benchmark rows across all 5 tables.';
END $$;

COMMIT;
