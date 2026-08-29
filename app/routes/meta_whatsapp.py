"""app/routes/meta_whatsapp.py
FastAPI Router for Meta WhatsApp Cloud API Webhook with Dynamic Tenant Resolution.

Features:
1. Dynamic Webhook Tenant Resolution:
   - Eliminates hardcoded fallbacks to bale_pananggeuhan or om_budi for sandbox +15556769563.
   - Detects onboarding intent: "saya baru saja mendaftar toko [slug]".
   - Maintains active conversation session per sender phone number.
   - Automatically falls back to the latest active COMMERCE_TEMPLATE tenant.
2. Injects real commerce catalog and negative boundaries via CommerceAIEngine.
"""

import os
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Response, Query, status

from app.services.whatsapp_service import (
    extract_meta_whatsapp_event,
    resolve_dynamic_tenant_for_whatsapp,
    send_whatsapp_text,
    user_tenant_sessions,
    safe_log_to_supabase_messages,
)
from app.services.onboarding_service import onboarding_service
from app.services.ai_engine import commerce_ai_engine

logger = logging.getLogger("META_WHATSAPP_ROUTER")

meta_whatsapp_router = APIRouter(tags=["Meta WhatsApp Webhook"])

VERIFY_TOKENS = [
    os.getenv("META_WEBHOOK_VERIFY_TOKEN", "boontrack-secure-verify-token"),
    os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_master_verify_token_2026"),
    "boontrack-secure-verify-token",
    "boontrack_master_verify_token_2026",
    "om_budi_secure_token_2026",
    "boontrack_career_token",
]


# =============================================================================
# 1. GET Handshake Verification (Meta Hub Challenge)
# =============================================================================

@meta_whatsapp_router.get("/api/v1/whatsapp/webhook", summary="Meta Webhook Verification")
@meta_whatsapp_router.get("/webhook/whatsapp", summary="Meta Webhook Verification Alias")
@meta_whatsapp_router.get("/api/whatsapp/webhook", summary="Meta Webhook Verification Alias 2")
async def verify_webhook_handshake(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Handles Meta webhook challenge subscription verification."""
    if hub_mode == "subscribe" and hub_verify_token in VERIFY_TOKENS:
        logger.info("[META WA] Webhook handshake verified successfully.")
        return Response(content=hub_challenge or "", media_type="text/plain", status_code=200)

    logger.warning(f"[META WA] Handshake token mismatch: {hub_verify_token}")
    return Response(content="Verification token mismatch", media_type="text/plain", status_code=403)


# =============================================================================
# 2. POST Message Ingestion & Dynamic Routing
# =============================================================================

@meta_whatsapp_router.post("/api/v1/whatsapp/webhook", summary="Meta WhatsApp Inbound Receiver")
@meta_whatsapp_router.post("/webhook/whatsapp", summary="Meta WhatsApp Inbound Receiver Alias")
@meta_whatsapp_router.post("/api/whatsapp/webhook", summary="Meta WhatsApp Inbound Receiver Alias 2")
async def handle_whatsapp_webhook(request: Request):
    """Ingests incoming WhatsApp messages and dynamically dispatches to the resolved tenant."""
    try:
        data = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON format"}

    event = extract_meta_whatsapp_event(data)

    # 1. Ignore delivery / read statuses
    if event.get("is_status"):
        return {"status": "status_ignored"}

    if not event.get("is_message"):
        return {"status": "ignored"}

    phone_id = event.get("phone_id", "")
    from_phone = event.get("from_phone", "")
    incoming_text = event.get("text", "")
    contact_name = event.get("contact_name") or "Kakak"

    # 2. Dynamic Tenant Resolution
    tenant_slug, is_new_binding = resolve_dynamic_tenant_for_whatsapp(
        phone_id=phone_id,
        from_phone=from_phone,
        message_text=incoming_text,
    )

    logger.info(
        f"[META WA] Inbound message from {from_phone} resolved to tenant '{tenant_slug}' (new_binding={is_new_binding})"
    )

    # Retrieve tenant info
    details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
    store_name = details.get("tenant", {}).get("name", tenant_slug) if details else tenant_slug

    # 3. Handle New Store Connection Announcement
    if is_new_binding:
        welcome_msg = details.get("persona", {}).get("welcome_message", "Ada yang bisa kami bantu?") if details else ""
        reply = (
            f"🎉 *Selamat Datang di {store_name}!* 🎉\n\n"
            f"Nomor WhatsApp Kakak (*{contact_name}*) kini resmi terhubung dengan asisten toko *{store_name}*.\n\n"
            f"{welcome_msg}\n\n"
            f"_Silakan ketik nama produk atau ketik *menu* untuk melihat katalog._"
        )
    else:
        # 4. Generate Bounded AI Commerce Response
        reply = await commerce_ai_engine.generate_commerce_response(
            tenant_slug=tenant_slug,
            user_message=incoming_text,
            user_phone=from_phone,
            user_name=contact_name,
            button_id=event.get("button_id"),
        )

    # Send outbound WhatsApp message asynchronously (non-blocking)
    if reply and from_phone:
        try:
            await send_whatsapp_text(recipient_phone=from_phone, text=reply)
        except Exception as send_err:
            logger.warning(f"[META WA Outbound Warning] {send_err}")

    # Safe log to message table
    safe_log_to_supabase_messages(
        sender="bot",
        text=reply,
        tenant_id=tenant_slug,
        channel="whatsapp",
        user_phone=from_phone,
        user_name=contact_name,
    )

    return {
        "status": "success",
        "tenant": tenant_slug,
        "is_new_binding": is_new_binding,
        "reply": reply,
    }
