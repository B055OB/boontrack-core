"""app/prompts/cv_review.py
Strategy-pattern prompt module for HR CV Review & ATS Diagnostic (SERVICE: CV_REVIEW).

CORE RULES:
1. Menghasilkan Structured JSON lengkap:
   - ats_score (overall score 0-100)
   - breakdown_scores (ats_compatibility, content_impact, structure_grammar, keyword_alignment)
   - strengths (analisis kelebihan profil)
   - red_flags (faktor kritis yang berpotensi menggugurkan pelamar di mata HR)
   - missing_keywords (kata kunci industri/peran yang belum dicantumkan)
   - actionable_fixes (rekomendasi perbaikan konkret per section)
   - priority_improvements (langkah perbaikan prioritas tertinggi)
2. Output HANYA berupa JSON valid tanpa teks pengantar maupun markdown penutup.
"""

from typing import Dict, Any

SYSTEM_PROMPT = (
    "Kamu adalah Senior HR Executive & Lead ATS Auditor BoonTrack.\n"
    "Tugas Utama: Lakukan audit komprehensif terhadap CV pengguna menggunakan standar seleksi HR korporat internasional dan algoritma ATS modern.\n\n"
    "ASPEK AUDIT WAJIB:\n"
    "1. SKOR ATS (0-100): Evaluasi kompatibilitas parsing, tata letak, keterbacaan bot, dan kekuatan bobot pengalaman.\n"
    "2. KEKUATAN UTAMA (STRENGTHS): Poin nilai jual kandidat yang paling menonjol.\n"
    "3. RED FLAGS & RISIKO KRITIS: Temuan kritis yang dapat memicu auto-rejection dari HR (misal: bullet points pasif tanpa metrik, gap yang tidak dijelaskan, layout tabel/grafik sulit di-parse, typo).\n"
    "4. MISSING KEYWORDS: Istilah teknis, tools industri, atau kompetensi inti yang lazim dicari namun absen dari CV.\n"
    "5. ACTIONABLE FIXES: Langkah konkret perbaikan per bagian CV dengan formula Tindakan + Konteks + Metrik Hasil.\n"
    "6. PRIORITY IMPROVEMENTS: 2-3 perbaikan berdampak tercepat dan tertinggi yang harus segera diterapkan kandidat."
)


def get_prompt(raw_text: str, filename: str = "Dokumen_CV") -> str:
    """Menghasilkan prompt audit HR & ATS lengkap."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "Kembalikan output HANYA berupa JSON valid sesuai skema berikut:\n"
        "{\n"
        '  "ats_score": 82,\n'
        '  "overall_score": 82,\n'
        '  "target_role": "Target Posisi / Profesi Kandidat",\n'
        '  "summary": "Ringkasan eksekutif audit CV...",\n'
        '  "breakdown_scores": {\n'
        '    "ats_compatibility": 88,\n'
        '    "content_impact": 75,\n'
        '    "structure_grammar": 84,\n'
        '    "keyword_alignment": 80\n'
        "  },\n"
        '  "strengths": [\n'
        '    "Riwayat kerja dan kronologi karir tersusun runtut",\n'
        '    "Latar belakang pendidikan dan kualifikasi dasar relevan"\n'
        "  ],\n"
        '  "red_flags": [\n'
        '    "Sebagian besar pengalaman kerja ditulis secara deskriptif tanpa indikator capaian terukur",\n'
        '    "Format kontak belum menyertakan tautan profil profesional aktif"\n'
        "  ],\n"
        '  "missing_keywords": [\n'
        '    "Project Management", "Data-Driven Decision Making", "Stakeholder Management"\n'
        "  ],\n"
        '  "actionable_fixes": [\n'
        '    {\n'
        '      "section": "Experience",\n'
        '      "issue": "Deskripsi pekerjaan bersifat pasif",\n'
        '      "fix": "Ubah ke Action Verbs aktif serta lengkapi metrik [Tambahkan angka/persentase]"\n'
        "    },\n"
        '    {\n'
        '      "section": "Summary",\n'
        '      "issue": "Terlalu umum dan belum memuat nilai pembeda",\n'
        '      "fix": "Tuliskan ringkasan 3 kalimat: Posisi + Keahlian Inti + Pencapaian Utama"\n'
        "    }\n"
        "  ],\n"
        '  "priority_improvements": [\n'
        '    "Restrukturisasi bullet poin pengalaman kerja menggunakan metode STAR",\n'
        '    "Tambahkan kata kunci industri yang relevan ke dalam ringkasan dan bagian keahlian"\n'
        "  ]\n"
        "}\n\n"
        f"Konten Naskah CV Pengguna ({filename}):\n{raw_text[:8000]}"
    )


def get_fallback_data(raw_text: str = "") -> Dict[str, Any]:
    """Fallback deterministik jika LLM gagal merespons valid JSON."""
    return {
        "ats_score": 78,
        "overall_score": 78,
        "target_role": "Kandidat Profesional",
        "summary": "CV memiliki fondasi yang cukup baik, namun memerlukan penguatan pada format bullet point berbasis metrik dan keselarasan kata kunci ATS.",
        "breakdown_scores": {
            "ats_compatibility": 82,
            "content_impact": 72,
            "structure_grammar": 80,
            "keyword_alignment": 76
        },
        "strengths": [
            "Riwayat pendidikan dan informasi kontak tersusun jelas",
            "Struktur pengalaman kerja memiliki kronologi yang runut"
        ],
        "red_flags": [
            "Bullet point pengalaman kerja masih belum menyertakan angka metrik pencapaian kuantitatif",
            "Profil ringkasan profesional masih berfokus pada daftar tugas daripada proposisi nilai"
        ],
        "missing_keywords": [
            "KPI Tracking",
            "Cross-Functional Collaboration",
            "Process Optimization"
        ],
        "actionable_fixes": [
            {
                "section": "Experience",
                "issue": "Poin pengalaman bersifat deskripsi tugas harian",
                "fix": "Terapkan formula Tindakan + Konteks + Metrik Hasil [Tambahkan angka % / volume]"
            },
            {
                "section": "Summary",
                "issue": "Ringkasan belum menonjolkan keahlian kunci spesifik",
                "fix": "Sertakan elevator pitch 3 kalimat yang merangkum spesialisasi dan pencapaian"
            }
        ],
        "priority_improvements": [
            "Lengkapi metrik pencapaian pada setiap posisi pekerjaan",
            "Sesuaikan kata kunci industri pada bagian skills dan ringkasan"
        ]
    }
