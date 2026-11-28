"""scripts/rehearse_migration_038_disposable.py
Disposable PostgreSQL Rollback & Recovery Rehearsal for Core SaaS Billing Contract v1.

Mandate:
- STRICT GUARDRAILS: Connects ONLY to local loopback PostgreSQL (127.0.0.1 / localhost).
  Strictly rejects Supabase Staging (xkhqirhurnjqglmajghn) and Production (mpluzajlzpregmjwpjqr).
- 5-Stage Lifecycle:
  1. PRE-APPLY: Establish baseline Core catalog (tenants, payment_intents, payment_outbox_events, roles).
  2. APPLY: Execute migrations/038_core_saas_billing_contract_v1.sql.
  3. VERIFY: Verify R1 (Tenant Isolation RLS) and R2 (Ledger Append-only & TRUNCATE protection).
  4. ROLLBACK: Execute migrations/038_core_saas_billing_contract_v1_rollback.sql and verify clean object teardown with zero damage to Core tables.
  5. RECOVERY: Re-apply Migration 038 to verify full recovery and idempotent re-application.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List
import uuid
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

_REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_038_FILE = _REPO_ROOT / "migrations" / "038_core_saas_billing_contract_v1.sql"
MIGRATION_038_ROLLBACK_FILE = _REPO_ROOT / "migrations" / "038_core_saas_billing_contract_v1_rollback.sql"

FORBIDDEN_MARKERS = ("xkhqirhurnjqglmajghn", "mpluzajlzpregmjwpjqr", "supabase.co", "pooler.supabase.com")
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")
DEFAULT_DISPOSABLE_DSN = os.getenv(
    "STAGE1_TEST_DISPOSABLE_PG_DSN",
    "postgresql://postgres@127.0.0.1:5433/postgres"
)
TARGET_DB_NAME = "bt_stage1_disposable_test_rehearsal_038"


def assert_safe_disposable_target(dsn: str) -> None:
    for marker in FORBIDDEN_MARKERS:
        if marker in dsn:
            raise RuntimeError(f"FATAL SECURITY VIOLATION: Forbidden marker '{marker}' found in target DSN!")
    # Check host
    import urllib.parse
    parsed = urllib.parse.urlparse(dsn)
    host = parsed.hostname or "127.0.0.1"
    if host.lower() not in ALLOWED_HOSTS:
        raise RuntimeError(f"FATAL SECURITY VIOLATION: Host '{host}' is not an authorized disposable loopback host!")


def ensure_disposable_postgres(dsn: str) -> bool:
    """Ensures local loopback postgres is responding on port 5433."""
    assert_safe_disposable_target(dsn)
    try:
        c = psycopg2.connect(dsn, connect_timeout=1)
        c.close()
        return True
    except Exception:
        pass

    import os
    import subprocess
    import time
    print("Starting ephemeral PostgreSQL 18 in WSL on port 5433...")
    start_cmd = [
        "wsl.exe", "-e", "/bin/su", "-s", "/bin/bash", "postgres", "-c",
        "mkdir -p /tmp/pg_disp_5433 && "
        "if [ ! -f /tmp/pg_disp_5433/PG_VERSION ]; then /usr/lib/postgresql/18/bin/initdb -D /tmp/pg_disp_5433 --auth=trust --no-sync; fi && "
        "/usr/lib/postgresql/18/bin/pg_ctl -D /tmp/pg_disp_5433 -l /tmp/pg_disp_5433/logfile -o '-p 5433 -h 0.0.0.0' start"
    ]
    try:
        with open(os.devnull, "r") as devnull:
            res = subprocess.run(start_cmd, stdin=devnull, capture_output=True, text=True, timeout=20)
        print("WSL start exit code:", res.returncode)
    except Exception as exc:
        print("Warning starting via WSL:", exc)

    # Wait up to 10 seconds for connection
    for _ in range(10):
        time.sleep(1)
        try:
            c = psycopg2.connect(dsn, connect_timeout=1)
            c.close()
            print("Successfully connected to ephemeral PostgreSQL 18 on 127.0.0.1:5433!")
            return True
        except Exception:
            continue
    raise RuntimeError("Failed to connect to ephemeral PostgreSQL 18 on port 5433!")


def get_admin_conn(dsn: str):
    assert_safe_disposable_target(dsn)
    conn = psycopg2.connect(dsn)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def get_db_conn(db_name: str, base_dsn: str):
    import urllib.parse
    parsed = urllib.parse.urlparse(base_dsn)
    target_dsn = f"{parsed.scheme}://{parsed.username or 'postgres'}{(':' + parsed.password) if parsed.password else ''}@{parsed.hostname or '127.0.0.1'}:{parsed.port or 5433}/{db_name}"
    assert_safe_disposable_target(target_dsn)
    return psycopg2.connect(target_dsn)


def run_stage_1_pre_apply(admin_dsn: str, target_db: str) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("STAGE 1: PRE-APPLY (Baseline Core Catalog Setup)")
    print("=" * 80)
    admin_conn = get_admin_conn(admin_dsn)
    with admin_conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {target_db};")
        cur.execute(f"CREATE DATABASE {target_db};")
    admin_conn.close()

    conn = get_db_conn(target_db, admin_dsn)
    with conn.cursor() as cur:
        # Bootstrap roles if not exist
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
        """)

        # Bootstrap Core Baseline tables
        cur.execute("""
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
                qr_string TEXT,
                qr_image_url TEXT,
                status VARCHAR(50) DEFAULT 'PENDING',
                idempotency_key VARCHAR(255),
                request_fingerprint VARCHAR(128),
                initiation_state VARCHAR(64) NOT NULL DEFAULT 'INITIATING',
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_payment_intent_tenant_order UNIQUE (tenant_id, order_id)
            );

            CREATE TABLE public.payment_outbox_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id VARCHAR(100) NOT NULL,
                event_type VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- Helper functions from Migration 027
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
            GRANT SELECT ON TABLE public.tenants TO authenticated, service_role;
        """)

        # Seed Core baseline data
        cur.execute("""
            INSERT INTO public.tenants (id, slug, name) VALUES
                ('11111111-1111-1111-1111-111111111111', 'onlineboost', 'PT OnlineBoost'),
                ('22222222-2222-2222-2222-222222222222', 'merchant-beta', 'Merchant Beta');

            INSERT INTO public.payment_intents (id, tenant_id, order_id, amount, total_amount, status) VALUES
                ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'onlineboost', 'ORD-CORE-001', 99000, 99000, 'PENDING');

            INSERT INTO public.payment_outbox_events (id, tenant_id, event_type, status) VALUES
                ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'onlineboost', 'PAYMENT_INITIATED', 'PENDING');
        """)
        conn.commit()

        # Verify 038 tables do not exist
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
        c_038 = cur.fetchone()[0]
        assert c_038 == 0, f"Expected 0 SaaS billing tables before apply, found {c_038}"

        cur.execute("SELECT count(*) FROM public.tenants;")
        tenants_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.payment_intents;")
        intents_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM public.payment_outbox_events;")
        outbox_count = cur.fetchone()[0]

    conn.close()
    res = {
        "status": "PASS",
        "tenants_count": tenants_count,
        "payment_intents_count": intents_count,
        "payment_outbox_count": outbox_count,
        "saas_billing_tables_count": c_038,
    }
    print("Stage 1 Pre-Apply OK:", res)
    return res


def run_stage_2_apply(target_db: str, admin_dsn: str) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("STAGE 2: APPLY (Execute Migration 038)")
    print("=" * 80)
    sql_text = MIGRATION_038_FILE.read_text(encoding="utf-8")
    conn = get_db_conn(target_db, admin_dsn)
    with conn.cursor() as cur:
        cur.execute(sql_text)
    conn.commit()

    with conn.cursor() as cur:
        # Check all 4 tables exist
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
              AND table_name IN (
                  'saas_billing_purchases',
                  'saas_billing_webhook_events',
                  'saas_billing_ledger_entries',
                  'saas_billing_entitlement_events'
              )
            ORDER BY table_name;
        """)
        created_tables = [r[0] for r in cur.fetchall()]
        assert len(created_tables) == 4, f"Expected 4 tables, got {created_tables}"

        # Check RLS enabled and forced
        cur.execute("""
            SELECT relname, relrowsecurity, relforcerowsecurity 
            FROM pg_class 
            WHERE relname IN (
                'saas_billing_purchases',
                'saas_billing_webhook_events',
                'saas_billing_ledger_entries',
                'saas_billing_entitlement_events'
            );
        """)
        rls_rows = cur.fetchall()
        for rname, rls, frls in rls_rows:
            assert rls is True, f"RLS not enabled on {rname}"
            assert frls is True, f"RLS not forced on {rname}"

        # Check Triggers on saas_billing_ledger_entries
        cur.execute("""
            SELECT tgname FROM pg_trigger 
            WHERE tgrelid = 'public.saas_billing_ledger_entries'::regclass
              AND tgname IN ('trg_saas_billing_ledger_no_update', 'trg_saas_billing_ledger_no_truncate');
        """)
        triggers = sorted([r[0] for r in cur.fetchall()])
        assert "trg_saas_billing_ledger_no_truncate" in triggers, "Missing truncate trigger"
        assert "trg_saas_billing_ledger_no_update" in triggers, "Missing mutation trigger"

        # Check Policies
        cur.execute("""
            SELECT tablename, policyname, roles, cmd 
            FROM pg_policies 
            WHERE schemaname = 'public' 
              AND tablename LIKE 'saas_billing_%'
            ORDER BY tablename, policyname;
        """)
        policies = cur.fetchall()

    conn.close()
    res = {
        "status": "PASS",
        "tables_created": created_tables,
        "rls_enforced_tables": [r[0] for r in rls_rows],
        "triggers_installed": triggers,
        "policy_count": len(policies),
    }
    print("Stage 2 Apply OK:", res)
    return res


def run_stage_3_verify(target_db: str, admin_dsn: str) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("STAGE 3: VERIFY (Audit Findings R1 & R2 Verification)")
    print("=" * 80)
    conn = get_db_conn(target_db, admin_dsn)
    
    TENANT_A_UUID = "11111111-1111-1111-1111-111111111111"
    TENANT_B_UUID = "22222222-2222-2222-2222-222222222222"
    INTENT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    
    PURCHASE_A_ID = str(uuid.uuid4())
    PURCHASE_B_ID = str(uuid.uuid4())
    
    results: Dict[str, Any] = {}

    with conn.cursor() as cur:
        # -------------------------------------------------------------
        # R1 Test 1: Positive matching tenant insert & query (Tenant A)
        # -------------------------------------------------------------
        cur.execute("SET LOCAL ROLE authenticated;")
        cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (TENANT_A_UUID,))
        cur.execute("""
            INSERT INTO public.saas_billing_purchases (
                id, canonical_tenant_id, product, request_reference, quote_id,
                catalog_version, request_fingerprint, idempotency_key, line_items,
                subtotal_idr, tax_policy_id, tax_amount_idr, total_idr,
                payment_intent_id, credential_profile_id
            ) VALUES (
                %s, %s, 'SHOP', 'ref-001', 'q-001',
                'v1', 'fp-001', 'idem-001', '[]'::jsonb,
                99000, 'TAX-1', 9900, 108900,
                %s, 'cred-001'
            );
        """, (PURCHASE_A_ID, TENANT_A_UUID, INTENT_UUID))
        
        cur.execute("SELECT count(*) FROM public.saas_billing_purchases WHERE id = %s;", (PURCHASE_A_ID,))
        cnt = cur.fetchone()[0]
        assert cnt == 1, "R1.1 FAIL: Matching tenant could not see inserted purchase"
        conn.commit()
        results["R1_1_positive_matching_tenant"] = "PASS (1 row inserted & queried)"

        # -------------------------------------------------------------
        # R1 Test 2: Negative missing/empty/NULL tenant context
        # -------------------------------------------------------------
        for empty_ctx in (None, "", "invalid-uuid-slug"):
            cur.execute("SET LOCAL ROLE authenticated;")
            if empty_ctx is None:
                cur.execute("SELECT set_config('app.current_tenant_id', NULL, true);")
            else:
                cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (empty_ctx,))
            
            # SELECT must return 0 rows
            cur.execute("SELECT count(*) FROM public.saas_billing_purchases;")
            cnt = cur.fetchone()[0]
            assert cnt == 0, f"R1.2 FAIL: Empty context '{empty_ctx}' leaked {cnt} rows"
            
            # INSERT must fail closed
            failed_closed = False
            cur.execute("SAVEPOINT sp_empty;")
            try:
                cur.execute("""
                    INSERT INTO public.saas_billing_purchases (
                        canonical_tenant_id, product, request_reference, quote_id,
                        catalog_version, request_fingerprint, idempotency_key, line_items,
                        subtotal_idr, tax_policy_id, tax_amount_idr, total_idr, credential_profile_id
                    ) VALUES (
                        %s, 'SHOP', 'ref-empty', 'q-empty', 'v1', 'fp-empty', %s, '[]'::jsonb,
                        99000, 'TAX-1', 9900, 108900, 'cred-001'
                    );
                """, (TENANT_A_UUID, str(uuid.uuid4())))
            except Exception:
                failed_closed = True
                cur.execute("ROLLBACK TO SAVEPOINT sp_empty;")
            assert failed_closed, f"R1.2 FAIL: Insert under empty context '{empty_ctx}' was not rejected"
        conn.commit()
        results["R1_2_negative_missing_context_rejected"] = "PASS (0 rows leaked, insert strictly rejected)"

        # -------------------------------------------------------------
        # R1 Test 3: Negative cross-tenant isolation (Tenant B cannot see Tenant A)
        # -------------------------------------------------------------
        cur.execute("SET LOCAL ROLE authenticated;")
        cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (TENANT_B_UUID,))
        cur.execute("SELECT count(*) FROM public.saas_billing_purchases WHERE canonical_tenant_id = %s;", (TENANT_A_UUID,))
        cnt = cur.fetchone()[0]
        assert cnt == 0, f"R1.3 FAIL: Cross-tenant data leak! Tenant B saw {cnt} rows of Tenant A"

        # Tenant B cannot insert row claiming to be Tenant A
        failed_closed = False
        cur.execute("SAVEPOINT sp_cross;")
        try:
            cur.execute("""
                INSERT INTO public.saas_billing_purchases (
                    canonical_tenant_id, product, request_reference, quote_id,
                    catalog_version, request_fingerprint, idempotency_key, line_items,
                    subtotal_idr, tax_policy_id, tax_amount_idr, total_idr, credential_profile_id
                ) VALUES (
                    %s, 'SHOP', 'ref-cross', 'q-cross', 'v1', 'fp-cross', %s, '[]'::jsonb,
                    99000, 'TAX-1', 9900, 108900, 'cred-001'
                );
            """, (TENANT_A_UUID, str(uuid.uuid4())))
        except Exception:
            failed_closed = True
            cur.execute("ROLLBACK TO SAVEPOINT sp_cross;")
        assert failed_closed, "R1.3 FAIL: Cross-tenant insert was not rejected"
        conn.commit()
        results["R1_3_negative_cross_tenant_isolation"] = "PASS (0 cross-tenant rows visible, spoofed insert rejected)"

        # -------------------------------------------------------------
        # R1 Test 4: Privileged service_role bypass
        # -------------------------------------------------------------
        cur.execute("SET LOCAL ROLE service_role;")
        cur.execute("SELECT set_config('app.current_tenant_id', NULL, true);")
        cur.execute("SELECT count(*) FROM public.saas_billing_purchases;")
        cnt = cur.fetchone()[0]
        assert cnt >= 1, "R1.4 FAIL: service_role could not query across tenants"
        results["R1_4_service_role_privileged_bypass"] = f"PASS (service_role can view all {cnt} rows without tenant context)"

        # -------------------------------------------------------------
        # R2 Test 1: TRUNCATE rejected on ledger entries
        # -------------------------------------------------------------
        # Insert a ledger entry first via service_role
        LEDGER_ENTRY_ID = str(uuid.uuid4())
        cur.execute("SET LOCAL ROLE service_role;")
        cur.execute("""
            INSERT INTO public.saas_billing_ledger_entries (
                id, canonical_tenant_id, purchase_id, payment_intent_id,
                product, sku, entry_kind, amount_idr, currency,
                provider, provider_event_id, catalog_version
            ) VALUES (
                %s, %s, %s, %s,
                'SHOP', 'SHOP_STARTER_GROWTH_BUNDLE', 'CHARGE', 99000, 'IDR',
                'XENDIT', 'evt-001', 'v1'
            );
        """, (LEDGER_ENTRY_ID, TENANT_A_UUID, PURCHASE_A_ID, INTENT_UUID))
        conn.commit()
        
        # 1a. Test TRUNCATE under authenticated (grant level)
        truncate_rejected_auth = False
        cur.execute("SET LOCAL ROLE authenticated;")
        cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (TENANT_A_UUID,))
        cur.execute("SAVEPOINT sp_tr_auth;")
        try:
            cur.execute("TRUNCATE TABLE public.saas_billing_ledger_entries;")
        except Exception as exc:
            truncate_rejected_auth = True
            cur.execute("ROLLBACK TO SAVEPOINT sp_tr_auth;")
        assert truncate_rejected_auth, "R2.1 FAIL: TRUNCATE on ledger entries was not rejected for authenticated!"
        
        # 1b. Test TRUNCATE under service_role (grant level revocation)
        truncate_rejected_service = False
        cur.execute("SET LOCAL ROLE service_role;")
        cur.execute("SAVEPOINT sp_tr_srv;")
        try:
            cur.execute("TRUNCATE TABLE public.saas_billing_ledger_entries;")
        except Exception as exc:
            truncate_rejected_service = True
            err_msg_srv = str(exc)
            cur.execute("ROLLBACK TO SAVEPOINT sp_tr_srv;")
        assert truncate_rejected_service, "R2.1 FAIL: TRUNCATE was not rejected for service_role!"

        # 1c. Test TRUNCATE under table owner (trigger level defense-in-depth)
        truncate_trigger_fired = False
        cur.execute("RESET ROLE;")
        cur.execute("SAVEPOINT sp_tr_owner;")
        try:
            cur.execute("TRUNCATE TABLE public.saas_billing_ledger_entries CASCADE;")
        except Exception as exc:
            truncate_trigger_fired = True
            err_msg_trigger = str(exc)
            cur.execute("ROLLBACK TO SAVEPOINT sp_tr_owner;")
        assert truncate_trigger_fired, "R2.1 FAIL: Statement trigger trg_saas_billing_ledger_no_truncate did not fire!"
        assert "SAAS_BILLING_LEDGER_APPEND_ONLY: truncate is strictly prohibited" in err_msg_trigger
        results["R2_1_truncate_protection"] = "PASS (TRUNCATE rejected by both grant revocation and statement trigger)"

        # -------------------------------------------------------------
        # R2 Test 2: UPDATE rejected on ledger entries
        # -------------------------------------------------------------
        # 2a. Test UPDATE under authenticated (grant level)
        update_rejected = False
        cur.execute("SET LOCAL ROLE authenticated;")
        cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (TENANT_A_UUID,))
        cur.execute("SAVEPOINT sp_upd_auth;")
        try:
            cur.execute("UPDATE public.saas_billing_ledger_entries SET amount_idr = 50000 WHERE id = %s;", (LEDGER_ENTRY_ID,))
        except Exception:
            update_rejected = True
            cur.execute("ROLLBACK TO SAVEPOINT sp_upd_auth;")
        assert update_rejected, "R2.2 FAIL: UPDATE on ledger entries was not rejected for authenticated!"

        # 2b. Test UPDATE under service_role (grant level revocation)
        update_srv_rejected = False
        cur.execute("SET LOCAL ROLE service_role;")
        cur.execute("SAVEPOINT sp_upd_srv;")
        try:
            cur.execute("UPDATE public.saas_billing_ledger_entries SET amount_idr = 50000 WHERE id = %s;", (LEDGER_ENTRY_ID,))
        except Exception as exc:
            update_srv_rejected = True
            cur.execute("ROLLBACK TO SAVEPOINT sp_upd_srv;")
        assert update_srv_rejected, "R2.2 FAIL: UPDATE on ledger entries was not rejected for service_role!"

        # 2c. Test UPDATE under table owner (row trigger level defense-in-depth)
        update_trigger_fired = False
        cur.execute("RESET ROLE;")
        cur.execute("SAVEPOINT sp_upd_owner;")
        try:
            cur.execute("UPDATE public.saas_billing_ledger_entries SET amount_idr = 50000 WHERE id = %s;", (LEDGER_ENTRY_ID,))
        except Exception as exc:
            update_trigger_fired = True
            err_msg = str(exc)
            cur.execute("ROLLBACK TO SAVEPOINT sp_upd_owner;")
        assert update_trigger_fired, "R2.2 FAIL: Row trigger did not reject UPDATE for owner"
        assert "SAAS_BILLING_LEDGER_APPEND_ONLY: use a compensating entry" in err_msg
        results["R2_2_update_protection"] = "PASS (UPDATE rejected by permission revocation and row trigger)"

        # -------------------------------------------------------------
        # R2 Test 3: DELETE rejected on ledger entries
        # -------------------------------------------------------------
        # 3a. Test DELETE under authenticated (grant level)
        delete_rejected = False
        cur.execute("SET LOCAL ROLE authenticated;")
        cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (TENANT_A_UUID,))
        cur.execute("SAVEPOINT sp_del_auth;")
        try:
            cur.execute("DELETE FROM public.saas_billing_ledger_entries WHERE id = %s;", (LEDGER_ENTRY_ID,))
        except Exception:
            delete_rejected = True
            cur.execute("ROLLBACK TO SAVEPOINT sp_del_auth;")
        assert delete_rejected, "R2.3 FAIL: DELETE on ledger entries was not rejected for authenticated!"

        # 3b. Test DELETE under service_role (grant level revocation)
        delete_srv_rejected = False
        cur.execute("SET LOCAL ROLE service_role;")
        cur.execute("SAVEPOINT sp_del_srv;")
        try:
            cur.execute("DELETE FROM public.saas_billing_ledger_entries WHERE id = %s;", (LEDGER_ENTRY_ID,))
        except Exception as exc:
            delete_srv_rejected = True
            cur.execute("ROLLBACK TO SAVEPOINT sp_del_srv;")
        assert delete_srv_rejected, "R2.3 FAIL: DELETE on ledger entries was not rejected for service_role!"

        # 3c. Test DELETE under table owner (row trigger level defense-in-depth)
        delete_trigger_fired = False
        cur.execute("RESET ROLE;")
        cur.execute("SAVEPOINT sp_del_owner;")
        try:
            cur.execute("DELETE FROM public.saas_billing_ledger_entries WHERE id = %s;", (LEDGER_ENTRY_ID,))
        except Exception as exc:
            delete_trigger_fired = True
            err_msg = str(exc)
            cur.execute("ROLLBACK TO SAVEPOINT sp_del_owner;")
        assert delete_trigger_fired, "R2.3 FAIL: Row trigger did not reject DELETE for owner"
        assert "SAAS_BILLING_LEDGER_APPEND_ONLY: use a compensating entry" in err_msg
        results["R2_3_delete_protection"] = "PASS (DELETE rejected by permission revocation and row trigger)"

    conn.close()
    print("Stage 3 Verify OK:", json.dumps(results, indent=2))
    return results


def run_stage_4_rollback(target_db: str, admin_dsn: str) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("STAGE 4: ROLLBACK (Execute Rollback 038 & Verify Core Table Preservation)")
    print("=" * 80)
    sql_text = MIGRATION_038_ROLLBACK_FILE.read_text(encoding="utf-8")
    conn = get_db_conn(target_db, admin_dsn)
    with conn.cursor() as cur:
        cur.execute(sql_text)
    conn.commit()

    with conn.cursor() as cur:
        # 1. Verify 038 tables are completely gone
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
        c_038 = cur.fetchone()[0]
        assert c_038 == 0, f"Expected 0 SaaS billing tables after rollback, found {c_038}"

        # 2. Verify 038 functions are dropped
        cur.execute("""
            SELECT count(*) FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = 'public'
              AND p.proname IN ('reject_saas_billing_ledger_mutation', 'reject_saas_billing_ledger_truncate');
        """)
        c_proc = cur.fetchone()[0]
        assert c_proc == 0, f"Expected 0 SaaS billing trigger functions after rollback, found {c_proc}"

        # 3. Verify Core tables are 100% INTACT with all rows
        cur.execute("SELECT count(*) FROM public.tenants;")
        tenants_count = cur.fetchone()[0]
        assert tenants_count == 2, f"Core tenants modified! Expected 2, got {tenants_count}"

        cur.execute("SELECT count(*) FROM public.payment_intents;")
        intents_count = cur.fetchone()[0]
        assert intents_count == 1, f"Core payment_intents modified! Expected 1, got {intents_count}"

        cur.execute("SELECT count(*) FROM public.payment_outbox_events;")
        outbox_count = cur.fetchone()[0]
        assert outbox_count == 1, f"Core payment_outbox_events modified! Expected 1, got {outbox_count}"

        # 4. Verify helper functions still exist and work
        cur.execute("SELECT public.try_cast_uuid('11111111-1111-1111-1111-111111111111');")
        casted = cur.fetchone()[0]
        assert str(casted) == "11111111-1111-1111-1111-111111111111"

    conn.close()
    res = {
        "status": "PASS",
        "saas_billing_tables_remaining": c_038,
        "saas_billing_functions_remaining": c_proc,
        "core_tenants_preserved": tenants_count,
        "core_payment_intents_preserved": intents_count,
        "core_payment_outbox_preserved": outbox_count,
    }
    print("Stage 4 Rollback OK:", res)
    return res


def run_stage_5_recovery(target_db: str, admin_dsn: str) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print("STAGE 5: RECOVERY (Re-apply Migration 038 & Verify Idempotency)")
    print("=" * 80)
    # Re-apply 038
    sql_text = MIGRATION_038_FILE.read_text(encoding="utf-8")
    conn = get_db_conn(target_db, admin_dsn)
    with conn.cursor() as cur:
        cur.execute(sql_text)
    conn.commit()

    with conn.cursor() as cur:
        # Check all 4 tables exist again
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
        c_038 = cur.fetchone()[0]
        assert c_038 == 4, f"Expected 4 restored SaaS billing tables, found {c_038}"

        # Verify Core tables still intact
        cur.execute("SELECT count(*) FROM public.tenants;")
        tenants_count = cur.fetchone()[0]
        assert tenants_count == 2

        cur.execute("SELECT count(*) FROM public.payment_intents;")
        intents_count = cur.fetchone()[0]
        assert intents_count == 1

        cur.execute("SELECT count(*) FROM public.payment_outbox_events;")
        outbox_count = cur.fetchone()[0]
        assert outbox_count == 1

    conn.close()
    res = {
        "status": "PASS",
        "saas_billing_tables_recovered": c_038,
        "core_tenants_preserved": tenants_count,
        "core_payment_intents_preserved": intents_count,
        "core_payment_outbox_preserved": outbox_count,
    }
    print("Stage 5 Recovery OK:", res)
    return res


def main():
    dsn = DEFAULT_DISPOSABLE_DSN
    print(f"Executing disposable rehearsal on target DSN (port 5433 loopback)...")
    assert_safe_disposable_target(dsn)
    ensure_disposable_postgres(dsn)

    s1 = run_stage_1_pre_apply(dsn, TARGET_DB_NAME)
    s2 = run_stage_2_apply(TARGET_DB_NAME, dsn)
    s3 = run_stage_3_verify(TARGET_DB_NAME, dsn)
    s4 = run_stage_4_rollback(TARGET_DB_NAME, dsn)
    s5 = run_stage_5_recovery(TARGET_DB_NAME, dsn)

    print("\n" + "=" * 80)
    print("ALL 5 REHEARSAL STAGES COMPLETED SUCCESSFULLY WITH 100% PASS RATE")
    print("=" * 80)


if __name__ == "__main__":
    main()
