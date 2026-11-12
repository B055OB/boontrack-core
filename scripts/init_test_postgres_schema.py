"""scripts/init_test_postgres_schema.py
Initializes PostgreSQL test database roles and schema for CTO P1 compliance.
Ensures roles 'anon', 'authenticated', 'service_role' exist with non-superuser / non-bypass privileges,
creates helper functions, tables, views, and strict RLS policies for 100% CI database isolation.
"""

import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security.test_isolation_guard import (
    assert_disposable_postgres_target,
    bootstrap_isolated_test_env,
    is_strict_test_guard_active,
    safe_load_dotenv,
    verify_connected_postgres_is_disposable,
)

if is_strict_test_guard_active():
    bootstrap_isolated_test_env()
else:
    safe_load_dotenv()

# Synchronize environment variables and settings cleanly with CI or local disposable test DB
_db_url = os.getenv("DATABASE_URL", "").strip()
if _db_url:
    assert_disposable_postgres_target(dsn=_db_url, allow_if_unconfigured=False)
    _u = urlparse(_db_url)
    if _u.hostname and not os.getenv("POSTGRES_HOST"):
        os.environ["POSTGRES_HOST"] = _u.hostname
    if _u.port and not os.getenv("POSTGRES_PORT"):
        os.environ["POSTGRES_PORT"] = str(_u.port)
    if _u.path and _u.path.lstrip("/") and not os.getenv("POSTGRES_DB"):
        os.environ["POSTGRES_DB"] = _u.path.lstrip("/")
    if _u.username and not os.getenv("POSTGRES_USER"):
        os.environ["POSTGRES_USER"] = _u.username
    if _u.password and not os.getenv("POSTGRES_PASSWORD"):
        os.environ["POSTGRES_PASSWORD"] = _u.password
else:
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
    assert_disposable_postgres_target(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        allow_if_unconfigured=False,
    )

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
    assert_disposable_postgres_target(
        dsn=os.getenv("DATABASE_URL") or None,
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        allow_if_unconfigured=False,
    )
    conn = get_db_connection()
    verify_connected_postgres_is_disposable(conn)
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
    CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_ledger_order_credit
      ON public.financial_ledger (order_id)
      WHERE (transaction_type = 'PAYMENT_CREDIT');
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

    -- Table: checkout_sessions (Migration 035: Durable Checkout Sessions & Unique-Code Lock)
    CREATE TABLE IF NOT EXISTS public.checkout_sessions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      order_id VARCHAR(128) NOT NULL UNIQUE REFERENCES public.orders(id) ON DELETE CASCADE,
      tenant_id VARCHAR(100) NOT NULL,
      canonical_tenant_id VARCHAR(100) NOT NULL,
      tenant_slug VARCHAR(128) NOT NULL,
      sku_id VARCHAR(255) NOT NULL,
      base_amount BIGINT NOT NULL,
      unique_code INT NOT NULL DEFAULT 0,
      total_amount BIGINT NOT NULL,
      qr_string TEXT NOT NULL,
      session_state VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
      jti VARCHAR(128) NOT NULL,
      cs_key_id VARCHAR(64) NOT NULL,
      iat_epoch BIGINT NOT NULL,
      exp_epoch BIGINT NOT NULL,
      revoked BOOLEAN NOT NULL DEFAULT FALSE,
      revoked_at TIMESTAMPTZ,
      revocation_reason VARCHAR(255),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      expires_at TIMESTAMPTZ NOT NULL,
      settled_at TIMESTAMPTZ,
      CONSTRAINT uq_checkout_sessions_jti UNIQUE (jti),
      CONSTRAINT chk_checkout_sessions_non_blank CHECK (
        BTRIM(order_id) <> ''
        AND BTRIM(tenant_id) <> ''
        AND BTRIM(canonical_tenant_id) <> ''
        AND BTRIM(tenant_slug) <> ''
        AND BTRIM(sku_id) <> ''
        AND BTRIM(jti) <> ''
        AND BTRIM(cs_key_id) <> ''
      ),
      CONSTRAINT chk_checkout_sessions_amounts CHECK (
        base_amount >= 0
        AND total_amount > 0
        AND total_amount = base_amount + unique_code
      ),
      CONSTRAINT chk_checkout_sessions_unique_code CHECK (
        unique_code = 0 OR (unique_code >= 100 AND unique_code <= 999)
      ),
      CONSTRAINT chk_checkout_sessions_state CHECK (
        session_state IN ('ACTIVE', 'SETTLED', 'EXPIRED', 'REVOKED', 'CANCELLED')
      ),
      CONSTRAINT chk_checkout_sessions_epoch_bounds CHECK (
        iat_epoch > 0 AND exp_epoch >= iat_epoch
      )
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_checkout_sessions_active_unique_amount
      ON public.checkout_sessions (tenant_id, base_amount, unique_code)
      WHERE (session_state = 'ACTIVE' AND revoked = FALSE AND unique_code > 0);
    CREATE INDEX IF NOT EXISTS idx_checkout_sessions_total_amount_active
      ON public.checkout_sessions (total_amount, created_at DESC)
      WHERE (session_state = 'ACTIVE' AND revoked = FALSE);
    CREATE INDEX IF NOT EXISTS idx_checkout_sessions_tenant_state_expires
      ON public.checkout_sessions (tenant_id, session_state, expires_at);
    ALTER TABLE public.checkout_sessions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.checkout_sessions FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS p1_tenant_isolation_checkout_sessions ON public.checkout_sessions;
    CREATE POLICY p1_tenant_isolation_checkout_sessions ON public.checkout_sessions
      AS PERMISSIVE FOR SELECT TO authenticated
      USING (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NOT NULL
        AND (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
          OR canonical_tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
          OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
          OR (
            current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            AND canonical_tenant_id = LOWER(current_setting('app.current_tenant_id', true))
          )
        )
      );
    DROP POLICY IF EXISTS service_role_all_checkout_sessions ON public.checkout_sessions;
    CREATE POLICY service_role_all_checkout_sessions ON public.checkout_sessions
      AS PERMISSIVE FOR ALL TO service_role
      USING (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR canonical_tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR (
          current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
          AND canonical_tenant_id = LOWER(current_setting('app.current_tenant_id', true))
        )
      )
      WITH CHECK (
        NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
        OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR canonical_tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR tenant_slug = NULLIF(current_setting('app.current_tenant_id', true), '')
        OR (
          current_setting('app.current_tenant_id', true) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
          AND canonical_tenant_id = LOWER(current_setting('app.current_tenant_id', true))
        )
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

    -- Table: inbound_webhook_events (Durable idempotency; zero tenant_id -> ENABLE RLS DEFAULT DENY, owner-only writes)
    CREATE TABLE IF NOT EXISTS public.inbound_webhook_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      channel_provider VARCHAR(50) NOT NULL DEFAULT 'whatsapp_meta',
      provider_message_id VARCHAR(255) NOT NULL,
      payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      status VARCHAR(50) NOT NULL DEFAULT 'RECEIVED',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      CONSTRAINT uq_inbound_webhook_channel_provider_msg_id UNIQUE (channel_provider, provider_message_id)
    );
    CREATE INDEX IF NOT EXISTS idx_inbound_webhook_provider_msg_id ON public.inbound_webhook_events(provider_message_id);
    CREATE INDEX IF NOT EXISTS idx_inbound_webhook_created_at ON public.inbound_webhook_events(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_inbound_webhook_status ON public.inbound_webhook_events(status);
    ALTER TABLE public.inbound_webhook_events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.inbound_webhook_events NO FORCE ROW LEVEL SECURITY;

    -- Table: phone_suppressions (Tenant opt-out registry with strict dual-resolution + FORCE RLS)
    CREATE TABLE IF NOT EXISTS public.phone_suppressions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id VARCHAR(100) NOT NULL,
      phone_number VARCHAR(50) NOT NULL,
      reason TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      CONSTRAINT phone_suppressions_tenant_phone_key UNIQUE (tenant_id, phone_number)
    );
    CREATE INDEX IF NOT EXISTS idx_phone_suppressions_tenant_phone ON public.phone_suppressions(tenant_id, phone_number);
    ALTER TABLE public.phone_suppressions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.phone_suppressions FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation_phone_suppressions ON public.phone_suppressions;
    CREATE POLICY tenant_isolation_phone_suppressions ON public.phone_suppressions
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      )
      WITH CHECK (
        tenant_id = public.current_app_tenant_slug()
        OR tenant_id = public.try_cast_uuid(current_setting('app.current_tenant_id', true))::text
      );
    DROP POLICY IF EXISTS service_role_all_phone_suppressions ON public.phone_suppressions;
    CREATE POLICY service_role_all_phone_suppressions ON public.phone_suppressions
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

    -- Strict least privilege for trial_quota_reservations & checkout_sessions: zero write privileges for anon or authenticated
    REVOKE ALL ON public.trial_quota_reservations FROM anon;
    REVOKE ALL ON public.trial_quota_reservations FROM authenticated;
    GRANT SELECT ON public.trial_quota_reservations TO authenticated;

    REVOKE ALL ON public.checkout_sessions FROM PUBLIC;
    REVOKE ALL ON public.checkout_sessions FROM anon;
    REVOKE ALL ON public.checkout_sessions FROM authenticated;
    GRANT SELECT ON public.checkout_sessions TO authenticated;
    GRANT ALL ON public.checkout_sessions TO service_role;
    """)

    cur.close()
    conn.close()
    print("[OK] Live PostgreSQL test database schema & roles successfully initialized!")


if __name__ == "__main__":
    init_test_schema()
