-- =============================================================================
-- Reconciliation Candidate R04 (C-07 & C-08): Post-Replay RLS, FORCE RLS,
-- Wildcard Policy Elimination, & Function Privilege Hardening
-- CANDIDATE ONLY — DO NOT EXECUTE ON REMOTE DB BEFORE CTO SHARED-DB SIGN-OFF.
--
-- Resolves Collisions C-07 & C-08:
--   1. Drops ALL leftover wildcard USING (true) / WITH CHECK (true) policies
--      granted to `anon`, `authenticated`, or `public` across `public` tables
--      introduced by earlier Inbox migrations.
--   2. Enforces ENABLE + FORCE ROW LEVEL SECURITY across ALL tenant-scoped
--      tables in `public` (including `public.tenant_config_audit_logs` and
--      `public.merchants`).
--   3. Enforces C-08 privilege boundary on `public.is_jti_revoked(TEXT, TEXT)`:
--      REVOKE ALL FROM PUBLIC; GRANT EXECUTE TO anon, authenticated, service_role.
--   4. Verifies `trg_tenants_set_updated_at` monotonic trigger on `public.tenants`.
-- =============================================================================

BEGIN;

-- 1. C-07: Remove ALL leftover wildcard USING (true) / WITH CHECK (true) policies
--    for anon / authenticated / public roles across public schema tables.
DO $$
DECLARE
    v_pol RECORD;
    v_roles TEXT[];
BEGIN
    FOR v_pol IN
        SELECT
            c.relname AS table_name,
            pol.polname AS policy_name,
            ARRAY(
                SELECT CASE WHEN r = 0 THEN 'public' ELSE r::regrole::text END
                FROM unnest(pol.polroles) AS r
            ) AS role_names,
            COALESCE(pg_get_expr(pol.polqual, pol.polrelid), '') AS qual_expr,
            COALESCE(pg_get_expr(pol.polwithcheck, pol.polrelid), '') AS check_expr
        FROM pg_policy pol
        JOIN pg_class c ON c.oid = pol.polrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
    LOOP
        v_roles := v_pol.role_names;
        IF (
            'anon' = ANY(v_roles)
            OR 'authenticated' = ANY(v_roles)
            OR 'public' = ANY(v_roles)
        ) AND (
            lower(btrim(v_pol.qual_expr)) = 'true'
            OR lower(btrim(v_pol.check_expr)) = 'true'
        ) THEN
            EXECUTE format(
                'DROP POLICY IF EXISTS %I ON public.%I;',
                v_pol.policy_name,
                v_pol.table_name
            );
        END IF;
    END LOOP;
END
$$;

-- 2. C-07: Enforce ENABLE + FORCE ROW LEVEL SECURITY on ALL tenant-scoped public tables
--    (plus public.merchants) and guarantee scoped service_role/authenticated policies
--    where missing without introducing any wildcard anon/authenticated policy.
DO $$
DECLARE
    v_tbl RECORD;
    v_has_tenant_id BOOLEAN;
    v_has_tenant_slug BOOLEAN;
    v_tenant_id_type TEXT;
    v_pred TEXT;
BEGIN
    FOR v_tbl IN
        SELECT DISTINCT t.table_name
        FROM information_schema.tables t
        JOIN information_schema.columns c
          ON c.table_schema = t.table_schema AND c.table_name = t.table_name
        WHERE t.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND (
              c.column_name IN ('tenant_id', 'tenant_slug', 'store_id', 'merchant_id')
              OR t.table_name IN ('cart_items', 'tenants', 'merchants', 'tenant_config_audit_logs')
          )
          AND t.table_name NOT IN (
              'system_health_checks', 'provinces', 'cities', 'districts',
              'postal_codes', 'subscription_plans', 'pricing_tiers', 'spatial_ref_sys'
          )
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', v_tbl.table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY;', v_tbl.table_name);

        -- Ensure at least one scoped tenant policy exists if table has 0 policies
        IF NOT EXISTS (
            SELECT 1
            FROM pg_policy pol
            JOIN pg_class cl ON cl.oid = pol.polrelid
            JOIN pg_namespace ns ON ns.oid = cl.relnamespace
            WHERE ns.nspname = 'public' AND cl.relname = v_tbl.table_name
        ) THEN
            SELECT
                BOOL_OR(column_name = 'tenant_id'),
                BOOL_OR(column_name = 'tenant_slug'),
                MAX(CASE WHEN column_name = 'tenant_id' THEN data_type ELSE NULL END)
            INTO v_has_tenant_id, v_has_tenant_slug, v_tenant_id_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = v_tbl.table_name;

            IF v_has_tenant_id AND v_tenant_id_type = 'uuid' THEN
                v_pred := 'tenant_id = public.current_app_tenant_uuid()';
            ELSIF v_has_tenant_id THEN
                v_pred := '(tenant_id::text = NULLIF(current_setting(''app.current_tenant_id'', true), '''') OR tenant_id::text = public.current_app_tenant_slug() OR tenant_id::text = public.current_app_tenant_uuid()::text)';
            ELSIF v_has_tenant_slug THEN
                v_pred := '(tenant_slug = NULLIF(current_setting(''app.current_tenant_id'', true), '''') OR tenant_slug = public.current_app_tenant_slug())';
            ELSE
                v_pred := 'NULLIF(current_setting(''app.current_tenant_id'', true), '''') IS NULL';
            END IF;

            EXECUTE format(
                'CREATE POLICY %I ON public.%I AS PERMISSIVE FOR ALL TO service_role USING (NULLIF(current_setting(''app.current_tenant_id'', true), '''') IS NULL OR %s) WITH CHECK (NULLIF(current_setting(''app.current_tenant_id'', true), '''') IS NULL OR %s);',
                'service_role_scoped_' || v_tbl.table_name,
                v_tbl.table_name,
                v_pred,
                v_pred
            );
        END IF;
    END LOOP;
END
$$;

-- 3. C-08: Explicit FORCE ROW LEVEL SECURITY + strict least-privilege on tenant_config_audit_logs
ALTER TABLE public.tenant_config_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_config_audit_logs FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.tenant_config_audit_logs FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.tenant_config_audit_logs TO service_role;

DROP POLICY IF EXISTS "service_role_full_access_tenant_config_audit_logs" ON public.tenant_config_audit_logs;
CREATE POLICY "service_role_scoped_tenant_config_audit_logs"
    ON public.tenant_config_audit_logs
    AS PERMISSIVE FOR ALL
    TO service_role
    USING (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_id = public.current_app_tenant_uuid()
    )
    WITH CHECK (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_id = public.current_app_tenant_uuid()
    );

-- 4. C-08: Explicit privilege hardening on public.is_jti_revoked(TEXT, TEXT)
REVOKE ALL ON FUNCTION public.is_jti_revoked(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_jti_revoked(TEXT, TEXT) TO anon, authenticated, service_role;

-- 5. C-08: Assert monotonic trigger trg_tenants_set_updated_at is installed on public.tenants
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'tenants'
          AND t.tgname = 'trg_tenants_set_updated_at'
          AND NOT t.tgisinternal
    ) THEN
        RAISE EXCEPTION 'C-08 VIOLATION: Trigger trg_tenants_set_updated_at missing on public.tenants';
    END IF;
END
$$;

COMMIT;
