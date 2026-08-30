"""app/utils/phone_sanitizer.py
WhatsApp Phone Number Sanitizer for Meta Cloud API standard format (628xxx).
"""

import re
from typing import Optional

def sanitize_phone_number(raw_phone: Optional[str]) -> str:
    """Menstandarkan format nomor telepon ke format internasional Meta WhatsApp API.
    
    Contoh konversi:
    - '081234567890'    -> '6281234567890'
    - '+62 812-3456-7890' -> '6281234567890'
    - '81234567890'     -> '6281234567890'
    """
    if not raw_phone:
        return ""

    # 1. Hapus semua karakter selain angka
    digits_only = re.sub(r"\D", "", str(raw_phone).strip())

    # 2. Normalisasi prefix
    if digits_only.startswith("0"):
        digits_only = "62" + digits_only[1:]
    elif digits_only.startswith("8"):
        digits_only = "62" + digits_only
    elif digits_only.startswith("620"):
        digits_only = "62" + digits_only[3:]

    return digits_only