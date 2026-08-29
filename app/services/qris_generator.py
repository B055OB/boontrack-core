"""app/services/qris_generator.py
In-Memory Native QRIS Image Generator Service.

Renders EMVCo QRIS payload strings directly into in-memory io.BytesIO PNG buffers
without writing temporary files to disk, eliminating third-party rendering dependencies.
"""

import io
import qrcode
from qrcode.constants import ERROR_CORRECT_M, ERROR_CORRECT_Q
from typing import Union


def generate_qris_png_buffer(
    qr_string: str,
    box_size: int = 10,
    border: int = 4,
    error_correction=ERROR_CORRECT_M,
) -> io.BytesIO:
    """Generates an in-memory PNG QR code buffer from an EMVCo QRIS string.
    
    Args:
        qr_string: The EMVCo payload string to encode.
        box_size: Pixel size of each QR box.
        border: Quiet zone border width (in boxes).
        error_correction: Error correction level (default ERROR_CORRECT_M).
        
    Returns:
        io.BytesIO buffer positioned at start (offset 0), containing PNG image data.
    """
    if not qr_string or not isinstance(qr_string, str):
        raise ValueError("qr_string must be a non-empty string")

    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction,
        box_size=box_size,
        border=border,
    )
    qr.add_data(qr_string.strip())
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def generate_qris_png_bytes(
    qr_string: str,
    box_size: int = 10,
    border: int = 4,
) -> bytes:
    """Convenience helper to return raw PNG bytes directly."""
    buf = generate_qris_png_buffer(qr_string, box_size=box_size, border=border)
    return buf.getvalue()
