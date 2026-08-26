import math
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Dynamic Pricing Matrix Constants (IDR)
TIER_1_MAX_WORDS = 1000
TIER_2_MAX_WORDS = 3000
TIER_3_MAX_WORDS = 5000

PRICE_TIER_1 = 15000   # ≤ 1.000 kata (Base price / flat rate)
PRICE_TIER_2 = 25000   # 1.001 - 3.000 kata (Medium rate)
PRICE_TIER_3 = 40000   # 3.001 - 5.000 kata (Large rate)
RATE_TIER_4_PER_1K = 7500 # > 5.000 kata (+Rp7.500 per 1.000 kata tambahan)

WORDS_PER_PAGE_STANDARD = 250


def calculate_document_metrics(text: str) -> Dict[str, Any]:
    """Menghitung metrik dokumen: word count, character count, dan estimasi halaman.
    
    Args:
        text: Konten string dokumen.
        
    Returns:
        Dict dengan 'word_count', 'char_count', 'char_count_no_spaces', 'estimated_pages'.
    """
    if not text or not isinstance(text, str):
        return {
            "word_count": 0,
            "char_count": 0,
            "char_count_no_spaces": 0,
            "estimated_pages": 0
        }

    # Ekstraksi kata dengan tokenisasi bersih
    words = re.findall(r"\b[\w'-]+\b", text, re.UNICODE)
    word_count = len(words)
    
    char_count = len(text)
    char_count_no_spaces = len(re.sub(r"\s+", "", text))
    
    estimated_pages = max(1, math.ceil(word_count / WORDS_PER_PAGE_STANDARD)) if word_count > 0 else 0

    return {
        "word_count": word_count,
        "char_count": char_count,
        "char_count_no_spaces": char_count_no_spaces,
        "estimated_pages": estimated_pages
    }


def calculate_pricing(task_type: str, word_count: int) -> Dict[str, Any]:
    """Menghitung tarif dinamis berdasarkan Dynamic Pricing Matrix per task_type dan word_count.
    
    Matrix:
    - Tier 1 (≤ 1.000 kata): Base price Rp15.000 (flat rate)
    - Tier 2 (1.001 - 3.000 kata): Medium rate Rp25.000
    - Tier 3 (3.001 - 5.000 kata): Large rate Rp40.000
    - Tier 4 (> 5.000 kata): Rp40.000 + Rp7.500 per 1.000 kata tambahan
    
    Args:
        task_type: Jenis tugas ('ATS_REVIEW', 'CV_REWRITE', 'PARAPHRASE').
        word_count: Jumlah kata dokumen.
        
    Returns:
        Dict rincian tarif dan tiering.
    """
    normalized_task = str(task_type or "CV_REWRITE").upper().strip()
    w_count = max(0, int(word_count))

    if w_count <= TIER_1_MAX_WORDS:
        tier = "TIER_1"
        tier_label = "Tier 1 (Ringkas ≤ 1.000 kata)"
        base_price = PRICE_TIER_1
        additional_price = 0
        final_price = PRICE_TIER_1
    elif w_count <= TIER_2_MAX_WORDS:
        tier = "TIER_2"
        tier_label = "Tier 2 (Menengah 1.001 - 3.000 kata)"
        base_price = PRICE_TIER_2
        additional_price = 0
        final_price = PRICE_TIER_2
    elif w_count <= TIER_3_MAX_WORDS:
        tier = "TIER_3"
        tier_label = "Tier 3 (Panjang 3.001 - 5.000 kata)"
        base_price = PRICE_TIER_3
        additional_price = 0
        final_price = PRICE_TIER_3
    else:
        tier = "TIER_4"
        tier_label = "Tier 4 (Ekstra > 5.000 kata)"
        base_price = PRICE_TIER_3
        extra_words = w_count - TIER_3_MAX_WORDS
        extra_thousands = math.ceil(extra_words / 1000)
        additional_price = extra_thousands * RATE_TIER_4_PER_1K
        final_price = base_price + additional_price

    return {
        "task_type": normalized_task,
        "word_count": w_count,
        "pricing_tier": tier,
        "tier_label": tier_label,
        "base_price": base_price,
        "additional_price": additional_price,
        "final_price": final_price,
        "currency": "IDR",
        "formatted_price": f"Rp{final_price:,}".replace(",", ".")
    }


def build_qris_invoice_payload(
    job_id: str,
    task_type: str,
    word_count: int,
    user_phone: str = "",
    tenant_id: str = "boontrack-career"
) -> Dict[str, Any]:
    """Membangun payload kalkulasi invoice QRIS sebelum ditagihkan ke user di WhatsApp."""
    pricing = calculate_pricing(task_type, word_count)
    return {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "user_phone": user_phone,
        "task_type": pricing["task_type"],
        "word_count": pricing["word_count"],
        "pricing_tier": pricing["pricing_tier"],
        "amount": pricing["final_price"],
        "currency": "IDR",
        "formatted_amount": pricing["formatted_price"],
        "invoice_title": f"Layanan {pricing['task_type']} ({pricing['tier_label']})"
    }
