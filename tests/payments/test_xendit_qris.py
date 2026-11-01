"""tests/payments/test_xendit_qris.py
Unit & Integration Test Suite for Xendit Sandbox Dynamic QRIS & Webhook Callback.

Tests:
1. Dynamic QRIS creation with Xendit client wrapper & basic auth verification.
2. Webhook callback security: rejection of unauthorized callback tokens (HTTP 403).
3. Webhook settlement processing: triggers customer WhatsApp confirmation & Meta CAPI Purchase event.
4. Resilient idempotency: duplicate webhook calls are acknowledged without duplicate triggers.
5. Support for multiple Xendit payload shapes (wrapped 'qr_code.paid' and direct object).
"""

import asyncio
import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.xendit_service import XenditService, xendit_service


class _InMemoryPaymentDB:
    """
    Stateful in-memory stand-in for the Postgres helpers used by app.routes.xendit.
    Guarantees zero live-DB access and deterministic idempotency semantics per test.
    """

    def __init__(self):
        self.processed_event_ids = set()
        self.settled_order_ids = set()
        self.settlements = []
        self.orders = {}

    def check_idempotency(self, event_id, external_id):
        if str(event_id) in self.processed_event_ids:
            return {"status": "ALREADY_PROCESSED", "reason": "event_already_processed"}
        if str(external_id) in self.settled_order_ids:
            return {"status": "ALREADY_PROCESSED", "reason": "order_already_paid"}
        ord_row = self.orders.get(str(external_id))
        if ord_row and str(ord_row.get("status") or "").upper() in ("PAID", "LUNAS", "SETTLED", "COMPLETED"):
            return {"status": "ALREADY_PROCESSED", "reason": "order_already_paid"}
        return None

    def lookup_order(self, external_id):
        return self.orders.get(str(external_id))

    def record_settlement(self, event_id, external_id, tenant_id, amount, payload, **kwargs):
        if str(external_id) in self.settled_order_ids:
            return {"status": "ALREADY_SETTLED"}
        self.processed_event_ids.add(str(event_id))
        self.settled_order_ids.add(str(external_id))
        if str(external_id) in self.orders:
            self.orders[str(external_id)]["status"] = "PAID"
            self.orders[str(external_id)]["payment_status"] = "PAID"
        self.settlements.append((str(event_id), str(external_id), tenant_id, amount))
        return {"status": "SETTLED"}



class TestXenditQRISIntegration(unittest.TestCase):
    """Test suite for Xendit dynamic QRIS generation and webhook handling."""

    def setUp(self):
        self.client = TestClient(app)
        xendit_service.clear_state()
        self.valid_token = os.getenv("XENDIT_CALLBACK_TOKEN", "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS")

        # Isolate persistence layer: no live PostgreSQL access from this suite.
        self.fake_db = _InMemoryPaymentDB()
        for target, fake in (
            ("app.routes.xendit._check_db_idempotency_sync", self.fake_db.check_idempotency),
            ("app.routes.xendit._lookup_persisted_order_sync", self.fake_db.lookup_order),
            ("app.routes.xendit._record_settlement_and_ledger_sync", self.fake_db.record_settlement),
        ):
            patcher = patch(target, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

        # Isolate every outbound side effect of the webhook background workers
        # (Evolution/Meta WhatsApp, CAPI, Supabase fulfillment, Telegram): zero network access.
        for target, kwargs in (
            ("httpx.AsyncClient.post", {"new_callable": AsyncMock, "return_value": MagicMock(status_code=200)}),
            ("app.routes.xendit.send_ereceipt_whatsapp", {"new_callable": AsyncMock}),
            ("app.routes.xendit.dispatch_all_capi", {"new_callable": AsyncMock}),
            ("app.routes.xendit.capi_dispatcher.dispatch_purchase", {"new_callable": AsyncMock}),
            ("app.routes.xendit.get_user_session_context", {"return_value": {}}),
            ("app.routes.xendit.dispatch_payment_success_notifications", {"new_callable": AsyncMock}),
            ("app.services.digital_fulfillment_service.fulfill_if_digital", {"new_callable": AsyncMock}),
            ("app.services.telegram_commerce_service.dispatch_flexing_alert", {"new_callable": AsyncMock}),
            ("app.services.transactional_event_service.trigger_payment_confirmed", {"new_callable": AsyncMock}),
            ("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug", {"return_value": {}}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

        # Deterministic background tasks: record coroutines scheduled by the webhook
        # and run them to completion on demand (no race with the TestClient event loop).
        self._scheduled = []
        real_asyncio = asyncio

        class _AsyncioProxy:
            def __getattr__(_self, name):
                return getattr(real_asyncio, name)

            @staticmethod
            def create_task(coro, *args, **kwargs):
                self._scheduled.append(coro)
                return MagicMock()

        patcher = patch("app.routes.xendit.asyncio", _AsyncioProxy())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _drain_background_tasks(self):
        """Execute all background coroutines scheduled by the webhook handler."""
        pending, self._scheduled[:] = list(self._scheduled), []

        async def _run():
            await asyncio.gather(*pending, return_exceptions=True)

        if pending:
            asyncio.run(_run())

    def _register_intent(self, external_id, amount, tenant_id="boontrack-career", phone=None):
        """Register a trusted payment intent (webhook fails closed for unknown orders)."""
        xendit_service._intents_by_external_id[external_id] = {
            "external_id": external_id,
            "amount": amount,
            "customer_phone": phone,
            "tenant_id": tenant_id,
        }

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

        # Verifikasi call parameters: call pertama WAJIB ke /qr_codes
        # (call kedua ke /v2/invoices adalah pembuatan invoice checkout non-fatal).
        self.assertGreaterEqual(mock_post.call_count, 1)
        first_call = mock_post.call_args_list[0]
        self.assertTrue(str(first_call.args[0]).endswith("/qr_codes"))
        call_kwargs = first_call.kwargs
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
        self._drain_background_tasks()

        # Verifikasi status settled di service
        self.assertTrue(xendit_service.is_settled(external_id))

        # Verifikasi background task 1 (WhatsApp) terpanggil dengan data order
        mock_wa.assert_called_once()
        wa_kwargs = mock_wa.call_args.kwargs
        self.assertEqual(wa_kwargs["to_phone"], phone)
        self.assertIn(external_id, wa_kwargs["text"])
        self.assertIn("150.000", wa_kwargs["text"])  # format Rupiah Indonesia: Rp150.000

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
        self._register_intent(external_id, amount, phone=phone)

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
        self._drain_background_tasks()
        self.assertEqual(mock_wa.call_count, 1)
        self.assertEqual(mock_capi.call_count, 1)

        # --- CALL 2: Duplicate / Replay Webhook Dispatch ---
        resp_2 = self.client.post("/api/v1/payments/xendit/callback", json=webhook_payload, headers=headers)
        self.assertEqual(resp_2.status_code, 200)
        self.assertEqual(resp_2.json()["status"], "ALREADY_PROCESSED")
        self.assertTrue(resp_2.json()["idempotent"])
        self._drain_background_tasks()

        # Pastikan TIDAK ADA pemanggilan ulang background tasks (count tetap 1)
        self.assertEqual(mock_wa.call_count, 1, "WhatsApp notification TIDAK boleh terkirim dua kali")
        self.assertEqual(mock_capi.call_count, 1, "Meta CAPI purchase event TIDAK boleh terkirim dua kali")

    # =========================================================================
    # 5. Route Alias Support (/api/v1/payment/xendit/callback)
    # =========================================================================

    @patch("app.routes.xendit.send_meta_capi_purchase", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock)
    def test_xendit_callback_route_alias(self, mock_wa, mock_capi):
        """Memvalidasi alias endpoint /api/v1/payment/xendit/callback berfungsi identik."""
        self._register_intent("ORD-ALIAS-001", 25000)
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

    @patch("app.routes.xendit.send_meta_capi_purchase", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock)
    def test_xendit_callback_delayed_webhook_after_cache_eviction(self, mock_wa, mock_capi):
        """Delayed PAID webhook arriving after L1 cache eviction resolves from persisted order and settles once."""
        external_id = "ORD-DELAYED-701"
        amount = 125000
        phone = "081234500701"

        self.fake_db.orders[external_id] = {
            "id": external_id,
            "tenant_slug": "boontrack-career",
            "tenant_id": "boontrack-career",
            "gross_amount": amount,
            "customer_name": "Delayed Buyer",
            "customer_phone": phone,
            "customer_email": "delayed@example.com",
            "product_title": "Career Pass",
            "status": "PENDING",
            "payment_status": "PENDING",
            "metadata": {},
        }
        xendit_service.clear_state()

        headers = {"x-callback-token": self.valid_token}
        delayed_paid_payload = {
            "id": "evt_delayed_701",
            "external_id": external_id,
            "amount": amount,
            "status": "PAID",
            "customer_phone": phone,
        }

        resp1 = self.client.post("/api/v1/payments/xendit/callback", json=delayed_paid_payload, headers=headers)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["status"], "SUCCESS")
        self._drain_background_tasks()
        self.assertEqual(len(self.fake_db.settlements), 1)
        self.assertEqual(self.fake_db.orders[external_id]["status"], "PAID")

        duplicate_diff_event = {
            "id": "evt_delayed_701_retry2",
            "external_id": external_id,
            "amount": amount,
            "status": "PAID",
            "customer_phone": phone,
        }
        resp2 = self.client.post("/api/v1/payments/xendit/callback", json=duplicate_diff_event, headers=headers)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "ALREADY_PROCESSED")
        self.assertTrue(resp2.json()["idempotent"])
        self.assertEqual(len(self.fake_db.settlements), 1)

    @patch("app.routes.xendit.send_meta_capi_purchase", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock)
    def test_xendit_callback_out_of_order_webhooks(self, mock_wa, mock_capi):
        """Out-of-order webhooks: PENDING/EXPIRED before PAID, and late PENDING/EXPIRED after PAID."""
        external_id = "ORD-OOO-802"
        amount = 85000
        phone = "081234500802"
        self._register_intent(external_id, amount, phone=phone)
        self.fake_db.orders[external_id] = {
            "id": external_id,
            "tenant_slug": "boontrack-career",
            "tenant_id": "boontrack-career",
            "gross_amount": amount,
            "customer_phone": phone,
            "status": "PENDING",
            "payment_status": "PENDING",
        }
        headers = {"x-callback-token": self.valid_token}

        early_pending = {"id": "evt_ooo_pending_1", "external_id": external_id, "amount": amount, "status": "PENDING"}
        r_early = self.client.post("/api/v1/payments/xendit/callback", json=early_pending, headers=headers)
        self.assertEqual(r_early.status_code, 200)
        self.assertEqual(r_early.json()["status"], "IGNORED")
        self.assertFalse(xendit_service.is_settled(external_id))
        self.assertEqual(len(self.fake_db.settlements), 0)

        paid_payload = {
            "id": "evt_ooo_paid_2",
            "external_id": external_id,
            "amount": amount,
            "status": "COMPLETED",
            "customer_phone": phone,
        }
        r_paid = self.client.post("/api/v1/payments/xendit/callback", json=paid_payload, headers=headers)
        self.assertEqual(r_paid.status_code, 200)
        self.assertEqual(r_paid.json()["status"], "SUCCESS")
        self._drain_background_tasks()
        self.assertTrue(xendit_service.is_settled(external_id))
        self.assertEqual(len(self.fake_db.settlements), 1)
        self.assertEqual(mock_wa.call_count, 1)

        late_expired = {"id": "evt_ooo_expired_3", "external_id": external_id, "amount": amount, "status": "EXPIRED"}
        r_late = self.client.post("/api/v1/payments/xendit/callback", json=late_expired, headers=headers)
        self.assertEqual(r_late.status_code, 200)
        self.assertEqual(r_late.json()["status"], "ALREADY_PROCESSED")
        self.assertTrue(r_late.json()["idempotent"])
        self.assertEqual(self.fake_db.orders[external_id]["status"], "PAID")
        self.assertEqual(len(self.fake_db.settlements), 1)
        self.assertEqual(mock_wa.call_count, 1)



if __name__ == "__main__":
    unittest.main()
