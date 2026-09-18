import io
import os
import re
import random
import urllib.parse
from typing import Optional
from PIL import Image
import qrcode
from qrcode.constants import ERROR_CORRECT_M

STANDARD_MASTER_QRIS = (
    "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI"
    "51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI520473725303360"
    "5802ID5909BoonTrack6012Kab. Bandung61054028663048DC1"
)


def crc16_ccitt(data: str) -> str:
    """Menghitung Checksum CRC16-CCITT poligon 0x1021 standar EMVCo QRIS."""
    crc = 0xFFFF
    for char in data:
        crc ^= (ord(char) << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def generate_unique_code(min_val: int = 100, max_val: int = 999) -> int:
    """Generate 3-digit kode unik acak dalam rentang 100 - 999."""
    return random.randint(min_val, max_val)


def generate_dynamic_qris_payload(static_payload: str, amount: int, invoice_id: str = "") -> str:
    """Mengubah master static QRIS menjadi Dynamic QRIS standar EMVCo resmi Bank Indonesia (ASPI).
    
    1. Format Tag 01 (Wajib Dinamis):
       Jika payload diawali '000201010211', ganti menjadi '000201010212'.
    2. Pembersihan Tag 54 Lama (Anti-Duplikasi):
       Hapus tag 54 yang mungkin sudah ada sebelumnya sebelum menyisipkan yang baru.
    3. Penempatan Tag 54:
       Format f"54{len(amt_str):02d}{amt_str}" disisipkan tepat sebelum "5802ID" (atau "5802").
       Tag 62 asli bawaan acquirer (misal 62070703A01) dipertahankan apa adanya.
    4. Hitung Ulang CRC16-CCITT:
       Hitung ulang CRC16 hingga '6304' dengan poly 0x1021, init 0xFFFF (UPPERCASE 4 digit).
    """
    clean_str = (static_payload or "").strip()
    if not clean_str.startswith("000201") or "5802ID" not in clean_str or "5303360" not in clean_str:
        clean_str = STANDARD_MASTER_QRIS

    # 1. Hapus Tag 63 (CRC lama) di belakang string
    if "6304" in clean_str:
        idx_63 = clean_str.rfind("6304")
        raw = clean_str[:idx_63]
    else:
        raw = clean_str[:-4] if len(clean_str) > 4 else clean_str

    # 2. Format Tag 01 (Wajib Dinamis):
    # Jika payload diawali "000201010211", ganti menjadi "000201010212"
    if raw.startswith("000201010211"):
        raw = "000201010212" + raw[12:]
    elif "010211" in raw:
        raw = raw.replace("010211", "010212", 1)

    # 3. Pembersihan Tag 54 Lama (Anti-Duplikasi) sebelum Tag 58:
    idx_58 = raw.find("5802ID")
    if idx_58 == -1:
        idx_58 = raw.find("5802")

    if idx_58 != -1:
        before_58 = raw[:idx_58]
        after_58 = raw[idx_58:]
        before_58 = re.sub(r'54\d{2}\d+', '', before_58)
        raw = before_58 + after_58

    # 4. Penempatan Tag 54:
    amt_str = str(int(amount))
    tag_54 = f"54{len(amt_str):02d}{amt_str}"

    idx_58 = raw.find("5802ID")
    if idx_58 == -1:
        idx_58 = raw.find("5802")

    if idx_58 != -1:
        payload_body = raw[:idx_58] + tag_54 + raw[idx_58:]
    else:
        payload_body = raw + tag_54

    # 5. Pertahankan Tag 62 bawaan acquirer (JANGAN ditimpa atau dimodifikasi)
    # Hanya tambahkan Tag 62 jika invoice_id disediakan dan Tag 62 belum ada di string master
    has_tag_62 = any(f"62{i:02d}" in payload_body for i in range(1, 100))
    if invoice_id and not has_tag_62:
        clean_inv = str(invoice_id).strip()[:25]
        sub_01 = f"01{len(clean_inv):02d}{clean_inv}"
        tag_62 = f"62{len(sub_01):02d}{sub_01}"
        payload_body += tag_62

    # 6. Hitung ulang CRC16-CCITT standar EMVCo (poly 0x1021, init 0xFFFF)
    full_for_crc = payload_body + "6304"
    crc = crc16_ccitt(full_for_crc)
    return full_for_crc + crc


generate_dynamic_qris = generate_dynamic_qris_payload


def render_qris_bytes(payload: str, box_size: int = 10, border: int = 4) -> bytes:
    """Render matriks QR ke in-memory byte buffer (io.BytesIO) PNG resolusi tinggi (>= 500x500 px)."""
    clean_payload = (payload or "").strip()
    if not clean_payload.startswith("000201"):
        clean_payload = STANDARD_MASTER_QRIS

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=box_size,
            border=border,
        )
        qr.add_data(clean_payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Pastikan ukuran gambar minimal 500x500 pixel untuk ketajaman scan kamera & m-banking gallery
        if hasattr(img, "size") and (img.size[0] < 500 or img.size[1] < 500):
            img = img.resize((540, 540), Image.Resampling.NEAREST)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        # Fallback generator sederhana jika terjadi issue resize/pillow
        qr = qrcode.QRCode(box_size=box_size, border=border)
        qr.add_data(clean_payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()


def get_dynamic_qris_string(amount: int, master_static: str = "", invoice_id: str = "") -> str:
    """Mengembalikan string Dynamic QRIS standar EMVCo."""
    if not master_static:
        master_static = os.getenv("BOONTRACK_STATIC_QRIS", "").strip()
    if not master_static or not master_static.startswith("000201"):
        master_static = STANDARD_MASTER_QRIS
    return generate_dynamic_qris_payload(master_static, int(amount), invoice_id=invoice_id)


def get_qr_code_image_url(qris_string: str, size: int = 600) -> str:
    """Menghasilkan direct image URL resolusi tinggi (>= 500x500 px) dengan quiet zone border yang cukup."""
    return f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&margin=16&format=png&data={urllib.parse.quote(qris_string.strip())}"


def get_quickchart_qr_url(qris_string: str) -> str:
    """Menghasilkan direct QuickChart image URL untuk QRIS string dengan resolusi 600x600 px dan border 4."""
    return f"https://quickchart.io/qr?text={urllib.parse.quote(qris_string.strip())}&size=600&margin=4&ecLevel=M"


def generate_dynamic_qris_image(amount: int, master_static: str = "", invoice_id: str = "") -> bytes:
    """Helper fungsi langsung untuk generate dynamic QRIS PNG bytes dari amount."""
    payload = get_dynamic_qris_string(amount, master_static, invoice_id=invoice_id)
    return render_qris_bytes(payload)


def save_dynamic_qris_temp_file(
    amount: int,
    filename: str = "",
    master_static: str = "",
    target_dir: str = "",
    invoice_id: str = "",
) -> str:
    """Menyimpan matriks QRIS ke file sementara di direktori terstandarisasi (app/assets/temp/ atau tempfile),
    bukan di root folder project. Mengembalikan path absolut file yang tersimpan.
    """
    import tempfile

    if not target_dir:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_dir = os.getenv("BOONTRACK_TEMP_DIR") or os.path.join(base_dir, "assets", "temp")

    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception:
        target_dir = tempfile.gettempdir()

    if not filename:
        rand_suffix = random.randint(1000, 9999)
        filename = f"qris_{int(amount)}_{rand_suffix}.png"

    file_path = os.path.join(target_dir, filename)
    qr_bytes = generate_dynamic_qris_image(amount, master_static, invoice_id=invoice_id)
    with open(file_path, "wb") as f:
        f.write(qr_bytes)
    return file_path


generate_qris_image_bytes = render_qris_bytes
