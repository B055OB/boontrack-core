import math
import re
import hashlib
import logging
from typing import Dict, Any, Optional, Tuple, Set

logger = logging.getLogger(__name__)

# Compliance & Official Naming
OFFICIAL_PRODUCT_NAME = "BoonTrack Document Polish & Rephrase"
COMPLIANCE_DISCLAIMER = (
    "Alat ini membantu keterbacaan dan struktur naskah — penggunaannya tetap "
    "mengikuti kebijakan integritas profesional dan akademik institusi Anda."
)

# Supported Task Types (Standardized)
TASK_POLISH_REPHRASE = "POLISH_REPHRASE"
TASK_CV_POLISH_REWRITE = "CV_POLISH_REWRITE"
TASK_CAREER_PRO_BUNDLE = "CAREER_PRO_BUNDLE"
TASK_ATS_DIAGNOSTIC = "ATS_DIAGNOSTIC"

# Legacy mapping compatibility
LEGACY_TASK_MAPPING = {
    "ATS_REVIEW": TASK_ATS_DIAGNOSTIC,
    "CV_REWRITE": TASK_CV_POLISH_REWRITE,
    "PARAPHRASE": TASK_POLISH_REPHRASE
}

# Pricing Constants (IDR - Approved by CFO & CEO)
PRICE_POLISH_TIER_1 = 5000    # < 500 kata
PRICE_POLISH_TIER_2 = 10000   # 500 - 2.500 kata
PRICE_POLISH_TIER_3 = 20000   # 2.500 - 6.000 kata
PRICE_POLISH_TIER_4 = 40000   # > 6.000 kata
PRICE_POLISH_ADDON_RATE = 5000 # +Rp5.000 per 2.000 kata tambahan di atas 12.000 kata

PRICE_CV_POLISH_REWRITE = 10000  # Standar HR Senior ATS Rewrite
PRICE_CAREER_PRO_BUNDLE = 25000 # CV Rewrite + 3 Ronde Simulasi Interview HR STAR

WORDS_PER_PAGE_STANDARD = 250

# In-Memory Cache Anti-Abuse Trial Tracking
_USED_FREE_TRIAL_HASHES: Set[str] = set()
_USED_FREE_TRIAL_USERS: Set[str] = set()


def compute_content_hash(text: str) -> str:
    """Menghitung SHA-256 hash dari teks yang dinormalisasi untuk deteksi anti-abuse."""
    if not text:
        return hashlib.sha256(b"").hexdigest()
    # Normalisasi spasi, huruf kecil, dan hapus tanda baca berlebih
    clean_text = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(clean_text.encode("utf-8")).hexdigest()


def calculate_jaccard_similarity(text_a: str, text_b: str) -> float:
    """Menghitung kemiripan kata (Jaccard similarity) antara dua teks."""
    words_a = set(re.findall(r"\b\w+\b", text_a.lower()))
    words_b = set(re.findall(r"\b\w+\b", text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = words_a.intersection(words_b)
    union = words_a.union(words_b)
    return len(intersection) / len(union) if union else 0.0


def check_anti_abuse_free_trial(
    doc_hash: str,
    text: str = "",
    user_id: str = "",
    sample_texts_cache: Optional[Dict[str, str]] = None
) -> Tuple[bool, str]:
    """Anti-abuse rule: Cek apakah user atau naskah sudah pernah memakai Free Trial.
    Jika hash sudah pernah terdaftar atau kemiripan teks >= 80%, tolak free trial berikutnya.
    
    Returns:
        (is_allowed, reason)
    """
    clean_uid = str(user_id or "").strip()
    
    # 1. Cek User ID
    if clean_uid and clean_uid in _USED_FREE_TRIAL_USERS:
        return False, "FREE_TRIAL_USER_LIMIT_EXCEEDED"

    # 2. Cek Exact Hash
    if doc_hash and doc_hash in _USED_FREE_TRIAL_HASHES:
        return False, "FREE_TRIAL_HASH_DUPLICATED"

    # 3. Cek Kemiripan Fuzzy (≥ 80%) jika ada cache sampel
    if text and sample_texts_cache:
        for cached_hash, cached_text in sample_texts_cache.items():
            sim = calculate_jaccard_similarity(text, cached_text)
            if sim >= 0.80:
                return False, f"FREE_TRIAL_CONTENT_SIMILARITY_EXCEEDED ({int(sim*100)}%)"

    return True, "OK"


def register_free_trial_usage(doc_hash: str, user_id: str = ""):
    """Mencatat penggunaan free trial ke cache/state."""
    if doc_hash:
        _USED_FREE_TRIAL_HASHES.add(doc_hash)
    if user_id:
        _USED_FREE_TRIAL_USERS.add(str(user_id).strip())


def calculate_document_metrics(text: str) -> Dict[str, Any]:
    """Menghitung metrik dokumen: word count, character count, estimasi halaman, dan SHA-256 hash."""
    if not text or not isinstance(text, str):
        return {
            "word_count": 0,
            "char_count": 0,
            "char_count_no_spaces": 0,
            "estimated_pages": 0,
            "doc_hash": compute_content_hash("")
        }

    words = re.findall(r"\b[\w'-]+\b", text, re.UNICODE)
    word_count = len(words)
    char_count = len(text)
    char_count_no_spaces = len(re.sub(r"\s+", "", text))
    estimated_pages = max(1, math.ceil(word_count / WORDS_PER_PAGE_STANDARD)) if word_count > 0 else 0
    doc_hash = compute_content_hash(text)

    return {
        "word_count": word_count,
        "char_count": char_count,
        "char_count_no_spaces": char_count_no_spaces,
        "estimated_pages": estimated_pages,
        "doc_hash": doc_hash
    }


def calculate_pricing(task_type: str, word_count: int) -> Dict[str, Any]:
    """Kalkulasi tarif dinamis resmi yang disetujui CFO & CEO.
    
    1. POLISH_REPHRASE (Document Polish & Rephrase):
       - Tier 1 (< 500 kata): Rp5.000
       - Tier 2 (500 - 2.500 kata): Rp10.000
       - Tier 3 (2.500 - 6.000 kata): Rp20.000
       - Tier 4 (> 6.000 kata): Rp40.000 (+Rp5.000 per 2.000 kata jika > 12.000 kata)
    2. CV_POLISH_REWRITE: Flat Rp10.000
    3. CAREER_PRO_BUNDLE: Flat Rp25.000
    4. ATS_DIAGNOSTIC: Free Rp0
    """
    raw_task = str(task_type or TASK_POLISH_REPHRASE).upper().strip()
    normalized_task = LEGACY_TASK_MAPPING.get(raw_task, raw_task)
    w_count = max(0, int(word_count))

    if normalized_task == TASK_POLISH_REPHRASE:
        if w_count < 500:
            tier = "TIER_1"
            tier_label = "Tier 1 (< 500 kata)"
            base_price = PRICE_POLISH_TIER_1
            addon_price = 0
            final_price = PRICE_POLISH_TIER_1
        elif w_count <= 2500:
            tier = "TIER_2"
            tier_label = "Tier 2 (500 - 2.500 kata)"
            base_price = PRICE_POLISH_TIER_2
            addon_price = 0
            final_price = PRICE_POLISH_TIER_2
        elif w_count <= 6000:
            tier = "TIER_3"
            tier_label = "Tier 3 (2.500 - 6.000 kata)"
            base_price = PRICE_POLISH_TIER_3
            addon_price = 0
            final_price = PRICE_POLISH_TIER_3
        else: # > 6.000 kata
            tier = "TIER_4"
            tier_label = "Tier 4 (> 6.000 kata)"
            base_price = PRICE_POLISH_TIER_4
            if w_count > 12000:
                extra_words = w_count - 12000
                extra_chunks = math.ceil(extra_words / 2000)
                addon_price = extra_chunks * PRICE_POLISH_ADDON_RATE
            else:
                addon_price = 0
            final_price = base_price + addon_price

    elif normalized_task == TASK_CV_POLISH_REWRITE:
        tier = "SINGLE_CV"
        tier_label = "Single CV Polish & ATS Rewrite"
        base_price = PRICE_CV_POLISH_REWRITE
        addon_price = 0
        final_price = PRICE_CV_POLISH_REWRITE

    elif normalized_task == TASK_CAREER_PRO_BUNDLE:
        tier = "CAREER_PRO_BUNDLE"
        tier_label = "Career Pro Bundle (CV Rewrite + 3x Interview HR)"
        base_price = PRICE_CAREER_PRO_BUNDLE
        addon_price = 0
        final_price = PRICE_CAREER_PRO_BUNDLE

    elif normalized_task == TASK_ATS_DIAGNOSTIC:
        tier = "FREE_TIER"
        tier_label = "Free Basic ATS Diagnostic"
        base_price = 0
        addon_price = 0
        final_price = 0

    else:
        tier = "CUSTOM"
        tier_label = f"Layanan {normalized_task}"
        base_price = PRICE_POLISH_TIER_2
        addon_price = 0
        final_price = PRICE_POLISH_TIER_2

    return {
        "task_type": normalized_task,
        "word_count": w_count,
        "pricing_tier": tier,
        "tier_label": tier_label,
        "base_price": base_price,
        "addon_price": addon_price,
        "price_amount": final_price,
        "final_price": final_price,
        "currency": "IDR",
        "formatted_price": f"Rp{final_price:,}".replace(",", "."),
        "disclaimer": COMPLIANCE_DISCLAIMER,
        "product_name": OFFICIAL_PRODUCT_NAME
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
        "price_amount": pricing["final_price"],
        "currency": "IDR",
        "formatted_amount": pricing["formatted_price"],
        "invoice_title": f"{OFFICIAL_PRODUCT_NAME} - {pricing['tier_label']}",
        "disclaimer": COMPLIANCE_DISCLAIMER
    }
