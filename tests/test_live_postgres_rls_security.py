"""tests/test_live_postgres_rls_security.py
CTO Directive 10 (P1-B):
Live PostgreSQL RLS Isolation & Non-Superuser Proof Test Suite.

Mathematically and empirically proves:
1. Live database connection is active and never skipped (exit code != 0 on skip/failure).
2. Connection fixture logs in using genuine non-superuser role ('boontrack_test_app_user' with NOSUPERUSER and NOBYPASSRLS).
3. Pre-test assertions strictly enforce rolsuper is False and rolbypassrls is False.
4. Real RLS CRUD row security enforcement: Tenant Alpha records are completely invisible (0 rows) to Tenant Beta.
5. Transaction-scoped SET LOCAL and RESET ROLE; RESET ALL; guarantee 100% pool hygiene.
"""

import os
import pytest
import psycopg2
from fastapi import HTTPException
from app.core.config import settings
from app.core.database import (
    get_db_connection,
    get_tenant_db_connection,
    tenant_transaction,
    close_and_reset_connection,
)
from app.core.security.inter_service_auth import enforce_tenant_boundary


def _ensure_live_db():
    if not os.getenv("POSTGRES_PASSWORD") and not os.getenv("DATABASE_URL"):
        pytest.fail("CTO P1-B Mandate: PostgreSQL credentials are required. Skips are strictly prohibited.")
    try:
        conn = get_db_connection()
        return conn
    except Exception as exc:
        pytest.fail(f"CTO P1-B Mandate: Failed to establish live PostgreSQL connection ({exc}). Skips prohibited.")


@pytest.fixture(scope="session")
def bootstrap_non_superuser_role():
    """Admin connection fixture used SOLELY to bootstrap the non-superuser test role."""
    admin_conn = _ensure_live_db()
    try:
        with admin_conn.cursor() as cur:
            cur.execute("""
                DO $$
                BEGIN
                  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'boontrack_test_app_user') THEN
                    CREATE ROLE boontrack_test_app_user WITH LOGIN PASSWORD 'TestAppUserPassword!123' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
                  END IF;
                END $$;
            """)
            admin_conn.commit()
            cur.execute("GRANT authenticated TO boontrack_test_app_user;")
            cur.execute("GRANT USAGE ON SCHEMA public TO boontrack_test_app_user;")
            cur.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO boontrack_test_app_user;")
            cur.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO boontrack_test_app_user;")
            admin_conn.commit()
    finally:
        admin_conn.close()


@pytest.fixture
def non_superuser_db_conn(bootstrap_non_superuser_role):
    """
    Dedicated connection fixture that logs into PostgreSQL directly using
    genuine non-superuser credentials ('boontrack_test_app_user').
    """
    admin_user = settings.POSTGRES_USER or os.getenv("POSTGRES_USER", "postgres")
    if "." in admin_user:
        project_ref = admin_user.split(".", 1)[1]
        login_user = f"boontrack_test_app_user.{project_ref}"
    else:
        login_user = "boontrack_test_app_user"

    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=int(settings.POSTGRES_PORT or 5432),
        dbname=settings.POSTGRES_DB,
        user=login_user,
        password="TestAppUserPassword!123"
    )
    try:
        # Pre-test assertion: Verify that the connection is truly non-superuser and non-bypassrls
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, session_user;")
            curr_user, sess_user = cur.fetchone()
            cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'boontrack_test_app_user';")
            super_flag, bypass_flag = cur.fetchone()
            assert super_flag is False, f"SECURITY AUDIT FAILURE: '{curr_user}' has rolsuper=True!"
            assert bypass_flag is False, f"SECURITY AUDIT FAILURE: '{curr_user}' has rolbypassrls=True!"
        yield conn
    finally:
        try:
            if not conn.closed:
                conn.rollback()
                with conn.cursor() as reset_cur:
                    reset_cur.execute("RESET ROLE; RESET ALL;")
                conn.commit()
                conn.close()
        except Exception:
            pass


def test_p1_b_live_postgres_role_privilege_audit():
    """Proves that 'authenticated' and 'anon' roles have ZERO superuser and NO bypassrls privileges."""
    conn = _ensure_live_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
                FROM pg_roles
                WHERE rolname IN ('authenticated', 'anon', 'service_role', 'boontrack_test_app_user')
                ORDER BY rolname;
            """)
            roles_data = {r[0]: {"rolsuper": r[1], "rolbypassrls": r[2], "rolcanlogin": r[3]} for r in cur.fetchall()}

        assert "authenticated" in roles_data, "Role 'authenticated' must exist in PostgreSQL engine."
        auth_role = roles_data["authenticated"]
        assert auth_role["rolsuper"] is False, "SECURITY FAILURE: 'authenticated' must have rolsuper=False."
        assert auth_role["rolbypassrls"] is False, "SECURITY FAILURE: 'authenticated' must have rolbypassrls=False (NOBYPASSRLS)."

        if "anon" in roles_data:
            anon_role = roles_data["anon"]
            assert anon_role["rolsuper"] is False, "SECURITY FAILURE: 'anon' must have rolsuper=False."
            assert anon_role["rolbypassrls"] is False, "SECURITY FAILURE: 'anon' must have rolbypassrls=False."

        if "boontrack_test_app_user" in roles_data:
            test_app_role = roles_data["boontrack_test_app_user"]
            assert test_app_role["rolsuper"] is False, "SECURITY FAILURE: 'boontrack_test_app_user' must have rolsuper=False."
            assert test_app_role["rolbypassrls"] is False, "SECURITY FAILURE: 'boontrack_test_app_user' must have rolbypassrls=False."
    finally:
        close_and_reset_connection(conn)


def test_p1_b_live_postgres_rls_negative_isolation_alpha_vs_beta(non_superuser_db_conn):
    """
    Simulates real cross-tenant RLS CRUD query under genuine non-superuser connection 'boontrack_test_app_user'.
    Tenant Alpha inserts a confidential staged alumni record.
    Tenant Beta queries for the exact same table and sees EXACTLY 0 rows, and cannot update/delete it.
    """
    conn = non_superuser_db_conn
    with conn.cursor() as cur:
        # Pre-test assertion required by CTO: rolsuper is False and rolbypassrls is False
        cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'boontrack_test_app_user';")
        rolsuper, rolbypassrls = cur.fetchone()
        assert rolsuper is False, "Assertion failure: rolsuper must be False"
        assert rolbypassrls is False, "Assertion failure: rolbypassrls must be False"

        # 1. Establish transaction context as authenticated under tenant_alpha
        cur.execute("SET LOCAL ROLE authenticated;")
        cur.execute("SELECT set_config('app.current_tenant_id', 'tenant_alpha', true);")

        # 2. Insert test record for Tenant Alpha
        cur.execute("""
            INSERT INTO public.staging_alumni_cpm (tenant_id, lead_phone, alumni_name, status)
            VALUES ('tenant_alpha', '628999900001', 'Confidential Non-Superuser Executive', 'STAGED');
        """)

        # 3. Tenant Alpha can see its own record
        cur.execute("SELECT COUNT(*) FROM public.staging_alumni_cpm WHERE tenant_id = 'tenant_alpha';")
        alpha_visible_count = cur.fetchone()[0]
        assert alpha_visible_count >= 1, "Tenant Alpha must be able to view its own staged record."

        # 4. Switch context to Tenant Beta within same transaction
        cur.execute("SELECT set_config('app.current_tenant_id', 'tenant_beta', true);")

        # 5. Tenant Beta attempts to read Tenant Alpha's record
        cur.execute("SELECT COUNT(*) FROM public.staging_alumni_cpm WHERE tenant_id = 'tenant_alpha';")
        beta_visible_count = cur.fetchone()[0]

        # PROOF: PostgreSQL RLS engine enforces 0 rows returned
        assert beta_visible_count == 0, f"SECURITY BREACH: Tenant Beta leaked {beta_visible_count} rows of Alpha!"

        # 6. Tenant Beta attempts to UPDATE Tenant Alpha's record
        cur.execute("""
            UPDATE public.staging_alumni_cpm
            SET alumni_name = 'Hacked Name'
            WHERE tenant_id = 'tenant_alpha';
        """)
        assert cur.rowcount == 0, f"SECURITY BREACH: Tenant Beta modified {cur.rowcount} rows of Alpha!"

        # 7. Tenant Beta attempts to DELETE Tenant Alpha's record
        cur.execute("DELETE FROM public.staging_alumni_cpm WHERE tenant_id = 'tenant_alpha';")
        assert cur.rowcount == 0, f"SECURITY BREACH: Tenant Beta deleted {cur.rowcount} rows of Alpha!"

    # Rollback temporary test record
    conn.rollback()


def test_p1_b_live_postgres_connection_pool_hygiene_and_state_reset():
    """
    Proves that executing transactions and rolling back or closing leaves zero context contamination
    in subsequent pooled connections.
    """
    conn1 = _ensure_live_db()
    try:
        with conn1.cursor() as cur1:
            cur1.execute("SET LOCAL ROLE authenticated;")
            cur1.execute("SELECT set_config('app.current_tenant_id', 'tenant_alpha', true);")
            cur1.execute("SELECT current_setting('app.current_tenant_id', true);")
            assert cur1.fetchone()[0] == "tenant_alpha"

        # Explicit rollback and clean reset
        conn1.rollback()
        with conn1.cursor() as reset_cur:
            reset_cur.execute("RESET ROLE; RESET ALL;")
        conn1.commit()
    finally:
        close_and_reset_connection(conn1)

    # Acquire fresh pooled connection
    conn2 = _ensure_live_db()
    try:
        with conn2.cursor() as cur2:
            cur2.execute("SELECT current_setting('app.current_tenant_id', true);")
            tenant_setting = cur2.fetchone()[0]
            assert tenant_setting in (None, "", "public"), f"Pool leak: tenant_id '{tenant_setting}' persisted across connections!"

            cur2.execute("SELECT current_user;")
            current_user = cur2.fetchone()[0]
            assert current_user != "authenticated", f"Pool leak: role '{current_user}' remained 'authenticated'!"
    finally:
        close_and_reset_connection(conn2)


def test_p1_b_tenant_membership_trust_boundary_rejection(non_superuser_db_conn):
    """
    Validates tenant trust boundary enforcement:
    1. Asserts non-superuser connection is active (rolsuper=False, rolbypassrls=False).
    2. Kernel-level RLS boundary: Under tenant_alpha context, an unauthorized insert into
       tenant_beta is strictly blocked by PostgreSQL RLS (WITH CHECK policy violation).
    3. Middleware-level boundary: enforce_tenant_boundary rejects caller attempting to operate
       on a tenant outside their signed membership (HTTP 403 TENANT_BOUNDARY_MISMATCH).
    4. Database context helper fail-closed: get_tenant_db_connection and tenant_transaction
       reject empty/None/blank tenant IDs with ValueError.
    """
    conn = non_superuser_db_conn

    # 1. Assert genuine non-superuser role
    with conn.cursor() as cur:
        cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'boontrack_test_app_user';")
        rolsuper, rolbypassrls = cur.fetchone()
        assert rolsuper is False, "Trust boundary requirement: rolsuper must be False"
        assert rolbypassrls is False, "Trust boundary requirement: rolbypassrls must be False"

        # 2. Kernel-level RLS boundary: Tenant Alpha context attempting unauthorized Tenant Beta write
        cur.execute("SET LOCAL ROLE authenticated;")
        cur.execute("SELECT set_config('app.current_tenant_id', 'tenant_alpha', true);")

        with pytest.raises(psycopg2.errors.InsufficientPrivilege) as exc_info:
            cur.execute("""
                INSERT INTO public.staging_alumni_cpm (tenant_id, lead_phone, alumni_name, status)
                VALUES ('tenant_beta', '628999900002', 'Malicious Cross Tenant Insert', 'STAGED');
            """)
        assert "violates row-level security policy" in str(exc_info.value), (
            f"Expected RLS WITH CHECK policy violation, got: {exc_info.value}"
        )

    # Rollback aborted transaction
    conn.rollback()

    # 3. Middleware-level boundary: Caller with tenant_alpha membership attempting tenant_beta action
    with pytest.raises(HTTPException) as http_exc:
        enforce_tenant_boundary("tenant_alpha", "tenant_beta")
    assert http_exc.value.status_code == 403
    assert http_exc.value.detail.get("error") == "TENANT_BOUNDARY_MISMATCH"

    # Self-tenant boundary is permitted
    enforce_tenant_boundary("tenant_alpha", "tenant_alpha")

    # 4. Context helper fail-closed: Blank/None tenant rejected
    for invalid_tenant in ["", "   ", None]:
        with pytest.raises(ValueError):
            get_tenant_db_connection(invalid_tenant)
        with pytest.raises(ValueError):
            with tenant_transaction(invalid_tenant):
                pass

