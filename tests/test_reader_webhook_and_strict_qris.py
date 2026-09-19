"""tests/test_reader_webhook_and_strict_qris.py
Test suite verifying:
1. Endpoint Reader Notification (/api/v1/reader/notification) strict tenant_id filtering and cross-tenant isolation.
2. Strict QRIS Config validation and elimination of platform account fallbacks.
"""

import pytest
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app
from app.utils.qris_generator import (
    generate_dynamic_qris_payload,
    render_qris_bytes,
    STANDARD_MASTER_QRIS,
)
from app.services.payment_service import PaymentService
from app.engines.generic_tenant_engine import GenericTenantEngine
from app.schemas.tenant_config import (
    TenantConfig,
    TenantPaymentConfig,
    TenantIdentity,
    TenantPersona,
    TenantMenuConfig,
    MenuItem,
)
from app.routes.d2c_order_routes import QuickQrisRequest, quick_qris_checkout_endpoint
from app.schemas.context import TenantRuntimeContext


class TestReaderNotificationStrictIsolation(unittest.TestCase):
    """Verifies that /api/v1/reader/notification strictly filters by tenant_id and isolates orders."""

    def setUp(self):
        self.client = TestClient(app)

    def test_missing_tenant_id_in_body_and_headers_returns_400(self):
        """Request without tenant_id must be rejected with HTTP 400."""
        payload = {
            "app_source": "com.gojek.gopay.merchant",
            "raw_text": "Rp150.000 diterima GoPay dari Budi",
            "notification_id": "notif-001",
        }
        res = self.client.post("/api/v1/reader/notification", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("missing_tenant_id", res.json().get("detail", ""))

    def test_tenant_id_from_header_x_tenant_id(self):
        """Header X-Tenant-Id must be recognized when omitted from body."""
        payload = {
            "app_source": "com.gojek.gopay.merchant",
            "raw_text": "Rp75.000 diterima GoPay dari Budi",
            "notification_id": "notif-002",
        }
        res = self.client.post(
            "/api/v1/reader/notification",
            json=payload,
            headers={"X-Tenant-Id": "buzzerukm"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("tenant_id"), "buzzerukm")
        self.assertEqual(data.get("amount"), 75000.0)

    def test_tenant_id_from_header_lowercase_x_tenant_id(self):
        """Header x-tenant-id (lowercase) must be recognized."""
        payload = {
            "app_source": "com.gojek.gopay.merchant",
            "raw_text": "Rp50.000 diterima GoPay dari Siti",
            "notification_id": "notif-003",
        }
        res = self.client.post(
            "/api/v1/reader/notification",
            json=payload,
            headers={"x-tenant-id": "buzzerukm"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("tenant_id"), "buzzerukm")

    def test_cross_tenant_isolation_never_matches_other_tenant_same_nominal(self):
        """Matching nominal Rp150.000 for tenant buzzerukm must NEVER match pending order of another tenant."""
        from app.core.database import get_db_connection

        order_buzzer = "ORD-BUZZER-ISOLATION-001"
        order_other = "ORD-OTHER-ISOLATION-002"
        target_amount = 150000

        # Seed 2 pending orders for 2 different tenants with identical amounts
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO orders (id, tenant_slug, product_id, product_title, gross_amount, customer_name, customer_phone, status, correlation_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET status = 'PENDING', gross_amount = EXCLUDED.gross_amount;
        """, (order_buzzer, "buzzerukm", "prod-1", "Buzzer Campaign", target_amount, "Client Buzzer", "0811111111", "corr-buzz-001"))

        cur.execute("""
            INSERT INTO orders (id, tenant_slug, product_id, product_title, gross_amount, customer_name, customer_phone, status, correlation_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET status = 'PENDING', gross_amount = EXCLUDED.gross_amount;
        """, (order_other, "otherstore", "prod-2", "Other Product", target_amount, "Client Other", "0822222222", "corr-other-002"))
        conn.commit()
        cur.close()
        conn.close()

        with patch("app.services.meta_capi_service.send_meta_capi_purchase", new_callable=AsyncMock) as mock_capi:
            mock_capi.return_value = {"status": "success"}

            # Send reader notification specifically for buzzerukm
            payload = {
                "tenant_id": "buzzerukm",
                "app_source": "com.gojek.gopay.merchant",
                "raw_text": f"Penerimaan Pembayaran Rp {target_amount:,} dari Client Buzzer",
                "notification_id": "notif-isolate-001",
            }
            res = self.client.post("/api/v1/reader/notification", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data.get("status"), "PROCESSED")
            self.assertEqual(data.get("matched_order_id"), order_buzzer)

            # Verify in DB: buzzerukm order is PAID, but otherstore order is still PENDING
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, status FROM orders WHERE id = %s;", (order_buzzer,))
            buzzer_db = cur.fetchone()
            cur.execute("SELECT id, status FROM orders WHERE id = %s;", (order_other,))
            other_db = cur.fetchone()
            cur.close()
            conn.close()

            self.assertEqual(buzzer_db[1], "PAID")
            self.assertEqual(other_db[1], "PENDING")  # Must NOT be affected!

    def test_unmatched_notification_returns_unmatched_and_leaves_orders(self):
        """Notification with unknown amount or no pending orders returns UNMATCHED."""
        payload = {
            "tenant_id": "buzzerukm",
            "app_source": "com.gojek.gopay.merchant",
            "raw_text": "Penerimaan Pembayaran Rp 999.999 dari Unknown",
            "notification_id": "notif-unmatched-001",
        }
        res = self.client.post("/api/v1/reader/notification", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "UNMATCHED")
        self.assertIsNone(data.get("matched_order_id"))


class TestStrictQRISConfigAndNoPlatformFallback(unittest.IsolatedAsyncioTestCase):
    """Verifies that unconfigured tenants are strictly rejected without fallback to BoonTrack DANA Bisnis."""

    def test_generate_dynamic_qris_payload_rejects_empty_payload(self):
        """Empty or invalid static_payload must raise ValueError and NOT fall back to BoonTrack DANA Bisnis."""
        with self.assertRaises(ValueError) as ctx:
            generate_dynamic_qris_payload("", 50000)
        self.assertIn("MERCHANT_QRIS_NOT_CONFIGURED", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            generate_dynamic_qris_payload("INVALID_PAYLOAD_STRING", 50000)
        self.assertIn("MERCHANT_QRIS_NOT_CONFIGURED", str(ctx.exception))

    def test_render_qris_bytes_rejects_invalid_payload(self):
        """render_qris_bytes must raise ValueError and NOT fall back to BoonTrack DANA Bisnis."""
        with self.assertRaises(ValueError) as ctx:
            render_qris_bytes("")
        self.assertIn("MERCHANT_QRIS_NOT_CONFIGURED", str(ctx.exception))

    def test_payment_service_create_qris_order_rejects_unconfigured_tenant(self):
        """PaymentService.create_qris_order must reject tenant orders without static_qris_payload in DB/meta."""
        with self.assertRaises(ValueError) as ctx:
            PaymentService.create_qris_order(
                user_id="user_123",
                base_amount=50000,
                tenant_id="tenant_without_qris",
                meta={}
            )
        self.assertIn("MERCHANT_QRIS_NOT_CONFIGURED", str(ctx.exception))

    async def test_generic_tenant_engine_no_fallback_to_boontrack_qris(self):
        """GenericTenantEngine must return error message and NOT fall back to BOONTRACK_STATIC_QRIS."""
        config = TenantConfig(
            identity=TenantIdentity(tenant_id="unconfigured_store", name="Unconfigured Store"),
            persona=TenantPersona(system_prompt="You are an assistant"),
            payment_config=TenantPaymentConfig(static_qris_payload=""),
            menu_config=TenantMenuConfig(
                options=[
                    MenuItem(id="1", title="Beli Produk", action="ORDER_QRIS", price_amount=50000)
                ]
            )
        )
        engine = GenericTenantEngine()
        resp = await engine.handle_message(
            tenant_config=config,
            incoming_message="1",
            user_id="user_123"
        )
        msg_text = resp if isinstance(resp, str) else resp.get("text", "")
        self.assertIn("MERCHANT_QRIS_NOT_CONFIGURED", msg_text)
        self.assertNotIn("BoonTrack", msg_text)

    @pytest.mark.asyncio
    async def test_quick_qris_checkout_rejects_unconfigured_tenant_with_422(self):
        """D2C Checkout endpoint must return HTTP 422 MERCHANT_QRIS_NOT_CONFIGURED if tenant has no QRIS config."""
        req = QuickQrisRequest(
            merchant_slug="unconfigured_tenant_slug",
            merchant_name="Unconfigured",
            product_name="Sample Item",
            customer_phone="081234567890",
            total_amount=50000,
        )
        # Mock tenant_context_resolver to return context with NO QRIS
        unconfigured_ctx = TenantRuntimeContext(
            tenant_id="unconfigured_tenant_slug",
            slug="unconfigured_tenant_slug",
            metadata={"payment_config": {"mode": "MANUAL_TRANSFER"}}
        )
        with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = unconfigured_ctx
            with pytest.raises(HTTPException) as exc_info:
                await quick_qris_checkout_endpoint(req)
            assert exc_info.value.status_code == 422
            assert exc_info.value.detail == "MERCHANT_QRIS_NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_quick_qris_checkout_rejects_nonexistent_tenant_with_422(self):
        """D2C Checkout endpoint must return HTTP 422 if tenant does not exist in DB."""
        req = QuickQrisRequest(
            merchant_slug="nonexistent_tenant_xyz",
            merchant_name="Ghost Store",
            product_name="Ghost Item",
            customer_phone="081234567890",
            total_amount=50000,
        )
        with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                await quick_qris_checkout_endpoint(req)
            assert exc_info.value.status_code == 422
            assert exc_info.value.detail == "MERCHANT_QRIS_NOT_CONFIGURED"
