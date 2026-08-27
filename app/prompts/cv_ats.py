"""app/prompts/cv_ats.py
Strategy-pattern prompt module for CV ATS Optimization (SERVICE: CV_BUILD / CV_ATS).

CORE RULES:
1. ATS-Friendly Formatting: Single column, clear semantic hierarchy, action-verb driven bullet points.
2. ZERO FABRICATED METRICS (MUTLAK): Dilarang keras mengarang atau menambahkan metrik/angka kuantitatif yang tidak ada pada dokumen asli.
   Jika data angka/metrik tidak disediakan oleh pengguna, pertahankan substansi tindakan dan sisipkan placeholder bertanda kurung siku:
   Contoh: "[Tambahkan metrik persentase peningkatan efisiensi]" atau "[Tambahkan angka pertumbuhan revenue]".
3. Output HANYA berupa JSON valid tanpa teks pengantar maupun markdown penutup.
"""

from typing import Dict, Any

SYSTEM_PROMPT = (
    "Kamu adalah Executive Resume Writer & ATS Optimization Specialist BoonTrack.\n"
    "Tugas Utama: Format ulang dan optimalkan data riwayat hidup kandidat menjadi CV profesional standar internasional yang 100% ramah sistem ATS (Applicant Tracking System).\n\n"
    "PEDOMAN KETAT (STRICT COMPLIANCE):\n"
    "1. ZERO FABRICATED METRICS (DILARANG MEMALSUKAN ANGKA): JANGAN PERNAH mengarang metrik persentase, nominal uang, skala tim, atau angka kuantitatif apa pun yang tidak tercantum dalam input asli.\n"
    "2. PLACEHOLDER BRACKET: Jika suatu pencapaian belum memiliki metrik kuantitatif, restrukturisasi kalimat menjadi action-verb berbobot lalu berikan rekomendasi pengisian metrik dalam tanda kurung siku, misalnya: '[Tambahkan metrik persentase efisiensi]' atau '[Tambahkan estimasi nominal/jumlah klien]'.\n"
    "3. FORMAT ACTION-VERB: Setiap bullet point pengalaman wajib diawali dengan kata kerja aksi kuat (Action Verb) yang relevan dan spesifik (misal: 'Merancang', 'Mengembangkan', 'Mengorkestrasi', 'Mengoptimalkan', 'Memimpin').\n"
    "4. STRUKTUR ATS TUNGGAL: Hasilkan struktur bersih: Nama, Kontak, Professional Summary, Skills (Technical & Soft Skills), Experience, Education, dan Certifications.\n"
    "5. OUTPUT FORMAT: Kembalikan respons HANYA berupa JSON valid sesuai skema yang ditentukan."
)


def get_prompt(raw_text: str, filename: str = "Dokumen_CV") -> str:
    """Menghasilkan prompt terstruktur untuk optimasi CV ATS dengan zero fabrication guarantee."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "Kembalikan output HANYA berupa JSON valid sesuai skema berikut:\n"
        "{\n"
        '  "full_name": "Nama Lengkap Kandidat",\n'
        '  "target_position": "Target Posisi / Profesi",\n'
        '  "email": "email@domain.com",\n'
        '  "phone": "+628123456789",\n'
        '  "location": "Kota, Negara",\n'
        '  "linkedin": "linkedin.com/in/username",\n'
        '  "portfolio": "github.com/username",\n'
        '  "summary": "Ringkasan profesional 2-3 kalimat tajam dengan proposisi nilai tanpa angka fiktif...",\n'
        '  "skills": {\n'
        '    "technical_skills": ["Skill 1", "Skill 2"],\n'
        '    "soft_skills": ["Problem Solving", "Komunikasi Strategis"]\n'
        "  },\n"
        '  "experience": [\n'
        "    {\n"
        '      "role": "Jabatan Pekerjaan",\n'
        '      "company": "Nama Perusahaan / Organisasi",\n'
        '      "period": "2022 - Sekarang",\n'
        '      "location": "Jakarta, Indonesia",\n'
        '      "bullets": [\n'
        '        "Mengembangkan inisiatif operasional untuk mempercepat alur kerja [Tambahkan metrik durasi waktu]",\n'
        '        "Mengkoordinasikan implementasi modul sistem bersama tim lintas divisi [Tambahkan metrik dampak hasil]"\n'
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "education": [\n'
        '    {"degree": "Gelar Pendidikan", "institution": "Nama Institusi Pendidikan", "year": "Tahun Kelulusan"}\n'
        "  ],\n"
        '  "certifications": ["Nama Sertifikasi / Lisensi"]\n'
        "}\n\n"
        f"Konten Naskah CV Pengguna ({filename}):\n{raw_text[:8000]}"
    )


def get_fallback_data(raw_text: str = "") -> Dict[str, Any]:
    """Fallback deterministik jika LLM mengalami kendala respons, tetap mematuhi aturan Zero Fabrication."""
    return {
        "full_name": "KANDIDAT PROFESIONAL",
        "target_position": "Spesialis Profesional",
        "email": "",
        "phone": "",
        "location": "Indonesia",
        "linkedin": "",
        "portfolio": "",
        "summary": "Profesional berdedikasi dengan rekam jejak kerja terstruktur dan komitmen pada peningkatan kualitas kerja berkelanjutan.",
        "skills": {
            "technical_skills": ["Manajemen Kerja", "Analisis Masalah"],
            "soft_skills": ["Komunikasi Efektif", "Kolaborasi Tim"]
        },
        "experience": [
            {
                "role": "Staf Profesional",
                "company": "Organisasi / Perusahaan",
                "period": "2022 - Sekarang",
                "location": "Indonesia",
                "bullets": [
                    "Melaksanakan tugas dan tanggung jawab operasional harian secara efisien dan tepat waktu",
                    "Mengidentifikasi peluang perbaikan alur kerja internal [Tambahkan metrik persentase efisiensi]"
                ]
            }
        ],
        "education": [
            {
                "degree": "Pendidikan Tinggi / Menengah",
                "institution": "Institusi Pendidikan",
                "year": "Lulus"
            }
        ],
        "certifications": []
    }
