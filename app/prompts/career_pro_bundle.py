"""app/prompts/career_pro_bundle.py
Strategy-pattern prompt module for Career Pro Bundle (SERVICE: CAREER_PRO_BUNDLE).

CORE RULES:
1. Orchestrates 3 Essential Career Pillars:
   - Part 1: CV Tailored ATS (Format single column, action-verbs, ZERO FABRICATED METRICS - placeholders if missing).
   - Part 2: Rekomendasi HR Profesional (Profile readiness, strengths, interview STAR guide, career trajectory).
   - Part 3: Surat Lamaran Kerja / Cover Letter (Formal, highly persuasive, customized for target role).
2. Output HANYA berupa JSON valid tanpa teks pengantar maupun markdown penutup.
"""

from typing import Dict, Any

SYSTEM_PROMPT = (
    "Kamu adalah Principal Career Strategist & Senior HR Executive BoonTrack.\n"
    "Tugas Utama: Buat Paket Lengkap Karir Pro (Career Pro Bundle) dari profil pengguna yang mencakup 3 pilar wajib:\n\n"
    "PILAR 1: CV ATS TAILORED\n"
    "- Format ulang riwayat kerja menjadi standar ATS internasional dengan Action Verbs kuat.\n"
    "- ATURAN MUTLAK ZERO FABRICATION: Dilarang keras mengarang metrik/angka fiktif! Jika tidak ada data kuantitatif, gunakan placeholder bracket '[Tambahkan metrik persentase/angka]'.\n\n"
    "PILAR 2: REKOMENDASI HR & PANDUAN INTERVIEW STAR\n"
    "- Analisis kesiapan profil kandidat di pasar kerja saat ini.\n"
    "- Identifikasi kekuatan pembeda utama dan saran pengembangan strategis.\n"
    "- Berikan panduan wawancara HR spesifik berbasis metode STAR (Situation, Task, Action, Result).\n\n"
    "PILAR 3: SURAT LAMARAN KERJA (COVER LETTER)\n"
    "- Tuliskan surat lamaran kerja formal, persuasif, dan elegan yang siap diajukan ke HR recruiter posisi target.\n"
    "- Terdiri dari salam pembuka, opening hook yang kuat, 2 paragraf inti berbasis proposisi nilai, closing statement persuasif, dan sign-off resmi."
)


def get_prompt(raw_text: str, filename: str = "Dokumen_Karir", target_role: str = "") -> str:
    """Menghasilkan prompt composite Career Pro Bundle."""
    target_note = f" (Target Posisi Spesifik: {target_role})" if target_role else ""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Target Posisi{target_note}\n\n"
        "Kembalikan output HANYA berupa JSON valid sesuai skema berikut:\n"
        "{\n"
        '  "full_name": "Nama Lengkap Kandidat",\n'
        '  "target_position": "Target Posisi Karir",\n'
        '  "email": "email@example.com",\n'
        '  "phone": "+628123456789",\n'
        '  "location": "Jakarta, Indonesia",\n'
        '  "linkedin": "linkedin.com/in/username",\n'
        '  "portfolio": "github.com/username",\n'
        '  "summary": "Ringkasan profesional ATS dengan proposisi nilai tanpa angka rekayasa...",\n'
        '  "skills": {\n'
        '    "technical_skills": ["Skill 1", "Skill 2"],\n'
        '    "leadership_soft_skills": ["Komunikasi Strategis", "Problem Solving"]\n'
        "  },\n"
        '  "experience": [\n'
        "    {\n"
        '      "role": "Jabatan Pekerjaan",\n'
        '      "company": "Nama Perusahaan",\n'
        '      "period": "2022 - Sekarang",\n'
        '      "location": "Jakarta, Indonesia",\n'
        '      "bullets": [\n'
        '        "Memimpin implementasi proses operasional baru guna meningkatkan kepuasan kerja tim [Tambahkan metrik %]",\n'
        '        "Mengorkestrasi koordinasi antar-divisi dalam penyelesaian proyek prioritas [Tambahkan metrik hasil]"\n'
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "education": [\n'
        '    {"degree": "Sarjana / Diploma", "institution": "Perguruan Tinggi", "year": "2018 - 2022"}\n'
        "  ],\n"
        '  "certifications": ["Sertifikasi Profesional Relevan"],\n'
        '  "hr_recommendations": {\n'
        '    "profile_readiness": "Sangat Siap & Kompetitif",\n'
        '    "key_strengths": [\n'
        '      "Latar belakang pengalaman relevan dengan alur kerja modern",\n'
        '      "Keahlian komunikasi dan kepemimpinan tim terbukti dalam proyek sebelumnya"\n'
        '    ],\n'
        '    "strategic_improvements": [\n'
        '      "Lengkapi portofolio dengan studi kasus nyata",\n'
        '      "Pertajam elaborasi peran individu dalam proyek kolaboratif"\n'
        '    ],\n'
        '    "interview_tips": [\n'
        '      "Jelaskan tantangan operasional terbesar menggunakan metode STAR secara runut",\n'
        '      "Tunjukkan antusiasme dan pemahaman mendalam mengenai industri target"\n'
        '    ]\n'
        "  },\n"
        '  "cover_letter": {\n'
        '    "recipient": "Yth. Tim Rekrutmen & Hiring Manager",\n'
        '    "subject": "Aplikasi Lamaran Pekerjaan - Target Posisi Karir",\n'
        '    "salutation": "Dengan hormat,",\n'
        '    "opening": "Melalui surat ini, saya bermaksud untuk menyampaikan ketertarikan mendalam saya untuk bergabung pada posisi Target Posisi Karir...",\n'
        '    "body_paragraphs": [\n'
        '      "Dengan pengalaman profesional yang saya bangun selama ini, saya telah terbiasa mengelola inisiatif kerja secara terukur...",\n'
        '      "Keahlian utama saya dalam koordinasi lintas fungsi dan penyelesaian masalah analitis akan memungkinkan saya memberikan kontribusi nyata sejak hari pertama."\n'
        '    ],\n'
        '    "closing": "Besar harapan saya untuk memperoleh kesempatan wawancara agar dapat memaparkan secara langsung bagaimana kompetensi saya selaras dengan tujuan strategis perusahaan.",\n'
        '    "sign_off": "Hormat saya,\\nNama Lengkap Kandidat"\n'
        "  }\n"
        "}\n\n"
        f"Konten Naskah Pengguna ({filename}):\n{raw_text[:8000]}"
    )


def get_fallback_data(raw_text: str = "") -> Dict[str, Any]:
    """Fallback deterministik jika LLM gagal mengembalikan respon JSON."""
    return {
        "full_name": "KANDIDAT PROFESIONAL",
        "target_position": "Spesialis Karir Profesional",
        "email": "",
        "phone": "",
        "location": "Indonesia",
        "linkedin": "",
        "portfolio": "",
        "summary": "Profesional berdedikasi tinggi dengan pengalaman kerja terstruktur, kemampuan komunikasi efektif, dan rekam jejak kerja kolaboratif.",
        "skills": {
            "technical_skills": ["Manajemen Proyek", "Analisis Alur Kerja"],
            "leadership_soft_skills": ["Komunikasi Efektif", "Pemecahan Masalah"]
        },
        "experience": [
            {
                "role": "Staf Profesional",
                "company": "Perusahaan Terkemuka",
                "period": "2021 - Sekarang",
                "location": "Indonesia",
                "bullets": [
                    "Melaksanakan operasional kerja harian secara konsisten dan tepat waktu",
                    "Mendukung optimalisasi proses kerja tim internal [Tambahkan metrik capaian %]"
                ]
            }
        ],
        "education": [
            {
                "degree": "Sarjana / Diploma",
                "institution": "Perguruan Tinggi Terakreditasi",
                "year": "2021"
            }
        ],
        "certifications": ["Pelatihan Profesional Terverifikasi"],
        "hr_recommendations": {
            "profile_readiness": "Kompetitif & Siap Seleksi",
            "key_strengths": [
                "Rekam jejak kerja jelas dan relevan",
                "Keahlian komunikasi dan adaptasi kerja cepat"
            ],
            "strategic_improvements": [
                "Tambahkan sertifikasi spesialisasi lanjutan",
                "Lengkapi metrik kuantitatif di setiap pengalaman kerja"
            ],
            "interview_tips": [
                "Siapkan 2 studi kasus sukses dengan metode STAR",
                "Tekankan kontribusi spesifik pada pencapaian tim"
            ]
        },
        "cover_letter": {
            "recipient": "Yth. Tim Rekrutmen & Hiring Manager",
            "subject": "Aplikasi Lamaran Pekerjaan - Spesialis Karir Profesional",
            "salutation": "Dengan hormat,",
            "opening": "Saya menulis surat ini untuk menyampaikan minat dan komitmen saya terhadap lowongan posisi Spesialis Karir Profesional di perusahaan Bapak/Ibu.",
            "body_paragraphs": [
                "Berdasarkan pengalaman yang telah saya jalani, saya memiliki pemahaman yang kuat dalam pengelolaan alur kerja operasional serta kolaborasi lintas divisi.",
                "Saya meyakini bahwa etos kerja dan dedikasi yang saya miliki dapat memberikan kontribusi positif dalam mendukung pencapaian target perusahaan."
            ],
            "closing": "Terima kasih atas waktu dan kesempatan yang diberikan untuk meninjau lamaran saya. Saya sangat menantikan kesempatan untuk berdiskusi lebih lanjut.",
            "sign_off": "Hormat saya,\nKandidat Profesional"
        }
    }
