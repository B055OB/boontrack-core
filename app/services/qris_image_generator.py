import io
import qrcode
from PIL import Image

def generate_qris_qr_bytes(qris_string: str) -> bytes:
    """Generate gambar QR Code dari string EMVCo dalam format byte stream (PNG)."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(qris_string)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()