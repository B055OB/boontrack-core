import unittest
import io
from docx import Document
from app.engines.rephrase_engine import academic_rephrase_engine, AcademicRephraseEngine
from app.services.doc_builder import build_document_result, chunk_document_text


def compute_levenshtein_distance(s1: str, s2: str) -> int:
    """Helper untuk menghitung Levenshtein distance antara dua string."""
    if len(s1) < len(s2):
        return compute_levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def compute_word_overlap_ratio(text_a: str, text_b: str) -> float:
    """Menghitung rasio kesamaan kata (Jaccard similarity)."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a.intersection(words_b)
    union = words_a.union(words_b)
    return len(intersection) / len(union)


class TestRephraseQuality(unittest.IsolatedAsyncioTestCase):
    """Test suite komprehensif untuk memverifikasi kualitas rephrase, pembersihan artefak, dan proteksi sitasi."""

    def test_pdf_artifact_scrubbing_and_typo_correction(self):
        """Memverifikasi pembersihan nomor halaman liar, spasi terputus, dan typo akademik."""
        dirty_input = (
            "--- Page 28 ---\n"
            "29 30\n"
            "Penelotian ini memakai metedologi kualitatif guna melihat va riabel terikat.\n"
            "Metode ini sangat penting untuk orga nisasi dalam meman faatkan infor masi.\n"
            "Halaman 29 dari 50\n"
            "12\n"
            "Berdasarkan analisa data, temuan ini menunjukkan bahwa sis tem informasi sangat berpengaruh."
        )

        cleaned = AcademicRephraseEngine.clean_academic_text(dirty_input)

        # 1. Pastikan nomor halaman mandiri terhapus
        self.assertNotIn("29 30", cleaned)
        self.assertNotIn("--- Page 28 ---", cleaned)
        self.assertNotIn("Halaman 29 dari 50", cleaned)
        self.assertNotIn("\n12\n", cleaned)

        # 2. Pastikan spasi terputus OCR diperbaiki
        self.assertIn("variabel", cleaned)
        self.assertIn("organisasi", cleaned)
        self.assertIn("informasi", cleaned)
        self.assertIn("sistem", cleaned)

        # 3. Pastikan typo naskah asli dikoreksi ke EYD V
        self.assertIn("penelitian", cleaned)
        self.assertNotIn("penelotian", cleaned)
        self.assertIn("metodologi", cleaned)
        self.assertNotIn("metedologi", cleaned)
        self.assertIn("analisis", cleaned)
        self.assertNotIn("analisa", cleaned)

    async def test_citation_and_formula_integrity_protection(self):
        """Memverifikasi bahwa sitasi naratif, sitasi kurung, dan formula matematika tidak pernah terdistorsi."""
        academic_text = (
            "Menurut Sugiyono (2015), efisiensi kinerja dipengaruhi oleh kepemimpinan. "
            "Hal ini diperkuat oleh Dendawijaya & Lukman (2015) serta temuan empiris (Fatihudin, 2020). "
            "Model regresi yang diestimasi adalah Y = a + b1X1 + b2X2 + e dengan tingkat signifikansi p < 0.05 "
            "dan koefisien determinasi R^2 = 0.85 serta uji simultan F = 14.2 dan t = 3.12 pada sampel N = 120."
        )

        # Masking test
        masked, mask_map = AcademicRephraseEngine.mask_academic_entities(academic_text)
        self.assertIn("__CIT_", masked)
        self.assertIn("__FORM_", masked)

        # Unmasking test
        unmasked = AcademicRephraseEngine.unmask_academic_entities(masked, mask_map)
        self.assertIn("Sugiyono (2015)", unmasked)
        self.assertIn("Dendawijaya & Lukman (2015)", unmasked)
        self.assertIn("(Fatihudin, 2020)", unmasked)
        self.assertIn("Y = a + b1X1 + b2X2 + e", unmasked)
        self.assertIn("p < 0.05", unmasked)
        self.assertIn("R^2 = 0.85", unmasked)
        self.assertIn("F = 14.2", unmasked)
        self.assertIn("t = 3.12", unmasked)
        self.assertIn("N = 120", unmasked)

        # Full rephrase pipeline execution
        res = await academic_rephrase_engine.rephrase_document(academic_text, filename="Jurnal_Keuangan.docx")
        full_result_text = res["full_text"]

        # Validasi sitasi & formula tetap utuh di output final
        self.assertIn("Sugiyono (2015)", full_result_text)
        self.assertIn("Dendawijaya & Lukman (2015)", full_result_text)
        self.assertIn("(Fatihudin, 2020)", full_result_text)
        self.assertIn("Y = a + b1X1 + b2X2 + e", full_result_text)
        self.assertIn("p < 0.05", full_result_text)

    async def test_rephrase_transformation_and_not_identical_copy(self):
        """Memverifikasi bahwa naskah hasil rephrase mengalami transformasi sintaksis & leksikal (bukan copy-paste)."""
        raw_text = (
            "Penelitian ini memakai metode kualitatif untuk melihat masalah ini. "
            "Sangat penting bagi organisasi untuk membuat sistem yang bagus karena sangat berpengaruh. "
            "Selain itu, hasil penelitian membuktikan bahwa karyawan bisa bekerja lebih baik."
        )

        res = await academic_rephrase_engine.rephrase_document(raw_text, filename="Evaluasi_SDM.docx")
        rephrased_text = res["full_text"]

        # 1. Pastikan tidak 100% identik dengan teks awal
        self.assertNotEqual(raw_text.strip(), rephrased_text.strip())

        # 2. Pastikan ada jarak Levenshtein yang signifikan
        dist = compute_levenshtein_distance(raw_text, rephrased_text)
        self.assertGreater(dist, 20, f"Levenshtein distance terlalu kecil ({dist}), teks kurang di-rephrase!")

        # 3. Pastikan kata-kata informal diganti dengan kosakata formal akademis
        self.assertNotIn("sangat penting bagi", rephrased_text.lower())
        self.assertNotIn("membuat sistem yang bagus", rephrased_text.lower())
        self.assertIn("esensial", rephrased_text.lower())
        self.assertIn("optimal", rephrased_text.lower())

    async def test_long_document_subbab_chunking_and_seamless_stitching(self):
        """Memverifikasi bahwa dokumen panjang (> 800 kata) di-chunk per sub-bab/paragraf 500-700 kata dan dijahit mulus."""
        subbab_1 = "BAB I PENDAHULUAN\n\n" + (
            "Latar belakang permasalahan dalam penelitian ini menitikberatkan pada dinamika transformasi digital organisasi. "
            "Perubahan pola kerja memerlukan adaptasi sistem yang berkelanjutan guna mempertahankan efisiensi operasional tim. "
        ) * 18 # ~360 kata

        subbab_2 = "BAB II TINJAUAN PUSTAKA\n\n" + (
            "Landasan teori kepemimpinan transformasional dikembangkan berdasarkan kajian Sugiyono (2015). "
            "Dendawijaya & Lukman (2015) mengemukakan bahwa integrasi teknologi berpengaruh signifikan terhadap produktivitas. "
        ) * 18 # ~360 kata

        subbab_3 = "BAB III METODE PENELITIAN\n\n" + (
            "Pendekatan yang diterapkan dalam penelitian ini adalah metode kuantitatif dengan model regresi Y = a + b1X1 + e. "
            "Pengumpulan data dilakukan melalui kuesioner kepada responden dengan kriteria yang telah ditentukan. "
        ) * 18 # ~360 kata

        long_document = f"{subbab_1}\n\n{subbab_2}\n\n{subbab_3}"
        total_words = len(long_document.split())
        self.assertGreater(total_words, 1000)

        # Test chunking helper
        chunks = AcademicRephraseEngine.chunk_document_smart(long_document, max_words_per_chunk=650)
        self.assertGreaterEqual(len(chunks), 3)

        # Test full rephrase pipeline with seamless stitching
        result = await academic_rephrase_engine.rephrase_document(long_document, filename="Skripsi_Lengkap.docx")
        self.assertEqual(len(result["sections"]), len(chunks))
        self.assertGreater(result["paraphrased_word_count"], 900)

        # Pastikan naskah lengkap dijahit tanpa terpotong di tengah kalimat
        self.assertTrue(result["full_text"].endswith(".") or result["full_text"].endswith("!"))

        # Test rendering ke format docx
        docx_bytes = build_document_result("POLISH_REPHRASE", result)
        self.assertGreater(len(docx_bytes), 1000)


if __name__ == "__main__":
    unittest.main()
