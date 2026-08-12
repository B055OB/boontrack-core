import re
from enum import Enum
from typing import Dict, Any, Optional

class IntentType(str, Enum):
    CASUAL = "CASUAL"
    CAREER_QUERY = "CAREER_QUERY"
    CV_REVIEW = "CV_REVIEW"
    CV_CREATION = "CV_CREATION"
    CAREER_PAGE = "CAREER_PAGE"
    PAYMENT = "PAYMENT"
    REFERRAL = "REFERRAL"
    ADMIN = "ADMIN"
    UNKNOWN = "UNKNOWN"

class IntentEngine:
    """
    Traffic Controller untuk mengklasifikasikan intent pesan user
    sebelum masuk ke layer pemrosesan/LLM.
    """
    def __init__(self):
        # Pattern matching berbasis regex untuk klasifikasi cepat (0-ms latency)
        self.patterns = {
            IntentType.ADMIN: [
                r"^/(admin|analytics|utm_fb|upload|set_user|fix_data)",
                r"^#admin"
            ],
            IntentType.PAYMENT: [
                r"\b(bayar|pembayaran|transfer|harga|biaya|invoice|receipt|bukti bayar|qris|sewa|membership|premium)\b"
            ],
            IntentType.REFERRAL: [
                r"\b(referral|kode ref|ref code|komisi|ajak teman|bonus poin|klaim poin)\b"
            ],
            IntentType.CV_CREATION: [
                r"\b(buat cv|bikin cv|generate cv|draf cv|susun cv|template cv|contoh cv)\b",
                r"^/buat_cv"
            ],
            IntentType.CV_REVIEW: [
                r"\b(review cv|cek cv|nilai cv|koreksi cv|skor cv|analisis cv|kurang bagus|bedah cv)\b",
                r"^/review_cv"
            ],
            IntentType.CAREER_PAGE: [
                r"\b(career page|portofolio|link karier|halaman karier|web karier|situs saya)\b"
            ],
            IntentType.CASUAL: [
                r"^(halo|hai|hi|p|ping|pagi|siang|malam|sore|tes|test|assalamu[']?alaikum|selamat|terima kasih|thanks|makasih|ok|okay|siap)$",
                r"^(siapa kamu|kamu siapa|bot apa ini)\b"
            ],
            IntentType.CAREER_QUERY: [
                r"\b(gaji|interview|wawancara|lamar|lowongan|loker|hrd|karir|karier|promosi|resign|probation|tipe pekerjaan|bidang kerja|pindah jurusan)\b",
                r"\b(kenapa saya belum|cocok gak|cocok tidak|peluang)\b"
            ]
        }

    async def detect_intent(self, user_message: str, is_owner: bool = False) -> Dict[str, Any]:
        """
        Deteksi intent utama dari pesan user.
        """
        clean_msg = user_message.strip().lower()

        # 1. Prioritas Khusus Admin
        if is_owner and any(re.search(p, clean_msg) for p in self.patterns[IntentType.ADMIN]):
            return {
                "intent": IntentType.ADMIN,
                "confidence": 1.0,
                "method": "rule_owner"
            }

        # 2. Fast Pattern Matching (Deterministic Keyword Check)
        for intent_type, pattern_list in self.patterns.items():
            if intent_type == IntentType.ADMIN:
                continue
            for pattern in pattern_list:
                if re.search(pattern, clean_msg):
                    return {
                        "intent": intent_type,
                        "confidence": 0.95,
                        "method": "pattern_match"
                    }

        # 3. Heuristic / Default Fallback
        # Jika panjang pesan sangat pendek dan tidak masuk kategori lain
        if len(clean_msg.split()) <= 2:
            return {
                "intent": IntentType.CASUAL,
                "confidence": 0.70,
                "method": "heuristic_short_msg"
            }

        # Default ke CAREER_QUERY untuk pesan panjang yang butuh konteks
        return {
            "intent": IntentType.CAREER_QUERY,
            "confidence": 0.60,
            "method": "fallback_default"
        }

# Singleton instance
intent_engine = IntentEngine()