"""tests/test_boonpilot_bulk_import_knowledge.py
Unit tests verifying injection of Universal Bulk Import (Excel/CSV) knowledge
into BoonPilot Engine and Platform Knowledge Base.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.whatsapp.traffic_splitter import (
    CONCIERGE_SYSTEM_PROMPT,
    OFFICIAL_KNOWLEDGE_BASE,
    get_static_concierge_response,
    get_static_group_boonpilot_response,
)
from app.services.boonpilot_service import boonpilot_service


class TestBoonPilotBulkImportKnowledge(unittest.IsolatedAsyncioTestCase):
    """Test suite for Universal Bulk Import knowledge in BoonTrack ecosystem."""

    def test_concierge_system_prompt_contains_bulk_import(self):
        """Verifies CONCIERGE_SYSTEM_PROMPT contains Bulk Import feature details."""
        self.assertIn("FITUR UNIVERSAL BULK IMPORT KONTAK, PESANAN & LEADS (EXCEL / CSV)", CONCIERGE_SYSTEM_PROMPT)
        self.assertIn("Pelanggan / Leads: nama, whatsapp / telepon, email", CONCIERGE_SYSTEM_PROMPT)
        self.assertIn("Pesanan / Order: order_number, nama_produk, nominal / total", CONCIERGE_SYSTEM_PROMPT)
        self.assertIn("https://dashboard.boontrack.com/register", CONCIERGE_SYSTEM_PROMPT)

    def test_official_knowledge_base_static_router(self):
        """Verifies OFFICIAL_KNOWLEDGE_BASE and get_static_concierge_response."""
        self.assertIn("bulk_import", OFFICIAL_KNOWLEDGE_BASE)
        kb_text = OFFICIAL_KNOWLEDGE_BASE["bulk_import"]
        self.assertIn("Universal Bulk Import", kb_text)
        self.assertIn("order_number", kb_text)
        self.assertIn("https://dashboard.boontrack.com/register", kb_text)

        # Test keyword routing
        queries = [
            "gimana cara import excel?",
            "apakah bisa bulk import kontak?",
            "format csv untuk upload pesanan",
            "cara migrasi data pelanggan lama",
        ]
        for q in queries:
            resp = get_static_concierge_response(q)
            self.assertIn("Universal Bulk Import", resp, f"Failed for query '{q}'")
            self.assertIn("https://dashboard.boontrack.com/register", resp)

    def test_group_boonpilot_static_router(self):
        """Verifies group BoonPilot static response for bulk import queries."""
        resp = get_static_group_boonpilot_response("halo kak, bisa import excel data pelanggan gak?")
        self.assertIn("Universal Bulk Import", resp)
        self.assertIn("warm leads", resp.lower())
        self.assertIn("https://dashboard.boontrack.com/register", resp)

    async def test_boonpilot_copilot_system_prompt(self):
        """Verifies BoonPilot Copilot tenant context contains bulk import instructions."""
        context_bundle = await boonpilot_service.build_tenant_context("onlineboost")
        system_prompt = context_bundle["system_prompt"]
        self.assertIn("FITUR UNIVERSAL BULK IMPORT KONTAK, PESANAN & LEADS (EXCEL / CSV)", system_prompt)
        self.assertIn("Pelanggan / Leads: nama, whatsapp / telepon, email", system_prompt)
        self.assertIn("https://dashboard.boontrack.com/register", system_prompt)

    def test_inbox_boonpilot_knowledge_file_integrity(self):
        """Verifies C:\\boontrack-inbox\\lib\\boonpilotKnowledge.ts contains the knowledge entries."""
        inbox_kb_path = r"C:\boontrack-inbox\lib\boonpilotKnowledge.ts"
        if os.path.exists(inbox_kb_path):
            with open(inbox_kb_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("universal_bulk_import", content)
            self.assertIn("getBoonPilotBulkImportKnowledge", content)
            self.assertIn("order_number", content)
            self.assertIn("https://dashboard.boontrack.com/register", content)


if __name__ == "__main__":
    unittest.main()
