"""tests/test_migration_038_gate3_rls_and_rollback.py
Unit and integration tests for Gate #3:
- R1: Tenant Isolation Policies (positive matching, missing context, cross-tenant isolation, service_role bypass)
- R2: Immutable Ledger (least-privilege grants, truncate protection, update/delete rejection)
- R3: Rollback & Recovery Rehearsal (clean table drop, core tables preservation)
"""

from __future__ import annotations

import os
from pathlib import Path
import unittest
import uuid
import psycopg2

_REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_038_FILE = _REPO_ROOT / "migrations" / "038_core_saas_billing_contract_v1.sql"
MIGRATION_038_ROLLBACK_FILE = _REPO_ROOT / "migrations" / "038_core_saas_billing_contract_v1_rollback.sql"

LOCAL_DISPOSABLE_DSN = "postgresql://postgres@127.0.0.1:5433/postgres"
raw_env_dsn = os.getenv("STAGE1_TEST_DISPOSABLE_PG_DSN", "")
if not raw_env_dsn or "test-postgres" in raw_env_dsn:
    DISPOSABLE_PG_DSN = LOCAL_DISPOSABLE_DSN
else:
    DISPOSABLE_PG_DSN = raw_env_dsn
TEST_DB_NAME = "bt_stage1_disposable_test_gate3_suite"


def _is_pg_available() -> bool:
    try:
        from scripts.rehearse_migration_038_disposable import ensure_disposable_postgres
        return ensure_disposable_postgres(DISPOSABLE_PG_DSN)
    except Exception:
        try:
            conn = psycopg2.connect(DISPOSABLE_PG_DSN, connect_timeout=1)
            conn.close()
            return True
        except Exception:
            return False


@unittest.skipUnless(_is_pg_available(), "Local disposable PostgreSQL (port 5433) is not available")
class TestMigration038Gate3SecurityAndRollback(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Create test database
        admin_conn = psycopg2.connect(DISPOSABLE_PG_DSN)
        admin_conn.autocommit = True
        with admin_conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME};")
            cur.execute(f"CREATE DATABASE {TEST_DB_NAME};")
        admin_conn.close()

        # Connect to test db and setup baseline
        import urllib.parse
        parsed = urllib.parse.urlparse(DISPOSABLE_PG_DSN)
        cls.target_dsn = f"{parsed.scheme}://{parsed.username or 'postgres'}{(':' + parsed.password) if parsed.password else ''}@{parsed.hostname or '127.0.0.1'}:{parsed.port or 5433}/{TEST_DB_NAME}"
        
        conn = psycopg2.connect(cls.target_dsn)
        with conn.cursor() as cur:
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                        CREATE ROLE authenticated NOLOGIN;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                        CREATE ROLE service_role NOLOGIN;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                        CREATE ROLE anon NOLOGIN;
                    END IF;
                END;
                $$;

                CREATE EXTENSION IF NOT EXISTS "pgcrypto";

                CREATE TABLE public.tenants (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    slug VARCHAR(100) NOT NULL UNIQUE,
                    name VARCHAR(255) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT true,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE public.payment_intents (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id VARCHAR(100) NOT NULL,
                    order_id VARCHAR(150) NOT NULL,
                    amount BIGINT NOT NULL,
                    unique_code INT NOT NULL DEFAULT 0,
                    total_amount BIGINT NOT NULL,
                    status VARCHAR(50) DEFAULT 'PENDING',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_payment_intent_tenant_order UNIQUE (tenant_id, order_id)
                );

                CREATE TABLE public.payment_outbox_events (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id VARCHAR(100) NOT NULL,
                    event_type VARCHAR(64) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE OR REPLACE FUNCTION public.try_cast_uuid(p_val text)
                RETURNS uuid LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
                BEGIN
                    IF p_val IS NULL OR p_val = '' THEN RETURN NULL; END IF;
                    IF p_val ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
                        RETURN p_val::uuid;
                    END IF;
                    RETURN NULL;
                EXCEPTION WHEN others THEN RETURN NULL; END;
                $$;

                CREATE OR REPLACE FUNCTION public.current_app_tenant_uuid()
                RETURNS uuid LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
                DECLARE v_val text;
                BEGIN
                    v_val := NULLIF(current_setting('app.current_tenant_id', true), '');
                    IF v_val IS NULL THEN RETURN NULL; END IF;
                    IF v_val ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
                        RETURN v_val::uuid;
                    END IF;
                    RETURN (SELECT id FROM public.tenants WHERE slug = v_val LIMIT 1);
                EXCEPTION WHEN others THEN RETURN NULL; END;
                $$;

                GRANT USAGE ON SCHEMA public TO authenticated, anon, service_role;
                GRANT ALL ON TABLE public.tenants TO authenticated, service_role;
                GRANT ALL ON TABLE public.payment_intents TO authenticated, service_role;
                GRANT ALL ON TABLE public.payment_outbox_events TO authenticated, service_role;

                INSERT INTO public.tenants (id, slug, name) VALUES
                    ('11111111-1111-1111-1111-111111111111', 'onlineboost', 'PT OnlineBoost'),
                    ('22222222-2222-2222-2222-222222222222', 'merchant-beta', 'Merchant Beta');

                INSERT INTO public.payment_intents (id, tenant_id, order_id, amount, total_amount, status) VALUES
                    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'onlineboost', 'ORD-CORE-001', 99000, 99000, 'PENDING');
            """)
            # Apply 038
            cur.execute(MIGRATION_038_FILE.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()

    def setUp(self) -> None:
        self.conn = psycopg2.connect(self.target_dsn)
        self.tenant_a = "11111111-1111-1111-1111-111111111111"
        self.tenant_b = "22222222-2222-2222-2222-222222222222"
        self.intent_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    def tearDown(self) -> None:
        self.conn.close()

    def test_r1_positive_matching_tenant_access(self) -> None:
        purchase_id = str(uuid.uuid4())
        with self.conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (self.tenant_a,))
            cur.execute("""
                INSERT INTO public.saas_billing_purchases (
                    id, canonical_tenant_id, product, request_reference, quote_id,
                    catalog_version, request_fingerprint, idempotency_key, line_items,
                    subtotal_idr, tax_policy_id, tax_amount_idr, total_idr,
                    payment_intent_id, credential_profile_id
                ) VALUES (
                    %s, %s, 'SHOP', 'ref-r1-pos', 'q-r1-pos',
                    'v1', 'fp-r1', %s, '[]'::jsonb,
                    99000, 'TAX-1', 9900, 108900,
                    %s, 'cred-001'
                );
            """, (purchase_id, self.tenant_a, str(uuid.uuid4()), self.intent_id))
            
            cur.execute("SELECT count(*) FROM public.saas_billing_purchases WHERE id = %s;", (purchase_id,))
            self.assertEqual(cur.fetchone()[0], 1)
        self.conn.commit()

    def test_r1_negative_missing_or_invalid_tenant_context(self) -> None:
        with self.conn.cursor() as cur:
            for bad_ctx in (None, "", "malicious' OR '1'='1"):
                cur.execute("SET LOCAL ROLE authenticated;")
                if bad_ctx is None:
                    cur.execute("SELECT set_config('app.current_tenant_id', NULL, true);")
                else:
                    cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (bad_ctx,))
                
                cur.execute("SELECT count(*) FROM public.saas_billing_purchases;")
                self.assertEqual(cur.fetchone()[0], 0, f"Leaked rows with context: {bad_ctx}")

    def test_r1_negative_cross_tenant_isolation(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (self.tenant_b,))
            cur.execute("SELECT count(*) FROM public.saas_billing_purchases WHERE canonical_tenant_id = %s;", (self.tenant_a,))
            self.assertEqual(cur.fetchone()[0], 0, "Tenant B saw Tenant A data!")

            with self.assertRaises(psycopg2.Error):
                cur.execute("""
                    INSERT INTO public.saas_billing_purchases (
                        canonical_tenant_id, product, request_reference, quote_id,
                        catalog_version, request_fingerprint, idempotency_key, line_items,
                        subtotal_idr, tax_policy_id, tax_amount_idr, total_idr, credential_profile_id
                    ) VALUES (
                        %s, 'SHOP', 'cross-ref', 'q-cross', 'v1', 'fp-cross', %s, '[]'::jsonb,
                        99000, 'TAX-1', 9900, 108900, 'cred-001'
                    );
                """, (self.tenant_a, str(uuid.uuid4())))
            self.conn.rollback()

    def test_r1_service_role_privileged_bypass(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE service_role;")
            cur.execute("SELECT set_config('app.current_tenant_id', NULL, true);")
            cur.execute("SELECT count(*) FROM public.saas_billing_purchases;")
            self.assertGreaterEqual(cur.fetchone()[0], 1)

    def test_r2_ledger_truncate_strictly_prohibited(self) -> None:
        with self.conn.cursor() as cur:
            # 1. authenticated role (grant check)
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (self.tenant_a,))
            with self.assertRaises(psycopg2.Error):
                cur.execute("TRUNCATE TABLE public.saas_billing_ledger_entries;")
            self.conn.rollback()

            # 2. service_role (grant check)
            cur.execute("SET LOCAL ROLE service_role;")
            with self.assertRaises(psycopg2.Error):
                cur.execute("TRUNCATE TABLE public.saas_billing_ledger_entries;")
            self.conn.rollback()

            # 3. owner CASCADE (trigger check)
            cur.execute("RESET ROLE;")
            with self.assertRaises(psycopg2.Error) as ctx:
                cur.execute("TRUNCATE TABLE public.saas_billing_ledger_entries CASCADE;")
            err = str(ctx.exception)
            self.assertIn("SAAS_BILLING_LEDGER_APPEND_ONLY: truncate is strictly prohibited", err)
            self.conn.rollback()

    def test_r2_ledger_update_and_delete_strictly_prohibited(self) -> None:
        # Create a ledger row via service_role
        ledger_id = str(uuid.uuid4())
        purchase_id = str(uuid.uuid4())
        test_intent_id = str(uuid.uuid4())
        with self.conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE service_role;")
            cur.execute("""
                INSERT INTO public.payment_intents (id, tenant_id, order_id, amount, total_amount, status)
                VALUES (%s, 'onlineboost', %s, 99000, 99000, 'PENDING');
            """, (test_intent_id, f"ORD-TEST-{uuid.uuid4().hex[:8]}"))
            cur.execute("""
                INSERT INTO public.saas_billing_purchases (
                    id, canonical_tenant_id, product, request_reference, quote_id,
                    catalog_version, request_fingerprint, idempotency_key, line_items,
                    subtotal_idr, tax_policy_id, tax_amount_idr, total_idr,
                    payment_intent_id, credential_profile_id
                ) VALUES (
                    %s, %s, 'SHOP', 'ref-led', 'q-led',
                    'v1', 'fp-led', %s, '[]'::jsonb,
                    99000, 'TAX-1', 9900, 108900,
                    %s, 'cred-001'
                );
            """, (purchase_id, self.tenant_a, str(uuid.uuid4()), test_intent_id))
            
            cur.execute("""
                INSERT INTO public.saas_billing_ledger_entries (
                    id, canonical_tenant_id, purchase_id, payment_intent_id,
                    product, sku, entry_kind, amount_idr, currency,
                    provider, provider_event_id, catalog_version
                ) VALUES (
                    %s, %s, %s, %s,
                    'SHOP', 'SHOP_STARTER_GROWTH_BUNDLE', 'CHARGE', 99000, 'IDR',
                    'XENDIT', %s, 'v1'
                );
            """, (ledger_id, self.tenant_a, purchase_id, test_intent_id, str(uuid.uuid4())))
        self.conn.commit()

        with self.conn.cursor() as cur:
            # UPDATE attempt
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (self.tenant_a,))
            with self.assertRaises(psycopg2.Error):
                cur.execute("UPDATE public.saas_billing_ledger_entries SET amount_idr = 1000 WHERE id = %s;", (ledger_id,))
            self.conn.rollback()

            # DELETE attempt
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (self.tenant_a,))
            with self.assertRaises(psycopg2.Error):
                cur.execute("DELETE FROM public.saas_billing_ledger_entries WHERE id = %s;", (ledger_id,))
            self.conn.rollback()

    def test_r3_rollback_preserves_core_and_drops_038(self) -> None:
        # Run rollback
        with self.conn.cursor() as cur:
            cur.execute(MIGRATION_038_ROLLBACK_FILE.read_text(encoding="utf-8"))
        self.conn.commit()

        with self.conn.cursor() as cur:
            # 038 tables must be gone
            cur.execute("""
                SELECT count(*) FROM information_schema.tables 
                WHERE table_schema = 'public' 
                  AND table_name IN (
                      'saas_billing_purchases',
                      'saas_billing_webhook_events',
                      'saas_billing_ledger_entries',
                      'saas_billing_entitlement_events'
                  );
            """)
            self.assertEqual(cur.fetchone()[0], 0)

            # Core tables must be intact
            cur.execute("SELECT count(*) FROM public.tenants;")
            self.assertEqual(cur.fetchone()[0], 2)
            cur.execute("SELECT count(*) FROM public.payment_intents;")
            self.assertGreaterEqual(cur.fetchone()[0], 1)

        # Re-apply to leave test db clean
        with self.conn.cursor() as cur:
            cur.execute(MIGRATION_038_FILE.read_text(encoding="utf-8"))
        self.conn.commit()


if __name__ == "__main__":
    unittest.main()
