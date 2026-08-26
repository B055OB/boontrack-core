import io
import os
import qrcode
from typing import Optional


def crc16_ccitt(data: str) -> str:
    """Kalkulasi CRC16-CCITT (poly 0x1021, init 0xFFFF) sesuai spesifikasi EMVCo / QRIS.
    
    Args:
        data (str): String input naskah payload QRIS yang akan dihitung checksum-nya.
        
    Returns:
        str: 4-digit hexadecimal string dalam format huruf besar (uppercase).
    """
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
    """Mengubah payload QRIS Statis menjadi Dynamic QRIS dengan menyisipkan nominal (Tag 54)
    sebelum Tag 58 (5802ID) dan menghitung ulang CRC16 (Tag 63) tanpa mengubah Tag 01 (tetap 010211).
    
    Args:
        static_payload (str): Payload QRIS statis dasar (dari .env / Shopee / BCA / DANA).
        amount (int): Nominal transaksi dalam Rupiah (integer bulat, e.g. 10000, 25000).
        
    Returns:
        str: String payload QRIS lengkap dengan nominal dan CRC16 baru.
    """
    clean_payload = (static_payload or "").strip()
    if not clean_payload:
        raise ValueError("Static QRIS payload tidak boleh kosong")

    # 1. Buang CRC lama
    raw = clean_payload[:-8] if len(clean_payload) >= 8 and clean_payload[-8:-4] == "6304" else clean_payload
    
    # 2. Susun Tag 54
    str_amount = str(int(amount))
    tag_54 = f"54{len(str_amount):02d}{str_amount}"
    
    # 3. Sisipkan sebelum 5802ID
    idx_58 = raw.find("5802ID")
    if idx_58 != -1:
        payload_with_amount = raw[:idx_58] + tag_54 + raw[idx_58:]
    else:
        payload_with_amount = raw + tag_54
        
    # 4. Hitung CRC16 baru
    payload_to_crc = payload_with_amount + "6304"
    new_crc = crc16_ccitt(payload_to_crc)
    return payload_to_crc + new_crc


def generate_qris_image_bytes(payload: str, box_size: int = 10, border: int = 2) -> bytes:
    """Render QR Code image PNG dalam bentuk bytes murni (In-Memory) menggunakan library qrcode.
    
    Args:
        payload (str): String payload QRIS lengkap.
        box_size (int): Ukuran piksel per kotak QR code.
        border (int): Tebal margin border di sekeliling QR code.
        
    Returns:
        bytes: Data gambar biner format PNG.
    """
    if not payload:
        raise ValueError("Payload QRIS tidak boleh kosong untuk merender gambar QR")

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
