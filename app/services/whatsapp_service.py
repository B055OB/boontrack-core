"""
app/services/whatsapp_service.py  ← FACADE (Zero Breaking Changes)
---------------------------------------------------------------------
File ini dipertahankan sebagai facade tipis untuk backward compatibility.
Semua implementasi telah dipindahkan ke package modular:
  app/services/whatsapp/
    ├── credentials.py      (Supabase, phone normalisation, session maps, WA credentials)
    ├── cloud_api.py        (Meta Cloud API send/upload functions, Supabase logging)
    ├── inbound_parser.py   (extract_meta_whatsapp_event)
    ├── commerce.py         (QRIS, catalogue, cart, checkout)
    ├── session_router.py   (DEMO_MENU_TEXT, resolve_dynamic_tenant_for_whatsapp)
    └── evolution.py        (Evolution API v2 adapter)

Semua import dari modul lain yang menggunakan:
    from app.services.whatsapp_service import X
tetap berfungsi tanpa perubahan.
"""

# Re-export semua public symbols dari package modular
from app.services.whatsapp import (  # noqa: F401, F403
    # credentials
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
    # cloud_api
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
    # inbound_parser
    extract_meta_whatsapp_event,
    # commerce
    BUY_INTENTS,
    is_closing_buy_intent,
    generate_qris_image_bytes,
    get_tenant_products_from_db,
    build_tenant_catalog_sections,
    send_whatsapp_tenant_catalog,
    add_product_to_cart,
    generate_cart_checkout_response,
    generate_fast_track_checkout_response,
    # session_router
    DEMO_MENU_TEXT,
    DEMO_TENANT_GREETINGS,
    resolve_dynamic_tenant_for_whatsapp,
    # evolution
    EVOLUTION_BASE_URL,
    EVOLUTION_API_KEY,
    get_evolution_headers,
    clean_evolution_base64_qr,
    get_or_create_evolution_session,
    is_valid_whatsapp_pairing_code,
    format_whatsapp_pairing_code,
    request_evolution_pairing_code,
    # activation
    normalize_activation_code,
    find_tenant_by_activation_code,
    ALLOWED_PENDING_STATUSES,
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
    # activation
    "normalize_activation_code",
    "find_tenant_by_activation_code",
    "ALLOWED_PENDING_STATUSES",
]