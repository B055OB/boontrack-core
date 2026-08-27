import re
import json
from typing import Dict, Any, List, Optional

class CVReviewEngine:
    """
    Deterministic & Rule-Based CV Review Engine.
    Menghitung skor CV matematis dan menyusun evaluasi komprehensif.
    """

    def __init__(self):
        # Action Verbs untuk pengukuran Evidence & Achievement Strength
        self.action_verbs = {
            "meningkatkan", "mengembangkan", "mengelola", "memimpin", "merancang",
            "membangun", "mengoptimalkan", "mengurangi", "menganalisis", "menyusun",
            "mengeksekusi", "mencapai", "memproduksi", "mengkoordinasikan", "implemented",
            "developed", "managed", "increased", "reduced", "designed", "led", "optimized"
        }

    def evaluate_cv(
        self,
        cv_text: str,
        target_position: Optional[str] = None,
        user_skills: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Evaluasi teks CV deterministik dengan 5 Breakdown Kategori ATS.
        """
        clean_text = cv_text.lower()
        user_skills = user_skills or []

        # 1. Hitung 5 Breakdown Kategori ATS
        ats_compatibility = self._calc_ats_compatibility(clean_text)
        experience_score = self._calc_experience_score(clean_text)
        achievement_score = self._calc_achievement_score(clean_text)
        keyword_score = self._calc_keyword_score(clean_text, target_position, user_skills)
        structure_score = self._calc_structure_score(clean_text)

        # 2. Hitung Overall Score (Bobot Rata-rata ATS)
        overall_score = int(
            (ats_compatibility * 0.20) +
            (experience_score * 0.25) +
            (achievement_score * 0.25) +
            (keyword_score * 0.15) +
            (structure_score * 0.15)
        )

        # 3. Ekstrak Temuan Masalah Baku (Top Findings)
        findings = self._extract_findings(
            clean_text,
            ats_compatibility,
            experience_score,
            achievement_score,
            keyword_score,
            structure_score
        )

        # 4. Tentukan Confidence Level
        word_count = len(clean_text.split())
        if word_count < 50 or structure_score < 35:
            confidence_level = "LOW"
            confidence_reason = "Informasi CV masih minim sehingga evaluasi parsing ATS belum maksimal."
        elif overall_score < 70:
            confidence_level = "MEDIUM"
            confidence_reason = "Struktur CV terdeteksi, namun rincian metrik angka & kata kerja aksi masih minim."
        else:
            confidence_level = "HIGH"
            confidence_reason = "Data dan struktur CV sangat lengkap untuk lolos seleksi ATS."

        return {
            "overall_score": overall_score,
            "breakdown_scores": {
                "ats_compatibility": ats_compatibility,
                "experience": experience_score,
                "achievement": achievement_score,
                "keyword": keyword_score,
                "structure": structure_score
            },
            "findings": findings,
            "metrics_detected": {
                "numeric_evidence_count": len(re.findall(r'\b\d+([.,]\d+)?%?\b', clean_text)),
                "action_verb_count": sum(1 for verb in self.action_verbs if verb in clean_text),
                "has_email": bool(re.search(r'[\w\.-]+@[\w\.-]+\.\w+', clean_text)),
                "has_phone": bool(re.search(r'(\+62|62|08)[0-9]{8,12}', clean_text))
            },
            "confidence": {
                "level": confidence_level,
                "reason": confidence_reason
            }
        }

    def _calc_ats_compatibility(self, text: str) -> int:
        """Menilai keterbacaan teks murni & kelengkapan identitas standar ATS."""
        score = 30
        if re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text):
            score += 35
        if re.search(r'(\+62|62|08)[0-9]{8,12}', text):
            score += 35
        return min(score, 100)

    def _calc_experience_score(self, text: str) -> int:
        """Menilai kelengkapan kronologis dan kata kerja aksi dalam pengalaman kerja."""
        score = 20
        if any(w in text for w in ["pengalaman", "experience", "riwayat kerja", "work history"]):
            score += 40
        
        found_verbs = sum(1 for verb in self.action_verbs if verb in text)
        score += min(found_verbs * 8, 40)
        return min(score, 100)

    def _calc_achievement_score(self, text: str) -> int:
        """Menilai penggunaan metode STAR dan metrik capaian (angka, rasio, persentase)."""
        score = 10
        numbers = re.findall(r'\b\d+([.,]\d+)?%?\b', text)
        percentages = re.findall(r'\b\d+%\b', text)

        score += min(len(numbers) * 10, 50)
        score += min(len(percentages) * 20, 40)
        return min(score, 100)

    def _calc_keyword_score(self, text: str, target_position: Optional[str], user_skills: List[str]) -> int:
        """Menilai keselarasan kata kunci terhadap target pekerjaan."""
        score = 35
        if target_position:
            keywords = [k.strip().lower() for k in target_position.split() if len(k) > 2]
            if keywords:
                matched_kw = sum(1 for kw in keywords if kw in text)
                score += int((matched_kw / len(keywords)) * 35)

        if user_skills:
            matched_skills = sum(1 for skill in user_skills if skill.lower() in text)
            score += min(matched_skills * 10, 30)

        return min(score, 100)

    def _calc_structure_score(self, text: str) -> int:
        """Menilai kelengkapan seksi utama (Summary, Experience, Education, Skills)."""
        score = 0
        if any(w in text for w in ["pengalaman", "experience", "riwayat kerja"]):
            score += 30
        if any(w in text for w in ["pendidikan", "education", "edukasi"]):
            score += 25
        if any(w in text for w in ["keahlian", "skill", "skills", "kemampuan"]):
            score += 25
        
        word_count = len(text.split())
        if word_count >= 120:
            score += 20
        elif word_count >= 60:
            score += 10

        return min(score, 100)

    def _extract_findings(
        self,
        text: str,
        ats: int,
        exp: int,
        ach: int,
        kw: int,
        struct: int
    ) -> List[str]:
        """Menyusun 3-5 poin temuan masalah nyata tanpa memberikan solusi langsung (Free Tier)."""
        problems = []

        if ats < 70:
            problems.append("Informasi kontak profesional (email resmi / nomor WhatsApp) belum terdeteksi secara optimal oleh parser.")
        if ach < 50:
            problems.append("Poin pengalaman kerja masih berupa deskripsi tugas umum, belum dilengkapi bukti pencapaian berbasis metrik/angka.")
        if exp < 60:
            problems.append("Penggunaan kata kerja aksi (action verbs) masih minim sehingga pengalaman terkesan pasif.")
        if kw < 60:
            problems.append("Kata kunci industri yang relevan dengan target posisi yang dituju masih kurang tersebar di isi CV.")
        if struct < 70:
            problems.append("Hierarki bagian CV belum lengkap (salah satu seksi wajib seperti Ringkasan, Pengalaman, Pendidikan, atau Skills belum terbaca jelas).")

        # Fallback jika CV sudah cukup bagus
        if len(problems) < 3:
            problems.append("Format penulisan rentang tanggal pengalaman kerja masih bisa distandarisasi agar kronologi lebih terbaca ATS.")
            problems.append("Pengelompokan hard skills dan soft skills masih bisa dioptimalkan agar relevan dengan job description.")

        return problems[:5]

    def build_llm_prompt(self, det_data: Dict[str, Any], cv_text: str, target_position: str, is_paid: bool = False) -> str:
        """Sistem Prompt Anti-Halusinasi untuk LLM Career Analyst."""
        tier = "PREMIUM_DEEP_REVIEW" if is_paid else "FREE_DIAGNOSIS"
        
        return f"""
Kamu adalah Senior Career & ATS Analyst di BoonTrack.
Tugasmu: Melakukan review dan diagnosa CV secara profesional, lugas, dan terstruktur.

TARGET POSISI: {target_position or 'General Professional'}
TIER AKSES: {tier}

DATA SKOR DETERMINISTIK (WAJIB DIGUNAKAN, DILARANG MENGUBAH ANGKA SKOR):
{json.dumps(det_data, indent=2)}

TEKS CV USER:
{cv_text[:3000]}

ATURAN EVALUASI & ANTI-HALUSINASI:
1. DILARANG membuat skor angka baru. Gunakan persis angka dari backend.
2. findings: Sebutkan 3-5 masalah nyata ("Apa yang kurang"), tanpa memberikan solusi langkah demi langkah secara lengkap jika tier bukan PREMIUM.
3. recommendations: Rincikan perbaikan konkret metode STAR & contoh kalimat perbaikan nyata (Khusus disediakan untuk akun Premium).
4. Kelompokkan rekomendasi berdasarkan prioritas: HIGH, MEDIUM, LOW.

OUTPUT WAJIB FORMAT JSON MURNI DENGAN SCHEMA BERIKUT:
{{
  "findings": [
    "Masalah 1: ...",
    "Masalah 2: ...",
    "Masalah 3: ..."
  ],
  "recommendations": [
    {{
      "priority": "HIGH",
      "category": "Experience",
      "issue": "Penjelasan masalah",
      "solution": "Cara memperbaiki tuntas",
      "before_after_example": "Contoh kalimat lama vs kalimat baru profesional"
    }}
  ]
}}
"""

    def apply_access_control(self, full_result: Dict[str, Any], is_paid: bool) -> Dict[str, Any]:
        """
        Security P0: Memfilter payload hasil review di level backend.
        - Free: overall_score, breakdown_scores, 3-5 findings, locked_preview.
        - Premium: findings + full recommendations + actionable steps.
        """
        base_response = {
            "status": "success",
            "is_premium": is_paid,
            "overall_score": full_result.get("overall_score", 0),
            "breakdown_scores": full_result.get("breakdown_scores", {
                "ats_compatibility": 0,
                "experience": 0,
                "achievement": 0,
                "keyword": 0,
                "structure": 0
            }),
            "findings": full_result.get("findings", [])[:5],
            "confidence": full_result.get("confidence", {
                "level": "MEDIUM",
                "reason": "Evaluasi otomatis berbasis standar ATS."
            })
        }

        if is_paid:
            base_response["recommendations"] = full_result.get("recommendations", [])
            base_response["actionable_examples"] = full_result.get("actionable_examples", [])
        else:
            # Sembunyikan rekomendasi dari payload response API Free User
            total_locked = len(full_result.get("recommendations", []))
            base_response["locked_preview"] = {
                "total_recommendations_locked": total_locked if total_locked > 0 else 3,
                "cta_text": "🚀 PERBAIKI CV SAYA",
                "cta_link": "/career#pricing"
            }

        return base_response

# Singleton instance
cv_review_engine = CVReviewEngine()
