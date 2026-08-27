#!/usr/bin/env python3
"""Manual Ad-hoc QRIS Generator Test Script."""

import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from app.utils.qris_generator import save_dynamic_qris_temp_file, get_dynamic_qris_string, crc16_ccitt

def generate_dynamic_qris(static_payload: str, amount: int, output_file: str = ""):
    raw = static_payload.strip()[:-4]
    raw = raw.replace("010211", "010212", 1)
    
    str_amt = str(int(amount))
    tag_54 = f"54{len(str_amt):02d}{str_amt}"
    
    parts = raw.split("5802ID", 1)
    payload_before_crc = parts[0] + tag_54 + "5802ID" + parts[1]
    
    final_payload = payload_before_crc + crc16_ccitt(payload_before_crc)
    
    if output_file:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=12,
            border=4
        )
        qr.add_data(final_payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(output_file)
        print(f"File QRIS {amount:,} berhasil dibuat: {output_file}")
    else:
        saved_path = save_dynamic_qris_temp_file(amount)
        print(f"File QRIS {amount:,} berhasil dibuat di temp: {saved_path}")
    print(f"Payload: {final_payload}")

# Master QRIS Statis DANA Asli BoonTrack
BOONTRACK_DANA_STATIC = "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI5204737253033605802ID5909BoonTrack6012Kab. Bandung61054028663048DC1"

if __name__ == "__main__":
    generate_dynamic_qris(BOONTRACK_DANA_STATIC, 39000)
