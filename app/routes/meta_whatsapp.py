"""app/routes/meta_whatsapp.py
FastAPI Router for Meta WhatsApp Cloud API Webhook with Deterministic Tenant Isolation.
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
    send_whatsapp_image_link,
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

_COMMERCE_DEMO_TRIGGERS = {"#reset", "#menu", "menu toko"}

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
    button_id = str(event.get("button_id") or "").strip().lower()
    phone_id = str(event.get("phone_id") or "").strip()
    text_lower = incoming_text.lower()

    # 1. Resolusi Tenant Dinamis Berdasarkan Phone Number ID & Konfigurasi Resmi
    tenant_slug, _ = resolve_dynamic_tenant_for_whatsapp(
        phone_id=phone_id,
        from_phone=from_phone,
        message_text=incoming_text,
    )

    # =========================================================================
    # JALUR A: PRODUKSI AKTIF (Career Assistant, Om Budi, Bale Pananggeuhan)
    # Diproses murni oleh Agent AI tanpa terpengaruh flow promo QRIS Masterclass
    # =========================================================================
    if tenant_slug in ("boontrack_career", "career", "om_budi", "ombudi", "bale_pananggeuhan"):
        reply = await process_incoming_message(
            tenant_slug=tenant_slug,
            message=incoming_text,
            user_phone=from_phone,
            user_name=contact_name,
            button_id=event.get("button_id"),
        )
        if reply and from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=reply)

        try:
            safe_log_to_supabase_messages(
                sender="bot",
                text=reply or "",
                tenant_id=tenant_slug,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
            )
        except Exception:
            pass

        return {"status": "success", "tenant": tenant_slug, "reply": reply}

    # =========================================================================
    # JALUR B: COMMERCE / DIGITAL COURSE (Suhu Ads Masterclass)
    # =========================================================================
    
    # 1. Menu Reset/Switcher (Hanya jika secara eksplisit dipanggil)
    if text_lower in _COMMERCE_DEMO_TRIGGERS or button_id == "btn_menu_reset":
        if from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=DEMO_MENU_TEXT)
        return {"status": "menu_dispatched", "tenant": "__MENU__"}

    # 2. Fast-Track QRIS Closing Flow
    is_qris_buy_action = (
        button_id in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris"}
        or "beli & bayar qris" in text_lower
        or "bayar qris" in text_lower
        or text_lower == "beli"
        or is_closing_buy_intent(incoming_text, button_id)
    )

    if is_qris_buy_action:
        try:
            reply, invoice, _ = await generate_fast_track_checkout_response(
                tenant_slug=tenant_slug,
                from_phone=from_phone,
                contact_name=contact_name,
            )

            qr_string = invoice.get("qr_string", "")
            qr_code_url = (
                invoice.get("qr_code_url")
                or f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&format=png&data={urllib.parse.quote(qr_string)}"
            )

            # Coba kirim gambar QRIS ke WhatsApp
            image_delivered = False
            try:
                link_resp = await send_whatsapp_image_link(
                    to_phone=from_phone,
                    image_url=qr_code_url,
                    caption=reply,
                    tenant_id=tenant_slug,
                )
                if link_resp and getattr(link_resp, "status_code", 200) in (200, 201):
                    image_delivered = True
            except Exception as err:
                logger.warning(f"[WA IMAGE DISPATCH ERROR] {err}")

            # Fallback kirim text jika gambar tertahan
            if not image_delivered and from_phone:
                await send_whatsapp_text(to_phone=from_phone, text=reply)

            try:
                safe_log_to_supabase_messages(
                    sender="bot",
                    text=f"[Kirim QRIS {invoice.get('external_id')}] {reply}",
                    tenant_id=tenant_slug,
                    channel="whatsapp",
                    user_phone=from_phone,
                    user_name=contact_name,
                )
            except Exception:
                pass

            return {
                "status": "qris_dispatched",
                "tenant": tenant_slug,
                "invoice_id": invoice.get("external_id"),
            }
        except Exception as e:
            logger.error(f"[FAST TRACK CHECKOUT ERROR] {e}")

    # 3. Silabus Kurikulum Action
    if button_id == "btn_view_syllabus" or "silabus" in text_lower:
        syllabus_text = (
            "📚 *SILABUS & KURIKULUM LENGKAP SUHU ADS MASTERCLASS:*\n\n"
            "• *Modul 1:* Riset Winning Audience & Bedah Pixel Meta Ads\n"
            "• *Modul 2:* Struktur Campaign CBO vs ABO & Scaling Strategy\n"
            "• *Modul 3:* Funneling, Creative Hook & Copywriting Konversi Tinggi\n"
            "• *Bonus:* Template Dashboard Budgeting Notion + Grup Diskusi VIP\n\n"
            "🔥 *Investasi Promo:* Cuma *Rp149.000* (Akses Selamanya)\n\n"
            "Ketik *Beli* untuk langsung membuat kode bayar QRIS."
        )
        if from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=syllabus_text)
        return {"status": "success", "tenant": tenant_slug, "reply": syllabus_text}

    # 4. Fallback AI Response
    reply = await commerce_ai_engine.generate_commerce_response(
        tenant_slug=tenant_slug,
        user_message=incoming_text,
        user_phone=from_phone,
        user_name=contact_name,
        button_id=event.get("button_id"),
    )
    if not reply:
        reply = await process_incoming_message(
            tenant_slug=tenant_slug,
            message=incoming_text,
            user_phone=from_phone,
            user_name=contact_name,
            button_id=event.get("button_id"),
        )

    if reply and from_phone:
        await send_whatsapp_text(to_phone=from_phone, text=reply)

    try:
        safe_log_to_supabase_messages(
            sender="bot",
            text=reply or "",
            tenant_id=tenant_slug,
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
    except Exception:
        pass

    return {"status": "success", "tenant": tenant_slug, "reply": reply}