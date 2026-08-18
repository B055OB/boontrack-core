import re
import os
import json
import logging
from aiohttp import web
from app.services.whatsapp_service import send_whatsapp_text

logger = logging.getLogger(__name__)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")

async def verify_webhook(request: web.Request) -> web.Response:
    """Handshake Verifikasi Webhook Meta (GET)"""
    params = request.rel_url.query
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("[WhatsApp] Webhook successfully verified by Meta.")
        return web.Response(text=challenge or "", status=200)

    logger.warning(f"[WhatsApp] Verification mismatch (got: {token})")
    return web.Response(text="Verification failed", status=403)

async def handle_incoming_whatsapp(request: web.Request) -> web.Response:
    """Menerima dan memproses pesan masuk dari WhatsApp (POST)"""
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="INVALID_PAYLOAD", status=400)

    # 1. Validasi struktur payload Meta
    entry = data.get("entry", [])
    if not entry:
        return web.Response(text="EVENT_RECEIVED", status=200)

    changes = entry[0].get("changes", [])
    if not changes:
        return web.Response(text="EVENT_RECEIVED", status=200)

    value = changes[0].get("value", {})
    
    # 2. Filter status event (sent/delivered/read)
    messages = value.get("messages", [])
    if not messages:
        return web.Response(text="EVENT_RECEIVED", status=200)

    msg_obj = messages[0]
    sender_wa_id = msg_obj.get("from")
    msg_type = msg_obj.get("type")

    if msg_type != "text":
        await send_whatsapp_text(
            sender_wa_id,
            "Halo! Saat ini bot membaca teks pesan dan format ID review CV dari WebChat. Ada yang bisa kami bantu?"
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    user_text = msg_obj.get("text", {}).get("body", "").strip()

    # 3. Hand-off Continuity dari WebChat (Deteksi Review ID)
    match = re.search(r"ID:\s*([A-Za-z0-9_\-]+)", user_text, re.IGNORECASE)
    if match:
        cv_identifier = match.group(1).strip()
        welcome_text = (
            f"Halo! 👋 Selamat datang di BoonTrack Career Assistant.\n\n"
            f"Data evaluasi CV kamu dengan ID: <b>{cv_identifier}</b> berhasil tersambung.\n\n"
            f"Berdasarkan analisis awal, ada beberapa poin perbaikan pada struktur metrik dan kata kunci ATS agar lolos seleksi awal HRD.\n\n"
            f"Mau kita bahas rekomendasi dan contoh perbaikannya sekarang?"
        )
        await send_whatsapp_text(sender_wa_id, welcome_text)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 4. Fallback Default Response
    reply_text = (
        "Halo! Terima kasih sudah menghubungi BoonTrack Assistant. 🚀\n\n"
        "Kamu bisa mengecek skor ATS, optimasi CV, dan mengaktifkan Website Career Page profesional langsung dari sini.\n\n"
        "Ketik posisi/role impian yang sedang kamu incar untuk memulai konsultasi!"
    )
    await send_whatsapp_text(sender_wa_id, reply_text)

    return web.Response(text="EVENT_RECEIVED", status=200)

def register_whatsapp_career_routes(app: web.Application):
    """Mendaftarkan route WhatsApp Career ke aiohttp app"""
    app.router.add_get("/api/whatsapp/webhook", verify_webhook)
    app.router.add_post("/api/whatsapp/webhook", handle_incoming_whatsapp)