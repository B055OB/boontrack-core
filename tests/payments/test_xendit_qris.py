"""tests/payments/test_xendit_qris.py
Unit & Integration Test Suite for Xendit Sandbox Dynamic QRIS & Webhook Callback.

Tests:
1. Dynamic QRIS creation with Xendit client wrapper & basic auth verification.
2. Webhook callback security: rejection of unauthorized callback tokens (HTTP 403).
3. Webhook settlement processing: triggers customer WhatsApp confirmation & Meta CAPI Purchase event.
4. Resilient idempotency: duplicate webhook calls are acknowledged without duplicate triggers.
5. Support for multiple Xendit payload shapes (wrapped 'qr_code.paid' and direct object).
"""

import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.xendit_service import XenditService, xendit_service


class TestXenditQRISIntegration(unittest.TestCase):
    """Test suite for Xendit dynamic QRIS generation and webhook handling."""

    def setUp(self):
        self.client = TestClient(app)
        xendit_service.clear_state()
        self.valid_token = "boontrack_xendit_webhook_token_secure"

    # =========================================================================
    # 1. Dynamic QRIS Generation
    # =========================================================================

    @patch("httpx.AsyncClient.post")
    def test_create_dynamic_qris_mock(self, mock_post):
        """Memvalidasi pembuatan QRIS dinamis via Xendit API dengan Basic Auth dan payload standar."""
        fake_xendit_response = MagicMock()
        fake_xendit_response.status_code = 200
        fake_xendit_response.json.return_value = {
            "id": "qr_test_uuid_12345",
            "external_id": "ORDER-TEST-001",
            "amount": 100000,
            "currency": "IDR",
            "type": "DYNAMIC",
            "status": "ACTIVE",
            "qr_string": "00020101021226570011ID.DANA.WWW...6304B7A1",
            "created": "2026-08-29T10:00:00.000Z",
        }
        mock_post.return_value = fake_xendit_response

        # Jalankan service call
        import asyncio
        service = XenditService()
        result = asyncio.run(
            service.create_dynamic_qris(
                external_id="ORDER-TEST-001",
                amount=100000,
                tenant_id="atmosfitnes",
                customer_phone="081299998888",
            )
        )

        # Verifikasi respons schema
        self.assertEqual(result["qr_id"], "qr_test_uuid_12345")
        self.assertEqual(result["external_id"], "ORDER-TEST-001")
        self.assertEqual(result["amount"], 100000)
        self.assertEqual(result["status"], "ACTIVE")
        self.assertTrue(result["qr_string"].startswith("000201"))

        # Verifikasi call parameters
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        headers = call_kwargs["headers"]
        self.assertIn("Authorization", headers)
        self.assertTrue(headers["Authorization"].startswith("Basic "))

        sent_payload = call_kwargs["json"]
        self.assertEqual(sent_payload["external_id"], "ORDER-TEST-001")
        self.assertEqual(sent_payload["type"], "DYNAMIC")
        self.assertEqual(sent_payload["currency"], "IDR")
        self.assertEqual(sent_payload["amount"], 100000)
        self.assertIn("/api/v1/payments/xendit/callback", sent_payload["callback_url"])

    # =========================================================================
    # 2. Callback Security: Token Validation
    # =========================================================================

    def test_xendit_callback_invalid_token_rejected(self):
        """Memvalidasi penolakan webhook (HTTP 403) jika token callback salah atau tidak disertakan."""
        payload = {
            "id": "qr_fake_111",
            "external_id": "ORD-UNAUTHORIZED-01",
            "amount": 50000,
            "status": "COMPLETED",
        }

        # 1. Tanpa header x-callback-token
        resp_no_token = self.client.post("/api/v1/payments/xendit/callback", json=payload)
        self.assertEqual(resp_no_token.status_code, 403)

        # 2. Header x-callback-token salah
        resp_wrong_token = self.client.post(
            "/api/v1/payments/xendit/callback",
            json=payload,
            headers={"x-callback-token": "wrong_token_untrusted"},
        )
        self.assertEqual(resp_wrong_token.status_code, 403)

    # =========================================================================
    # 3. Successful Settlement & Background Tasks
    # =========================================================================

    @patch("app.routes.xendit.send_meta_capi_purchase", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock)
    def test_xendit_callback_settlement_and_tasks(self, mock_wa, mock_capi):
        """Memvalidasi pemrosesan webhook sukses memicu notifikasi WhatsApp dan event Meta CAPI."""
        external_id = "ORD-CAREER-778"
        amount = 150000
        phone = "081234567890"

        # Simulasikan intent terdaftar
        xendit_service._intents_by_external_id[external_id] = {
            "external_id": external_id,
            "amount": amount,
            "customer_phone": phone,
            "tenant_id": "boontrack-career",
        }

        webhook_payload = {
            "event": "qr_code.paid",
            "data": {
                "id": "qr_paid_778",
                "external_id": external_id,
                "amount": amount,
                "status": "COMPLETED",
                "customer_phone": phone,
            },
        }

        resp = self.client.post(
            "/api/v1/payments/xendit/callback",
            json=webhook_payload,
            headers={"x-callback-token": self.valid_token},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["external_id"], external_id)

        # Verifikasi status settled di service
        self.assertTrue(xendit_service.is_settled(external_id))

        # Verifikasi background task 1 (WhatsApp) terpanggil dengan data order
        mock_wa.assert_called_once()
        wa_kwargs = mock_wa.call_args.kwargs
        self.assertEqual(wa_kwargs["to_phone"], phone)
        self.assertIn(external_id, wa_kwargs["text"])
        self.assertIn("150,000", wa_kwargs["text"])

        # Verifikasi background task 2 (Meta CAPI) terpanggil dengan event Purchase
        mock_capi.assert_called_once()
        capi_kwargs = mock_capi.call_args.kwargs
        self.assertEqual(capi_kwargs["external_id"], external_id)
        self.assertEqual(capi_kwargs["value"], amount)
        self.assertEqual(capi_kwargs["currency"], "IDR")

    # =========================================================================
    # 4. Strict Idempotency Check
    # =========================================================================

    @patch("app.routes.xendit.send_meta_capi_purchase", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock)
    def test_xendit_callback_strict_idempotency(self, mock_wa, mock_capi):
        """Memvalidasi pengiriman payload webhook duplikat dicegah dari double-processing."""
        external_id = "ORD-IDEMPOTENT-999"
        amount = 50000
        phone = "081987654321"

        webhook_payload = {
            "id": "qr_idem_999",
            "external_id": external_id,
            "amount": amount,
            "status": "COMPLETED",
            "customer_phone": phone,
        }

        headers = {"x-callback-token": self.valid_token}

        # --- CALL 1: First Webhook Dispatch ---
        resp_1 = self.client.post("/api/v1/payments/xendit/callback", json=webhook_payload, headers=headers)
        self.assertEqual(resp_1.status_code, 200)
        self.assertEqual(resp_1.json()["status"], "SUCCESS")
        self.assertEqual(mock_wa.call_count, 1)
        self.assertEqual(mock_capi.call_count, 1)

        # --- CALL 2: Duplicate / Replay Webhook Dispatch ---
        resp_2 = self.client.post("/api/v1/payments/xendit/callback", json=webhook_payload, headers=headers)
        self.assertEqual(resp_2.status_code, 200)
        self.assertEqual(resp_2.json()["status"], "ALREADY_PROCESSED")
        self.assertTrue(resp_2.json()["idempotent"])

        # Pastikan TIDAK ADA pemanggilan ulang background tasks (count tetap 1)
        self.assertEqual(mock_wa.call_count, 1, "WhatsApp notification TIDAK boleh terkirim dua kali")
        self.assertEqual(mock_capi.call_count, 1, "Meta CAPI purchase event TIDAK boleh terkirim dua kali")

    # =========================================================================
    # 5. Route Alias Support (/api/v1/payment/xendit/callback)
    # =========================================================================

    def test_xendit_callback_route_alias(self):
        """Memvalidasi alias endpoint /api/v1/payment/xendit/callback berfungsi identik."""
        payload = {
            "id": "qr_alias_001",
            "external_id": "ORD-ALIAS-001",
            "amount": 25000,
            "status": "COMPLETED",
        }
        resp = self.client.post(
            "/api/v1/payment/xendit/callback",
            json=payload,
            headers={"x-callback-token": self.valid_token},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
