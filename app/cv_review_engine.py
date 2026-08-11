import json
import logging

class CVReviewEngine:
    def __init__(self):
        # Inisialisasi konfigurasi atau koneksi jika diperlukan
        pass

    def calculate_deterministic_metrics(self, raw_data: dict) -> dict:
        """
        Memastikan perhitungan metrik angka (Quality, Match, Evidence) 
        dikalkulasi langsung secara lokal, aman meskipun API AI mengalami gangguan.
        """
        # Contoh logika deterministik dasar untuk skor
        quality_score = raw_data.get("quality_score", 75)
        match_score = raw_data.get("match_score", 70)
        evidence_score = raw_data.get("evidence_score", 65)

        return {
            "cv_quality": quality_score,
            "job_match": match_score,
            "evidence_strength": evidence_score
        }

    def detect_weaknesses_and_recommend(self, metrics: dict) -> list:
        """
        Kunci The Holy Trinity Metrics & Weakness Detector:
        Memberikan rekomendasi bertingkat (Impact Tinggi, Sedang, Rendah).
        """
        recommendations = []
        
        if metrics["cv_quality"] < 80:
            recommendations.append({
                "impact": "Tinggi",
                "area": "CV Quality",
                "message": "Tambahkan lebih banyak hasil terukur dan metrik angka pada deskripsi pengalaman kerja."
            })
            
        if metrics["job_match"] < 75:
            recommendations.append({
                "impact": "Sedang",
                "area": "Job Match",
                "message": "Sesuaikan kata kunci (keywords) pada ringkasan profesional dengan deskripsi pekerjaan target."
            })
            
        if metrics["evidence_strength"] < 70:
            recommendations.append({
                "impact": "Rendah",
                "area": "Evidence Strength",
                "message": "Perkuat portofolio atau tautan pendukung pencapaian."
            })

        return recommendations

    def process_review(self, raw_data: dict) -> dict:
        """
        Fungsi utama yang memproses seluruh pilar penilaian.
        """
        metrics = self.calculate_deterministic_metrics(raw_data)
        weaknesses = self.detect_weaknesses_and_recommend(metrics)
        
        return {
            "metrics": metrics,
            "recommendations": weaknesses,
            "status": "success"
        }