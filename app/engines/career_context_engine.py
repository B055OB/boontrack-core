from typing import Dict, Any, Optional, List

class CareerContextEngine:
    """
    Membentuk context terstruktur dari data pengguna dan hasil skor deterministik
    sebelum dikirim ke LLM sebagai bahan penjelasan (Explainer).
    """

    def build_context(
        self,
        user_profile: Dict[str, Any],
        cv_scores: Optional[Dict[str, Any]] = None,
        intent: str = "CAREER_QUERY"
    ) -> Dict[str, Any]:
        """
        Susun payload konteks karier yang padat dan informatif.
        """
        scores = cv_scores.get("scores", {}) if cv_scores else {}
        metrics = cv_scores.get("metrics_detected", {}) if cv_scores else {}

        # Analisis Cepat Strengths & Gaps berdasarkan skor Python
        top_strengths = []
        top_gaps = []

        cv_quality = scores.get("cv_quality", 0)
        evidence_strength = scores.get("evidence_strength", 0)
        job_match = scores.get("job_match", 0)

        if evidence_strength >= 70:
            top_strengths.append("Bukti pencapaian dan angka (metrics) sangat kuat.")
        elif evidence_strength < 50:
            top_gaps.append("Kurang bukti kuantitatif/angka hasil kerja (Action & Metrics).")

        if cv_quality >= 75:
            top_strengths.append("Kelengkapan struktur CV dan kontak sudah baik.")
        elif cv_quality < 60:
            top_gaps.append("Struktur CV atau kelengkapan bagian utama belum ideal.")

        if job_match < 60:
            top_gaps.append("Kata kunci CV kurang cocok dengan target posisi.")

        return {
            "intent": intent,
            "target_position": user_profile.get("target_position", "Belum Ditentukan"),
            "experience_years": user_profile.get("experience_years", 0),
            "skills": user_profile.get("skills", []),
            "cv_scores": {
                "cv_quality": cv_quality,
                "job_match": job_match,
                "evidence_strength": evidence_strength
            },
            "metrics_detected": metrics,
            "top_strengths": top_strengths,
            "top_gaps": top_gaps
        }

# Singleton instance
career_context_engine = CareerContextEngine()