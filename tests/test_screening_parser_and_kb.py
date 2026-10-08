"""tests/test_screening_parser_and_kb.py
Unit & Integration Tests for Screening Parser, Knowledge Base, and Inbound Stream Worker.

Validates:
1. Regex extraction of child_name and screening_id across varied formats (URL-encoded, multi-line, spaces).
2. Little Bite Feeding Tenant Knowledge Base & Persona Configuration.
3. Inbound Stream Worker consumption and personalized greeting generation.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.knowledge_base import (
    generate_greeting_response,
    get_tenant_knowledge_base,
    LITTLE_BITE_FEEDING_KB,
)
from app.services.screening_parser import extract_screening_lead
from app.workers.whatsapp_inbound_worker import process_inbound_stream_event


class TestScreeningParser(unittest.TestCase):
    """Unit tests for inbound screening lead regex parser."""

    def test_standard_format_matching(self):
        msg = "Halo Dok, saya mau konsultasi hasil skrining untuk si kecil Muhammad Rayyan (ID: LBF-2026-001)"
        result = extract_screening_lead(msg)
        self.assertIsNotNone(result)
        self.assertEqual(result["child_name"], "Muhammad Rayyan")
        self.assertEqual(result["screening_id"], "LBF-2026-001")

    def test_multiline_and_extra_spaces(self):
        msg = "Halo Dok,\n\nBerikut hasil skrining untuk si kecil   Aisyah Putri   (ID: SCR-9988-X)"
        result = extract_screening_lead(msg)
        self.assertIsNotNone(result)
        self.assertEqual(result["child_name"], "Aisyah Putri")
        self.assertEqual(result["screening_id"], "SCR-9988-X")

    def test_url_encoded_string(self):
        # Format produced by web redirect links or WhatsApp click-to-chat
        msg = "Halo%20Dok%2C%20skrining%20untuk%20si%20kecil%20Arka%20Bumi%20(ID%3A%20SCR-101-ABC)"
        result = extract_screening_lead(msg)
        self.assertIsNotNone(result)
        self.assertEqual(result["child_name"], "Arka Bumi")
        self.assertEqual(result["screening_id"], "SCR-101-ABC")

    def test_plus_encoded_spaces(self):
        msg = "Halo+Dok+skrining+untuk+si+kecil+Kenzo+(ID:+KID-55)"
        result = extract_screening_lead(msg)
        self.assertIsNotNone(result)
        self.assertEqual(result["child_name"], "Kenzo")
        self.assertEqual(result["screening_id"], "KID-55")

    def test_non_screening_message_returns_none(self):
        non_screening_messages = [
            "Halo Dok, mau tanya jadwal praktek hari ini?",
            "Berapa harga biaya konsultasinya ya?",
            "Si kecil tidak mau makan nih dok",
            "P",
            "",
            None,
        ]
        for msg in non_screening_messages:
            self.assertIsNone(extract_screening_lead(msg))


class TestKnowledgeBase(unittest.TestCase):
    """Unit tests for Little Bite Feeding Knowledge Base & Persona Configuration."""

    def test_knowledge_base_retrieval_and_aliases(self):
        for alias in ["little-bite-feeding", "littlebite", "lbf", "little_bite_feeding"]:
            kb = get_tenant_knowledge_base(alias)
            self.assertIsNotNone(kb, f"Alias '{alias}' should resolve to KB")
            self.assertEqual(kb["brand_name"], "Little Bite Feeding")

    def test_knowledge_base_content_requirements(self):
        kb = LITTLE_BITE_FEEDING_KB
        self.assertEqual(kb["screening_url"], "https://screening.littlebitefeeding.com/")

        # Verify services & pricing
        services = {s["name"]: s for s in kb["services"]}
        self.assertIn("Konsultasi Chat", services)
        self.assertEqual(services["Konsultasi Chat"]["price"], 150000)
        self.assertTrue(services["Konsultasi Chat"]["is_primary"])

        self.assertIn("Google Meet", services)
        self.assertEqual(services["Google Meet"]["price"], 250000)
        self.assertFalse(services["Google Meet"]["is_primary"])

        # Verify payout details
        payout = kb["payout_details"]
        self.assertEqual(payout["bank_name"], "BCA")
        self.assertEqual(payout["account_number"], "3741672471")
        self.assertEqual(payout["account_name"], "Muhamad Harys Maulana")

        # Verify 5 GTM scenarios
        self.assertEqual(len(kb["gtm_scenarios"]), 5)

        # Verify persona guidelines (no blame)
        self.assertIn("Jangan pernah menyalahkan bunda", kb["persona_guidelines"]["golden_rule"])

    def test_generate_greeting_response(self):
        reply = generate_greeting_response(child_name="Kenzo", screening_id="LBF-2026-99")
        self.assertIn("Kenzo", reply)
        self.assertIn("LBF-2026-99", reply)
        self.assertIn("Konsultasi Chat", reply)
        self.assertIn("Rp150.000", reply)
        self.assertIn("3741672471", reply)
        self.assertIn("Muhamad Harys Maulana", reply)


class TestInboundStreamWorker(unittest.TestCase):
    """Unit tests for WhatsAppInboundWorker event processing."""

    def test_process_stream_event_with_screening_lead(self):
        event = {
            "tenant_id": "little-bite-feeding",
            "from": "6281234567890",
            "message_data": {
                "text": {
                    "body": "Halo Dok, skrining untuk si kecil Bima (ID: LBF-SCR-77)"
                }
            },
        }

        result = process_inbound_stream_event(event)
        self.assertEqual(result["status"], "screening_lead_processed")
        self.assertTrue(result["is_screening"])
        self.assertEqual(result["child_name"], "Bima")
        self.assertEqual(result["screening_id"], "LBF-SCR-77")
        self.assertIsNotNone(result["reply_text"])
        self.assertIn("Bima", result["reply_text"])
        self.assertIn("LBF-SCR-77", result["reply_text"])

    def test_process_stream_event_with_standard_message(self):
        event = {
            "tenant_id": "little-bite-feeding",
            "from": "6281234567890",
            "message_data": {
                "text": {
                    "body": "Halo mau tanya info harga"
                }
            },
        }

        result = process_inbound_stream_event(event)
        self.assertEqual(result["status"], "standard_message_processed")
        self.assertFalse(result["is_screening"])
        self.assertIsNone(result["reply_text"])


if __name__ == "__main__":
    unittest.main()
