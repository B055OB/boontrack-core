"""Meta WhatsApp Client Adapter & Gateway Module for BoonTrack Core."""

from app.services.whatsapp_service import (
    upload_media,
    upload_whatsapp_media,
    send_whatsapp_image,
    send_whatsapp_text,
    send_whatsapp_buttons,
    send_whatsapp_document,
    download_whatsapp_media_by_id,
    get_wa_credentials,
    get_supabase,
    log_to_supabase_messages,
    normalize_phone_number,
)
from app.whatsapp.gateway import (
    verify_whatsapp_handshake,
    handle_whatsapp_inbound,
)
from app.whatsapp.router import register_whatsapp_routes

__all__ = [
    "upload_media",
    "upload_whatsapp_media",
    "send_whatsapp_image",
    "send_whatsapp_text",
    "send_whatsapp_buttons",
    "send_whatsapp_document",
    "download_whatsapp_media_by_id",
    "get_wa_credentials",
    "get_supabase",
    "log_to_supabase_messages",
    "normalize_phone_number",
    "verify_whatsapp_handshake",
    "handle_whatsapp_inbound",
    "register_whatsapp_routes",
]
