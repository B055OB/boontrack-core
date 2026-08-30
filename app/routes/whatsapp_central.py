import logging
import os
import re
from typing import Any, Dict, List, Optional
import aiohttp
from aiohttp import web

# Security & Compliance Layers
from app.core.security.rate_limiter import wa_rate_limiter
from app.core.security.masking import ZeroPIILogFilter
from app.services.whatsapp_service import (
    log_to_supabase_messages, 
    safe_log_to_supabase_messages,
    send_whatsapp_image,
    extract_meta_whatsapp_event
)

logger = logging.getLogger("CENTRAL_WA_ROUTER")
if not any(isinstance(f, ZeroPIILogFilter) for f in logger.filters):
    logger.addFilter(ZeroPIILogFilter())

central_wa_routes = web.RouteTableDef()

# --- 1. Verifikasi Tokens Meta ---
VERIFY_TOKENS = [
    "boontrack_master_verify_token_2026",
    "om_budi_secure_token_2026",
    "boontrack_career_token",
    "boontrack_wa_secret_token",
    "boontrack_aduan_token"
]

# --- 2. Konfigurasi Phone Number ID Tenant ---
OM_BUDI_PHONE_NUMBER_ID = "1268977686299719"       # Produksi Om Budi
CAREER_PHONE_NUMBER_ID = "1340866379104241"        # Produksi Career Assistant
ADUAN_SANDBOX_PHONE_ID = "1306479742542883"        # Sandbox / Uji Coba Diskominfo Aduan

# --- 3. Access Tokens Resolver (Dengan Fallback ke WHATSAPP_TOKEN) ---
PERMANENT_META_TOKEN = "EAANbiVgBfGQBSQkvsZBc8JmqdEZBJWSrZAWR1gnJep0lkyZAv4O02LKEwjoNAc8lNOvaEeKhtb6pcr45S8wtd5CrSKdoMwEq6A1eJV4Yb140DBOMbmj3wLzo0Y7fZBrus25EJ0xeqXlPbDisP6d4DmZAGkvbJ7hnKfFih3G7L7mn6g56OQVU42dZByNSHNEiwZDZD"

OM_BUDI_ACCESS_TOKEN = os.getenv(
    "OM_BUDI_ACCESS_TOKEN",
    os.getenv("WHATSAPP_TOKEN", PERMANENT_META_TOKEN)
)
CAREER_ACCESS_TOKEN = os.getenv(
    "CAREER_ACCESS_TOKEN",
    os.getenv("WHATSAPP_TOKEN", OM_BUDI_ACCESS_TOKEN)
)
ADUAN_SANDBOX_ACCESS_TOKEN = os.getenv(
    "ADUAN_ACCESS_TOKEN",
    os.getenv("WHATSAPP_TOKEN", OM_BUDI_ACCESS_TOKEN)
)

ALLOWED_IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/jpg"]


def resolve_tenant_token(phone_id: str) -> str:
    """Mengambil access token yang tepat sesuai Phone Number ID."""
    clean_id = str(phone_id).strip()
    if clean_id == CAREER_PHONE_NUMBER_ID:
        return CAREER_ACCESS_TOKEN
    elif clean_id == ADUAN_SANDBOX_PHONE_ID:
        return ADUAN_SANDBOX_ACCESS_TOKEN
    return OM_BUDI_ACCESS_TOKEN


# --- 4. Helper Outbound WA Dinamis Multi-Tenant ---
async def send_wa_text(recipient_phone: str, text: str, phone_id: str):
    clean_id_match = re.findall(r"\d+", str(phone_id))
    clean_id = clean_id_match[0] if clean_id_match else phone_id
    token = resolve_tenant_token(clean_id)

    clean_text = str(text).strip() if text else ""
    if not clean_text or clean_text.lower() in ["none", "null"]:
        clean_text = "Afwan Kakak, pesan sedang diproses. Silakan pilih opsi menu yang tersedia."

    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": clean_text}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[CENTRAL WA] Outbound text error ({resp.status}) phone_id={clean_id}: {resp_text}")
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending text message: {e}", exc_info=True)


async def send_wa_buttons(recipient_phone: str, body_text: str, buttons: List[Dict[str, str]], phone_id: str):
    clean_id_match = re.findall(r"\d+", str(phone_id))
    clean_id = clean_id_match[0] if clean_id_match else phone_id
    token = resolve_tenant_token(clean_id)

    clean_body = str(body_text).strip() if body_text else ""
    if not clean_body or clean_body.lower() in ["none", "null"]:
        clean_body = "Silakan pilih salah satu opsi di bawah untuk melanjutkan:"

    if not buttons:
        await send_wa_text(recipient_phone, clean_body, phone_id)
        return

    if len(clean_body) > 1000:
        await send_wa_text(recipient_phone, clean_body, phone_id)
        clean_body = "👇 *Silakan pilih menu navigasi di bawah ini:*"

    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    button_rows = [{"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}} for b in buttons[:3]]
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": clean_body[:1024]},
            "action": {"buttons": button_rows}
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[CENTRAL WA] Outbound button error ({resp.status}) phone_id={clean_id}: {resp_text}")
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending buttons: {e}", exc_info=True)


async def send_wa_image(recipient_phone: str, image_url_or_path_or_bytes: Any, caption: str, phone_id: str) -> bool:
    """Mengirim pesan gambar WhatsApp ke Meta Cloud API via direct public URL link atau upload fallback."""
    clean_id_match = re.findall(r"\d+", str(phone_id))
    clean_id = clean_id_match[0] if clean_id_match else phone_id
    token = resolve_tenant_token(clean_id)

    clean_phone = "".join(filter(str.isdigit, str(recipient_phone)))
    if clean_phone.startswith("08"):
        clean_phone = "62" + clean_phone[1:]
    elif clean_phone.startswith("008"):
        clean_phone = "62" + clean_phone[2:]

    # 1. Jika input merupakan URL gambar publik yang valid
    if isinstance(image_url_or_path_or_bytes, str) and image_url_or_path_or_bytes.startswith(("http://", "https://")):
        image_url = image_url_or_path_or_bytes
        url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": {
                "link": image_url,
                "caption": caption
            }
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    resp_text = await resp.text()
                    if resp.status in (200, 201):
                        logger.info(f"[CENTRAL WA] Image successfully delivered to {clean_phone}")
                        return True
                    logger.error(f"[CENTRAL WA] Outbound image error ({resp.status}) phone_id={clean_id}: {resp_text}")
        except Exception as e:
            logger.error(f"[CENTRAL WA] Exception sending image via URL: {e}", exc_info=True)

    # 2. Upload Bytes PNG jika bukan URL
    if isinstance(image_url_or_path_or_bytes, bytes):
        upload_url = f"https://graph.facebook.com/v20.0/{clean_id}/media"
        headers = {"Authorization": f"Bearer {token}"}
        form_data = aiohttp.FormData()
        form_data.add_field("messaging_product", "whatsapp")
        form_data.add_field("type", "image/png")
        form_data.add_field("file", image_url_or_path_or_bytes, filename="qris_code.png", content_type="image/png")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(upload_url, headers=headers, data=form_data) as up_resp:
                    if up_resp.status in (200, 201):
                        up_json = await up_resp.json()
                        media_id = up_json.get("id")
                        if media_id:
                            msg_url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
                            payload = {
                                "messaging_product": "whatsapp",
                                "recipient_type": "individual",
                                "to": clean_phone,
                                "type": "image",
                                "image": {
                                    "id": str(media_id),
                                    "caption": caption
                                }
                            }
                            async with session.post(msg_url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload) as msg_resp:
                                if msg_resp.status in (200, 201):
                                    return True
                                logger.error(f"[CENTRAL WA] Outbound media_id error ({msg_resp.status}): {await msg_resp.text()}")
                    else:
                        logger.error(f"[CENTRAL WA] Media upload error ({up_resp.status}): {await up_resp.text()}")
        except Exception as e:
            logger.error(f"[CENTRAL WA] Exception in multipart media upload: {e}", exc_info=True)

    # 3. Fallback Teks bila image pengiriman gagal
    await send_wa_text(clean_phone, caption, phone_id)
    return False


async def send_wa_list_menu(recipient_phone: str, body_text: str, button_text: str, sections: List[Dict[str, Any]], phone_id: str):
    """Mengirim Interactive List Message WhatsApp untuk menu hierarki."""
    clean_id_match = re.findall(r"\d+", str(phone_id))
    clean_id = clean_id_match[0] if clean_id_match else phone_id
    token = resolve_tenant_token(clean_id)

    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text[:20],
                "sections": sections
            }
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                if resp.status not in (200, 201):
                    logger.error(f"[CENTRAL WA] Outbound list error ({resp.status}) phone_id={clean_id}: {resp_text}")
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending list menu: {e}", exc_info=True)


# --- 5. Webhook GET: Verifikasi Meta ---
@central_wa_routes.get("/webhook/whatsapp")
@central_wa_routes.get("/api/v1/tenants/om_budi/webhook/whatsapp")
@central_wa_routes.get("/api/whatsapp/webhook")
@central_wa_routes.get("/api/v1/whatsapp/webhook")
async def verify_webhook(request: web.Request) -> web.Response:
    query = request.query
    mode = query.get("hub.mode")
    token = query.get("hub.verify_token")
    challenge = query.get("hub.challenge")

    if mode == "subscribe" and token in VERIFY_TOKENS:
        logger.info(f"[CENTRAL WA] Webhook verified with token: {token}")
        return web.Response(text=challenge or "", status=200)

    return web.Response(text="Verification failed", status=403)


# --- 6. Webhook POST: Dispatcher Pesan Terisolasi ---
@central_wa_routes.post("/webhook/whatsapp")
@central_wa_routes.post("/api/v1/tenants/om_budi/webhook/whatsapp")
@central_wa_routes.post("/api/whatsapp/webhook")
@central_wa_routes.post("/api/v1/whatsapp/webhook")
async def handle_incoming_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        event = extract_meta_whatsapp_event(data)

        # 6.1. Abaikan status delivery / read receipts
        if event["is_status"]:
            return web.json_response({"status": "status_ignored"}, status=200)

        if not event["is_message"]:
            return web.json_response({"status": "ignored"}, status=200)

        phone_id = event["phone_id"]
        from_phone = event["from_phone"]
        msg_type = event["msg_type"]
        contact_name = event["contact_name"] or "Kakak"
        incoming_text = event["text"]
        button_id = event["button_id"]
        media_id = event["media_id"]
        image_mime = event["media_mime"] or "image/jpeg"
        image_bytes: Optional[bytes] = None

        # 6.2. Anti-Spam Rate Limiter (Maks 5 pesan / menit)
        is_allowed, retry_after = wa_rate_limiter.is_allowed(from_phone)
        if not is_allowed:
            logger.warning(f"[RATE LIMIT] Pengirim {from_phone} terkena throttling.")
            await send_wa_text(
                recipient_phone=from_phone,
                text=f"Pesan Kakak terkirim terlalu cepat. Silakan tunggu {retry_after} detik sebelum mencoba lagi.",
                phone_id=phone_id
            )
            return web.json_response({"status": "rate_limited"}, status=429)

        # 6.3. Filter Media & Dokumen Tak Didukung di Channel Utama
        if msg_type in ["video", "audio"]:
            await send_wa_text(
                recipient_phone=from_phone,
                text="Format berkas tidak diizinkan. Silakan lampirkan gambar/foto berformat JPG atau PNG maksimal 5MB.",
                phone_id=phone_id
            )
            return web.json_response({"status": "unsupported_media"}, status=200)

        # 6.4. Download Media Gambar jika Ada
        if msg_type == "image" and media_id:
            if image_mime not in ALLOWED_IMAGE_MIME_TYPES:
                await send_wa_text(
                    recipient_phone=from_phone,
                    text="Lampiran gambar wajib berformat JPG atau PNG.",
                    phone_id=phone_id
                )
                return web.json_response({"status": "invalid_media_type"}, status=200)

            token = resolve_tenant_token(phone_id)
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(
                        f"https://graph.facebook.com/v20.0/{media_id}",
                        headers={"Authorization": f"Bearer {token}"}
                    ) as m_resp:
                        if m_resp.status == 200:
                            m_data = await m_resp.json()
                            media_url = m_data.get("url")
                            async with sess.get(
                                media_url,
                                headers={"Authorization": f"Bearer {token}"}
                            ) as bin_resp:
                                if bin_resp.status == 200:
                                    image_bytes = await bin_resp.read()
            except Exception as e:
                logger.error(f"[MEDIA DOWNLOAD ERROR] {e}")

        # 6.5. Dispatching Terisolasi Berdasarkan Phone Number ID
        if phone_id == CAREER_PHONE_NUMBER_ID:
            from app.tenants.career.router import handle_incoming_whatsapp
            return await handle_incoming_whatsapp(request)

        elif phone_id == OM_BUDI_PHONE_NUMBER_ID:
            from app.tenants.om_budi.service import om_budi_service

            safe_log_to_supabase_messages(
                sender="user",
                text=incoming_text or f"[{msg_type}]",
                tenant_id="om-budi",
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
                metadata={
                    "button_id": button_id,
                    "phone_number_id": phone_id,
                    "msg_type": msg_type
                }
            )

            res = await om_budi_service.handle_incoming_message(
                phone_number=from_phone,
                message_text=incoming_text,
                button_id=button_id,
                user_name=contact_name,
                image_bytes=image_bytes,
                image_mime=image_mime
            )

            res_type = res.get("type", "text")
            reply_text = res.get("reply", "")
            buttons = res.get("buttons") or res.get("nav_buttons")

            if res_type == "image":
                img_src = (
                    res.get("image_url")
                    or res.get("image_link")
                    or (res.get("image", {}).get("link") if isinstance(res.get("image"), dict) else None)
                    or res.get("image_path")
                    or res.get("image")
                )
                caption_text = res.get("reply", "") or res.get("caption", "")
                await send_wa_image(
                    recipient_phone=from_phone,
                    image_url_or_path_or_bytes=img_src,
                    caption=caption_text,
                    phone_id=phone_id
                )
                if buttons:
                    await send_wa_buttons(
                        from_phone,
                        "👇 *Pilih menu untuk melanjutkan:*",
                        buttons,
                        phone_id
                    )
            elif res_type == "list":
                await send_wa_list_menu(
                    from_phone,
                    reply_text,
                    res.get("button_text", "Pilih Menu"),
                    res.get("sections", []),
                    phone_id
                )
            elif res_type == "buttons" and len(reply_text) <= 1000:
                await send_wa_buttons(from_phone, reply_text, buttons or [], phone_id)
            else:
                await send_wa_text(from_phone, reply_text, phone_id)
                if buttons:
                    await send_wa_buttons(
                        from_phone,
                        "👇 *Pilih menu untuk melanjutkan:*",
                        buttons,
                        phone_id
                    )

            safe_log_to_supabase_messages(
                sender="bot",
                text=reply_text,
                tenant_id="om-budi",
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
                metadata={
                    "res_type": res_type,
                    "phone_number_id": phone_id,
                    "buttons": buttons
                }
            )

            return web.json_response({"status": "success", "tenant": "om_budi"}, status=200)

        else:
            # 6.6. Dynamic Tenant Resolution with Top-Level Demo Menu Interceptor
            from app.services.whatsapp_service import (
                resolve_dynamic_tenant_for_whatsapp,
                user_tenant_sessions,
                normalize_phone_number,
                generate_fast_track_checkout_response,
                is_closing_buy_intent,
                DEMO_MENU_TEXT,
                DEMO_TENANT_GREETINGS,
            )
            from app.services.ai_engine import commerce_ai_engine
            from app.services.onboarding_service import onboarding_service

            clean_phone = normalize_phone_number(from_phone)
            text_lower = (incoming_text or "").strip().lower()
            clean_btn = str(button_id or "").strip().lower()

            # ---------------------------------------------------------------
            # STEP A: Prioritas Tertinggi - Deteksi Tombol / Teks Beli QRIS
            # ---------------------------------------------------------------
            is_qris_trigger = (
                clean_btn in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris"}
                or "beli & bayar qris" in text_lower
                or "bayar qris" in text_lower
                or text_lower == "beli"
                or is_closing_buy_intent(incoming_text, clean_btn)
            )

            active_session_tenant = user_tenant_sessions.get(clean_phone) or "onlineboost"

            if is_qris_trigger and active_session_tenant not in ("bale_pananggeuhan", "bale-pananggeuhan", "pelayanan_publik"):
                logger.info(f"[CENTRAL WA QRIS] Fast-track buy intent from {from_phone} on tenant '{active_session_tenant}'")
                
                safe_log_to_supabase_messages(
                    sender="user",
                    text=incoming_text or "[Klik Beli QRIS]",
                    tenant_id=active_session_tenant,
                    channel="whatsapp",
                    user_phone=from_phone,
                    user_name=contact_name,
                    user_id=from_phone,
                    conversation_id=from_phone,
                    metadata={"phone_number_id": phone_id, "button_id": button_id}
                )

                reply_text, invoice, qr_bytes = await generate_fast_track_checkout_response(
                    tenant_slug=active_session_tenant,
                    from_phone=from_phone,
                    contact_name=contact_name,
                )

                # Siapkan Direct PNG URL untuk render langsung di WhatsApp
                qr_target_url = invoice.get("qr_code_url")
                if not qr_target_url and invoice.get("qr_string"):
                    import urllib.parse
                    qr_target_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&format=png&data={urllib.parse.quote(invoice.get('qr_string'))}"

                is_img_sent = False
                if qr_target_url:
                    is_img_sent = await send_wa_image(from_phone, qr_target_url, reply_text, phone_id)
                elif qr_bytes:
                    is_img_sent = await send_wa_image(from_phone, qr_bytes, reply_text, phone_id)

                if not is_img_sent:
                    await send_wa_text(from_phone, reply_text, phone_id)

                safe_log_to_supabase_messages(
                    sender="bot",
                    text=f"[Kirim QRIS {invoice.get('external_id')}] {reply_text}",
                    tenant_id=active_session_tenant,
                    channel="whatsapp",
                    user_phone=from_phone,
                    user_name=contact_name,
                    user_id=from_phone,
                    conversation_id=from_phone,
                    metadata={"phone_number_id": phone_id, "invoice_id": invoice.get("external_id")}
                )
                return web.json_response({"status": "qris_dispatched", "tenant": active_session_tenant}, status=200)

            # ---------------------------------------------------------------
            # STEP B: Pre-check — is this an onboarding announcement? Exempt it.
            # ---------------------------------------------------------------
            _is_onboarding_msg = bool(
                re.search(
                    r"saya\s+baru\s+(?:saja\s+)?(?:mendaftar|daftar)\s+toko\s+[a-zA-Z0-9\-_]+",
                    incoming_text or "",
                    re.IGNORECASE,
                )
                or re.search(r"toko\s*:\s*[a-zA-Z0-9\-_]+", incoming_text or "", re.IGNORECASE)
            )

            # ---------------------------------------------------------------
            # STEP C: TOP-LEVEL DEMO MENU INTERCEPTOR
            # ---------------------------------------------------------------
            _MENU_TRIGGER_KEYWORDS = {"halo", "hi", "p", "test", "tes", "hai", "start", "info", "menu", "demo", "#reset", "reset"}
            _MENU_OPTION_MAP = {
                "1": "bale_pananggeuhan",
                "2": "atmosfitnes",
                "3": "onlineboost",
            }

            _is_keyword_trigger = text_lower in _MENU_TRIGGER_KEYWORDS or clean_btn == "btn_menu_reset"
            _has_active_session = bool(clean_phone and clean_phone in user_tenant_sessions)

            if (not _is_onboarding_msg) and (_is_keyword_trigger or not _has_active_session):
                if clean_phone:
                    user_tenant_sessions.pop(clean_phone, None)

                if text_lower not in _MENU_OPTION_MAP:
                    logger.info(
                        f"[CENTRAL WA INTERCEPTOR] Sender {from_phone} triggered menu "
                        f"(keyword={_is_keyword_trigger}, no_session={not _has_active_session})"
                    )
                    await send_wa_text(from_phone, DEMO_MENU_TEXT, phone_id)
                    safe_log_to_supabase_messages(
                        sender="bot",
                        text=DEMO_MENU_TEXT,
                        tenant_id="__MENU__",
                        channel="whatsapp",
                        user_phone=from_phone,
                        user_name=contact_name,
                        user_id=from_phone,
                        conversation_id=from_phone,
                    )
                    return web.json_response({
                        "status": "menu_dispatched",
                        "tenant": "__MENU__",
                        "reply": DEMO_MENU_TEXT,
                    }, status=200)

            # ---------------------------------------------------------------
            # STEP D: MENU OPTION SELECTION (1, 2, 3)
            # ---------------------------------------------------------------
            if text_lower in _MENU_OPTION_MAP:
                selected_slug = _MENU_OPTION_MAP[text_lower]
                if clean_phone:
                    user_tenant_sessions[clean_phone] = selected_slug
                logger.info(
                    f"[CENTRAL WA MENU SELECT] Sender {from_phone} selected '{text_lower}' -> locked to '{selected_slug}'"
                )
                greeting = DEMO_TENANT_GREETINGS.get(
                    selected_slug,
                    f"🎉 Anda kini terhubung dengan *{selected_slug}*. Silakan mulai percakapan!"
                )
                if selected_slug == "onlineboost":
                    buttons = [
                        {"id": "btn_buy_now", "title": "💳 Beli & Bayar QRIS"},
                        {"id": "btn_view_service", "title": "🚀 Info Layanan & Modul"},
                        {"id": "btn_menu_reset", "title": "🔄 Ganti Demo Toko"},
                    ]
                    await send_wa_buttons(
                        from_phone,
                        (
                            "Halo Kak! Selamat datang di *OnlineBoost Official Store* 🚀\n\n"
                            "Solusi praktis scale-up campaign Meta & TikTok Ads, optimasi ROAS, dan landing page konversi tinggi.\n\n"
                            "🔥 *Promo Hari Ini:* Starter Kit Paid Traffic cuma *Rp99.000* (Diskon 50%). Sudah termasuk modul video HD + Template Kalkulator ROI Spreadsheet."
                        ),
                        buttons,
                        phone_id,
                    )
                else:
                    await send_wa_text(from_phone, greeting, phone_id)

                safe_log_to_supabase_messages(
                    sender="bot",
                    text=greeting,
                    tenant_id=selected_slug,
                    channel="whatsapp",
                    user_phone=from_phone,
                    user_name=contact_name,
                    user_id=from_phone,
                    conversation_id=from_phone,
                )
                return web.json_response({
                    "status": "success",
                    "tenant": selected_slug,
                    "is_new_binding": True,
                    "reply": greeting,
                }, status=200)

            # ---------------------------------------------------------------
            # STEP E: NORMAL PIPELINE — Resolve tenant + AI engine
            # ---------------------------------------------------------------
            tenant_slug, is_new_binding = resolve_dynamic_tenant_for_whatsapp(
                phone_id=phone_id,
                from_phone=from_phone,
                message_text=incoming_text,
            )

            details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
            store_name = details.get("tenant", {}).get("name", tenant_slug) if details else tenant_slug

            safe_log_to_supabase_messages(
                sender="user",
                text=incoming_text,
                tenant_id=tenant_slug,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
                metadata={"phone_number_id": phone_id, "msg_type": msg_type, "button_id": button_id}
            )

            if clean_btn in {"btn_view_service", "btn_view_syllabus"} or "layanan" in text_lower or "paket" in text_lower:
                reply_text = (
                    "🚀 *PAKET SCALE-UP DIGITAL MARKETING ONLINEBOOST:*\n\n"
                    "• *Modul 1:* Setup Pixel & Riset Winning Audience Meta/TikTok Ads\n"
                    "• *Modul 2:* Strategi Scaling Budget Campaign CBO vs ABO\n"
                    "• *Modul 3:* High-Converting Funneling & Copywriting Konversi\n"
                    "• *Bonus:* Template Spreadsheet Kalkulator ROI Iklan + Diskusi VIP\n\n"
                    "🔥 *Promo Starter Kit:* Cuma *Rp99.000* (Akses Selamanya)\n\n"
                    "Ketik *Beli* atau klik tombol di atas untuk pembayaran QRIS instan."
                )
                await send_wa_text(from_phone, reply_text, phone_id)
            elif is_new_binding and _is_onboarding_msg:
                reply_text = (
                    f"🎉 *Selamat Datang di {store_name}!* 🚀\n\n"
                    f"Nomor WhatsApp Kakak (*{contact_name}*) kini resmi terhubung dengan asisten toko *{store_name}*.\n\n"
                    f"Ada yang bisa kami bantu seputar produk atau promo hari ini?"
                )
                await send_wa_text(from_phone, reply_text, phone_id)
            else:
                reply_text = await commerce_ai_engine.generate_commerce_response(
                    tenant_slug=tenant_slug,
                    user_message=incoming_text,
                    user_phone=from_phone,
                    user_name=contact_name,
                    button_id=button_id,
                )
                if not reply_text:
                    from app.services.agent_service import process_incoming_message
                    reply_text = await process_incoming_message(
                        tenant_slug=tenant_slug,
                        message=incoming_text,
                        user_phone=from_phone,
                        user_name=contact_name,
                        button_id=button_id,
                    )
                if reply_text:
                    await send_wa_text(from_phone, reply_text, phone_id)

            safe_log_to_supabase_messages(
                sender="bot",
                text=reply_text,
                tenant_id=tenant_slug,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
                metadata={"phone_number_id": phone_id}
            )

            return web.json_response({"status": "success", "tenant": tenant_slug}, status=200)

    except Exception as e:
        logger.error(f"[CENTRAL WA ERROR] {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)


def register_central_whatsapp_routes(app: web.Application):
    app.add_routes(central_wa_routes)
    logger.info("[ROUTER] Central WhatsApp Webhook registered.")