#!/usr/bin/env python3
"""scripts/rehearse_shared_db_migrations_pg17.py
================================================================================
GERBANG B — PACKET 2B (TRACK A.2): SHARED-DB PG 17 MIGRATION RECONCILIATION
& CLEAN-REPLAY ASSERTION HARNESS (C-01..C-08)
================================================================================
Executes a deterministic CLEAN EMPTY DATABASE REPLAY of Core + Inbox migrations
plus additive reconciliation candidates (`migrations/reconciliation/`) against a
strictly LOCAL DISPOSABLE PostgreSQL 17 container (`127.0.0.1` / `localhost`).

FAIL-CLOSED SAFETY GUARDRAILS:
- Refuses any non-local host or forbidden cloud/Supabase/Railway marker.
- Never modifies canonical historical migration files in Core or Inbox.
- Verifies ZERO SQL errors across all replayed migrations.
- Runs runtime SQL assertions proving C-01 through C-08 PASS.
================================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import psycopg2

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "migrations" / "reconciliation" / "shared_db_migration_manifest.json"
DEFAULT_INBOX_MIGRATIONS_DIR = Path(r"C:\boontrack-inbox-gateb-p2\supabase\migrations")

FORBIDDEN_MARKERS = (
    "mpluzajlzpregmjwpjqr",
    "xkhqirhurnjqglmajghn",
    "tjkbgxrckaocgosvmzmj",
    ".supabase.co",
    ".supabase.com",
    "pooler.supabase.com",
    "railway.app",
    "rlwy.net",
)
ALLOWED_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def assert_disposable_local_dsn(dsn: str) -> None:
    lower = dsn.lower()
    for marker in FORBIDDEN_MARKERS:
        if marker in lower:
            raise RuntimeError(f"[FAIL-CLOSED] Refusing forbidden remote DB marker '{marker}' in DSN.")
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_LOCAL_HOSTS:
        raise RuntimeError(f"[FAIL-CLOSED] Refusing non-local PostgreSQL host '{host}'. Allowed: {sorted(ALLOWED_LOCAL_HOSTS)}.")


def load_manifest() -> Dict[str, Any]:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_migration_path(entry: Dict[str, str], inbox_dir: Path) -> Path:
    repo = entry["repo"]
    fname = entry["file"]
    if repo == "core":
        return REPO_ROOT / "migrations" / fname
    if repo == "reconciliation":
        return REPO_ROOT / "migrations" / "reconciliation" / fname
    if repo == "inbox":
        return inbox_dir / fname
    raise ValueError(f"Unknown manifest repo key: {repo}")


def print_ordering_comparison(manifest: Dict[str, Any], inbox_dir: Path) -> None:
    print("=" * 88)
    print("SHARED-DB MIGRATION ORDERING COMPARISON (BEFORE vs AFTER RECONCILIATION MANIFEST)")
    print("=" * 88)
    print("\n[BEFORE — NAIVE / UNRECONCILED REPLAY HAZARDS]")
    for item in manifest["before_naive_order_hazards"]:
        print(f"  - {item}")

    print("\n[AFTER — DETERMINISTIC RECONCILED MANIFEST EXECUTION PLAN]")
    step_idx = 0
    for phase in manifest["after_reconciled_phases"]:
        print(f"\n  Phase: {phase['phase']} — {phase['description']}")
        for entry in phase["entries"]:
            step_idx += 1
            note = ""
            if "replaces_inbox" in entry:
                note = f" (replaces inbox/{entry['replaces_inbox']})"
            elif "replaces_core" in entry:
                note = f" (replaces core/{entry['replaces_core']})"
            print(f"    {step_idx:03d}. [{entry['repo']:<14}] {entry['file']}{note}")

    # Verify 100% coverage of all non-rollback Core & Inbox SQL files
    core_files = sorted(
        p.name for p in (REPO_ROOT / "migrations").glob("*.sql")
        if "rollback" not in p.name.lower()
    )
    inbox_files = sorted(p.name for p in inbox_dir.glob("*.sql"))

    manifest_core = {
        e["file"]
        for p in manifest["after_reconciled_phases"]
        for e in p["entries"]
        if e["repo"] == "core"
    }
    replaced_core = {
        e["replaces_core"]
        for p in manifest["after_reconciled_phases"]
        for e in p["entries"]
        if "replaces_core" in e
    }
    manifest_inbox = {
        e["file"]
        for p in manifest["after_reconciled_phases"]
        for e in p["entries"]
        if e["repo"] == "inbox"
    }
    replaced_inbox = {
        e["replaces_inbox"]
        for p in manifest["after_reconciled_phases"]
        for e in p["entries"]
        if "replaces_inbox" in e
    }

    missing_core = sorted(set(core_files) - (manifest_core | replaced_core))
    missing_inbox = sorted(set(inbox_files) - (manifest_inbox | replaced_inbox))
    print(f"\n[COVERAGE CHECK] Core SQL files accounted for: {len(manifest_core | replaced_core)}/{len(core_files)} | "
          f"Inbox SQL files accounted for: {len(manifest_inbox | replaced_inbox)}/{len(inbox_files)}")
    if missing_core or missing_inbox:
        raise RuntimeError(
            f"[COVERAGE FAILURE] Unaccounted migrations! missing_core={missing_core}, missing_inbox={missing_inbox}"
        )


def reset_clean_database(dsn: str) -> None:
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("DROP SCHEMA IF EXISTS auth CASCADE;")
            cur.execute("DROP SCHEMA IF EXISTS control_plane CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER;")
            cur.execute("GRANT USAGE ON SCHEMA public TO PUBLIC;")
    finally:
        conn.close()


def execute_sql_file(dsn: str, sql_path: Path) -> None:
    sql_text = sql_path.read_text(encoding="utf-8")
    if not sql_text.strip():
        return
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql_text)
    finally:
        conn.close()


def run_c01_to_c08_assertions(dsn: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    print("\n" + "=" * 88)
    print("RUNTIME SQL ASSERTIONS (C-01 .. C-08)")
    print("=" * 88)
    results: Dict[str, Any] = {}
    conn = psycopg2.connect(dsn)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # -----------------------------------------------------------------
            # C-01: payment_events PG 17 valid policies + Core 033a-033c contract
            # -----------------------------------------------------------------
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'payment_events'
                  AND column_name IN ('event_id', 'provider_event_id', 'order_id', 'tenant_id', 's2s_verification_status', 'record_classification');
            """)
            pe_cols = dict(cur.fetchall())
            for req_col in ("event_id", "provider_event_id", "order_id", "tenant_id", "s2s_verification_status", "record_classification"):
                assert req_col in pe_cols, f"C-01 missing column payment_events.{req_col}"
            assert pe_cols["tenant_id"] == "character varying", f"C-01 tenant_id type mismatch: {pe_cols['tenant_id']}"
            assert pe_cols["order_id"] == "character varying", f"C-01 order_id type mismatch: {pe_cols['order_id']}"

            cur.execute("""
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'public.payment_events'::regclass
                  AND conname IN ('uq_payment_events_provider_event_id', 'uq_payment_events_provider_provider_event_id');
            """)
            pe_cons = {r[0] for r in cur.fetchall()}
            assert pe_cons == {"uq_payment_events_provider_event_id", "uq_payment_events_provider_provider_event_id"}, f"C-01 missing constraints: {pe_cons}"

            # Insert a live Stage 3 payment_event and verify append-only DELETE protection
            pe_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO public.payment_events (id, provider, event_id, provider_event_id, order_id, tenant_id, event_type, amount, status)
                VALUES (%s, 'XENDIT', %s, %s, 'ord-c01-probe', 'onlineboost', 'payment.success', 150000, 'PROCESSED');
            """, (pe_id, f"evt-{pe_id}", f"tx-{pe_id}"))
            cur.execute("SAVEPOINT sp_c01_del;")
            delete_blocked = False
            try:
                cur.execute("DELETE FROM public.payment_events WHERE id = %s;", (pe_id,))
            except psycopg2.Error as exc:
                assert "IMMUTABLE_LOG_VIOLATION" in str(exc)
                delete_blocked = True
                cur.execute("ROLLBACK TO SAVEPOINT sp_c01_del;")
            assert delete_blocked, "C-01 append-only trigger did not block DELETE"
            cur.execute("RELEASE SAVEPOINT sp_c01_del;")
            results["C-01"] = "PASS (PG 17 policies valid, Core 033a-033c columns/constraints/append-only verified)"
            print(f"  [PASS] C-01: {results['C-01']}")

            # -----------------------------------------------------------------
            # C-02: whatsapp_connections schema union + Core/Inbox statuses
            # -----------------------------------------------------------------
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'whatsapp_connections';
            """)
            wa_cols = {r[0] for r in cur.fetchall()}
            for req_col in ("tenant_id", "tenant_slug", "mode", "provider", "status", "is_connected"):
                assert req_col in wa_cols, f"C-02 missing column whatsapp_connections.{req_col}"

            cur.execute("""
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'public.whatsapp_connections'::regclass
                  AND conname = 'uq_whatsapp_connections_tenant_provider';
            """)
            assert cur.fetchone() is not None, "C-02 missing uq_whatsapp_connections_tenant_provider"

            # Insert both Core status ('open'/'close') and Inbox status ('CONNECTED'/'DISCONNECTED')
            cur.execute("""
                INSERT INTO public.whatsapp_connections (tenant_id, tenant_slug, provider, instance_name, mode, status, is_connected)
                VALUES
                  ('c02-tenant-core', 'c02-tenant-core', 'EVOLUTION', 'inst-c02-core', 'SHARED', 'open', true),
                  ('c02-tenant-inbox', 'c02-tenant-inbox', 'WABA', 'inst-c02-inbox', 'DEDICATED', 'CONNECTED', true),
                  ('c02-tenant-close', 'c02-tenant-close', 'EVOLUTION', 'inst-c02-close', 'SHARED', 'close', false),
                  ('c02-tenant-disc', 'c02-tenant-disc', 'WABA', 'inst-c02-disc', 'SHARED', 'DISCONNECTED', false);
            """)
            cur.execute("SAVEPOINT sp_c02_bad;")
            bad_wa_blocked = False
            try:
                cur.execute("""
                    INSERT INTO public.whatsapp_connections (tenant_id, tenant_slug, provider, instance_name, mode, status)
                    VALUES ('c02-bad', 'c02-bad', 'EVOLUTION', 'inst-c02-bad', 'SHARED', 'INVALID_STATUS');
                """)
            except psycopg2.errors.CheckViolation:
                bad_wa_blocked = True
                cur.execute("ROLLBACK TO SAVEPOINT sp_c02_bad;")
            assert bad_wa_blocked, "C-02 invalid status was not rejected"
            cur.execute("RELEASE SAVEPOINT sp_c02_bad;")
            results["C-02"] = "PASS (whatsapp_connections union columns, uq_whatsapp_connections_tenant_provider, Core+Inbox statuses accepted, invalid rejected)"
            print(f"  [PASS] C-02: {results['C-02']}")

            # -----------------------------------------------------------------
            # C-03: conversations chk_conversations_status Core + Inbox union
            # -----------------------------------------------------------------
            for st in ("unassigned", "assigned", "resolved", "HUMAN_PAUSED", "active"):
                cur.execute("""
                    INSERT INTO public.conversations (tenant_id, customer_phone, status, bot_mode, bot_paused)
                    VALUES ('onlineboost', %s, %s, 'AI_ACTIVE', false);
                """, (f"628120000{st[:4]}", st))

            cur.execute("SAVEPOINT sp_c03_bad;")
            bad_conv_blocked = False
            try:
                cur.execute("""
                    INSERT INTO public.conversations (tenant_id, customer_phone, status)
                    VALUES ('onlineboost', '628199999999', 'INVALID_CONV_STATUS');
                """)
            except psycopg2.errors.CheckViolation:
                bad_conv_blocked = True
                cur.execute("ROLLBACK TO SAVEPOINT sp_c03_bad;")
            assert bad_conv_blocked, "C-03 invalid conversation status was not rejected"
            cur.execute("RELEASE SAVEPOINT sp_c03_bad;")
            results["C-03"] = "PASS (conversations accepted unassigned/assigned/resolved/HUMAN_PAUSED/active and rejected invalid status)"
            print(f"  [PASS] C-03: {results['C-03']}")

            # -----------------------------------------------------------------
            # C-04: Explicit 20261030 -> 20261122 ordering & objects verified
            # -----------------------------------------------------------------
            flat_inbox = [
                e["file"]
                for p in manifest["after_reconciled_phases"]
                for e in p["entries"]
                if e["repo"] == "inbox"
            ]
            idx_global = flat_inbox.index("20261030_global_auth_studio_and_creator.sql")
            idx_google = flat_inbox.index("20261030_atomic_google_identity_linking.sql")
            idx_obs = flat_inbox.index("20261030_profile_trigger_observability.sql")
            idx_oauth = flat_inbox.index("20261030_shared_oauth_state_replay_protection.sql")
            idx_1112 = flat_inbox.index("20261112_create_tenant_config_audit_logs.sql")
            idx_1115 = flat_inbox.index("20261115_distributed_jti_revocation.sql")
            idx_1120 = flat_inbox.index("20261120_monotonic_tenants_updated_at_trigger.sql")
            idx_1122 = flat_inbox.index("20261122_revoke_public_is_jti_revoked.sql")
            assert idx_global < idx_google < idx_obs < idx_oauth < idx_1112 < idx_1115 < idx_1120 < idx_1122

            cur.execute("""
                SELECT proname FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                  AND proname IN (
                      'fn_reconcile_platform_profile',
                      'fn_link_google_identity',
                      'fn_consume_oauth_state',
                      'is_jti_revoked',
                      'set_tenants_updated_at'
                  );
            """)
            found_procs = {r[0] for r in cur.fetchall()}
            assert len(found_procs) == 5, f"C-04 missing functions: {found_procs}"
            results["C-04"] = "PASS (20261030_global_auth precedes atomic_google/observability/oauth_state -> 20261112 -> 20261115 -> 20261120 -> 20261122; all 5 RPCs/triggers verified)"
            print(f"  [PASS] C-04: {results['C-04']}")

            # -----------------------------------------------------------------
            # C-05 & C-06: Base catalog bootstrap + 036_create_merchants_registry
            # -----------------------------------------------------------------
            expected_base_tables = (
                ("auth", "users"),
                ("public", "tenants"),
                ("public", "orders"),
                ("public", "products"),
                ("public", "commerce_products"),
                ("public", "affiliates"),
                ("public", "contacts"),
                ("public", "tenant_credit_ledger"),
                ("public", "tenant_entitlements"),
                ("public", "merchants"),
            )
            for sch, tbl in expected_base_tables:
                cur.execute("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s;
                """, (sch, tbl))
                assert cur.fetchone() is not None, f"C-05/C-06 missing table {sch}.{tbl}"

            cur.execute("""
                SELECT c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'merchants';
            """)
            m_rls, m_force = cur.fetchone()
            assert m_rls is True and m_force is True, f"C-05/C-06 public.merchants RLS={m_rls}, FORCE={m_force}"
            results["C-05/C-06"] = "PASS (all 10 base catalog tables + public.merchants with RLS=true & FORCE=true verified on clean PG 17 replay)"
            print(f"  [PASS] C-05/C-06: {results['C-05/C-06']}")

            # -----------------------------------------------------------------
            # C-07: Strict RLS ordering + FORCE RLS + zero anon/auth USING(true)
            # -----------------------------------------------------------------
            cur.execute("""
                SELECT
                    c.relname,
                    pol.polname,
                    ARRAY(
                        SELECT CASE WHEN r = 0 THEN 'public' ELSE r::regrole::text END
                        FROM unnest(pol.polroles) AS r
                    ) AS roles,
                    COALESCE(pg_get_expr(pol.polqual, pol.polrelid), '') AS qual,
                    COALESCE(pg_get_expr(pol.polwithcheck, pol.polrelid), '') AS wc
                FROM pg_policy pol
                JOIN pg_class c ON c.oid = pol.polrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public';
            """)
            wildcards = []
            for relname, polname, roles, qual, wc in cur.fetchall():
                if any(r in ("anon", "authenticated", "public") for r in roles):
                    if qual.strip().lower() == "true" or wc.strip().lower() == "true":
                        wildcards.append((relname, polname, roles, qual, wc))
            assert len(wildcards) == 0, f"C-07 leftover anon/authenticated/public wildcard policies: {wildcards}"

            cur.execute("""
                SELECT DISTINCT t.table_name, c.relrowsecurity, c.relforcerowsecurity
                FROM information_schema.tables t
                JOIN information_schema.columns col
                  ON col.table_schema = t.table_schema AND col.table_name = t.table_name
                JOIN pg_class c ON c.relname = t.table_name
                JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
                WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
                  AND (
                      col.column_name IN ('tenant_id', 'tenant_slug', 'store_id', 'merchant_id')
                      OR t.table_name IN ('cart_items', 'tenants', 'merchants', 'tenant_config_audit_logs')
                  )
                ORDER BY t.table_name;
            """)
            tenant_rls_rows = cur.fetchall()
            non_forced = [r for r in tenant_rls_rows if not (r[1] and r[2])]
            assert len(non_forced) == 0, f"C-07 tables missing RLS or FORCE RLS: {non_forced}"
            results["C-07"] = f"PASS ({len(tenant_rls_rows)}/{len(tenant_rls_rows)} tenant-scoped tables have RLS=true & FORCE=true; 0 anon/authenticated/public wildcard USING(true) policies)"
            print(f"  [PASS] C-07: {results['C-07']}")

            # -----------------------------------------------------------------
            # C-08: tenant_config_audit_logs FORCE RLS + is_jti_revoked ACL + monotonic trigger
            # -----------------------------------------------------------------
            cur.execute("""
                SELECT c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'tenant_config_audit_logs';
            """)
            tcal_rls, tcal_force = cur.fetchone()
            assert tcal_rls is True and tcal_force is True, f"C-08 tenant_config_audit_logs RLS={tcal_rls}, FORCE={tcal_force}"

            cur.execute("SELECT has_function_privilege('public', 'public.is_jti_revoked(text,text)', 'EXECUTE');")
            pub_exec = cur.fetchone()[0]
            cur.execute("SELECT has_function_privilege('anon', 'public.is_jti_revoked(text,text)', 'EXECUTE');")
            anon_exec = cur.fetchone()[0]
            cur.execute("SELECT has_function_privilege('authenticated', 'public.is_jti_revoked(text,text)', 'EXECUTE');")
            auth_exec = cur.fetchone()[0]
            cur.execute("SELECT has_function_privilege('service_role', 'public.is_jti_revoked(text,text)', 'EXECUTE');")
            svc_exec = cur.fetchone()[0]
            assert pub_exec is False, f"C-08 PUBLIC still has EXECUTE on is_jti_revoked: {pub_exec}"
            assert anon_exec is True and auth_exec is True and svc_exec is True, (
                f"C-08 expected anon/authenticated/service_role EXECUTE=true, got {anon_exec}/{auth_exec}/{svc_exec}"
            )

            # Test strict monotonicity of trg_tenants_set_updated_at over 5 rapid updates in 1 txn
            mono_slug = f"c08-mono-{uuid.uuid4().hex[:8]}"
            cur.execute("""
                INSERT INTO public.tenants (name, slug, tier, status, is_active)
                VALUES ('Monotonic Probe', %s, 'STARTER', 'ACTIVE', true)
                RETURNING id, updated_at;
            """, (mono_slug,))
            mono_id, prev_ts = cur.fetchone()
            ts_chain = [prev_ts]
            for i in range(5):
                cur.execute("""
                    UPDATE public.tenants
                    SET name = %s
                    WHERE id = %s
                    RETURNING updated_at;
                """, (f"Monotonic Probe {i}", mono_id))
                nxt_ts = cur.fetchone()[0]
                assert nxt_ts > prev_ts, f"C-08 updated_at NOT strictly monotonic: {nxt_ts} <= {prev_ts}"
                ts_chain.append(nxt_ts)
                prev_ts = nxt_ts

            results["C-08"] = (
                f"PASS (tenant_config_audit_logs FORCE RLS=true; "
                f"is_jti_revoked EXECUTE public={pub_exec}, anon={anon_exec}, authenticated={auth_exec}, service_role={svc_exec}; "
                f"trg_tenants_set_updated_at strictly monotonic across 5 rapid updates: "
                f"{ts_chain[0].isoformat()} -> {ts_chain[-1].isoformat()})"
            )
            print(f"  [PASS] C-08: {results['C-08']}")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared-DB PG 17 Migration Reconciliation & Clean-Replay Harness")
    parser.add_argument(
        "--dsn",
        default=os.getenv(
            "RECONCILE_PG17_DSN",
            "postgresql://reconcile_user:reconcile_password@127.0.0.1:55432/bt_gateb_reconcile_pg17",
        ),
        help="Local disposable PostgreSQL 17 DSN (loopback only).",
    )
    parser.add_argument(
        "--inbox-migrations-dir",
        default=os.getenv("INBOX_MIGRATIONS_DIR", str(DEFAULT_INBOX_MIGRATIONS_DIR)),
        help="Path to boontrack-inbox supabase/migrations directory.",
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Drop and recreate public/auth/control_plane schemas before clean replay.",
    )
    args = parser.parse_args()

    assert_disposable_local_dsn(args.dsn)
    inbox_dir = Path(args.inbox_migrations_dir)
    if not inbox_dir.is_dir():
        raise RuntimeError(f"Inbox migrations directory not found: {inbox_dir}")

    manifest = load_manifest()
    print_ordering_comparison(manifest, inbox_dir)

    if args.reset_db:
        print("\n[RESET] Wiping public/auth/control_plane schemas for clean empty DB replay...")
        reset_clean_database(args.dsn)

    # Report PG engine version
    conn = psycopg2.connect(args.dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), version();")
        db_name, pg_ver = cur.fetchone()
    conn.close()
    print(f"\n[ENGINE] Target DB: {db_name} | {pg_ver.split(',')[0]}")
    assert "PostgreSQL 17" in pg_ver, f"Expected PostgreSQL 17 engine, got: {pg_ver}"

    print("\n" + "=" * 88)
    print("EXECUTING CLEAN EMPTY DATABASE REPLAY (ZERO SQL ERRORS REQUIRED)")
    print("=" * 88)
    executed = 0
    for phase in manifest["after_reconciled_phases"]:
        print(f"\n--- {phase['phase']} ---")
        for entry in phase["entries"]:
            sql_path = resolve_migration_path(entry, inbox_dir)
            if not sql_path.is_file():
                raise FileNotFoundError(f"Missing migration file: {sql_path}")
            try:
                execute_sql_file(args.dsn, sql_path)
            except Exception as exc:
                print(f"  [FAIL] [{entry['repo']}] {entry['file']} -> {type(exc).__name__}: {exc}")
                raise
            executed += 1
            print(f"  [OK {executed:03d}] [{entry['repo']:<14}] {entry['file']}")

    print(f"\n[REPLAY COMPLETE] Executed {executed} SQL files cleanly with ZERO SQL errors.")
    run_c01_to_c08_assertions(args.dsn, manifest)
    print("\n" + "=" * 88)
    print("OVERALL VERDICT: PASS — ALL SHARED-DB PG 17 RECONCILIATION CHECKS (C-01..C-08) VERIFIED")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
