"""tests/test_worker_cross_tenant_isolation.py
CTO Directive 09 FIX 5:
Automated test suite simulating cross-tenant worker job execution (Alpha vs Beta).
Mathematically and empirically proves:
1. Reconciler worker executing payload for Tenant Alpha targeting Tenant Beta's order is strictly rejected with PermissionError.
2. Tenant Alpha's worker database transaction targeting Tenant Beta's object affects exactly 0 rows.
3. Storage / media worker running for Tenant Alpha targeting Tenant Beta's assets raises PermissionError.
4. Non-existent or empty tenant_id in worker job is rejected with ValueError.
"""

import os
import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.workers.payment_reconciler_worker import (
    save_payment_order,
    get_payment_order,
    clear_payment_orders_store,
    reconcile_single_order,
    PaymentStatus,
)
from app.services.storage.r2 import generate_presigned_download_url
from app.core.database import (
    get_db_connection,
    tenant_transaction,
    close_and_reset_connection,
    worker_elevated_transaction,
    close_worker_db_connection,
)


@pytest.fixture(autouse=True)
def clean_stores():
    clear_payment_orders_store()
    yield
    clear_payment_orders_store()


# -----------------------------------------------------------------------------
# 1. Payment Reconciler Worker Cross-Tenant Simulation
# -----------------------------------------------------------------------------
def test_worker_reconciler_cross_tenant_payload_raises_permission_error():
    """
    Simulates a background worker execution where Tenant Alpha's payload attempts
    to manipulate or reconcile an order belonging to Tenant Beta.
    Proves that the worker detects cross-tenant boundary breach and raises PermissionError.
    """
    now = datetime.now(timezone.utc)
    beta_order_id = "ORD-BETA-CRITICAL-99"

    # Register an order belonging to Tenant Beta
    save_payment_order(
        tenant_id="tenant_beta",
        order_id=beta_order_id,
        amount=500000,
        expired_at=now - timedelta(minutes=5),
        items_reserved=[{"item_id": "PREMIUM_COURSE", "quantity": 1}],
        payment_status=PaymentStatus.PENDING,
    )

    # Worker executes job with Tenant Alpha's credentials targeting Beta's order
    with pytest.raises(PermissionError, match="Cross-tenant worker manipulation forbidden"):
        reconcile_single_order(
            order_id=beta_order_id,
            current_tenant_id="tenant_alpha",
        )

    # Verify that Beta's order was untouched (still PENDING)
    beta_order = get_payment_order(beta_order_id)
    assert beta_order is not None
    assert beta_order["payment_status"] == PaymentStatus.PENDING.value


def test_worker_reconciler_same_tenant_succeeds():
    """Proves that a worker executing for the legitimate tenant succeeds."""
    now = datetime.now(timezone.utc)
    alpha_order_id = "ORD-ALPHA-VALID-01"

    save_payment_order(
        tenant_id="tenant_alpha",
        order_id=alpha_order_id,
        amount=150000,
        expired_at=now - timedelta(minutes=5),
        items_reserved=[{"item_id": "CONSULT_01", "quantity": 1}],
        payment_status=PaymentStatus.PENDING,
    )

    result = reconcile_single_order(
        order_id=alpha_order_id,
        current_tenant_id="tenant_alpha",
    )
    assert result["status"] == "SUCCESS"
    assert result["rows_affected"] == 1

    alpha_order = get_payment_order(alpha_order_id)
    assert alpha_order is not None
    assert alpha_order["payment_status"] == PaymentStatus.EXPIRED.value


def test_worker_reconciler_missing_tenant_id_raises_value_error():
    """Proves that empty or missing tenant_id in worker execution raises ValueError."""
    with pytest.raises(ValueError, match="current_tenant_id is mandatory"):
        reconcile_single_order(
            order_id="ORD-ANY-01",
            current_tenant_id="",
        )


# -----------------------------------------------------------------------------
# 2. Database Worker Mutation Cross-Tenant Isolation (0 Rows Affected)
# -----------------------------------------------------------------------------
def test_worker_db_mutation_cross_tenant_rejected_zero_rows():
    """
    Simulates a worker job executing inside tenant_transaction for Tenant Alpha.
    When attempting to maliciously update an order belonging to Tenant Beta using only
    the target order ID, the mutation affects EXACTLY 0 rows via PostgreSQL RLS enforcement.
    Also verifies positive control: Tenant Alpha can update its own order.
    """
    alpha_tenant_id = "00000000-0000-0000-0000-00000000000a"
    beta_tenant_id = "00000000-0000-0000-0000-00000000000b"
    test_beta_order_id = "test-worker-beta-order-999"
    test_alpha_order_id = "test-worker-alpha-order-111"

    if not os.getenv("POSTGRES_PASSWORD") and not os.getenv("DATABASE_URL"):
        pytest.fail("PostgreSQL credentials missing in environment. P1-B mandates live DB verification.")

    try:
        conn = get_db_connection()
        try:
            conn.set_session(readonly=False)
        except Exception:
            pass
    except Exception as exc:
        pytest.fail(f"PostgreSQL connection failed. P1-B mandates live DB verification: {exc}")

    try:
        # 1. Setup/Seed: Create orders for Tenant Beta and Tenant Alpha in administrative context
        cur = conn.cursor()
        
        # Clean up any leftover test orders
        cur.execute("DELETE FROM public.orders WHERE id IN (%s, %s);", (test_beta_order_id, test_alpha_order_id))
        
        # Seed Tenant Beta order
        cur.execute(
            """
            INSERT INTO public.orders (id, tenant_id, tenant_slug, product_id, product_title, customer_name, customer_phone, status, gross_amount, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, status = EXCLUDED.status;
            """,
            (test_beta_order_id, beta_tenant_id, "tenant_beta", "prod_test_01", "Test Product", "Beta Customer", "62899999999", "PENDING", 250000),
        )

        # Seed Tenant Alpha order (for positive control)
        cur.execute(
            """
            INSERT INTO public.orders (id, tenant_id, tenant_slug, product_id, product_title, customer_name, customer_phone, status, gross_amount, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, status = EXCLUDED.status;
            """,
            (test_alpha_order_id, alpha_tenant_id, "tenant_alpha", "prod_test_01", "Test Product", "Alpha Customer", "62811111111", "PENDING", 150000),
        )
        conn.commit()
        cur.close()

        # 2. Cross-Tenant Attack Execution & Positive Control
        # Enter tenant session via tenant_transaction(alpha_tenant_id, conn)
        with tenant_transaction(alpha_tenant_id, conn):
            worker_cur = conn.cursor()
            
            # Cross-Tenant Attack: Tenant Alpha's worker tries to maliciously update Beta's order using ONLY order ID
            # (PostgreSQL RLS performs the enforcement; no tenant_id condition in WHERE)
            worker_cur.execute(
                """
                UPDATE public.orders 
                SET status = 'TAMPERED', updated_at = NOW() 
                WHERE id = %s;
                """,
                (test_beta_order_id,),
            )
            affected = worker_cur.rowcount
            
            # PROOF: 0 rows affected! RLS hides and blocks foreign row.
            assert affected == 0, f"Cross-tenant breach! Worker affected {affected} rows."

            # 4. Positive Control: Tenant Alpha CAN successfully update an order legitimately owned by Tenant Alpha
            worker_cur.execute(
                """
                UPDATE public.orders 
                SET status = 'PROCESSED', updated_at = NOW() 
                WHERE id = %s;
                """,
                (test_alpha_order_id,),
            )
            alpha_affected = worker_cur.rowcount
            assert alpha_affected == 1, f"Positive control failed! Expected 1 row affected for owned order, got {alpha_affected}."

            worker_cur.close()

        # 3. Privilege Verification via administrative connection
        admin_cur = conn.cursor()
        
        # Verify Beta order remains untampered (still PENDING)
        admin_cur.execute("SELECT status FROM public.orders WHERE id = %s;", (test_beta_order_id,))
        beta_status_row = admin_cur.fetchone()
        assert beta_status_row is not None, "Beta order missing during verification!"
        assert beta_status_row[0] == "PENDING", f"Security violation! Beta order status was tampered: {beta_status_row[0]}"

        # Verify Alpha order was legitimately updated to PROCESSED
        admin_cur.execute("SELECT status FROM public.orders WHERE id = %s;", (test_alpha_order_id,))
        alpha_status_row = admin_cur.fetchone()
        assert alpha_status_row is not None, "Alpha order missing during verification!"
        assert alpha_status_row[0] == "PROCESSED", f"Positive control verification failed: expected PROCESSED, got {alpha_status_row[0]}"

        # Clean up seeded orders
        admin_cur.execute("DELETE FROM public.orders WHERE id IN (%s, %s);", (test_beta_order_id, test_alpha_order_id))
        conn.commit()
        admin_cur.close()

    finally:
        close_and_reset_connection(conn)


# -----------------------------------------------------------------------------
# 3. Storage / Media Worker Cross-Tenant Rejection (PermissionError)
# -----------------------------------------------------------------------------
def test_worker_storage_cross_tenant_access_raises_permission_error():
    """
    Simulates an asynchronous media / video processing worker executing for Tenant Alpha.
    When attempting to access or download private assets belonging to Tenant Beta,
    R2 storage client raises PermissionError immediately.
    """
    with pytest.raises(PermissionError, match="Cross-tenant storage access forbidden"):
        generate_presigned_download_url(
            object_key="tenants/tenant_beta/private/master_recording.mp4",
            current_tenant_id="tenant_alpha",
            expires_in=300,
        )


# -----------------------------------------------------------------------------
# 4. Elevated Worker Connection Hygiene & State Reset (P1-E)
# -----------------------------------------------------------------------------
def test_worker_elevated_transaction_hygiene_and_state_reset():
    """
    CTO Directive 10 (P1-E):
    Proves that worker_elevated_transaction guarantees strict connection hygiene:
    1. Operates under elevated service_role inside the context block.
    2. Guaranteed try/finally execution executes RESET ROLE; RESET ALL;.
    3. Returning to pool has zero state leakage.
    """
    if not os.getenv("POSTGRES_PASSWORD") and not os.getenv("DATABASE_URL"):
        pytest.fail("PostgreSQL credentials missing - P1-B prohibits skipping database tests.")

    try:
        conn = get_db_connection()
    except Exception as exc:
        pytest.fail(f"PostgreSQL connection failed - P1-B prohibits skipping: {exc}")

    try:
        # Before entering: check baseline session
        with conn.cursor() as cur:
            cur.execute("SELECT current_user;")
            base_user = cur.fetchone()[0]

        # Inside elevated worker transaction
        with worker_elevated_transaction("audit_p1_worker", conn):
            with conn.cursor() as cur:
                cur.execute("SELECT current_user;")
                elevated_user = cur.fetchone()[0]
                assert elevated_user == "service_role", f"Expected elevated service_role, got {elevated_user}"

        # After exiting: verify RESET ROLE; RESET ALL; reverted role to baseline
        with conn.cursor() as cur:
            cur.execute("SELECT current_user;")
            post_user = cur.fetchone()[0]
            assert post_user == base_user, f"Expected {base_user}, got {post_user}"
            assert post_user != "service_role", "Pool contaminated: service_role leaked into session!"
    finally:
        close_worker_db_connection(conn, "audit_p1_worker")
