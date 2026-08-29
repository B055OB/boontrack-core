"""tests/tenants/test_dynamic_webhook_and_ai.py
Unit & Integration Test Suite for Dynamic Tenant Webhook Routing & Context Injection.

Tests:
1. Dynamic Webhook Tenant Resolution via onboarding intent ("saya baru saja mendaftar toko [slug]").
2. Sender session persistence (subsequent messages seamlessly route to the bound store).
3. Meta Sandbox fallback to the latest active COMMERCE_TEMPLATE tenant (eliminating hardcoded bale_pananggeuhan/om_budi).
4. Real commerce catalog injection into AI system prompt (Product Name, Price, Variants, Bundling, Asset URL).
5. Strict negative context boundaries enforcement in AI system prompt.
6. Tenant Query Endpoint GET /api/v1/tenants/{slug} returning store profile, products, payout, and persona.
"""

import unittest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.services.onboarding_service import onboarding_service
from app.services.whatsapp_service import (
    user_tenant_sessions,
    resolve_dynamic_tenant_for_whatsapp,
)
from app.services.ai_engine import commerce_ai_engine


class TestDynamicWebhookAndAIContext(unittest.TestCase):
    """Test suite for dynamic tenant resolution and commerce AI prompt injection."""

    def setUp(self):
        self.client = TestClient(app)
        onboarding_service.clear_state()
        user_tenant_sessions.clear()

    def tearDown(self):
        onboarding_service.clear_state()
        user_tenant_sessions.clear()

    # =========================================================================
    # 1. Dynamic Webhook Tenant Resolution via Onboarding Message & Session
    # =========================================================================

    def test_dynamic_tenant_resolution_via_onboarding_message(self):
        """Memvalidasi pesan onboarding mengikat sesi nomor pengirim ke slug toko tujuan."""
        unique_suffix = uuid4().hex[:6]
        slug = f"kopi-senja-{unique_suffix}"

        # 1. Onboard Toko Baru
        onboard_resp = self.client.post("/api/v1/tenants/onboard", json={
            "name": f"Kopi Senja {unique_suffix.upper()}",
            "slug": slug,
            "template": "COMMERCE_TEMPLATE",
            "vertical": "FNB",
            "product": {"title": "Kopi Susu Literan", "price": 75000},
            "payout": {"bank_name": "BCA", "account_number": "112233", "account_holder": "Owner Kopi"},
        })
        self.assertEqual(onboard_resp.status_code, 201)

        sender_phone = "6281234567890"

        # 2. Kirim Pesan Deklarasi Toko dari WhatsApp Sandbox
        inbound_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "entry_id_001",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "15556769563",
                            "phone_number_id": "1306479742542883"
                        },
                        "contacts": [{"profile": {"name": "Budi"}, "wa_id": sender_phone}],
                        "messages": [{
                            "from": sender_phone,
                            "id": "wamid.001",
                            "timestamp": "1700000000",
                            "type": "text",
                            "text": {"body": f"Halo, saya baru saja mendaftar toko {slug}"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=inbound_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["tenant"], slug)
        self.assertTrue(data["is_new_binding"])
        self.assertIn("resmi terhubung", data["reply"])

        # Verifikasi Sesi Tersimpan
        self.assertIn(sender_phone, user_tenant_sessions)
        self.assertEqual(user_tenant_sessions[sender_phone], slug)

        # 3. Pesan Kedua Tanpa Sebut Toko -> Otomatis Terhubung ke Sesi Toko Sebelumnya
        follow_up_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "entry_id_001",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "15556769563",
                            "phone_number_id": "1306479742542883"
                        },
                        "contacts": [{"profile": {"name": "Budi"}, "wa_id": sender_phone}],
                        "messages": [{
                            "from": sender_phone,
                            "id": "wamid.002",
                            "timestamp": "1700000010",
                            "type": "text",
                            "text": {"body": "Berapa harga kopi susu literan?"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp2 = self.client.post("/api/v1/whatsapp/webhook", json=follow_up_payload)
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2["tenant"], slug)
        self.assertFalse(data2["is_new_binding"])

    # =========================================================================
    # 2. Meta Sandbox Fallback to Latest Commerce Tenant
    # =========================================================================

    def test_dynamic_tenant_resolution_sandbox_fallback(self):
        """Memvalidasi pengirim baru di sandbox otomatis diarahkan ke toko COMMERCE_TEMPLATE terbaru."""
        unique_suffix = uuid4().hex[:6]
        latest_slug = f"butik-hijab-{unique_suffix}"

        # 1. Onboard Toko Commerce Terbaru
        self.client.post("/api/v1/tenants/onboard", json={
            "name": f"Butik Hijab {unique_suffix.upper()}",
            "slug": latest_slug,
            "template": "COMMERCE_TEMPLATE",
            "vertical": "FASHION",
            "product": {"title": "Gamis Sutra Eksklusif", "price": 350000},
            "payout": {"bank_name": "BRI", "account_number": "999000", "account_holder": "Butik Hijab"},
        })

        new_sender = "6289998887776"

        # 2. Pesan Masuk Tanpa Sesi Sebelumnya di Sandbox (+15556769563)
        sandbox_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "entry_id_002",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "15556769563",
                            "phone_number_id": "1306479742542883"
                        },
                        "contacts": [{"profile": {"name": "Siti"}, "wa_id": new_sender}],
                        "messages": [{
                            "from": new_sender,
                            "id": "wamid.003",
                            "timestamp": "1700000020",
                            "type": "text",
                            "text": {"body": "Halo apakah ada ukuran L?"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=sandbox_payload)
        self.assertEqual(resp.status_code, 200)
        # Pastikan BUKAN hardcoded bale_pananggeuhan atau om_budi
        self.assertEqual(resp.json()["tenant"], latest_slug)
        self.assertNotIn("bale_pananggeuhan", resp.json()["reply"].lower())
        self.assertNotIn("aduan", resp.json()["reply"].lower())

    # =========================================================================
    # 3. AI System Prompt Real Products & Context Injection
    # =========================================================================

    def test_ai_prompt_injection_commerce_catalog(self):
        """Memvalidasi injeksi nama toko, harga riil, bundling, dan asset URL ke system prompt AI."""
        slug = f"studio-creative-{uuid4().hex[:6]}"
        self.client.post("/api/v1/tenants/onboard", json={
            "name": "Studio Creative Pro",
            "slug": slug,
            "template": "COMMERCE_TEMPLATE",
            "vertical": "DIGITAL_PRODUCTS",
            "product": {
                "title": "Paket Video Reels 100 Template",
                "price": 99000,
                "product_type": "DIGITAL_FILE",
                "asset_reference": "reels_pack_v1",
                "description": "100 Template Reels siap pakai di Canva dan CapCut",
            },
            "payout": {"bank_name": "MANDIRI", "account_number": "777888", "account_holder": "Studio Pro"},
        })

        system_prompt = commerce_ai_engine.build_commerce_system_prompt(slug)

        # 1. Injeksi Identitas Toko & Vertikal
        self.assertIn("Studio Creative Pro", system_prompt)
        self.assertIn("DIGITAL_PRODUCTS", system_prompt)

        # 2. Injeksi Produk Riil & Harga
        self.assertIn("Paket Video Reels 100 Template", system_prompt)
        self.assertIn("Rp99,000", system_prompt)
        self.assertIn("100 Template Reels siap pakai", system_prompt)

        # 3. Injeksi Promo Bundling & Download URL Digital
        self.assertIn("Promo Bundling", system_prompt)
        self.assertIn(f"https://{slug}.boontrack.com/assets/reels_pack_v1", system_prompt)

    # =========================================================================
    # 4. Strict Negative Context Boundaries
    # =========================================================================

    def test_ai_prompt_negative_context_boundary(self):
        """Memvalidasi instruksi penolakan topik di luar toko (gym, layanan kelurahan, KTP/bansos)."""
        slug = f"toko-skincare-{uuid4().hex[:6]}"
        self.client.post("/api/v1/tenants/onboard", json={
            "name": "Glow Skincare Official",
            "slug": slug,
            "template": "COMMERCE_TEMPLATE",
            "vertical": "BEAUTY",
            "product": {"title": "Serum Niacinamide 10%", "price": 115000},
            "payout": {"bank_name": "BCA", "account_number": "555666", "account_holder": "Glow Official"},
        })

        system_prompt = commerce_ai_engine.build_commerce_system_prompt(slug)

        # Verifikasi Batasan Topik Ketat (Negative Boundaries)
        self.assertIn("BATASAN TOPIK & INTEGRITAS TOKO", system_prompt)
        self.assertIn("Atmosfitnes", system_prompt)
        self.assertIn("KTP/SKU/bansos", system_prompt)
        self.assertIn("Balé Pananggeuhan", system_prompt)
        self.assertIn("tolak dengan sopan", system_prompt.lower())

    # =========================================================================
    # 5. GET /api/v1/tenants/{slug} Endpoint for boontrack-inbox
    # =========================================================================

    def test_get_tenant_by_slug_endpoint(self):
        """Memvalidasi endpoint query tenant mengembalikan detail lengkap toko untuk frontend boontrack-inbox."""
        slug = f"kedai-kopi-sedap-{uuid4().hex[:6]}"
        self.client.post("/api/v1/tenants/onboard", json={
            "name": "Kedai Kopi Sedap",
            "slug": slug,
            "template": "COMMERCE_TEMPLATE",
            "vertical": "FNB",
            "product": {
                "title": "Cold Brew Arabika",
                "price": 32000,
                "description": "Kopi seduh dingin tahan 7 hari",
            },
            "payout": {
                "bank_name": "BCA",
                "account_number": "888999",
                "account_holder": "Barista Sedap",
            },
        })

        # 1. Query Tenant yang Valid (HTTP 200)
        resp = self.client.get(f"/api/v1/tenants/{slug}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["tenant"]["name"], "Kedai Kopi Sedap")
        self.assertEqual(data["tenant"]["slug"], slug)
        self.assertEqual(data["tenant"]["vertical"], "FNB")
        self.assertEqual(data["tenant"]["template"], "COMMERCE_TEMPLATE")

        # Verifikasi Products Metadata
        self.assertIsInstance(data["products"], list)
        self.assertGreaterEqual(len(data["products"]), 1)
        self.assertEqual(data["products"][0]["title"], "Cold Brew Arabika")
        self.assertEqual(data["products"][0]["price"], 32000.0)

        # Verifikasi Persona Metadata
        persona = data["persona"]
        self.assertIn("system_prompt", persona)
        self.assertIn("welcome_message", persona)

        # 2. Query Tenant yang Tidak Ditemukan (HTTP 404)
        resp_404 = self.client.get("/api/v1/tenants/non-existent-tenant-slug-999")
        self.assertEqual(resp_404.status_code, 404)
        self.assertIn("not found", resp_404.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
