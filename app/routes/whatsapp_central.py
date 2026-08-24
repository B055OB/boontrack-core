import logging
import os
import re
from typing import Any, Dict, List, Optional
import aiohttp
from aiohttp import web

# Security & Compliance Layers
from app.core.security.rate_limiter import wa_rate_limiter
from app.core.security.masking import ZeroPIILogFilter

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
        clean_text = "Afwan Bapak/Ibu, pesan sedang diproses. Silakan ulangi atau pilih opsi menu yang tersedia."

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
            "body": {"text": clean_body},
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
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return web.json_response({"status": "ignored"}, status=200)

        # Ambil phone_number_id dari metadata webhook
        phone_id = str(value.get("metadata", {}).get("phone_number_id", "")).strip()

        msg_obj = messages[0]
        from_phone = msg_obj.get("from")
        msg_type = msg_obj.get("type")
        contact_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Bapak/Ibu")

        # 6.1. Anti-Spam Rate Limiter (Maks 5 pesan / menit)
        is_allowed, retry_after = wa_rate_limiter.is_allowed(from_phone)
        if not is_allowed:
            logger.warning(f"[RATE LIMIT] Pengirim {from_phone} terkena throttling.")
            await send_wa_text(
                recipient_phone=from_phone,
                text=f"Pesan Anda terkirim terlalu cepat. Silakan tunggu {retry_after} detik sebelum mencoba lagi.",
                phone_id=phone_id
            )
            return web.json_response({"status": "rate_limited"}, status=429)

        # 6.2. Filter Media & File Attachment
        if msg_type in ["document", "video", "audio"]:
            await send_wa_text(
                recipient_phone=from_phone,
                text="Format berkas tidak diizinkan. Silakan lampirkan gambar/foto berformat JPG atau PNG maksimal 5MB.",
                phone_id=phone_id
            )
            return web.json_response({"status": "unsupported_media"}, status=200)

        # 6.3. Ekstraksi Pesan & Download Media Gambar jika Ada
        incoming_text = ""
        button_id = None
        image_bytes: Optional[bytes] = None
        image_mime: str = "image/jpeg"

        if msg_type == "text":
            incoming_text = msg_obj.get("text", {}).get("body", "")
        elif msg_type == "interactive":
            inter = msg_obj.get("interactive", {})
            if inter.get("type") == "button_reply":
                btn = inter.get("button_reply", {})
                button_id = btn.get("id")
                incoming_text = btn.get("title", "")
        elif msg_type == "image":
            image_data = msg_obj.get("image", {})
            image_mime = image_data.get("mime_type", "image/jpeg")
            if image_mime not in ALLOWED_IMAGE_MIME_TYPES:
                await send_wa_text(
                    recipient_phone=from_phone,
                    text="Lampiran gambar wajib berformat JPG atau PNG.",
                    phone_id=phone_id
                )
                return web.json_response({"status": "invalid_media_type"}, status=200)

            media_id = image_data.get("id")
            if media_id:
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

            incoming_text = image_data.get("caption", "[FOTO_TERLAMPIR]")

        # 6.4. Dispatching Terisolasi Berdasarkan Phone Number ID
        if phone_id == CAREER_PHONE_NUMBER_ID:
            from app.routes.whatsapp_career import handle_incoming_whatsapp
            return await handle_incoming_whatsapp(request)

        elif phone_id == OM_BUDI_PHONE_NUMBER_ID:
            from app.tenants.om_budi.service import om_budi_service
            res = await om_budi_service.handle_incoming_message(
                phone_number=from_phone,
                message_text=incoming_text,
                button_id=button_id,
                user_name=contact_name,
                image_bytes=image_bytes,
                image_mime=image_mime
            )

            raw_reply = res.get("reply") if isinstance(res, dict) else str(res)
            if not raw_reply or str(raw_reply).strip().lower() in ["none", "null", ""]:
                reply_text = (
                    f"Alhamdulillah, baik Bapak/Ibu *{contact_name}*.\n\n"
                    "Untuk pendaftaran *Kelas Online Bimbingan Om Budi*, silakan tekan tombol di bawah ini:"
                )
                fallback_buttons = [
                    {"id": "btn_daftar_kelas", "title": "Daftar Kelas Online"},
                    {"id": "btn_tanya_curhat", "title": "Tanya / Curhat"}
                ]
                await send_wa_buttons(from_phone, reply_text, fallback_buttons, phone_id)
            elif isinstance(res, dict) and res.get("type") == "buttons":
                await send_wa_buttons(from_phone, raw_reply, res.get("buttons", []), phone_id)
            else:
                await send_wa_text(from_phone, raw_reply, phone_id)

            return web.json_response({"status": "success", "tenant": "om_budi"}, status=200)

        elif phone_id == ADUAN_SANDBOX_PHONE_ID:
            sandbox_reply = (
                f"🏛️ *[BALÉ PANANGGEUHAN DISKOMINFO - UJI COBA]*\n\n"
                f"Sampurasun, *{contact_name}*.\n"
                f"Laporan/aspirasi Anda telah tercatat di sistem pengujian:\n\n"
                f"📝 *Ringkasan:* \"{incoming_text}\"\n"
                f"🔒 *Status Keamanan:* RLS & Field-Level Encryption Active.\n\n"
                f"_Tiket aduan pengujian telah diteruskan ke Posko Jabar._"
            )
            await send_wa_text(from_phone, sandbox_reply, phone_id)
            return web.json_response({"status": "success", "tenant": "aduan_sandbox"}, status=200)

        else:
            logger.warning(f"[CENTRAL WA] Phone ID tidak dikenal: {phone_id}")
            return web.json_response({"status": "unrecognized_phone_id"}, status=400)

    except Exception as e:
        logger.error(f"[CENTRAL WA ERROR] {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)


def register_central_whatsapp_routes(app: web.Application):
    app.add_routes(central_wa_routes)
    logger.info("[ROUTER] Central WhatsApp Webhook registered with isolated Diskominfo sandbox.")