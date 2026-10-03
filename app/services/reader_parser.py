import re
from typing import Optional, Dict, Any

# Regex khusus push notifikasi DANA Bisnis riil (§DANA-PARSER-V2):
# Title: "Pembayaran Masuk" | Body: "Rp99.304 diterima DANA Bisnis."
_DANA_BISNIS_SPECIFIC = re.compile(
    r"Rp\s*([\d][\d\.\,]*)\s+diterima\s+DANA\s+Bisnis",
    re.IGNORECASE
)

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
        # 2a. Regex spesifik format push notifikasi DANA Bisnis:
        #     Title: "Pembayaran Masuk"  |  Body: "Rp99.304 diterima DANA Bisnis."
        title_lower = (app_source or "")  # app_source berisi title pada beberapa implementasi
        is_payment_in_title = "pembayaran masuk" in clean_text.lower() or "masuk" in clean_text.lower()
        match_specific = _DANA_BISNIS_SPECIFIC.search(clean_text)
        if match_specific:
            parsed["amount"] = _clean_amount(match_specific.group(1))
            parsed["is_payment_in"] = True
        # 2b. Fallback: rule generik untuk varian teks lain
        elif any(w in clean_text.lower() for w in ("diterima", "masuk", "kirim", "berhasil")):
            match_amt = re.search(r"(?:Rp\s?|IDR\s?)([0-9.,]+)", clean_text, re.IGNORECASE)
            if match_amt:
                parsed["amount"] = _clean_amount(match_amt.group(1))
                # Hanya tandai payment_in jika bukan notifikasi outbound (kirim/mengirim)
                outbound_words = ("kirim", "mengirim", "transfer ke", "dikirim ke")
                parsed["is_payment_in"] = not any(w in clean_text.lower() for w in outbound_words)

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