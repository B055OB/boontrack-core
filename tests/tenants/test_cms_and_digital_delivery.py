"""tests/tenants/test_cms_and_digital_delivery.py
Unit & Integration Tests for Tenant CMS Settings CRUD, Auto-Delivery Webhook, and Expanded AI Knowledge Base.

Tests:
1. Auto-Delivery on Payment Success:
   - Verifies WhatsApp notification contains digital delivery URL:
     "Pembayaran Berhasil! Silakan akses materi lengkap Anda di sini: https://drive.google.com/drive/folders/suhu-ads-masterclass-2026"
   - Verifies CTA "[📂 Buka Materi Drive]" is included in the message.
2. Expanded AI Knowledge Base:
   - Verifies "suhu-ads-masterclass" system prompt & responses contain:
     * Modul 1: Riset Winning Audience & Bedah Pixel Meta Ads
     * Modul 2: Struktur Campaign CBO vs ABO & Scaling Strategy (Budgeting & Ad Sets)
     * Modul 3: Funneling, Creative Hook & Copywriting Konversi Tinggi
     * Bonus: Template Dashboard Budgeting & Akses Grup Diskusi Eksklusif
3. Tenant CMS Backpanel Endpoints:
   - GET /api/v1/tenants/{slug}/settings: Returns settings, trust badges, persona, payout, products, and FAQ.
   - PUT /api/v1/tenants/{slug}/settings: Updates store settings and syncs to LOADED_CONFIG_TENANTS.
   - POST /api/v1/tenants/{slug}/products: Adds or updates catalog products.
"""

import unittest
from uuid import uuid4
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.tenant_loader import LOADED_CONFIG_TENANTS
from app.services.onboarding_service import onboarding_service
from app.services.ai_engine import commerce_ai_engine
from app.routes.xendit import send_whatsapp_payment_notification


class TestCMSAndDigitalDelivery(unittest.TestCase):
    """Test suite for CMS backpanel CRUD, auto-delivery notifications, and expanded AI curriculum."""

    def setUp(self):
        self.client = TestClient(app)
        onboarding_service.clear_state()

        self.slug = "suhu-ads-masterclass"
        self.brand_name = "Suhu Ads Masterclass 2026"
        self.price = 199000
        self.drive_url = "https://drive.google.com/drive/folders/suhu-ads-masterclass-2026"

        # Register suhu-ads-masterclass tenant
        resp = self.client.post("/api/v1/tenants/onboard", json={
            "name": self.brand_name,
            "slug": self.slug,
            "template": "COMMERCE_TEMPLATE",
            "vertical": "DIGITAL_PRODUCTS",
            "admin_phone": "6281299988877",
            "product": {
                "title": "Masterclass Meta Ads Full Stack 2026",
                "price": self.price,
                "product_type": "DIGITAL_COURSE",
                "asset_reference": self.drive_url,
                "description": "Kurikulum lengkap dari riset audience, pixel tracking, CBO scaling, hingga creative copywriting",
            },
            "payout": {
                "bank_name": "BCA",
                "account_number": "1234567890",
                "account_holder": "Suhu Digital",
            },
        })
        self.assertEqual(resp.status_code, 201)

    def tearDown(self):
        onboarding_service.clear_state()

    # =========================================================================
    # 1. Auto-Delivery Notification Tests
    # =========================================================================

    @patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock)
    def test_auto_delivery_whatsapp_message_contains_drive_link_and_cta(self, mock_send_wa):
        """Memvalidasi notifikasi pembayaran berhasil menyertakan link Google Drive dan CTA [📂 Buka Materi Drive]."""
        import asyncio

        phone = "6281299988877"
        ext_id = f"INV-{uuid4().hex[:8].upper()}"

        asyncio.run(send_whatsapp_payment_notification(
            phone=phone,
            external_id=ext_id,
            amount=self.price,
            tenant_id=self.slug,
        ))

        mock_send_wa.assert_awaited_once()
        call_kwargs = mock_send_wa.await_args.kwargs
        sent_text = call_kwargs.get("text", "")

        self.assertIn("Pembayaran Berhasil! Silakan akses materi lengkap Anda di sini:", sent_text)
        self.assertIn(self.drive_url, sent_text)
        self.assertIn("[📂 Buka Materi Drive]", sent_text)
        self.assertIn("LUNAS", sent_text)

    # =========================================================================
    # 2. Expanded AI Knowledge Base Curriculum Tests
    # =========================================================================

    def test_ai_knowledge_base_suhu_ads_masterclass_curriculum(self):
        """Memvalidasi query seputar kurikulum mengembalikan detail Modul 1, Modul 2, Modul 3, dan Bonus."""
        import asyncio

        reply = asyncio.run(commerce_ai_engine.generate_commerce_response(
            tenant_slug=self.slug,
            user_message="Tolong jelaskan apa saja silabus kurikulum dan materinya?",
            user_name="Andi",
        ))

        self.assertIn("Modul 1: Riset Winning Audience & Bedah Pixel Meta Ads", reply)
        self.assertIn("Modul 2: Struktur Campaign CBO vs ABO & Scaling Strategy", reply)
        self.assertIn("Modul 3: Funneling, Creative Hook & Copywriting Konversi Tinggi", reply)
        self.assertIn("Bonus: Template Dashboard Budgeting & Akses Grup Diskusi Eksklusif", reply)

    def test_ai_system_prompt_injects_expanded_curriculum(self):
        """Memvalidasi system prompt AI menginjeksi kurikulum materi dan batasan strict."""
        prompt = commerce_ai_engine.build_commerce_system_prompt(self.slug)

        self.assertIn("KURIKULUM & SILABUS MATERI RESMI:", prompt)
        self.assertIn("Modul 1: Riset Winning Audience", prompt)
        self.assertIn("Modul 2: Struktur Campaign CBO vs ABO", prompt)
        self.assertIn("Modul 3: Funneling, Creative Hook", prompt)
        self.assertIn("Bonus: Template Dashboard Budgeting", prompt)
        self.assertIn("STRICT NEGATIVE BOUNDARIES", prompt)

    # =========================================================================
    # 3. Tenant CMS Backpanel Endpoints Tests
    # =========================================================================

    def test_get_tenant_settings_endpoint(self):
        """Memvalidasi GET /api/v1/tenants/{slug}/settings mengembalikan konfigurasi lengkap."""
        resp = self.client.get(f"/api/v1/tenants/{self.slug}/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "success")
        self.assertIn("tenant", data)
        self.assertIn("trust_badges", data["tenant"])
        self.assertTrue(len(data["tenant"]["trust_badges"]) >= 2)
        self.assertIn("persona", data)
        self.assertIn("products", data)
        self.assertIn("faq", data)
        self.assertTrue(len(data["faq"]) >= 1)

    def test_put_tenant_settings_endpoint_syncs_runtime(self):
        """Memvalidasi PUT /api/v1/tenants/{slug}/settings memperbarui konfigurasi dan sinkron ke LOADED_CONFIG_TENANTS."""
        update_payload = {
            "public_description": "Platform edukasi Meta Ads no. 1 di Indonesia",
            "trust_badges": ["100% Praktisi Teruji", "Garansi Scaling"],
            "delivery_url": "https://drive.google.com/drive/folders/custom-vip-2026",
            "persona": {
                "tone": "Sangat Enerjik, Praktisi, dan Tegas",
                "welcome_message": "Selamat datang di Suhu Ads VIP!",
            },
        }

        resp = self.client.put(f"/api/v1/tenants/{self.slug}/settings", json=update_payload)
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()

        self.assertEqual(res_data["status"], "success")
        settings = res_data["settings"]
        self.assertEqual(settings["tenant"]["public_description"], "Platform edukasi Meta Ads no. 1 di Indonesia")
        self.assertIn("Garansi Scaling", settings["tenant"]["trust_badges"])

        # Verifikasi sinkronisasi runtime di LOADED_CONFIG_TENANTS
        cfg = LOADED_CONFIG_TENANTS.get(self.slug)
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.persona.tone, "Sangat Enerjik, Praktisi, dan Tegas")
        self.assertEqual(cfg.persona.welcome_message, "Selamat datang di Suhu Ads VIP!")

    def test_post_tenant_product_crud(self):
        """Memvalidasi POST /api/v1/tenants/{slug}/products menambahkan produk baru ke katalog."""
        new_prod_payload = {
            "title": "Modul Lanjutan: TikTok Ads & Shopee Live Mastery",
            "price": 299000,
            "promo_price": 249000,
            "description": "8 modul live streaming strategy dan viral hook TikTok",
            "product_type": "DIGITAL_COURSE",
            "delivery_url": "https://drive.google.com/drive/folders/tiktok-shopee-2026",
            "is_available": True,
        }

        resp = self.client.post(f"/api/v1/tenants/{self.slug}/products", json=new_prod_payload)
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()

        self.assertEqual(res_data["status"], "success")
        self.assertEqual(res_data["product"]["title"], new_prod_payload["title"])
        self.assertEqual(res_data["product"]["price"], 299000.0)

        # Cek kembali melalui GET settings
        get_resp = self.client.get(f"/api/v1/tenants/{self.slug}/settings")
        products = get_resp.json()["products"]
        titles = [p["title"] for p in products]
        self.assertIn(new_prod_payload["title"], titles)


if __name__ == "__main__":
    unittest.main()
