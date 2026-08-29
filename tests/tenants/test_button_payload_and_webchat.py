"""tests/tenants/test_button_payload_and_webchat.py
Unit & Integration Tests for Button Payload Handling & Dynamic Webchat LLM Hook.

Tests:
1. Quick-reply button click (INFO_PRODUK / DETAIL_PRODUK) generates internal LLM query and rich product explanation.
2. Text message "Info Produk" generates product details (name, price, variants, syllabus, bundling) without static greeting.
3. Internal LLM query contains exact structured prompt:
   "Jelaskan secara lengkap, menarik, dan luwes mengenai produk [product_name] dengan harga [price], varian/opsi, materi/silabus, serta promo bundling [promo] sesuai persona toko."
4. Interactive Webchat API endpoints (POST /api/v1/chat, POST /api/v1/chat/{slug}, POST /api/v1/tenants/{slug}/chat, POST /api/webchat/{slug}).
5. Error handling (HTTP 400 when missing tenant identifier, HTTP 404 for unknown tenant).
"""

import unittest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.services.onboarding_service import onboarding_service
from app.services.ai_engine import commerce_ai_engine
from app.services.agent_service import handle_button_or_message, is_button_trigger


class TestButtonPayloadAndWebchat(unittest.TestCase):
    """Test suite for quick-reply button payload handling and interactive webchat LLM routing."""

    def setUp(self):
        self.client = TestClient(app)
        onboarding_service.clear_state()

        self.unique_suffix = uuid4().hex[:6]
        self.slug = f"academy-pro-{self.unique_suffix}"
        self.brand_name = f"Academy Pro {self.unique_suffix.upper()}"
        self.product_title = "Master AI Prompting & Agents"
        self.price = 149000
        self.description = "50 modul video silabus komprehensif dan 100 template prompt siap pakai"

        # Onboard Store
        onboard_resp = self.client.post("/api/v1/tenants/onboard", json={
            "name": self.brand_name,
            "slug": self.slug,
            "template": "COMMERCE_TEMPLATE",
            "vertical": "DIGITAL_PRODUCTS",
            "product": {
                "title": self.product_title,
                "price": self.price,
                "product_type": "DIGITAL_COURSE",
                "asset_reference": "course_ai_bundle_v1",
                "description": self.description,
            },
            "payout": {"bank_name": "BCA", "account_number": "12345678", "account_holder": "Academy Pro"},
        })
        self.assertEqual(onboard_resp.status_code, 201)

    def tearDown(self):
        onboarding_service.clear_state()

    # =========================================================================
    # 1. Quick-Reply Button Trigger Detection & Internal Query Construction
    # =========================================================================

    def test_quick_reply_trigger_detection(self):
        """Memvalidasi pendeteksian button_id dan keyword pesan teks terkait info produk."""
        self.assertTrue(is_button_trigger("Menu", button_id="INFO_PRODUK"))
        self.assertTrue(is_button_trigger("Pilih", button_id="DETAIL_PRODUK"))
        self.assertTrue(is_button_trigger("Info Produk"))
        self.assertTrue(is_button_trigger("detail produk ini apa ya?"))
        self.assertTrue(is_button_trigger("Bisa minta info paket?"))
        self.assertFalse(is_button_trigger("Halo selamat pagi"))

    def test_internal_product_query_prompt_construction(self):
        """Memvalidasi query internal LLM dibentuk dengan struktur instruksi persis sesuai spesifikasi."""
        details = onboarding_service.get_tenant_details_by_slug(self.slug)
        self.assertIsNotNone(details)

        query = commerce_ai_engine.build_internal_product_query(details)

        # Harus memuat instruksi prompt spesifik:
        # "Jelaskan secara lengkap, menarik, dan luwes mengenai produk [product_name] dengan harga [price], varian/opsi, materi/silabus, serta promo bundling [promo] sesuai persona toko."
        self.assertIn("Jelaskan secara lengkap, menarik, dan luwes mengenai produk", query)
        self.assertIn(self.product_title, query)
        self.assertIn("Rp149,000", query)
        self.assertIn("DIGITAL_COURSE", query)
        self.assertIn(self.description, query)
        self.assertIn("promo bundling", query.lower())
        self.assertIn("sesuai persona toko", query)

    # =========================================================================
    # 2. Button Payload & Text Message Execution via Agent Service
    # =========================================================================

    def test_button_payload_info_produk_execution(self):
        """Memvalidasi klik tombol INFO_PRODUK menghasilkan penjelasan produk kaya, bukan greeting statis."""
        import asyncio

        reply = asyncio.run(handle_button_or_message(
            tenant_slug=self.slug,
            message="Lihat",
            button_id="INFO_PRODUK",
            user_name="Andi",
        ))

        self.assertIsNotNone(reply)
        # Memastikan tidak mengembalikan greeting template statis semata
        self.assertNotIn("Pesan Kakak sudah kami terima. Silakan ketik nama produk", reply)
        # Memastikan memuat detail produk riil
        self.assertIn(self.product_title, reply)
        self.assertIn("Rp149,000", reply)
        self.assertIn("Materi", reply)

    def test_text_message_info_produk_execution(self):
        """Memvalidasi pesan teks 'Info Produk' mengembalikan penjelasan produk kaya."""
        import asyncio

        reply = asyncio.run(handle_button_or_message(
            tenant_slug=self.slug,
            message="Info Produk",
            user_name="Budi",
        ))

        self.assertIsNotNone(reply)
        self.assertIn(self.product_title, reply)
        self.assertIn("Rp149,000", reply)

    # =========================================================================
    # 3. Interactive Webchat Endpoints (POST /api/v1/chat, POST /api/v1/chat/{slug})
    # =========================================================================

    def test_webchat_endpoint_by_tenant_id_in_body(self):
        """Memvalidasi POST /api/v1/chat dengan tenant_id di dalam request body."""
        resp = self.client.post("/api/v1/chat", json={
            "tenant_id": self.slug,
            "message": "Halo, apa saja keuntungan kursus ini?",
            "session_id": "sess_user_001",
            "user_name": "Citra",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["tenant_id"], self.slug)
        self.assertEqual(data["session_id"], "sess_user_001")
        self.assertTrue(len(data["reply"]) > 10)

    def test_webchat_endpoint_with_button_id(self):
        """Memvalidasi POST /api/v1/chat dengan button_id INFO_PRODUK menghasilkan detail produk."""
        resp = self.client.post("/api/v1/chat", json={
            "slug": self.slug,
            "message": "Menu",
            "button_id": "INFO_PRODUK",
            "session_id": "sess_user_002",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn(self.product_title, data["reply"])
        self.assertIn("Rp149,000", data["reply"])

    def test_webchat_endpoint_by_slug_in_path(self):
        """Memvalidasi POST /api/v1/chat/{slug} dan POST /api/v1/tenants/{slug}/chat."""
        # 1. Test /api/v1/chat/{slug}
        resp1 = self.client.post(f"/api/v1/chat/{self.slug}", json={
            "message": "Info Produk",
        })
        self.assertEqual(resp1.status_code, 200)
        self.assertIn(self.product_title, resp1.json()["reply"])

        # 2. Test /api/v1/tenants/{slug}/chat (frontend boontrack-inbox integration)
        resp2 = self.client.post(f"/api/v1/tenants/{self.slug}/chat", json={
            "message": "Detail Produk",
            "button_id": "DETAIL_PRODUK",
        })
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "success")
        self.assertIn(self.product_title, resp2.json()["reply"])

        # 3. Test /api/webchat/{slug}
        resp3 = self.client.post(f"/api/webchat/{self.slug}", json={
            "session_id": "sess_wb_003",
            "message": "Info Produk",
        })
        self.assertEqual(resp3.status_code, 200)
        self.assertIn(self.product_title, resp3.json()["reply"])

    # =========================================================================
    # 4. Error Handling
    # =========================================================================

    def test_webchat_missing_tenant_identifier_400(self):
        """Memvalidasi HTTP 400 jika tenant_id dan slug tidak disertakan."""
        resp = self.client.post("/api/v1/chat", json={
            "message": "Halo apa kabar?",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("specified", resp.json()["detail"].lower())

    def test_webchat_unknown_tenant_404(self):
        """Memvalidasi HTTP 404 jika tenant slug tidak ditemukan."""
        resp = self.client.post("/api/v1/chat", json={
            "slug": "tenant-tidak-ada-99999",
            "message": "Halo",
        })
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
