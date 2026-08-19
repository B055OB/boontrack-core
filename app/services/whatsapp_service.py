import os
import io
import mimetypes
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)


def get_wa_credentials():
    """Mengambil token dan phone number ID secara dinamis saat runtime sesuai variabel Railway."""
    token = (
        os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or os.getenv("WA_TOKEN")
        or ""
    )
    phone_id = (
        os.getenv("PHONE_NUMBER_ID")
        or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        or os.getenv("META_PHONE_NUMBER_ID")
        or ""
    )
    version = os.getenv("META_GRAPH_VERSION", "v19.0")
    return token.strip(), phone_id.strip(), version


def _get_auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def send_whatsapp_text(to_phone: str, text: str, preview_url: bool = False) -> Optional[Dict[str, Any]]:
    """Mengirim pesan teks standar ke user WhatsApp via Meta Graph API."""
    token, phone_id, version = get_wa_credentials()
    if not token or not phone_id:
        logger.error(f"[WhatsApp Service] Missing credentials at runtime (token_len={len(token)}, phone_id={phone_id})")
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {
            "preview_url": preview_url,
            "body": text
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"[WhatsApp Service] send_text failed: {response.status_code} - {response.text}")
                return None
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_text: {e}")
        return None


async def upload_whatsapp_media(file_bytes: bytes, filename: str, mime_type: str) -> Optional[str]:
    """Mengunggah file biner ke Meta Cloud API untuk mendapatkan media_id."""
    token, phone_id, version = get_wa_credentials()
    if not token or not phone_id:
        logger.error("[WhatsApp Service] Missing credentials for media upload")
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/media"
    headers = _get_auth_headers(token)

    try:
        files = {
            "file": (filename, file_bytes, mime_type)
        }
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            if response.status_code != 200:
                logger.error(f"[WhatsApp Service] upload_media failed: {response.status_code} - {response.text}")
                return None
            return response.json().get("id")
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in upload_whatsapp_media: {e}")
        return None


async def send_whatsapp_image(to_phone: str, image_path: str, caption: str = "") -> Optional[Dict[str, Any]]:
    """Membaca file gambar lokal, mengunggah ke Meta, dan mengirimkannya sebagai pesan gambar ber-caption."""
    if not os.path.exists(image_path):
        logger.error(f"[WhatsApp Service] Image path not found: {image_path}")
        return await send_whatsapp_text(to_phone, caption)

    token, phone_id, version = get_wa_credentials()
    if not token or not phone_id:
        logger.error("[WhatsApp Service] Missing credentials in send_whatsapp_image, falling back to text")
        return await send_whatsapp_text(to_phone, caption)

    try:
        with open(image_path, "rb") as f:
            img_bytes = f.read()

        filename = os.path.basename(image_path)
        mime_type, _ = mimetypes.guess_type(image_path)
        mime_type = mime_type or "image/jpeg"

        media_id = await upload_whatsapp_media(img_bytes, filename, mime_type)
        if not media_id:
            return await send_whatsapp_text(to_phone, caption)

        url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
        headers = {
            **_get_auth_headers(token),
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "image",
            "image": {
                "id": media_id,
                "caption": caption
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"[WhatsApp Service] send_image failed: {response.status_code} - {response.text}")
                return await send_whatsapp_text(to_phone, caption)
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_image: {e}")
        return await send_whatsapp_text(to_phone, caption)


async def send_whatsapp_document(to_phone: str, file_bytes: bytes, filename: str, caption: str = "") -> Optional[Dict[str, Any]]:
    """Mengirim file dokumen (.pdf / .docx) langsung ke user WhatsApp."""
    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"

    media_id = await upload_whatsapp_media(file_bytes, filename, mime_type)
    if not media_id:
        return None

    token, phone_id, version = get_wa_credentials()
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
            "caption": caption
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"[WhatsApp Service] send_document failed: {response.status_code} - {response.text}")
                return None
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_document: {e}")
        return None


async def download_whatsapp_media_by_id(media_id: str) -> Optional[bytes]:
    """Mengunduh file bytes dari webhook attachment user berdasarkan media_id."""
    token, _, version = get_wa_credentials()
    if not token:
        logger.error("[WhatsApp Service] Missing token for download")
        return None

    headers = _get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            meta_res = await client.get(f"https://graph.facebook.com/{version}/{media_id}", headers=headers)
            if meta_res.status_code != 200:
                logger.error(f"[WhatsApp Service] Failed to retrieve media URL: {meta_res.status_code}")
                return None

            download_url = meta_res.json().get("url")
            if not download_url:
                return None

            file_res = await client.get(download_url, headers=headers)
            if file_res.status_code == 200:
                return file_res.content
            return None
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in download_whatsapp_media_by_id: {e}")
        return None