"""
app/routes/meta_whatsapp.py
FastAPI Router for Meta WhatsApp Cloud API Webhook with Deterministic Tenant Isolation & OnlineBoost Storefront.
"""

import os
import logging
import urllib.parse
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Response, Query

from app.services.whatsapp_service import (
    extract_meta_whatsapp_event,
    resolve_dynamic_tenant_for_whatsapp,
    send_whatsapp_text,
    send_whatsapp_buttons,
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
from app.services.agent_service import process_incoming_message

logger = logging.getLogger("META_WHATSAPP_ROUTER")

meta_whatsapp_router = APIRouter(tags=["Meta WhatsApp Webhook"])
router = meta_whatsapp_router

VERIFY_TOKENS = [
    os.getenv("META_WEBHOOK_VERIFY_TOKEN", "boontrack-secure-verify-token"),
    os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_master_verify_token_2026"),
    "boontrack-secure-verify-token",
    "boontrack_master_verify_token_2026",
    "om_budi_secure_token_2026",
    "boontrack_career_token",
]

_COMMERCE_DEMO_TRIGGERS = {"#reset", "reset", "menu", "#menu", "demo"}

_MENU_OPTION_MAP: Dict[str, str] = {
    "1": "bale_pananggeuhan",
    "2": "atmosfitnes",
    "3": "onlineboost",
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
# 2. POST Message Ingestion & Safe Multi-Tenant Routing
# =============================================================================

@meta_whatsapp_router.post("/api/v1/whatsapp/webhook", summary="Meta WhatsApp Inbound Receiver")
@meta_whatsapp_router.post("/webhook/whatsapp", summary="Meta WhatsApp Inbound Receiver Alias")
@meta_whatsapp_router.post("/api/whatsapp/webhook", summary="Meta WhatsApp Inbound Receiver Alias 2")
async def handle_whatsapp_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON format"}

    # Guard 1: Filter status updates (sent, delivered, read) agar tidak looping
    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        val = changes.get("value", {})
        if "statuses" in val and "messages" not in val:
            return {"status": "status_ignored"}
    except Exception:
        pass

    event = extract_meta_whatsapp_event(data)

    if event.get("is_status") or not event.get("is_message"):
        return {"status": "ignored"}

    from_phone = event.get("from_phone", "")
    incoming_text = (event.get("text") or "").strip()
    contact_name = event.get("contact_name") or "Kakak"
    clean_phone = normalize_phone_number(from_phone)
    button_id = str(event.get("button_id") or "").strip().lower()
    phone_id = str(event.get("phone_id") or "").strip()
    text_lower = incoming_text.lower()

    # Resolusi Tenant Dinamis
    tenant_slug, is_new_bind = resolve_dynamic_tenant_for_whatsapp(
        phone_id=phone_id,
        from_phone=from_phone,
        message_text=incoming_text,
    )

    if tenant_slug in ("suhu-ads-masterclass", "suhu_ads"):
        tenant_slug = "onlineboost"

    # =========================================================================
    # JALUR A: PRODUKSI AKTIF (Career Assistant & Admin Om Budi)
    # =========================================================================
    if tenant_slug in ("boontrack-career", "boontrack_career", "career", "om_budi", "om-budi", "ombudi"):
        reply = await process_incoming_message(
            tenant_slug=tenant_slug,
            message=incoming_text,
            user_phone=from_phone,
            user_name=contact_name,
            button_id=event.get("button_id"),
        )
        if reply and from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=reply, tenant_id=tenant_slug)

        safe_log_to_supabase_messages(
            sender="bot",
            text=reply or "",
            tenant_id=tenant_slug,
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
        return {"status": "success", "tenant": tenant_slug, "reply": reply}

    # =========================================================================
    # JALUR B: TOKO DEMO (Menu Switcher 1, 2, 3)
    # =========================================================================

    # 1. Reset ke Menu Utama
    if text_lower in _COMMERCE_DEMO_TRIGGERS or button_id == "btn_menu_reset":
        if clean_phone:
            user_tenant_sessions.pop(clean_phone, None)
        if from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=DEMO_MENU_TEXT)
        return {"status": "menu_dispatched", "tenant": "__MENU__"}

    # 2. Pilihan Menu 1, 2, 3
    if text_lower in _MENU_OPTION_MAP:
        selected_slug = _MENU_OPTION_MAP[text_lower]
        if clean_phone:
            user_tenant_sessions[clean_phone] = selected_slug
        
        greeting = DEMO_TENANT_GREETINGS.get(selected_slug, f"🎉 Anda kini terhubung dengan *{selected_slug}*.")

        if selected_slug == "onlineboost":
            buttons = [
                {"id": "btn_buy_now", "title": "💳 Beli & Bayar QRIS"},
                {"id": "btn_view_service", "title": "🚀 Info Layanan & Modul"},
                {"id": "btn_menu_reset", "title": "🔄 Ganti Demo Toko"},
            ]
            if from_phone:
                try:
                    await send_whatsapp_buttons(
                        to_phone=from_phone,
                        body_text=(
                            "Halo Kak! Selamat datang di *OnlineBoost Official Store* 🚀\n\n"
                            "Solusi praktis scale-up campaign Meta & Google Ads, optimasi ROAS, dan landing page konversi tinggi.\n\n"
                            "🔥 *Promo Hari Ini:* Starter Kit Paid Traffic cuma *Rp99.000* (Diskon 50%). Sudah termasuk modul video HD + Template Kalkulator ROI Spreadsheet."
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

    # Ambil tenant aktif sesi saat ini
    active_tenant = user_tenant_sessions.get(clean_phone, "onlineboost")

    # 3. Fast-Track QRIS Closing (Tombol Beli / Kata Kunci Pembelian)
    is_qris_buy_action = (
        button_id in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris"}
        or "beli & bayar qris" in text_lower
        or "bayar qris" in text_lower
        or text_lower == "beli"
        or is_closing_buy_intent(incoming_text, button_id)
    )

    if is_qris_buy_action and active_tenant not in ("bale_pananggeuhan", "pelayanan_publik"):
        try:
            reply, invoice, _ = await generate_fast_track_checkout_response(
                tenant_slug="onlineboost",
                from_phone=from_phone,
                contact_name=contact_name,
            )

            qr_string = invoice.get("qr_string", "")
            qr_code_url = (
                invoice.get("qr_code_url")
                or f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&format=png&data={urllib.parse.quote(qr_string)}"
            )

            image_delivered = False
            try:
                link_resp = await send_whatsapp_image_link(
                    to_phone=from_phone,
                    image_url=qr_code_url,
                    caption=reply,
                    tenant_id="onlineboost",
                )
                if link_resp and getattr(link_resp, "status_code", 200) in (200, 201):
                    image_delivered = True
            except Exception as err:
                logger.warning(f"[WA IMAGE DISPATCH ERROR] {err}")

            if not image_delivered and from_phone:
                await send_whatsapp_text(to_phone=from_phone, text=reply)

            safe_log_to_supabase_messages(
                sender="bot",
                text=f"[Kirim QRIS {invoice.get('external_id')}] {reply}",
                tenant_id="onlineboost",
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
            )
            return {
                "status": "qris_dispatched",
                "tenant": "onlineboost",
                "invoice_id": invoice.get("external_id"),
            }
        except Exception as e:
            logger.error(f"[FAST TRACK CHECKOUT ERROR] {e}")

    # 4. Info Layanan Action
    if button_id == "btn_view_service" or "layanan" in text_lower or "paket" in text_lower or "silabus" in text_lower:
        layanan_text = (
            "🚀 *PAKET SCALE-UP DIGITAL MARKETING ONLINEBOOST:*\n\n"
            "• *Modul 1:* Setup Pixel & Riset Winning Audience Meta/TikTok Ads\n"
            "• *Modul 2:* Strategi Scaling Budget Campaign CBO vs ABO\n"
            "• *Modul 3:* High-Converting Funneling & Copywriting Konversi\n"
            "• *Bonus:* Template Spreadsheet Kalkulator ROI Iklan + Diskusi VIP\n\n"
            "🔥 *Promo Starter Kit:* Cuma *Rp99.000* (Akses Selamanya)\n\n"
            "Ketik *Beli* atau klik tombol di atas untuk pembayaran QRIS instan."
        )
        if from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=layanan_text)
        return {"status": "success", "tenant": "onlineboost", "reply": layanan_text}

    # 5. Fallback AI Response
    reply = await commerce_ai_engine.generate_commerce_response(
        tenant_slug=active_tenant,
        user_message=incoming_text,
        user_phone=from_phone,
        user_name=contact_name,
        button_id=event.get("button_id"),
    )
    if not reply:
        reply = await process_incoming_message(
            tenant_slug=active_tenant,
            message=incoming_text,
            user_phone=from_phone,
            user_name=contact_name,
            button_id=event.get("button_id"),
        )

    if reply and from_phone:
        await send_whatsapp_text(to_phone=from_phone, text=reply)

    safe_log_to_supabase_messages(
        sender="bot",
        text=reply or "",
        tenant_id=active_tenant,
        channel="whatsapp",
        user_phone=from_phone,
        user_name=contact_name,
    )

    return {"status": "success", "tenant": active_tenant, "reply": reply}