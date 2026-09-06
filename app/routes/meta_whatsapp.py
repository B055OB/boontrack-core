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
    get_tenant_products_from_db,
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
from app.repositories.session_repository import SessionRepository
from app.modules.conversation import (
    load_customer_state,
    dump_customer_state,
    extract_signals,
    determine_strategy,
    get_system_prompt_for_mode,
    validate_action,
    TenantDBAdapter,
)

logger = logging.getLogger("META_WHATSAPP_ROUTER")

_conversation_session_repo = SessionRepository()


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
    # Inisialisasi default button untuk mencegah UnboundLocalError
    button_id = ""
    clean_btn = ""
    raw_msg = event.get("raw_msg") or {}
    if event.get("button_id"):
        button_id = str(event.get("button_id") or "").strip()
        clean_btn = button_id.lower()
    elif raw_msg.get("type") == "interactive":
        interactive = raw_msg.get("interactive", {})
        button_reply = interactive.get("button_reply", {})
        button_id = str(button_reply.get("id", "")).strip()
        clean_btn = button_id.lower()
    elif raw_msg.get("type") == "button":
        button_id = str(raw_msg.get("button", {}).get("payload", "")).strip()
        clean_btn = button_id.lower()
    
    phone_id = str(event.get("phone_id") or "").strip()
    if not phone_id:
        phone_id = os.getenv("OM_BUDI_PHONE_NUMBER_ID", "1268977686299719")

    clean_text = incoming_text.strip().lower()
    text_lower = clean_text

    if clean_phone and phone_id:
        user_phone_number_id_sessions[clean_phone] = phone_id

    career_phone_id = os.getenv("CAREER_PHONE_NUMBER_ID", "1340866379104241")
    is_career_phone = (phone_id == "1340866379104241" or phone_id == career_phone_id)

    # =========================================================================
    # P0 INTERCEPT: COMMAND #RESET / RESET / MENU UTAMA
    # =========================================================================
    import re
    clean_kw = re.sub(r"[^\w#]", "", clean_text)
    is_explicit_reset = (
        clean_kw in ["#reset", "reset"]
        or clean_text.startswith("#reset")
        or clean_text.startswith("# reset")
        or "#reset" in clean_text
    )
    is_reset = is_explicit_reset if is_career_phone else (
        is_explicit_reset
        or clean_kw in ["reset", "menu", "demo"]
        or clean_text in ["#reset", "reset", "menu utama", "#menu", "menu", "demo", "# reset", "start", "#start"]
        or clean_btn in ["btn_menu_reset", "reset"]
    )

    if is_reset:
        logger.info(f"[META WA ROUTER] Reset command detected from {clean_phone} (is_career={is_career_phone}).")
        reset_whatsapp_user_session(clean_phone)
        if from_phone:
            reset_whatsapp_user_session(from_phone)

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
                await send_whatsapp_tenant_catalog(from_phone, "onlineboost")
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
    elif tenant_slug in ("boontrack-career", "boontrack_career", "career") or (is_career_phone and user_tenant_sessions.get(clean_phone) not in ("onlineboost", "growthplus", "proscale")):
        from app.tenants.career.service import career_service
        msg_type = event.get("msg_type", "text")
        if msg_type == "image":
            await career_service.handle_image(
                sender_wa_id=from_phone,
                display_name=contact_name,
                media_id=event.get("media_id")
            )
            return JSONResponse(status_code=200, content={"status": "success", "tenant": "boontrack-career", "reply": "Career image handled"})
        elif msg_type == "document":
            await career_service.handle_document(
                sender_wa_id=from_phone,
                display_name=contact_name,
                media_id=event.get("media_id"),
                filename=event.get("media_filename") or "document.pdf"
            )
            return JSONResponse(status_code=200, content={"status": "success", "tenant": "boontrack-career", "reply": "Career document handled"})
        else:
            await career_service.handle_text_or_button(
                sender_wa_id=from_phone,
                display_name=contact_name,
                user_text=incoming_text,
                button_id=event.get("button_id") or ""
            )
            return JSONResponse(status_code=200, content={"status": "success", "tenant": "boontrack-career", "reply": "Career message handled"})

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

            try:
                session_key = f"{active_tenant}:{clean_phone}"
                wa_session = await _conversation_session_repo.get_or_create(user_id=session_key, channel="whatsapp")
                c_state = load_customer_state(session_id=clean_phone, tenant_id=active_tenant, raw_context=wa_session.context_json or {})
                c_state.stage = "CLOSED"
                wa_session.context_json = dump_customer_state(c_state, wa_session.context_json or {})
                await _conversation_session_repo.save(wa_session)
            except Exception as se:
                logger.debug(f"[SESSION SAVE ERROR] {se}")

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
    if button_id in {"btn_view_service", "btn_catalog", "btn_view_catalog"} or "daftar produk" in text_lower or text_lower == "katalog":
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
    # 3. 3-LAYER CONVERSATIONAL COMMERCE ENGINE (LAYER 1 -> 2 -> 3 + VALIDATOR)
    # -------------------------------------------------------------------------
    session_key = f"{active_tenant}:{clean_phone}"
    wa_session = await _conversation_session_repo.get_or_create(user_id=session_key, channel="whatsapp")
    raw_context = wa_session.context_json or {}
    customer_state = load_customer_state(session_id=clean_phone, tenant_id=active_tenant, raw_context=raw_context)

    # a. Layer 1: Signal Extraction
    intent = extract_signals(incoming_text, customer_state)

    # b. Layer 2: Strategy Determination
    nba = determine_strategy(customer_state, intent)

    # c. Data Fetching
    store_name, products = get_tenant_products_from_db(active_tenant)
    if not customer_state.target_product_ids and products:
        first_pid = str(products[0].get("id") or products[0].get("slug") or "")
        if first_pid:
            customer_state.target_product_ids.append(first_pid)

    product_context = ""
    if products:
        p_summaries = []
        for p in products[:5]:
            p_name = p.get("title") or p.get("name") or "Produk"
            p_price = int(float(p.get("promo_price") or p.get("price") or 0))
            p_desc = (p.get("description") or "").strip()
            p_summaries.append(f"- {p_name} (Harga Resmi: Rp{p_price:,}): {p_desc}".replace(",", "."))
        product_context = "\n".join(p_summaries)

    # d. Layer 3: Generator Prompt Mode
    mode_prompt = get_system_prompt_for_mode(nba, product_context)

    logger.info(f"[META WA 3-LAYER] Executing conversation engine for tenant={active_tenant}, user={from_phone}")
    try:
        reply = await commerce_ai_engine.generate_commerce_response(
            tenant_slug=active_tenant,
            user_message=incoming_text,
            user_phone=from_phone,
            user_name=contact_name,
            button_id=event.get("button_id"),
            mode_prompt=mode_prompt,
        )
        if not reply:
            reply = await process_incoming_message(
                tenant_slug=active_tenant,
                message=incoming_text,
                user_phone=from_phone,
                user_name=contact_name,
                button_id=event.get("button_id"),
            )
    except Exception as ai_err:
        logger.error(f"[META WA AI GENERATION ERROR] Error calling commerce_ai_engine: {ai_err}", exc_info=True)
        reply = None

    if not reply:
        reply = (
            f"Halo Kak! Senang bisa membantu di *{store_name}*. "
            "Untuk pemula di dunia digital marketing, kami sangat menyarankan paket dasar praktis kami. "
            "Ketik *Katalog* untuk melihat kurikulum ecourse lengkap atau langsung tanyakan materi yang ingin dipelajari ya Kak! ✨"
        )

    # e. Validator Guardrail
    db_session = TenantDBAdapter(products)
    action_result = validate_action(customer_state, db_session)

    # 3. Dispatch Balasan & State Persistence
    reply = sanitize_whatsapp_message_text(reply)

    if action_result.get("allow_button") is True:
        # Kirim tombol interaktif transaksi / Checkout QRIS
        checkout_buttons = [
            {"id": "btn_buy_now", "title": "💳 Beli Sekarang (QRIS)"},
            {"id": "btn_view_service", "title": "🛍️ Lihat Produk Lain"},
        ]
        btn_sent = False
        if from_phone and len(reply) <= 1000:
            try:
                await send_whatsapp_buttons(
                    to_phone=from_phone,
                    body_text=reply,
                    buttons=checkout_buttons,
                    footer_text="Pilih aksi di bawah untuk lanjut:",
                    tenant_id="ombudi",
                    phone_number_id=phone_id,
                )
                btn_sent = True
            except Exception as b_err:
                logger.warning(f"[WA BUTTON DISPATCH FAILED] {b_err}")
        if not btn_sent and reply and from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=reply, tenant_id="ombudi", phone_number_id=phone_id)
    else:
        # JANGAN kirim tombol checkout sama sekali (hanya kirim teks percakapan natural)
        if reply and from_phone:
            await send_whatsapp_text(to_phone=from_phone, text=reply, tenant_id="ombudi", phone_number_id=phone_id)

    # Simpan kembali state ke context_json via dump_customer_state dan update ke session database
    wa_session.context_json = dump_customer_state(customer_state, wa_session.context_json or {})
    await _conversation_session_repo.save(wa_session)

    safe_log_to_supabase_messages(
        sender="bot",
        text=reply or "",
        tenant_id=active_tenant,
        channel="whatsapp",
        user_phone=from_phone,
        user_name=contact_name,
        metadata={
            "conversation_engine_stage": customer_state.stage,
            "next_best_action": nba,
            "allow_button": action_result.get("allow_button", False),
        },
    )

    return JSONResponse(status_code=200, content={
        "status": "success",
        "tenant": active_tenant,
        "reply": reply,
        "stage": customer_state.stage,
        "allow_button": action_result.get("allow_button", False),
    })