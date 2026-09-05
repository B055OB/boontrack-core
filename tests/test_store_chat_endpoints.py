"""tests/test_store_chat_endpoints.py
Integration & Security Tests for BoonTrack AI Gateway ADR Endpoints:
1. POST /api/v1/store/chat
   - Format response: {"reply_text", "action", "payload": {"product_ids": [...]}, "session_state": {...}}
   - Action Catalog validation: SHOW_PRODUCT, SHOW_PRODUCT_LIST, SHOW_CHECKOUT, NONE
   - Database matching & Out-of-Stock validation before returning checkout action
   - Tenant isolation scoped session (tenant:{tenant_id}:session:{session_id})
2. POST /api/v1/merchant/copilot (BoonPilot - REASONING)
3. POST /api/v1/platform/support (BoonTrack CS - BALANCED)
"""

import os
import sys
import unittest
from unittest.mock import patch, AsyncMock

# Pastikan root direktori masuk ke sys.path untuk eksekusi pytest langsung
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.services.sales_agent_guard import StoreContextBoundaryManager, backend_security_validator
from app.services.ai_gateway import ai_gateway, AgentProfile, ModelProfile
from app.services.platform_support_agent import platform_support_agent
from app.services.boonpilot_service import boonpilot_service


class TestStoreChatEndpoints(unittest.TestCase):
    """Test suite for the 3 AI Gateway ADR FastAPI endpoints."""

    def setUp(self):
        self.client = TestClient(app)

    # =========================================================================
    # 1. STORE SALES AGENT (POST /api/v1/store/chat)
    # =========================================================================

    def test_store_chat_response_format_and_action_none(self):
        """Format respons wajib memuat reply_text, action, payload (product_ids), dan session_state."""
        fake_catalog = [
            {
                "product_id": "prod_101",
                "title": "Produk Sampel Store",
                "slug": "produk-sampel",
                "price": 100000.0,
                "stock": 10,
                "is_available": True,
            }
        ]

        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_catalog):
            resp = self.client.post(
                "/api/v1/store/chat",
                json={
                    "tenant_slug": "growth",
                    "message": "Halo, selamat pagi",
                    "session_id": "sess_cust_001",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Verifikasi 4 field wajib sesuai ADR specification
        self.assertIn("reply_text", data)
        self.assertIn("action", data)
        self.assertIn("payload", data)
        self.assertIn("session_state", data)

        # Untuk salam umum, action adalah 'NONE'
        self.assertEqual(data["action"], "NONE")
        self.assertIn("product_ids", data["payload"])
        self.assertEqual(data["payload"]["product_ids"], [])

        # Verifikasi format scoped session
        state = data["session_state"]
        self.assertEqual(state["tenant_id"], "growth")
        self.assertEqual(state["session_id"], "sess_cust_001")
        self.assertEqual(state["scoped_key"], "tenant:growth:session:sess_cust_001")

    def test_store_chat_action_show_product(self):
        """Saat user bertanya harga atau detail, action menjadi SHOW_PRODUCT dengan product_ids terverifikasi."""
        fake_catalog = [
            {
                "product_id": "prod_masterclass_ads",
                "title": "Masterclass Meta & TikTok Ads 2026",
                "slug": "masterclass-ads",
                "price": 149000.0,
                "stock": 25,
                "is_available": True,
            }
        ]

        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_catalog):
            resp = self.client.post(
                "/api/v1/store/chat",
                json={
                    "tenant_slug": "onlineboost",
                    "message": "Berapa harga Masterclass Ads 2026?",
                    "session_id": "buyer_wa_123",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "SHOW_PRODUCT")
        self.assertEqual(data["payload"]["product_ids"], ["prod_masterclass_ads"])
        self.assertIsNotNone(data.get("product"))
        self.assertEqual(data["product"]["price"], 149000.0)

    def test_store_chat_action_show_product_list(self):
        """Saat user meminta daftar seluruh katalog, action menjadi SHOW_PRODUCT_LIST."""
        fake_catalog = [
            {"product_id": "p1", "title": "Produk 1", "slug": "p1", "price": 50000.0, "stock": 10, "is_available": True},
            {"product_id": "p2", "title": "Produk 2", "slug": "p2", "price": 75000.0, "stock": 5, "is_available": True},
        ]

        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_catalog):
            resp = self.client.post(
                "/api/v1/store/chat",
                json={
                    "tenant_slug": "onlineboost",
                    "message": "Boleh lihat daftar produk lengkap di toko ini?",
                    "session_id": "buyer_wa_456",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "SHOW_PRODUCT_LIST")
        self.assertEqual(data["payload"]["product_ids"], ["p1", "p2"])

    def test_store_chat_action_show_checkout_with_stock_verification(self):
        """Saat user ingin checkout dan stok ready di DB, action SHOW_CHECKOUT dikembalikan."""
        fake_catalog = [
            {
                "product_id": "prod_kursus_kilat",
                "title": "Kursus Kilat Digital",
                "slug": "kursus-kilat",
                "price": 199000.0,
                "stock": 15,
                "is_available": True,
            }
        ]

        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_catalog):
            resp = self.client.post(
                "/api/v1/store/chat",
                json={
                    "tenant_slug": "onlineboost",
                    "message": "Saya mau beli dan checkout Kursus Kilat sekarang via QRIS",
                    "session_id": "buyer_wa_789",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "SHOW_CHECKOUT")
        self.assertEqual(data["payload"]["product_ids"], ["prod_kursus_kilat"])
        self.assertEqual(data["product"]["price"], 199000.0)

    def test_store_chat_rejects_checkout_when_out_of_stock(self):
        """Security Boundary: Jika stok di DB 0, aksi checkout ditolak dan action menjadi NONE."""
        fake_catalog_habis = [
            {
                "product_id": "prod_habis",
                "title": "Barang Langka Sold Out",
                "slug": "barang-langka",
                "price": 500000.0,
                "stock": 0,  # HABIS!
                "is_available": False,
            }
        ]

        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_catalog_habis):
            resp = self.client.post(
                "/api/v1/store/chat",
                json={
                    "tenant_slug": "onlineboost",
                    "message": "Saya mau beli dan bayar Barang Langka",
                    "session_id": "buyer_wa_habis",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Harus NONE karena ditolak oleh DB validator
        self.assertEqual(data["action"], "NONE")
        self.assertIn("habis", data["reply_text"].lower())

    def test_store_chat_shipping_intent_does_not_render_product(self):
        """Pertanyaan ongkir/pengiriman mengembalikan action NONE dan tanpa kartu produk."""
        fake_catalog = [
            {
                "product_id": "prod_kaos",
                "title": "Kaos Polos Premium",
                "slug": "kaos-polos",
                "price": 85000.0,
                "stock": 50,
                "is_available": True,
            }
        ]

        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_catalog):
            resp = self.client.post(
                "/api/v1/store/chat",
                json={
                    "tenant_slug": "onlineboost",
                    "message": "Berapa ongkir ke Jakarta Selatan via ekspedisi JNE?",
                    "session_id": "buyer_wa_shipping",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "NONE")
        self.assertIsNone(data.get("product"))
        self.assertEqual(data["payload"]["product_ids"], [])
        self.assertIn("reply_text", data)

    # =========================================================================
    # 2. MERCHANT COPILOT (POST /api/v1/merchant/copilot)
    # =========================================================================

    def test_merchant_copilot_sales_query(self):
        """Merchant copilot merespons pertanyaan performa penjualan dengan data omset."""
        resp = self.client.post(
            "/api/v1/merchant/copilot",
            json={
                "tenant_slug": "onlineboost",
                "message": "Bagaimana performa penjualan dan omset toko saya?",
                "session_id": "copilot_test_sess",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("reply_text", data)
        self.assertIn("omset", data["reply_text"].lower())
        self.assertEqual(data["tenant_id"], "onlineboost")

    def test_merchant_copilot_mutation_proposal(self):
        """Merchant copilot menghasilkan action proposal saat mendeteksi instruksi mutasi stok."""
        resp = self.client.post(
            "/api/v1/merchant/copilot",
            json={
                "tenant_slug": "onlineboost",
                "message": "Tolong ubah stok Masterclass Ads menjadi 60 unit",
                "session_id": "copilot_mutation_sess",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "ACTION_PROPOSAL")
        self.assertIsNotNone(data.get("action_proposal"))
        self.assertEqual(data["action_proposal"]["status"], "AWAITING_APPROVAL")

    # =========================================================================
    # 3. PLATFORM SUPPORT (POST /api/v1/platform/support)
    # =========================================================================

    def test_platform_support_billing_and_escalation(self):
        """Platform support merespons bantuan billing dan menyertakan link eskalasi WhatsApp."""
        resp = self.client.post(
            "/api/v1/platform/support",
            json={
                "tenant_slug": "onlineboost",
                "message": "Bagaimana cara upgrade ke paket ProScale WABA resmi?",
                "category": "billing",
                "session_id": "cs_test_sess",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("reply_text", data)
        self.assertEqual(data["type"], "ESCALATE_WA")
        self.assertIsNotNone(data.get("escalation_url"))
        self.assertIn("wa.me", data["escalation_url"])


if __name__ == "__main__":
    unittest.main()
