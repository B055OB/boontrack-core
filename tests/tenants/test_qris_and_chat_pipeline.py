"""tests/tenants/test_qris_and_chat_pipeline.py
Unit & Integration Tests for Real Dynamic QRIS String & Webchat LLM Pipeline.

Tests:
1. Dynamic QRIS Generation (POST /api/v1/payments/qris/create):
   - Returns valid raw EMVCo qr_string (starts with 000201010212).
   - Returns qr_code_url (valid HTTPS image URL).
   - Returns external_id, amount, and expired_at ISO timestamp.
   - Tests singular alias /api/v1/payment/qris/create.
   - Tests input validation (amount <= 0 returns 400).
2. Conversational Webchat LLM Pipeline (POST /api/v1/chat):
   - Accepts { tenant_slug, message, history, session_id }.
   - Multi-turn conversation memory processing.
   - Returns real catalog details, syllabus, pricing, and bundling promos without static fallback.
"""

import unittest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.services.onboarding_service import onboarding_service
from app.services.xendit_service import xendit_service


class TestQRISAndChatPipeline(unittest.TestCase):
    """Test suite for dynamic QRIS payload exposure and multi-turn webchat LLM pipeline."""

    def setUp(self):
        self.client = TestClient(app)
        onboarding_service.clear_state()
        xendit_service.clear_state()

        self.unique_suffix = uuid4().hex[:6]
        self.slug = f"digital-lab-{self.unique_suffix}"
        self.brand_name = f"Digital Lab {self.unique_suffix.upper()}"
        self.product_title = "Masterclass Digital Marketing & AI"
        self.price = 199000
        self.description = "Silabus lengkap 12 modul video, 50 template kampanye, dan studi kasus praktis"

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
                "asset_reference": "digital_mkt_pack_v1",
                "description": self.description,
            },
            "payout": {"bank_name": "BCA", "account_number": "88812345", "account_holder": "Digital Lab"},
        })
        self.assertEqual(onboard_resp.status_code, 201)

    def tearDown(self):
        onboarding_service.clear_state()
        xendit_service.clear_state()

    # =========================================================================
    # 1. Dynamic QRIS Generation Endpoint Tests
    # =========================================================================

    def test_create_dynamic_qris_endpoint_returns_emvco_and_url(self):
        """Memvalidasi endpoint POST /api/v1/payments/qris/create mengembalikan raw EMVCo qr_string dan image URL."""
        payload = {
            "tenant_slug": self.slug,
            "amount": self.price,
            "customer_phone": "6281299988877",
            "customer_name": "Budi Hartono",
            "product_name": self.product_title,
        }

        # 1. Test POST /api/v1/payments/qris/create
        resp = self.client.post("/api/v1/payments/qris/create", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "ACTIVE")
        self.assertEqual(data["amount"], self.price)
        self.assertEqual(data["tenant_id"], self.slug)
        self.assertTrue(data["external_id"].startswith("INV-"))

        # Validasi raw payload EMVCo QRIS
        qr_string = data["qr_string"]
        self.assertTrue(qr_string.startswith("000201010212"), "QRIS dinamis harus diawali 000201010212")
        self.assertIn("5802ID", qr_string, "Payload EMVCo QRIS wajib memuat country code 5802ID")
        self.assertTrue(len(qr_string) > 60)

        # Validasi image URL & expired_at
        self.assertTrue(data["qr_code_url"].startswith("http"))
        self.assertTrue(len(data["expired_at"]) > 10)

        # 2. Test Route Alias POST /api/v1/payment/qris/create (singular)
        resp_alias = self.client.post("/api/v1/payment/qris/create", json={
            "amount": 50000,
            "tenant_id": self.slug,
        })
        self.assertEqual(resp_alias.status_code, 200)
        self.assertEqual(resp_alias.json()["amount"], 50000)
        self.assertTrue(resp_alias.json()["qr_string"].startswith("000201010212"))

    def test_create_dynamic_qris_invalid_amount_400(self):
        """Memvalidasi validasi nominal amount <= 0 mengembalikan HTTP 400 Bad Request."""
        resp = self.client.post("/api/v1/payments/qris/create", json={
            "amount": 0,
            "tenant_slug": self.slug,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("lebih besar dari 0", resp.json()["detail"].lower())

    # =========================================================================
    # 2. Webchat LLM Pipeline with History Tests
    # =========================================================================

    def test_webchat_endpoint_with_tenant_slug_and_history(self):
        """Memvalidasi endpoint POST /api/v1/chat menerima { tenant_slug, message, history, session_id }."""
        chat_payload = {
            "tenant_slug": self.slug,
            "message": "Berapa harganya dan apa saja materi yang didapatkan?",
            "history": [
                {"role": "user", "content": f"Halo apakah ini toko {self.brand_name}?"},
                {"role": "assistant", "content": f"Halo Kakak! Benar, selamat datang di {self.brand_name}."}
            ],
            "session_id": "sess_multi_turn_abc",
            "user_name": "Rina",
        }

        resp = self.client.post("/api/v1/chat", json=chat_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["tenant_id"], self.slug)
        self.assertEqual(data["slug"], self.slug)
        self.assertEqual(data["session_id"], "sess_multi_turn_abc")

        # Jawaban wajib memuat info katalog dan harga riil
        reply = data["reply"]
        self.assertIn(self.product_title, reply)
        self.assertIn("Rp199,000", reply)
        self.assertIn("Silabus", reply)

    def test_webchat_no_static_fallback_on_product_inquiry(self):
        """Memvalidasi pertanyaan seputar produk tidak pernah menghasilkan greeting statis/generic."""
        chat_payload = {
            "tenant_slug": self.slug,
            "message": "Tolong jelaskan varian dan silabus lengkapnya dong",
            "session_id": "sess_inquiry_xyz",
        }

        resp = self.client.post("/api/v1/chat", json=chat_payload)
        self.assertEqual(resp.status_code, 200)
        reply = resp.json()["reply"]

        # Tidak boleh greeting template statis tanpa info produk
        self.assertNotIn("Pesan Kakak sudah kami terima. Silakan ketik nama produk yang ingin dipesan", reply)

        # Harus memuat produk riil
        self.assertIn(self.product_title, reply)
        self.assertIn("Rp199,000", reply)
        self.assertIn("Promo Bundling", reply)


if __name__ == "__main__":
    unittest.main()
