"""
app/services/whatsapp/__init__.py
------------------------------------------
Package init - re-export semua public symbol dari sub-modul.
Importers yang menggunakan `from app.services.whatsapp import X`
akan mendapatkan symbol yang sama.
"""

# credentials
from app.services.whatsapp.credentials import (
    get_supabase,
    normalize_phone_number,
    user_tenant_sessions,
    user_session_states,
    user_cart_sessions,
    user_phone_number_id_sessions,
    reset_whatsapp_user_session,
    get_user_session,
    set_user_session,
    get_wa_credentials,
    _get_auth_headers,
)

# cloud_api
from app.services.whatsapp.cloud_api import (
    sanitize_whatsapp_message_text,
    log_to_supabase_messages,
    safe_log_to_supabase_messages,
    send_whatsapp_text,
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

# inbound_parser
from app.services.whatsapp.inbound_parser import (
    extract_meta_whatsapp_event,
)

# commerce
from app.services.whatsapp.commerce import (
    BUY_INTENTS,
    is_closing_buy_intent,
    generate_qris_image_bytes,
    get_tenant_products_from_db,
    build_tenant_catalog_sections,
    send_whatsapp_tenant_catalog,
    add_product_to_cart,
    generate_cart_checkout_response,
    generate_fast_track_checkout_response,
)

# session_router
from app.services.whatsapp.session_router import (
    DEMO_MENU_TEXT,
    DEMO_TENANT_GREETINGS,
    resolve_dynamic_tenant_for_whatsapp,
)

# evolution
from app.services.whatsapp.evolution import (
    EVOLUTION_BASE_URL,
    EVOLUTION_API_KEY,
    get_evolution_headers,
    clean_evolution_base64_qr,
    get_or_create_evolution_session,
    is_valid_whatsapp_pairing_code,
    format_whatsapp_pairing_code,
    request_evolution_pairing_code,
)


__all__ = [
    # credentials
    "get_supabase",
    "normalize_phone_number",
    "user_tenant_sessions",
    "user_session_states",
    "user_cart_sessions",
    "user_phone_number_id_sessions",
    "reset_whatsapp_user_session",
    "get_user_session",
    "set_user_session",
    "get_wa_credentials",
    "_get_auth_headers",
    # cloud_api
    "sanitize_whatsapp_message_text",
    "log_to_supabase_messages",
    "safe_log_to_supabase_messages",
    "send_whatsapp_text",
    "send_otp_whatsapp",
    "send_ereceipt_whatsapp",
    "send_whatsapp_buttons",
    "upload_media",
    "upload_whatsapp_media",
    "send_whatsapp_image_link",
    "send_whatsapp_image",
    "send_whatsapp_document",
    "download_whatsapp_media_by_id",
    # inbound_parser
    "extract_meta_whatsapp_event",
    # commerce
    "BUY_INTENTS",
    "is_closing_buy_intent",
    "generate_qris_image_bytes",
    "get_tenant_products_from_db",
    "build_tenant_catalog_sections",
    "send_whatsapp_tenant_catalog",
    "add_product_to_cart",
    "generate_cart_checkout_response",
    "generate_fast_track_checkout_response",
    # session_router
    "DEMO_MENU_TEXT",
    "DEMO_TENANT_GREETINGS",
    "resolve_dynamic_tenant_for_whatsapp",
    # evolution
    "EVOLUTION_BASE_URL",
    "EVOLUTION_API_KEY",
    "get_evolution_headers",
    "clean_evolution_base64_qr",
    "get_or_create_evolution_session",
    "is_valid_whatsapp_pairing_code",
    "format_whatsapp_pairing_code",
    "request_evolution_pairing_code",
]
