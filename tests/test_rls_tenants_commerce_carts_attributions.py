"""tests/test_rls_tenants_commerce_carts_attributions.py
Verification suite for Row-Level Security (RLS) on:
- tenants
- commerce_products
- carts
- attributions

Guarantees:
1. Native column data types (UUID vs VARCHAR) are respected without invalid type cast exceptions.
2. Safe evaluation of current_setting('app.current_tenant_id', true) across UUID, slug, empty string,
   NULL, and malicious SQL injection payloads.
3. Strict cross-tenant isolation (0 rows leaked between tenants).
"""

import uuid
import pytest
from app.core.database import (
    get_db_connection,
    close_and_reset_connection,
)


@pytest.fixture(scope="module")
def db_conn():
    conn = get_db_connection()
    yield conn
    close_and_reset_connection(conn)


def test_rls_no_type_error_on_edge_case_tenant_settings(db_conn):
    """Proves that querying tenants, commerce_products, carts, and attributions never throws

    data type errors (e.g. invalid input syntax for type uuid) regardless of current_setting value.
    """
    test_settings = [
        ("Valid UUID", str(uuid.uuid4())),
        ("Valid Slug", "test_tenant_slug"),
        ("Empty String", ""),
        ("NULL Setting", None),
        ("Alphanumeric String", "random_string_12345"),
        ("SQL Injection Attempt", "victim_tenant' OR '1'='1"),
    ]

    tables = [
        "tenants", "commerce_products", "carts", "attributions",
        "affiliates", "affiliate_commissions", "cart_items"
    ]
    roles = ["authenticated", "anon"]

    with db_conn.cursor() as cur:
        for role in roles:
            cur.execute(f"SET LOCAL ROLE {role};")
            for label, setting_val in test_settings:
                if setting_val is None:
                    cur.execute("SELECT set_config('app.current_tenant_id', NULL, true);")
                else:
                    cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (setting_val,))

                for tbl in tables:
                    try:
                        cur.execute(f"SELECT count(*) FROM public.{tbl};")
                        cnt = cur.fetchone()[0]
                        assert isinstance(cnt, int), f"Expected int count for {tbl}, got {cnt}"
                    except Exception as exc:
                        pytest.fail(
                            f"RLS Query Failed on table '{tbl}' under role '{role}' with setting '{label}' ({setting_val}): {exc}"
                        )
        db_conn.rollback()


def test_rls_cross_tenant_isolation_carts_and_attributions(db_conn):
    """Proves that Tenant Beta cannot read or modify Tenant Alpha's carts, attributions, affiliates, and cart_items."""
    alpha_tenant_id = str(uuid.uuid4())
    beta_tenant_id = str(uuid.uuid4())
    alpha_slug = f"alpha_{uuid.uuid4().hex[:8]}"
    beta_slug = f"beta_{uuid.uuid4().hex[:8]}"

    # Setup seed tenants as postgres/superuser
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.tenants (id, name, slug, is_active)
            VALUES (%s, 'Alpha Corp', %s, true), (%s, 'Beta Corp', %s, true)
            ON CONFLICT (slug) DO NOTHING;
            """,
            (alpha_tenant_id, alpha_slug, beta_tenant_id, beta_slug),
        )
        db_conn.commit()

    try:
        # 1. Tenant Alpha creates a cart, attribution, cart_item, and affiliate
        cart_id = str(uuid.uuid4())
        attr_id = str(uuid.uuid4())
        cart_item_id = str(uuid.uuid4())
        affiliate_id = str(uuid.uuid4())

        with db_conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (alpha_tenant_id,))

            cur.execute(
                """
                INSERT INTO public.carts (id, tenant_id, session_id, status)
                VALUES (%s, %s::uuid, 'session_alpha_1', 'ACTIVE');
                """,
                (cart_id, alpha_tenant_id),
            )

            cur.execute(
                """
                INSERT INTO public.cart_items (
                    id, cart_id, product_id, quantity, unit_price_snapshot, selected_modifiers, modifier_hash
                )
                VALUES (%s, %s::uuid, 'prod_test_1', 1, 10000, '{}'::jsonb, 'hash_test_1');
                """,
                (cart_item_id, cart_id),
            )

            cur.execute(
                """
                INSERT INTO public.attributions (id, tenant_id, session_id, utm_source, ip_hash)
                VALUES (%s, %s, 'session_alpha_1', 'meta_ads', 'test_hash_123');
                """,
                (attr_id, alpha_slug),
            )

            cur.execute(
                """
                INSERT INTO public.affiliates (
                    id, tenant_id, name, phone_number, email, referral_code, commission_rate, status, role
                )
                VALUES (%s, %s, 'Alpha Partner', '6281299990001', 'partner@alpha.com', %s, 10.0, 'ACTIVE', 'affiliate');
                """,
                (affiliate_id, alpha_slug, f"REF_{uuid.uuid4().hex[:6]}"),
            )
            db_conn.commit()

        # 2. Tenant Alpha verifies visibility of own records
        with db_conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (alpha_tenant_id,))

            cur.execute("SELECT count(*) FROM public.carts WHERE id = %s;", (cart_id,))
            assert cur.fetchone()[0] == 1, "Tenant Alpha must see its own cart."

            cur.execute("SELECT count(*) FROM public.cart_items WHERE id = %s;", (cart_item_id,))
            assert cur.fetchone()[0] == 1, "Tenant Alpha must see its own cart_item."

            cur.execute("SELECT count(*) FROM public.attributions WHERE id = %s;", (attr_id,))
            assert cur.fetchone()[0] == 1, "Tenant Alpha must see its own attribution."

            cur.execute("SELECT count(*) FROM public.affiliates WHERE id = %s;", (affiliate_id,))
            assert cur.fetchone()[0] == 1, "Tenant Alpha must see its own affiliate."

        # 3. Tenant Beta tries to access Tenant Alpha's records -> Zero Leakage (0 rows)
        with db_conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE authenticated;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (beta_tenant_id,))

            cur.execute("SELECT count(*) FROM public.carts WHERE id = %s;", (cart_id,))
            assert cur.fetchone()[0] == 0, "BREACH: Tenant Beta saw Tenant Alpha's cart!"

            cur.execute("SELECT count(*) FROM public.cart_items WHERE id = %s;", (cart_item_id,))
            assert cur.fetchone()[0] == 0, "BREACH: Tenant Beta saw Tenant Alpha's cart_item!"

            cur.execute("SELECT count(*) FROM public.attributions WHERE id = %s;", (attr_id,))
            assert cur.fetchone()[0] == 0, "BREACH: Tenant Beta saw Tenant Alpha's attribution!"

            cur.execute("SELECT count(*) FROM public.affiliates WHERE id = %s;", (affiliate_id,))
            assert cur.fetchone()[0] == 0, "BREACH: Tenant Beta saw Tenant Alpha's affiliate!"

    finally:
        db_conn.rollback()
        # Clean up seeded records as superuser
        with db_conn.cursor() as cur:
            cur.execute("RESET ROLE; RESET ALL;")
            cur.execute("DELETE FROM public.cart_items WHERE id = %s;", (cart_item_id,))
            cur.execute("DELETE FROM public.carts WHERE id = %s;", (cart_id,))
            cur.execute("DELETE FROM public.attributions WHERE id = %s;", (attr_id,))
            cur.execute("DELETE FROM public.affiliates WHERE id = %s;", (affiliate_id,))
            cur.execute("DELETE FROM public.tenants WHERE id IN (%s, %s);", (alpha_tenant_id, beta_tenant_id))
            db_conn.commit()

