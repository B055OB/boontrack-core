import re

def parse_reader_notification(app_source: str, raw_text: str) -> dict:
    """Ekstraksi nominal dan transaction ref dari push notification HP."""
    parsed = {
        "amount": 0.0,
        "ref": None,
        "is_payment_in": False
    }

    clean_text = raw_text.replace("\n", " ").strip()

    # Pattern GoPay / GoBiz Merchant (Contoh: "Penerimaan Pembayaran Rp 150.000 dari ...")
    if "gobiz" in app_source.lower() or "gopay" in app_source.lower():
        match_amt = re.search(r"Rp\s?([0-9.,]+)", clean_text, re.IGNORECASE)
        if match_amt:
            amt_digits = re.sub(r"[^\d]", "", match_amt.group(1))
            parsed["amount"] = float(amt_digits)
            parsed["is_payment_in"] = True

    # Pattern Bank BCA / Mandiri / SMS banking
    elif "bca" in app_source.lower() or "bank" in app_source.lower():
        if "cr" in clean_text.lower() or "masuk" in clean_text.lower() or "diterima" in clean_text.lower():
            match_amt = re.search(r"(?:Rp\s?|IDR\s?)([0-9.,]+)", clean_text, re.IGNORECASE)
            if match_amt:
                amt_digits = re.sub(r"[^\d]", "", match_amt.group(1))
                parsed["amount"] = float(amt_digits)
                parsed["is_payment_in"] = True

    # Ambil referensi unik transaksi atau nomor referensi jika ada
    match_ref = re.search(r"(?:ref|trx|id)[:\s]*([a-zA-Z0-9]+)", clean_text, re.IGNORECASE)
    if match_ref:
        parsed["ref"] = match_ref.group(1)

    return parsed