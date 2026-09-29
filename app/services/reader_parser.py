import re
from typing import Optional, Dict, Any

# 5 Akun Penerima Otomatis Merchant Resmi (§14.1 & §15.2):
# 1. BCA Mobile / myBCA
# 2. DANA Bisnis
# 3. GoPay / GoBiz
# 4. Shopee Partner / ShopeeFood
# 5. GrabMerchant / GrabFood

def _clean_amount(text_match: str) -> float:
    """Bersihkan nominal Rupiah, abaikan sen ,00 atau .00 jika ada."""
    raw = text_match.strip()
    if raw.endswith(",00") or raw.endswith(".00"):
        raw = raw[:-3]
    digits = re.sub(r"\D", "", raw)
    return float(digits) if digits else 0.0

def parse_reader_notification(app_source: str, raw_text: str) -> dict:
    """Ekstraksi nominal dan transaction ref dari push notification HP untuk 5 akun resmi Reader."""
    parsed = {
        "amount": 0.0,
        "ref": None,
        "is_payment_in": False,
        "supported": False
    }

    src = (app_source or "").lower()
    clean_text = raw_text.replace("\n", " ").strip()

    # Zero Fake Fallbacks: Bank Mandiri, BRI, BNI, BSI belum memiliki parser notifikasi Android
    if any(unsupported in src for unsupported in ("mandiri", "bri", "bni", "bsi")):
        return parsed

    # 1. BCA Mobile / myBCA
    if "bca" in src or "mybca" in src:
        parsed["supported"] = True
        if any(w in clean_text.lower() for w in ("cr", "masuk", "diterima", "berhasil", "transfer")):
            match_amt = re.search(r"(?:Rp\s?|IDR\s?)([0-9.,]+)", clean_text, re.IGNORECASE)
            if match_amt:
                parsed["amount"] = _clean_amount(match_amt.group(1))
                parsed["is_payment_in"] = True

    # 2. DANA Bisnis
    elif "dana" in src:
        parsed["supported"] = True
        if any(w in clean_text.lower() for w in ("diterima", "masuk", "kirim", "berhasil")):
            match_amt = re.search(r"(?:Rp\s?|IDR\s?)([0-9.,]+)", clean_text, re.IGNORECASE)
            if match_amt:
                parsed["amount"] = _clean_amount(match_amt.group(1))
                parsed["is_payment_in"] = True

    # 3. GoPay / GoBiz Merchant
    elif "gobiz" in src or "gopay" in src:
        parsed["supported"] = True
        if any(w in clean_text.lower() for w in ("pembayaran", "diterima", "masuk", "transaksi")):
            match_amt = re.search(r"(?:Rp\s?|IDR\s?)([0-9.,]+)", clean_text, re.IGNORECASE)
            if match_amt:
                parsed["amount"] = _clean_amount(match_amt.group(1))
                parsed["is_payment_in"] = True

    # 4. Shopee Partner / ShopeeFood
    elif "shopee" in src:
        parsed["supported"] = True
        if any(w in clean_text.lower() for w in ("pesanan", "pembayaran", "diterima", "masuk", "dana")):
            match_amt = re.search(r"(?:Rp\s?|IDR\s?)([0-9.,]+)", clean_text, re.IGNORECASE)
            if match_amt:
                parsed["amount"] = _clean_amount(match_amt.group(1))
                parsed["is_payment_in"] = True

    # 5. GrabMerchant / GrabFood
    elif "grab" in src:
        parsed["supported"] = True
        if any(w in clean_text.lower() for w in ("pesanan", "pembayaran", "diterima", "masuk", "telah")):
            match_amt = re.search(r"(?:Rp\s?|IDR\s?)([0-9.,]+)", clean_text, re.IGNORECASE)
            if match_amt:
                parsed["amount"] = _clean_amount(match_amt.group(1))
                parsed["is_payment_in"] = True

    # Ambil referensi unik transaksi atau nomor referensi jika ada
    match_ref = re.search(r"(?:ref|trx|id|no\.\s?transaksi)[:\s]*([a-zA-Z0-9]+)", clean_text, re.IGNORECASE)
    if match_ref:
        parsed["ref"] = match_ref.group(1)

    return parsed