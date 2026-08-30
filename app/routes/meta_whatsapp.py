"""app/routes/meta_whatsapp.py
FastAPI Router for Meta WhatsApp Cloud API Webhook with Dynamic Tenant Resolution.
"""

import os
import logging
import re
import urllib.parse
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Response, Query, status

from app.services.whatsapp_service import (
    extract_meta_whatsapp_event,
    resolve_dynamic_tenant_for_whatsapp,
    send_whatsapp_text,
    send_whatsapp_image_link,
    user_tenant_sessions,
    safe_log_to_supabase_messages,
    normalize_phone_number,
    generate_fast_track_checkout_response,
    is_closing_buy_intent,
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

_MENU_TRIGGER_KEYWORDS = {"halo", "hi", "p", "test", "tes", "hai", "start", "info", "menu", "demo", "#reset", "reset"}

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
    try:
        data = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON format"}

    event = extract_meta_whatsapp_event(data)

    if event.get("is_status"):
        return {"status": "status_ignored"}

    if not event.get("is_message"):
        return {"status": "ignored"}

    from_phone = event.get("from_phone", "")
    incoming_text = (event.get("text") or "").strip()
    contact_name = event.get("contact_name") or "Kakak"
    clean_phone = normalize_phone_number(from_phone)
    text_lower = incoming_text.lower()
    button_id = str(event.get("button_id") or "").strip().lower()
    phone_id = event.get("phone_id", "")

    if clean_phone and clean_phone not in user_tenant_sessions:
        user_tenant_sessions[clean_phone] = "suhu-ads-masterclass"

    active_tenant = user_tenant_sessions.get(clean_phone, "suhu-ads-masterclass")

    # =========================================================================
    # FAST-TRACK QRIS INTENT (Prioritas Paling Atas)
    # =========================================================================
    is_qris_buy_action = (
        button_id in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris"}
        or "beli & bayar qris" in text_lower
        or "beli" in text_lower
        or "bayar qris" in text_lower
        or "qris" in text_lower
        or is_closing_buy_intent(incoming_text, button_id)
    )

    if is_qris_buy_action and active_tenant not in ("bale_pananggeuhan", "bale-pananggeuhan", "pelayanan_publik"):
        reply, invoice, _ = await generate_fast_track_checkout_response(
            tenant_slug=active_tenant,
            from_phone=from_phone,
            contact_name=contact_name,
        )

        qr_string = invoice.get("qr_string", "")
        qr_code_url = invoice.get("qr_code_url") or f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(qr_string)}"

        image_delivered = False
        try:
            link_resp = await send_whatsapp_image_link(
                to_phone=from_phone,
                image_url=qr_code_url,
                caption=reply,
                tenant_id=active_tenant,
            )
            if link_resp and getattr(link_resp, "status_code", 200) in (200, 201):
                image_delivered = True
        except Exception as err:
            logger.warning(f"[WA IMAGE SEND ERROR] {err}")

        if not image_delivered:
            await send_whatsapp_text(to_phone=from_phone, text=reply)

        safe_log_to_supabase_messages(
            sender="bot",
            text=f"[Kirim QRIS {invoice.get('external_id')}] {reply}",
            tenant_id=active_tenant,
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
        return {
            "status": "qris_dispatched",
            "tenant": active_tenant,
            "invoice_id": invoice.get("external_id"),
        }

    # =========================================================================
    # SILABUS ACTION
    # =========================================================================
    if button_id == "btn_view_syllabus" or "silabus" in text_lower:
        syllabus_text = (
            "📚 *SILABUS & KURIKULUM LENGKAP SUHU ADS MASTERCLASS:*\n\n"
            "• *Modul 1:* Riset Winning Audience & Bedah Pixel Meta Ads\n"
            "• *Modul 2:* Struktur Campaign CBO vs ABO & Scaling Strategy\n"
            "• *Modul 3:* Funneling, Creative Hook & Copywriting Konversi Tinggi\n"
            "• *Bonus:* Template Dashboard Budgeting Notion + Grup Diskusi VIP\n\n"
            "🔥 *Investasi Promo:* Cuma *Rp149.000* (Akses Selamanya)\n\n"
            "Ketik *Beli* atau klik tombol di bawah untuk pembayaran QRIS."
        )
        await send_whatsapp_text(to_phone=from_phone, text=syllabus_text)
        return {"status": "success", "tenant": active_tenant, "reply": syllabus_text}

    # =========================================================================
    # MENU SELECTION (1, 2, 3)
    # =========================================================================
    if text_lower in _MENU_OPTION_MAP:
        selected_slug = _MENU_OPTION_MAP[text_lower]
        if clean_phone:
            user_tenant_sessions[clean_phone] = selected_slug
        
        greeting = DEMO_TENANT_GREETINGS.get(selected_slug, f"🎉 Anda kini terhubung dengan *{selected_slug}*.")

        if selected_slug == "suhu-ads-masterclass":
            buttons = [
                {"id": "btn_buy_now", "title": "💳 Beli & Bayar QRIS"},
                {"id": "btn_view_syllabus", "title": "📚 Cek Silabus Materi"},
                {"id": "btn_menu_reset", "title": "🔄 Menu Toko Lain"},
            ]
            if from_phone:
                try:
                    from app.services.whatsapp_service import send_whatsapp_buttons
                    await send_whatsapp_buttons(
                        to_phone=from_phone,
                        body_text=(
                            "Halo Kak! Selamat datang di *Suhu Ads Masterclass 2026* 🚀\n\n"
                            "Rahasia scale-up Meta Ads & optimasi konversi praktis untuk melipatgandakan profit bisnis.\n\n"
                            "🔥 *Promo Hari Ini:* Cuma *Rp149.000* (Diskon 50% dari ~Rp299.000~). Full akses video Google Drive selamanya + Template Budgeting."
                        ),
                        buttons=buttons,
                        footer_text="Pilih opsi di bawah untuk lanjut:",
                    )
                except Exception:
                    await send_whatsapp_text(to_phone=from_phone, text=greeting)
        elif from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=greeting)

        safe_log_to_supabase_messages(
            sender="bot",
            text=greeting,
            tenant_id=selected_slug,
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
        return {"status": "success", "tenant": selected_slug, "reply": greeting}

    # =========================================================================
    # TOP-LEVEL DEMO MENU
    # =========================================================================
    if text_lower in _MENU_TRIGGER_KEYWORDS or button_id == "btn_menu_reset":
        if from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=DEMO_MENU_TEXT)

        safe_log_to_supabase_messages(
            sender="bot",
            text=DEMO_MENU_TEXT,
            tenant_id="__MENU__",
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
        return {"status": "menu_dispatched", "tenant": "__MENU__", "reply": DEMO_MENU_TEXT}

    # =========================================================================
    # AI ENGINE ROUTING
    # =========================================================================
    tenant_slug, is_new_binding = resolve_dynamic_tenant_for_whatsapp(
        phone_id=phone_id,
        from_phone=from_phone,
        message_text=incoming_text,
    )
    if clean_phone:
        user_tenant_sessions[clean_phone] = tenant_slug

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

    if reply and from_phone:
        await send_whatsapp_text(to_phone=from_phone, text=reply)

    safe_log_to_supabase_messages(
        sender="bot",
        text=reply,
        tenant_id=tenant_slug,
        channel="whatsapp",
        user_phone=from_phone,
        user_name=contact_name,
    )

    return {"status": "success", "tenant": tenant_slug, "reply": reply}