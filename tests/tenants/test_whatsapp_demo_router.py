"""tests/tenants/test_whatsapp_demo_router.py
Unit & Integration Test Suite for Interactive Multi-Tenant Demo Router on WhatsApp.

Tests:
1. Greeting keywords ('halo', 'hi', 'p', 'test') trigger Demo Menu (no active session).
2. Explicit '#reset' or 'menu' trigger Demo Menu even in active session.
3. Selecting '1' locks session to bale_pananggeuhan and sends Bale greeting.
4. Selecting '2' locks session to atmosfitnes and sends Prima Fit Gym greeting.
5. Selecting '3' locks session to suhu-ads-masterclass and sends Suhu Ads greeting.
6. Subsequent messages route to locked tenant until #reset.
7. #reset clears session and sends menu again.
8. Multi-product catalog: POST adds multiple products, GET returns all with category field.
"""

import unittest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.services.onboarding_service import onboarding_service
from app.services.whatsapp_service import (
    user_tenant_sessions,
    DEMO_MENU_TEXT,
    DEMO_TENANT_GREETINGS,
    normalize_phone_number,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wa_payload(phone: str, text: str, phone_id: str = "1306479742542883") -> dict:
    """Builds a minimal Meta WhatsApp inbound webhook payload."""
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
                    "contacts": [{"profile": {"name": "Tester"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": f"wamid.{uuid4().hex[:8]}",
                        "timestamp": "1700000100",
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


ONBOARD_SLUG = f"test-cms-{uuid4().hex[:6]}"


class TestWhatsAppDemoRouter(unittest.TestCase):
    """Test suite for Interactive Multi-Tenant Demo Router."""

    @classmethod
    def setUpClass(cls):
        """Onboard one test tenant for session tests."""
        cls.client = TestClient(app)
        onboarding_service.clear_state()
        user_tenant_sessions.clear()

        resp = cls.client.post("/api/v1/tenants/onboard", json={
            "name": "Demo Test Store",
            "slug": ONBOARD_SLUG,
            "template": "COMMERCE_TEMPLATE",
            "vertical": "DIGITAL_PRODUCTS",
            "product": {"title": "Test Course", "price": 299000},
            "payout": {"bank_name": "BCA", "account_number": "112233", "account_holder": "Owner"},
        })
        assert resp.status_code == 201, f"Onboard failed: {resp.text}"

    @classmethod
    def tearDownClass(cls):
        onboarding_service.clear_state()
        user_tenant_sessions.clear()

    def setUp(self):
        """Ensure clean session per test."""
        user_tenant_sessions.clear()

    # =========================================================================
    # 1. Greeting triggers Demo Menu (no active session)
    # =========================================================================

    def test_greeting_halo_returns_demo_menu(self):
        """Mengirim 'halo' tanpa sesi aktif harus mengembalikan Demo Menu Selector."""
        phone = "628111000001"
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "halo"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn(data.get("status"), ("menu_dispatched", "success"))
        self.assertIn("1", data["reply"])
        self.assertIn("Bale", data["reply"])
        self.assertIn("2", data["reply"])
        self.assertIn("Prima Fit", data["reply"])
        self.assertIn("3", data["reply"])
        self.assertIn("Suhu Ads", data["reply"])

    def test_greeting_hi_returns_demo_menu(self):
        """'hi' tanpa sesi harus menghasilkan menu demo."""
        phone = "628111000002"
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "hi"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("BoonTrack", resp.json()["reply"])

    def test_greeting_p_returns_demo_menu(self):
        """'p' tanpa sesi harus menghasilkan menu demo."""
        phone = "628111000003"
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "p"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("BoonTrack", resp.json()["reply"])

    def test_greeting_test_returns_demo_menu(self):
        """'test' tanpa sesi harus menghasilkan menu demo."""
        phone = "628111000004"
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "test"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("BoonTrack", resp.json()["reply"])

    def test_new_sender_any_message_returns_demo_menu(self):
        """Nomor baru tanpa sesi aktif (pesan apapun) harus mengembalikan menu demo."""
        phone = "628111000099"
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "mau beli"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("BoonTrack", resp.json()["reply"])

    # =========================================================================
    # 2. #reset / menu keyword always shows menu
    # =========================================================================

    def test_reset_clears_session_and_sends_menu(self):
        """'#reset' harus menghapus sesi aktif dan mengirim menu selector."""
        phone = "628111000010"
        clean = normalize_phone_number(phone)
        user_tenant_sessions[clean] = "suhu-ads-masterclass"
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "#reset"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn(clean, user_tenant_sessions)
        self.assertIn("BoonTrack", data["reply"])

    def test_menu_keyword_shows_menu_even_in_active_session(self):
        """'menu' harus mengirim menu selector meskipun sesi aktif sudah ada."""
        phone = "628111000011"
        clean = normalize_phone_number(phone)
        user_tenant_sessions[clean] = "atmosfitnes"
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "menu"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("BoonTrack", resp.json()["reply"])
        self.assertNotIn(clean, user_tenant_sessions)

    # =========================================================================
    # 3. Menu Option Selection: 1 -> bale_pananggeuhan
    # =========================================================================

    def test_select_option_1_locks_to_bale_pananggeuhan(self):
        """Input '1' harus mengunci sesi ke bale_pananggeuhan dan mengirim greeting Bale."""
        phone = "628111000020"
        clean = normalize_phone_number(phone)
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "1"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("tenant"), "bale_pananggeuhan")
        self.assertTrue(data.get("is_new_binding"))
        # Reply contains "Pananggeuhan" (handles "Balé" unicode)
        self.assertIn("Pananggeuhan", data["reply"])
        self.assertEqual(user_tenant_sessions.get(clean), "bale_pananggeuhan")

    # =========================================================================
    # 4. Menu Option Selection: 2 -> atmosfitnes
    # =========================================================================

    def test_select_option_2_locks_to_atmosfitnes(self):
        """Input '2' harus mengunci sesi ke atmosfitnes dan mengirim greeting Prima Fit Gym."""
        phone = "628111000021"
        clean = normalize_phone_number(phone)
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "2"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("tenant"), "atmosfitnes")
        self.assertTrue(data.get("is_new_binding"))
        self.assertIn("Prima Fit", data["reply"])
        self.assertEqual(user_tenant_sessions.get(clean), "atmosfitnes")

    # =========================================================================
    # 5. Menu Option Selection: 3 -> suhu-ads-masterclass
    # =========================================================================

    def test_select_option_3_locks_to_suhu_ads_masterclass(self):
        """Input '3' harus mengunci sesi ke suhu-ads-masterclass dan mengirim greeting Suhu Ads."""
        phone = "628111000022"
        clean = normalize_phone_number(phone)
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "3"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("tenant"), "suhu-ads-masterclass")
        self.assertTrue(data.get("is_new_binding"))
        self.assertIn("Suhu", data["reply"])
        self.assertEqual(user_tenant_sessions.get(clean), "suhu-ads-masterclass")

    # =========================================================================
    # 6. Session lock persists until #reset
    # =========================================================================

    def test_subsequent_messages_route_to_locked_tenant(self):
        """Setelah memilih 1 (Bale), pesan berikutnya otomatis ke bale_pananggeuhan."""
        phone = "628111000030"
        clean = normalize_phone_number(phone)

        # Select option 1 -> lock to bale_pananggeuhan
        self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "1"))
        self.assertEqual(user_tenant_sessions.get(clean), "bale_pananggeuhan")

        # Follow-up message should route to bale
        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "bagaimana cara daftar ktp?"))
        data = resp.json()
        self.assertEqual(data.get("tenant"), "bale_pananggeuhan")

    def test_reset_after_session_lock_shows_menu(self):
        """Setelah sesi terkunci ke suhu-ads-masterclass, '#reset' harus kirim menu kembali."""
        phone = "628111000031"
        clean = normalize_phone_number(phone)
        user_tenant_sessions[clean] = "suhu-ads-masterclass"

        resp = self.client.post("/api/v1/whatsapp/webhook", json=_wa_payload(phone, "#reset"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(clean, user_tenant_sessions)
        self.assertIn("BoonTrack", resp.json()["reply"])

    # =========================================================================
    # 7. Multi-Product Catalog CRUD & Category
    # =========================================================================

    def test_multi_product_crud_appends_to_catalog(self):
        """POST /products beberapa kali harus menambah item baru (bukan overwrite)."""
        # Add first product
        resp1 = self.client.post(f"/api/v1/tenants/{ONBOARD_SLUG}/products", json={
            "title": "Ebook Meta Ads Pemula",
            "category": "E-Book",
            "price": 99000,
            "description": "Panduan lengkap Meta Ads untuk pemula",
        })
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["product"]["category"], "E-Book")

        # Add second product
        resp2 = self.client.post(f"/api/v1/tenants/{ONBOARD_SLUG}/products", json={
            "title": "Template Dashboard Budgeting",
            "category": "Template",
            "price": 49000,
            "description": "Notion spreadsheet budgeting ads",
        })
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["product"]["category"], "Template")

        # Add third product
        resp3 = self.client.post(f"/api/v1/tenants/{ONBOARD_SLUG}/products", json={
            "title": "Membership VIP Masterclass",
            "category": "Membership",
            "price": 499000,
        })
        self.assertEqual(resp3.status_code, 200)

        # GET all products must return at least 3 items (including initial)
        get_resp = self.client.get(f"/api/v1/tenants/{ONBOARD_SLUG}/products")
        self.assertEqual(get_resp.status_code, 200)
        data = get_resp.json()
        self.assertGreaterEqual(data["count"], 3)
        titles = [p["title"] for p in data["products"]]
        self.assertIn("Ebook Meta Ads Pemula", titles)
        self.assertIn("Template Dashboard Budgeting", titles)
        self.assertIn("Membership VIP Masterclass", titles)

    def test_get_products_returns_category_field(self):
        """GET /products harus menyertakan field 'category' pada setiap item."""
        resp = self.client.post(f"/api/v1/tenants/{ONBOARD_SLUG}/products", json={
            "title": "Produk Kategori Test",
            "category": "Digital Course",
            "price": 150000,
        })
        self.assertEqual(resp.status_code, 200)

        get_resp = self.client.get(f"/api/v1/tenants/{ONBOARD_SLUG}/products")
        self.assertEqual(get_resp.status_code, 200)
        products = get_resp.json()["products"]
        # Every product must have a category field
        for prod in products:
            self.assertIn("category", prod)

    def test_get_products_unknown_tenant_returns_404(self):
        """GET /products untuk tenant yang tidak ada harus mengembalikan 404."""
        resp = self.client.get("/api/v1/tenants/slug-yang-tidak-ada-sama-sekali/products")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
