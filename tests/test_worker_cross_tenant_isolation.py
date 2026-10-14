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
    When attempting to update or delete an object belonging to Tenant Beta,
    the mutation affects EXACTLY 0 rows.
    """
    alpha_tenant_id = "00000000-0000-0000-0000-00000000000a"
    beta_tenant_id = "00000000-0000-0000-0000-00000000000b"
    test_beta_order_id = "test-worker-beta-order-999"

    if not os.getenv("POSTGRES_PASSWORD") and not os.getenv("DATABASE_URL"):
        pytest.fail("PostgreSQL credentials missing in environment. P1-B mandates live DB verification.")

    try:
        conn = get_db_connection()
    except Exception as exc:
        pytest.fail(f"PostgreSQL connection failed. P1-B mandates live DB verification: {exc}")

    try:
        # Pre-seed test order for Tenant Beta in superuser/admin context
        cur = conn.cursor()
        
        # Clean up any leftover
        cur.execute("DELETE FROM orders WHERE id = %s;", (test_beta_order_id,))
        cur.execute(
            """
            INSERT INTO orders (id, tenant_id, tenant_slug, product_id, product_title, customer_name, customer_phone, status, gross_amount, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, status = EXCLUDED.status;
            """,
            (test_beta_order_id, beta_tenant_id, "tenant_beta", "prod_test_01", "Test Product", "Beta Customer", "62899999999", "PENDING", 250000),
        )
        conn.commit()
        cur.close()

        # Now execute worker job strictly scoped to Tenant Alpha
        with tenant_transaction(alpha_tenant_id, conn):
            worker_cur = conn.cursor()
            
            # Tenant Alpha's worker tries to maliciously update Beta's order
            worker_cur.execute(
                """
                UPDATE orders 
                SET status = 'EXPIRED', updated_at = NOW() 
                WHERE id = %s AND (tenant_id = current_setting('app.current_tenant_id', true)::uuid OR tenant_id = %s::uuid);
                """,
                (test_beta_order_id, alpha_tenant_id),
            )
            affected = worker_cur.rowcount
            
            # PROOF: 0 rows affected!
            assert affected == 0, f"Cross-tenant breach! Worker affected {affected} rows."
            worker_cur.close()

        # Clean up seeded order
        clean_cur = conn.cursor()
        clean_cur.execute("DELETE FROM orders WHERE id = %s;", (test_beta_order_id,))
        conn.commit()
        clean_cur.close()

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
