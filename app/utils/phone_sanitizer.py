"""app/utils/phone_sanitizer.py
WhatsApp Phone Number Sanitizer for Meta Cloud API & Canonical E.164 standard format (628xxx).
"""

import re
from typing import Optional


def clean_phone_number(raw_phone: Optional[str]) -> str:
    """Menstandarkan format nomor telepon ke format internasional kanonis E.164 (standar 628xxx Indonesia).
    
    Menghapus karakter non-digit, spasi, simbol (+, -), dan memastikan awalan 628xxx standar Indonesia.
    
    Contoh konversi:
    - '081234567890'      -> '6281234567890'
    - '+62 812-3456-7890' -> '6281234567890'
    - '+6281234567890'    -> '6281234567890'
    - '81234567890'       -> '6281234567890'
    - '0081234567890'     -> '6281234567890'
    - '62081234567890'    -> '6281234567890'
    - '+1 203-634-3087'   -> '12036343087'
    - None / ''           -> ''
    """
    if not raw_phone:
        return ""

    # 1. Hapus semua karakter non-digit (termasuk spasi, +, -, titik, kurung)
    digits_only = re.sub(r"\D", "", str(raw_phone).strip())
    if not digits_only:
        return ""

    # 2. Normalisasi prefix standar Indonesia (628xxx)
    if digits_only.startswith("08"):
        digits_only = "62" + digits_only[1:]
    elif digits_only.startswith("008"):
        digits_only = "62" + digits_only[2:]
    elif digits_only.startswith("6208"):
        digits_only = "62" + digits_only[3:]
    elif digits_only.startswith("620"):
        digits_only = "62" + digits_only[3:]
    elif digits_only.startswith("8") and 9 <= len(digits_only) <= 14:
        digits_only = "62" + digits_only
    elif digits_only.startswith("0") and len(digits_only) >= 9:
        digits_only = "62" + digits_only[1:]

    return digits_only


# Backward-compatibility alias
sanitize_phone_number = clean_phone_number