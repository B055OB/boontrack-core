import os
import json
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.core.database import save_user, track_event, get_user_history, save_dropoff
from app.handlers.admin_handler import admin_handler
from app.services.analytics_service import analytics_service
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service

TOTAL_STEPS = 10

# INISIALISASI GLOBAL STATE
user_state = {}

TOTAL_STEPS = len(CV_QUESTIONS)

CV_QUESTIONS = {
    1: (
        "Sebelum kita mulai, CV kamu ingin dibuat dalam bahasa apa?\n\n"
        "1️⃣ *CV English (Ngobrol B. Indonesia)*\n"
        "2️⃣ *CV Bahasa Indonesia*\n"
        "3️⃣ *Full English*\n\n"
        "_(Ketik angka 1, 2, atau 3)_"
    ),
    2: (
        "Siapa **nama lengkap** yang ingin kamu tampilkan di CV?\n\n"
        "_(Contoh: Rayi Gemilang)_"
    ),
    3: (
        "Nomor kontak aktif yang bisa dihubungi HRD:\n\n"
        "💡 *Tips:* Ketik *'pakai wa'* jika ingin memakai nomor WhatsApp ini otomatis, "
        "tulis nomor lain, atau ketik *-* jika ingin dilewati."
    ),
    4: (
        "Alamat **email aktif** kamu?\n\n"
        "_(Ketik email atau ketik *-* jika ingin diisi nanti saat edit manual)_"
    ),
    5: (
        "**Kota domisili** saat ini?\n\n"
        "_(Contoh: Bandung / Jakarta Selatan / ketik *-* untuk lewati)_"
    ),
    6: (
        "**Posisi atau bidang pekerjaan** yang sedang kamu incar?\n\n"
        "_(Contoh: Admin Sales, Digital Marketer, Barista, Staff Gudang)_"
    ),
    7: (
        "Tuliskan **pengalaman kerja terakhirmu** (Posisi, Perusahaan, & Tahun):\n\n"
        "💡 *Tips:* Jika Fresh Graduate / belum ada pengalaman resmi, ketik *-* "
        "atau tulis pengalaman magang / organisasi kampus."
    ),
    8: (
        "**Pendidikan terakhirmu** (Jurusan, Sekolah/Kampus, Tahun Lulus)?\n\n"
        "_(Contoh: SMA Negeri 5 Bandung 2020 atau S1 Manajemen Unpad 2023 / ketik *-*)_"
    ),
    9: (
        "Sebutkan 2–4 **keahlian utama (skills)** yang kamu miliki:\n\n"
        "💡 *Contoh:* Microsoft Excel, Negosiasi Penjualan, Canva, Layanan Pelanggan "
        "_(Ketik *-* jika ingin AI memilihkan otomatis berdasarkan posisimu)_"
    ),
    10: (
        "Punya **link LinkedIn / Portofolio / Sertifikat** pendukung?\n\n"
        "_(Opsional: Tulis link/namanya, atau langsung ketik *-* untuk dilewati)_"
    ),
    11: (
        "Punya deskripsi singkat tentang dirimu?\n\n"
        "💡 *Rekomendasi:* Langsung ketik *-* saja agar **AI BoonTrack yang merangkumkan profil profesional terbaik** untukmu!"
    )
}

def get_progress_bar(step: int) -> str:
    return f"📍 <b>Langkah {step} dari {TOTAL_STEPS}</b>\n━━━━━━━━━━"

async def send_welcome(message: types.Message):
    user_id = message.chat.id
    first_name = message.chat.first_name or "Teman"
    text = (message.text or "").strip()

    if text.startswith("/analytics") or text.startswith("/admin"):
        response_text = await admin_handler.handle_admin_command(user_id, text)
        await message.reply(response_text, parse_mode="Markdown")
        return

    text_parts = text.split()
    args = text_parts[1] if len(text_parts) > 1 else "direct"

    if args.startswith("ref_"):
        meta_data = {
            "first_source": "referral",
            "latest_source": "referral",
            "utm_source": "referral", 
            "utm_medium": "word_of_mouth",
            "utm_campaign": "user_referral",
            "utm_content": "none",
            "referrer_id": args.replace("ref_", "")
        }
    else:
        clean_args = args.replace("__", "-")
        payload = clean_args.split("-")
        source_val = payload[0] if len(payload) > 0 and payload[0] else "direct"
        
        meta_data = {
            "first_source": source_val,
            "latest_source": source_val,
            "utm_source": source_val,
            "utm_medium": payload[1] if len(payload) > 1 else "none",
            "utm_campaign": payload[2] if len(payload) > 2 else "none",
            "utm_content": payload[3] if len(payload) > 3 else "none",
            "utm_term": payload[4] if len(payload) > 4 else "none"
        }
        await analytics_service.save_user_utm(user_id, clean_args)

    if message.from_user:
        await save_user(message.from_user, meta=meta_data)
    await track_event(user_id, "start", meta=meta_data)
    
    progress, last_cv = await get_user_history(user_id)

    saved_data = progress.get("data", {}) if progress else {}
    if user_id not in user_state:
        user_state[user_id] = {"step": progress.get("last_step", 0) if progress else 0, "data": saved_data}

    # Tampilkan Menu Utama Interaktif Lengkap (6 Tombol)
    kbd = InlineKeyboardMarkup(row_width=1)
    kbd.add(
        InlineKeyboardButton("📝 Buat / Edit CV Baru", callback_data="home_create_cv"),
        InlineKeyboardButton("🔍 Review CV Saya", callback_data="trigger_cv_review"),
        InlineKeyboardButton("🌐 Buat Career Page Profesional (Rp10.000)", callback_data="don_10000"),
        InlineKeyboardButton("📚 Ebook & Program Digital", callback_data="home_digital_products"),
        InlineKeyboardButton("🎁 Cek Referral Saya", callback_data="home_check_ref"),
        InlineKeyboardButton("💬 Tanya Seputar Dunia Kerja", callback_data="home_career_qa")
    )

    if progress and 1 < progress.get("last_step", 0) < TOTAL_STEPS:
        last_step = progress["last_step"]
        user_state[user_id]["step"] = last_step
        
        kbd_resume = InlineKeyboardMarkup(row_width=2)
        kbd_resume.add(
            InlineKeyboardButton("▶️ Lanjutkan CV", callback_data="resume_flow"),
            InlineKeyboardButton("🔄 Mulai Baru", callback_data="restart_flow")
        )
        kbd_resume.add(InlineKeyboardButton("🔍 Review CV Saya", callback_data="trigger_cv_review"))
        
        await message.reply(
            f"Halo lagi, <b>{first_name}</b>! 👋\n\n"
            f"Kemarin kita sempat membuat CV sampai di <b>Langkah {last_step} dari {TOTAL_STEPS}</b>.\n\n"
            "Pilih opsi di bawah untuk melanjutkan atau review CV:",
            reply_markup=kbd_resume,
            parse_mode="HTML"
        )
        return

    greeting = (
        f"Halo, <b>{first_name}</b>! 👋\n\n"
        "<b>Selamat datang di BoonTrack Karir!</b>\n"
        "Asisten karir cerdas untuk pembuatan CV ATS-friendly dan diagnosa kualitas CV secara profesional.\n\n"
        "Silakan pilih layanan yang kamu butuhkan:"
    )
    await message.reply(greeting, reply_markup=kbd, parse_mode="HTML")

async def cancel_handler(message: types.Message):
    user_id = message.from_user.id
    user_state[user_id] = {"step": 0, "data": {}}
    await save_dropoff(user_id, 0, {})
    await message.reply("❌ <b>Proses pembuatan CV dibatalkan.</b>", parse_mode="HTML")

async def render_free_cv_review(user_id: int, bot, cv_text: str, target_position: str = "General Professional"):
    """
    Eksekusi Review Deterministic + Backend Entitlement Filter (Security P0)
    """
    await bot.send_message(user_id, "⏳ <b>Sedang menganalisis struktur & skor ATS CV kamu...</b>", parse_mode="HTML")
    
    # 1. Analisis skor dengan CV Review Engine
    eval_result = cv_review_engine.evaluate_cv(cv_text, target_position=target_position)
    
    # 2. Filter Entitlement (Free Tier: Score + Breakdown + Findings)
    filtered_data = cv_review_service.filter_entitlement_response(eval_result, is_premium=False)
    
    # 3. Simpan ke database
    await cv_review_service.save_review(
        user_id=user_id,
        target_position=target_position,
        overall_score=filtered_data.get("overall_score", 0),
        quality_score=filtered_data.get("breakdown_scores", {}).get("ats_compatibility", 0),
        job_match_score=filtered_data.get("breakdown_scores", {}).get("keyword", 0),
        evidence_score=filtered_data.get("breakdown_scores", {}).get("experience", 0),
        review_json=filtered_data,
        confidence_level=eval_result.get("confidence", {}).get("level", "MEDIUM")
    )

    # 4. Tracking Event Funnel
    await analytics_service.log_funnel_event("cv_review_completed", user_id=user_id)
    await analytics_service.log_funnel_event("cv_review_result_viewed", user_id=user_id)

    # 5. Format Tampilan Pesan Diagnosis
    b = filtered_data.get("breakdown_scores", {})

    # Pemetaan fleksibel skor kategori
    ats_score = b.get("ats_compatibility") or b.get("quality") or 70
    format_score = b.get("format_relevance") or b.get("structure") or b.get("keyword") or 75
    exp_score = b.get("experience_impact") or b.get("experience") or b.get("evidence") or 80

    findings = filtered_data.get("findings", [])
    findings_list = "\n".join([f"• {f}" for f in findings]) if findings else "• Format dasar CV sudah terbaca dengan baik."

    review_msg = (
        "📊 <b>HASIL DIAGNOSIS SKOR CV KAMU</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Overall Score:</b> {filtered_data.get('overall_score', 0)} / 100\n\n"
        "📌 <b>Breakdown Kategori:</b>\n"
        f"• ATS Compatibility: <b>{ats_score}/100</b>\n"
        f"• Relevansi Format: <b>{format_score}/100</b>\n"
        f"• Kualitas Pengalaman: <b>{exp_score}/100</b>\n\n"
        "💡 <b>Poin Evaluasi AI:</b>\n"
        f"{findings_list}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 <b>Bikin HRD Langsung Lirik Lamaranmu!</b>\n"
        "Dapatkan <b>CV Rekomendasi AI + Career Page</b>. Order Rp10rb atau ajak 5 teman untuk akses <b>GRATIS</b>! ✨"
    )

    kbd_result = InlineKeyboardMarkup(row_width=1)
    kbd_result.add(
        InlineKeyboardButton("🚀 Order Career Page (Rp10.000)", callback_data="don_10000"),
        InlineKeyboardButton("📣 Gratis via Invite 5 Teman (Referral)", callback_data="home_check_ref"),
        InlineKeyboardButton("🏠 Menu Utama", callback_data="home_back_main")
    )

    await bot.send_message(user_id, review_msg, reply_markup=kbd_result, parse_mode="HTML")