from app.utils.qris_generator import generate_dynamic_qris_payload, crc16_ccitt

calc_crc16 = crc16_ccitt

def generate_dynamic_qris(static_qris: str, amount: int) -> str:
    """Inject Tag 54 tanpa mengubah Tag 01, lalu hitung ulang CRC16 Tag 63."""
    return generate_dynamic_qris_payload(static_qris, amount)