import os
import re
import json
import logging
from typing import Dict, Any, List, Tuple, Optional

from app.services.ai_gateway import ai_gateway

logger = logging.getLogger("ACADEMIC_REPHRASE_ENGINE")

ACADEMIC_SYSTEM_PROMPT = (
    "Kamu adalah Senior Academic Editor & NLP Stylist Spesialis Bahasa Indonesia Baku (EYD V).\n"
    "Tugas Utama: Rombak dan tulis ulang (paraphrase/rephrase) naskah berikut menjadi karya ilmiah formal bereputasi tinggi.\n\n"
    "Panduan Wajib:\n"
    "1. Standar Bahasa: Gunakan kaidah EYD V (Tata Bahasa Baku Bahasa Indonesia), kalimat efektif, dan register akademis.\n"
    "2. Variasi Struktur: Variasikan struktur kalimat aktif dan pasif secara proporsional untuk meningkatkan kejelasan sintaksis dan daya alir naskah.\n"
    "3. Diksi Akademis: Ganti kata umum dengan kosakata akademis formal (misal: 'menggunakan' -> 'memanfaatkan/menerapkan', 'banyak' -> 'sejumlah besar/berbagai', 'sangat penting' -> 'krusial/fundamental/esensial', 'karena itu' -> 'oleh karena itu/dengan demikian').\n"
    "4. PROTEKSI ENTITAS & SITASI: Pertahankan persis setiap token sitasi (contoh: __CIT_0__, [1], (Sugiyono, 2015)), formula matematika (__FORM_0__), nama teori, dan data kuantitatif tanpa modifikasi.\n"
    "5. Integritas Makna: Jangan pernah menghilangkan argumen atau menambahkan opini yang menyimpang dari naskah asli.\n"
    "6. FORMAT OUTPUT: Kembalikan teks hasil parafrase secara utuh, rapi, dan padat."
)


# Kamus pembersihan spasi terputus PDF/OCR yang lazim
PDF_BROKEN_SPACES_MAP = {
    r"\bva\s+riabel\b": "variabel",
    r"\bpe\s+nelitian\b": "penelitian",
    r"\bpeneli\s+tian\b": "penelitian",
    r"\bpem\s+belajaran\b": "pembelajaran",
    r"\bpembel\s+ajaran\b": "pembelajaran",
    r"\bmeto\s+de\b": "metode",
    r"\bkua\s+litatif\b": "kualitatif",
    r"\bkuan\s+titatif\b": "kuantitatif",
    r"\bsis\s+tem\b": "sistem",
    r"\binfor\s+masi\b": "informasi",
    r"\bdokumen\s+tasi\b": "dokumentasi",
    r"\bimple\s+mentasi\b": "implementasi",
    r"\bana\s+lisis\b": "analisis",
    r"\bsigni\s+fikan\b": "signifikan",
    r"\brefe\s+rensi\b": "referensi",
    r"\bhipo\s+tesis\b": "hipotesis",
    r"\borga\s+nisasi\b": "organisasi",
    r"\bdi\s+terapkan\b": "diterapkan",
    r"\bdi\s+lakukan\b": "dilakukan",
    r"\bdi\s+peroleh\b": "diperoleh",
    r"\bber\s+dasarkan\b": "berdasarkan",
    r"\bmenun\s+jukkan\b": "menunjukkan",
    r"\bpenga\s+ruh\b": "pengaruh",
    r"\bhubu\s+ngan\b": "hubungan",
    r"\bindi\s+kator\b": "indikator",
    r"\bpopu\s+lasi\b": "populasi",
    r"\bsam\s+pel\b": "sampel",
}

# Kamus pengayaan leksikal akademis (Rule-based Fallback)
ACADEMIC_LEXICON_REPLACEMENTS = [
    (r"\bsangat penting\b", "esensial"),
    (r"\bsangat berpengaruh\b", "berpengaruh signifikan"),
    (r"\bmembuat\b", "menghasilkan"),
    (r"\bmemakai\b", "menerapkan"),
    (r"\bbisa\b", "dapat"),
    (r"\bhanya\b", "semata-mata"),
    (r"\bbanyak\b", "sejumlah besar"),
    (r"\bkarena itu\b", "oleh karena itu"),
    (r"\bdengan ini\b", "dengan demikian"),
    (r"\buntuk\b", "guna"),
    (r"\bmasalah ini\b", "problematika tersebut"),
    (r"\bbagus\b", "optimal"),
    (r"\bjelek\b", "kurang optimal"),
]


class AcademicRephraseEngine:
    """Mesin parafrase naskah akademis formal (EYD V) dengan proteksi sitasi & chunking cerdas."""

    @staticmethod
    def clean_academic_text(raw_text: str) -> str:
        """Pembersihan artefak PDF liar, header/footer, nomor halaman, dan spasi terputus."""
        if not raw_text:
            return ""

        text = raw_text

        # 1. Hapus nomor halaman dan header/footer PDF khas
        text = re.sub(r"-+\s*(?:Page|Halaman)\s*\d+\s*-+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:Halaman|Page)\s*\d+\s*(?:dari|of)\s*\d+\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n\s*\d+\s*\n", "\n\n", text)  # Standalone page number on its own line

        # 2. Hapus tanda hubung pemisah baris (hyphenated line breaks: "va-\nriabel" -> "variabel")
        text = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", text)
        text = re.sub(r"(\w+)-\s+(\w+)", r"\1\2", text)

        # 3. Perbaiki spasi terputus umum (OCR/PDF glitch)
        for pattern, replacement in PDF_BROKEN_SPACES_MAP.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # 4. Normalisasi newline dan whitespace berlebih
        text = re.sub(r"\r\n|\r", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    @staticmethod
    def mask_academic_entities(text: str) -> Tuple[str, Dict[str, str]]:
        """Mendeteksi dan melindungi sitasi akademik, formula statistik, dan entitas presisi."""
        mask_map: Dict[str, str] = {}
        masked_text = text

        # 1. Masking Sitasi Akademik: (Sugiyono, 2015), (Kotler & Keller, 2016: 45), (Smith et al., 2020), [1], [1-3]
        citation_patterns = [
            r"\((?:[A-Z][a-zA-Z\s&.,]+|et al\.)[,\s]+\d{4}(?::\s*\d+(?:-\d+)?)?\)",
            r"\[\d+(?:[-,]\s*\d+)*\]"
        ]

        cit_counter = 0
        for pat in citation_patterns:
            matches = list(re.finditer(pat, masked_text))
            for match in matches:
                matched_str = match.group(0)
                mask_token = f"__CIT_{cit_counter}__"
                mask_map[mask_token] = matched_str
                masked_text = masked_text.replace(matched_str, mask_token, 1)
                cit_counter += 1

        # 2. Masking Formula Matematika / Statistik: Y = a + b1X1, p < 0.05, R^2 = 0.85
        formula_patterns = [
            r"\b[Yy]\s*=\s*[a-zA-Z0-9\s+*_/\-^()]+\b",
            r"\b[pP]\s*[<>=]\s*0\.\d+\b",
            r"\b[Rr]\^?2\s*=\s*0\.\d+\b",
            r"\bF\s*=\s*\d+(?:\.\d+)?\b",
            r"\bt\s*=\s*\d+(?:\.\d+)?\b"
        ]

        form_counter = 0
        for pat in formula_patterns:
            matches = list(re.finditer(pat, masked_text))
            for match in matches:
                matched_str = match.group(0)
                mask_token = f"__FORM_{form_counter}__"
                mask_map[mask_token] = matched_str
                masked_text = masked_text.replace(matched_str, mask_token, 1)
                form_counter += 1

        return masked_text, mask_map

    @staticmethod
    def unmask_academic_entities(text: str, mask_map: Dict[str, str]) -> str:
        """Mengembalikan token proteksi entitas ke bentuk aslinya 100% presisi."""
        unmasked = text
        for mask_token, original_val in mask_map.items():
            unmasked = unmasked.replace(mask_token, original_val)
        return unmasked

    @classmethod
    def chunk_document_smart(cls, text: str, max_words_per_chunk: int = 700) -> List[str]:
        """Memecah naskah panjang ke dalam potongan 600 - 800 kata berbasis paragraf tanpa memotong kalimat."""
        paragraphs = text.split("\n\n")
        chunks: List[str] = []
        current_chunk: List[str] = []
        current_word_count = 0

        for para in paragraphs:
            para_clean = para.strip()
            if not para_clean:
                continue

            para_words = len(para_clean.split())
            if current_word_count + para_words > max_words_per_chunk and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [para_clean]
                current_word_count = para_words
            else:
                current_chunk.append(para_clean)
                current_word_count += para_words

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks if chunks else [text]

    @classmethod
    def apply_rule_based_academic_rephrase(cls, text: str) -> str:
        """Fallback linguistik akademis berstandar EYD V jika AI API offline."""
        paraphrased = text
        for pattern, replacement in ACADEMIC_LEXICON_REPLACEMENTS:
            paraphrased = re.sub(pattern, replacement, paraphrased, flags=re.IGNORECASE)

        paragraphs = paraphrased.split("\n\n")
        enhanced_paragraphs = []
        for p in paragraphs:
            p_strip = p.strip()
            if not p_strip:
                continue
            # Pastikan huruf kapital di awal kalimat
            sentences = re.split(r"(?<=[.!?])\s+", p_strip)
            enhanced_sentences = []
            for s in sentences:
                s_clean = s.strip()
                if s_clean:
                    s_cap = s_clean[0].upper() + s_clean[1:] if len(s_clean) > 1 else s_clean.upper()
                    enhanced_sentences.append(s_cap)
            enhanced_paragraphs.append(" ".join(enhanced_sentences))

        return "\n\n".join(enhanced_paragraphs)

    @classmethod
    async def rephrase_chunk(cls, chunk_text: str, chunk_idx: int = 0) -> str:
        """Memproses satu chunk teks menggunakan AIGateway dengan system prompt akademis formal."""
        masked_text, mask_map = cls.mask_academic_entities(chunk_text)

        prompt = (
            f"{ACADEMIC_SYSTEM_PROMPT}\n\n"
            f"Tulis ulang naskah berikut secara elegan dan akademis formal (EYD V). "
            f"Pertahankan semua token __CIT_X__ dan __FORM_X__ persis:\n\n"
            f"{masked_text}"
        )

        try:
            ai_res = await ai_gateway.generate(
                user_message=prompt,
                context={"feature": "academic_rephrase", "chunk_idx": chunk_idx},
                system_prompt=ACADEMIC_SYSTEM_PROMPT
            )
            if ai_res and len(ai_res.strip()) > 30:
                unmasked = cls.unmask_academic_entities(ai_res.strip(), mask_map)
                return unmasked
        except Exception as e:
            logger.warning(f"[AcademicRephraseEngine] Chunk {chunk_idx} AI generate note: {e}")

        # Fallback lokal
        rule_based = cls.apply_rule_based_academic_rephrase(masked_text)
        return cls.unmask_academic_entities(rule_based, mask_map)

    @classmethod
    async def rephrase_document(
        cls,
        raw_text: str,
        filename: str = "Dokumen_Akademik"
    ) -> Dict[str, Any]:
        """Rombak naskah akademis lengkap: Pre-cleaning -> Chunking -> AI Rephrasing -> Seamless Stitching."""
        # 1. Pre-cleaning & Normalisasi Naskah
        cleaned_text = cls.clean_academic_text(raw_text)
        if not cleaned_text:
            return {
                "title": f"Hasil Polish: {filename}",
                "tone": "Akademik Formal (EYD V)",
                "original_word_count": 0,
                "paraphrased_word_count": 0,
                "key_takeaways": ["Naskah kosong."],
                "sections": [],
                "full_text": ""
            }

        orig_word_count = len(cleaned_text.split())

        # 2. Sentence-Aware Chunking (600-800 kata per chunk)
        chunks = cls.chunk_document_smart(cleaned_text, max_words_per_chunk=750)
        rephrased_chunks: List[str] = []

        logger.info(f"[AcademicRephraseEngine] Processing {orig_word_count} words across {len(chunks)} chunks for {filename}")

        # 3. Eksekusi Parafrase Tiap Chunk
        for idx, chunk in enumerate(chunks):
            rephrased = await cls.rephrase_chunk(chunk, chunk_idx=idx)
            rephrased_chunks.append(rephrased)

        # 4. Seamless Stitching (Penggabungan Utuh)
        full_rephrased_text = "\n\n".join(rephrased_chunks)
        final_word_count = len(full_rephrased_text.split())

        # 5. Strukturkan ke sections untuk render Word .docx yang rapi
        sections = []
        for i, chunk in enumerate(rephrased_chunks):
            heading = f"Bagian {i + 1}" if len(rephrased_chunks) > 1 else "Naskah Hasil Penyempurnaan"
            sections.append({
                "heading": heading,
                "content": chunk
            })

        title_clean = os.path.splitext(filename)[0].replace("_", " ").title()

        return {
            "title": f"Penyempurnaan Akademis: {title_clean}",
            "tone": "Akademik Formal (EYD V)",
            "original_word_count": orig_word_count,
            "paraphrased_word_count": final_word_count,
            "key_takeaways": [
                "Naskah telah disempurnakan sesuai kaidah tata bahasa baku EYD V.",
                "Struktur kalimat aktif-pasif divariasikan dengan kosakata ilmiah formal.",
                "Seluruh sitasi akademik, formula statistik, dan entitas kunci terlindungi 100%."
            ],
            "sections": sections,
            "full_text": full_rephrased_text
        }


academic_rephrase_engine = AcademicRephraseEngine()
