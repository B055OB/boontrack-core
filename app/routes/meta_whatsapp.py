"""
app/routes/meta_whatsapp.py
FastAPI Router for Meta WhatsApp Cloud API Webhook with Deterministic Tenant Isolation & OnlineBoost Storefront.
"""

import os
import logging
import urllib.parse
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import JSONResponse

from app.services.whatsapp_service import (
    extract_meta_whatsapp_event,
    resolve_dynamic_tenant_for_whatsapp,
    reset_whatsapp_user_session,
    sanitize_whatsapp_message_text,
    send_whatsapp_text,
    send_whatsapp_buttons,
    send_whatsapp_image_link,
    send_whatsapp_tenant_catalog,
    user_tenant_sessions,
    user_session_states,
    user_phone_number_id_sessions,
    user_cart_sessions,
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
    os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_verify_secret"),
    os.getenv("META_WEBHOOK_VERIFY_TOKEN", "boontrack-secure-verify-token"),
    "boontrack_verify_secret",
    "boontrack-secure-verify-token",
    "boontrack_master_verify_token_2026",
    "om_budi_secure_token_2026",
    "boontrack_career_token",
]

_COMMERCE_DEMO_TRIGGERS = {"#reset", "reset", "menu", "#menu", "demo"}

_MENU_OPTION_MAP: Dict[str, str] = {
    "1": "ombudi",
    "ombudi": "ombudi",
    "om budi": "ombudi",
    "om-budi": "ombudi",
    "retail": "ombudi",
    "2": "growthplus",
    "growthplus": "growthplus",
    "growth+": "growthplus",
    "tier growth+": "growthplus",
    "3": "proscale",
    "proscale": "proscale",
    "tier proscale": "proscale",
    "4": "onlineboost",
    "onlineboost": "onlineboost",
    "digital": "onlineboost",
    "course": "onlineboost",
    "suhu-ads-masterclass": "onlineboost",
    "suhu ads": "onlineboost",
}


# =============================================================================
# 1. GET Handshake Verification (Meta Hub Challenge)
# =============================================================================

@meta_whatsapp_router.get("/api/v1/whatsapp/webhook", summary="Meta Webhook Verification")
@meta_whatsapp_router.get("/webhook/whatsapp", summary="Meta Webhook Verification Alias")
@meta_whatsapp_router.get("/api/whatsapp/webhook", summary="Meta Webhook Verification Alias 2")
async def verify_webhook_handshake(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "boontrack_verify_secret")
    mode = hub_mode or request.query_params.get("mode")
    token = hub_verify_token or request.query_params.get("token") or request.query_params.get("verify_token")
    challenge = hub_challenge or request.query_params.get("challenge")

    if mode == "subscribe" and (token == verify_token or token in VERIFY_TOKENS):
        logger.info("[META WA] Webhook handshake verified successfully.")
        return Response(content=str(challenge or ""), media_type="text/plain", status_code=200)

    logger.warning(f"[META WA] Handshake token mismatch: {token}")
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
        return JSONResponse(status_code=200, content={"status": "error", "message": "Invalid JSON format"})

    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        val = changes.get("value", {})
        if "statuses" in val and "messages" not in val:
            return JSONResponse(status_code=200, content={"status": "status_ignored"})
    except Exception:
        pass

    event = extract_meta_whatsapp_event(data)

    if event.get("is_status") or not event.get("is_message"):
        return JSONResponse(status_code=200, content={"status": "ignored"})

    from_phone = event.get("from_phone", "")
    incoming_text = (event.get("text") or "").strip()
    contact_name = event.get("contact_name") or "Kakak"
    clean_phone = normalize_phone_number(from_phone)
    button_id = str(event.get("button_id") or "").strip().lower()
    
    phone_id = str(event.get("phone_id") or "").strip()
    if not phone_id:
        phone_id = os.getenv("OM_BUDI_PHONE_NUMBER_ID", "1268977686299719")

    clean_text = incoming_text.strip().lower()
    text_lower = clean_text
    clean_btn = button_id

    if clean_phone and phone_id:
        user_phone_number_id_sessions[clean_phone] = phone_id

    # =========================================================================
    # P0 INTERCEPT: COMMAND #RESET / RESET / MENU UTAMA
    # =========================================================================
    if clean_text in ["#reset", "reset", "menu utama", "#menu", "menu", "demo"] or clean_btn in ["btn_menu_reset", "reset"]:
        logger.info(f"[META WA ROUTER] Reset command detected from {clean_phone}.")
        reset_whatsapp_user_session(clean_phone)
        if clean_phone:
            user_session_states[clean_phone] = "AWAITING_PORTAL_CHOICE"
            if phone_id:
                user_phone_number_id_sessions[clean_phone] = phone_id
        if from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=DEMO_MENU_TEXT, tenant_id="ombudi", phone_number_id=phone_id)
        safe_log_to_supabase_messages(
            sender="bot",
            text=DEMO_MENU_TEXT,
            tenant_id="__MENU__",
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
        return JSONResponse(status_code=200, content={"status": "menu_dispatched", "tenant": "__MENU__", "reply": DEMO_MENU_TEXT})

    # =========================================================================
    # P0 INTERCEPT: MENU SELECTION 1, 2, 3, 4
    # =========================================================================
    if clean_text in _MENU_OPTION_MAP or (user_session_states.get(clean_phone) == "AWAITING_PORTAL_CHOICE" and clean_text in _MENU_OPTION_MAP):
        selected_slug = _MENU_OPTION_MAP[clean_text]
        if clean_phone:
            user_tenant_sessions[clean_phone] = selected_slug
            user_session_states[clean_phone] = "ACTIVE"
            if phone_id:
                user_phone_number_id_sessions[clean_phone] = phone_id
        
        greeting = DEMO_TENANT_GREETINGS.get(selected_slug, f"🎉 Anda kini terhubung dengan *{selected_slug}*.")

        if selected_slug == "onlineboost":
            if from_phone:
                await send_whatsapp_tenant_catalog(
                    phone=from_phone,
                    tenant_slug="onlineboost",
                    tenant_id="ombudi",
                    phone_number_id=phone_id
                )
            safe_log_to_supabase_messages(
                sender="bot",
                text="[Katalog OnlineBoost Dispatched]",
                tenant_id="onlineboost",
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
            )
            return JSONResponse(status_code=200, content={"status": "success", "tenant": "onlineboost", "reply": "[Katalog OnlineBoost Dispatched]"})

        elif selected_slug == "ombudi":
            ombudi_buttons = [
                {"id": "menu_zoom_booster", "title": "🚀 Zoom Booster"},
                {"id": "menu_sedekah_berjamaah", "title": "🤲 Sedekah"},
                {"id": "menu_daftar_kelas", "title": "Daftar Kelas Online"}
            ]
            if from_phone:
                try:
                    await send_whatsapp_buttons(
                        to_phone=from_phone,
                        body_text=greeting,
                        buttons=ombudi_buttons,
                        footer_text="Pilih menu di bawah untuk lanjut:",
                        tenant_id="ombudi",
                        phone_number_id=phone_id,
                    )
                except Exception:
                    await send_whatsapp_text(to_phone=from_phone, text=greeting, tenant_id="ombudi", phone_number_id=phone_id)
            safe_log_to_supabase_messages(
                sender="bot",
                text=greeting,
                tenant_id="ombudi",
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
            )
            return JSONResponse(status_code=200, content={"status": "success", "tenant": "ombudi", "reply": greeting})

        elif selected_slug in ("growthplus", "proscale"):
            if from_phone:
                await send_whatsapp_text(to_phone=from_phone, text=greeting, tenant_id="ombudi", phone_number_id=phone_id)
            safe_log_to_supabase_messages(
                sender="bot",
                text=greeting,
                tenant_id=selected_slug,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
            )
            return JSONResponse(status_code=200, content={"status": "success", "tenant": selected_slug, "reply": greeting})

    # Resolusi Tenant Dinamis
    tenant_slug, is_new_bind = resolve_dynamic_tenant_for_whatsapp(
        phone_id=phone_id,
        from_phone=from_phone,
        message_text=incoming_text,
    )

    if tenant_slug in ("suhu-ads-masterclass", "suhu_ads"):
        tenant_slug = "onlineboost"

    # =========================================================================
    # JALUR PRODUKSI: CAREER ATAU OM BUDI LAMA
    # =========================================================================
    if tenant_slug in ("onlineboost", "growthplus", "proscale"):
        pass
    elif tenant_slug in ("boontrack-career", "boontrack_career", "career"):
        reply = await process_incoming_message(
            tenant_slug=tenant_slug,
            message=incoming_text,
            user_phone=from_phone,
            user_name=contact_name,
            button_id=event.get("button_id"),
        )
        reply = sanitize_whatsapp_message_text(reply)
        if reply and from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=reply, tenant_id=tenant_slug, phone_number_id=phone_id)

        safe_log_to_supabase_messages(
            sender="bot",
            text=reply or "",
            tenant_id=tenant_slug,
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
        return JSONResponse(status_code=200, content={"status": "success", "tenant": tenant_slug, "reply": reply})

    elif tenant_slug in ("ombudi", "om_budi", "om-budi"):
        from app.tenants.om_budi.service import om_budi_service
        res = await om_budi_service.handle_incoming_message(
            phone_number=from_phone,
            message_text=incoming_text,
            button_id=event.get("button_id"),
            user_name=contact_name,
        )
        reply_text = sanitize_whatsapp_message_text(res.get("reply", ""))
        buttons = res.get("buttons") or res.get("nav_buttons")
        if buttons and len(buttons) <= 3 and len(reply_text) <= 1000:
            try:
                await send_whatsapp_buttons(
                    to_phone=from_phone,
                    body_text=reply_text,
                    buttons=buttons,
                    tenant_id="ombudi",
                    phone_number_id=phone_id,
                )
            except Exception:
                await send_whatsapp_text(to_phone=from_phone, text=reply_text, tenant_id="ombudi", phone_number_id=phone_id)
        elif reply_text and from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=reply_text, tenant_id="ombudi", phone_number_id=phone_id)

        safe_log_to_supabase_messages(
            sender="bot",
            text=reply_text or "",
            tenant_id="ombudi",
            channel="whatsapp",
            user_phone=from_phone,
            user_name=contact_name,
        )
        return JSONResponse(status_code=200, content={"status": "success", "tenant": "ombudi", "reply": reply_text})

    # =========================================================================
    # JALUR TOKO DEMO (ONLINEBOOST, GROWTH+, PROSCALE)
    # =========================================================================
    if tenant_slug == "__MENU__" or clean_text in _COMMERCE_DEMO_TRIGGERS or button_id == "btn_menu_reset":
        if clean_phone:
            reset_whatsapp_user_session(clean_phone)
        if from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=DEMO_MENU_TEXT, tenant_id="ombudi", phone_number_id=phone_id)
        return JSONResponse(status_code=200, content={"status": "menu_dispatched", "tenant": "__MENU__", "reply": DEMO_MENU_TEXT})

    active_tenant = user_tenant_sessions.get(clean_phone) or "onlineboost"

    # -------------------------------------------------------------------------
    # 1. FAST-TRACK QRIS CHECKOUT
    # -------------------------------------------------------------------------
    is_qris_buy_action = (
        button_id in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris", "btn_checkout_cart"}
        or "beli & bayar qris" in text_lower
        or "bayar qris" in text_lower
        or text_lower in {"beli", "beli 1", "bayar"}
        or is_closing_buy_intent(incoming_text, button_id)
    )

    if is_qris_buy_action and active_tenant not in ("bale_pananggeuhan", "pelayanan_publik"):
        try:
            reply, invoice, _ = await generate_fast_track_checkout_response(
                tenant_slug=active_tenant,
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
                    tenant_id="ombudi",
                    phone_number_id=phone_id,
                )
                if link_resp and getattr(link_resp, "status_code", 200) in (200, 201):
                    image_delivered = True
            except Exception as err:
                logger.warning(f"[WA IMAGE DISPATCH ERROR] {err}")

            if not image_delivered and from_phone:
                await send_whatsapp_text(to_phone=from_phone, text=reply, tenant_id="ombudi", phone_number_id=phone_id)

            safe_log_to_supabase_messages(
                sender="bot",
                text=f"[Kirim QRIS {invoice.get('external_id')}] {reply}",
                tenant_id=active_tenant,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
            )
            return JSONResponse(status_code=200, content={
                "status": "qris_dispatched",
                "tenant": active_tenant,
                "invoice_id": invoice.get("external_id"),
            })
        except Exception as e:
            logger.error(f"[FAST TRACK CHECKOUT ERROR] {e}")
            fallback_msg = "Maaf, sistem sedang memproses antrean invoice QRIS. Silakan ketik *Beli* sekali lagi ya Kak! 🙏"
            if from_phone:
                await send_whatsapp_text(to_phone=from_phone, text=fallback_msg, tenant_id="ombudi", phone_number_id=phone_id)
            return JSONResponse(status_code=200, content={"status": "error", "tenant": active_tenant, "error": str(e)})

    # -------------------------------------------------------------------------
    # 2. HANDLER TOMBOL INTERAKTIF 1, 2, 3
    # -------------------------------------------------------------------------

    # Tombol 1: Daftar / Rincian Produk
    if button_id in {"btn_view_service", "btn_view_catalog"} or "daftar produk" in text_lower or text_lower == "katalog":
        if from_phone:
            await send_whatsapp_tenant_catalog(
                phone=from_phone,
                tenant_slug=active_tenant,
                tenant_id="ombudi",
                phone_number_id=phone_id,
            )
        return JSONResponse(status_code=200, content={"status": "success", "tenant": active_tenant, "action": "view_catalog"})

    # Tombol 2: Keranjang Belanja
    if button_id in {"btn_view_cart", "btn_cart"} or "keranjang" in text_lower:
        items = user_cart_sessions.get(clean_phone, [])
        if not items:
            cart_msg = (
                "🛒 *Keranjang Belanja Anda Kosong*\n\n"
                "Silakan pilih produk dari katalog terlebih dahulu dengan mengetik *Beli* atau klik tombol di bawah:"
            )
            cart_empty_btns = [
                {"id": "btn_view_service", "title": "🛍️ Daftar Produk"},
                {"id": "btn_ask_ai", "title": "💬 Tanya Produk (AI)"},
            ]
            if from_phone:
                await send_whatsapp_buttons(
                    to_phone=from_phone,
                    body_text=cart_msg,
                    buttons=cart_empty_btns,
                    tenant_id="ombudi",
                    phone_number_id=phone_id,
                )
            return JSONResponse(status_code=200, content={"status": "success", "tenant": active_tenant, "action": "empty_cart"})

        item_lines = [
            f"• *{it.get('title') or it.get('name')}* (Rp{int(float(it.get('promo_price') or it.get('price') or 0)):,})".replace(",", ".")
            for it in items
        ]
        total_bill = sum(int(float(it.get('promo_price') or it.get('price') or 0)) for it in items)
        cart_summary = (
            f"🛒 *KERANJANG BELANJA ANDA ({len(items)} Item)*\n\n"
            + "\n".join(item_lines)
            + f"\n\n💰 *Total:* Rp{total_bill:,}".replace(",", ".")
            + "\n\nKetik *Beli* untuk langsung bayar via Dynamic QRIS."
        )
        cart_filled_btns = [
            {"id": "btn_buy_now", "title": "💳 Bayar QRIS"},
            {"id": "btn_view_service", "title": "🛍️ Tambah Produk"},
        ]
        if from_phone:
            await send_whatsapp_buttons(
                to_phone=from_phone,
                body_text=cart_summary,
                buttons=cart_filled_btns,
                tenant_id="ombudi",
                phone_number_id=phone_id,
            )
        return JSONResponse(status_code=200, content={"status": "success", "tenant": active_tenant, "action": "view_cart"})

    # Tombol 3: Tanya Produk (LLM Contextual Agent)
    if button_id in {"btn_ask_ai", "ask_ai"} or "tanya produk" in text_lower:
        prompt_intro = (
            "🤖 *BoonPilot AI Assistant*\n\n"
            f"Ada yang ingin ditanyakan seputar materi ecourse atau paket layanan di *{active_tenant.upper()}*?\n\n"
            "Ketik langsung pertanyaan Kakak (misal: _'Apa materi yang dipelajari di Ecourse CPM?'_), asisten AI kami siap menjawab! ✨"
        )
        if from_phone:
            await send_whatsapp_text(
                to_phone=from_phone,
                text=prompt_intro,
                tenant_id="ombudi",
                phone_number_id=phone_id,
            )
        return JSONResponse(status_code=200, content={"status": "success", "tenant": active_tenant, "action": "ask_ai_prompt"})

    # -------------------------------------------------------------------------
    # 3. CONVERSATIONAL COMMERCE AI (FALLBACK LLM DENGAN DATA TOKO)
    # -------------------------------------------------------------------------
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

    reply = sanitize_whatsapp_message_text(reply)

    if reply and from_phone:
        await send_whatsapp_text(to_phone=from_phone, text=reply, tenant_id="ombudi", phone_number_id=phone_id)

    safe_log_to_supabase_messages(
        sender="bot",
        text=reply or "",
        tenant_id=active_tenant,
        channel="whatsapp",
        user_phone=from_phone,
        user_name=contact_name,
    )

    return JSONResponse(status_code=200, content={"status": "success", "tenant": active_tenant, "reply": reply})