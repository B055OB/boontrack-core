import logging
import json
from app.services.ai_gateway import ai_gateway
from app.services.docx_service import generate_cv_docx

logger = logging.getLogger(__name__)

CV_POLISHER_PROMPT = """
Kamu adalah Konsultan Karir Senior & ATS Specialist Internasional.
Tugasmu: Mengubah data profil dan pengalaman kerja mentah dari user menjadi narasi CV profesional berstandar ATS tingkat tinggi.

Format bahasa yang diinginkan: {lang_mode}

Data Mentah User:
- Nama: {name}
- Email: {email}
- Kontak: {phone}
- Domisili: {city}
- Target Posisi: {target_position}
- Pengalaman Kerja: {raw_experience}
- Pendidikan: {raw_education}
- Keahlian (Skills): {raw_skills}
- Sertifikasi/Portofolio: {raw_cert}
- Ringkasan Diri: {raw_summary}

Instruksi Transformasi:
1. SUMMARY: Buat 2-3 kalimat ringkasan profesional yang memikat, percaya diri, dan relevan dengan target posisi.
2. EXPERIENCE: Pecah setiap entri kerja (meski hanya dipisah koma/spasi). Untuk setiap posisi, buat 2-3 bullet point pencapaian menggunakan Action Verbs aktif & metrik realistis (Google XYZ formula). Urutkan dari yang terbaru ke terlama. Jika fresh graduate/kosong, buatkan 1-2 proyek relevan/organisasi.
3. SKILLS: Kelompokkan menjadi Hard Skills relevan dan Tools industri.
4. Pastikan output JSON valid tanpa teks markdown di luar blok JSON.

Keluarkan hasil HANYA dalam format JSON dengan struktur:
{{
  "name": "...",
  "phone": "...",
  "email": "...",
  "city": "...",
  "target_position": "...",
  "summary": "...",
  "experience": [
    {{
      "role": "...",
      "company": "...",
      "period": "...",
      "bullet_points": ["...", "..."]
    }}
  ],
  "education": [
    {{
      "degree_or_major": "...",
      "institution": "...",
      "year": "..."
    }}
  ],
  "skills": ["Skill 1", "Skill 2", "Skill 3"],
  "certifications": ["Cert 1", "Cert 2"]
}}
"""

class CVGeneratorService:
    async def polish_and_build_cv(self, user_id: str, raw_data: dict, lang_mode: str = "id") -> str:
        """
        Memoles data mentah via AI, lalu mengekspor ke file DOCX.
        Mengembalikan file_path dokumen yang berhasil dibuat.
        """
        try:
            # 1. Parsing input mentah dari 10 langkah
            name = raw_data.get(1, "Job Seeker")
            phone = raw_data.get(2, "-")
            email = raw_data.get(3, "-")
            city = raw_data.get(4, "-")
            target_pos = raw_data.get(5, "General Professional")
            experience = raw_data.get(6, "-")
            education = raw_data.get(7, "-")
            skills = raw_data.get(8, "-")
            cert = raw_data.get(9, "-")
            summary = raw_data.get(10, "-")

            lang_label = "Full English" if lang_mode == "en" else ("English CV with Indonesian context" if lang_mode == "en_id" else "Bahasa Indonesia")

            # 2. Kirim ke AI Gateway untuk di-polish
            prompt = CV_POLISHER_PROMPT.format(
                lang_mode=lang_label,
                name=name,
                phone=phone,
                email=email,
                city=city,
                target_position=target_pos,
                raw_experience=experience,
                raw_education=education,
                raw_skills=skills,
                raw_cert=cert,
                raw_summary=summary
            )

            ai_response = await ai_gateway.ask(prompt, user_id=user_id)
            
            # 3. Clean JSON Output
            clean_json = ai_response.replace("```json", "").replace("```", "").strip()
            polished_data = json.loads(clean_json)

            # 4. Render ke file DOCX
            file_path = await generate_cv_docx(user_id, polished_data)
            return file_path

        except Exception as e:
            logger.error(f"[CV Generator Service Error] {e}")
            # Fallback jika AI timeout/error: render data apa adanya
            return await generate_cv_docx(user_id, raw_data)

cv_generator_service = CVGeneratorService()
