"""tests/test_tumbuh_kembang_persona.py
Unit & Integration Tests for Persona Admin Klinik & Anti-Hardselling Tenant tumbuh-kembang-anak.

Validates:
1. Strict Identity Guardrail: Admin / Tim Layanan Pasien dr. Harys Maulana (BUKAN dokter/asisten medis).
2. Salutation Guardrail: Sapaan wajib 'Ayah/Bunda'.
3. Anti-Hardselling Guardrail: Turn 1 keluhan anak TIDAK memuat link checkout atau mematok harga Rp150.000.
4. Screening Request Interceptor: User menanyakan/meminta form/link screening -> bot membagikan https://screening.littlebitefeeding.com (tanpa link checkout berbayar).
5. Dynamic Custom Domain: Menggunakan https://konsul.littlebitefeeding.com dan https://screening.littlebitefeeding.com, menghilangkan fallback statis shop.boontrack.com.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.knowledge_base import (
    get_tenant_knowledge_base,
    generate_greeting_response,
    TUMBUH_KEMBANG_ANAK_KB,
)
from app.services.ai_engine import commerce_ai_engine
from app.whatsapp.traffic_splitter import get_tenant_greeting_message
from app.utils.url_builder import extract_custom_domain, extract_assessment_url, resolve_storefront_url, resolve_product_url


class TestTumbuhKembangKnowledgeBase(unittest.TestCase):
    """Test KB and persona configuration for tenant tumbuh-kembang-anak."""

    def test_kb_retrieval_and_aliases(self):
        for alias in ["tumbuh-kembang-anak", "tumbuhkembanganak", "tumbuh_kembang_anak"]:
            kb = get_tenant_knowledge_base(alias)
            self.assertIsNotNone(kb, f"Alias '{alias}' should resolve to KB")
            self.assertEqual(kb["tenant_id"], "tumbuh-kembang-anak")
            self.assertIn("Harys Maulana", kb["brand_name"])

    def test_strict_identity_and_guardrail(self):
        kb = TUMBUH_KEMBANG_ANAK_KB
        guidelines = kb["persona_guidelines"]
        self.assertEqual(guidelines["identity"], "Admin / Tim Layanan Pasien dr. Harys Maulana (Tumbuh Kembang Anak)")
        self.assertEqual(guidelines["salutation"], "Ayah/Bunda")
        self.assertIn("BUKAN dokter", guidelines["strict_guardrail"])
        self.assertIn("DILARANG langsung melampirkan link pembayaran", guidelines["anti_hardselling"])

    def test_official_services_and_checkout_link(self):
        kb = TUMBUH_KEMBANG_ANAK_KB
        self.assertEqual(
            kb["checkout_url"],
            "https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak",
        )
        self.assertEqual(
            kb["screening_url"],
            "https://screening.littlebitefeeding.com",
        )
        services = {s["id"]: s for s in kb["services"]}
        self.assertIn("eat_and_grow", services)
        self.assertEqual(services["eat_and_grow"]["price"], 150000)
        self.assertEqual(
            services["eat_and_grow"]["checkout_url"],
            "https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak",
        )

    def test_greeting_response_for_tumbuh_kembang_anak(self):
        reply = generate_greeting_response(
            child_name="Arka",
            screening_id="TKA-2026-001",
            tenant_id="tumbuh-kembang-anak",
        )
        self.assertIn("Admin dr. Harys Maulana", reply)
        self.assertIn("Ayah/Bunda", reply)
        self.assertIn("Arka", reply)
        self.assertIn("TKA-2026-001", reply)
        self.assertIn("https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak", reply)
        self.assertNotIn("shop.boontrack.com", reply)


class TestTumbuhKembangSystemPrompt(unittest.TestCase):
    """Test system prompt construction for tenant tumbuh-kembang-anak."""

    def test_system_prompt_contains_strict_guardrails(self):
        prompt = commerce_ai_engine.build_commerce_system_prompt(
            tenant_slug="tumbuh-kembang-anak",
            is_first_message=True,
            has_history=False,
        )

        # 1. Identitas & Larangan Medis
        self.assertIn("Admin / Tim Layanan Pasien dr. Harys Maulana", prompt)
        self.assertIn("BUKAN dokter", prompt)
        self.assertIn("LARANGAN DIAGNOSTIK MEDIS", prompt)

        # 2. Sapaan Ayah/Bunda
        self.assertIn("Ayah/Bunda", prompt)
        self.assertIn("DILARANG KERAS menggunakan sapaan 'Kak'", prompt)

        # 3. Anti-Hardselling
        self.assertIn("ATURAN ANTI-HARDSELLING (MANDATORY)", prompt)
        self.assertIn("DILARANG LANGSUNG melampirkan link pembayaran atau mematok harga Rp150.000", prompt)

        # 4. Skrining Mandiri & Canonical URLs
        self.assertIn("SKRINING MANDIRI RESMI (ASSESSMENT FORM)", prompt)
        self.assertIn("https://screening.littlebitefeeding.com", prompt)
        self.assertIn("https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak", prompt)
        self.assertNotIn("shop.boontrack.com/tumbuh-kembang-anak", prompt)


class TestTumbuhKembangAntiHardsellingFlow(unittest.IsolatedAsyncioTestCase):
    """Integration & mock test for conversational turns."""

    async def test_turn_1_complaint_anti_hardselling_guard(self):
        """Turn 1: Orang tua mengeluhkan anak susah makan -> TIDAK boleh ada link checkout / harga 150.000."""
        # Simulasi jika LLM awalnya mencoba mengembalikan link/harga
        mock_llm_response = (
            "Halo Bunda! Anak susah makan ya? Silakan beli paket Konsultasi Chat seharga Rp150.000 di "
            "https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak ya!"
        )

        with patch.object(commerce_ai_engine.ai_service, "generate", new_callable=AsyncMock) as mock_gen, \
             patch.object(commerce_ai_engine.ai_service, "generate_for_agent", new_callable=AsyncMock) as mock_gen_agent:
            mock_gen.return_value = mock_llm_response
            mock_gen_agent.return_value = mock_llm_response

            user_complaint = "Anak saya usia 18 bulan susah banget makan, selalu GTM dan maunya cuma minum susu"
            reply = await commerce_ai_engine.generate_commerce_response(
                tenant_slug="tumbuh-kembang-anak",
                user_message=user_complaint,
                user_phone="6281234567890",
                history=[],  # Turn 1
            )

            # Assert: Link checkout & harga DILARANG keluar di turn 1 keluhan
            self.assertNotIn("https://konsul.littlebitefeeding.com", reply)
            self.assertNotIn("https://shop.boontrack.com", reply)
            self.assertNotIn("150.000", reply)
            self.assertNotIn("150000", reply)

            # Assert: Menggunakan persona Admin dr. Harys Maulana & sapaan Ayah/Bunda
            self.assertIn("Admin dr. Harys Maulana", reply)
            self.assertIn("Ayah/Bunda", reply)

            # Assert: Pertanyaan skrining administratif diajukan
            self.assertIn("Usia dan berat badan", reply)
            self.assertIn("berapa lama", reply)

    async def test_turn_1_direct_price_inquiry_allowed(self):
        """Turn 1 saat user secara eksplisit bertanya biaya / harga konsultasi."""
        mock_llm_response = (
            "Halo Ayah/Bunda! Untuk konsultasi langsung bersama dr. Harys Maulana tersedia melalui layanan "
            "Eat & Grow (Konsultasi Chat GTM Anak) dengan biaya Rp150.000. "
            "Pendaftaran resmi dapat diakses di https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak"
        )

        with patch.object(commerce_ai_engine.ai_service, "generate", new_callable=AsyncMock) as mock_gen, \
             patch.object(commerce_ai_engine.ai_service, "generate_for_agent", new_callable=AsyncMock) as mock_gen_agent:
            mock_gen.return_value = mock_llm_response
            mock_gen_agent.return_value = mock_llm_response

            user_msg = "Halo, berapa biaya konsultasi dengan dr. Harys Maulana?"
            reply = await commerce_ai_engine.generate_commerce_response(
                tenant_slug="tumbuh-kembang-anak",
                user_message=user_msg,
                user_phone="6281234567890",
                history=[],
            )

            # Karena eksplisit menanyakan biaya, link dan harga diperkenankan
            self.assertIn("150.000", reply)
            self.assertIn("https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak", reply)
            self.assertNotIn("shop.boontrack.com/tumbuh-kembang-anak", reply)

    async def test_screening_request_intent_returns_official_screening_url(self):
        """User meminta link skrining ('link screening mana kak / mau screening dulu saja') -> Wajib memberikan link formulir skrining resmi."""
        user_queries = [
            "link screening mana kak / mau screening dulu saja",
            "minta link screeningnya dong kak",
            "mau isi screening dulu kak",
            "ada link formulir skrining?",
        ]

        for query in user_queries:
            reply = await commerce_ai_engine.generate_commerce_response(
                tenant_slug="tumbuh-kembang-anak",
                user_message=query,
                user_phone="6281234567890",
                history=[],
            )

            # WAJIB membagikan link form screening mandiri
            self.assertIn(
                "https://screening.littlebitefeeding.com",
                reply,
                f"Query '{query}' harus memuat link form screening resmi"
            )

            # DILARANG membagikan link checkout konsultasi dokter
            self.assertNotIn(
                "https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak",
                reply,
                f"Query '{query}' tidak boleh memuat link checkout konsultasi"
            )
            self.assertNotIn("shop.boontrack.com", reply)

    def test_traffic_splitter_greeting_message(self):
        """Test default greeting message from traffic splitter for tumbuh-kembang-anak."""
        greeting = get_tenant_greeting_message(
            store_name="Tumbuh Kembang Anak",
            tenant_slug="tumbuh-kembang-anak",
        )
        self.assertIn("Ayah/Bunda", greeting)
        self.assertIn("Admin dr. Harys Maulana", greeting)
        self.assertNotIn("Halo Kak!", greeting)
        # Sapaan pembuka tidak boleh menempelkan link katalog belanja
        self.assertNotIn("https://shop.boontrack.com/tumbuh-kembang-anak", greeting)


class TestDynamicCustomDomainResolution(unittest.TestCase):
    """Test dynamic custom domain and assessment URL resolution."""

    def test_extract_custom_domain_and_assessment_url(self):
        meta = {
            "custom_domain": "konsul.littlebitefeeding.com",
            "assessment_url": "https://screening.littlebitefeeding.com",
        }
        self.assertEqual(extract_custom_domain(meta), "konsul.littlebitefeeding.com")
        self.assertEqual(extract_assessment_url(meta), "https://screening.littlebitefeeding.com")

        # Custom domains list
        meta_list = {
            "custom_domains": ["konsul.littlebitefeeding.com"],
            "kidmap_assessment_url": "https://screening.littlebitefeeding.com",
        }
        self.assertEqual(extract_custom_domain(meta_list), "konsul.littlebitefeeding.com")
        self.assertEqual(extract_assessment_url(meta_list), "https://screening.littlebitefeeding.com")

    def test_resolve_storefront_and_product_url(self):
        meta = {
            "custom_domain": "konsul.littlebitefeeding.com",
        }
        store_url = resolve_storefront_url("tumbuh-kembang-anak", meta)
        self.assertEqual(store_url, "https://konsul.littlebitefeeding.com")

        prod_url = resolve_product_url(
            "tumbuh-kembang-anak",
            "eat-and-grow-konsultasi-chat-gtm-anak",
            meta,
        )
        self.assertEqual(
            prod_url,
            "https://konsul.littlebitefeeding.com/p/eat-and-grow-konsultasi-chat-gtm-anak"
        )


if __name__ == "__main__":
    unittest.main()
