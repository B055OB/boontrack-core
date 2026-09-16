"""test_xendit_hardening.py
Verification test script for Xendit webhook live hardening & idempotency.
Tests:
1. First webhook execution -> marks order as LUNAS/PAID, records financial_ledger & payment_events
2. Database assertions: order status == 'PAID'/'LUNAS', payment_events status == 'PROCESSED', financial_ledger entry created
3. Second duplicate webhook execution -> returns ALREADY_PROCESSED with idempotent=True
"""

import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from app.core.database import get_db_connection, init_db
from app.routes.xendit import process_xendit_webhook_core


async def run_verification():
    print("=" * 60)
    print("RUNNING XENDIT WEBHOOK HARDENING & IDEMPOTENCY TEST")
    print("=" * 60)

    # Ensure DB tables exist
    await init_db()

    # Generate unique test IDs
    test_uid = uuid.uuid4().hex[:8]
    test_order_id = f"TEST-ORD-{test_uid}"
    test_event_id = f"evt_xendit_{test_uid}"
    test_amount = 75000
    test_token = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN") or "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS"

    # Pre-create test order in DB with status PENDING
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO orders (id, status, gross_amount, customer_name, customer_phone, tenant_slug, product_id, product_title)
            VALUES (%s, 'PENDING', %s, 'Budi Tester', '628123456789', 'onlineboost', 'prod_test_01', 'Paket Hardening Test')
            ON CONFLICT (id) DO UPDATE SET status = 'PENDING';
            """,
            (test_order_id, test_amount)
        )
        conn.commit()
        print(f"[SETUP] Created order '{test_order_id}' with status PENDING.")
    finally:
        cur.close()
        conn.close()

    payload = {
        "id": test_event_id,
        "event": "invoice.paid",
        "data": {
            "id": test_event_id,
            "external_id": test_order_id,
            "reference_id": test_order_id,
            "amount": test_amount,
            "paid_amount": test_amount,
            "status": "PAID",
            "payment_method": "QRIS",
            "customer_phone": "628123456789",
            "customer_email": "tester@boontrack.com",
            "product_name": "Paket Hardening Test",
            "tenant_id": "onlineboost",
        }
    }
    headers = {
        "x-callback-token": test_token
    }

    # =========================================================================
    # TEST 1: First Webhook Dispatch
    # =========================================================================
    print("\n--- TEST 1: First Webhook Dispatch (Initial Settlement) ---")
    res1 = await process_xendit_webhook_core(payload, headers)
    print(f"Response 1 HTTP Status: {res1.get('http_status')}")
    print(f"Response 1 Body: {res1.get('response')}")

    assert res1.get("http_status") == 200, f"Expected 200, got {res1.get('http_status')}"
    assert res1.get("response", {}).get("status") == "SUCCESS", "Expected status == SUCCESS"
    assert res1.get("response", {}).get("external_id") == test_order_id, "Order ID mismatch"
    print(">> TEST 1 PASSED: Webhook processed successfully.")

    # =========================================================================
    # TEST 2: Database Assertions
    # =========================================================================
    print("\n--- TEST 2: Database Assertions (State & Ledger Verification) ---")
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Check order status
        cur.execute("SELECT status FROM orders WHERE id = %s;", (test_order_id,))
        order_row = cur.fetchone()
        assert order_row is not None, "Order row not found in DB"
        print(f"DB Order Status: status='{order_row[0]}'")
        assert order_row[0] in ("LUNAS", "PAID"), f"Order status is not LUNAS/PAID: {order_row[0]}"

        # Check payment_events
        cur.execute("SELECT status, provider, event_id FROM payment_events WHERE event_id = %s;", (test_event_id,))
        event_row = cur.fetchone()
        assert event_row is not None, "payment_events entry not found"
        print(f"DB payment_events: event_id='{event_row[2]}', provider='{event_row[1]}', status='{event_row[0]}'")
        assert event_row[0] == "PROCESSED", f"payment_events status is not PROCESSED: {event_row[0]}"

        # Check financial_ledger
        cur.execute("SELECT order_id, provider, gross_amount, status FROM financial_ledger WHERE order_id = %s;", (test_order_id,))
        ledger_row = cur.fetchone()
        assert ledger_row is not None, "financial_ledger row not found"
        print(f"DB financial_ledger: order_id='{ledger_row[0]}', provider='{ledger_row[1]}', gross_amount={ledger_row[2]}, status='{ledger_row[3]}'")
        assert float(ledger_row[2]) == float(test_amount), f"Ledger amount mismatch: {ledger_row[2]} != {test_amount}"
        assert ledger_row[3] == "SETTLED", f"Ledger status is not SETTLED: {ledger_row[3]}"

    finally:
        cur.close()
        conn.close()
    print(">> TEST 2 PASSED: Database state, payment_events, and financial_ledger verified.")

    # =========================================================================
    # TEST 3: Duplicate Webhook Replay (Idempotency Guard)
    # =========================================================================
    print("\n--- TEST 3: Duplicate Webhook Replay (Idempotency Guard) ---")
    res2 = await process_xendit_webhook_core(payload, headers)
    print(f"Response 2 HTTP Status: {res2.get('http_status')}")
    print(f"Response 2 Body: {res2.get('response')}")

    assert res2.get("http_status") == 200, f"Expected 200, got {res2.get('http_status')}"
    resp2_body = res2.get("response", {})
    assert resp2_body.get("status") == "ALREADY_PROCESSED", f"Expected ALREADY_PROCESSED, got {resp2_body.get('status')}"
    assert resp2_body.get("idempotent") is True, "Expected idempotent == True"
    print(">> TEST 3 PASSED: Duplicate request immediately acknowledged with ALREADY_PROCESSED (idempotent=True).")

    # Cleanup test data
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM financial_ledger WHERE order_id = %s;", (test_order_id,))
        cur.execute("DELETE FROM payment_events WHERE event_id = %s;", (test_event_id,))
        cur.execute("DELETE FROM orders WHERE id = %s;", (test_order_id,))
        conn.commit()
        print(f"\n[CLEANUP] Removed test records for '{test_order_id}'.")
    finally:
        cur.close()
        conn.close()

    print("\n" + "=" * 60)
    print("ALL 3 XENDIT HARDENING ASSERTIONS PASSED SUCCESSFULLY! (100% GREEN)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_verification())
