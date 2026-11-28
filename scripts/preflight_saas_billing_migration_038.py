"""Read-only preflight checks for Core SaaS Billing Migration 038.

--verify-disposable checks an isolated runner-local PostgreSQL database after Migration
038 has been applied by CI. --staging-read-only inspects an explicitly supplied
Staging connection without executing DDL or mutating rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlparse


REQUIRED_TABLES = {
    "saas_billing_purchases",
    "saas_billing_webhook_events",
    "saas_billing_ledger_entries",
    "saas_billing_entitlement_events",
}
REQUIRED_CORE_TABLES = {"tenants", "payment_intents", "payment_outbox_events"}
REQUIRED_SANDBOX_ENV = (
    "SAAS_XENDIT_ENV",
    "SAAS_XENDIT_SANDBOX_PROFILE_ID",
    "SAAS_XENDIT_SANDBOX_SECRET_KEY",
    "SAAS_XENDIT_SANDBOX_CALLBACK_TOKEN",
    "SAAS_XENDIT_SANDBOX_BUSINESS_ID",
    "SAAS_XENDIT_SANDBOX_WEBHOOK_URL",
)


def _profile_readiness() -> dict[str, object]:
    present = [key for key in REQUIRED_SANDBOX_ENV if bool(os.getenv(key, "").strip())]
    generic_secret = os.getenv("XENDIT_SECRET_KEY", "").strip()
    generic_callback = os.getenv("XENDIT_CALLBACK_TOKEN", "").strip()
    dedicated_secret = os.getenv("SAAS_XENDIT_SANDBOX_SECRET_KEY", "").strip()
    dedicated_callback = os.getenv("SAAS_XENDIT_SANDBOX_CALLBACK_TOKEN", "").strip()
    credential_separation = (
        not dedicated_secret or not generic_secret or dedicated_secret != generic_secret
    ) and (
        not dedicated_callback or not generic_callback or dedicated_callback != generic_callback
    )
    sandbox_selected = os.getenv("SAAS_XENDIT_ENV", "").strip().lower() == "sandbox"
    return {
        "required_keys_present": present,
        "missing_keys": [key for key in REQUIRED_SANDBOX_ENV if key not in present],
        "sandbox_selected": sandbox_selected,
        "credential_separation": credential_separation,
        "ready": len(present) == len(REQUIRED_SANDBOX_ENV) and sandbox_selected and credential_separation,
    }


def _verify_schema(conn, *, require_saas_tables: bool) -> dict[str, object]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public';
            """
        )
        tables = {str(row[0]) for row in cur.fetchall()}
        missing_core = sorted(REQUIRED_CORE_TABLES - tables)
        if missing_core:
            raise RuntimeError("CORE_SCHEMA_PREREQUISITES_MISSING:" + ",".join(missing_core))
        existing_saas = REQUIRED_TABLES & tables
        if require_saas_tables and existing_saas != REQUIRED_TABLES:
            raise RuntimeError("SAAS_MIGRATION_038_TABLES_INCOMPLETE:" + ",".join(sorted(REQUIRED_TABLES - existing_saas)))
        if not require_saas_tables and existing_saas and existing_saas != REQUIRED_TABLES:
            raise RuntimeError("SAAS_MIGRATION_038_PARTIAL_SCHEMA:" + ",".join(sorted(REQUIRED_TABLES - existing_saas)))

        if require_saas_tables:
            cur.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = 'uq_saas_billing_ledger_event_purchase_sku_kind';
                """
            )
            index_row = cur.fetchone()
            if not index_row:
                raise RuntimeError("SAAS_MULTI_SKU_DEDUPE_INDEX_MISSING")
            indexdef = str(index_row[0]).lower()
            for column in ("provider_event_id", "purchase_id", "sku", "entry_kind"):
                if column not in indexdef:
                    raise RuntimeError("SAAS_MULTI_SKU_DEDUPE_INDEX_INVALID")
            cur.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = ANY(%s);
                """,
                (list(REQUIRED_TABLES),),
            )
            rls = {str(row[0]): (bool(row[1]), bool(row[2])) for row in cur.fetchall()}
            if set(rls) != REQUIRED_TABLES or any(not v[0] or not v[1] for v in rls.values()):
                raise RuntimeError("SAAS_RLS_FORCE_NOT_ENABLED")
            cur.execute(
                """
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_saas_billing_ledger_no_update'
                  AND NOT tgisinternal;
                """
            )
            if not cur.fetchone():
                raise RuntimeError("SAAS_LEDGER_APPEND_ONLY_TRIGGER_MISSING")
        return {
            "core_prerequisites": sorted(REQUIRED_CORE_TABLES),
            "saas_tables": sorted(existing_saas),
            "schema_state": "APPLIED_AND_VERIFIED" if existing_saas == REQUIRED_TABLES else "NOT_YET_APPLIED",
        }


def _verify_disposable() -> dict[str, object]:
    from app.core.security.test_isolation_guard import assert_disposable_postgres_target
    import psycopg2

    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DISPOSABLE_DATABASE_URL_REQUIRED")
    assert_disposable_postgres_target(dsn=dsn, allow_if_unconfigured=False)
    conn = psycopg2.connect(dsn, connect_timeout=5)
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), inet_server_addr()::text;")
            db_name, db_address = cur.fetchone()
        schema = _verify_schema(conn, require_saas_tables=True)
        profile = _profile_readiness()
        if not profile["ready"]:
            raise RuntimeError("SAAS_XENDIT_SANDBOX_TEST_PROFILE_NOT_READY")
        conn.rollback()
        return {
            "mode": "DISPOSABLE_CI_READ_ONLY",
            "sandbox_profile": profile,
            "database": db_name,
            "server_address": db_address,
            **schema,
        }
    finally:
        conn.close()


def _verify_staging_read_only() -> dict[str, object]:
    import psycopg2

    dsn = os.getenv("SAAS_BILLING_STAGING_PREFLIGHT_DSN", "").strip()
    if not dsn:
        raise RuntimeError("SAAS_BILLING_STAGING_PREFLIGHT_DSN_NOT_CONFIGURED")
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    database = (parsed.path or "").lstrip("/").lower()
    if not ("staging" in host or "staging" in database):
        raise RuntimeError("STAGING_TARGET_IDENTITY_NOT_EXPLICIT")
    conn = psycopg2.connect(dsn, connect_timeout=5, options="-c default_transaction_read_only=on")
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY;")
            cur.execute("SELECT current_database(), inet_server_addr()::text, current_user;")
            db_name, db_address, db_user = cur.fetchone()
            schema = _verify_schema(conn, require_saas_tables=False)
        conn.rollback()
        profile = _profile_readiness()
        return {
            "mode": "STAGING_READ_ONLY",
            "database": db_name,
            "server_address": db_address,
            "database_user": db_user,
            **schema,
            "sandbox_profile": profile,
            "staging_ddl_executed": False,
            "migration_application_authorized": False,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify-disposable", action="store_true")
    group.add_argument("--staging-read-only", action="store_true")
    args = parser.parse_args()
    try:
        result = _verify_disposable() if args.verify_disposable else _verify_staging_read_only()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"preflight": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
