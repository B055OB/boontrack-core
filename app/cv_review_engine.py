import json
import logging
import re

class CVReviewEngine:
    def __init__(self):
        # Inisialisasi konfigurasi atau koneksi jika diperlukan
        pass

    def calculate_deterministic_metrics(self, raw_data: dict) -> dict:
        """
        Memastikan perhitungan metrik angka (Quality, Match, Evidence) 
        dikalkulasi secara nyata berdasarkan kelengkapan data user.
        """
        # 1. Ambil data teks dari berbagai kemungkinan key (fallback kompatibel)
        nama = str(raw_data.get("nama_panggilan") or raw_data.get("1") or "").strip()
        email = str(raw_data.get("2") or raw_data.get("email") or "").strip()
        pengalaman = str(raw_data.get("pengalaman_web") or raw_data.get("3") or raw_data.get("pengalaman") or "").strip()
        pendidikan = str(raw_data.get("5") or raw_data.get("pendidikan") or "").strip()
        skill = str(raw_data.get("keahlian_web") or raw_data.get("6") or raw_data.get("skill") or "").strip()
        ringkasan = str(raw_data.get("ringkasan_web") or raw_data.get("4") or "").strip()

        # 2. Base Score jika AI melempar angka (opsional), jika tidak ada mulai dari 0
        quality_score = raw_data.get("quality_score", 40)
        match_score = raw_data.get("match_score", 40)
        evidence_score = raw_data.get("evidence_score", 30)

        # 3. Hitung kelengkapan riwayat (Kalkulasi Otomatis)
        if len(pengalaman) > 50:
            quality_score += 30
            evidence_score += 35
        elif len(pengalaman) > 15:
            quality_score += 15
            evidence_score += 15

        if len(skill) > 20:
            match_score += 35
        elif len(skill) > 5:
            match_score += 15

        if len(pendidikan) > 5:
            quality_score += 15

        if len(ringkasan) > 20:
            quality_score += 15
            match_score += 15

        # 4. HARD PENALTY RULES (Pangkas skor jika data kritis bolong)
        
        # PENGALAMAN KOSONG / MINIM -> Max Evidence 20, Quality 35
        if not pengalaman or len(pengalaman) < 15:
            evidence_score = min(evidence_score, 20)
            quality_score = min(quality_score, 35)

        # SKILL KOSONG / MINIM -> Max Match 25
        if not skill or len(skill) < 5:
            match_score = min(match_score, 25)

        # PENDIDIKAN KOSONG -> Potong Quality
        if not pendidikan:
            quality_score = min(quality_score, 50)

        # Cek angka/metrik konkret dalam pengalaman (e.g. 50%, Rp 10jt, 5 orang)
        has_metrics = bool(re.search(r'\d+', pengalaman))
        if not has_metrics and pengalaman:
            evidence_score = min(evidence_score, 45)

        # 5. Cap Skor Maksimal 100 dan Minimal 10
        quality_score = max(10, min(100, quality_score))
        match_score = max(10, min(100, match_score))
        evidence_score = max(10, min(100, evidence_score))

        return {
            "cv_quality": quality_score,
            "job_match": match_score,
            "evidence_strength": evidence_score
        }

    def detect_weaknesses_and_recommend(self, metrics: dict, raw_data: dict = None) -> list:
        """
        Kunci The Holy Trinity Metrics & Weakness Detector:
        Memberikan rekomendasi bertingkat (Impact Tinggi, Sedang, Rendah).
        """
        recommendations = []
        raw_data = raw_data or {}
        pengalaman = str(raw_data.get("pengalaman_web") or raw_data.get("3") or "").strip()
        skill = str(raw_data.get("keahlian_web") or raw_data.get("6") or "").strip()

        # Rekomendasi berdasarkan Hard Penalty
        if not pengalaman or len(pengalaman) < 15:
            recommendations.append({
                "impact": "Tinggi",
                "area": "Pengalaman Kerja",
                "message": "[Kritis] Isi deskripsi pengalaman kerja kamu. Tanpa riwayat kerja, rekruter kesulitan menilai kualifikasimu."
            })
        elif metrics["cv_quality"] < 80:
            recommendations.append({
                "impact": "Tinggi",
                "area": "CV Quality",
                "message": "Tambahkan lebih banyak hasil terukur dan metrik angka (persentase, jumlah, nominal) pada deskripsi pengalaman kerja."
            })

        if not skill or len(skill) < 5:
            recommendations.append({
                "impact": "Tinggi",
                "area": "Keahlian / Skill",
                "message": "[Kritis] Cantumkan keahlian utama yang relevan dengan posisi target agar lolos screening awal."
            })
        elif metrics["job_match"] < 75:
            recommendations.append({
                "impact": "Sedang",
                "area": "Job Match",
                "message": "Sesuaikan kata kunci (keywords) pada ringkasan profesional dengan deskripsi pekerjaan target."
            })

        if metrics["evidence_strength"] < 70:
            recommendations.append({
                "impact": "Rendah",
                "area": "Evidence Strength",
                "message": "Perkuat portofolio, sertifikat, atau tautan pendukung pencapaian kerja."
            })

        return recommendations

    def process_review(self, raw_data: dict) -> dict:
        """
        Fungsi utama yang memproses seluruh pilar penilaian.
        """
        metrics = self.calculate_deterministic_metrics(raw_data)
        weaknesses = self.detect_weaknesses_and_recommend(metrics, raw_data)
        
        return {
            "metrics": metrics,
            "recommendations": weaknesses,
            "status": "success"
        }