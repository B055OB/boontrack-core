import io
import random
import qrcode
from qrcode.constants import ERROR_CORRECT_M


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


def generate_dynamic_qris_payload(static_payload: str, amount: int) -> str:
    """Mengubah master static QRIS menjadi Dynamic QRIS dengan Tag 54 dan Tag 01=010212."""
    clean_str = static_payload.strip()
    raw = clean_str[:-4]  # Menyisakan sampai "...6304"
    
    # 1. Ubah Tag 01 Point of Initiation Method menjadi Dinamis (010211 -> 010212)
    raw = raw.replace("010211", "010212", 1)
    
    # 2. Format Tag 54 (Nominal)
    str_amount = str(int(amount))
    tag_54 = f"54{len(str_amount):02d}{str_amount}"
    
    # 3. Sisipkan Tag 54 persis sebelum "5802ID"
    idx_58 = raw.find("5802ID")
    if idx_58 != -1:
        payload_body = raw[:idx_58] + tag_54 + raw[idx_58:]
    else:
        payload_body = raw + tag_54
    
    # 4. Hitung ulang CRC16-CCITT standar EMVCo
    return payload_body + crc16_ccitt(payload_body)


def render_qris_bytes(payload: str) -> bytes:
    """Render matriks QR ke in-memory byte buffer (io.BytesIO) PNG."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=4
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def get_dynamic_qris_string(amount: int, master_static: str = "") -> str:
    """Mengembalikan string Dynamic QRIS standar EMVCo."""
    if not master_static:
        import os
        master_static = os.getenv("BOONTRACK_STATIC_QRIS", "").strip()
    if not master_static:
        master_static = "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI5204737253033605802ID5909BoonTrack6012Kab. Bandung61054028663048DC1"
    return generate_dynamic_qris_payload(master_static, int(amount))


def get_quickchart_qr_url(qris_string: str) -> str:
    """Menghasilkan direct QuickChart image URL untuk QRIS string."""
    import urllib.parse
    return f"https://quickchart.io/qr?text={urllib.parse.quote(qris_string)}&size=500&ecLevel=H"


def generate_dynamic_qris_image(amount: int, master_static: str = "") -> bytes:
    """Helper fungsi langsung untuk generate dynamic QRIS PNG bytes dari amount."""
    payload = get_dynamic_qris_string(amount, master_static)
    return render_qris_bytes(payload)


def save_dynamic_qris_temp_file(
    amount: int,
    filename: str = "",
    master_static: str = "",
    target_dir: str = ""
) -> str:
    """Menyimpan matriks QRIS ke file sementara di direktori terstandarisasi (app/assets/temp/ atau tempfile),
    bukan di root folder project. Mengembalikan path absolut file yang tersimpan.
    """
    import os
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
    qr_bytes = generate_dynamic_qris_image(amount, master_static)
    with open(file_path, "wb") as f:
        f.write(qr_bytes)
    return file_path


generate_qris_image_bytes = render_qris_bytes