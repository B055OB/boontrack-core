import os
import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Membaca environment variables dari Railway
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID") or os.getenv("META_WA_PHONE_NUMBER_ID", "")
ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN") or os.getenv("META_WA_ACCESS_TOKEN", "")
GRAPH_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages" if PHONE_NUMBER_ID else ""
MEDIA_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/media" if PHONE_NUMBER_ID else ""

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


async def send_whatsapp_document(
    to_number: str,
    file_path_or_url: str,
    filename: str = "CV_ATS_BoonTrack.docx",
    caption: str = ""
) -> bool:
    """Mengirim file dokumen (.docx / .pdf) via URL publik atau upload path lokal."""
    if not PHONE_NUMBER_ID or not ACCESS_TOKEN:
        logger.error("[WhatsApp] Credentials PHONE_NUMBER_ID atau WHATSAPP_TOKEN belum diatur.")
        return False

    # 1. JIKA FILE BERUPA URL PUBLIK (Supabase Storage / CDN)
    if file_path_or_url.startswith("http://") or file_path_or_url.startswith("https://"):
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "document",
            "document": {
                "link": file_path_or_url,
                "filename": filename,
                "caption": caption
            }
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GRAPH_API_URL, headers=HEADERS, json=payload)
                if response.status_code == 200:
                    logger.info(f"[WhatsApp] Berhasil kirim dokumen URL ke {to_number}")
                    return True
                logger.error(f"[WhatsApp Doc URL Error] {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"[WhatsApp Doc URL Exception] {e}")
            return False

    # 2. JIKA FILE DARI PATH LOKAL SERVER (Upload binary ke Meta Media Endpoint)
    try:
        if not os.path.exists(file_path_or_url):
            logger.error(f"[WhatsApp] File lokal tidak ditemukan: {file_path_or_url}")
            return False

        upload_headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(file_path_or_url, "rb") as f:
                files = {"file": (filename, f, mime_type)}
                data = {
                    "messaging_product": "whatsapp",
                    "type": mime_type
                }
                upload_res = await client.post(MEDIA_API_URL, headers=upload_headers, data=data, files=files)

            if upload_res.status_code != 200:
                logger.error(f"[WhatsApp Upload Media Error] {upload_res.status_code}: {upload_res.text}")
                return False

            media_id = upload_res.json().get("id")

            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_number,
                "type": "document",
                "document": {
                    "id": media_id,
                    "filename": filename,
                    "caption": caption
                }
            }
            send_res = await client.post(GRAPH_API_URL, headers=HEADERS, json=payload)
            if send_res.status_code == 200:
                logger.info(f"[WhatsApp] Berhasil kirim dokumen lokal ke {to_number}")
                return True
            logger.error(f"[WhatsApp Send Media ID Error] {send_res.status_code}: {send_res.text}")
            return False

    except Exception as e:
        logger.error(f"[WhatsApp Doc Local Exception] Gagal upload & kirim file: {e}")
        return False