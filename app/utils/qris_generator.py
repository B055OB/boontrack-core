import io
import os
import re
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
    """Mengubah payload QRIS Statis menjadi QRIS Dinamis dengan menyisipkan nominal (Tag 54)
    dan memperbarui Checksum CRC16 (Tag 63).
    
    Langkah:
    1. Bersihkan static payload dari 8 karakter CRC lama (Tag 6304XXXX).
    2. Ubah Tag 01 (Point of Initiation Method): '010211' (Static) -> '010212' (Dynamic).
    3. Susun Tag 54 nominal: f"54{len(amount_str):02d}{amount_str}".
    4. Sisipkan Tag 54 persis sebelum Tag 58 ('5802ID').
    5. Tambahkan header '6304', hitung CRC16-CCITT baru, dan gabungkan di akhir.
    
    Args:
        static_payload (str): Payload QRIS statis dasar (misal dari .env / Shopee / BCA / DANA).
        amount (int): Nominal transaksi dalam Rupiah (integer bulat, e.g. 10000, 25000).
        
    Returns:
        str: String payload QRIS Dinamis lengkap siap render.
    """
    clean_payload = (static_payload or "").strip()
    if not clean_payload:
        raise ValueError("Static QRIS payload tidak boleh kosong")

    # 1. Hapus Tag 63 lama (6304XXXX) jika ada di bagian akhir
    if "6304" in clean_payload:
        last_6304_pos = clean_payload.rfind("6304")
        if last_6304_pos >= len(clean_payload) - 8:
            clean_payload = clean_payload[:last_6304_pos]
    elif len(clean_payload) > 8 and clean_payload[-8:-4] == "6304":
        clean_payload = clean_payload[:-8]

    # 2. Ganti Tag 01: 010211 (Static) -> 010212 (Dynamic)
    if "010211" in clean_payload:
        clean_payload = clean_payload.replace("010211", "010212", 1)

    # 3. Susun Tag 54 nominal: 54{len(amount):02d}{amount}
    amount_str = str(int(amount))
    tag_54 = f"54{len(amount_str):02d}{amount_str}"

    # 4. Sisipkan Tag 54 persis sebelum Tag 58 (5802ID / 5802)
    if "5802ID" in clean_payload:
        pos = clean_payload.find("5802ID")
        payload_body = clean_payload[:pos] + tag_54 + clean_payload[pos:]
    elif "5802" in clean_payload:
        pos = clean_payload.find("5802")
        payload_body = clean_payload[:pos] + tag_54 + clean_payload[pos:]
    else:
        payload_body = clean_payload + tag_54

    # 5. Tambahkan header 6304, hitung CRC16, dan gabungkan di akhir
    payload_with_header = payload_body + "6304"
    checksum = crc16_ccitt(payload_with_header)
    return payload_with_header + checksum


def generate_qris_image_bytes(payload: str, box_size: int = 10, border: int = 2) -> bytes:
    """Render QR Code image PNG dalam bentuk bytes murni (In-Memory) menggunakan library qrcode.
    
    Args:
        payload (str): String payload QRIS lengkap (statis atau dinamis).
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
