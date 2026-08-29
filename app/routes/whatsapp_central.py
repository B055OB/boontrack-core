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

    # Jika teks melebihi limit 1000 karakter Meta API, kirim teks biasa dulu lalu kirim tombol
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


async def send_wa_image(recipient_phone: str, image_url_or_path: str, caption: str, phone_id: str) -> bool:
    """Mengirim pesan gambar WhatsApp ke Meta Cloud API menggunakan public URL HTTPS dengan fallback text."""
    clean_id_match = re.findall(r"\d+", str(phone_id))
    clean_id = clean_id_match[0] if clean_id_match else phone_id
    token = resolve_tenant_token(clean_id)

    image_url = str(image_url_or_path or "")
    if not image_url.startswith(("http://", "https://")):
        public_base = (
            os.getenv("PUBLIC_BASE_URL")
            or os.getenv("RAILWAY_STATIC_URL")
            or os.getenv("RAILWAY_PUBLIC_DOMAIN")
            or "https://boontrack-core.up.railway.app"
        ).strip().rstrip("/")
        if not public_base.startswith("http"):
            public_base = f"https://{public_base}"
        filename = os.path.basename(image_url) if image_url else "qrisombudi.png"
        image_url = f"{public_base}/static/{filename}"

    url = f"https://graph.facebook.com/v20.0/{clean_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
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
                    return True
                logger.error(f"[CENTRAL WA] Outbound image error ({resp.status}) phone_id={clean_id}: {resp_text}")
                # Fallback ke pesan teks lengkap agar info rekening/NMID tetap sampai ke user
                await send_wa_text(recipient_phone, caption, phone_id)
                return False
    except Exception as e:
        logger.error(f"[CENTRAL WA] Exception sending image: {e}", exc_info=True)
        await send_wa_text(recipient_phone, caption, phone_id)
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

            # 1. Simpan pesan user masuk ke Supabase secara aman non-blocking
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
                    image_url_or_path=img_src,
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
                # Kirim teks konten biasa (support s/d 4096 karakter)
                await send_wa_text(from_phone, reply_text, phone_id)
                # Jika ada tombol navigasi, kirim pesan terpisah berisi tombol
                if buttons:
                    await send_wa_buttons(
                        from_phone,
                        "👇 *Pilih menu untuk melanjutkan:*",
                        buttons,
                        phone_id
                    )

            # 2. Simpan balasan bot ke Supabase secara aman non-blocking
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
            # 6.6. Dynamic Tenant Resolution (Meta Sandbox +15556769563 / 1306479742542883 / Custom)
            from app.services.whatsapp_service import resolve_dynamic_tenant_for_whatsapp
            from app.services.ai_engine import commerce_ai_engine
            from app.services.onboarding_service import onboarding_service

            tenant_slug, is_new_binding = resolve_dynamic_tenant_for_whatsapp(
                phone_id=phone_id,
                from_phone=from_phone,
                message_text=incoming_text,
            )

            details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
            store_name = details.get("tenant", {}).get("name", tenant_slug) if details else tenant_slug

            # Simpan pesan user ke Supabase
            safe_log_to_supabase_messages(
                sender="user",
                text=incoming_text,
                tenant_id=tenant_slug,
                channel="whatsapp",
                user_phone=from_phone,
                user_name=contact_name,
                user_id=from_phone,
                conversation_id=from_phone,
                metadata={"phone_number_id": phone_id, "msg_type": msg_type}
            )

            if is_new_binding:
                welcome_msg = details.get("persona", {}).get("welcome_message", "") if details else ""
                reply_text = (
                    f"🎉 *Selamat Datang di {store_name}!* 🎉\n\n"
                    f"Nomor WhatsApp Kakak (*{contact_name}*) kini resmi terhubung dengan asisten toko *{store_name}*.\n\n"
                    f"{welcome_msg}\n\n"
                    f"_Silakan ketik nama produk atau ketik *menu* untuk melihat katalog._"
                )
            else:
                reply_text = await commerce_ai_engine.generate_commerce_response(
                    tenant_slug=tenant_slug,
                    user_message=incoming_text,
                    user_phone=from_phone,
                    user_name=contact_name,
                    button_id=button_id,
                )

            await send_wa_text(from_phone, reply_text, phone_id)

            # Simpan balasan bot ke Supabase
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
