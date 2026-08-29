"""app/routes/meta_whatsapp.py
FastAPI Router for Meta WhatsApp Cloud API Webhook with Dynamic Tenant Resolution.

Features:
1. Top-Level Demo Menu Interceptor (highest priority):
   - General greetings ('halo', 'hi', 'p', 'test'), menu/reset keywords,
     or any sender without an active session -> instantly return Demo Menu Selector.
   - No fallback to digicorn or get_latest_commerce_tenant for these cases.
2. Menu Option Selection (1, 2, 3):
   - 1 -> bale_pananggeuhan
   - 2 -> atmosfitnes
   - 3 -> suhu-ads-masterclass
3. Dynamic Webhook Tenant Resolution for normal messages in active sessions.
4. Injects real commerce catalog and negative boundaries via CommerceAIEngine.
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
    normalize_phone_number,
    DEMO_MENU_TEXT,
    DEMO_TENANT_GREETINGS,
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

# Demo Menu Interceptor: these keywords always show the menu
_MENU_TRIGGER_KEYWORDS = {"halo", "hi", "p", "test", "tes", "hai", "start", "info", "menu", "demo", "#reset", "reset"}

# Menu Option Mapping: 1=Bale, 2=Gym, 3=Suhu Ads
_MENU_OPTION_MAP: Dict[str, str] = {
    "1": "bale_pananggeuhan",
    "2": "atmosfitnes",
    "3": "suhu-ads-masterclass",
}


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
    """Ingests incoming WhatsApp messages and dynamically dispatches to the resolved tenant.

    Priority execution order:
    1. Ignore status/non-message events.
    2. TOP-LEVEL INTERCEPTOR: greetings / #reset / no active session -> send Demo Menu.
    3. Menu Option Selection: '1', '2', '3' -> lock session + send greeting.
    4. Onboarding announcement: 'saya baru saja mendaftar toko [slug]' -> bind session.
    5. Active session -> route to tenant AI engine.
    """
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

    from_phone = event.get("from_phone", "")
    incoming_text = (event.get("text") or "").strip()
    contact_name = event.get("contact_name") or "Kakak"
    clean_phone = normalize_phone_number(from_phone)
    text_lower = incoming_text.lower()

    # Pre-check: Is this an onboarding announcement? If so, skip the menu interceptor.
    import re as _re
    _is_onboarding_msg = bool(
        _re.search(
            r"saya\s+baru\s+(?:saja\s+)?(?:mendaftar|daftar)\s+toko\s+[a-zA-Z0-9\-_]+",
            incoming_text,
            _re.IGNORECASE,
        )
        or _re.search(r"toko\s*:\s*[a-zA-Z0-9\-_]+", incoming_text, _re.IGNORECASE)
    )

    # =========================================================================
    # 2. TOP-LEVEL DEMO MENU INTERCEPTOR (Highest Priority)
    #    Fires BEFORE any tenant resolution or AI engine call.
    #    Condition: greeting keyword, #reset/menu/demo, or sender has NO active session.
    # =========================================================================
    _is_keyword_trigger = text_lower in _MENU_TRIGGER_KEYWORDS
    _has_active_session = bool(clean_phone and clean_phone in user_tenant_sessions)

    if (not _is_onboarding_msg) and (_is_keyword_trigger or not _has_active_session):
        # Forced reset: clear any stale session
        if clean_phone:
            user_tenant_sessions.pop(clean_phone, None)

        # BUT: if the message is actually a menu option (1/2/3), let step 3 handle it
        if text_lower not in _MENU_OPTION_MAP:
            logger.info(
                f"[META WA INTERCEPTOR] Sender {from_phone} triggered menu "
                f"(keyword={_is_keyword_trigger}, no_session={not _has_active_session})"
            )
            if from_phone:
                try:
                    await send_whatsapp_text(to_phone=from_phone, text=DEMO_MENU_TEXT)
                except Exception as err:
                    logger.warning(f"[META WA Menu Send Warning] {err}")

            safe_log_to_supabase_messages(
                sender="bot",
                text=DEMO_MENU_TEXT,
                tenant_id="__MENU__",
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
            )
            return {
                "status": "menu_dispatched",
                "tenant": "__MENU__",
                "is_new_binding": False,
                "reply": DEMO_MENU_TEXT,
            }

    # =========================================================================
    # 3. MENU OPTION SELECTION (1, 2, 3)
    # =========================================================================
    if text_lower in _MENU_OPTION_MAP:
        selected_slug = _MENU_OPTION_MAP[text_lower]
        if clean_phone:
            user_tenant_sessions[clean_phone] = selected_slug
        logger.info(
            f"[META WA MENU SELECT] Sender {from_phone} selected '{text_lower}' -> locked to '{selected_slug}'"
        )
        greeting = DEMO_TENANT_GREETINGS.get(selected_slug, f"🎉 Anda kini terhubung dengan *{selected_slug}*. Silakan mulai percakapan!")

        if from_phone:
            try:
                await send_whatsapp_text(to_phone=from_phone, text=greeting)
            except Exception as err:
                logger.warning(f"[META WA Greeting Send Warning] {err}")

        safe_log_to_supabase_messages(
            sender="bot",
            text=greeting,
            tenant_id=selected_slug,
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
        return {
            "status": "success",
            "tenant": selected_slug,
            "is_new_binding": True,
            "reply": greeting,
        }

    # =========================================================================
    # 4. Normal Message Pipeline: Resolve tenant + AI Engine
    # =========================================================================
    phone_id = event.get("phone_id", "")

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

    # Handle New Store Connection Announcement (onboarding pattern only)
    if is_new_binding and _is_onboarding_msg:
        welcome_msg = details.get("persona", {}).get("welcome_message", "Ada yang bisa kami bantu?") if details else ""
        reply = (
            f"🎉 *Selamat Datang di {store_name}!* 🎉\n\n"
            f"Nomor WhatsApp Kakak (*{contact_name}*) kini resmi terhubung dengan asisten toko *{store_name}*.\n\n"
            f"{welcome_msg}\n\n"
            f"_Silakan ketik nama produk atau ketik *menu* untuk melihat katalog._"
        )
    else:
        # Generate Dynamic AI Engine Response for locked tenant session
        reply = await commerce_ai_engine.generate_commerce_response(
            tenant_slug=tenant_slug,
            user_message=incoming_text,
            user_phone=from_phone,
            user_name=contact_name,
            button_id=event.get("button_id"),
        )
        if not reply:
            from app.services.agent_service import process_incoming_message
            reply = await process_incoming_message(
                tenant_slug=tenant_slug,
                message=incoming_text,
                user_phone=from_phone,
                user_name=contact_name,
                button_id=event.get("button_id"),
            )

    # Send outbound WhatsApp message
    if reply and from_phone:
        try:
            await send_whatsapp_text(to_phone=from_phone, text=reply)
        except Exception as send_err:
            logger.warning(f"[META WA Outbound Warning] {send_err}")

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
