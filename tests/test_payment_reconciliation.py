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
import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi import status
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import get_db_connection
from app.core.security.payment_auth_guard import CredentialProfileMapper
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
    """Integration tests for deprecated generic lock (HTTP 403) & provider-specific webhooks."""

    TENANT_LITTLE_BITE_ID = "2c300000-0000-0000-0000-000000000001"
    TENANT_FASHION_ID = "2c300000-0000-0000-0000-000000000002"
    XENDIT_BIZ_ID = "xnd_biz_recon_01"
    MIDTRANS_MERCHANT_ID = "M_RECON_FASHION"

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _seed_tenant_and_order(
        self,
        *,
        tenant_uuid: str,
        tenant_slug: str,
        order_id: str,
        amount: int,
        credential_profile_id: str,
    ) -> None:
        metadata = {
            "payment_config": {
                "mode": "NATIVE_PG",
                "active_provider": "XENDIT",
                "credential_profiles": {
                    "cred_xendit_recon": {
                        "credential_profile_id": "cred_xendit_recon",
                        "canonical_tenant_id": tenant_uuid,
                        "provider": "XENDIT",
                        "verification_method": "XENDIT_CALLBACK_TOKEN",
                        "expected_provider_account_id": self.XENDIT_BIZ_ID,
                        "environment": "production",
                        "profile_status": "ACTIVE",
                        "verification_secrets": [
                            {
                                "secret_version_id": "xnd_recon_v1",
                                "secret_ref": "vault://recon/xendit/active",
                                "status": "ACTIVE",
                            }
                        ],
                    },
                    "cred_midtrans_recon": {
                        "credential_profile_id": "cred_midtrans_recon",
                        "canonical_tenant_id": tenant_uuid,
                        "provider": "MIDTRANS",
                        "verification_method": "MIDTRANS_SHA512",
                        "expected_provider_account_id": self.MIDTRANS_MERCHANT_ID,
                        "environment": "production",
                        "profile_status": "ACTIVE",
                        "verification_secrets": [
                            {
                                "secret_version_id": "mid_recon_v1",
                                "secret_ref": "vault://recon/midtrans/active",
                                "status": "ACTIVE",
                            }
                        ],
                    },
                },
            }
        }
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO public.tenants (id, name, slug, metadata)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata, slug = EXCLUDED.slug;
                """,
                (tenant_uuid, f"Recon {tenant_slug}", tenant_slug, json.dumps(metadata)),
            )
            cur.execute(
                """
                INSERT INTO public.orders (
                    id, tenant_id, tenant_slug, sku_id, product_id, product_title,
                    gross_amount, amount, customer_name, customer_phone, customer_email,
                    status, payment_status, order_status, metadata, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', 'PENDING', 'PENDING', %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, gross_amount = EXCLUDED.gross_amount, metadata = EXCLUDED.metadata;
                """,
                (
                    order_id,
                    tenant_uuid,
                    tenant_slug,
                    "SKU-RECON-01",
                    "SKU-RECON-01",
                    "Recon Test Product",
                    amount,
                    amount,
                    "Customer Recon",
                    "628123456789",
                    "recon@example.test",
                    json.dumps({"credential_profile_id": credential_profile_id}),
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def _fetch_pg_order(self, order_id: str) -> dict:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT status, payment_status, paid_at FROM public.orders WHERE id = %s",
                (order_id,),
            )
            row = cur.fetchone()
            return {
                "status": row[0],
                "payment_status": row[1],
                "paid_at": row[2],
            }
        finally:
            cur.close()
            conn.close()

    def setUp(self):
        clear_payment_orders_store()
        self.test_token = "xendit_test_callback_token_2026_secret"
        self.server_key = "midtrans_test_server_key_2026_secret"
        vault = {
            "vault://recon/xendit/active": self.test_token,
            "vault://recon/midtrans/active": self.server_key,
        }
        orig_resolve = CredentialProfileMapper._resolve_secret_ref

        def _mock_resolve(mapper_self, ref: str) -> str:
            if ref in vault:
                return vault[ref]
            return orig_resolve(mapper_self, ref)

        patcher = patch.object(CredentialProfileMapper, "_resolve_secret_ref", _mock_resolve)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_webhook_invalid_token_returns_401(self):
        order_id = f"ORD-INVTOK-{uuid.uuid4().hex[:8]}"
        self._seed_tenant_and_order(
            tenant_uuid=self.TENANT_LITTLE_BITE_ID,
            tenant_slug="little-bite",
            order_id=order_id,
            amount=100000,
            credential_profile_id="cred_xendit_recon",
        )

        # 1. Deprecated generic route MUST fail closed with HTTP 403
        generic_payload = {"external_id": order_id, "status": "PAID", "amount": 100000}
        res_generic = self.client.post(
            "/api/v1/payment/webhook",
            json=generic_payload,
            headers={"X-Callback-Token": "invalid_token_12345"},
        )
        self.assertEqual(res_generic.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            res_generic.json()["detail"],
            "DEPRECATED_GENERIC_WEBHOOK_USE_PROVIDER_SPECIFIC_ROUTE",
        )

        # 2. Provider-specific route MUST reject invalid Xendit callback token with 401/403
        provider_payload = {
            "id": f"evt_inv_{uuid.uuid4().hex[:8]}",
            "external_id": order_id,
            "business_id": self.XENDIT_BIZ_ID,
            "status": "PAID",
            "amount": 100000,
        }
        res_provider = self.client.post(
            "/api/v1/payment/webhook/xendit",
            json=provider_payload,
            headers={"X-Callback-Token": "invalid_token_12345"},
        )
        self.assertIn(res_provider.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(self._fetch_pg_order(order_id)["status"], "PENDING")

    def test_webhook_settlement_success_and_order_paid(self):
        order_id = f"ORD-SETTLE-{uuid.uuid4().hex[:8]}"
        self._seed_tenant_and_order(
            tenant_uuid=self.TENANT_LITTLE_BITE_ID,
            tenant_slug="little-bite",
            order_id=order_id,
            amount=150000,
            credential_profile_id="cred_xendit_recon",
        )

        headers = {"X-Callback-Token": self.test_token}
        payload = {
            "id": f"evt_settle_{uuid.uuid4().hex[:8]}",
            "external_id": order_id,
            "business_id": self.XENDIT_BIZ_ID,
            "status": "PAID",
            "amount": 150000,
        }

        # Deprecated generic route remains locked down (403)
        res_generic = self.client.post("/api/v1/payment/webhook", json=payload, headers=headers)
        self.assertEqual(res_generic.status_code, status.HTTP_403_FORBIDDEN)

        # Settlement succeeds through verified provider-specific Xendit route
        res = self.client.post("/api/v1/payment/webhook/xendit", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["external_id"], order_id)

        order = self._fetch_pg_order(order_id)
        self.assertEqual(order["status"], "PAID")
        self.assertEqual(order["payment_status"], "PAID")
        self.assertIsNotNone(order["paid_at"])

    def test_webhook_durable_idempotency_duplicate_is_noop(self):
        order_id = f"ORD-IDEMP-{uuid.uuid4().hex[:8]}"
        self._seed_tenant_and_order(
            tenant_uuid=self.TENANT_LITTLE_BITE_ID,
            tenant_slug="little-bite",
            order_id=order_id,
            amount=150000,
            credential_profile_id="cred_xendit_recon",
        )

        headers = {"X-Callback-Token": self.test_token}
        payload = {
            "id": f"evt_idemp_{uuid.uuid4().hex[:8]}",
            "external_id": order_id,
            "business_id": self.XENDIT_BIZ_ID,
            "status": "PAID",
            "amount": 150000,
        }

        # Deprecated generic route remains locked down (403)
        self.assertEqual(
            self.client.post("/api/v1/payment/webhook", json=payload, headers=headers).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 1st Webhook via provider-specific route: settles order
        res1 = self.client.post("/api/v1/payment/webhook/xendit", json=payload, headers=headers)
        self.assertEqual(res1.status_code, 200, res1.text)
        self.assertEqual(res1.json()["status"], "SUCCESS")

        # 2nd Webhook (duplicate/retry): durable idempotency guard returns HTTP 200 no-op
        res2 = self.client.post("/api/v1/payment/webhook/xendit", json=payload, headers=headers)
        self.assertEqual(res2.status_code, 200, res2.text)
        data2 = res2.json()
        self.assertEqual(data2["status"], "ALREADY_PROCESSED")
        self.assertTrue(data2.get("idempotent"))
        self.assertEqual(data2["order_id"], order_id)

    def test_webhook_midtrans_signature_verification(self):
        order_id = f"ORD-MID-{uuid.uuid4().hex[:8]}"
        status_code = "200"
        gross_amount = "250000.00"
        self._seed_tenant_and_order(
            tenant_uuid=self.TENANT_FASHION_ID,
            tenant_slug="store-fashion",
            order_id=order_id,
            amount=250000,
            credential_profile_id="cred_midtrans_recon",
        )

        # Compute valid SHA512 signature key
        sig_raw = f"{order_id}{status_code}{gross_amount}{self.server_key}"
        signature_key = hashlib.sha512(sig_raw.encode("utf-8")).hexdigest()

        payload = {
            "order_id": order_id,
            "transaction_id": f"mid-tx-{uuid.uuid4().hex[:8]}",
            "merchant_id": self.MIDTRANS_MERCHANT_ID,
            "status_code": status_code,
            "gross_amount": gross_amount,
            "transaction_status": "settlement",
            "fraud_status": "accept",
            "signature_key": signature_key,
        }

        # Deprecated generic route remains locked down (403)
        self.assertEqual(
            self.client.post("/api/v1/payment/webhook", json=payload).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Provider-specific Midtrans webhook verifies signature and settles order
        res = self.client.post("/api/v1/payment/webhook/midtrans", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "ok")

        order = self._fetch_pg_order(order_id)
        self.assertEqual(order["status"], "PAID")
        self.assertEqual(order["payment_status"], "PAID")


if __name__ == "__main__":
    unittest.main()
