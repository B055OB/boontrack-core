import re
import os
import io
import asyncio
import random
import logging
from typing import Tuple, Optional
from aiohttp import web
from app.services.whatsapp_service import send_whatsapp_text, send_whatsapp_image
from app.constants.messages import MENU_INVALID_MSG
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service
from app.services.ai_service import ai_gateway
from app.core.database import track_event, count_referrals
from app.services.document_parser_service import download_whatsapp_media, extract_text_from_bytes
from app.services.qris_engine import generate_dynamic_qris_payload, render_qris_image
from app.services.pricing_service import get_career_product
from app.core.config import settings

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")


def get_user_display_name(sender_wa_id: str) -> str:
    """Mengambil nama pengguna dari session atau data CV."""
    user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
    user_data = user_session.get("data", {})
    return user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""


def get_whatsapp_full_menu(sender_wa_id: str) -> str:
    """Menghasilkan pesan pembuka ramah & anti-overclaim sesuai arahan briefing."""
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
    """Mengirim hasil diagnosis 3 breakdown skor + catatan praktisi HR dan auto-trigger hook upsell Rp25.000."""
    overall_score = filtered_data.get("overall_score", 0)
    b = filtered_data.get("breakdown_scores", {})

    ats_comp = b.get("ats_compatibility", 85)
    keyword_score = b.get("keyword", b.get("structure", 80))
    exp_score = b.get("experience", 85)

    findings = filtered_data.get("findings", [])
    findings_list = "\n".join([f"• {f}" for f in findings]) if findings else "• Format dasar CV sudah terbaca dengan baik."

    # 1. Output Diagnosis 3 Breakdown Skor AI Lengkap
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

    # 2. Jeda 7 Detik Sesuai Funnel
    await asyncio.sleep(7)

    # 3. Pesan Upsell Premium CV Rewrite (Rp25.000)
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

    # Inisialisasi session user
    user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    user_data = user_session.setdefault("data", {})

    # Ekstraksi Nama Profil WhatsApp
    contacts = value_data.get("contacts", [])
    if contacts and isinstance(contacts, list) and len(contacts) > 0:
        raw_profile_name = contacts[0].get("profile", {}).get("name", "").strip()
        if raw_profile_name and not user_data.get("nama_panggilan"):
            user_data["nama_panggilan"] = raw_profile_name
            user_data["nama_lengkap"] = raw_profile_name

    # =========================================================================
    # 1. HANDLING DOKUMEN CV (.PDF / .DOCX)
    # =========================================================================
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

            # Simpan parsed text untuk reuse di modul rewrite (Zero-Reinput)
            user_session["parsed_cv_text"] = extracted_text

            eval_result = cv_review_engine.evaluate_cv(extracted_text, target_position="General Professional")
            filtered_data = cv_review_service.filter_entitlement_response(eval_result, is_premium=False)

            try:
                numeric_user_id = int(re.sub(r"\D", "", str(sender_wa_id)))
                await cv_review_service.save_review(
                    user_id=numeric_user_id,
                    target_position="General Professional",
                    overall_score=filtered_data.get("overall_score", 0),
                    quality_score=filtered_data.get("breakdown_scores", {}).get("ats_compatibility", 0),
                    job_match_score=filtered_data.get("breakdown_scores", {}).get("keyword", 0),
                    evidence_score=filtered_data.get("breakdown_scores", {}).get("experience", 0),
                    review_json=filtered_data,
                    confidence_level=eval_result.get("confidence", {}).get("level", "MEDIUM")
                )
            except Exception as dbe:
                logger.error(f"[DB Save Review Error] {dbe}")

            user_session["mode"] = "post_review"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True

            # Kirim hasil review gratis + jalankan task jeda upsell
            asyncio.create_task(deliver_review_and_trigger_upsell(sender_wa_id, filtered_data, filename))

        except Exception as e:
            logger.error(f"[Upload Document Error] {e}")
            await send_whatsapp_text(
                sender_wa_id,
                "⚠️ Terjadi kendala saat membaca dokumen. Silakan kirim ulang atau tempel teks CV kamu."
            )

        return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 2. HANDLING PESAN TEKS
    # =========================================================================
    if msg_type != "text":
        await send_whatsapp_text(
            sender_wa_id,
            "Halo! Kirim pesan teks atau unggah file dokumen CV (.pdf / .docx). Ketik *Menu* untuk bantuan."
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    user_text = msg_obj.get("text", {}).get("body", "").strip()
    user_text_clean = user_text.lower().strip()

    # Tracking Referral
    if "ref_" in user_text_clean:
        ref_match = re.search(r"ref_(\d+)", user_text_clean)
        if ref_match:
            referrer_phone = ref_match.group(1)
            if referrer_phone != sender_wa_id:
                try:
                    await track_event(sender_wa_id, "referral_signup", meta={"referrer_id": referrer_phone})
                except Exception as dbe:
                    logger.debug(f"[Referral Track Error] {dbe}")

    # Reset / Entry Point
    if user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "home", "/menu", "/start"]:
        await track_event(sender_wa_id, "source", meta={"source": "whatsapp_direct"})
        await track_event(sender_wa_id, "referral_code", meta={"code": "PROMO_CAREER"})

        current_data = user_session.get("data", {})
        GLOBAL_USER_STATES[sender_wa_id] = {
            "step": 0,
            "mode": "menu",
            "data": current_data
        }
        await send_whatsapp_text(sender_wa_id, get_whatsapp_full_menu(sender_wa_id))
        return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 3. TRIGGER UPSELL REWRITE (DYNAMIC QRIS DANA Rp25.000)
    # =========================================================================
    if user_text_clean in ["rewrite", "perbaiki", "mau rewrite", "ambil rewrite"]:
        await track_event(sender_wa_id, "rewrite_clicked")

        product = await get_career_product("career-rewrite-25k")
        nominal = product.get("final_price", 25000)

        # Generate Dynamic QRIS DANA Bisnis
        raw_static_qris = settings.DANA_STATIC_QRIS
        dynamic_payload = generate_dynamic_qris_payload(raw_static_qris, nominal)
        qr_img_bytes = render_qris_image(dynamic_payload)

        temp_qr_path = f"/tmp/qris_{sender_wa_id}.png"
        try:
            with open(temp_qr_path, "wb") as f:
                f.write(qr_img_bytes.getvalue())
        except Exception:
            temp_qr_path = f"qris_{sender_wa_id}.png"
            with open(temp_qr_path, "wb") as f:
                f.write(qr_img_bytes.getvalue())

        caption_text = (
            f"📱 *QRIS DANA BISNIS - PREMIUM CV REWRITE*\n\n"
            f"🏷️ *Nominal:* Rp{nominal:,} *(Terkunci Otomatis)*\n\n"
            "1. Scan QRIS di atas melalui aplikasi E-Wallet (DANA, GoPay, OVO, ShopeePay) atau Mobile Banking apa pun.\n"
            "2. Nominal sudah otomatis terkunci presisi Rp25.000 tanpa perlu input manual.\n"
            "3. Setelah transfer selesai, sistem akan otomatis mendeteksi dan langsung memproses CV ATS versi terbaik Anda!"
        )

        await track_event(sender_wa_id, "payment_created", meta={"amount": nominal, "type": "dana_qris_dynamic"})
        user_session["mode"] = "awaiting_rewrite_payment"

        await send_whatsapp_image(sender_wa_id, image_path=temp_qr_path, caption=caption_text)
        return web.Response(text="EVENT_RECEIVED", status=200)

    current_mode = user_session.get("mode", "menu")

    # =========================================================================
    # 4. WIZARD STEP CV BUILDER (Step 1 s/d 10)
    # =========================================================================
    if user_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        for msg in result.get("messages", [result["reply_text"]]):
            await send_whatsapp_text(sender_wa_id, msg)

        if result.get("is_completed"):
            await track_event(sender_wa_id, "cv_basic_completed")
            user_session["mode"] = "post_cv"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True
        return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 5. MODE REVIEW CV DARI TEKS MANUAL (State 1: Opsi 1)
    # =========================================================================
    if current_mode == "review":
        if len(user_text.split()) < 6:
            await send_whatsapp_text(
                sender_wa_id,
                "⚠️ Teks CV terlalu singkat. Silakan tempel (paste) teks CV lengkapmu atau kirimkan file dokumen (.pdf / .docx)."
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
            await send_whatsapp_text(
                sender_wa_id,
                "⚠️ Gagal menganalisis teks CV. Pastikan konten cukup lengkap lalu coba lagi."
            )
        return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 6. MENU UTAMA (Pilihan 1 atau 2 Sesuai Promo)
    # =========================================================================
    if current_mode == "menu":
        # Opsi 1: Review CV Gratis
        if user_text_clean in ["1", "review cv", "review & optimasi cv", "cek ats", "1️⃣"]:
            user_session["mode"] = "review"
            intro_review = (
                "Silakan kirimkan dokumen CV Anda (*format PDF/DOCX*) atau *salin-tempel (copy-paste) teks riwayat CV* Anda langsung di chat ini untuk kami bedah secara gratis."
            )
            await send_whatsapp_text(sender_wa_id, intro_review)
            return web.Response(text="EVENT_RECEIVED", status=200)

        # Opsi 2: Bikin CV Dasar Gratis
        if user_text_clean in ["2", "buat cv", "bikin cv", "bikin cv dasar", "2️⃣"]:
            user_session["mode"] = "builder"
            result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
            await send_whatsapp_text(sender_wa_id, result["reply_text"])
            return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 7. FALLBACK RESPONS AI
    # =========================================================================
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