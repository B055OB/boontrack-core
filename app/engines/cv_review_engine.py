import re
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

        # Ringkasan Fakta Backend (Python Facts)
        return {
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

# Singleton instance
cv_review_engine = CVReviewEngine()