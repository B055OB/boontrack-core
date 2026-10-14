-- ==============================================================================================
-- Migration 028: Harden RLS on affiliates, affiliate_commissions, and cart_items
-- ==============================================================================================
-- CTO War Room Directive P1-01:
-- 1. Eliminasi total policy permisif bertipe USING (true) atau WITH CHECK (true) pada tabel:
--    - affiliates
--    - affiliate_commissions
--    - cart_items
-- 2. Terapkan policy isolasi tenant yang ketat menggunakan helper dual-resolution
--    (try_cast_uuid / tenant slug lookup) yang kompatibel dengan context app.current_tenant_id.
-- 3. Jamin ZERO DATA LEAKAGE dan ZERO TYPE ERROR lintas role database (public, authenticated, service_role).
-- ==============================================================================================

-- ==============================================================================================
-- 1. TABEL: affiliates (id: UUID, tenant_id: VARCHAR)
-- ==============================================================================================
ALTER TABLE public.affiliates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.affiliates FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS allow_all_ops_affiliates ON public.affiliates;
DROP POLICY IF EXISTS "Public read access on affiliates" ON public.affiliates;
DROP POLICY IF EXISTS "Service role full access on affiliates" ON public.affiliates;
DROP POLICY IF EXISTS public_select_active_affiliates ON public.affiliates;
DROP POLICY IF EXISTS auth_tenant_affiliates ON public.affiliates;
DROP POLICY IF EXISTS service_role_all_affiliates ON public.affiliates;

-- Storefront / Public Read: Hanya dapat membaca affiliate yang aktif dan terikat ke tenant aktif
CREATE POLICY public_select_active_affiliates ON public.affiliates
AS PERMISSIVE FOR SELECT TO public
USING (
    status = 'ACTIVE'
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

-- Merchant Authenticated DML: Mengelola affiliate dalam tenant sendiri
CREATE POLICY auth_tenant_affiliates ON public.affiliates
AS PERMISSIVE FOR ALL TO authenticated
USING (
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
WITH CHECK (
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
);

-- Service Role Full Access
CREATE POLICY service_role_all_affiliates ON public.affiliates
AS PERMISSIVE FOR ALL TO service_role
USING (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = current_setting('app.current_tenant_id', true)
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
)
WITH CHECK (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = current_setting('app.current_tenant_id', true)
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


-- ==============================================================================
-- 2. TABEL: affiliate_commissions (id: UUID, tenant_id: VARCHAR, affiliate_id: UUID)
-- ==============================================================================
ALTER TABLE public.affiliate_commissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.affiliate_commissions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS allow_all_ops_affiliate_commissions ON public.affiliate_commissions;
DROP POLICY IF EXISTS "Service role full access on affiliate_commissions" ON public.affiliate_commissions;
DROP POLICY IF EXISTS auth_tenant_affiliate_commissions ON public.affiliate_commissions;
DROP POLICY IF EXISTS service_role_all_affiliate_commissions ON public.affiliate_commissions;

CREATE POLICY auth_tenant_affiliate_commissions ON public.affiliate_commissions
AS PERMISSIVE FOR ALL TO authenticated
USING (
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
WITH CHECK (
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
);

CREATE POLICY service_role_all_affiliate_commissions ON public.affiliate_commissions
AS PERMISSIVE FOR ALL TO service_role
USING (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = current_setting('app.current_tenant_id', true)
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
)
WITH CHECK (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = current_setting('app.current_tenant_id', true)
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


-- ==============================================================================
-- 3. TABEL: cart_items (id: UUID, cart_id: UUID)
-- ==============================================================================
ALTER TABLE public.cart_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cart_items FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public cart_items select" ON public.cart_items;
DROP POLICY IF EXISTS "Public cart_items insert" ON public.cart_items;
DROP POLICY IF EXISTS "Public cart_items update" ON public.cart_items;
DROP POLICY IF EXISTS "Public cart_items delete" ON public.cart_items;
DROP POLICY IF EXISTS public_access_tenant_cart_items ON public.cart_items;
DROP POLICY IF EXISTS auth_tenant_cart_items ON public.cart_items;
DROP POLICY IF EXISTS service_role_all_cart_items ON public.cart_items;

-- Public / Storefront Cart Item Access: Terikat langsung ke cart milik tenant yang aktif
CREATE POLICY public_access_tenant_cart_items ON public.cart_items
AS PERMISSIVE FOR ALL TO public
USING (
    EXISTS (
        SELECT 1 FROM public.carts c
        WHERE c.id = cart_items.cart_id
          AND c.tenant_id = (
              CASE 
                  WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                  THEN current_setting('app.current_tenant_id', true)::uuid
                  ELSE (
                      SELECT id FROM public.tenants 
                      WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                  )
              END
          )
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1 FROM public.carts c
        WHERE c.id = cart_items.cart_id
          AND c.tenant_id = (
              CASE 
                  WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                  THEN current_setting('app.current_tenant_id', true)::uuid
                  ELSE (
                      SELECT id FROM public.tenants 
                      WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                  )
              END
          )
    )
);

-- Authenticated Merchant Access
CREATE POLICY auth_tenant_cart_items ON public.cart_items
AS PERMISSIVE FOR ALL TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.carts c
        WHERE c.id = cart_items.cart_id
          AND c.tenant_id = (
              CASE 
                  WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                  THEN current_setting('app.current_tenant_id', true)::uuid
                  ELSE (
                      SELECT id FROM public.tenants 
                      WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                  )
              END
          )
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1 FROM public.carts c
        WHERE c.id = cart_items.cart_id
          AND c.tenant_id = (
              CASE 
                  WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                  THEN current_setting('app.current_tenant_id', true)::uuid
                  ELSE (
                      SELECT id FROM public.tenants 
                      WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                  )
              END
          )
    )
);

-- Service Role Full Access
CREATE POLICY service_role_all_cart_items ON public.cart_items
AS PERMISSIVE FOR ALL TO service_role
USING (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR EXISTS (
            SELECT 1 FROM public.carts c
            WHERE c.id = cart_items.cart_id
              AND c.tenant_id = (
                  CASE 
                      WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                      THEN current_setting('app.current_tenant_id', true)::uuid
                      ELSE (
                          SELECT id FROM public.tenants 
                          WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                      )
                  END
              )
        )
    )
)
WITH CHECK (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR EXISTS (
            SELECT 1 FROM public.carts c
            WHERE c.id = cart_items.cart_id
              AND c.tenant_id = (
                  CASE 
                      WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                      THEN current_setting('app.current_tenant_id', true)::uuid
                      ELSE (
                          SELECT id FROM public.tenants 
                          WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
                      )
                  END
              )
        )
    )
);
