import re
import os
import io
import random
import asyncio
import logging
from typing import Tuple, Optional
from aiohttp import web
from app.services.whatsapp_service import send_whatsapp_text, send_whatsapp_image, send_whatsapp_buttons
from app.constants.messages import MENU_INVALID_MSG
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service
from app.services.ai_service import ai_gateway
from app.core.database import track_event
from app.services.document_parser_service import download_whatsapp_media, extract_text_from_bytes
from app.services.reconciliation_service import generate_unique_payment_intent
from app.core.config import settings

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")


def get_user_display_name(sender_wa_id: str) -> str:
    user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
    user_data = user_session.get("data", {})
    return user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""


async def send_whatsapp_menu_buttons(sender_wa_id: str):
    nama = get_user_display_name(sender_wa_id)
    greeting = f", *{nama}*" if nama else ""

    body = (
        f"Halo{greeting}! Selamat datang di *BoonTrack Career*. 💼\n\n"
        "Layanan kami dikembangkan dengan pendekatan ATS-friendly dan masukan HR Senior.\n\n"
        "Silakan pilih menu gratis Anda di bawah ini:"
    )

    buttons = [
        {"id": "btn_review", "title": "🔍 Review CV"},
        {"id": "btn_builder", "title": "📝 Bikin CV Dasar"}
    ]

    await send_whatsapp_buttons(
        to_phone=sender_wa_id,
        body_text=body,
        buttons=buttons,
        header_text="BOONTRACK CAREER",
        footer_text="Pilih salah satu tombol di atas"
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
        "Sistem akan merombak total deskripsi pengalaman Anda mengikuti struktur, diksi, dan gaya rekrutmen level tinggi.\n\n"
        "🏷️ *Investasi:* Rp25.000"
    )

    upsell_buttons = [
        {"id": "btn_rewrite", "title": "🚀 Ambil Rewrite"},
        {"id": "btn_menu", "title": "🏠 Menu Utama"}
    ]

    await send_whatsapp_buttons(
        to_phone=sender_wa_id,
        body_text=upsell_msg,
        buttons=upsell_buttons,
        footer_text="Pilih tombol untuk melanjutkan"
    )
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

    # 2. EKSTRAKSI TEKS & TOMBOL INTERAKTIF
    user_text = ""
    button_id = ""

    if msg_type == "text":
        user_text = msg_obj.get("text", {}).get("body", "").strip()
    elif msg_type == "interactive":
        interactive_data = msg_obj.get("interactive", {})
        if interactive_data.get("type") == "button_reply":
            button_id = interactive_data.get("button_reply", {}).get("id", "")
            user_text = interactive_data.get("button_reply", {}).get("title", "")
    else:
        await send_whatsapp_menu_buttons(sender_wa_id)
        return web.Response(text="EVENT_RECEIVED", status=200)

    user_text_clean = user_text.lower().strip()

    # Reset / Entry
    if button_id == "btn_menu" or user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "home", "/menu", "/start"]:
        current_data = user_session.get("data", {})
        GLOBAL_USER_STATES[sender_wa_id] = {
            "step": 0,
            "mode": "menu",
            "data": current_data
        }
        await send_whatsapp_menu_buttons(sender_wa_id)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 3. TRIGGER REWRITE (QRIS ASLI + KODE UNIK SMART RECONCILIATION)
    if button_id == "btn_rewrite" or user_text_clean in ["rewrite", "perbaiki", "mau rewrite", "ambil rewrite", "🚀 ambil rewrite"]:
        await track_event(sender_wa_id, "rewrite_clicked")

        intent = generate_unique_payment_intent(
            tenant_id="boontrack_career",
            base_amount=25000,
            product_id="premium_cv_rewrite",
            user_id=sender_wa_id
        )

        exact_amount = intent["total_amount"]
        unique_code = intent["unique_code"]
        invoice_id = intent["invoice_id"]

        user_session["mode"] = "awaiting_rewrite_payment"
        user_session["active_invoice"] = invoice_id

        caption_text = (
            "📱 *INVOICE PEMBAYARAN PREMIUM CV REWRITE*\n"
            f"🧾 *No. Invoice:* `{invoice_id}`\n\n"
            f"🏷️ *TOTAL TRANSFER:* `{exact_amount}`\n"
            f"*(Rp{exact_amount:,} - Sudah termasuk 3 digit kode unik: {unique_code})*\n\n"
            "📌 *Panduan Pembayaran QRIS:*\n"
            "1. *Simpan / Screenshot* gambar QRIS di atas ke galeri HP kamu.\n"
            "2. Buka aplikasi m-Banking (*BCA, Mandiri, BRI, BNI*) atau e-Wallet (*GoPay, OVO, DANA, ShopeePay*).\n"
            "3. Pilih menu *Scan QRIS* ➔ ketuk *ikon Galeri / Unggah Gambar* ➔ pilih gambar QRIS tadi.\n"
            f"4. Masukkan nominal persis: `{exact_amount}`\n\n"
            f"⚠️ *PENTING:* Silakan *salin (copy)* angka `{exact_amount}` di atas agar jumlah transfer tepat. "
            "Sistem verifikasi otomatis *tidak akan dapat memproses pesanan Anda* jika nominal yang dimasukkan berbeda."
        )

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        asset_candidates = [
            os.path.join(base_dir, "assets", "qris.png"),
            os.path.join(base_dir, "assets", "qris.jpg"),
            os.path.join(base_dir, "assets", "qris_boontrack.png"),
            os.path.join(base_dir, "assets", "qris_dana.jpg"),
            os.path.join(base_dir, "assets", "qris_dana.png"),
            os.path.join(os.getcwd(), "assets", "qris.png"),
            os.path.join(os.getcwd(), "assets", "qris.jpg"),
        ]
        found_file = next((p for p in asset_candidates if os.path.exists(p)), None)

        if found_file:
            await send_whatsapp_image(sender_wa_id, image_path_or_bytes=found_file, caption=caption_text)
        else:
            await send_whatsapp_text(sender_wa_id, caption_text)

        return web.Response(text="EVENT_RECEIVED", status=200)

    current_mode = user_session.get("mode", "menu")

    # 4. HANDLE BUTTON PILIHAN MENU UTAMA
    if button_id == "btn_review" or (current_mode == "menu" and user_text_clean in ["1", "review cv", "🔍 review cv"]):
        user_session["mode"] = "review"
        intro_review = (
            "Silakan kirimkan dokumen CV Anda (*format PDF/DOCX*) atau *salin-tempel (copy-paste) teks riwayat CV* Anda langsung di chat ini untuk kami bedah secara gratis."
        )
        await send_whatsapp_text(sender_wa_id, intro_review)
        return web.Response(text="EVENT_RECEIVED", status=200)

    if button_id == "btn_builder" or (current_mode == "menu" and user_text_clean in ["2", "bikin cv", "📝 bikin cv dasar"]):
        user_session["mode"] = "builder"
        user_session["step"] = 0
        result = await process_unified_cv_step(sender_wa_id, "", platform="whatsapp")
        
        lang_buttons = [
            {"id": "lang_en_id", "title": "EN (B. Indo)"},
            {"id": "lang_id", "title": "B. Indonesia"},
            {"id": "lang_en", "title": "Full English"}
        ]
        await send_whatsapp_buttons(
            to_phone=sender_wa_id,
            body_text=result["reply_text"],
            buttons=lang_buttons,
            footer_text="Klik pilihan bahasa di atas"
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 5. HANDLE PILIHAN BAHASA VIA BUTTON
    if button_id.startswith("lang_"):
        lang_choice = "1" if button_id == "lang_en_id" else ("2" if button_id == "lang_id" else "3")
        result = await process_unified_cv_step(sender_wa_id, lang_choice, platform="whatsapp")
        await send_whatsapp_text(sender_wa_id, result["reply_text"])
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 6. CV BUILDER WIZARD (Step 2 - 10)
    if current_mode == "builder" or user_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        messages_to_send = result.get("messages", [])
        if not messages_to_send and result.get("reply_text"):
            messages_to_send = [result["reply_text"]]

        for msg in messages_to_send:
            await send_whatsapp_text(sender_wa_id, msg)

        if result.get("is_completed"):
            user_session["mode"] = "post_cv"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 7. REVIEW DARI TEKS MANUAL
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

    # 8. FALLBACK AI
    ai_reply = await ai_gateway.generate(
        user_message=user_text,
        context={"user_id": sender_wa_id, "feature": "career_consultation"}
    )
    if ai_reply:
        await send_whatsapp_text(sender_wa_id, ai_reply)
    else:
        await send_whatsapp_menu_buttons(sender_wa_id)

    return web.Response(text="EVENT_RECEIVED", status=200)


def register_whatsapp_career_routes(app: web.Application):
    app.router.add_get("/api/whatsapp/webhook", verify_webhook)
    app.router.add_post("/api/whatsapp/webhook", handle_incoming_whatsapp)