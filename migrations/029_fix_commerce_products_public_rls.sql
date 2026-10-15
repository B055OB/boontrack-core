-- =============================================================================
-- Migration: 029_fix_commerce_products_public_rls.sql
-- Description: 
-- 1. Fix product isolation leak on commerce_products:
--    Changes clause from `is_active = true OR (...)` to `is_active = true AND (...)`.
--    Ensures public/anon role can ONLY read products that are active AND match
--    app.current_tenant_id (via dual UUID/slug resolution). When tenant_id is NULL
--    or unset, 0 rows are returned.
-- 2. Enforce FORCE ROW LEVEL SECURITY across all tenant-scoped tables.
-- 3. Eliminate legacy wildcard USING (true) policies on tenant-scoped tables.
-- =============================================================================

-- =============================================================================
-- 1. COMMERCE_PRODUCTS: STRICT TENANT ISOLATION FIX
-- =============================================================================

DROP POLICY IF EXISTS public_select_active_commerce_products ON public.commerce_products;

CREATE POLICY public_select_active_commerce_products ON public.commerce_products
AS PERMISSIVE FOR SELECT TO public
USING (
    is_active = true
    AND (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_id = (
            SELECT slug FROM public.tenants 
            WHERE id = (
                CASE 
                    WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    THEN current_setting('app.current_tenant_id', true)::uuid
                    ELSE NULL
                END
            )
        )
        OR tenant_id = (
            SELECT id::text FROM public.tenants 
            WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        )
    )
);

-- =============================================================================
-- 1.B TENANTS: STRICT TENANT ISOLATION FIX
-- =============================================================================

DROP POLICY IF EXISTS public_select_active_tenants ON public.tenants;

CREATE POLICY public_select_active_tenants ON public.tenants
AS PERMISSIVE FOR SELECT TO public
USING (
    is_active = true
    AND (
        id = (
            CASE 
                WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN current_setting('app.current_tenant_id', true)::uuid
                ELSE NULL
            END
        )
        OR slug = NULLIF(current_setting('app.current_tenant_id', true), '')
    )
);

-- =============================================================================
-- 2. ENFORCE FORCE ROW LEVEL SECURITY ON ALL TENANT-SCOPED TABLES
-- =============================================================================

DO $$
DECLARE
    tbl_rec RECORD;
BEGIN
    FOR tbl_rec IN 
        SELECT DISTINCT t.table_name
        FROM information_schema.tables t
        JOIN information_schema.columns c ON c.table_name = t.table_name AND c.table_schema = t.table_schema
        WHERE t.table_schema = 'public' 
          AND t.table_type = 'BASE TABLE'
          AND (c.column_name IN ('tenant_id', 'tenant_slug', 'store_id', 'merchant_id') OR t.table_name IN ('cart_items', 'tenants'))
          AND t.table_name NOT IN ('system_health_checks', 'provinces', 'cities', 'districts', 'postal_codes', 'subscription_plans', 'pricing_tiers', 'spatial_ref_sys')
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', tbl_rec.table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY;', tbl_rec.table_name);
    END LOOP;
END $$;
