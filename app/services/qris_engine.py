import io
import qrcode

def calculate_crc16(data: str) -> str:
    crc = 0xFFFF
    for char in data:
        crc ^= ord(char) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return f"{crc:04X}"

def generate_dynamic_qris_payload(static_qris_raw: str, amount: int) -> str:
    # 1. Bersihkan CRC bawaan (Tag 63)
    if "6304" in static_qris_raw:
        base_payload = static_qris_raw[:static_qris_raw.rfind("6304")]
    else:
        base_payload = static_qris_raw

    # 2. Set Point of Initiation ke Dinamis (12)
    base_payload = base_payload.replace("010211", "010212", 1)

    # 3. Sisipkan Tag 54 (Nominal)
    str_amount = str(amount)
    tag_54 = f"54{len(str_amount):02d}{str_amount}"

    idx_58 = base_payload.find("5802ID")
    if idx_58 != -1:
        dynamic_payload = base_payload[:idx_58] + tag_54 + base_payload[idx_58:]
    else:
        dynamic_payload = base_payload + tag_54

    # 4. Generate CRC16 Baru
    payload_to_sign = dynamic_payload + "6304"
    crc_value = calculate_crc16(payload_to_sign)
    return payload_to_sign + crc_value

def render_qris_image(qris_payload: str) -> io.BytesIO:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(qris_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf