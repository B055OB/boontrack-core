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
4. Direct Fast-Track QRIS Native Image Dispatch for checkout intents.
5. Injects real commerce catalog and negative boundaries via CommerceAIEngine.
"""

import os
import logging
import re
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Response, Query, status

from app.services.whatsapp_service import (
    extract_meta_whatsapp_event,
    resolve_dynamic_tenant_for_whatsapp,
    send_whatsapp_text,
    send_whatsapp_image,
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
    2. INTERCEPTOR FOR FAST-TRACK QRIS: Directly generates and sends Native QR Image.
    3. TOP-LEVEL INTERCEPTOR: greetings / #reset / no active session -> send Demo Menu.
    4. Menu Option Selection: '1', '2', '3' -> lock session + send greeting.
    5. Onboarding announcement: 'saya baru saja mendaftar toko [slug]' -> bind session.
    6. Active session -> route to tenant AI engine.
    """
    body_raw = "{}"
    try:
        data = await request.json()
        body_raw = str(data)
    except Exception:
        return {"status": "error", "message": "Invalid JSON format"}

    print(f"📥 [WHATSAPP EVENT RECEIVED] Raw: {body_raw[:600]}", flush=True)

    event = extract_meta_whatsapp_event(data)

    # 1. Ignore delivery / read statuses
    if event.get("is_status"):
        return {"status": "status_ignored"}

    if not event.get("is_message"):
        print(f"🔕 [WHATSAPP EVENT IGNORED] Not a message. Keys: {list(data.keys())}", flush=True)
        return {"status": "ignored"}

    from_phone = event.get("from_phone", "")
    incoming_text = (event.get("text") or "").strip()
    contact_name = event.get("contact_name") or "Kakak"
    clean_phone = normalize_phone_number(from_phone)
    text_lower = incoming_text.lower()
    button_id = str(event.get("button_id") or "").strip().lower()
    phone_id = event.get("phone_id", "")

    print(
        f"🎯 [PARSED ACTION] sender={from_phone} | msg_type={event.get('msg_type')} "
        f"| text={incoming_text!r} | button_id={button_id!r}",
        flush=True
    )

    # Resolve active tenant for sender
    active_tenant = user_tenant_sessions.get(clean_phone) or "suhu-ads-masterclass"

    # =========================================================================
    # FAST-TRACK QRIS INTENT INTERCEPTOR (Highest Priority for Purchase Flow)
    # =========================================================================
    is_qris_buy_action = (
        button_id in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris"}
        or "beli & bayar qris" in text_lower
        or "bayar qris" in text_lower
        or is_closing_buy_intent(incoming_text, button_id)
    )

    if is_qris_buy_action and active_tenant not in ("bale_pananggeuhan", "bale-pananggeuhan", "pelayanan_publik"):
        print(f"🛒 [FAST-TRACK] Direct QRIS Intent detected from {from_phone} on tenant '{active_tenant}'", flush=True)
        logger.info(f"[META WA FAST-TRACK] Direct QRIS Buy action from {from_phone} on tenant '{active_tenant}'")

        reply, invoice, qr_bytes = await generate_fast_track_checkout_response(
            tenant_slug=active_tenant,
            from_phone=from_phone,
            contact_name=contact_name,
        )

        image_delivered = False
        qr_code_url = invoice.get("qr_code_url")

        # 1. Dispatch Native Image via Binary Bytes Upload to Meta /media
        if qr_bytes:
            try:
                print(f"📸 [MEDIA UPLOAD] Dispatching {len(qr_bytes)} bytes PNG to Meta API for {from_phone}", flush=True)
                img_resp = await send_whatsapp_image(
                    to_phone=from_phone,
                    image_path_or_bytes=qr_bytes,
                    caption=reply,
                    tenant_id=active_tenant,
                )
                if img_resp and not (isinstance(img_resp, dict) and img_resp.get("status") == "failed"):
                    image_delivered = True
                    print(f"✅ [MEDIA SENT] QRIS image delivered successfully to {from_phone}", flush=True)
            except Exception as err:
                print(f"❌ [MEDIA BYTES EXCEPTION] {err}", flush=True)
                logger.warning(f"[META WA Image Send Error] {err}")

        # 2. Dispatch via Direct Public Image URL Link Fallback
        if not image_delivered and qr_code_url:
            try:
                print(f"🔗 [MEDIA URL FALLBACK] Sending QRIS via Image URL Link: {qr_code_url}", flush=True)
                link_resp = await send_whatsapp_image_link(
                    to_phone=from_phone,
                    image_url=qr_code_url,
                    caption=reply,
                    tenant_id=active_tenant,
                )
                if link_resp:
                    image_delivered = True
                    print(f"✅ [MEDIA LINK SENT] Delivered via Public URL to {from_phone}", flush=True)
            except Exception as link_err:
                print(f"❌ [MEDIA LINK EXCEPTION] {link_err}", flush=True)

        # 3. Fallback to Detailed Text Message
        if not image_delivered:
            print(f"📩 [TEXT FALLBACK] Sending invoice details as plain text", flush=True)
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

    # Pre-check: Is this an onboarding announcement?
    _is_onboarding_msg = bool(
        re.search(
            r"saya\s+baru\s+(?:saja\s+)?(?:mendaftar|daftar)\s+toko\s+[a-zA-Z0-9\-_]+",
            incoming_text,
            re.IGNORECASE,
        )
        or re.search(r"toko\s*:\s*[a-zA-Z0-9\-_]+", incoming_text, re.IGNORECASE)
    )

    # =========================================================================
    # 2. TOP-LEVEL DEMO MENU INTERCEPTOR
    # =========================================================================
    _is_keyword_trigger = text_lower in _MENU_TRIGGER_KEYWORDS or button_id == "btn_menu_reset"
    _has_active_session = bool(clean_phone and clean_phone in user_tenant_sessions)

    if (not _is_onboarding_msg) and (_is_keyword_trigger or not _has_active_session):
        if clean_phone:
            user_tenant_sessions.pop(clean_phone, None)

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
                except Exception as err:
                    logger.warning(f"[META WA Buttons Send Warning] {err}")
                    await send_whatsapp_text(to_phone=from_phone, text=greeting)
        elif from_phone:
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
    # 4. View Syllabus Action
    # =========================================================================
    if button_id == "btn_view_syllabus" or "silabus" in text_lower:
        syllabus_text = (
            "📚 *SILABUS & KURIKULUM LENGKAP SUHU ADS MASTERCLASS:*\n\n"
            "• *Modul 1:* Riset Winning Audience & Bedah Pixel Meta Ads (Event tracking, Custom & Lookalike Audience, CAPI setup)\n"
            "• *Modul 2:* Struktur Campaign CBO vs ABO & Scaling Strategy (Budgeting & Ad Sets, Horizontal & Vertical Scaling)\n"
            "• *Modul 3:* Funneling, Creative Hook & Copywriting Konversi Tinggi (Video hooks, AIDA framework, LP Optimization)\n"
            "• *Bonus:* Template Dashboard Budgeting Notion & Akses Grup Diskusi Telegram VIP\n\n"
            "🔥 *Investasi Promo:* Cuma *Rp149.000* (Akses Selamanya + Google Drive Update)\n\n"
            "Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
        )
        await send_whatsapp_text(to_phone=from_phone, text=syllabus_text)
        return {"status": "success", "tenant": active_tenant, "reply": syllabus_text}

    # =========================================================================
    # 5. Normal Message Pipeline: Resolve tenant + AI Engine
    # =========================================================================
    tenant_slug, is_new_binding = resolve_dynamic_tenant_for_whatsapp(
        phone_id=phone_id,
        from_phone=from_phone,
        message_text=incoming_text,
    )
    if clean_phone:
        user_tenant_sessions[clean_phone] = tenant_slug

    details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
    store_name = details.get("tenant", {}).get("name", tenant_slug) if details else tenant_slug

    if is_new_binding and _is_onboarding_msg:
        reply = (
            f"🎉 *Selamat Datang di {store_name}!* 🚀\n\n"
            f"Nomor WhatsApp Kakak (*{contact_name}*) kini resmi terhubung dengan asisten toko *{store_name}*.\n\n"
            f"Ada yang bisa kami bantu seputar produk atau promo hari ini?"
        )
    else:
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