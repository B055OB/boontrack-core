import re
import os
import logging
from aiohttp import web
from app.services.whatsapp_service import send_whatsapp_text
from app.constants.messages import GREETING_MENU_MSG, CV_HANDOFF_MSG, MENU_INVALID_MSG
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.services.ai_service import ai_gateway

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")

async def verify_webhook(request: web.Request) -> web.Response:
    """Handshake Verifikasi Webhook Meta (GET)"""
    params = request.rel_url.query
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        logger.info("[WhatsApp] Webhook verified by Meta.")
        return web.Response(text=params.get("hub.challenge") or "", status=200)
    return web.Response(text="Verification failed", status=403)

async def handle_incoming_whatsapp(request: web.Request) -> web.Response:
    """Menerima dan memproses pesan masuk dari WhatsApp (POST)"""
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="INVALID_PAYLOAD", status=400)

    entry = data.get("entry", [])
    if not entry:
        return web.Response(text="EVENT_RECEIVED", status=200)

    changes = entry[0].get("changes", [])
    if not changes:
        return web.Response(text="EVENT_RECEIVED", status=200)

    messages = changes[0].get("value", {}).get("messages", [])
    if not messages:
        return web.Response(text="EVENT_RECEIVED", status=200)

    msg_obj = messages[0]
    sender_wa_id = msg_obj.get("from")

    if msg_obj.get("type") != "text":
        await send_whatsapp_text(
            sender_wa_id,
            "Halo! Saat ini bot hanya dapat memproses pesan teks. Ketik *Menu* untuk opsi layanan."
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    user_text = msg_obj.get("text", {}).get("body", "").strip()
    user_text_clean = user_text.lower()

    # 1. Reset / Panggil Menu Utama
    if user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal"]:
        GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "menu", "data": {}}
        await send_whatsapp_text(sender_wa_id, GREETING_MENU_MSG)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 2. Deteksi Hand-off ID WebChat
    match = re.search(r"ID:\s*([A-Za-z0-9_\-]+)", user_text, re.IGNORECASE)
    if match:
        cv_id = match.group(1).strip()
        GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "menu", "data": {}}
        await send_whatsapp_text(sender_wa_id, CV_HANDOFF_MSG.format(id=cv_id))
        return web.Response(text="EVENT_RECEIVED", status=200)

    current_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    current_mode = current_session.get("mode", "menu")

    # 3. Pengecekan Alur Aktif Buat CV (State Step > 0)
    if current_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        for msg in result.get("messages", [result["reply_text"]]):
            await send_whatsapp_text(sender_wa_id, msg)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 4. Navigasi Pilihan Menu (1, 2, 3)
    if user_text_clean == "1" or "buat cv" in user_text_clean:
        current_session["mode"] = "builder"
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        await send_whatsapp_text(sender_wa_id, result["reply_text"])

    elif user_text_clean == "2" or "review cv" in user_text_clean:
        current_session["mode"] = "review"
        await send_whatsapp_text(
            sender_wa_id,
            "Silakan ketik atau paste teks ringkasan pengalaman kerja / draf CV kamu di sini untuk diperiksa skor ATS-nya. 🔍"
        )

    elif user_text_clean == "3" or "konsultasi" in user_text_clean:
        current_session["mode"] = "consultation"
        await send_whatsapp_text(
            sender_wa_id,
            "Sesi Konsultasi Karir aktif 💼.\n\nSilakan tanyakan apa saja seputar persiapan kerja, interview, nego gaji, atau karir internasional. Ketik *Menu* untuk kembali ke opsi awal."
        )

    # 5. Routing Pesan Aktif Berdasarkan Mode
    elif current_mode == "consultation":
        # Kirim prompt langsung ke AIGateway
        ai_reply = await ai_gateway.generate(
            user_message=user_text,
            context={"user_id": sender_wa_id, "feature": "career_consultation"}
        )
        
        if not ai_reply:
            ai_reply = "Mohon maaf, sistem konsultasi sedang padat. Silakan coba tanyakan kembali beberapa saat lagi."
            
        await send_whatsapp_text(sender_wa_id, ai_reply)

    elif current_mode == "review":
        review_prompt = (
            "Lakukan review singkat dan berikan analisis skor ATS (skala 1-100) serta 2-3 saran perbaikan "
            f"untuk teks CV berikut:\n\n{user_text}"
        )
        ai_reply = await ai_gateway.generate(
            user_message=review_prompt,
            context={"user_id": sender_wa_id, "feature": "cv_review"}
        )
        if not ai_reply:
            ai_reply = "Format teks CV telah diterima. Rekomendasi perbaikan sedang dianalisis."
            
        await send_whatsapp_text(sender_wa_id, ai_reply)

    else:
        # Jika bukan di dalam mode khusus dan teks berbentuk pertanyaan umum -> Arahkan otomatis ke AI Gateway
        is_question = any(q in user_text_clean for q in ["bagaimana", "gimana", "apa", "berapa", "kenapa", "mengapa", "cara", "?"])
        if is_question:
            current_session["mode"] = "consultation"
            ai_reply = await ai_gateway.generate(
                user_message=user_text,
                context={"user_id": sender_wa_id, "feature": "general_career_chat"}
            )
            if ai_reply:
                await send_whatsapp_text(sender_wa_id, ai_reply)
                return web.Response(text="EVENT_RECEIVED", status=200)

        await send_whatsapp_text(sender_wa_id, MENU_INVALID_MSG)

    return web.Response(text="EVENT_RECEIVED", status=200)

def register_whatsapp_career_routes(app: web.Application):
    app.router.add_get("/api/whatsapp/webhook", verify_webhook)
    app.router.add_post("/api/whatsapp/webhook", handle_incoming_whatsapp)