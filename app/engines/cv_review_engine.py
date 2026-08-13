import re
import json
from typing import Dict, Any, List, Optional

class CVReviewEngine:
    """
    Deterministic CV Review Engine.
    Menghitung skor CV matematis tanpa bergantung pada LLM.
    """

    def __init__(self):
        # Action Verbs untuk pengukuran Evidence Strength
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
        Evaluasi teks CV dan hasilkan 3 skor deterministik.
        """
        clean_text = cv_text.lower()
        user_skills = user_skills or []

        # 1. Hitung CV Quality Score (Max: 100)
        cv_quality = self._calc_cv_quality(clean_text)

        # 2. Hitung Evidence Strength Score (Max: 100)
        evidence_strength = self._calc_evidence_strength(clean_text)

        # 3. Hitung Job Match Score (Max: 100)
        job_match = self._calc_job_match(clean_text, target_position, user_skills)

        # Hitung Overall Score (Bobot Rata-rata)
        overall_score = int((cv_quality * 0.35) + (job_match * 0.35) + (evidence_strength * 0.30))

        # Tentukan Confidence Level
        word_count = len(clean_text.split())
        if word_count < 50 or cv_quality < 35:
            confidence_level = "LOW"
            confidence_reason = "Informasi CV masih minim sehingga hasil analisis belum maksimal."
        elif cv_quality < 70:
            confidence_level = "MEDIUM"
            confidence_reason = "Informasi CV lumayan lengkap, namun rincian angka & achievement masih bisa ditingkatkan."
        else:
            confidence_level = "HIGH"
            confidence_reason = "Data CV sangat lengkap untuk dianalisis komprehensif."

        return {
            "overall_score": overall_score,
            "scores": {
                "cv_quality": cv_quality,
                "job_match": job_match,
                "evidence_strength": evidence_strength
            },
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

    def _calc_cv_quality(self, text: str) -> int:
        score = 0
        
        # Kelengkapan Kontak (Max 25 pt)
        if re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text):
            score += 15
        if re.search(r'(\+62|62|08)[0-9]{8,12}', text):
            score += 10

        # Struktur Bagian Utama (Max 45 pt)
        if any(w in text for w in ["pengalaman", "experience", "riwayat kerja"]):
            score += 20
        if any(w in text for w in ["pendidikan", "education", "edukasi"]):
            score += 15
        if any(w in text for w in ["keahlian", "skill", "skills", "kemampuan"]):
            score += 10

        # Keterbacaan & Panjang Teks (Max 30 pt)
        word_count = len(text.split())
        if word_count >= 150:
            score += 30
        elif word_count >= 80:
            score += 15
        else:
            score += 5

        return min(score, 100)

    def _calc_evidence_strength(self, text: str) -> int:
        score = 20  # Base score
        
        # Deteksi Angka & Persentase (Metrics Presence)
        numbers = re.findall(r'\b\d+([.,]\d+)?%?\b', text)
        percentage = re.findall(r'\b\d+%\b', text)
        
        score += min(len(numbers) * 8, 40)      # Max 40 pt dari jumlah angka/metrik
        score += min(len(percentage) * 10, 20)  # Max 20 pt jika ada bukti persentase
        
        # Deteksi Action Verbs
        found_verbs = sum(1 for verb in self.action_verbs if verb in text)
        score += min(found_verbs * 5, 20)       # Max 20 pt dari kata kerja aksi

        return min(score, 100)

    def _calc_job_match(
        self,
        text: str,
        target_position: Optional[str],
        user_skills: List[str]
    ) -> int:
        score = 40  # Base score jika belum ada target khusus
        
        # Jika ada Target Posisi, cek kemunculan kata kuncinya di CV
        if target_position:
            score = 30
            keywords = [k.strip().lower() for k in target_position.split() if len(k) > 2]
            matched_kw = sum(1 for kw in keywords if kw in text)
            if keywords:
                score += int((matched_kw / len(keywords)) * 40)

        # Cek kesesuaian skill
        if user_skills:
            matched_skills = sum(1 for skill in user_skills if skill.lower() in text)
            score += min(matched_skills * 10, 30)

        return min(score, 100)

    def build_llm_prompt(self, det_data: Dict[str, Any], cv_text: str, target_position: str, is_paid: bool = False) -> str:
        """Sistem Prompt Anti-Halusinasi untuk LLM Career Analyst"""
        tier = "DEEP_REVIEW" if is_paid else "BASIC_REVIEW"
        
        return f"""
Kamu adalah Senior Career Analyst di BoonTrack.
Tugasmu: Jelaskan hasil analisis deterministik backend berikut secara profesional, jujur, dan berdaya guna tinggi.

TARGET POSISI: {target_position}
TIER ANALYSIS: {tier}

SKOR DETERMINISTIK DARI BACKEND (JANGAN DIUBAH ANGKANYA):
{json.dumps(det_data, indent=2)}

TEKS CV USER:
{cv_text[:2000]}

ATURAN ANTI-HALUSINASI (WAJIB):
1. DILARANG MENGUBAH ATAU MEMBUAT ANGKA SKOR BARU. Gunakan skor dari backend!
2. DILARANG menyuruh user menambahkan skill yang TIDAK ADA di CV seolah-olah mereka sudah memilikinya. Jika ada skill gap, kategorikan sebagai "Hal yang perlu dipelajari/dikuasai terlebih dahulu".
3. DILARANG mengarang angka pencapaian.
4. Action Plan WAJIB dikelompokkan berdasarkan prioritas: HIGH (merah/paling krusial), MEDIUM (kuning), LOW (hijau).

OUTPUT WAJIB FORMAT JSON MURNI DENGAN SCHEMA INI:
{{
  "strengths": ["poin 1", "poin 2"],
  "weaknesses": ["poin 1", "poin 2"],
  "keyword_gaps": ["gap 1"],
  "skill_gaps": ["skill gap 1"],
  "evidence_gaps": ["evidence gap 1"],
  "action_plan": [
    {{
      "priority": "HIGH",
      "section": "Experience",
      "problem": "Penjelasan masalah",
      "recommendation": "Saran perbaikan konkret"
    }}
  ]
}}
"""

    def apply_access_control(self, full_result: Dict[str, Any], is_paid: bool) -> Dict[str, Any]:
        """Membatasi output jika user masih status FREE (Basic Review)"""
        if is_paid:
            full_result['tier'] = 'DEEP'
            return full_result
        
        # Jika FREE / BASIC, batasi kedalaman insight
        return {
            "tier": "BASIC",
            "overall_score": full_result.get("overall_score"),
            "scores": full_result.get("scores"),
            "strengths": full_result.get("strengths", [])[:2],
            "weaknesses": full_result.get("weaknesses", [])[:2],
            "confidence": full_result.get("confidence"),
            "is_locked": True,
            "upgrade_cta": "🔒 <b>Buka Career Page untuk unlock Keyword Gap, Skill Gap, dan Detailed Action Plan!</b>"
        }

# Singleton instance
cv_review_engine = CVReviewEngine()