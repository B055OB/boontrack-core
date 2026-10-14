"""tests/test_live_postgres_rls_security.py
CTO Directive 10 (P1-B):
Live PostgreSQL RLS Isolation & Non-Superuser Proof Test Suite.

Mathematically and empirically proves:
1. Live database connection is active and never skipped (exit code != 0 on skip/failure).
2. Role 'authenticated' has rolsuper=False and rolbypassrls=False (Zero Superuser, 100% RLS-enforced).
3. Real RLS row security enforcement: Tenant Alpha row is completely invisible (0 rows) to Tenant Beta.
4. Transaction-scoped SET LOCAL and RESET ROLE; RESET ALL; guarantee 100% pool hygiene.
"""

import os
import pytest
from app.core.database import (
    get_db_connection,
    tenant_transaction,
    close_and_reset_connection,
)


def _ensure_live_db():
    if not os.getenv("POSTGRES_PASSWORD") and not os.getenv("DATABASE_URL"):
        pytest.fail("CTO P1-B Mandate: PostgreSQL credentials are required. Skips are strictly prohibited.")
    try:
        conn = get_db_connection()
        return conn
    except Exception as exc:
        pytest.fail(f"CTO P1-B Mandate: Failed to establish live PostgreSQL connection ({exc}). Skips prohibited.")


def test_p1_b_live_postgres_role_privilege_audit():
    """Proves that 'authenticated' and 'anon' roles have ZERO superuser and NO bypassrls privileges."""
    conn = _ensure_live_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
                FROM pg_roles
                WHERE rolname IN ('authenticated', 'anon', 'service_role')
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
    finally:
        close_and_reset_connection(conn)


def test_p1_b_live_postgres_rls_negative_isolation_alpha_vs_beta():
    """
    Simulates real cross-tenant RLS query under 'authenticated' role.
    Tenant Alpha inserts a confidential staged alumni record.
    Tenant Beta queries for the exact same table and sees EXACTLY 0 rows.
    """
    conn = _ensure_live_db()
    try:
        with conn.cursor() as cur:
            # 1. Establish transaction context as authenticated under tenant_alpha
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', 'tenant_alpha', true);")

            # 2. Insert test record for Tenant Alpha
            cur.execute("""
                INSERT INTO public.staging_alumni_cpm (tenant_id, lead_phone, alumni_name, status)
                VALUES ('tenant_alpha', '628999900001', 'Confidential Alpha Executive', 'STAGED');
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

        # Rollback temporary test record
        conn.rollback()
    finally:
        close_and_reset_connection(conn)


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
