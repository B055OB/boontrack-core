"""tests/test_whatsapp_bot_router_dynamic_payment.py
Unit & Integration Test Suite for:
1. WhatsApp 4-Option Main Interactive Menu (#reset / say hello)
2. Supabase Real Products Query (no mock fallbacks, OnlineBoost 4 ecourses, empty tenant notification)
3. Dynamic QRIS Generation & Webhook CAPI Purchase Event Trigger
"""

import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.whatsapp_service import (
    DEMO_MENU_TEXT,
    DEMO_TENANT_GREETINGS,
    get_tenant_products_from_db,
    build_tenant_catalog_sections,
    generate_fast_track_checkout_response,
    resolve_dynamic_tenant_for_whatsapp,
    user_tenant_sessions,
    normalize_phone_number,
)
from app.services.whatsapp_menu_flow_service import WhatsAppMenuFlowService


def _make_wa_payload(phone: str, text: str, phone_id: str = "1306479742542883") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry_demo",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "15556769563",
                        "phone_number_id": phone_id,
                    },
                    "contacts": [{"profile": {"name": "Test User"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": "wamid.test_12345",
                        "timestamp": "1700000000",
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


class TestWhatsAppBotRouterAndDynamicPayment(unittest.TestCase):
    """Test suite for WhatsApp Bot Router & Dynamic Payment Flow."""

    def setUp(self):
        self.client = TestClient(app)
        user_tenant_sessions.clear()

    def tearDown(self):
        user_tenant_sessions.clear()

    # =========================================================================
    # 1. Main Interactive Menu (4 Opsi: ombudi, growthplus, proscale, onlineboost)
    # =========================================================================

    def test_demo_menu_contains_all_four_options(self):
        """Menu utama wajib memiliki 4 opsi merchant resmi."""
        self.assertIn("1️⃣ *Om Budi Channel*", DEMO_MENU_TEXT)
        self.assertIn("ombudi", DEMO_MENU_TEXT)
        self.assertIn("2️⃣ *Tier Growth+*", DEMO_MENU_TEXT)
        self.assertIn("growthplus", DEMO_MENU_TEXT)
        self.assertIn("3️⃣ *Tier ProScale*", DEMO_MENU_TEXT)
        self.assertIn("proscale", DEMO_MENU_TEXT)
        self.assertIn("4️⃣ *OnlineBoost*", DEMO_MENU_TEXT)
        self.assertIn("onlineboost", DEMO_MENU_TEXT)

    def test_greeting_triggers_menu_selector(self):
        """Pesan salam (halo/hi/reset) menampilkan menu 4 opsi."""
        phone = "628999000001"
        for kw in ["halo", "hi", "test", "#reset"]:
            resp = self.client.post("/api/v1/whatsapp/webhook", json=_make_wa_payload(phone, kw))
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get("status"), "menu_dispatched")
            self.assertIn("Om Budi Channel", data.get("reply", ""))
            self.assertIn("Tier Growth+", data.get("reply", ""))
            self.assertIn("Tier ProScale", data.get("reply", ""))
            self.assertIn("OnlineBoost", data.get("reply", ""))

    def test_option_selection_locks_tenants(self):
        """Memilih angka 1, 2, 3, 4 mengunci ke masing-masing slug merchant."""
        phone = "628999000002"
        clean = normalize_phone_number(phone)

        # Opsi 1 -> ombudi
        r1 = self.client.post("/api/v1/whatsapp/webhook", json=_make_wa_payload(phone, "1"))
        self.assertEqual(r1.json().get("tenant"), "ombudi")
        self.assertEqual(user_tenant_sessions.get(clean), "ombudi")
        self.assertIn("Om Budi", r1.json().get("reply", ""))

        # Opsi 2 -> growthplus
        r2 = self.client.post("/api/v1/whatsapp/webhook", json=_make_wa_payload(phone, "2"))
        self.assertEqual(r2.json().get("tenant"), "growthplus")
        self.assertEqual(user_tenant_sessions.get(clean), "growthplus")
        self.assertIn("Tier Growth+", r2.json().get("reply", ""))

        # Opsi 3 -> proscale
        r3 = self.client.post("/api/v1/whatsapp/webhook", json=_make_wa_payload(phone, "3"))
        self.assertEqual(r3.json().get("tenant"), "proscale")
        self.assertEqual(user_tenant_sessions.get(clean), "proscale")
        self.assertIn("Tier ProScale", r3.json().get("reply", ""))

        # Opsi 4 -> onlineboost
        r4 = self.client.post("/api/v1/whatsapp/webhook", json=_make_wa_payload(phone, "4"))
        self.assertEqual(r4.json().get("tenant"), "onlineboost")
        self.assertEqual(user_tenant_sessions.get(clean), "onlineboost")
        self.assertIn("OnlineBoost", r4.json().get("reply", ""))

    # =========================================================================
    # 2. Audit & Bersihkan Mock Fallback: Query Real Products & Empty Message
    # =========================================================================

    def test_onlineboost_loads_four_real_ecourses_from_supabase(self):
        """OnlineBoost wajib memuat 4 ecourse nyata dari tabel products Supabase tanpa mock."""
        store_name, products = get_tenant_products_from_db("onlineboost")
        self.assertEqual(len(products), 4, f"Expected 4 OnlineBoost products from Supabase, got {len(products)}")

        titles = [p.get("title") for p in products]
        self.assertTrue(any("YouTube AI" in t for t in titles))
        self.assertTrue(any("Internet Marketing CPM" in t for t in titles))
        self.assertTrue(any("Paid Traffic" in t for t in titles))

        # Pastikan mock parfum missionary atau produk toko lain TIDAK ADA
        for t in titles:
            self.assertNotIn("Parfum", t)
            self.assertNotIn("Missionary", t)

    def test_onlineboost_catalog_sections_returns_four_items(self):
        """build_tenant_catalog_sections untuk OnlineBoost menampilkan 4 baris ecourse."""
        body_text, sections = build_tenant_catalog_sections("onlineboost")
        self.assertIn("OnlineBoost", body_text)
        self.assertEqual(len(sections), 1)
        self.assertEqual(len(sections[0]["rows"]), 4)

    def test_empty_tenant_returns_informative_message_no_mock(self):
        """Tenant kosong/belum ada produk harus mengembalikan pesan informatif bahwa katalog sedang disiapkan."""
        empty_slug = "toko-kosong-tanpa-produk-999"
        store_name, products = get_tenant_products_from_db(empty_slug)
        self.assertEqual(len(products), 0)

        body_text, sections = build_tenant_catalog_sections(empty_slug)
        self.assertEqual(sections, [])
        self.assertIn("sedang disiapkan oleh admin", body_text)
        self.assertNotIn("Parfum", body_text)
        self.assertNotIn("Missionary", body_text)

    def test_whatsapp_menu_flow_empty_tenant_returns_informative_message(self):
        """WhatsAppMenuFlowService mengembalikan pesan informatif jika produk kosong."""
        menu_flow = WhatsAppMenuFlowService()
        msg = menu_flow.build_products_menu_message("tenant-baru-kosong")
        self.assertIn("sedang disiapkan oleh admin", msg)
        self.assertNotIn("Masterclass Meta & TikTok Ads 2026", msg)

    # =========================================================================
    # 3. Dynamic QRIS Generation (Xendit Sandbox) & Webhook CAPI Trigger
    # =========================================================================

    @patch("app.services.xendit_service.httpx.AsyncClient.post")
    def test_dynamic_qris_generation_uses_xendit_sandbox(self, mock_post):
        """generate_fast_track_checkout_response menggunakan modul Xendit Sandbox resmi."""
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "id": "qr_xendit_test_001",
            "external_id": "INV-ONLINE-001",
            "amount": 499000,
            "currency": "IDR",
            "qr_string": "00020101021226570011ID.DANA.WWW...6304B7A1",
        }
        mock_post.return_value = fake_resp

        import asyncio
        caption, invoice, _ = asyncio.run(
            generate_fast_track_checkout_response(
                tenant_slug="onlineboost",
                from_phone="628123456789",
                contact_name="Budi",
            )
        )

        self.assertIn("Berikut Kode QRIS Pembayaran Anda", caption)
        self.assertIn("Total:", caption)
        self.assertTrue(invoice.get("qr_string", "").startswith("000201"))
        self.assertIn("api.qrserver.com", invoice.get("qr_code_url", ""))

    @patch("app.routes.xendit.dispatch_all_capi", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_meta_capi_purchase", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock)
    def test_webhook_payment_paid_triggers_capi_purchase(self, mock_wa, mock_capi, mock_dispatch):
        """Saat webhook status COMPLETED/PAID, CAPI event Purchase terpicu dengan order_id, amount, dan phone."""
        order_id = "INV-XENDIT-CAPI-888"
        amount = 499000
        phone = "081299887766"
        token = "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS"

        payload = {
            "id": "qr_xendit_888",
            "external_id": order_id,
            "amount": amount,
            "status": "COMPLETED",
            "customer_phone": phone,
            "customer_email": "buyer@example.com",
            "product_name": "Rahasia Dollar Paid Traffic",
        }

        resp = self.client.post(
            "/api/v1/payments/xendit/callback",
            json=payload,
            headers={"x-callback-token": token},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "SUCCESS")

        # Verifikasi trigger CAPI Purchase
        mock_capi.assert_called_once()
        capi_args = mock_capi.call_args.kwargs
        self.assertEqual(capi_args["external_id"], order_id)
        self.assertEqual(capi_args["value"], float(amount))
        self.assertEqual(capi_args["currency"], "IDR")
        self.assertEqual(capi_args["phone"], phone)
        self.assertEqual(capi_args["email"], "buyer@example.com")

        # Verifikasi dispatch_all_capi juga terpanggil
        mock_dispatch.assert_called_once()
        dispatch_payload = mock_dispatch.call_args.args[0]
        self.assertEqual(dispatch_payload["order_id"], order_id)
        self.assertEqual(dispatch_payload["amount"], amount)
        self.assertEqual(dispatch_payload["customer_phone"], phone)


if __name__ == "__main__":
    unittest.main()

