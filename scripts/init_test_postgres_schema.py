"""scripts/init_test_postgres_schema.py
Initializes PostgreSQL test database roles and schema for CTO P1 compliance.
Ensures roles 'anon', 'authenticated', 'service_role' exist with non-superuser / non-bypass privileges,
and tables 'orders' and 'staging_alumni_cpm' have RLS and FORCE RLS enabled.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import get_db_connection


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def init_test_schema():
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOLOGIN;
      END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOLOGIN;
      END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role BYPASSRLS NOCREATEDB NOCREATEROLE NOLOGIN;
      END IF;
    END
    $$;

    CREATE TABLE IF NOT EXISTS public.orders (
      id VARCHAR PRIMARY KEY,
      tenant_id VARCHAR NOT NULL,
      tenant_slug VARCHAR NOT NULL,
      product_id VARCHAR,
      product_title VARCHAR,
      customer_name VARCHAR,
      customer_phone VARCHAR,
      status VARCHAR NOT NULL,
      gross_amount NUMERIC,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS public.staging_alumni_cpm (
      id SERIAL PRIMARY KEY,
      tenant_id VARCHAR NOT NULL,
      lead_phone VARCHAR NOT NULL,
      alumni_name VARCHAR,
      status VARCHAR,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );

    ALTER TABLE public.staging_alumni_cpm ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.staging_alumni_cpm FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation_staging_alumni_cpm ON public.staging_alumni_cpm;
    CREATE POLICY tenant_isolation_staging_alumni_cpm ON public.staging_alumni_cpm
      AS PERMISSIVE FOR ALL TO public
      USING ((tenant_id)::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
      WITH CHECK ((tenant_id)::text = NULLIF(current_setting('app.current_tenant_id', true), ''));

    ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.orders FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS p1_tenant_isolation_orders ON public.orders;
    CREATE POLICY p1_tenant_isolation_orders ON public.orders
      AS PERMISSIVE FOR ALL TO public
      USING (((tenant_id)::text = NULLIF(current_setting('app.current_tenant_id', true), '')) OR (tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')))
      WITH CHECK (((tenant_id)::text = NULLIF(current_setting('app.current_tenant_id', true), '')) OR (tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')));

    GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authenticated;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;
    """)

    cur.close()
    conn.close()
    print("[OK] Live PostgreSQL test database schema & roles successfully initialized!")


if __name__ == "__main__":
    init_test_schema()
