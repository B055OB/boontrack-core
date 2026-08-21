import os
import io
import mimetypes
import logging
from typing import Optional, Dict, Any, Union, List
import httpx

logger = logging.getLogger(__name__)


def get_wa_credentials():
    """Mengambil token dan phone number ID secara dinamis saat runtime sesuai variabel Railway."""
    token = (
        os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or os.getenv("WA_TOKEN")
        or os.getenv("META_WA_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or ""
    )
    phone_id = (
        os.getenv("PHONE_NUMBER_ID")
        or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        or os.getenv("META_PHONE_NUMBER_ID")
        or os.getenv("META_WA_PHONE_NUMBER_ID")
        or ""
    )
    version = os.getenv("META_GRAPH_VERSION", "v21.0")
    return token.strip(), phone_id.strip(), version


def _get_auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def send_whatsapp_text(to_phone: str, text: str, preview_url: bool = False) -> Optional[Dict[str, Any]]:
    """Mengirim pesan teks standar ke user WhatsApp via Meta Graph API."""
    token, phone_id, version = get_wa_credentials()
    if not token or not phone_id:
        logger.error(f"[WhatsApp Service] Missing credentials (token_len={len(token)}, phone_id={phone_id})")
        return None

    clean_phone = str(to_phone).replace("+", "").strip()
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "text",
        "text": {
            "preview_url": preview_url,
            "body": text
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                logger.error(f"[WhatsApp Service] send_text failed: {response.status_code} - {response.text}")
                return None
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_text: {e}")
        return None


async def send_whatsapp_buttons(to_phone: str, body_text: str, buttons: List[Dict[str, str]], header_text: str = "", footer_text: str = "") -> Optional[Dict[str, Any]]:
    """Mengirim pesan tombol interaktif (Quick Reply Buttons) maksimal 3 tombol."""
    token, phone_id, version = get_wa_credentials()
    if not token or not phone_id:
        logger.error("[WhatsApp Service] Missing credentials in send_whatsapp_buttons")
        return await send_whatsapp_text(to_phone, body_text)

    clean_phone = str(to_phone).replace("+", "").strip()
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }

    button_action_list = []
    for btn in buttons[:3]:
        button_action_list.append({
            "type": "reply",
            "reply": {
                "id": btn.get("id", "btn_id"),
                "title": btn.get("title", "Tombol")[:20]  # Meta limit 20 chars
            }
        })

    interactive_obj: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": button_action_list}
    }

    if header_text:
        interactive_obj["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive_obj["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "interactive",
        "interactive": interactive_obj
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                logger.error(f"[WhatsApp Service] send_buttons failed: {response.status_code} - {response.text}")
                return await send_whatsapp_text(to_phone, body_text)
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_buttons: {e}")
        return await send_whatsapp_text(to_phone, body_text)


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
            if response.status_code not in (200, 201):
                logger.error(f"[WhatsApp Service] upload_media failed: {response.status_code} - {response.text}")
                return None
            return response.json().get("id")
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in upload_whatsapp_media: {e}")
        return None


async def send_whatsapp_image(to_phone: str, image_path_or_bytes: Union[str, bytes], caption: str = "") -> Optional[Dict[str, Any]]:
    """Mendukung pengiriman gambar via file path, bytes, maupun link."""
    token, phone_id, version = get_wa_credentials()
    if not token or not phone_id:
        return await send_whatsapp_text(to_phone, caption)

    clean_phone = str(to_phone).replace("+", "").strip()
    img_bytes = None
    filename = "qris_boontrack.png"
    mime_type = "image/png"

    if isinstance(image_path_or_bytes, bytes):
        img_bytes = image_path_or_bytes
    elif isinstance(image_path_or_bytes, str) and os.path.exists(image_path_or_bytes):
        with open(image_path_or_bytes, "rb") as f:
            img_bytes = f.read()
        filename = os.path.basename(image_path_or_bytes)
        guessed, _ = mimetypes.guess_type(image_path_or_bytes)
        mime_type = guessed or ("image/jpeg" if filename.endswith((".jpg", ".jpeg")) else "image/png")
    elif isinstance(image_path_or_bytes, str) and image_path_or_bytes.startswith(("http://", "https://")):
        url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
        headers = {
            **_get_auth_headers(token),
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": {"link": image_path_or_bytes, "caption": caption}
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code in (200, 201):
                    return res.json()
                return await send_whatsapp_text(to_phone, caption)
        except Exception:
            return await send_whatsapp_text(to_phone, caption)

    if not img_bytes:
        return await send_whatsapp_text(to_phone, caption)

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
        "to": clean_phone,
        "type": "image",
        "image": {"id": media_id, "caption": caption}
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                return await send_whatsapp_text(to_phone, caption)
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_image: {e}")
        return await send_whatsapp_text(to_phone, caption)


async def send_whatsapp_document(to_phone: str, file_path_or_bytes: Union[str, bytes], filename: str = "document.docx", caption: str = "") -> Optional[Dict[str, Any]]:
    """Mengirim file dokumen (.docx / .pdf) langsung ke user WhatsApp."""
    if isinstance(file_path_or_bytes, str) and os.path.exists(file_path_or_bytes):
        with open(file_path_or_bytes, "rb") as f:
            file_bytes = f.read()
        filename = os.path.basename(file_path_or_bytes)
    elif isinstance(file_path_or_bytes, bytes):
        file_bytes = file_path_or_bytes
    else:
        return None

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    media_id = await upload_whatsapp_media(file_bytes, filename, mime_type)
    if not media_id:
        return None

    token, phone_id, version = get_wa_credentials()
    clean_phone = str(to_phone).replace("+", "").strip()
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
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
            if response.status_code not in (200, 201):
                return None
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_document: {e}")
        return None


async def download_whatsapp_media_by_id(media_id: str) -> Optional[bytes]:
    """Mengunduh file bytes dari attachment user."""
    token, _, version = get_wa_credentials()
    if not token:
        return None

    headers = _get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            meta_res = await client.get(f"https://graph.facebook.com/{version}/{media_id}", headers=headers)
            if meta_res.status_code != 200:
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