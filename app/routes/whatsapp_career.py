import re
import os
import io
import random
import asyncio
import logging
from datetime import datetime
from typing import Tuple, Optional
from aiohttp import web

from app.services.whatsapp_service import (
    send_whatsapp_text, 
    send_whatsapp_image, 
    send_whatsapp_buttons, 
    log_to_supabase_messages
)
from app.constants.messages import MENU_INVALID_MSG
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service
from app.services.ai_service import ai_gateway
from app.core.database import track_event
from app.services.document_parser_service import download_whatsapp_media, extract_text_from_bytes
from app.services.reconciliation_service import generate_unique_payment_intent, PAYMENT_INTENTS
from app.services.receipt_ocr_service import parse_receipt_image
from app.core.config import settings

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")
CAREER_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def get_user_display_name(sender_wa_id: str) -> str:
    user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
    user_data = user_session.get("data", {})
    return user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""


async def send_whatsapp_menu_buttons(sender_wa_id: str):
    nama = get_user_display_name(sender_wa_id)
    greeting = f", *{nama}*" if nama else ""

    body = (
        f"Halo{greeting}! Selamat datang di *BoonTrack Career*. 💼\n\n"
        "Layanan kami dikembangkan dengan standar ATS dan kurasi HR Senior.\n\n"
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
        footer_text="Pilih salah satu opsi di atas",
        tenant_id=CAREER_TENANT_ID
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
        f"📌 *Breakdown Evaluasi:*\n"
        f"• ⚙️ ATS Compatibility: *{ats_comp}/100*\n"
        f"• 🎯 Relevansi Kata Kunci: *{keyword_score}/100*\n"
        f"• 📈 Kualitas Pengalaman: *{exp_score}/100*\n\n"
        f"💡 *Catatan Praktisi HR:*\n"
        f"{findings_list}\n\n"
        f"_Anda dapat menggunakan catatan di atas sebagai panduan revisi._"
    )
    await send_whatsapp_text(sender_wa_id, diagnosis_msg, tenant_id=CAREER_TENANT_ID)
    await track_event(sender_wa_id, "review_completed", meta={"score": overall_score, "file": filename})

    await asyncio.sleep(6)

    upsell_msg = (
        "Ingin melihat versi terbaik dari potensi profesional Anda? 🚀\n\n"
        "Gunakan layanan: *Premium CV Rewrite (Standar HR Senior)*.\n\n"
        "Sistem akan merombak total struktur, diksi pencapaian, dan dampak kerja CV Anda.\n\n"
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
        footer_text="Pilih opsi untuk melanjutkan",
        tenant_id=CAREER_TENANT_ID
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

    # 1. HANDLING GAMBAR (AI OCR SCANNER UNTUK BUKTI TRANSFER)
    if msg_type == "image":
        image_info = msg_obj.get("image", {})
        media_id = image_info.get("id")

        await log_to_supabase_messages(
            sender=f"Customer / +{sender_wa_id}",
            text="[Mengirim Gambar Bukti Transfer]",
            tenant_id=CAREER_TENANT_ID
        )

        if user_session.get("mode") == "awaiting_rewrite_payment":
            await send_whatsapp_text(
                sender_wa_id,
                "🔍 *Mendeteksi bukti transfer...* AI sedang memverifikasi struk pembayaran Anda. Mohon tunggu sebentar ⏳",
                tenant_id=CAREER_TENANT_ID
            )

            try:
                image_bytes = await download_whatsapp_media(media_id)
                receipt_data = await parse_receipt_image(image_bytes)

                if not receipt_data or not receipt_data.get("is_transfer_receipt"):
                    await send_whatsapp_text(
                        sender_wa_id,
                        "⚠️ Gambar yang dikirim tidak terdeteksi sebagai bukti transfer yang valid. Pastikan foto memperlihatkan nominal dan status pembayaran.",
                        tenant_id=CAREER_TENANT_ID
                    )
                    return web.Response(text="EVENT_RECEIVED", status=200)

                amount = int(receipt_data.get("amount", 0))

                active_invoice = user_session.get("active_invoice")
                target_intent = PAYMENT_INTENTS.get(active_invoice) if active_invoice else None
                base_price = target_intent.get("base_amount", 25000) if target_intent else 25000

                min_allowed = base_price
                max_allowed = base_price + 999

                if min_allowed <= amount <= max_allowed:
                    if target_intent:
                        target_intent["status"] = "PAID"
                        target_intent["paid_at"] = datetime.now()
                        target_intent["transaction_reference"] = f"OCR_VERIFIED: Rp{amount:,}"

                    user_session["is_premium_paid"] = True
                    user_session["mode"] = "post_review"

                    success_msg = (
                        f"🎉 *BUKTI TRANSFER TERVERIFIKASI!*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧾 *Invoice:* `{active_invoice or '-'}`\n"
                        f"💰 *Nominal Terbaca:* Rp{amount:,}\n"
                        f"📊 *Status:* Sah (Masuk Rentang Rp{min_allowed:,} - Rp{max_allowed:,})\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        "Terima kasih! AI BoonTrack sedang memproses perombakan CV Anda ke standar HR Senior. Hasil akan segera dikirimkan! 🚀"
                    )
                    await send_whatsapp_text(sender_wa_id, success_msg, tenant_id=CAREER_TENANT_ID)
                    return web.Response(text="EVENT_RECEIVED", status=200)
                else:
                    await send_whatsapp_text(
                        sender_wa_id,
                        f"⚠️ Nominal transfer yang terbaca (*Rp{amount:,}*) berada di luar rentang harga paket (*Rp{min_allowed:,} - Rp{max_allowed:,}*).\n\n"
                        "Silakan cek kembali nominal transfer Anda atau hubungi admin jika terdapat kesalahan.",
                        tenant_id=CAREER_TENANT_ID
                    )
                    return web.Response(text="EVENT_RECEIVED", status=200)

            except Exception as e:
                logger.error(f"[Receipt Image OCR Error] {e}")
                await send_whatsapp_text(sender_wa_id, "⚠️ Terjadi kesalahan saat membaca gambar. Silakan coba unggah kembali.", tenant_id=CAREER_TENANT_ID)
                return web.Response(text="EVENT_RECEIVED", status=200)

    # 2. HANDLING DOKUMEN CV (PDF / DOCX)
    if msg_type == "document":
        doc_info = msg_obj.get("document", {})
        media_id = doc_info.get("id")
        filename = doc_info.get("filename", "document.pdf")

        await log_to_supabase_messages(
            sender=f"Customer / +{sender_wa_id}",
            text=f"[Mengirim Dokumen: {filename}]",
            tenant_id=CAREER_TENANT_ID
        )

        await send_whatsapp_text(
            sender_wa_id,
            f"📥 Menerima dokumen *{filename}*. Sedang menganalisis struktur & skor ATS CV kamu... ⏳",
            tenant_id=CAREER_TENANT_ID
        )

        try:
            file_bytes = await download_whatsapp_media(media_id)
            extracted_text = extract_text_from_bytes(file_bytes, filename)

            if not extracted_text or len(extracted_text) < 50:
                await send_whatsapp_text(
                    sender_wa_id,
                    "⚠️ Teks di dalam dokumen tidak dapat diekstrak. Pastikan file PDF/DOCX berisi teks asli, bukan hasil scan gambar.",
                    tenant_id=CAREER_TENANT_ID
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
                "⚠️ Terjadi kendala saat membaca dokumen. Silakan kirim ulang atau tempel teks CV kamu.",
                tenant_id=CAREER_TENANT_ID
            )

        return web.Response(text="EVENT_RECEIVED", status=200)

    # 3. EKSTRAKSI TEKS & TOMBOL INTERAKTIF
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

    # Catat pesan teks / tombol masuk ke Supabase
    if user_text:
        await log_to_supabase_messages(
            sender=f"Customer / +{sender_wa_id}",
            text=user_text,
            tenant_id=CAREER_TENANT_ID
        )

    user_text_clean = user_text.lower().strip()

    # Reset / Navigation
    if button_id == "btn_menu" or user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "home", "/menu", "/start"]:
        current_data = user_session.get("data", {})
        GLOBAL_USER_STATES[sender_wa_id] = {
            "step": 0,
            "mode": "menu",
            "data": current_data
        }
        await send_whatsapp_menu_buttons(sender_wa_id)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # Info Unggah Bukti Struk
    if button_id == "btn_upload_receipt_info":
        await send_whatsapp_text(
            sender_wa_id,
            "📸 *Silakan kirimkan foto / screenshot struk bukti pembayaran Anda* langsung ke chat ini.\n\nAI Vision kami akan membaca nominal dan memproses pesanan Anda secara otomatis.",
            tenant_id=CAREER_TENANT_ID
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 4. TRIGGER REWRITE (QRIS ASLI + KODE UNIK + ACTION BUTTONS)
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
            f"*(Rp{exact_amount:,} - Termasuk kode unik: {unique_code})*\n\n"
            "📌 *Panduan Pembayaran QRIS:*\n"
            "1. *Simpan / Screenshot* gambar QRIS di atas ke galeri HP kamu.\n"
            "2. Buka aplikasi m-Banking (*BCA, Mandiri, BRI, BNI*) atau e-Wallet (*GoPay, OVO, DANA, ShopeePay*).\n"
            "3. Pilih menu *Scan QRIS* ➔ ketuk *ikon Galeri / Unggah Gambar* ➔ pilih gambar QRIS tadi.\n"
            f"4. Masukkan nominal persis: `{exact_amount}`\n\n"
            f"⚠️ *PENTING:* Silakan *salin (copy)* angka `{exact_amount}` di atas agar tepat. "
            "Sistem verifikasi otomatis mendeteksi transaksi Anda secara instan!"
        )

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        asset_candidates = [
            os.path.join(base_dir, "assets", "qris.jpg"),
            os.path.join(base_dir, "assets", "qris.png"),
            os.path.join(base_dir, "assets", "qris_boontrack.png"),
            os.path.join(os.getcwd(), "assets", "qris.jpg"),
            os.path.join(os.getcwd(), "assets", "qris.png"),
        ]
        found_file = next((p for p in asset_candidates if os.path.exists(p)), None)

        if found_file:
            await send_whatsapp_image(sender_wa_id, image_path_or_bytes=found_file, caption=caption_text, tenant_id=CAREER_TENANT_ID)
        else:
            await send_whatsapp_text(sender_wa_id, caption_text, tenant_id=CAREER_TENANT_ID)

        await asyncio.sleep(1)

        action_buttons = [
            {"id": "btn_upload_receipt_info", "title": "📸 Kirim Bukti Struk"},
            {"id": "btn_menu", "title": "🏠 Menu Utama"}
        ]
        await send_whatsapp_buttons(
            to_phone=sender_wa_id,
            body_text="Jika ada salah transfer atau mutasi belum terdeteksi otomatis, Anda bisa mengirimkan foto screenshot bukti transfer ke chat ini.",
            buttons=action_buttons,
            footer_text="BoonTrack Payment Assistant",
            tenant_id=CAREER_TENANT_ID
        )

        return web.Response(text="EVENT_RECEIVED", status=200)

    current_mode = user_session.get("mode", "menu")

    # 5. MENU BUTTON HANDLERS
    if button_id == "btn_review" or (current_mode == "menu" and user_text_clean in ["1", "review cv", "🔍 review cv"]):
        user_session["mode"] = "review"
        intro_review = (
            "Silakan kirimkan dokumen CV Anda (*format PDF/DOCX*) atau *salin-tempel (copy-paste) teks riwayat CV* Anda langsung di chat ini untuk kami bedah secara gratis."
        )
        await send_whatsapp_text(sender_wa_id, intro_review, tenant_id=CAREER_TENANT_ID)
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
            footer_text="Klik pilihan bahasa di atas",
            tenant_id=CAREER_TENANT_ID
        )
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 6. CV BUILDER LANGUAGE SELECTION
    if button_id.startswith("lang_"):
        lang_choice = "1" if button_id == "lang_en_id" else ("2" if button_id == "lang_id" else "3")
        result = await process_unified_cv_step(sender_wa_id, lang_choice, platform="whatsapp")
        await send_whatsapp_text(sender_wa_id, result["reply_text"], tenant_id=CAREER_TENANT_ID)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 7. CV BUILDER WIZARD STEPS
    if current_mode == "builder" or user_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        messages_to_send = result.get("messages", [])
        if not messages_to_send and result.get("reply_text"):
            messages_to_send = [result["reply_text"]]

        for msg in messages_to_send:
            await send_whatsapp_text(sender_wa_id, msg, tenant_id=CAREER_TENANT_ID)

        if result.get("is_completed"):
            user_session["mode"] = "post_cv"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 8. REVIEW VIA MANUAL TEXT INPUT
    if current_mode == "review":
        if len(user_text.split()) < 6:
            await send_whatsapp_text(
                sender_wa_id,
                "⚠️ Teks CV terlalu singkat. Silakan tempel teks CV lengkap atau kirim file dokumen (.pdf / .docx).",
                tenant_id=CAREER_TENANT_ID
            )
            return web.Response(text="EVENT_RECEIVED", status=200)

        nama = get_user_display_name(sender_wa_id)
        sapaan = f", *{nama}*" if nama else ""
        await send_whatsapp_text(sender_wa_id, f"⏳ *Sedang menganalisis struktur & skor ATS CV kamu{sapaan}...*", tenant_id=CAREER_TENANT_ID)
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
            await send_whatsapp_text(sender_wa_id, "⚠️ Gagal menganalisis teks CV.", tenant_id=CAREER_TENANT_ID)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # 9. FALLBACK AI CONSULTATION
    ai_reply = await ai_gateway.generate(
        user_message=user_text,
        context={"user_id": sender_wa_id, "feature": "career_consultation"}
    )
    if ai_reply:
        await send_whatsapp_text(sender_wa_id, ai_reply, tenant_id=CAREER_TENANT_ID)
    else:
        await send_whatsapp_menu_buttons(sender_wa_id)

    return web.Response(text="EVENT_RECEIVED", status=200)


def register_whatsapp_career_routes(app: web.Application):
    app.router.add_get("/api/whatsapp/webhook", verify_webhook)
    app.router.add_post("/api/whatsapp/webhook", handle_incoming_whatsapp)