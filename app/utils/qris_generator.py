import io
import qrcode

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

def generate_dynamic_qris_payload(static_payload: str, amount: int) -> str:
    raw = static_payload.strip()[:-8] if static_payload.strip()[-8:-4] == "6304" else static_payload.strip()
    
    str_amount = str(int(amount))
    tag_54 = f"54{len(str_amount):02d}{str_amount}"
    
    idx_58 = raw.find("5802ID")
    payload_no_crc = raw[:idx_58] + tag_54 + raw[idx_58:]
    
    payload_to_crc = payload_no_crc + "6304"
    return payload_to_crc + crc16_ccitt(payload_to_crc)

def render_qris_bytes(payload: str) -> bytes:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()

# Alias fungsi agar kompatibel dengan payment.py dan test_suite
generate_qris_image_bytes = render_qris_bytes