import base64
import json
import logging
import os
import aiohttp
from typing import Dict, Any

logger = logging.getLogger("RECEIPT_OCR")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


async def analyze_receipt_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    """Menganalisis struk transfer/QRIS via Gemini Vision Model."""
    fallback_res = {
        "is_valid_receipt": False,
        "nominal": 0,
        "transaction_date": "",
        "reference_no_rrn": "",
        "bank_source": "UNKNOWN"
    }

    if not GEMINI_API_KEY or not image_bytes:
        logger.warning("[OCR] API key atau payload gambar tidak ditemukan.")
        return fallback_res

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = """
    Analisis gambar bukti transfer / struk pembayaran bank / QRIS ini.
    Ekstrak data dalam format JSON murni tanpa markdown formatting:
    {
      "is_valid_receipt": boolean, // true jika ini bukti transfer berhasil/sukses, false jika bukan struk/gagal
      "nominal": integer, // angka nominal uang tanpa titik/koma (misal 200000)
      "transaction_date": string, // tanggal transaksi tertera
      "reference_no_rrn": string, // nomor referensi / RRN / no transaksi
      "bank_source": string // Bank atau Dompet Digital pengirim/penerima (BSI, BCA, QRIS, dll)
    }
    """

    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": encoded_image
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.1
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, json=payload, timeout=25) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text_response = data["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(text_response)
                else:
                    err = await resp.text()
                    logger.error(f"[OCR ERROR] Status {resp.status}: {err}")
    except Exception as e:
        logger.error(f"[OCR EXCEPTION] {e}", exc_info=True)

    return fallback_res


# Alias untuk kompatibilitas import modul lama/baru
async def parse_receipt_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    return await analyze_receipt_image(image_bytes=image_bytes, mime_type=mime_type)