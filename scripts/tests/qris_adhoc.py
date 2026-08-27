"""Ad-hoc experimental QRIS generator script."""
import io
import os
import qrcode
from qrcode.constants import ERROR_CORRECT_M


def crc16_ccitt(data: str) -> str:
    """Menghitung Checksum CRC16-CCITT (0xFFFF, Poly 0x1021)."""
    crc = 0xFFFF
    for char in data:
        crc ^= (ord(char) << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def build_dynamic_qris_payload(amount: int, static_payload: str = None) -> str:
    """Mengubah payload statis menjadi dinamis dengan nominal tagihan."""
    payload = static_payload or os.getenv("BOONTRACK_STATIC_QRIS", "")
    if not payload:
        raise ValueError("Payload QRIS Statis tidak ditemukan di .env")

    raw = payload.strip()[:-4]
    raw = raw.replace("010211", "010212", 1)

    str_amount = str(int(amount))
    tag_54 = f"54{len(str_amount):02d}{str_amount}"

    split_marker = "5802ID"
    if split_marker not in raw:
        raise ValueError("Tag 5802ID tidak ditemukan pada string QRIS")

    parts = raw.split(split_marker, 1)
    payload_before_crc = parts[0] + tag_54 + split_marker + parts[1]
    
    return payload_before_crc + crc16_ccitt(payload_before_crc)


def generate_qris_image_bytes(amount: int, static_payload: str = None) -> bytes:
    """Menghasilkan binary bytes PNG untuk langsung dikirim via WhatsApp API."""
    dynamic_payload = build_dynamic_qris_payload(amount, static_payload)

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    qr.add_data(dynamic_payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
