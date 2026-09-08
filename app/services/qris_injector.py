def calc_crc16(payload: str) -> str:
    # CRC16-CCITT (0x1021), init 0xFFFF
    crc = 0xFFFF
    for char in payload:
        crc ^= (ord(char) << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"

def generate_dynamic_qris(static_qris: str, amount: int) -> str:
    """Inject Tag 54 tanpa mengubah Tag 01, lalu hitung ulang CRC16 Tag 63."""
    if not static_qris or not static_qris.startswith("000201"):
        return static_qris

    try:
        # 1. Potong string sebelum Tag 6304
        idx_63 = static_qris.rfind("6304")
        raw = static_qris[:idx_63] if idx_63 != -1 else static_qris

        # 2. Format Tag 54 (Transaction Amount)
        amt_str = str(int(amount))
        tag_54 = f"54{len(amt_str):02d}{amt_str}"

        # 3. Sisipkan Tag 54 tepat sebelum Tag 58 (Country Code)
        idx_58 = raw.find("5802")
        if idx_58 != -1:
            raw = raw[:idx_58] + tag_54 + raw[idx_58:]
        else:
            raw += tag_54

        # 4. Hitung ulang CRC16
        payload_for_crc = raw + "6304"
        return payload_for_crc + calc_crc16(payload_for_crc)
    except Exception:
        return static_qris