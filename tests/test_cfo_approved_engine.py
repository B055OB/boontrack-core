import io
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from docx import Document

from app.tenants.career.messages import (
    CAREER_ENTRY_BUTTONS,
    PREMIUM_CLUSTER_BUTTONS,
    DOCS_CLUSTER_BUTTONS,
    COMPANION_CLUSTER_BUTTONS,
    COMPLIANCE_DISCLAIMER,
    OFFICIAL_PRODUCT_NAME,
    UPSELL_BUTTONS
)
from app.services.pricing_engine import (
    calculate_document_metrics,
    calculate_pricing,
    build_qris_invoice_payload,
    compute_content_hash,
    check_anti_abuse_free_trial,
    register_free_trial_usage,
    TASK_POLISH_REPHRASE,
    TASK_CV_POLISH_REWRITE,
    TASK_CAREER_PRO_BUNDLE,
    TASK_ATS_DIAGNOSTIC
)
from app.services.doc_builder import (
    chunk_document_text,
    render_ats_review_docx,
    render_cv_rewrite_docx,
    render_paraphrase_docx,
    build_document_result
)
from app.services.document_engine import (
    validate_document_file,
    intake_document_job,
    process_document_job_async,
    execute_ai_document_task
)
from app.tenants.career.service import CareerService, is_whitelisted_career_phone


class TestCFOApprovedEngine(unittest.IsolatedAsyncioTestCase):

    # ==========================================
    # 1. Tests for WhatsApp Menu Hierarchy & 2-Tier UX
    # ==========================================
    def test_pre_payment_entry_menu_buttons(self):
        """Validasi Menu User Baru / Pre-Payment: 3 Interactive Buttons."""
        self.assertEqual(len(CAREER_ENTRY_BUTTONS), 3)
        button_ids = [b["id"] for b in CAREER_ENTRY_BUTTONS]
        self.assertIn("btn_create_cv", button_ids)
        self.assertIn("btn_review_cv", button_ids)
        self.assertIn("btn_paraphrase", button_ids)

    def test_post_payment_cluster_menu_buttons(self):
        """Validasi Menu Pasca-Pembayaran / Premium Dashboard: 2 Cluster Buttons."""
        self.assertEqual(len(PREMIUM_CLUSTER_BUTTONS), 2)
        button_ids = [b["id"] for b in PREMIUM_CLUSTER_BUTTONS]
        self.assertIn("btn_cluster_docs", button_ids)
        self.assertIn("btn_cluster_companion", button_ids)

    def test_cluster_submenus(self):
        """Validasi Submenu Kluster Dokumen dan Kluster Career Companion."""
        doc_ids = [b["id"] for b in DOCS_CLUSTER_BUTTONS]
        self.assertIn("btn_create_cv", doc_ids)
        self.assertIn("btn_review_cv", doc_ids)
        self.assertIn("btn_paraphrase", doc_ids)

        comp_ids = [b["id"] for b in COMPANION_CLUSTER_BUTTONS]
        self.assertIn("btn_job_match", comp_ids)
        self.assertIn("btn_mock_interview", comp_ids)
        self.assertIn("btn_salary_coach", comp_ids)

    # ==========================================
    # 2. Tests for CFO & CEO Approved Pricing Tiers
    # ==========================================
    def test_polish_and_rephrase_pricing_matrix(self):
        """Validasi Matrix Tarif Resmi Document Polish & Rephrase."""
        # Tier 1 (< 500 kata): Rp5.000
        p_tier1 = calculate_pricing(TASK_POLISH_REPHRASE, 350)
        self.assertEqual(p_tier1["pricing_tier"], "TIER_1")
        self.assertEqual(p_tier1["final_price"], 5000)

        # Tier 2 (500 - 2.500 kata): Rp10.000
        p_tier2 = calculate_pricing(TASK_POLISH_REPHRASE, 1200)
        self.assertEqual(p_tier2["pricing_tier"], "TIER_2")
        self.assertEqual(p_tier2["final_price"], 10000)

        # Tier 3 (2.500 - 6.000 kata): Rp20.000
        p_tier3 = calculate_pricing(TASK_POLISH_REPHRASE, 4500)
        self.assertEqual(p_tier3["pricing_tier"], "TIER_3")
        self.assertEqual(p_tier3["final_price"], 20000)

        # Tier 4 (> 6.000 kata s/d 12.000 kata): Rp40.000
        p_tier4 = calculate_pricing(TASK_POLISH_REPHRASE, 8000)
        self.assertEqual(p_tier4["pricing_tier"], "TIER_4")
        self.assertEqual(p_tier4["final_price"], 40000)

        # Tier 4 Add-on (> 12.000 kata): +Rp5.000 per 2.000 kata
        # 14.000 kata -> 40.000 + (1 * 5000) = 45.000
        p_tier4_addon1 = calculate_pricing(TASK_POLISH_REPHRASE, 14000)
        self.assertEqual(p_tier4_addon1["final_price"], 45000)

        # 17.000 kata -> 40.000 + (3 * 5000) = 55.000
        p_tier4_addon3 = calculate_pricing(TASK_POLISH_REPHRASE, 17000)
        self.assertEqual(p_tier4_addon3["final_price"], 55000)

    def test_career_products_pricing(self):
        """Validasi Tarif Single CV Polish & Career Pro Bundle."""
        # Single CV Polish & ATS Rewrite: Rp10.000
        p_cv = calculate_pricing(TASK_CV_POLISH_REWRITE, 600)
        self.assertEqual(p_cv["final_price"], 10000)

        # Career Pro Bundle: Rp25.000
        p_bundle = calculate_pricing(TASK_CAREER_PRO_BUNDLE, 600)
        self.assertEqual(p_bundle["final_price"], 25000)

        # ATS Diagnostic: Rp0
        p_free = calculate_pricing(TASK_ATS_DIAGNOSTIC, 500)
        self.assertEqual(p_free["final_price"], 0)

    # ==========================================
    # 3. Tests for SHA-256 Anti-Abuse Hashing
    # ==========================================
    def test_sha256_content_hashing(self):
        """Validasi kalkulasi SHA-256 Content Hashing."""
        sample_a = "Ini adalah naskah dokumen asli untuk uji hash."
        sample_b = "  ini  adalah   naskah dokumen asli untuk uji hash.  " # Normalized should match
        sample_c = "Naskah berbeda untuk tes anti abuse."

        hash_a = compute_content_hash(sample_a)
        hash_b = compute_content_hash(sample_b)
        hash_c = compute_content_hash(sample_c)

        self.assertEqual(len(hash_a), 64)
        self.assertEqual(hash_a, hash_b) # Case & whitespace normalized
        self.assertNotEqual(hash_a, hash_c)

    def test_anti_abuse_free_trial_enforcement(self):
        """Validasi penolakan free trial kedua untuk hash/user yang sama."""
        test_hash = compute_content_hash("Dokumen Uji Free Trial #12345")
        user_id = "test_user_abuse_999"

        # Trial 1: Allowed
        allowed_1, reason_1 = check_anti_abuse_free_trial(test_hash, user_id=user_id)
        self.assertTrue(allowed_1)

        # Register usage
        register_free_trial_usage(test_hash, user_id=user_id)

        # Trial 2 with same user: Denied
        allowed_2, reason_2 = check_anti_abuse_free_trial(test_hash, user_id=user_id)
        self.assertFalse(allowed_2)
        self.assertIn("LIMIT_EXCEEDED", reason_2)

    # ==========================================
    # 4. Tests for Document Chunking & Compliance
    # ==========================================
    def test_chunk_document_text_preserves_structure(self):
        """Validasi chunking teks panjang dengan pembagian logis."""
        text = (
            "BAB I PENDAHULUAN\n\n"
            + ("Latar belakang penelitian ini membahas dampak AI (Smith, 2024). " * 50)
            + "\n\nBAB II METODE PENELITIAN\n\n"
            + ("Metodologi yang digunakan adalah kuantitatif terapan. " * 50)
        )
        chunks = chunk_document_text(text, max_chunk_words=100)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(any("BAB I" in c["heading"] or "BAB I" in c["text"] for c in chunks))

    def test_compliance_naming_and_disclaimer(self):
        """Validasi nama resmi dan disclaimer kepatuhan."""
        self.assertEqual(OFFICIAL_PRODUCT_NAME, "BoonTrack Document Polish & Rephrase")
        self.assertIn("kebijakan integritas profesional dan akademik", COMPLIANCE_DISCLAIMER)

        # Ensure no disallowed words in templates
        disallowed = ["joki", "lolos turnitin", "bypass turnitin"]
        for word in disallowed:
            self.assertNotIn(word, COMPLIANCE_DISCLAIMER.lower())
            self.assertNotIn(word, OFFICIAL_PRODUCT_NAME.lower())

    # ==========================================
    # 5. Tests for Intake Pipeline & Async Execution
    # ==========================================
    @patch("app.services.document_engine.get_supabase")
    async def test_intake_zero_blocking_and_hash(self, mock_get_supabase):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value = MagicMock(execute=MagicMock(return_value={"data": []}))
        mock_get_supabase.return_value = mock_client

        fake_doc = Document()
        fake_doc.add_paragraph("Naskah akademik pengujian intake pipeline terpadu.")
        doc_io = io.BytesIO()
        fake_doc.save(doc_io)
        docx_bytes = doc_io.getvalue()

        res = await intake_document_job(
            tenant_id="boontrack-career",
            task_type=TASK_POLISH_REPHRASE,
            filename="skripsi_dani.docx",
            file_bytes=docx_bytes,
            user_id="user_555",
            user_phone="6281237450222"
        )

        self.assertEqual(res["status"], "WAITING_PAYMENT")
        self.assertEqual(res["task_type"], TASK_POLISH_REPHRASE)
        self.assertEqual(len(res["doc_hash"]), 64)
        self.assertIsNotNone(res["pricing"])
        self.assertEqual(res["pricing"]["final_price"], 5000)


if __name__ == "__main__":
    unittest.main()
