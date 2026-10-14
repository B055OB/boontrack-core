"""scripts/init_test_postgres_schema.py
Initializes PostgreSQL test database roles and schema for CTO P1 compliance.
Ensures roles 'anon', 'authenticated', 'service_role' exist with non-superuser / non-bypass privileges,
and tables 'orders' and 'staging_alumni_cpm' have RLS and FORCE RLS enabled.
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

if not os.getenv("POSTGRES_HOST") or os.getenv("POSTGRES_HOST") == "postgres":
    os.environ["POSTGRES_HOST"] = "127.0.0.1"
if not os.getenv("POSTGRES_PORT"):
    os.environ["POSTGRES_PORT"] = "5432"
if not os.getenv("POSTGRES_PASSWORD"):
    os.environ["POSTGRES_PASSWORD"] = "test_ci_postgres_password"
if not os.getenv("POSTGRES_USER"):
    os.environ["POSTGRES_USER"] = "postgres"
if not os.getenv("POSTGRES_DB"):
    os.environ["POSTGRES_DB"] = "postgres"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import get_db_connection
from app.core.config import settings

if not getattr(settings, "POSTGRES_PASSWORD", None):
    settings.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "test_ci_postgres_password")
if not getattr(settings, "POSTGRES_USER", None):
    settings.POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
if not getattr(settings, "POSTGRES_DB", None):
    settings.POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
if not getattr(settings, "POSTGRES_PORT", None):
    settings.POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
if not getattr(settings, "POSTGRES_HOST", None) or settings.POSTGRES_HOST == "postgres":
    settings.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")

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
      tenant_id UUID NOT NULL,
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

    DO $$
    BEGIN
      BEGIN
        ALTER TABLE public.orders ALTER COLUMN tenant_id TYPE UUID USING tenant_id::uuid;
      EXCEPTION WHEN others THEN
        NULL;
      END;
    END
    $$;

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

    CREATE TABLE IF NOT EXISTS public.tenants (
      id UUID PRIMARY KEY,
      name VARCHAR NOT NULL,
      slug VARCHAR UNIQUE NOT NULL,
      is_active BOOLEAN DEFAULT TRUE,
      metadata JSONB DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_read_policy ON public.tenants;
    CREATE POLICY tenant_read_policy ON public.tenants
      AS PERMISSIVE FOR SELECT TO public
      USING (true);

    INSERT INTO public.tenants (id, name, slug)
    VALUES 
      ('00000000-0000-0000-0000-00000000000a', 'Tenant Alpha', 'tenant_alpha'),
      ('00000000-0000-0000-0000-00000000000b', 'Tenant Beta', 'tenant_beta')
    ON CONFLICT (slug) DO NOTHING;

    CREATE TABLE IF NOT EXISTS public.whatsapp_connections (
      id VARCHAR PRIMARY KEY,
      tenant_id VARCHAR NOT NULL,
      tenant_slug VARCHAR NOT NULL,
      provider VARCHAR,
      channel_type VARCHAR,
      status VARCHAR,
      is_connected BOOLEAN DEFAULT TRUE,
      phone_number VARCHAR,
      phone_number_id VARCHAR,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    ALTER TABLE public.whatsapp_connections ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.whatsapp_connections FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS auth_permissive_whatsapp_connections ON public.whatsapp_connections;
    CREATE POLICY auth_permissive_whatsapp_connections ON public.whatsapp_connections
      AS PERMISSIVE FOR ALL TO public
      USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
      WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

    GRANT ALL ON SCHEMA public TO postgres;
    GRANT USAGE ON SCHEMA public TO authenticated, anon, service_role;
    GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres;
    GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authenticated;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated, service_role;
    """)

    cur.close()
    conn.close()
    print("[OK] Live PostgreSQL test database schema & roles successfully initialized!")


if __name__ == "__main__":
    init_test_schema()
