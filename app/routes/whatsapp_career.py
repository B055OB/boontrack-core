import re
import os
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

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")


def get_whatsapp_full_menu(sender_wa_id: str) -> str:
    """Menghasilkan menu utama 5 layanan BoonTrack dengan sapaan nama."""
    user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
    user_data = user_session.get("data", {})
    nama = user_data.get("nama_panggilan") or user_data.get("nama_lengkap")
    greeting_name = f", *{nama}*" if nama else ""

    return (
        f"Halo{greeting_name}! 👋 Selamat datang di *BoonTrack Career Assistant*.\n\n"
        "Saya siap membantu perjalanan karirmu agar lebih optimal dan dilirik HRD:\n\n"
        "1️⃣ *Buat CV ATS Baru* (Panduan step-by-step dari awal)\n"
        "2️⃣ *Review & Cek Skor ATS CV* (Upload PDF/DOCX atau kirim teks)\n"
        "3️⃣ *Aktivasi Career Page Pribadi (Rp10.000)*\n"
        "4️⃣ *Cek Status Referral & Hadiah Gratis*\n"
        "5️⃣ *Konsultasi Karir & Tanya Jawab HRD*\n\n"
        "_Ketik angka 1, 2, 3, 4, atau 5 untuk memilih._"
    )


def generate_payment_message(sender_wa_id: str, base_amt: int = 10000) -> Tuple[int, str]:
    """Format checkout Career Page dengan sapaan nama dan 3 digit nominal unik."""
    user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
    user_data = user_session.get("data", {})
    nama = user_data.get("nama_panggilan") or user_data.get("nama_lengkap")
    greeting = f", *{nama}*" if nama else ""

    unique_code = random.randint(100, 999)
    total_amt = base_amt + unique_code

    msg = (
        f"🎉 *Terima kasih telah memilih BoonTrack{greeting}!*\n\n"
        "Tinggal satu langkah lagi untuk mengaktifkan *Career Page Profesional* milikmu dan tampil lebih menonjol di mata HRD/Klien.\n\n"
        "🌐 *Contoh Tampilan Career Page:*\n"
        "Lihat preview tampilan Career Page yang akan kamu dapatkan di sini:\n"
        "👉 https://rayigemilang.boontrack.com\n\n"
        "_✨ Format modern, recruiter-friendly, responsif di HP/laptop, dan *aktif seumur hidup (sekali bayar tanpa biaya langganan)*._\n\n"
        "💳 *Rincian Pembayaran:*\n"
        "• *Item:* Aktivasi Career Page Personal (Lifetime Access)\n"
        f"• *Transfer Tepat:* `Rp{total_amt:,}` _(Wajib transfer sesuai hingga 3 digit terakhir)_\n"
        f"• *Rincian:* Rp{base_amt:,} + kode verifikasi Rp{unique_code}\n"
        "• *Masa Aktif Web:* *Aktif Seumur Hidup*\n\n"
        "📱 *Panduan Bayar via QRIS (Jika Pakai 1 HP):*\n"
        "1. *Simpan QR:* *Screenshot gambar QRIS di atas* atau simpan ke galeri.\n"
        "2. *Buka E-Wallet / Mobile Banking:* (BCA, Mandiri, BRI, DANA, GoPay, OVO, ShopeePay, dll).\n"
        "3. *Pilih Menu QRIS / Scan:* Buka scanner QRIS di aplikasimu.\n"
        "4. *Upload dari Galeri:* Klik ikon galeri pada scanner & pilih gambar QR tadi.\n"
        f"5. *Input Nominal PRESISI:* Pastikan nominal tepat *Rp{total_amt:,}*.\n"
        "6. Selesaikan pembayaran.\n\n"
        "⏳ _Sistem otomatis memverifikasi pembayaran secara real-time melalui BoonTrack Reader. Begitu dana masuk, bot akan langsung mengirimkan link Career Page aktif milikmu!_"
    )
    return total_amt, msg


async def send_qris_checkout_flow(sender_wa_id: str, base_amt: int = 10000):
    """Mengirim 1 kali pesan gambar QRIS dengan caption (mencegah duplikasi)."""
    total_amt, msg_caption = generate_payment_message(sender_wa_id, base_amt)

    possible_qris_paths = [
        "assets/qris.jpg",
        "qris.jpg",
        "/app/assets/qris.jpg",
        "/app/qris.jpg",
        "app/qris.jpg",
        os.path.join(os.getcwd(), "assets", "qris.jpg"),
        os.path.join(os.getcwd(), "qris.jpg")
    ]
    found_qris = next((p for p in possible_qris_paths if os.path.exists(p)), None)

    if found_qris:
        try:
            await send_whatsapp_image(sender_wa_id, image_path=found_qris, caption=msg_caption)
            return  # Kunci agar tidak mengirim pesan teks dobel
        except Exception as e:
            logger.error(f"[WA Send QRIS Image Error] {e}")

    # Fallback teks hanya jika file gambar tidak ditemukan
    await send_whatsapp_text(sender_wa_id, msg_caption)


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

    # Ambil Profil Nama dari Meta Contact jika tersedia
    contacts = value_data.get("contacts", [])
    profile_name = ""
    if contacts and isinstance(contacts, list):
        profile_name = contacts[0].get("profile", {}).get("name", "").strip()

    user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    if profile_name and not user_session.get("data", {}).get("nama_panggilan"):
        user_session.setdefault("data", {})["nama_panggilan"] = profile_name
        user_session["data"]["nama_lengkap"] = profile_name

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

            b = filtered_data.get("breakdown_scores", {})
            findings = filtered_data.get("findings", [])
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
                "💡 *Catatan Standar Screening HRD:*\n"
                f"{findings_list}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔥 *Bikin HRD Langsung Lirik Lamaranmu!*\n\n"
                "Dapatkan *Career Page Portofolio Online Pribadi*.\n\n"
                "Pilih opsi selanjutnya:\n"
                "1️⃣ *Order Career Page (Rp10.000)*\n"
                "2️⃣ *Ajak 5 Teman (Gratis via Referral)*\n"
                "3️⃣ *Menu Utama*\n\n"
                "_Ketik angka 1, 2, atau 3 untuk memilih._"
            )

            user_session["mode"] = "post_cv"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True
            await send_whatsapp_text(sender_wa_id, review_msg)

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

    # Reset ke Menu Utama
    if user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "home", "/menu", "/start"]:
        current_data = user_session.get("data", {})
        GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "menu", "data": current_data}
        await send_whatsapp_text(sender_wa_id, get_whatsapp_full_menu(sender_wa_id))
        return web.Response(text="EVENT_RECEIVED", status=200)

    current_mode = user_session.get("mode", "menu")

    # =========================================================================
    # 3. WIZARD STEP CV BUILDER (Step 1 s/d 10)
    # =========================================================================
    if user_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        for msg in result.get("messages", [result["reply_text"]]):
            await send_whatsapp_text(sender_wa_id, msg)

        if result.get("is_completed"):
            user_session["mode"] = "post_cv"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True
        return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 4. POST_CV STATE (Setelah Review atau Pembuatan CV)
    # =========================================================================
    if current_mode == "post_cv":
        if user_text_clean in ["1", "order", "beli", "order career page"]:
            await send_qris_checkout_flow(sender_wa_id, base_amt=10000)
            return web.Response(text="EVENT_RECEIVED", status=200)

        if user_text_clean in ["2", "referral", "gratis", "ajak teman"]:
            try:
                invited_count = await count_referrals(sender_wa_id)
            except Exception:
                invited_count = 0
            ref_link = f"https://boontrack.com/ref/{sender_wa_id}"
            ref_msg = (
                "🎁 *PROGRAM CAREER PAGE GRATIS VIA REFERRAL*\n\n"
                "Silakan bagikan link referral ini ke rekan atau grupmu:\n\n"
                f"📊 *Status Referral Kamu:* *({invited_count}/5)* teman bergabung\n"
                f"🔗 *Link Referral Kamu:* {ref_link}\n\n"
                "Jika 5 teman mendaftar lewat linkmu, Career Page profesional langsung aktif gratis seumur hidup!"
            )
            await send_whatsapp_text(sender_wa_id, ref_msg)
            return web.Response(text="EVENT_RECEIVED", status=200)

        if user_text_clean in ["3", "menu utama"]:
            current_data = user_session.get("data", {})
            GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "menu", "data": current_data}
            await send_whatsapp_text(sender_wa_id, get_whatsapp_full_menu(sender_wa_id))
            return web.Response(text="EVENT_RECEIVED", status=200)

        ai_reply = await ai_gateway.generate(
            user_message=user_text,
            context={"user_id": sender_wa_id, "feature": "career_consultation"}
        )
        if ai_reply:
            await send_whatsapp_text(sender_wa_id, ai_reply)
            return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 5. MODE REVIEW CV DARI TEKS MANUAL
    # =========================================================================
    if current_mode == "review":
        if len(user_text.split()) < 6:
            await send_whatsapp_text(
                sender_wa_id,
                "⚠️ Teks CV terlalu singkat. Silakan tempel (paste) teks CV lengkapmu atau kirimkan file dokumen (.pdf / .docx)."
            )
            return web.Response(text="EVENT_RECEIVED", status=200)

        await send_whatsapp_text(sender_wa_id, "⏳ *Sedang menganalisis struktur & skor ATS CV kamu...*")
        try:
            eval_result = cv_review_engine.evaluate_cv(user_text, target_position="General Professional")
            filtered_data = cv_review_service.filter_entitlement_response(eval_result, is_premium=False)

            b = filtered_data.get("breakdown_scores", {})
            findings = filtered_data.get("findings", [])
            findings_list = "\n".join([f"• {f}" for f in findings]) if findings else "• Format dasar CV sudah terbaca."

            review_msg = (
                "📊 *HASIL DIAGNOSIS SKOR CV KAMU*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Target Role:* General Professional\n"
                f"📈 *Overall Score:* *{filtered_data.get('overall_score', 0)} / 100*\n\n"
                "📌 *Breakdown Kategori:*\n"
                f"• ATS Compatibility: *{b.get('ats_compatibility', 70)}%*\n"
                f"• Relevansi Format: *{b.get('structure', 75)}%*\n"
                f"• Kualitas Pengalaman: *{b.get('experience', 80)}%*\n\n"
                "💡 *Catatan Standar Screening HRD:*\n"
                f"{findings_list}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔥 *Bikin HRD Langsung Lirik Lamaranmu!*\n\n"
                "Dapatkan *Career Page Portofolio Online Pribadi*.\n\n"
                "Pilih opsi selanjutnya:\n"
                "1️⃣ *Order Career Page (Rp10.000)*\n"
                "2️⃣ *Ajak 5 Teman (Gratis via Referral)*\n"
                "3️⃣ *Menu Utama*\n\n"
                "_Ketik angka 1, 2, atau 3 untuk memilih._"
            )
            user_session["step"] = 0
            user_session["mode"] = "post_cv"
            user_session.setdefault("data", {})["has_completed_cv"] = True
            await send_whatsapp_text(sender_wa_id, review_msg)
        except Exception as e:
            logger.error(f"[WA Review Error] {e}")
            await send_whatsapp_text(
                sender_wa_id,
                "⚠️ Gagal menganalisis teks CV. Pastikan konten cukup lengkap lalu coba lagi."
            )
        return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 6. MODE KONSULTASI KARIR
    # =========================================================================
    if current_mode == "consultation":
        ai_reply = await ai_gateway.generate(
            user_message=user_text,
            context={"user_id": sender_wa_id, "feature": "career_consultation"}
        )
        if ai_reply:
            await send_whatsapp_text(sender_wa_id, ai_reply)
        else:
            await send_whatsapp_text(
                sender_wa_id,
                "Maaf, AI sedang memproses data. Silakan ketik pertanyaanmu lagi atau ketik *Menu* untuk kembali."
            )
        return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 7. MENU UTAMA (5 PILIHAN UTAMA)
    # =========================================================================
    if current_mode == "menu":
        # Opsi 1: Buat CV
        if user_text_clean in ["1", "buat cv", "bikin cv", "buat cv ats baru", "1️⃣"]:
            user_session["mode"] = "builder"
            result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
            await send_whatsapp_text(sender_wa_id, result["reply_text"])
            return web.Response(text="EVENT_RECEIVED", status=200)

        # Opsi 2: Review CV
        if user_text_clean in ["2", "review cv", "review & optimasi cv", "cek ats", "2️⃣"]:
            user_session["mode"] = "review"
            intro_review = (
                "Halo! Mari kita bedah skor dan kualitas ATS CV kamu. 📊✨\n\n"
                "Kamu bisa langsung *kirim file dokumen CV (.pdf / .docx)* ke chat ini, atau *salin-tempel (copy-paste) teks CV kamu* sekarang ya."
            )
            await send_whatsapp_text(sender_wa_id, intro_review)
            return web.Response(text="EVENT_RECEIVED", status=200)

        # Opsi 3: Aktivasi Career Page (Rp10.000)
        if user_text_clean in ["3", "order", "career page", "aktivasi", "3️⃣"]:
            await send_qris_checkout_flow(sender_wa_id, base_amt=10000)
            return web.Response(text="EVENT_RECEIVED", status=200)

        # Opsi 4: Referral Hadiah Gratis
        if user_text_clean in ["4", "referral", "cek referral", "gratis", "4️⃣"]:
            try:
                invited_count = await count_referrals(sender_wa_id)
            except Exception:
                invited_count = 0
            ref_link = f"https://boontrack.com/ref/{sender_wa_id}"
            ref_msg = (
                "🎁 *PROGRAM CAREER PAGE GRATIS VIA REFERRAL*\n\n"
                f"📊 *Status Referral:* *({invited_count}/5)* teman bergabung\n"
                f"🔗 *Link Referral:* {ref_link}\n\n"
                "Jika sudah mencapai 5 teman, Career Page otomatis aktif gratis untukmu!"
            )
            await send_whatsapp_text(sender_wa_id, ref_msg)
            return web.Response(text="EVENT_RECEIVED", status=200)

        # Opsi 5: Konsultasi Karir
        if user_text_clean in ["5", "konsultasi", "konsultasi karir", "5️⃣"]:
            user_session["mode"] = "consultation"
            await send_whatsapp_text(
                sender_wa_id,
                "💼 *Konsultasi Karir & Dunia Kerja Bersama BoonTrack AI*\n\n"
                "Silakan tanyakan apa saja seputar persiapan interview, negosiasi gaji/UMR, tips CV, atau strategi karir impianmu!"
            )
            return web.Response(text="EVENT_RECEIVED", status=200)

    # =========================================================================
    # 8. FALLBACK OBROLAN BEBAS
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