-- ==============================================================================================
-- Migration 027: Harden RLS on tenants, commerce_products, carts, and attributions
-- ==============================================================================================
-- Tujuan:
-- 1. Menyelaraskan perbandingan RLS dengan tipe data asli tiap kolom (UUID vs VARCHAR/TEXT).
-- 2. Memvalidasi current_setting('app.current_tenant_id', true) secara aman agar tidak melempar
--    exception 'invalid input syntax for type uuid' saat nilainya berupa slug teks, string kosong (''),
--    atau NULL.
-- 3. Mendukung dual-resolution: mengenali tenant baik melalui UUID (misal tenants.id, carts.tenant_id)
--    maupun melalui slug teks (misal tenants.slug, commerce_products.tenant_id, attributions.tenant_id).
-- 4. Mengeliminasi seluruh kebijakan permissif wildcard `USING (true)` / `WITH CHECK (true)`.
-- ==============================================================================================

-- ----------------------------------------------------------------------------------------------
-- 1. Helper Functions: Safe UUID Cast & Tenant Resolution
-- ----------------------------------------------------------------------------------------------

-- Fungsi aman konversi string ke UUID tanpa melempar runtime exception
CREATE OR REPLACE FUNCTION public.try_cast_uuid(p_val text)
RETURNS uuid
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
AS $$
BEGIN
    IF p_val IS NULL OR p_val = '' THEN
        RETURN NULL;
    END IF;
    IF p_val ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        RETURN p_val::uuid;
    END IF;
    RETURN NULL;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$;

-- Mengembalikan UUID tenant aktif dari session context app.current_tenant_id
-- Jika konteks berisi UUID, langsung dikembalikan sebagai UUID.
-- Jika konteks berisi slug string, dilakukan lookup id UUID ke tabel public.tenants.
CREATE OR REPLACE FUNCTION public.current_app_tenant_uuid()
RETURNS uuid
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
AS $$
DECLARE
    v_val text;
BEGIN
    v_val := NULLIF(current_setting('app.current_tenant_id', true), '');
    IF v_val IS NULL THEN
        RETURN NULL;
    END IF;
    -- Jika format UUID valid
    IF v_val ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        RETURN v_val::uuid;
    END IF;
    -- Jika format slug teks, cari UUID id dari tabel tenants
    RETURN (SELECT id FROM public.tenants WHERE slug = v_val LIMIT 1);
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$;

-- Mengembalikan slug teks tenant aktif dari session context app.current_tenant_id
-- Jika konteks berisi slug, dikembalikan sebagai slug.
-- Jika konteks berisi UUID, dicari slug pasangannya di tabel public.tenants.
CREATE OR REPLACE FUNCTION public.current_app_tenant_slug()
RETURNS text
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
AS $$
DECLARE
    v_val text;
BEGIN
    v_val := NULLIF(current_setting('app.current_tenant_id', true), '');
    IF v_val IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_val ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        RETURN (SELECT slug FROM public.tenants WHERE id = v_val::uuid LIMIT 1);
    END IF;
    RETURN (SELECT slug FROM public.tenants WHERE slug = v_val LIMIT 1);
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$;

-- Berikan hak eksekusi helper function ke seluruh role database
GRANT EXECUTE ON FUNCTION public.try_cast_uuid(text) TO authenticated, anon, service_role;
GRANT EXECUTE ON FUNCTION public.current_app_tenant_uuid() TO authenticated, anon, service_role;
GRANT EXECUTE ON FUNCTION public.current_app_tenant_slug() TO authenticated, anon, service_role;


-- ----------------------------------------------------------------------------------------------
-- 2. TABEL: tenants (id: UUID, slug: VARCHAR)
-- ----------------------------------------------------------------------------------------------
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenants FORCE ROW LEVEL SECURITY;

-- Drop legacy / wildcard policies
DROP POLICY IF EXISTS allow_all_select_tenants ON public.tenants;
DROP POLICY IF EXISTS allow_all_insert_tenants ON public.tenants;
DROP POLICY IF EXISTS allow_all_update_tenants ON public.tenants;
DROP POLICY IF EXISTS "Allow public read tenants" ON public.tenants;
DROP POLICY IF EXISTS tenant_read_policy ON public.tenants;
DROP POLICY IF EXISTS public_select_active_tenants ON public.tenants;
DROP POLICY IF EXISTS auth_tenant_dml_tenants ON public.tenants;
DROP POLICY IF EXISTS service_role_all_tenants ON public.tenants;

-- Storefront / Public Read: Membaca tenant yang sedang aktif atau mencocokkan tenant_id aktif
CREATE POLICY public_select_active_tenants ON public.tenants
AS PERMISSIVE FOR SELECT TO public
USING (
    is_active = true
    OR id = (
        CASE 
            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN current_setting('app.current_tenant_id', true)::uuid
            ELSE NULL
        END
    )
    OR slug = NULLIF(current_setting('app.current_tenant_id', true), '')
);

-- Merchant Authenticated DML: Hanya dapat memodifikasi data tenant miliknya sendiri
CREATE POLICY auth_tenant_dml_tenants ON public.tenants
AS PERMISSIVE FOR ALL TO authenticated
USING (
    id = (
        CASE 
            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN current_setting('app.current_tenant_id', true)::uuid
            ELSE NULL
        END
    )
    OR slug = NULLIF(current_setting('app.current_tenant_id', true), '')
)
WITH CHECK (
    id = (
        CASE 
            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN current_setting('app.current_tenant_id', true)::uuid
            ELSE NULL
        END
    )
    OR slug = NULLIF(current_setting('app.current_tenant_id', true), '')
);

-- Service Role Full Access
CREATE POLICY service_role_all_tenants ON public.tenants
AS PERMISSIVE FOR ALL TO service_role
USING (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR id = (
            CASE 
                WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN current_setting('app.current_tenant_id', true)::uuid
                ELSE NULL
            END
        )
        OR slug = current_setting('app.current_tenant_id', true)
    )
)
WITH CHECK (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR id = (
            CASE 
                WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN current_setting('app.current_tenant_id', true)::uuid
                ELSE NULL
            END
        )
        OR slug = current_setting('app.current_tenant_id', true)
    )
);


-- ----------------------------------------------------------------------------------------------
-- 3. TABEL: commerce_products (tenant_id: VARCHAR)
-- ----------------------------------------------------------------------------------------------
ALTER TABLE public.commerce_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.commerce_products FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS allow_all_select_commerce_products ON public.commerce_products;
DROP POLICY IF EXISTS allow_all_insert_commerce_products ON public.commerce_products;
DROP POLICY IF EXISTS allow_all_update_commerce_products ON public.commerce_products;
DROP POLICY IF EXISTS allow_all_ops_commerce_products ON public.commerce_products;
DROP POLICY IF EXISTS public_select_active_commerce_products ON public.commerce_products;
DROP POLICY IF EXISTS auth_tenant_dml_commerce_products ON public.commerce_products;
DROP POLICY IF EXISTS service_role_all_commerce_products ON public.commerce_products;

-- Storefront Public Read: Produk aktif dapat dibaca publik atau dicocokkan dengan tenant aktif
CREATE POLICY public_select_active_commerce_products ON public.commerce_products
AS PERMISSIVE FOR SELECT TO public
USING (
    is_active = true
    OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
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

-- Merchant Authenticated DML: Operasi katalog produk terisolasi per tenant
CREATE POLICY auth_tenant_dml_commerce_products ON public.commerce_products
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
CREATE POLICY service_role_all_commerce_products ON public.commerce_products
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


-- ----------------------------------------------------------------------------------------------
-- 4. TABEL: carts (id: UUID, tenant_id: UUID)
-- ----------------------------------------------------------------------------------------------
ALTER TABLE public.carts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.carts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public carts select" ON public.carts;
DROP POLICY IF EXISTS "Public carts insert" ON public.carts;
DROP POLICY IF EXISTS "Public carts update" ON public.carts;
DROP POLICY IF EXISTS auth_tenant_carts ON public.carts;
DROP POLICY IF EXISTS public_access_tenant_carts ON public.carts;
DROP POLICY IF EXISTS service_role_all_carts ON public.carts;

-- Storefront / Public Shopper Access:
-- Tipe kolom tenant_id adalah UUID. Menggunakan resolusi UUID valid atau lookup slug dari tenants.
-- Menjamin zero data leakage dan zero type error.
CREATE POLICY public_access_tenant_carts ON public.carts
AS PERMISSIVE FOR ALL TO public
USING (
    tenant_id = (
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
WITH CHECK (
    tenant_id = (
        CASE 
            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN current_setting('app.current_tenant_id', true)::uuid
            ELSE (
                SELECT id FROM public.tenants 
                WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            )
        END
    )
);

-- Authenticated Merchant Access
CREATE POLICY auth_tenant_carts ON public.carts
AS PERMISSIVE FOR ALL TO authenticated
USING (
    tenant_id = (
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
WITH CHECK (
    tenant_id = (
        CASE 
            WHEN current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN current_setting('app.current_tenant_id', true)::uuid
            ELSE (
                SELECT id FROM public.tenants 
                WHERE slug = NULLIF(current_setting('app.current_tenant_id', true), '')
            )
        END
    )
);

-- Service Role Full Access
CREATE POLICY service_role_all_carts ON public.carts
AS PERMISSIVE FOR ALL TO service_role
USING (
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = (
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
    (current_user = 'service_role' OR auth.role() = 'service_role')
    AND (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = (
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


-- ----------------------------------------------------------------------------------------------
-- 5. TABEL: attributions (id: UUID, tenant_id: VARCHAR)
-- ----------------------------------------------------------------------------------------------
ALTER TABLE public.attributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attributions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public access on attributions" ON public.attributions;
DROP POLICY IF EXISTS "Service role full access on attributions" ON public.attributions;
DROP POLICY IF EXISTS public_insert_attributions ON public.attributions;
DROP POLICY IF EXISTS auth_tenant_attributions ON public.attributions;
DROP POLICY IF EXISTS service_role_all_attributions ON public.attributions;

-- Storefront / Visitor Tracking: Insert kunjungan dengan tenant_id terikat konteks tenant aktif
CREATE POLICY public_insert_attributions ON public.attributions
AS PERMISSIVE FOR INSERT TO public
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

-- Merchant Authenticated Access: Melihat & mengelola atribusi tenant sendiri
CREATE POLICY auth_tenant_attributions ON public.attributions
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
CREATE POLICY service_role_all_attributions ON public.attributions
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
