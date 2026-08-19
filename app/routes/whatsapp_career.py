import re
import os
import logging
from aiohttp import web
from app.services.whatsapp_service import send_whatsapp_text
from app.constants.messages import GREETING_MENU_MSG, CV_HANDOFF_MSG, MENU_INVALID_MSG
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service
from app.services.ai_service import ai_gateway
from app.core.database import track_event, count_referrals

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")

async def verify_webhook(request: web.Request) -> web.Response:
    params = request.rel_url.query
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return web.Response(text=params.get("hub.challenge") or "", status=200)
    return web.Response(text="Verification failed", status=403)

async def handle_incoming_whatsapp(request: web.Request) -> web.Response:
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
        await send_whatsapp_text(sender_wa_id, "Halo! Bot saat ini hanya menerima pesan teks. Ketik *Menu* untuk bantuan.")
        return web.Response(text="EVENT_RECEIVED", status=200)

    user_text = msg_obj.get("text", {}).get("body", "").strip()
    user_text_clean = user_text.lower()

    # 1. Reset / Menu
    if user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "4"]:
        GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "menu", "data": {}}
        await send_whatsapp_text(sender_wa_id, GREETING_MENU_MSG)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 2. Tracking Referral Link
    if "ref_" in user_text_clean:
        ref_match = re.search(r"ref_(\d+)", user_text_clean)
        if ref_match:
            referrer_phone = ref_match.group(1)
            if referrer_phone != sender_wa_id:
                await track_event(sender_wa_id, "referral_signup", meta={"referrer_id": referrer_phone})

    # 3. Mode Review CV Masuk
    if "mau review cv" in user_text_clean or "review cv" in user_text_clean:
        GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "review", "data": {}}
        intro_review = (
            "Halo! Siap, mari kita bedah skor dan kualitas ATS CV kamu. 📊✨\n\n"
            "Silakan *salin dan tempel (copy-paste) seluruh isi teks CV kamu* langsung ke chat ini ya."
        )
        await send_whatsapp_text(sender_wa_id, intro_review)
        return web.Response(text="EVENT_RECEIVED", status=200)

    current_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    current_mode = current_session.get("mode", "menu")

    # 4. Alur Step Pembuatan CV Aktif
    if current_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        for msg in result.get("messages", [result["reply_text"]]):
            await send_whatsapp_text(sender_wa_id, msg)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 5. Opsi Menu 2 -> Tampilkan Info Referral & Counter Bersih
    if user_text_clean in ["2", "referral", "cek referral", "gratis"]:
        try:
            invited_count = await count_referrals(sender_wa_id)
        except Exception:
            invited_count = 0

        ref_link = f"[https://boontrack.com/ref/](https://boontrack.com/ref/){sender_wa_id}"
        ref_msg = (
            "🎁 *PROGRAM CAREER PAGE GRATIS VIA REFERRAL*\n\n"
            "Silakan share link berikut ke teman-temanmu. Semangat ya! 🚀\n\n"
            f"📊 *Status Referral Kamu:* *({invited_count}/5)* teman bergabung\n"
            f"🔗 *Link Referral Kamu:* {ref_link}\n\n"
            "Jika sudah mencapai 5 teman, Career Page profesional senilai Rp10.000 otomatis aktif gratis untukmu!"
        )
        await send_whatsapp_text(sender_wa_id, ref_msg)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 6. Opsi Menu Buat CV
    if user_text_clean == "1" or "buat cv" in user_text_clean:
        current_session["mode"] = "builder"
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        await send_whatsapp_text(sender_wa_id, result["reply_text"])
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 7. Mode Review CV
    if current_mode == "review":
        await send_whatsapp_text(sender_wa_id, "⏳ *Sedang menganalisis struktur & skor ATS CV kamu...*")
        try:
            eval_result = cv_review_engine.evaluate_cv(user_text, target_position="General Professional")[cite: 2]
            filtered_data = cv_review_service.filter_entitlement_response(eval_result, is_premium=False)[cite: 1]

            await cv_review_service.save_review(
                user_id=int(sender_wa_id),
                target_position="General Professional",
                overall_score=filtered_data.get("overall_score", 0),
                quality_score=filtered_data.get("breakdown_scores", {}).get("ats_compatibility", 0),
                job_match_score=filtered_data.get("breakdown_scores", {}).get("keyword", 0),
                evidence_score=filtered_data.get("breakdown_scores", {}).get("experience", 0),
                review_json=filtered_data,
                confidence_level=eval_result.get("confidence", {}).get("level", "MEDIUM")
            )[cite: 1]

            b = filtered_data.get("breakdown_scores", {})[cite: 1]
            findings = filtered_data.get("findings", [])[cite: 1]
            findings_list = "\n".join([f"• {f}" for f in findings]) if findings else "• Format dasar CV sudah terbaca dengan baik."

            review_msg = (
                "📊 *HASIL DIAGNOSIS SKOR CV KAMU*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Target Role:* General Professional\n"
                f"📈 *Overall Score:* *{filtered_data.get('overall_score', 0)} / 100*\n\n"
                "📌 *Breakdown Kategori:*\n"
                f"• ATS Compatibility: *{b.get('ats_compatibility', 70)}%*\n"
                f"• Relevansi Format: *{b.get('structure', 75)}%*\n"
                f"• Kualitas Pengalaman: *{b.get('experience', 80)}%*\n\n"
                "💡 *Poin Evaluasi AI:*\n"
                f"{findings_list}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔥 *Bikin HRD Langsung Lirik Lamaranmu!*\n\n"
                "Dapatkan *CV Rekomendasi AI + Career Page Profesional*.\n\n"
                "Pilih opsi selanjutnya:\n"
                "1️⃣ *Order Career Page (Rp10.000)*\n"
                "2️⃣ *Ajak 5 Teman (Gratis)*\n"
                "3️⃣ *Menu Utama*\n\n"
                "_Ketik angka 1, 2, atau 3 untuk memilih._"
            )
            current_session["mode"] = "menu"
            await send_whatsapp_text(sender_wa_id, review_msg)
        except Exception as e:
            logger.error(f"[WA Review Error] {e}")
            await send_whatsapp_text(sender_wa_id, "⚠️ Gagal menganalisis CV. Pastikan teks CV cukup lengkap lalu coba lagi.")
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 8. AI Karir Konsultasi
    ai_reply = await ai_gateway.generate(user_message=user_text, context={"user_id": sender_wa_id, "feature": "career_consultation"})
    if ai_reply:
        await send_whatsapp_text(sender_wa_id, ai_reply)
    else:
        await send_whatsapp_text(sender_wa_id, MENU_INVALID_MSG)

    return web.Response(text="EVENT_RECEIVED", status=200)

def register_whatsapp_career_routes(app: web.Application):
    app.router.add_get("/api/whatsapp/webhook", verify_webhook)
    app.router.add_post("/api/whatsapp/webhook", handle_incoming_whatsapp)