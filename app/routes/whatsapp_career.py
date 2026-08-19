import re
import os
import random
import logging
from typing import Tuple
from aiohttp import web
from app.services.whatsapp_service import send_whatsapp_text, send_whatsapp_image
from app.constants.messages import MENU_INVALID_MSG
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service
from app.services.ai_service import ai_gateway
from app.core.database import track_event, count_referrals, get_supabase_client
from app.services.document_parser_service import download_whatsapp_media, extract_text_from_bytes

logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") or os.getenv("META_WA_VERIFY_TOKEN", "boontrack_wa_secret_token")

# Cache in-memory untuk user yang terkonfirmasi pernah review / buat CV
RETURNING_WA_USERS = set()


async def check_is_returning_user(sender_wa_id: str) -> Tuple[bool, str]:
    """
    Mengecek apakah user sudah pernah berinteraksi / mengisi CV / me-review CV
    melalui Session State, In-Memory Cache, atau langsung query ke Supabase DB.
    """
    user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
    user_data = user_session.get("data", {})
    nama = user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""

    if user_data.get("has_completed_cv") or sender_wa_id in RETURNING_WA_USERS or nama:
        return True, nama

    # Cek langsung ke database Supabase tabel cv_reviews
    try:
        supabase = get_supabase_client()
        clean_wa = re.sub(r"\D", "", str(sender_wa_id))
        
        # Query berdasarkan nomor WA murni atau ID
        res = supabase.table("cv_reviews").select("*").or_(f"user_id.eq.{clean_wa},user_id.eq.{sender_wa_id}").limit(1).execute()
        if res.data and len(res.data) > 0:
            RETURNING_WA_USERS.add(sender_wa_id)
            user_session.setdefault("data", {})["has_completed_cv"] = True
            return True, nama
    except Exception as e:
        logger.warning(f"[DB Check Returning User] Notice: {e}")

    # Cek via service helper
    try:
        numeric_id = int(re.sub(r"\D", "", str(sender_wa_id)))
        reviews = await cv_review_service.get_user_reviews(numeric_id)
        if reviews and len(reviews) > 0:
            RETURNING_WA_USERS.add(sender_wa_id)
            user_session.setdefault("data", {})["has_completed_cv"] = True
            return True, nama
    except Exception:
        pass

    return False, ""


async def get_whatsapp_dynamic_home_menu(sender_wa_id: str) -> str:
    """Menghasilkan Menu Beranda Dinamis (1-5 untuk returning user, 1-3 untuk new user)."""
    is_returning, nama = await check_is_returning_user(sender_wa_id)

    if is_returning:
        greeting = f", *{nama}*" if nama else ""
        return (
            f"Halo{greeting}! 👋 Selamat datang kembali di *BoonTrack*.\n\n"
            f"Ada yang mau dibahas atau dioptimasi lagi? Silakan pilih menu di bawah ya:\n\n"
            f"1️⃣ *Buat / Perbarui Versi CV ATS*\n"
            f"2️⃣ *Review & Cek Skor ATS CV*\n"
            f"3️⃣ *Aktivasi Career Page Pribadi (Rp10.000)*\n"
            f"4️⃣ *Cek Status Referral & Hadiah Gratis*\n"
            f"5️⃣ *Konsultasi Karir & Interview*\n\n"
            f"_Ketik angka 1, 2, 3, 4, atau 5 untuk memilih._"
        )

    return (
        "Halo! 👋 Selamat datang di *BoonTrack Career Assistant*.\n\n"
        "Saya siap membantu perjalanan karirmu agar lebih optimal dan dilirik HRD.\n\n"
        "Silakan pilih layanan yang kamu butuhkan:\n"
        "1️⃣ *Buat CV ATS Baru* (Panduan step-by-step dari awal)\n"
        "2️⃣ *Review & Optimasi CV* (Cek skor ATS & analisis perbaikan)\n"
        "3️⃣ *Konsultasi Dunia Kerja* (Tips interview, strategi karir & negosiasi)\n\n"
        "_Ketik angka 1, 2, atau 3 untuk mulai!_"
    )


def generate_payment_message(user_id: str, base_amt: int = 10000) -> Tuple[int, str]:
    unique_code = random.randint(100, 999)
    total_amt = base_amt + unique_code

    msg = (
        "🎉 *Terima kasih telah memilih BoonTrack!*\n\n"
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
            return
        except Exception as e:
            logger.error(f"[WA Send QRIS Image Error] {e}")

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

    messages = changes[0].get("value", {}).get("messages", [])
    if not messages:
        return web.Response(text="EVENT_RECEIVED", status=200)

    msg_obj = messages[0]
    sender_wa_id = msg_obj.get("from")
    msg_type = msg_obj.get("type")

    # --- 1. HANDLING DOKUMEN CV (.PDF / .DOCX) ---
    if msg_type == "document":
        doc_info = msg_obj.get("document", {})
        media_id = doc_info.get("id")
        filename = doc_info.get("filename", "document.pdf")

        await send_whatsapp_text(sender_wa_id, f"📥 Menerima dokumen *{filename}*. Sedang mengekstrak dan menganalisis skor ATS CV kamu... ⏳")

        try:
            file_bytes = await download_whatsapp_media(media_id)
            extracted_text = extract_text_from_bytes(file_bytes, filename)

            if not extracted_text or len(extracted_text) < 50:
                await send_whatsapp_text(sender_wa_id, "⚠️ Teks di dalam dokumen tidak terbaca. Pastikan dokumen berupa PDF/DOCX teks asli.")
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

            RETURNING_WA_USERS.add(sender_wa_id)
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
                "2️⃣ *Ajak 5 Teman (Gratis)*\n"
                "3️⃣ *Menu Utama*\n\n"
                "_Ketik angka 1, 2, atau 3 untuk memilih._"
            )
            user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "post_cv", "data": {}})
            user_session["mode"] = "post_cv"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True
            await send_whatsapp_text(sender_wa_id, review_msg)

        except Exception as e:
            logger.error(f"[Upload Document Error] {e}")
            await send_whatsapp_text(sender_wa_id, "⚠️ Terjadi kendala saat memproses dokumen. Silakan coba lagi.")

        return web.Response(text="EVENT_RECEIVED", status=200)

    # --- 2. HANDLING PESAN TEKS ---
    if msg_type != "text":
        await send_whatsapp_text(sender_wa_id, "Halo! Kirim pesan teks atau unggah file dokumen CV (.pdf / .docx). Ketik *Menu* untuk bantuan.")
        return web.Response(text="EVENT_RECEIVED", status=200)

    user_text = msg_obj.get("text", {}).get("body", "").strip()
    user_text_clean = user_text.lower().strip()

    # Reset ke Menu Utama
    if user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "home", "/menu", "/start"]:
        current_data = GLOBAL_USER_STATES.get(sender_wa_id, {}).get("data", {})
        GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "menu", "data": current_data}
        dynamic_home = await get_whatsapp_dynamic_home_menu(sender_wa_id)
        await send_whatsapp_text(sender_wa_id, dynamic_home)
        return web.Response(text="EVENT_RECEIVED", status=200)

    current_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    current_mode = current_session.get("mode", "menu")

    # Wizard Step CV Builder (Step 1-10)
    if current_session.get("step", 0) > 0:
        result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
        for msg in result.get("messages", [result["reply_text"]]):
            await send_whatsapp_text(sender_wa_id, msg)
        
        if result.get("is_completed"):
            current_session["mode"] = "post_cv"
            current_session["step"] = 0
            current_session.setdefault("data", {})["has_completed_cv"] = True
            RETURNING_WA_USERS.add(sender_wa_id)
        return web.Response(text="EVENT_RECEIVED", status=200)

    # --- PRIORITAS 1: POST_CV STATE (Checkout / Referral / Kembali) ---
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
                "Silakan share link berikut ke teman-temanmu. Semangat ya! 🚀\n\n"
                f"📊 *Status Referral Kamu:* *({invited_count}/5)* teman bergabung\n"
                f"🔗 *Link Referral Kamu:* {ref_link}\n\n"
                "Jika sudah mencapai 5 teman, Career Page otomatis aktif gratis untukmu!"
            )
            await send_whatsapp_text(sender_wa_id, ref_msg)
            return web.Response(text="EVENT_RECEIVED", status=200)

        if user_text_clean in ["3", "menu utama"]:
            current_data = current_session.get("data", {})
            GLOBAL_USER_STATES[sender_wa_id] = {"step": 0, "mode": "menu", "data": current_data}
            dynamic_home = await get_whatsapp_dynamic_home_menu(sender_wa_id)
            await send_whatsapp_text(sender_wa_id, dynamic_home)
            return web.Response(text="EVENT_RECEIVED", status=200)

        # Pertanyaan karir bebas
        ai_reply = await ai_gateway.generate(user_message=user_text, context={"user_id": sender_wa_id, "feature": "career_consultation"})
        if ai_reply:
            await send_whatsapp_text(sender_wa_id, ai_reply)
            return web.Response(text="EVENT_RECEIVED", status=200)

    # --- PRIORITAS 2: MODE REVIEW CV INPUT TEKS ---
    if current_mode == "review":
        if len(user_text.split()) < 6:
            await send_whatsapp_text(sender_wa_id, "⚠️ Teks CV terlalu singkat. Silakan tempel (paste) seluruh teks CV kamu atau kirim file dokumen (.pdf / .docx).")
            return web.Response(text="EVENT_RECEIVED", status=200)

        await send_whatsapp_text(sender_wa_id, "⏳ *Sedang menganalisis struktur & skor ATS CV kamu...*")
        try:
            eval_result = cv_review_engine.evaluate_cv(user_text, target_position="General Professional")
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

            RETURNING_WA_USERS.add(sender_wa_id)
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
                "2️⃣ *Ajak 5 Teman (Gratis)*\n"
                "3️⃣ *Menu Utama*\n\n"
                "_Ketik angka 1, 2, atau 3 untuk memilih._"
            )
            current_session["step"] = 0
            current_session["mode"] = "post_cv"
            current_session.setdefault("data", {})["has_completed_cv"] = True
            await send_whatsapp_text(sender_wa_id, review_msg)
        except Exception as e:
            logger.error(f"[WA Review Error] {e}")
            await send_whatsapp_text(sender_wa_id, "⚠️ Gagal menganalisis CV. Pastikan teks CV lengkap lalu coba lagi.")
        return web.Response(text="EVENT_RECEIVED", status=200)

    # --- PRIORITAS 3: MODE KONSULTASI KARIR ---
    if current_mode == "consultation":
        ai_reply = await ai_gateway.generate(user_message=user_text, context={"user_id": sender_wa_id, "feature": "career_consultation"})
        if ai_reply:
            await send_whatsapp_text(sender_wa_id, ai_reply)
        else:
            await send_whatsapp_text(sender_wa_id, "Maaf, silakan ulangi pertanyaanmu atau ketik *Menu*.")
        return web.Response(text="EVENT_RECEIVED", status=200)

    # --- PRIORITAS 4: MENU UTAMA DINAMIS ---
    if current_mode == "menu":
        is_returning, _ = await check_is_returning_user(sender_wa_id)

        # Opsi 1: Buat CV
        if user_text_clean in ["1", "buat cv", "bikin cv", "buat cv ats baru", "1️⃣"]:
            current_session["mode"] = "builder"
            result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
            await send_whatsapp_text(sender_wa_id, result["reply_text"])
            return web.Response(text="EVENT_RECEIVED", status=200)

        # Opsi 2: Review CV
        if user_text_clean in ["2", "review cv", "review & optimasi cv", "cek ats", "2️⃣"]:
            current_session["mode"] = "review"
            intro_review = (
                "Halo! Mari kita bedah skor dan kualitas ATS CV kamu. 📊✨\n\n"
                "Kamu bisa langsung *kirim file CV (PDF / DOCX)* ke chat ini, atau *salin-tempel (copy-paste) teks CV kamu* sekarang ya."
            )
            await send_whatsapp_text(sender_wa_id, intro_review)
            return web.Response(text="EVENT_RECEIVED", status=200)

        # Menu Returning User
        if is_returning:
            if user_text_clean in ["3", "order", "career page", "aktivasi", "3️⃣"]:
                await send_qris_checkout_flow(sender_wa_id, base_amt=10000)
                return web.Response(text="EVENT_RECEIVED", status=200)

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

            if user_text_clean in ["5", "konsultasi", "konsultasi karir", "5️⃣"]:
                current_session["mode"] = "consultation"
                await send_whatsapp_text(sender_wa_id, "💼 *Konsultasi Karir & Dunia Kerja*\n\nSilakan tanyakan apa saja seputar persiapan interview, tips CV, atau negosiasi gaji!")
                return web.Response(text="EVENT_RECEIVED", status=200)

        else:
            # Menu New User
            if user_text_clean in ["3", "konsultasi", "konsultasi dunia kerja", "3️⃣"]:
                current_session["mode"] = "consultation"
                await send_whatsapp_text(sender_wa_id, "💼 *Konsultasi Karir & Dunia Kerja*\n\nSilakan tanyakan apa saja seputar persiapan interview, tips CV, atau negosiasi gaji!")
                return web.Response(text="EVENT_RECEIVED", status=200)

    # Fallback Obrolan Bebas
    ai_reply = await ai_gateway.generate(user_message=user_text, context={"user_id": sender_wa_id, "feature": "career_consultation"})
    if ai_reply:
        await send_whatsapp_text(sender_wa_id, ai_reply)
    else:
        await send_whatsapp_text(sender_wa_id, MENU_INVALID_MSG)

    return web.Response(text="EVENT_RECEIVED", status=200)


def register_whatsapp_career_routes(app: web.Application):
    app.router.add_get("/api/whatsapp/webhook", verify_webhook)
    app.router.add_post("/api/whatsapp/webhook", handle_incoming_whatsapp)