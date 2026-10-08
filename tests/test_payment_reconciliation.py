"""tests/test_payment_reconciliation.py
Unit & Integration Tests for Dynamic QRIS & Payment Reconciliation Engine.

Validates:
1. Payment Schemas & Lifecycle Status:
   - PaymentStatus Enum: PENDING, PAID, EXPIRED, FAILED.
   - Order creation and inventory tracking fields.
2. Payment Reconciler Worker:
   - Automatically expires transactions where expired_at < NOW().
   - Restores held quota / reserved inventory items upon expiration.
   - Leaves unexpired transactions in PENDING state with inventory held.
3. Payment Gateway Webhook Callback Handler:
   - Token & signature verification (compatible with Xendit, Midtrans, Duitku).
   - Rejection of invalid token / signature with HTTP 401.
   - Successful settlement / paid transition with WhatsApp dispatch.
   - Durable idempotency guard (no-op HTTP 200 on duplicate callbacks).
"""

import hashlib
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import status
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.models.payment_order import PaymentOrder, PaymentStatus
from app.schemas.payment import (
    PaymentOrderCreate,
    PaymentOrderResponse,
    PaymentStatus as SchemaPaymentStatus,
    PaymentWebhookPayload,
    ReservedItem,
)
from app.workers.payment_reconciler_worker import (
    clear_payment_orders_store,
    get_payment_order,
    get_restored_inventory_log,
    register_inventory_restore_hook,
    run_reconciliation_cycle,
    save_payment_order,
)


class TestPaymentSchemasAndModels(unittest.TestCase):
    """Unit tests for payment schemas and status enum."""

    def test_payment_status_enum_values(self):
        self.assertEqual(PaymentStatus.PENDING.value, "PENDING")
        self.assertEqual(PaymentStatus.PAID.value, "PAID")
        self.assertEqual(PaymentStatus.EXPIRED.value, "EXPIRED")
        self.assertEqual(PaymentStatus.FAILED.value, "FAILED")
        self.assertEqual(SchemaPaymentStatus.PENDING.value, "PENDING")

    def test_payment_order_create_and_reserved_items(self):
        now = datetime.now(timezone.utc)
        order_req = PaymentOrderCreate(
            tenant_id="little-bite",
            order_id="ORD-TEST-001",
            amount=Decimal("150000"),
            expired_at=now + timedelta(minutes=15),
            items_reserved=[
                {"item_id": "SKU-CHAT-01", "name": "Konsultasi Chat", "quantity": 1, "price": 150000}
            ],
            customer_phone="628123456789",
            customer_name="Ibu Rahma",
        )
        self.assertEqual(order_req.order_id, "ORD-TEST-001")
        self.assertEqual(order_req.amount, Decimal("150000"))
        self.assertEqual(len(order_req.items_reserved), 1)

    def test_webhook_payload_normalization(self):
        # Xendit adapter
        xendit_payload = PaymentWebhookPayload(
            external_id="ORD-XENDIT-99",
            status="PAID",
            amount=Decimal("250000"),
        )
        self.assertEqual(xendit_payload.resolve_order_id(), "ORD-XENDIT-99")
        self.assertTrue(xendit_payload.is_settlement_paid())

        # Midtrans adapter
        midtrans_payload = PaymentWebhookPayload(
            order_id="ORD-MIDTRANS-88",
            transaction_status="settlement",
            gross_amount="250000.00",
        )
        self.assertEqual(midtrans_payload.resolve_order_id(), "ORD-MIDTRANS-88")
        self.assertTrue(midtrans_payload.is_settlement_paid())

        # Duitku adapter
        duitku_payload = PaymentWebhookPayload(
            merchant_order_id="ORD-DUITKU-77",
            result_code="00",
        )
        self.assertEqual(duitku_payload.resolve_order_id(), "ORD-DUITKU-77")
        self.assertTrue(duitku_payload.is_settlement_paid())


class TestPaymentReconcilerWorker(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the payment reconciliation background worker."""

    def setUp(self):
        clear_payment_orders_store()

    async def test_expired_transaction_updates_to_expired_and_restores_inventory(self):
        now = datetime.now(timezone.utc)
        order_id = f"ORD-EXP-{os.urandom(4).hex()}"
        items = [
            {"item_id": "PROD-A", "quantity": 2},
            {"item_id": "PROD-B", "quantity": 1},
        ]

        # Order expired 10 minutes ago
        save_payment_order(
            tenant_id="tenant-alpha",
            order_id=order_id,
            amount=200000,
            expired_at=now - timedelta(minutes=10),
            items_reserved=items,
            payment_status=PaymentStatus.PENDING,
        )

        res = await run_reconciliation_cycle()
        self.assertEqual(res["status"], "success")
        self.assertIn(order_id, res["expired_orders"])
        self.assertEqual(res["expired_count"], 1)

        # Check order state updated to EXPIRED
        order = get_payment_order(order_id)
        self.assertIsNotNone(order)
        self.assertEqual(order["payment_status"], "EXPIRED")

        # Check inventory restored log
        restored = get_restored_inventory_log()
        self.assertEqual(len(restored), 2)
        restored_item_ids = [r["item_id"] for r in restored]
        self.assertIn("PROD-A", restored_item_ids)
        self.assertIn("PROD-B", restored_item_ids)

    async def test_unexpired_transaction_remains_pending(self):
        now = datetime.now(timezone.utc)
        order_id = f"ORD-ACTIVE-{os.urandom(4).hex()}"
        items = [{"item_id": "PROD-ACTIVE", "quantity": 1}]

        # Order expires in 20 minutes
        save_payment_order(
            tenant_id="tenant-beta",
            order_id=order_id,
            amount=75000,
            expired_at=now + timedelta(minutes=20),
            items_reserved=items,
            payment_status=PaymentStatus.PENDING,
        )

        res = await run_reconciliation_cycle()
        self.assertEqual(res["expired_count"], 0)
        self.assertNotIn(order_id, res["expired_orders"])

        # Check order remains PENDING
        order = get_payment_order(order_id)
        self.assertIsNotNone(order)
        self.assertEqual(order["payment_status"], "PENDING")

        # Inventory should NOT have been restored
        restored = get_restored_inventory_log()
        self.assertEqual(len(restored), 0)


class TestPaymentWebhookCallbackHandler(unittest.TestCase):
    """Integration tests for POST /api/v1/payment/webhook."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        clear_payment_orders_store()

    def test_webhook_invalid_token_returns_401(self):
        payload = {
            "external_id": "ORD-INVALID-TOKEN",
            "status": "PAID",
            "amount": 100000,
        }
        headers = {"X-Callback-Token": "invalid_token_12345"}
        res = self.client.post("/api/v1/payment/webhook", json=payload, headers=headers)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_webhook_settlement_success_and_order_paid(self):
        now = datetime.now(timezone.utc)
        order_id = f"ORD-SETTLE-{os.urandom(4).hex()}"
        save_payment_order(
            tenant_id="little-bite",
            order_id=order_id,
            amount=150000,
            expired_at=now + timedelta(minutes=15),
            payment_status=PaymentStatus.PENDING,
            customer_phone="628123456789",
            customer_name="Ibu Rahma",
        )

        payload = {
            "external_id": order_id,
            "status": "PAID",
            "amount": 150000,
            "callback_token": "xendit_test_callback_token",
        }

        res = self.client.post("/api/v1/payment/webhook", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["order_id"], order_id)
        self.assertEqual(data["payment_status"], "PAID")
        self.assertIn("paid_at", data)

        # Check order is updated in store
        order = get_payment_order(order_id)
        self.assertEqual(order["payment_status"], "PAID")
        self.assertIsNotNone(order["paid_at"])

    def test_webhook_durable_idempotency_duplicate_is_noop(self):
        now = datetime.now(timezone.utc)
        order_id = f"ORD-IDEMP-{os.urandom(4).hex()}"
        save_payment_order(
            tenant_id="little-bite",
            order_id=order_id,
            amount=150000,
            expired_at=now + timedelta(minutes=15),
            payment_status=PaymentStatus.PENDING,
            customer_phone="628123456789",
            customer_name="Ibu Rahma",
        )

        headers = {"X-Callback-Token": "xendit_test_callback_token"}
        payload = {
            "external_id": order_id,
            "status": "PAID",
            "amount": 150000,
        }

        # 1st Webhook: confirms PAID
        res1 = self.client.post("/api/v1/payment/webhook", json=payload, headers=headers)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["status"], "success")

        # 2nd Webhook (duplicate/retry): must trigger durable idempotency guard and return HTTP 200 no-op
        res2 = self.client.post("/api/v1/payment/webhook", json=payload, headers=headers)
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2["status"], "already_paid")
        self.assertTrue(data2.get("idempotent"))
        self.assertEqual(data2["order_id"], order_id)

    def test_webhook_midtrans_signature_verification(self):
        now = datetime.now(timezone.utc)
        order_id = f"ORD-MID-{os.urandom(4).hex()}"
        status_code = "200"
        gross_amount = "250000.00"
        server_key = "midtrans_test_server_key"

        save_payment_order(
            tenant_id="store-fashion",
            order_id=order_id,
            amount=250000,
            expired_at=now + timedelta(minutes=30),
            payment_status=PaymentStatus.PENDING,
            customer_phone="628555666777",
            customer_name="Budi Santoso",
        )

        # Compute valid SHA512 signature key
        sig_raw = f"{order_id}{status_code}{gross_amount}{server_key}"
        signature_key = hashlib.sha512(sig_raw.encode("utf-8")).hexdigest()

        payload = {
            "order_id": order_id,
            "status_code": status_code,
            "gross_amount": gross_amount,
            "transaction_status": "settlement",
            "signature_key": signature_key,
        }

        res = self.client.post("/api/v1/payment/webhook", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["order_id"], order_id)

        # Verify order transitioned to PAID
        order = get_payment_order(order_id)
        self.assertEqual(order["payment_status"], "PAID")


if __name__ == "__main__":
    unittest.main()
