import os
import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Membaca environment variables yang sudah ada di Railway
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID") or os.getenv("META_WA_PHONE_NUMBER_ID", "")
ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN") or os.getenv("META_WA_ACCESS_TOKEN", "")
GRAPH_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages" if PHONE_NUMBER_ID else ""

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

async def send_whatsapp_text(to_number: str, message_text: str) -> bool:
    """Mengirim pesan teks ke WhatsApp pengguna via Meta Cloud API."""
    if not PHONE_NUMBER_ID or not ACCESS_TOKEN:
        logger.error("[WhatsApp] Credentials PHONE_NUMBER_ID atau WHATSAPP_TOKEN belum diatur.")
        return False

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": message_text
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(GRAPH_API_URL, headers=HEADERS, json=payload)
            if response.status_code == 200:
                logger.info(f"[WhatsApp] Berhasil kirim pesan ke {to_number}")
                return True
            logger.error(f"[WhatsApp Send Error] {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"[WhatsApp Exception] Gagal kirim pesan ke {to_number}: {e}")
        return False