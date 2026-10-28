"""tests/test_xendit_3x_idempotency_simulation.py
Automated Pytest Suite: Xendit Webhook 3x Consecutive Retry Idempotency & Side-Effect Guard.
"""

import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
import pytest

# Lazy imports inside test to prevent collection DLL load issues on Windows



@pytest.mark.asyncio
async def test_xendit_webhook_3x_consecutive_retry_idempotency():
    from starlette.testclient import TestClient
    from app.main import app
    from app.core.database import get_db_connection, init_db

    await init_db()

    test_uid = uuid.uuid4().hex[:8]
    test_order_id = f"ORD-PYTEST-{test_uid}"
    test_event_id = f"evt_xendit_pytest_{test_uid}"
    test_amount = 99000
    test_phone = "6285712345678"
    test_email = "pytest.buyer@boontrack.com"
    test_product = "Kelas Inkubasi CTWA Batch 1 - Paket Starter"
    test_tenant = "onlineboost"
    test_token = os.getenv("XENDIT_CALLBACK_TOKEN") or "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS"

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO orders (
                id, status, gross_amount, customer_name, customer_phone, customer_email,
                tenant_slug, product_id, product_title, created_at, updated_at
            )
            VALUES (%s, 'PENDING', %s, 'Siti Pytest', %s, %s, %s, 'ctwa-starter', %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET status = 'PENDING';
            """,
            (test_order_id, test_amount, test_phone, test_email, test_tenant, test_product)
        )
        conn.commit()
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
            "customer_phone": test_phone,
            "customer_email": test_email,
            "product_name": test_product,
            "tenant_id": test_tenant,
        }
    }
    headers = {
        "x-callback-token": test_token,
        "Content-Type": "application/json"
    }

    wa_calls = []
    capi_calls = []

    async def mock_wa(phone, external_id, amount, tenant_id="onlineboost", product_name=None):
        wa_calls.append({"phone": phone, "order_id": external_id})

    async def mock_onlineboost_fulfill(order_id, buyer_name=None, buyer_phone=None, amount=None, tenant_id="onlineboost"):
        wa_calls.append({"phone": buyer_phone, "order_id": order_id})

    async def mock_capi(external_id, amount, phone=None, email=None, product_name=None, currency="IDR", tenant_id="onlineboost"):
        capi_calls.append({"order_id": external_id, "amount": amount})

    import concurrent.futures

    def fire_request():
        with TestClient(app) as local_client:
            res = local_client.post("/api/v1/payments/xendit/callback", json=payload, headers=headers)
            return res.status_code, res.json()

    with patch("app.routes.xendit.send_whatsapp_payment_notification", side_effect=mock_wa), \
         patch("app.services.ctwa_fulfillment_service.fulfill_onlineboost_ctwa_order", side_effect=mock_onlineboost_fulfill), \
         patch("app.routes.xendit.send_capi_task", side_effect=mock_capi), \
         patch("app.routes.xendit.dispatch_payment_success_notifications", new_callable=AsyncMock), \
         patch("app.services.digital_fulfillment_service.fulfill_if_digital", new_callable=AsyncMock):

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(fire_request) for _ in range(3)]
            responses = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Verifikasi Invariant Concurrency
    # 1. Seluruh 3 respons konkuren wajib HTTP 200 OK
    assert len(responses) == 3
    for code, body in responses:
        assert code == 200, f"Concurrent request returned {code}: {body}"

    # 2. Tepat 1 request berstatus 'SUCCESS' dan tepat 2 request berstatus 'ALREADY_PROCESSED' (idempotent=True)
    successes = [b for code, b in responses if b.get("status") == "SUCCESS"]
    already_processed = [b for code, b in responses if b.get("status") == "ALREADY_PROCESSED" and b.get("idempotent") is True]

    assert len(successes) == 1, f"Expected exactly 1 SUCCESS, got {len(successes)}: {responses}"
    assert len(already_processed) == 2, f"Expected exactly 2 ALREADY_PROCESSED, got {len(already_processed)}: {responses}"

    # 3. Database invariants
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT status FROM orders WHERE id = %s;", (test_order_id,))
        assert cur.fetchone()[0] in ("LUNAS", "PAID")

        cur.execute("SELECT count(*) FROM financial_ledger WHERE order_id = %s;", (test_order_id,))
        assert cur.fetchone()[0] == 1  # TEPAT 1 KALI

        cur.execute("DELETE FROM financial_ledger WHERE order_id = %s;", (test_order_id,))
        cur.execute("DELETE FROM orders WHERE id = %s;", (test_order_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    # 4. WhatsApp Side Effect: TEPAT 1 KALI
    assert len(wa_calls) == 1
    assert wa_calls[0]["order_id"] == test_order_id

    # 5. Meta CAPI Side Effect: TEPAT 1 KALI
    assert len(capi_calls) == 1
    assert capi_calls[0]["order_id"] == test_order_id
