"""
app/services/whatsapp_cloud_api.py
-----------------------------------
Official Meta Cloud API (Graph v20.0+) Service Adapter for WhatsApp Business Platform.
Includes standardized payload building, message dispatching, and Supabase queue persistence.
"""
import logging
from typing import Optional, Dict, Any, List

# Re-export core WhatsApp functions and payload builders
from app.services.whatsapp.cloud_api import (
    build_whatsapp_text_payload,
    send_text,
    send_whatsapp_text,
    sanitize_whatsapp_message_text,
    log_to_supabase_messages,
    safe_log_to_supabase_messages,
    send_otp_whatsapp,
    send_ereceipt_whatsapp,
    send_whatsapp_buttons,
    upload_media,
    upload_whatsapp_media,
    send_whatsapp_image_link,
    send_whatsapp_image,
    send_whatsapp_document,
    download_whatsapp_media_by_id,
)

from app.services.whatsapp.credentials import (
    get_wa_credentials,
    normalize_phone_number,
    get_supabase,
)

logger = logging.getLogger("app.services.whatsapp_cloud_api")

__all__ = [
    "build_whatsapp_text_payload",
    "send_text",
    "send_whatsapp_text",
    "sanitize_whatsapp_message_text",
    "log_to_supabase_messages",
    "safe_log_to_supabase_messages",
    "send_otp_whatsapp",
    "send_ereceipt_whatsapp",
    "send_whatsapp_buttons",
    "upload_media",
    "upload_whatsapp_media",
    "send_whatsapp_image_link",
    "send_whatsapp_image",
    "send_whatsapp_document",
    "download_whatsapp_media_by_id",
    "get_wa_credentials",
    "normalize_phone_number",
    "get_supabase",
]
