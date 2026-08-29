"""app/services/meta_media.py
Meta Graph Media API Client for WhatsApp Cloud API.

Handles multipart uploading of in-memory image buffers (io.BytesIO or bytes)
to obtain media_id tokens, and sending native media messages.
"""

import io
import logging
import httpx
from typing import Optional, Dict, Any, Union
from app.services.whatsapp_service import get_wa_credentials, _get_auth_headers

logger = logging.getLogger("META_MEDIA_API")


async def upload_whatsapp_media(
    image_bytes: Union[io.BytesIO, bytes],
    mime_type: str = "image/png",
    filename: str = "qris_xendit.png",
    tenant_id: str = "suhu-ads-masterclass",
) -> Optional[str]:
    """Uploads in-memory image buffer via multipart/form-data to Meta WhatsApp Cloud API.
    
    POST https://graph.facebook.com/{version}/{phone_number_id}/media
    
    Args:
        image_bytes: io.BytesIO buffer or raw bytes of the image.
        mime_type: MIME type of the upload (default "image/png").
        filename: Attachment filename.
        tenant_id: Tenant slug for credential lookup.
        
    Returns:
        media_id string if successful, else None.
    """
    token, phone_id, version = get_wa_credentials(tenant_id)
    if not token or not phone_id:
        logger.error(f"[Meta Media] Missing WA credentials for tenant '{tenant_id}'")
        return None

    raw_data = image_bytes.getvalue() if isinstance(image_bytes, io.BytesIO) else image_bytes
    if not raw_data:
        logger.error("[Meta Media] Empty image buffer provided")
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/media"
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": (filename, raw_data, mime_type)}
    data = {
        "messaging_product": "whatsapp",
        "type": mime_type,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            if response.status_code in (200, 201):
                res_json = response.json()
                media_id = res_json.get("id")
                if media_id:
                    logger.info(f"[Meta Media] Successfully uploaded {len(raw_data)} bytes -> media_id={media_id}")
                    return str(media_id)
            logger.error(f"[Meta Media] Upload failed HTTP {response.status_code}: {response.text}")
            return None
    except Exception as e:
        logger.error(f"[Meta Media] Exception uploading media: {e}", exc_info=True)
        return None


async def send_whatsapp_media_image(
    to_phone: str,
    media_id: str,
    caption: str = "",
    tenant_id: str = "suhu-ads-masterclass",
) -> Optional[Dict[str, Any]]:
    """Sends a native image message to WhatsApp user using an uploaded media_id.
    
    Args:
        to_phone: Recipient phone number.
        media_id: Meta Cloud API media identifier.
        caption: Accompanying text caption.
        tenant_id: Tenant slug.
        
    Returns:
        Response payload from Meta API.
    """
    from app.services.whatsapp_service import send_whatsapp_image
    return await send_whatsapp_image(
        to_phone=to_phone,
        image_path_or_bytes=None,
        caption=caption,
        tenant_id=tenant_id,
        media_id=media_id,
    )
