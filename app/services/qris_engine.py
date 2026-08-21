import io
import re
import qrcode
from PIL import Image


def calculate_crc16(payload: str) -> str:
    """Menghitung ulang CRC16 CCITT (0xFFFF) sesuai standar EMVCo / QRIS."""
    crc = 0xFFFF
    for char in payload.encode("utf-8"):
        crc ^= (char << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def inject_dynamic_amount_bca(base_qris_payload: str, amount: int) -> str:
    """
    Menyuntikkan Tag 01=12 (Dynamic) dan Tag 54 (Nominal) ke string QRIS BCA Uwinfly.
    """
    if not base_qris_payload:
        base_qris_payload = (
            "00020101021126590014ID.CO.BCA.WWW0118936000140014781630020810221473"
            "5204581253033605802ID5915UWINFLY BANDUNG6007BANDUNG6304"
        )

    # 1. Potong checksum lama (Tag 63)
    clean_str = base_qris_payload.split("6304")[0]

    # 2. Ubah Tag 01 (Point of Initiation) menjadi 12 (Dynamic)
    if "010211" in clean_str:
        clean_str = clean_str.replace("010211", "010212", 1)

    # 3. Hapus Tag 54 lama jika ada
    clean_str = re.sub(r"54\d{2}\d+", "", clean_str)

    # 4. Buat Tag 54 (Amount/Nominal)
    amt_str = str(amount)
    amt_tag = f"54{len(amt_str):02d}{amt_str}"

    # 5. Sisipkan Tag 54 sebelum Tag 58 (Country Code '5802ID')
    if "5802ID" in clean_str:
        pos = clean_str.find("5802ID")
        clean_str = clean_str[:pos] + amt_tag + clean_str[pos:]
    else:
        clean_str += amt_tag

    # 6. Hitung CRC16 baru
    raw_payload_with_tag63 = clean_str + "6304"
    new_crc = calculate_crc16(raw_payload_with_tag63)

    return raw_payload_with_tag63 + new_crc


def render_qris_image(payload: str) -> io.BytesIO:
    """Render string payload ke gambar QR Code PNG di memory buffer."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#000000", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf