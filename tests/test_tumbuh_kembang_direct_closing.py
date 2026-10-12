"""tests/test_tumbuh_kembang_direct_closing.py
Unit & Integration Tests for Tenant 'tumbuh-kembang-anak' (Tumbuh Kembang Anak dr. Harys Maulana).

Validates:
1. Intent Transition & Auto-Offer:
   - Saat user menanyakan harga/benefit produk digital, bot tidak hanya membalas nominal lalu diam (read-only mode).
   - Bot wajib menyertakan direct-closing action (mengarahkan ke pembayaran atau meminta Nama & Email untuk penerbitan Dynamic QRIS otomatis).
   - Sapaan wajib 'Ayah/Bunda', dilarang 'Kak'/'Kakak'.
2. Lead Capture & Automatic Dynamic QRIS Issuance:
   - Saat user mengirimkan Nama & Email, bot menerbitkan invoice & Dynamic QRIS otomatis via SELLER_NATIVE_QRIS.
   - Triggers pembayaran langsung ('mau bayar', 'minta qris') menghasilkan Dynamic QRIS dengan media_url.
3. Non-WABA Connection & Media Sender:
   - Function send_evolution_media berjalan normal dan mengirim media ke Evolution API /message/sendMedia/{instance}.
   - Rute webhook dan connection status instance tumbuh-kembang-anak berstatus aktif.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.knowledge_base import get_tenant_knowledge_base, TUMBUH_KEMBANG_ANAK_KB
from app.services.ai_engine import commerce_ai_engine
from app.services.unified_conversation_service import (
    unified_conversation_engine,
    resolve_tumbuh_kembang_product,
)
from app.services.whatsapp.evolution import send_evolution_media
from app.services.whatsapp_service import get_supabase
from app.services.circuit_breaker_service import circuit_breaker_service


class TestTumbuhKembangCatalogAndKnowledge(unittest.TestCase):
    """Memastikan seluruh 5 produk digital dan konsultasi terdaftar lengkap di KB."""

    def test_all_products_registered_in_kb(self):
        kb = get_tenant_knowledge_base("tumbuh-kembang-anak")
        self.assertIsNotNone(kb)
        services = {s["slug"]: s for s in kb.get("services", [])}

        expected_slugs = [
            "eat-and-grow-konsultasi-chat-gtm-anak",
            "happyeating",
            "panduan-stimulasianakcerdas",
            "play-n-grow-cirebon",
            "konsultasi-dokter",
        ]
        for slug in expected_slugs:
            self.assertIn(slug, services, f"Slug '{slug}' harus terdaftar di KB TKA")

        # Verifikasi harga produk
        self.assertEqual(services["happyeating"]["promo_price"], 99999)
        self.assertEqual(services["panduan-stimulasianakcerdas"]["promo_price"], 149000)
        self.assertEqual(services["play-n-grow-cirebon"]["promo_price"], 75000)
        self.assertEqual(services["konsultasi-dokter"]["promo_price"], 150000)

    def test_direct_closing_guidelines_in_kb(self):
        kb = TUMBUH_KEMBANG_ANAK_KB
        guidelines = kb.get("persona_guidelines", {})
        self.assertIn("auto_offer_direct_closing", guidelines)
        closing_guide = guidelines["auto_offer_direct_closing"]
        self.assertIn("DILARANG KERAS hanya membalas nominal", closing_guide)
        self.assertIn("direct-closing", closing_guide.lower())
        self.assertIn("Dynamic QRIS", closing_guide)


class TestTumbuhKembangProductResolver(unittest.TestCase):
    """Test pencocokan produk dinamis dari teks user atau history."""

    def setUp(self):
        self.catalog = [
            {"slug": "happyeating", "title": "Course GTM & Solusi MPASI Anti-GTM", "promo_price": 99999},
            {"slug": "panduan-stimulasianakcerdas", "title": "Panduan Stimulasi Anak Cerdas", "promo_price": 149000},
            {"slug": "play-n-grow-cirebon", "title": "E-Course PLAY N GROW (Khusus Cirebon)", "promo_price": 75000},
            {"slug": "konsultasi-dokter", "title": "Konsultasi Klinis & Screening Dokter Anak", "promo_price": 150000},
            {"slug": "eat-and-grow-konsultasi-chat-gtm-anak", "title": "Eat & Grow", "price": 150000},
        ]

    def test_resolve_from_query_keywords(self):
        # 1. GTM / MPASI
        p1 = resolve_tumbuh_kembang_product("berapa harga course gtm mpasi?", catalog=self.catalog)
        self.assertEqual(p1["slug"], "happyeating")

        # 2. Stimulasi
        p2 = resolve_tumbuh_kembang_product("saya mau modul panduan stimulasi anak cerdas", catalog=self.catalog)
        self.assertEqual(p2["slug"], "panduan-stimulasianakcerdas")

        # 3. Play n grow
        p3 = resolve_tumbuh_kembang_product("info paket play n grow cirebon dong", catalog=self.catalog)
        self.assertEqual(p3["slug"], "play-n-grow-cirebon")

        # 4. Screening Dokter
        p4 = resolve_tumbuh_kembang_product("biaya konsultasi klinis dokter anak", catalog=self.catalog)
        self.assertEqual(p4["slug"], "konsultasi-dokter")

    def test_resolve_from_conversation_history(self):
        history = [
            {"role": "user", "content": "Berapa harga panduan stimulasi anak cerdas ya?"},
            {"role": "assistant", "content": "Harga promo Rp149.000 Ayah/Bunda. Boleh kami bantu Nama & Email?"},
        ]
        # User memberikan email tanpa menyebutkan nama produk di pesan terakhir
        p = resolve_tumbuh_kembang_product("Nama: Bunda Rika, rika@gmail.com", history=history, catalog=self.catalog)
        self.assertEqual(p["slug"], "panduan-stimulasianakcerdas")


class TestTumbuhKembangDirectClosingFlow(unittest.IsolatedAsyncioTestCase):
    """Test alur AI engine dan direct closing saat user menanyakan harga."""

    async def test_price_inquiry_appends_direct_closing_action(self):
        """Saat user menanyakan harga dan LLM hanya menjawab nominal, guard wajib menambahkan closing action."""
        # Simulasi respons LLM yang 'read-only' (hanya nominal tanpa penutup closing)
        read_only_llm_reply = (
            "Halo Ayah/Bunda! Untuk Course GTM & Solusi MPASI Anti-GTM investasinya adalah Rp99.999."
        )

        with patch.object(commerce_ai_engine.ai_service, "generate", new_callable=AsyncMock) as mock_gen, \
             patch.object(commerce_ai_engine.ai_service, "generate_for_agent", new_callable=AsyncMock) as mock_gen_agent:
            mock_gen.return_value = read_only_llm_reply
            mock_gen_agent.return_value = read_only_llm_reply

            user_query = "Halo admin, berapa harga course gtm mpasi?"
            reply = await commerce_ai_engine.generate_commerce_response(
                tenant_slug="tumbuh-kembang-anak",
                user_message=user_query,
                user_phone="6281234567890",
                history=[],
            )

            # Bot WAJIB menyebutkan harga
            self.assertIn("99.999", reply)
            # Bot DILARANG read-only: WAJIB menyertakan call to action direct-closing minta data Nama & Email
            self.assertTrue(
                ("Nama Lengkap" in reply and "Email" in reply) or "QRIS" in reply or "pembayaran" in reply,
                "Bot wajib menyertakan direct-closing action minta data/pembayaran"
            )
            # Sapaan wajib Ayah/Bunda
            self.assertIn("Ayah/Bunda", reply)
            self.assertNotIn("Kakak", reply)
            self.assertNotIn("Kak ", reply)


class TestUnifiedConversationTumbuhKembang(unittest.IsolatedAsyncioTestCase):
    """Test penanganan di UnifiedConversationEngine."""

    async def test_lead_capture_issues_dynamic_qris_for_tumbuh_kembang(self):
        """User mengirimkan nama & email -> terbit Dynamic QRIS otomatis dengan salutation Ayah/Bunda."""
        user_msg = "Nama: Bunda Sinta, email: sinta.gtm@gmail.com, mau ambil course gtm mpasi ya min"

        # Mock generate_fast_track_checkout_response
        mock_invoice = {
            "external_id": "INV-TUMBUH-K-123456",
            "order_id": "INV-TUMBUH-K-123456",
            "amount": 99750,
            "base_amount": 99999,
            "unique_code": 249,
            "product_name": "Course GTM & Solusi MPASI Anti-GTM",
            "provider": "SELLER_NATIVE_QRIS",
            "status": "PENDING",
            "qr_code_url": "https://quickchart.io/qr?text=000201...test",
            "media_url": "https://quickchart.io/qr?text=000201...test",
            "image_url": "https://quickchart.io/qr?text=000201...test",
        }
        mock_caption = (
            "Berikut Rincian Tagihan & Barcode QRIS Pembayaran 💳\n\n"
            "📦 *Nama Produk:* Course GTM & Solusi MPASI Anti-GTM\n"
            "💰 *Total Tagihan (Lunas):* Rp99.750\n"
            "🏦 *Alternatif Transfer Bank:*\n• Bank: BCA\n• No. Rek: `3741672471`\n• Penerima: Muhamad Harys Maulana\n"
        )

        with patch("app.services.whatsapp.commerce.generate_fast_track_checkout_response", new_callable=AsyncMock) as mock_ft:
            mock_ft.return_value = (mock_caption, mock_invoice, b"fake_png_bytes")

            res = await unified_conversation_engine.process_chat(
                tenant_slug="tumbuh-kembang-anak",
                message=user_msg,
                sender_id="6281234567890",
                sender_name="Bunda Sinta",
                channel="whatsapp",
            )

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "DIRECT_PAYMENT_INSTRUCTIONS")
            self.assertEqual(res.get("type"), "MEDIA")
            self.assertEqual(res.get("media_url"), "https://quickchart.io/qr?text=000201...test")

            reply_text = res.get("reply", "")
            self.assertIn("Bunda Sinta", reply_text)
            self.assertIn("sinta.gtm@gmail.com", reply_text)
            self.assertIn("Ayah/Bunda", reply_text)
            self.assertNotIn("Kakak", reply_text)
            self.assertIn("Course GTM", reply_text)

    async def test_direct_pay_trigger_returns_dynamic_qris(self):
        """User mengirimkan trigger pembayaran eksplisit ('mau bayar sekarang min')."""
        mock_invoice = {
            "external_id": "INV-TUMBUH-K-998877",
            "amount": 149750,
            "provider": "SELLER_NATIVE_QRIS",
            "media_url": "https://quickchart.io/qr?text=000201...paytest",
        }
        mock_caption = (
            "Berikut Rincian Tagihan & Barcode QRIS Pembayaran 💳\n\n"
            "📦 *Nama Produk:* Panduan Stimulasi Anak Cerdas (0–5 Tahun)\n"
            "💰 *Total Tagihan (Lunas):* Rp149.750\n"
        )

        with patch("app.services.whatsapp.commerce.generate_fast_track_checkout_response", new_callable=AsyncMock) as mock_ft:
            mock_ft.return_value = (mock_caption, mock_invoice, b"fake_bytes")

            res = await unified_conversation_engine.process_chat(
                tenant_slug="tumbuh-kembang-anak",
                message="mau bayar panduan stimulasi via qris min",
                sender_id="6281234567890",
                sender_name="Bunda Maya",
                channel="whatsapp",
            )

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "DIRECT_PAYMENT_INSTRUCTIONS")
            self.assertEqual(res.get("media_url"), "https://quickchart.io/qr?text=000201...paytest")
            self.assertIn("Panduan Stimulasi", res.get("reply", ""))


class TestNonWabaConnectionAndEvolutionMedia(unittest.IsolatedAsyncioTestCase):
    """Test rute koneksi dan fungsi penembak media QRIS non-WABA."""

    def test_whatsapp_connection_active_and_circuit_closed(self):
        """Memverifikasi instance tumbuh-kembang-anak di database aktif dan circuit breaker CLOSED."""
        sb = get_supabase()
        if sb:
            conn = sb.table("whatsapp_connections").select("*").eq("instance_name", "tumbuh-kembang-anak").maybe_single().execute()
            if conn.data:
                self.assertEqual(conn.data.get("status"), "open")
                self.assertTrue(conn.data.get("is_connected"))
                self.assertEqual(conn.data.get("provider"), "EVOLUTION")

        # Circuit breaker harus dalam keadaan CLOSED (normal)
        self.assertFalse(circuit_breaker_service.is_circuit_open("tumbuh-kembang-anak"))

    async def test_send_evolution_media_dispatches_correctly(self):
        """Memverifikasi fungsi send_evolution_media memformat payload dan memanggil endpoint Evolution API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"key": {"id": "msg_qris_001"}, "status": "PENDING"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            res = await send_evolution_media(
                number="6281234567890",
                media_url="https://quickchart.io/qr?text=000201...test",
                caption="Silakan scan barcode QRIS resmi ini Ayah/Bunda ✨",
                instance_name="tumbuh-kembang-anak",
            )

            self.assertTrue(res.get("success"))
            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            call_payload = mock_post.call_args[1]["json"]

            self.assertIn("/message/sendMedia/tumbuh-kembang-anak", call_url)
            self.assertEqual(call_payload["number"], "6281234567890")
            self.assertEqual(call_payload["mediatype"], "image")
            self.assertEqual(call_payload["mimetype"], "image/png")
            self.assertIn("quickchart.io", call_payload["media"])
            self.assertIn("Ayah/Bunda", call_payload["caption"])


if __name__ == "__main__":
    unittest.main()
