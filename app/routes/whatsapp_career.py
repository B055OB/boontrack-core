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
from app.services.document_parser_service import download_whatsapp_media, extract_text_from_bytes

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")

PAYMENT_OFFER_MSG_TEMPLATE = (
    "💼 *AKTIVASI CAREER PAGE PORTOFOLIO PROFESIONAL*\n\n"
    "Tingkatkan peluang panggilan interview dengan domain portofolio live pribadi kamu!\n\n"
    "💳 *Biaya:* Rp10.000 (Sekali bayar / Akses Penuh)\n"
    "✨ *Fitur yang didapat:*\n"
    "• Custom Subdomain Web Portofolio (contoh: _namamu.boontrack.com_)\n"
    "• Tombol Download CV Instan (.docx / PDF)\n"
    "• Showroom Proyek & Pengalaman Kerja Interaktif\n"
    "• Integrasi Langsung ke Kontak WhatsApp & LinkedIn\n\n"
    "Silakan selesaikan pembayaran melalui link resmi berikut:\n"
    "👉 https://boontrack.com/pay/{user_id}\n\n"
    "_Setelah pembayaran terkonfirmasi via QRIS/DANA/Transfer, Career Page kamu otomatis langsung aktif live!_"
)

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
    msg_type = msg_obj.get("type")

    # --- FITUR 1: HANDLING UPLOAD DOKUMEN CV (PDF / DOCX) ---
    if msg_type == "document":
        doc_info = msg_obj.get("document", {})
        media_id = doc_info.get("id")
        filename = doc_info.get("filename", "document.pdf")

        await send_whatsapp_text(sender_wa_id, f"📥 Menerima dokumen *{filename}*. Sedang mengekstrak dan menganalisis skor ATS CV kamu... ⏳")

        try:
            file_bytes = await download_whatsapp_media(media_id)
            extracted_text = extract_text_from_bytes(file_bytes, filename)

            if not extracted_text or len(extracted_text) < 50:
                await send_whatsapp_text(sender_wa_id, "⚠️ Teks di dalam dokumen tidak terbaca atau terlalu pendek. Pastikan dokumen berupa PDF/DOCX teks (bukan hasil scan/gambar).")
                return web.Response(text="EVENT_RECEIVED", status=200)

            # Jalankan evaluasi review CV
            eval_result = cv_review_engine.evaluate_cv(extracted_text, target_position="General Professional")[cite: 2]
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
                "📊 *HASIL DIAGNOSIS SKOR DOKUMEN CV KAMU*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📄 *File:* {filename}\n"
                f"📈 *Overall Score:* *{filtered_data.get('overall_score', 0)} / 100*\n\n"
                "📌 *Breakdown Kategori:*\n"
                f"• ATS Compatibility: *{b.get('ats_compatibility', 70)}%*\n"
                f"• Relevansi Format: *{b.get('structure', 75)}%*\n"
                f"• Kualitas Pengalaman: *{b.get('experience', 80)}%*\n\n"
                "💡 *Poin Evaluasi AI:*\n"
                f"{findings_list}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔥 *Bikin HRD Langsung Lirik Lamaranmu!*\n\n"
                "Dapatkan *Career Page Portofolio Online Pribadi*.\n\n"
                "Pilih opsi selanjutnya:\n"
                "1️⃣ *Order Career Page (Rp10.000)*\n"
                "2️⃣ *Ajak 5 Teman (Gratis)*\n"
                "3️⃣ *Menu Utama*\n\n"
                "_Ketik angka 1, 2, atau 3 untuk memilih._"
            )
            GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "post_cv", "data": {}}
            await send_whatsapp_text(sender_wa_id, review_msg)

        except Exception as e:
            logger.error(f"[Upload Document Error] {e}")
            await send_whatsapp_text(sender_wa_id, "⚠️ Terjadi kendala saat memproses file dokumen. Silakan coba kirim ulang atau tempelkan isi teks CV kamu langsung.")

        return web.Response(text="EVENT_RECEIVED", status=200)

    # --- FITUR 2: HANDLING PESAN TEKS BIASA ---
    if msg_type != "text":
        await send_whatsapp_text(sender_wa_id, "Halo! Kirim pesan teks atau unggah file dokumen CV (.pdf / .docx). Ketik *Menu* untuk bantuan.")
        return web.Response(text="EVENT_RECEIVED", status=200)

    user_text = msg_obj.get("text", {}).get("body", "").strip()
    user_text_clean = user_text.lower()

    # 1. Reset / Menu Utama
    if user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "4"]:
        GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "menu", "data": {}}
        await send_whatsapp_text(sender_wa_id, GREETING_MENU_MSG)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 2. Tracking Referral Link Masuk
    if "ref_" in user_text_clean:
        ref_match = re.search(r"ref_(\d+)", user_text_clean)
        if ref_match:
            referrer_phone = ref_match.group(1)
            if referrer_phone != sender_wa_id:
                await track_event(sender_wa_id, "referral_signup", meta={"referrer_id": referrer_phone})

    # 3. Mode Review CV Masuk dari Link Tautan / Perintah
    if "mau review cv" in user_text_clean or "review cv" in user_text_clean:
        GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "review", "data": {}}
        intro_review = (
            "Halo! Siap, mari kita bedah skor dan kualitas ATS CV kamu. 📊✨\n\n"
            "Kamu bisa langsung *kirim file CV (PDF / DOCX)* ke chat ini, atau *salin-tempel (copy-paste) teks CV kamu* sekarang ya."
        )
        await send_whatsapp_text(sender_wa_id, intro_review)
        return web.Response(text="EVENT_RECEIVED", status=200)

    current_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    current_mode = current_session.get("mode", "menu")

    # 4. Alur Step Pembuatan CV Sedang Berjalan (Step 1 s/d 10)
    if current_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        for msg in result.get("messages", [result["reply_text"]]):
            await send_whatsapp_text(sender_wa_id, msg)
        
        if result.get("is_completed"):
            current_session["mode"] = "post_cv"
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 5. INTENT EXPLICIT: Order / Beli Career Page (Prioritas Tinggi)
    if (
        "order career" in user_text_clean
        or "order page" in user_text_clean
        or "beli career" in user_text_clean
        or "bayar" in user_text_clean
        or "qris" in user_text_clean
        or "10000" in user_text_clean
        or "10.000" in user_text_clean
        or (current_mode == "post_cv" and user_text_clean in ["1", "order", "beli"])
    ):
        order_msg = PAYMENT_OFFER_MSG_TEMPLATE.format(user_id=sender_wa_id)
        await send_whatsapp_text(sender_wa_id, order_msg)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 6. INTENT EXPLICIT: Program Referral / Gratis 5 Teman
    if user_text_clean in ["2", "referral", "cek referral", "gratis", "ajak teman"] or "referral" in user_text_clean:
        try:
            invited_count = await count_referrals(sender_wa_id)
        except Exception:
            invited_count = 0

        ref_link = f"https://boontrack.com/ref/{sender_wa_id}"
        ref_msg = (
            "🎁 *PROGRAM CAREER PAGE GRATIS VIA REFERRAL*\n\n"
            "Silakan share link berikut ke teman-temanmu. Semangat ya! 🚀\n\n"
            f"📊 *Status Referral Kamu:* *({invited_count}/5)* teman bergabung\n"
            f"🔗 *Link Referral Kamu:* {ref_link}\n\n"
            "Jika sudah mencapai 5 teman, Career Page profesional senilai Rp10.000 otomatis aktif gratis untukmu!"
        )
        await send_whatsapp_text(sender_wa_id, ref_msg)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 7. Edit Bagian CV
    if current_mode == "post_cv" and (user_text_clean == "3" or "edit" in user_text_clean):
        current_session["mode"] = "builder"
        current_session["step"] = 1
        edit_msg = (
            "🔄 *Perbarui Bagian CV*\n\n"
            "Mari kita perbarui data CV kamu dari awal. Data draft sebelumnya akan disesuaikan kembali.\n\n"
            "📝 *Langkah 1/10*\nSiapa nama lengkapmu?"
        )
        await send_whatsapp_text(sender_wa_id, edit_msg)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 8. Trigger Buat CV dari Menu
    if user_text_clean in ["1", "buat cv", "bikin cv", "buat cv baru"] or "buat cv" in user_text_clean:
        current_session["mode"] = "builder"
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        await send_whatsapp_text(sender_wa_id, result["reply_text"])
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 9. Mode Analisis Review CV Teks Mentah
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
            current_session["mode"] = "post_cv"
            await send_whatsapp_text(sender_wa_id, review_msg)
        except Exception as e:
            logger.error(f"[WA Review Error] {e}")
            await send_whatsapp_text(sender_wa_id, "⚠️ Gagal menganalisis CV. Pastikan teks CV cukup lengkap lalu coba lagi.")
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 10. AI Konsultasi Karir Otomatis (Fallback Umum)
    ai_reply = await ai_gateway.generate(user_message=user_text, context={"user_id": sender_wa_id, "feature": "career_consultation"})
    if ai_reply:
        await send_whatsapp_text(sender_wa_id, ai_reply)
    else:
        await send_whatsapp_text(sender_wa_id, MENU_INVALID_MSG)

    return web.Response(text="EVENT_RECEIVED", status=200)

def register_whatsapp_career_routes(app: web.Application):
    app.router.add_get("/api/whatsapp/webhook", verify_webhook)
    app.router.add_post("/api/whatsapp/webhook", handle_incoming_whatsapp)