import io
import re
import random
import qrcode
from PIL import Image


def calculate_crc16(payload: str) -> str:
    """Menghitung CRC16 CCITT (0xFFFF) sesuai standar EMVCo / QRIS."""
    crc = 0xFFFF
    for char in payload.encode("utf-8"):
        crc ^= (char << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def generate_dynamic_qris_payload(static_qris: str, amount: int) -> str:
    """Mengubah string QRIS statis DANA menjadi QRIS Dinamis dengan nominal terkunci."""
    if not static_qris or len(static_qris) < 20:
        # Fallback template payload jika string QRIS env kosong
        static_qris = "00020101021126670016ID.CO.DANA.WWW0118936009153000000000520458125802ID5916BoonTrack6007Bandung6304"

    # 1. Potong checksum lama (Tag 63)
    clean_payload = static_qris.split("6304")[0]

    # 2. Ubah Tag 01 (Point of Initiation Method) dari '11' (Statis) ke '12' (Dinamis)
    if "010211" in clean_payload:
        clean_payload = clean_payload.replace("010211", "010212", 1)
    elif "010212" not in clean_payload:
        clean_payload = clean_payload[:8] + "010212" + clean_payload[8:]

    # 3. Hapus Tag 54 (Amount) jika sudah ada sebelumnya
    clean_payload = re.sub(r"54\d{2}\d+", "", clean_payload)

    # 4. Format Tag 54 untuk nominal baru
    amount_str = str(amount)
    amount_len = f"{len(amount_str):02d}"
    tag_54 = f"54{amount_len}{amount_str}"

    # 5. Sisipkan Tag 54 sebelum Tag 58 (Country Code '5802ID')
    if "5802ID" in clean_payload:
        idx = clean_payload.find("5802ID")
        clean_payload = clean_payload[:idx] + tag_54 + clean_payload[idx:]
    else:
        clean_payload += tag_54

    # 6. Tambahkan Tag 6304 lalu hitung checksum CRC16
    payload_to_crc = clean_payload + "6304"
    crc_code = calculate_crc16(payload_to_crc)

    return payload_to_crc + crc_code


def render_qris_image(payload: str) -> io.BytesIO:
    """Merender string payload QRIS menjadi file gambar PNG di memory stream."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#000000", back_color="#FFFFFF")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr