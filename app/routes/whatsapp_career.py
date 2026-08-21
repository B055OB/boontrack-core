import re
import os
import io
import asyncio
import logging
from typing import Tuple, Optional
from aiohttp import web
from app.services.whatsapp_service import send_whatsapp_text, send_whatsapp_image
from app.constants.messages import MENU_INVALID_MSG
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service
from app.services.ai_service import ai_gateway
from app.core.database import track_event
from app.services.document_parser_service import download_whatsapp_media, extract_text_from_bytes
from app.services.pricing_service import get_career_product

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")


def get_user_display_name(sender_wa_id: str) -> str:
    user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
    user_data = user_session.get("data", {})
    return user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""


def get_whatsapp_full_menu(sender_wa_id: str) -> str:
    nama = get_user_display_name(sender_wa_id)
    greeting = f", *{nama}*" if nama else ""

    return (
        f"Halo{greeting}! Selamat datang di *BoonTrack Career*. 💼\n\n"
        "Sistem kami disusun dengan pendekatan ATS-friendly dan metodologi review "
        "yang dikembangkan bersama masukan profesional HR.\n\n"
        "Kode promo spesial Anda aktif hari ini. Silakan pilih layanan *GRATIS* Anda:\n\n"
        "🔍 *1. Review CV*\n"
        "_(Sistem membedah CV lama Anda, mengecek keterbacaan ATS, dan memberi catatan evaluasi)_\n\n"
        "📝 *2. Bikin CV Dasar*\n"
        "_(Sistem menyusun data Anda ke format template standar yang rapi, bersih, dan ramah ATS)_\n\n"
        "Balas *1* atau *2* untuk memulai."
    )


async def deliver_review_and_trigger_upsell(sender_wa_id: str, filtered_data: dict, filename: str = "Dokumen CV"):
    overall_score = filtered_data.get("overall_score", 0)
    b = filtered_data.get("breakdown_scores", {})

    ats_comp = b.get("ats_compatibility", 85)
    keyword_score = b.get("keyword", b.get("structure", 80))
    exp_score = b.get("experience", 85)

    findings = filtered_data.get("findings", [])
    findings_list = "\n".join([f"• {f}" for f in findings]) if findings else "• Format dasar CV sudah terbaca dengan baik."

    diagnosis_msg = (
        f"Analisis CV Anda selesai! 📊\n\n"
        f"🎯 *Skor Keterbacaan ATS:* {overall_score}/100\n\n"
        f"📌 *Breakdown Evaluasi Mendalam:*\n"
        f"• ⚙️ ATS Compatibility: *{ats_comp}/100*\n"
        f"• 🎯 Relevansi Kata Kunci: *{keyword_score}/100*\n"
        f"• 📈 Kualitas Pengalaman: *{exp_score}/100*\n\n"
        f"💡 *Catatan Evaluasi Praktisi HR:*\n"
        f"{findings_list}\n\n"
        f"_Anda dapat menggunakan catatan di atas sebagai acuan revisi mandiri._"
    )
    await send_whatsapp_text(sender_wa_id, diagnosis_msg)
    await track_event(sender_wa_id, "review_completed", meta={"score": overall_score, "file": filename})

    await asyncio.sleep(7)

    upsell_msg = (
        "Ingin melihat versi terbaik dari potensi profesional Anda? 🚀\n\n"
        "Gunakan layanan: *Premium CV Rewrite (Standar HR Senior)*.\n\n"
        "Disusun dengan pendekatan ATS-friendly dan metodologi review yang dikembangkan "
        "bersama masukan profesional HR. Sistem akan merombak total deskripsi pengalaman Anda "
        "mengikuti struktur, diksi, dan gaya bahasa rekrutmen level tinggi.\n\n"
        "Jadikan CV ini sebagai benchmark & motivasi untuk melihat potensi maksimal profil karier Anda.\n\n"
        "🏷️ *Investasi:* Rp25.000\n\n"
        "Balas *REWRITE* untuk memproses versi terbaik CV Anda."
    )
    await send_whatsapp_text(sender_wa_id, upsell_msg)
    await track_event(sender_wa_id, "rewrite_offer_shown")


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

    value_data = changes[0].get("value", {})
    messages = value_data.get("messages", [])
    if not messages:
        return web.Response(text="EVENT_RECEIVED", status=200)

    msg_obj = messages[0]
    sender_wa_id = msg_obj.get("from")
    msg_type = msg_obj.get("type")

    user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    user_data = user_session.setdefault("data", {})

    contacts = value_data.get("contacts", [])
    if contacts and isinstance(contacts, list) and len(contacts) > 0:
        raw_profile_name = contacts[0].get("profile", {}).get("name", "").strip()
        if raw_profile_name and not user_data.get("nama_panggilan"):
            user_data["nama_panggilan"] = raw_profile_name
            user_data["nama_lengkap"] = raw_profile_name

    # 1. HANDLING DOKUMEN CV
    if msg_type == "document":
        doc_info = msg_obj.get("document", {})
        media_id = doc_info.get("id")
        filename = doc_info.get("filename", "document.pdf")

        await send_whatsapp_text(
            sender_wa_id,
            f"📥 Menerima dokumen *{filename}*. Sedang menganalisis struktur & skor ATS CV kamu... ⏳"
        )

        try:
            file_bytes = await download_whatsapp_media(media_id)
            extracted_text = extract_text_from_bytes(file_bytes, filename)

            if not extracted_text or len(extracted_text) < 50:
                await send_whatsapp_text(
                    sender_wa_id,
                    "⚠️ Teks di dalam dokumen tidak dapat diekstrak. Pastikan file PDF/DOCX berisi teks asli."
                )
                return web.Response(text="EVENT_RECEIVED", status=200)

            user_session["parsed_cv_text"] = extracted_text
            eval_result = cv_review_engine.evaluate_cv(extracted_text, target_position="General Professional")
            filtered_data = cv_review_service.filter_entitlement_response(eval_result, is_premium=False)

            user_session["mode"] = "post_review"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True

            asyncio.create_task(deliver_review_and_trigger_upsell(sender_wa_id, filtered_data, filename))

        except Exception as e:
            logger.error(f"[Upload Document Error] {e}")
            await send_whatsapp_text(
                sender_wa_id,
                "⚠️ Terjadi kendala saat membaca dokumen. Silakan kirim ulang atau tempel teks CV kamu."
            )

        return web.Response(text="EVENT_RECEIVED", status=200)

    # 2. HANDLING TEKS
    if msg_type != "text":
        await send_whatsapp_text(
            sender_wa_id,
            "Halo! Kirim pesan teks atau unggah file dokumen CV (.pdf / .docx). Ketik *Menu* untuk bantuan."
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    user_text = msg_obj.get("text", {}).get("body", "").strip()
    user_text_clean = user_text.lower().strip()

    # Reset / Entry
    if user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "home", "/menu", "/start"]:
        current_data = user_session.get("data", {})
        GLOBAL_USER_STATES[sender_wa_id] = {
            "step": 0,
            "mode": "menu",
            "data": current_data
        }
        await send_whatsapp_text(sender_wa_id, get_whatsapp_full_menu(sender_wa_id))
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 3. TRIGGER REWRITE (QRIS BOONTRACK DIATAS)
    if user_text_clean in ["rewrite", "perbaiki", "mau rewrite", "ambil rewrite"]:
        await track_event(sender_wa_id, "rewrite_clicked")
        user_session["mode"] = "awaiting_rewrite_payment"
        user_session["active_payment"] = {"amount": 25000, "product": "career-rewrite-25k"}

        caption_text = (
            "📱 *PEMBAYARAN PREMIUM CV REWRITE*\n\n"
            "🏷️ *Nominal:* Rp25.000\n\n"
            "1. Scan *QRIS BoonTrack diatas* melalui aplikasi E-Wallet (GoPay, OVO, DANA, ShopeePay) atau Mobile Banking (BCA, Mandiri, BRI, BNI, dll).\n"
            "2. Masukkan/pastikan nominal pembayaran Rp25.000.\n"
            "3. Setelah pembayaran berhasil, AI akan otomatis mendeteksi dan langsung memproses CV ATS versi terbaik Anda!"
        )

        qris_image_url = "https://boontrack-core-production.up.railway.app/assets/qris.png"

        sent = await send_whatsapp_image(sender_wa_id, image_path=qris_image_url, caption=caption_text)
        if not sent:
            await send_whatsapp_text(sender_wa_id, caption_text)

        return web.Response(text="EVENT_RECEIVED", status=200)

    current_mode = user_session.get("mode", "menu")

    # 4. CV BUILDER WIZARD
    if user_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        for msg in result.get("messages", [result["reply_text"]]):
            await send_whatsapp_text(sender_wa_id, msg)

        if result.get("is_completed"):
            user_session["mode"] = "post_cv"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 5. REVIEW DARI TEKS MANUAL
    if current_mode == "review":
        if len(user_text.split()) < 6:
            await send_whatsapp_text(
                sender_wa_id,
                "⚠️ Teks CV terlalu singkat. Silakan tempel teks CV lengkap atau kirim file dokumen (.pdf / .docx)."
            )
            return web.Response(text="EVENT_RECEIVED", status=200)

        nama = get_user_display_name(sender_wa_id)
        sapaan = f", *{nama}*" if nama else ""
        await send_whatsapp_text(sender_wa_id, f"⏳ *Sedang menganalisis struktur & skor ATS CV kamu{sapaan}...*")
        try:
            user_session["parsed_cv_text"] = user_text
            eval_result = cv_review_engine.evaluate_cv(user_text, target_position="General Professional")
            filtered_data = cv_review_service.filter_entitlement_response(eval_result, is_premium=False)

            user_session["step"] = 0
            user_session["mode"] = "post_review"
            user_session.setdefault("data", {})["has_completed_cv"] = True

            asyncio.create_task(deliver_review_and_trigger_upsell(sender_wa_id, filtered_data, "Manual Text Input"))
        except Exception as e:
            logger.error(f"[WA Review Error] {e}")
            await send_whatsapp_text(sender_wa_id, "⚠️ Gagal menganalisis teks CV.")
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 6. MENU UTAMA
    if current_mode == "menu":
        if user_text_clean in ["1", "review cv", "review & optimasi cv", "cek ats", "1️⃣"]:
            user_session["mode"] = "review"
            intro_review = (
                "Silakan kirimkan dokumen CV Anda (*format PDF/DOCX*) atau *salin-tempel (copy-paste) teks riwayat CV* Anda langsung di chat ini untuk kami bedah secara gratis."
            )
            await send_whatsapp_text(sender_wa_id, intro_review)
            return web.Response(text="EVENT_RECEIVED", status=200)

        if user_text_clean in ["2", "buat cv", "bikin cv", "bikin cv dasar", "2️⃣"]:
            user_session["mode"] = "builder"
            result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
            await send_whatsapp_text(sender_wa_id, result["reply_text"])
            return web.Response(text="EVENT_RECEIVED", status=200)

    ai_reply = await ai_gateway.generate(
        user_message=user_text,
        context={"user_id": sender_wa_id, "feature": "career_consultation"}
    )
    if ai_reply:
        await send_whatsapp_text(sender_wa_id, ai_reply)
    else:
        await send_whatsapp_text(sender_wa_id, MENU_INVALID_MSG)

    return web.Response(text="EVENT_RECEIVED", status=200)


def register_whatsapp_career_routes(app: web.Application):
    app.router.add_get("/api/whatsapp/webhook", verify_webhook)
    app.router.add_post("/api/whatsapp/webhook", handle_incoming_whatsapp)