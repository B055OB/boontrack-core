"""Ad-hoc experimental QRIS helper functions."""


def crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for char in data:
        crc ^= (ord(char) << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def make_dynamic_qris_string(static_str: str, amount: int) -> str:
    # 1. Bersihkan CRC lama (8 karakter terakhir)
    raw = static_str.strip()[:-8]
    
    # 2. Ubah Tag 01 dari statis (11) ke dinamis (12)
    raw = raw.replace("010211", "010212", 1)
    
    # 3. Format Tag 54 (Nominal)
    amount_str = str(int(amount))
    tag54 = f"54{len(amount_str):02d}{amount_str}"
    
    # 4. Sisipkan Tag 54 persis sebelum 5802ID
    pos = raw.find("5802ID")
    payload_body = raw[:pos] + tag54 + raw[pos:]
    
    # 5. Hitung CRC16 baru
    payload_with_tag63 = payload_body + "6304"
    return payload_with_tag63 + crc16_ccitt(payload_with_tag63)
