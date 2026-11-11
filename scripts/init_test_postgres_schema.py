"""scripts/init_test_postgres_schema.py
Initializes PostgreSQL test database roles and schema for CTO P1 compliance.
Ensures roles 'anon', 'authenticated', 'service_role' exist with non-superuser / non-bypass privileges,
creates helper functions, tables, views, and strict RLS policies for 100% CI database isolation.
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

# Synchronize environment variables and settings with CI or local test DB
if not os.getenv("POSTGRES_HOST") or os.getenv("POSTGRES_HOST") == "postgres":
    os.environ["POSTGRES_HOST"] = "127.0.0.1"
if not os.getenv("POSTGRES_PORT"):
    os.environ["POSTGRES_PORT"] = "5432"
if not os.getenv("POSTGRES_PASSWORD"):
    os.environ["POSTGRES_PASSWORD"] = "test_password"
if not os.getenv("POSTGRES_USER"):
    os.environ["POSTGRES_USER"] = "test_user"
if not os.getenv("POSTGRES_DB"):
    os.environ["POSTGRES_DB"] = "test_boontrack"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
settings.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
settings.POSTGRES_USER = os.getenv("POSTGRES_USER")
settings.POSTGRES_DB = os.getenv("POSTGRES_DB")
settings.POSTGRES_PORT = os.getenv("POSTGRES_PORT")
settings.POSTGRES_HOST = os.getenv("POSTGRES_HOST")

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
    -- 1. ROLES INITIALIZATION
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
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'boontrack_test_app_user') THEN
        CREATE ROLE boontrack_test_app_user WITH LOGIN PASSWORD 'TestAppUserPassword!123' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
      END IF;
      GRANT authenticated TO boontrack_test_app_user;
    END
    $$;

    -- 2. HELPER FUNCTIONS FOR DUAL RESOLUTION (UUID & SLUG)
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

    -- Pre-declare tenants table so helper functions can compile
    CREATE TABLE IF NOT EXISTS public.tenants (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      name VARCHAR NOT NULL,
      slug VARCHAR UNIQUE NOT NULL,
      tier VARCHAR DEFAULT 'STARTER',
      status VARCHAR DEFAULT 'ACTIVE',
      is_active BOOLEAN DEFAULT TRUE,
      region_config JSONB DEFAULT '{}'::jsonb,
      metadata JSONB DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS tier VARCHAR DEFAULT 'STARTER';
    ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'ACTIVE';
    ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS region_config JSONB DEFAULT '{}'::jsonb;

    CREATE OR REPLACE FUNCTION public.current_app_tenant_uuid()
    RETURNS uuid
    LANGUAGE plpgsql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $$
    DECLARE
        v_val text;
    BEGIN
        v_val := NULLIF(current_setting('app.current_tenant_id', true), '');
        IF v_val IS NULL THEN
            RETURN NULL;
        END IF;
        IF v_val ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
            RETURN v_val::uuid;
        END IF;
        RETURN (SELECT id FROM public.tenants WHERE slug = v_val LIMIT 1);
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
    $$;

    CREATE OR REPLACE FUNCTION public.current_app_tenant_slug()
    RETURNS text
    LANGUAGE plpgsql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
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

    GRANT EXECUTE ON FUNCTION public.try_cast_uuid(text) TO authenticated, anon, service_role;
    GRANT EXECUTE ON FUNCTION public.current_app_tenant_uuid() TO authenticated, anon, service_role;
    GRANT EXECUTE ON FUNCTION public.current_app_tenant_slug() TO authenticated, anon, service_role;

    -- 3. CORE & TEST TABLES
    -- Table: tenants
    ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.tenants FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_read_policy ON public.tenants;
    DROP POLICY IF EXISTS public_select_active_tenants ON public.tenants;
    CREATE POLICY public_select_active_tenants ON public.tenants
      AS PERMISSIVE FOR SELECT TO public
      USING (is_active = true);

    DROP POLICY IF EXISTS auth_tenant_dml_tenants ON public.tenants;
    CREATE POLICY auth_tenant_dml_tenants ON public.tenants
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))
        OR slug = NULLIF(current_setting('app.current_tenant_id', true), '')
      )
      WITH CHECK (
        id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))
        OR slug = NULLIF(current_setting('app.current_tenant_id', true), '')
      );

    DROP POLICY IF EXISTS service_role_all_tenants ON public.tenants;
    CREATE POLICY service_role_all_tenants ON public.tenants
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))
        OR slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      )
      WITH CHECK (
        id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))
        OR slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      );

    INSERT INTO public.tenants (id, name, slug)
    VALUES
      ('00000000-0000-0000-0000-00000000000a', 'Tenant Alpha', 'tenant_alpha'),
      ('00000000-0000-0000-0000-00000000000b', 'Tenant Beta', 'tenant_beta')
    ON CONFLICT (slug) DO NOTHING;

    -- Table: merchants (Production-grade transactional merchant registry)
    CREATE TABLE IF NOT EXISTS public.merchants (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      slug VARCHAR UNIQUE NOT NULL,
      store_name VARCHAR NOT NULL,
      business_category VARCHAR DEFAULT 'Retail / E-Commerce',
      owner_name VARCHAR NOT NULL,
      owner_whatsapp VARCHAR DEFAULT '',
      owner_email VARCHAR NOT NULL,
      status VARCHAR NOT NULL DEFAULT 'ACTIVE',
      plan_tier VARCHAR DEFAULT 'STARTER',
      is_otp_verified BOOLEAN DEFAULT FALSE,
      active_until TIMESTAMPTZ,
      referral_code VARCHAR,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'ACTIVE';
    ALTER TABLE public.merchants ADD COLUMN IF NOT EXISTS is_otp_verified BOOLEAN DEFAULT FALSE;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_merchants_slug_unique ON public.merchants (slug);
    CREATE INDEX IF NOT EXISTS idx_merchants_status ON public.merchants (status);
    CREATE INDEX IF NOT EXISTS idx_merchants_owner_email ON public.merchants (lower(owner_email));

    ALTER TABLE public.merchants ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.merchants NO FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS service_role_all_merchants ON public.merchants;
    CREATE POLICY service_role_all_merchants ON public.merchants
      AS PERMISSIVE FOR ALL TO service_role
      USING (true)
      WITH CHECK (true);

    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, status, plan_tier)
    VALUES
      ('tenant_alpha', 'Tenant Alpha Store', 'Alpha Owner', 'owner_alpha@boontrack.com', 'ACTIVE', 'STARTER'),
      ('tenant_beta', 'Tenant Beta Store', 'Beta Owner', 'owner_beta@boontrack.com', 'ACTIVE', 'STARTER')
    ON CONFLICT (slug) DO NOTHING;

    -- Table: cs_agents (Tenant team members & operational staff)
    CREATE TABLE IF NOT EXISTS public.cs_agents (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id VARCHAR NOT NULL,
      name VARCHAR(255) NOT NULL,
      phone VARCHAR(50),
      email VARCHAR(255),
      role VARCHAR(20) NOT NULL DEFAULT 'agent' CHECK (role IN ('owner', 'supervisor', 'agent', 'admin')),
      presence VARCHAR(20) NOT NULL DEFAULT 'offline' CHECK (presence IN ('active', 'break', 'offline')),
      max_active_chats INT NOT NULL DEFAULT 10,
      is_active BOOLEAN NOT NULL DEFAULT TRUE,
      created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    ALTER TABLE public.cs_agents ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.cs_agents FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation_cs_agents ON public.cs_agents;
    CREATE POLICY tenant_isolation_cs_agents ON public.cs_agents
      AS PERMISSIVE FOR ALL TO public
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      );

    DROP POLICY IF EXISTS service_role_all_cs_agents ON public.cs_agents;
    CREATE POLICY service_role_all_cs_agents ON public.cs_agents
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      );

    INSERT INTO public.cs_agents (tenant_id, name, email, role, is_active)
    VALUES
      ('tenant_alpha', 'Staff Alpha', 'staff_alpha@boontrack.com', 'admin', true)
    ON CONFLICT DO NOTHING;

    -- Table: orders (Aligned with Migration 033 & Staging Baseline: tenant_id VARCHAR(100))
    CREATE TABLE IF NOT EXISTS public.orders (
      id VARCHAR PRIMARY KEY,
      tenant_id VARCHAR(100) NOT NULL,
      tenant_slug VARCHAR NOT NULL,
      sku_id VARCHAR(255),
      product_id VARCHAR,
      product_title VARCHAR,
      customer_name VARCHAR,
      customer_phone VARCHAR,
      customer_email VARCHAR,
      status VARCHAR NOT NULL,
      payment_status VARCHAR(32) DEFAULT 'PENDING',
      order_status VARCHAR(32) DEFAULT 'PENDING',
      fulfillment_status VARCHAR(64) NOT NULL DEFAULT 'UNFULFILLED',
      gross_amount NUMERIC,
      amount NUMERIC(14, 2),
      paid_at TIMESTAMPTZ,
      metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      fulfillment_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.orders FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS p1_tenant_isolation_orders ON public.orders;
    CREATE POLICY p1_tenant_isolation_orders ON public.orders
      AS PERMISSIVE FOR ALL TO public
      USING (
        tenant_id::text = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
      )
      WITH CHECK (
        tenant_id::text = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
      );

    -- Table: payment_events (Aligned with Migration 033: tenant_id VARCHAR(100) + DuitkuS2SVerifier columns)
    CREATE TABLE IF NOT EXISTS public.payment_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      provider VARCHAR(64) NOT NULL,
      event_id VARCHAR(128) UNIQUE NOT NULL,
      provider_event_id VARCHAR(128),
      reference_id VARCHAR(128),
      order_id VARCHAR(128),
      tenant_id VARCHAR(100) NOT NULL,
      event_type VARCHAR(64) NOT NULL,
      amount NUMERIC(14, 2),
      payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      status VARCHAR(64) NOT NULL DEFAULT 'PROCESSING',
      record_classification VARCHAR(64) NOT NULL DEFAULT 'STAGE3_SETTLEMENT',
      processed_at TIMESTAMPTZ,
      s2s_verification_status VARCHAR(64),
      s2s_claimed_at TIMESTAMPTZ,
      s2s_lease_expires_at TIMESTAMPTZ,
      s2s_claimed_by VARCHAR(128),
      s2s_attempt_count INT NOT NULL DEFAULT 0,
      s2s_last_error TEXT,
      s2s_verified_at TIMESTAMPTZ,
      s2s_status_code VARCHAR(32),
      s2s_reference VARCHAR(128),
      s2s_response_payload JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      CONSTRAINT uq_payment_events_provider_event_id UNIQUE (provider, event_id),
      CONSTRAINT uq_payment_events_provider_provider_event_id UNIQUE (provider, provider_event_id)
    );
    ALTER TABLE public.payment_events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.payment_events FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation_payment_events ON public.payment_events;
    CREATE POLICY tenant_isolation_payment_events ON public.payment_events
      FOR ALL TO authenticated
      USING (
        tenant_id = current_setting('app.current_tenant_id', true)::text
      )
      WITH CHECK (
        tenant_id = current_setting('app.current_tenant_id', true)::text
      );

    -- Table: financial_ledger (Aligned with Migration 033: tenant_id VARCHAR(100) + nullable fee/net)
    CREATE TABLE IF NOT EXISTS public.financial_ledger (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      order_id VARCHAR(128) NOT NULL,
      tenant_id VARCHAR(100) NOT NULL,
      provider VARCHAR(64) NOT NULL,
      event_id VARCHAR(128),
      gross_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
      fee_amount NUMERIC(14, 2),
      net_amount NUMERIC(14, 2),
      currency VARCHAR(16) NOT NULL DEFAULT 'IDR',
      transaction_type VARCHAR(64) NOT NULL DEFAULT 'PAYMENT_CREDIT',
      status VARCHAR(32) NOT NULL DEFAULT 'SETTLED',
      transaction_status VARCHAR(32) NOT NULL DEFAULT 'SETTLED',
      reconciliation_status VARCHAR(64) NOT NULL DEFAULT 'PENDING_RECONCILIATION',
      metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      CONSTRAINT chk_financial_ledger_reconciliation_integrity CHECK (
        (reconciliation_status = 'PENDING_RECONCILIATION' AND fee_amount IS NULL AND net_amount IS NULL)
        OR (
          reconciliation_status = 'RECONCILED'
          AND fee_amount IS NOT NULL
          AND net_amount IS NOT NULL
          AND fee_amount >= 0
          AND net_amount = gross_amount - fee_amount
        )
        OR (
          reconciliation_status = 'HISTORICAL_UNVERIFIED_ZERO_FEE'
          AND fee_amount IS NOT NULL
          AND net_amount IS NOT NULL
          AND fee_amount = 0
          AND net_amount = gross_amount
        )
      )
    );
    ALTER TABLE public.financial_ledger ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.financial_ledger FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation_financial_ledger ON public.financial_ledger;
    CREATE POLICY tenant_isolation_financial_ledger ON public.financial_ledger
      FOR ALL TO authenticated
      USING (
        tenant_id = current_setting('app.current_tenant_id', true)::text
      )
      WITH CHECK (
        tenant_id = current_setting('app.current_tenant_id', true)::text
      );

    -- Table: trial_quota_reservations (Migration 034: Persistent Atomic Trial Quota Reservation Store)
    CREATE TABLE IF NOT EXISTS public.trial_quota_reservations (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id VARCHAR(100) NOT NULL,
      tenant_slug VARCHAR(100),
      order_id VARCHAR(128) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'RESERVED',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      expires_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT uq_trial_quota_tenant_order UNIQUE (tenant_id, order_id),
      CONSTRAINT chk_trial_quota_non_empty CHECK (
        BTRIM(tenant_id) <> ''
        AND BTRIM(order_id) <> ''
      ),
      CONSTRAINT chk_trial_quota_status CHECK (
        status IN ('RESERVED', 'COMMITTED', 'RELEASED', 'AMBIGUOUS_TIMEOUT')
      )
    );
    CREATE INDEX IF NOT EXISTS idx_trial_quota_tenant_status
    ON public.trial_quota_reservations (tenant_id, status);

    CREATE INDEX IF NOT EXISTS idx_trial_quota_slug_status
    ON public.trial_quota_reservations (tenant_slug, status);

    ALTER TABLE public.trial_quota_reservations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.trial_quota_reservations FORCE ROW LEVEL SECURITY;

    DROP POLICY IF EXISTS p1_tenant_isolation_trial_quota ON public.trial_quota_reservations;
    CREATE POLICY p1_tenant_isolation_trial_quota ON public.trial_quota_reservations
      AS PERMISSIVE FOR SELECT TO authenticated
      USING (
        tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
      );

    DROP POLICY IF EXISTS service_role_trial_quota ON public.trial_quota_reservations;
    CREATE POLICY service_role_trial_quota ON public.trial_quota_reservations
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
      )
      WITH CHECK (
        tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
      );

    -- Table: staging_alumni_cpm
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

    -- Table: whatsapp_connections
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

    -- Table: commerce_products
    CREATE TABLE IF NOT EXISTS public.commerce_products (
      id SERIAL PRIMARY KEY,
      tenant_id VARCHAR NOT NULL DEFAULT 'digicorn',
      product_code VARCHAR NOT NULL,
      title VARCHAR NOT NULL,
      category VARCHAR NOT NULL,
      price INT NOT NULL DEFAULT 5000,
      delivery_payload TEXT,
      keywords TEXT,
      is_active BOOLEAN DEFAULT TRUE,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );
    ALTER TABLE public.commerce_products ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.commerce_products FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS public_select_active_commerce_products ON public.commerce_products;
    CREATE POLICY public_select_active_commerce_products ON public.commerce_products
      AS PERMISSIVE FOR SELECT TO public
      USING (
        is_active = true
        AND (
          tenant_id = public.current_app_tenant_slug()
          OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        )
      );
    DROP POLICY IF EXISTS auth_tenant_dml_commerce_products ON public.commerce_products;
    CREATE POLICY auth_tenant_dml_commerce_products ON public.commerce_products
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      );
    DROP POLICY IF EXISTS service_role_all_commerce_products ON public.commerce_products;
    CREATE POLICY service_role_all_commerce_products ON public.commerce_products
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      );

    -- Table: carts
    CREATE TABLE IF NOT EXISTS public.carts (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL,
      session_id TEXT NOT NULL,
      customer_id TEXT,
      status TEXT NOT NULL DEFAULT 'ACTIVE',
      currency TEXT NOT NULL DEFAULT 'IDR',
      metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + interval '14 days'),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE public.carts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.carts FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS auth_tenant_carts ON public.carts;
    CREATE POLICY auth_tenant_carts ON public.carts
      AS PERMISSIVE FOR ALL TO authenticated
      USING (tenant_id = public.current_app_tenant_uuid())
      WITH CHECK (tenant_id = public.current_app_tenant_uuid());
    DROP POLICY IF EXISTS public_access_tenant_carts ON public.carts;
    CREATE POLICY public_access_tenant_carts ON public.carts
      AS PERMISSIVE FOR ALL TO public
      USING (tenant_id = public.current_app_tenant_uuid())
      WITH CHECK (tenant_id = public.current_app_tenant_uuid());
    DROP POLICY IF EXISTS service_role_all_carts ON public.carts;
    CREATE POLICY service_role_all_carts ON public.carts
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        tenant_id = public.current_app_tenant_uuid()
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_uuid()
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      );

    -- Table: cart_items
    CREATE TABLE IF NOT EXISTS public.cart_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      cart_id UUID NOT NULL,
      product_id TEXT NOT NULL,
      variant_id TEXT,
      quantity INT NOT NULL DEFAULT 1,
      unit_price_snapshot NUMERIC NOT NULL DEFAULT 0,
      selected_modifiers JSONB NOT NULL DEFAULT '[]'::jsonb,
      modifier_hash TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE public.cart_items ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.cart_items FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS auth_tenant_cart_items ON public.cart_items;
    CREATE POLICY auth_tenant_cart_items ON public.cart_items
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        cart_id IN (
          SELECT id FROM public.carts WHERE tenant_id = public.current_app_tenant_uuid()
        )
      )
      WITH CHECK (
        cart_id IN (
          SELECT id FROM public.carts WHERE tenant_id = public.current_app_tenant_uuid()
        )
      );
    DROP POLICY IF EXISTS public_access_tenant_cart_items ON public.cart_items;
    CREATE POLICY public_access_tenant_cart_items ON public.cart_items
      AS PERMISSIVE FOR ALL TO public
      USING (
        cart_id IN (
          SELECT id FROM public.carts WHERE tenant_id = public.current_app_tenant_uuid()
        )
      )
      WITH CHECK (
        cart_id IN (
          SELECT id FROM public.carts WHERE tenant_id = public.current_app_tenant_uuid()
        )
      );
    DROP POLICY IF EXISTS service_role_all_cart_items ON public.cart_items;
    CREATE POLICY service_role_all_cart_items ON public.cart_items
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        cart_id IN (
          SELECT id FROM public.carts WHERE tenant_id = public.current_app_tenant_uuid()
        )
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      )
      WITH CHECK (
        cart_id IN (
          SELECT id FROM public.carts WHERE tenant_id = public.current_app_tenant_uuid()
        )
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      );

    -- Table: attributions
    CREATE TABLE IF NOT EXISTS public.attributions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id VARCHAR NOT NULL,
      session_id VARCHAR NOT NULL,
      affiliate_id UUID,
      utm_source VARCHAR,
      utm_medium VARCHAR,
      utm_campaign VARCHAR,
      utm_content VARCHAR,
      utm_term VARCHAR,
      fbclid TEXT,
      ttclid TEXT,
      ip_hash VARCHAR NOT NULL,
      user_agent TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );
    ALTER TABLE public.attributions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.attributions FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS auth_tenant_attributions ON public.attributions;
    CREATE POLICY auth_tenant_attributions ON public.attributions
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      );
    DROP POLICY IF EXISTS public_insert_attributions ON public.attributions;
    CREATE POLICY public_insert_attributions ON public.attributions
      AS PERMISSIVE FOR INSERT TO public
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      );
    DROP POLICY IF EXISTS service_role_all_attributions ON public.attributions;
    CREATE POLICY service_role_all_attributions ON public.attributions
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      );

    -- Table: affiliates
    CREATE TABLE IF NOT EXISTS public.affiliates (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id VARCHAR NOT NULL,
      name VARCHAR NOT NULL,
      phone_number VARCHAR,
      email VARCHAR,
      referral_code VARCHAR NOT NULL,
      commission_rate NUMERIC NOT NULL DEFAULT 10.00,
      payout_bank_details JSONB DEFAULT '{}'::jsonb,
      status VARCHAR NOT NULL DEFAULT 'ACTIVE',
      role VARCHAR NOT NULL DEFAULT 'affiliate',
      manager_id UUID,
      phone VARCHAR,
      bank_name VARCHAR,
      bank_account_number VARCHAR,
      bank_account_holder VARCHAR,
      is_bank_verified BOOLEAN DEFAULT FALSE,
      experience_level VARCHAR DEFAULT 'BEGINNER',
      promotion_strategy_notes TEXT,
      social_media_links JSONB DEFAULT '{}'::jsonb,
      portfolio_url TEXT,
      screening_status VARCHAR DEFAULT 'PENDING',
      rejection_reason TEXT,
      agreed_to_rules BOOLEAN DEFAULT FALSE,
      reviewed_by UUID,
      reviewed_at TIMESTAMPTZ,
      parent_am_id UUID,
      region VARCHAR DEFAULT 'ID-NATIONAL',
      metadata JSONB DEFAULT '{}'::jsonb,
      balance NUMERIC DEFAULT 0,
      total_withdrawn NUMERIC DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE public.affiliates ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.affiliates FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS auth_tenant_affiliates ON public.affiliates;
    CREATE POLICY auth_tenant_affiliates ON public.affiliates
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      );
    DROP POLICY IF EXISTS public_select_active_affiliates ON public.affiliates;
    CREATE POLICY public_select_active_affiliates ON public.affiliates
      AS PERMISSIVE FOR SELECT TO public
      USING (
        status = 'ACTIVE'
        AND (
          tenant_id = public.current_app_tenant_slug()
          OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        )
      );
    DROP POLICY IF EXISTS service_role_all_affiliates ON public.affiliates;
    CREATE POLICY service_role_all_affiliates ON public.affiliates
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      );

    -- Table: affiliate_commissions
    CREATE TABLE IF NOT EXISTS public.affiliate_commissions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id VARCHAR NOT NULL,
      affiliate_id UUID NOT NULL,
      order_id VARCHAR NOT NULL,
      order_amount NUMERIC NOT NULL DEFAULT 0,
      amount NUMERIC NOT NULL DEFAULT 0,
      status VARCHAR NOT NULL DEFAULT 'PENDING',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      paid_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      product_type VARCHAR DEFAULT 'SHOP',
      CONSTRAINT uq_affiliate_commissions_tenant_order UNIQUE (tenant_id, order_id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_uq_affiliate_commissions_tenant_order ON public.affiliate_commissions (tenant_id, order_id);

    ALTER TABLE public.affiliate_commissions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.affiliate_commissions FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS auth_tenant_commissions ON public.affiliate_commissions;
    CREATE POLICY auth_tenant_commissions ON public.affiliate_commissions
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      );
    DROP POLICY IF EXISTS service_role_all_commissions ON public.affiliate_commissions;
    CREATE POLICY service_role_all_commissions ON public.affiliate_commissions
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
        OR NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
      );

    -- Table: conversation_sessions
    CREATE TABLE IF NOT EXISTS public.conversation_sessions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      session_id VARCHAR NOT NULL,
      tenant_id VARCHAR NOT NULL,
      channel VARCHAR,
      user_identifier VARCHAR,
      current_state VARCHAR,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW(),
      is_paused BOOLEAN DEFAULT FALSE,
      paused_until TIMESTAMPTZ,
      metadata JSONB DEFAULT '{}'::jsonb,
      paused_at TIMESTAMPTZ,
      paused_by VARCHAR
    );
    ALTER TABLE public.conversation_sessions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.conversation_sessions FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation_conversation_sessions ON public.conversation_sessions;
    CREATE POLICY tenant_isolation_conversation_sessions ON public.conversation_sessions
      AS PERMISSIVE FOR ALL TO public
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      );

    -- 4. REQUIRED VIEWS WITH SECURITY_INVOKER = TRUE
    DROP VIEW IF EXISTS public.v_affiliate_ledger CASCADE;
    DROP VIEW IF EXISTS public.affiliate_ledger CASCADE;
    DROP VIEW IF EXISTS public.v_affiliate_payout_summary CASCADE;
    DROP VIEW IF EXISTS public.chat_sessions CASCADE;

    CREATE OR REPLACE VIEW public.affiliate_ledger
    WITH (security_invoker = true) AS
    SELECT * FROM public.affiliate_commissions;

    CREATE OR REPLACE VIEW public.v_affiliate_ledger
    WITH (security_invoker = true) AS
    SELECT * FROM public.affiliate_ledger;

    CREATE OR REPLACE VIEW public.v_affiliate_payout_summary
    WITH (security_invoker = true) AS
    SELECT
        a.id AS affiliate_id,
        a.name AS affiliate_name,
        a.referral_code,
        NULL::text AS manager_name,
        count(c.id) AS total_sales_count,
        COALESCE(sum(c.amount), 0::numeric) AS total_commission_earned,
        COALESCE(sum(CASE WHEN c.status = 'PENDING' THEN c.amount ELSE 0 END), 0::numeric) AS commission_pending,
        COALESCE(sum(CASE WHEN c.status = 'PAID' THEN c.amount ELSE 0 END), 0::numeric) AS commission_paid
    FROM public.affiliates a
    LEFT JOIN public.affiliate_commissions c ON a.id = c.affiliate_id
    GROUP BY a.id, a.name, a.referral_code;

    CREATE OR REPLACE VIEW public.chat_sessions
    WITH (security_invoker = true) AS
    SELECT * FROM public.conversation_sessions;

    -- 5. GRANTS FOR ROLE SECURITY
    GRANT USAGE ON SCHEMA public TO authenticated, anon, service_role, boontrack_test_app_user;
    GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated, anon, service_role, boontrack_test_app_user;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated, anon, service_role, boontrack_test_app_user;

    -- Strict least privilege for trial_quota_reservations: zero write privileges for anon or authenticated
    REVOKE ALL ON public.trial_quota_reservations FROM anon;
    REVOKE ALL ON public.trial_quota_reservations FROM authenticated;
    GRANT SELECT ON public.trial_quota_reservations TO authenticated;
    """)

    cur.close()
    conn.close()
    print("[OK] Live PostgreSQL test database schema & roles successfully initialized!")


if __name__ == "__main__":
    init_test_schema()
