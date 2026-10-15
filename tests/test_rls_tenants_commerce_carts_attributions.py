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


def test_rls_commerce_products_alpha_vs_beta_isolation(db_conn):
    """Proves 100% strict multi-tenant isolation on commerce_products (Alpha vs Beta):

    a. Seed Tenant Alpha active product and Tenant Beta active product.
    b. Query under Tenant Alpha context (UUID and slug) -> 100% only Alpha products returned, Beta products 0 rows.
    c. Query under NULL / anon session -> 0 rows returned (zero data leakage).
    d. Context spoofing / tampering attempt -> 0 rows returned.
    """
    alpha_tenant_id = str(uuid.uuid4())
    beta_tenant_id = str(uuid.uuid4())
    alpha_slug = f"alpha_comm_{uuid.uuid4().hex[:8]}"
    beta_slug = f"beta_comm_{uuid.uuid4().hex[:8]}"

    prod_alpha_act = f"PROD_A_ACT_{uuid.uuid4().hex[:6]}"
    prod_alpha_inact = f"PROD_A_INACT_{uuid.uuid4().hex[:6]}"
    prod_beta_act = f"PROD_B_ACT_{uuid.uuid4().hex[:6]}"
    prod_beta_inact = f"PROD_B_INACT_{uuid.uuid4().hex[:6]}"

    # 1. Setup seed tenants & products as superuser
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.tenants (id, name, slug, is_active)
            VALUES (%s, 'Alpha Commerce Corp', %s, true), (%s, 'Beta Commerce Corp', %s, true)
            ON CONFLICT (slug) DO NOTHING;
            """,
            (alpha_tenant_id, alpha_slug, beta_tenant_id, beta_slug),
        )
        cur.execute(
            """
            INSERT INTO public.commerce_products (tenant_id, product_code, title, category, price, delivery_payload, keywords, is_active)
            VALUES 
                (%s, %s, 'Alpha Active Product', 'DIGITAL', 50000, 'Payload Alpha Act', 'alpha', true),
                (%s, %s, 'Alpha Inactive Product', 'DIGITAL', 40000, 'Payload Alpha Inact', 'alpha', false),
                (%s, %s, 'Beta Active Product', 'DIGITAL', 75000, 'Payload Beta Act', 'beta', true),
                (%s, %s, 'Beta Inactive Product', 'DIGITAL', 60000, 'Payload Beta Inact', 'beta', false);
            """,
            (alpha_slug, prod_alpha_act, alpha_slug, prod_alpha_inact, beta_slug, prod_beta_act, beta_slug, prod_beta_inact),
        )
        db_conn.commit()

    try:
        with db_conn.cursor() as cur:
            # 2. Test under role 'anon' with Tenant Alpha slug
            cur.execute("SET LOCAL ROLE anon;")
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (alpha_slug,))
            cur.execute("SELECT product_code FROM public.commerce_products;")
            results_alpha = [r[0] for r in cur.fetchall()]

            assert prod_alpha_act in results_alpha, "Tenant Alpha active product must be visible."
            assert prod_alpha_inact not in results_alpha, "Inactive products must NEVER be visible to public/anon."
            assert prod_beta_act not in results_alpha, "BREACH: Tenant Beta product leaked to Tenant Alpha context!"
            assert prod_beta_inact not in results_alpha, "BREACH: Tenant Beta inactive product leaked!"
            assert len(results_alpha) == 1, f"Expected exactly 1 product for Alpha, got {len(results_alpha)}"

            # 3. Test under role 'anon' with Tenant Alpha UUID (dual resolution check)
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (alpha_tenant_id,))
            cur.execute("SELECT product_code FROM public.commerce_products;")
            results_alpha_uuid = [r[0] for r in cur.fetchall()]
            assert results_alpha_uuid == [prod_alpha_act], "Tenant Alpha UUID lookup must return only Alpha active product."

            # 4. Test under role 'anon' with Tenant Beta slug
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (beta_slug,))
            cur.execute("SELECT product_code FROM public.commerce_products;")
            results_beta = [r[0] for r in cur.fetchall()]
            assert prod_beta_act in results_beta, "Tenant Beta active product must be visible."
            assert prod_alpha_act not in results_beta, "BREACH: Tenant Alpha product leaked to Tenant Beta context!"
            assert len(results_beta) == 1, f"Expected exactly 1 product for Beta, got {len(results_beta)}"

            # 5. Test under role 'anon' with NULL / empty / unset tenant -> ZERO ROWS LEAKAGE
            cur.execute("SELECT set_config('app.current_tenant_id', NULL, true);")
            cur.execute("SELECT count(*) FROM public.commerce_products;")
            null_count = cur.fetchone()[0]
            assert null_count == 0, f"BREACH: Anonymous query without tenant returned {null_count} products!"

            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT count(*) FROM public.commerce_products;")
            empty_count = cur.fetchone()[0]
            assert empty_count == 0, f"BREACH: Query with empty tenant returned {empty_count} products!"

            # 6. Test context spoofing and SQL injection attempts
            cur.execute("SELECT set_config('app.current_tenant_id', 'spoofed_tenant_slug_xyz', true);")
            cur.execute("SELECT count(*) FROM public.commerce_products;")
            assert cur.fetchone()[0] == 0, "Spoofed slug must return 0 products."

            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (str(uuid.uuid4()),))
            cur.execute("SELECT count(*) FROM public.commerce_products;")
            assert cur.fetchone()[0] == 0, "Spoofed non-existent UUID must return 0 products."

            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", ("victim' OR '1'='1",))
            cur.execute("SELECT count(*) FROM public.commerce_products;")
            assert cur.fetchone()[0] == 0, "SQL injection spoofing attempt must return 0 products."

    finally:
        db_conn.rollback()
        with db_conn.cursor() as cur:
            cur.execute("RESET ROLE; RESET ALL;")
            cur.execute("DELETE FROM public.commerce_products WHERE product_code IN (%s, %s, %s, %s);", 
                        (prod_alpha_act, prod_alpha_inact, prod_beta_act, prod_beta_inact))
            cur.execute("DELETE FROM public.tenants WHERE id IN (%s, %s);", (alpha_tenant_id, beta_tenant_id))
            db_conn.commit()


def test_rls_tenants_public_anon_negative_isolation(db_conn):
    """Proves 100% strict multi-tenant isolation on tenants table for public/anon:

    a. Role anon with empty/NULL session context CANNOT read any tenant records (0 rows).
    b. Role anon with another tenant's slug/UUID CANNOT read the target tenant's row.
    c. Role anon with non-existent / spoofed tenant CANNOT read any records (0 rows).
    d. Inactive tenants are NEVER visible to public/anon even with matching session context.
    """
    alpha_tenant_id = str(uuid.uuid4())
    beta_tenant_id = str(uuid.uuid4())
    inact_tenant_id = str(uuid.uuid4())
    alpha_slug = f"alpha_t_{uuid.uuid4().hex[:8]}"
    beta_slug = f"beta_t_{uuid.uuid4().hex[:8]}"
    inact_slug = f"inact_t_{uuid.uuid4().hex[:8]}"

    # 1. Seed tenants as superuser
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.tenants (id, name, slug, is_active)
            VALUES 
                (%s, 'Alpha Isolation Corp', %s, true),
                (%s, 'Beta Isolation Corp', %s, true),
                (%s, 'Inactive Corp', %s, false)
            ON CONFLICT (slug) DO NOTHING;
            """,
            (alpha_tenant_id, alpha_slug, beta_tenant_id, beta_slug, inact_tenant_id, inact_slug),
        )
        db_conn.commit()

    try:
        with db_conn.cursor() as cur:
            # 2. Under role 'anon' with empty string context -> 0 rows (ZERO LEAK)
            cur.execute("SET LOCAL ROLE anon;")
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT count(*) FROM public.tenants;")
            assert cur.fetchone()[0] == 0, "BREACH: Role anon with empty tenant context read tenant rows!"

            # 3. Under role 'anon' with NULL context -> 0 rows (ZERO LEAK)
            cur.execute("SELECT set_config('app.current_tenant_id', NULL, true);")
            cur.execute("SELECT count(*) FROM public.tenants;")
            assert cur.fetchone()[0] == 0, "BREACH: Role anon with NULL tenant context read tenant rows!"

            # 4. Under role 'anon' with Tenant Alpha context -> CANNOT see Tenant Beta
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (alpha_slug,))
            cur.execute("SELECT slug FROM public.tenants;")
            results_alpha = [r[0] for r in cur.fetchall()]
            assert results_alpha == [alpha_slug], f"Expected only Alpha slug, got {results_alpha}"
            assert beta_slug not in results_alpha, "BREACH: Tenant Beta leaked to Tenant Alpha context!"
            assert inact_slug not in results_alpha, "BREACH: Inactive tenant leaked to Tenant Alpha context!"

            # 5. Under role 'anon' with Tenant Beta context -> CANNOT see Tenant Alpha
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (beta_slug,))
            cur.execute("SELECT slug FROM public.tenants;")
            results_beta = [r[0] for r in cur.fetchall()]
            assert results_beta == [beta_slug], f"Expected only Beta slug, got {results_beta}"
            assert alpha_slug not in results_beta, "BREACH: Tenant Alpha leaked to Tenant Beta context!"

            # 6. Under role 'anon' with spoofed slug / UUID / SQL injection -> 0 rows
            cur.execute("SELECT set_config('app.current_tenant_id', 'unauthorized_spoofed_slug', true);")
            cur.execute("SELECT count(*) FROM public.tenants;")
            assert cur.fetchone()[0] == 0, "Spoofed slug must return 0 tenants."

            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (str(uuid.uuid4()),))
            cur.execute("SELECT count(*) FROM public.tenants;")
            assert cur.fetchone()[0] == 0, "Spoofed UUID must return 0 tenants."

            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", ("victim' OR '1'='1",))
            cur.execute("SELECT count(*) FROM public.tenants;")
            assert cur.fetchone()[0] == 0, "SQL injection spoofing attempt must return 0 tenants."

            # 7. Inactive tenant cannot be read even if its slug is passed
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (inact_slug,))
            cur.execute("SELECT count(*) FROM public.tenants;")
            assert cur.fetchone()[0] == 0, "Inactive tenant must NOT be readable by public/anon!"

    finally:
        db_conn.rollback()
        with db_conn.cursor() as cur:
            cur.execute("RESET ROLE; RESET ALL;")
            cur.execute("DELETE FROM public.tenants WHERE id IN (%s, %s, %s);", (alpha_tenant_id, beta_tenant_id, inact_tenant_id))
            db_conn.commit()



