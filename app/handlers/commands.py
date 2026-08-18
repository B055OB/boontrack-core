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

CV_QUESTIONS = {
    1: "👤 Siapa nama lengkapmu?",
    2: "📧 Email aktif yang bisa dihubungi recruiter?",
    3: "📱 Nomor WhatsApp / HP aktif? <i>(contoh: 081234567890)</i>",
    4: "📍 Di kota mana kamu berdomisili saat ini?",
    5: "🔗 Link akun LinkedIn kamu? <i>(Ketik '-' jika tidak ada)</i>",
    6: "🎯 Posisi/pekerjaan apa yang ingin kamu lamar?",
    7: (
        "💼 <b>Pengalaman kerja terakhirmu?</b>\n\n"
        "Tuliskan nama posisi, tempat kerja, dan tahunnya.\n"
        "Jika ada lebih dari 1 pekerjaan, pisahkan dengan <b>pindah baris (Enter)</b>, tanda <b>garis tegak ('|')</b>, atau <b>koma (',')</b>.\n\n"
        "<i>Contoh:</i>\n"
        "Kasir — Toko Makmur (2020 - 2022)\n"
        "Staff Admin — PT ABC (2022 - 2024)\n\n"
        "<i>(Ketik '-' jika fresh graduate)</i>"
    ),
    8: "🏆 Ceritakan tugas atau pencapaian utamamu di pekerjaan tersebut. <i>(Tulis santai saja, nanti saya bantu rapikan menjadi poin-poin profesional)</i>",
    9: "🎓 Pendidikan terakhirmu? <i>(contoh: S1 Manajemen, Universitas Terbuka, 2023)</i>",
    10: "🛠️ Apa saja skill atau keahlian utamamu? <i>(contoh: Microsoft Excel, Pelayanan Pelanggan, Kasir)</i>"
}

def get_progress_bar(step: int) -> str:
    return f"📍 <b>Langkah {step} dari {TOTAL_STEPS}</b>\n━━━━━━━━━━"

async def send_welcome(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

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

    await save_user(message.from_user, meta=meta_data)
    await track_event(user_id, "start", meta=meta_data)
    
    progress, last_cv = await get_user_history(user_id)
    first_name = message.from_user.first_name or "Teman"

    saved_data = progress.get("data", {}) if progress else {}
    if user_id not in user_state:
        user_state[user_id] = {"step": progress.get("last_step", 0) if progress else 0, "data": saved_data}

    # Tampilkan Menu Utama Interaktif
    kbd = InlineKeyboardMarkup(row_width=1)
    kbd.add(
        InlineKeyboardButton("📝 Buat / Edit CV Baru", callback_data="restart_flow"),
        InlineKeyboardButton("🔍 Review CV Saya", callback_data="trigger_cv_review"),
        InlineKeyboardButton("🚀 Buat Career Page Profesional", callback_data="open_career_pricing")
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
            f"Halo lagi, {first_name}! 👋\n\n"
            f"Kemarin kita sempat membuat CV sampai di <b>Langkah {last_step} dari {TOTAL_STEPS}</b>.\n\n"
            "Pilih opsi di bawah untuk melanjutkan atau review CV:",
            reply_markup=kbd_resume,
            parse_mode="HTML"
        )
        return

    greeting = (
        f"Halo, {first_name}! 👋\n\n"
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
    
    # 2. Filter Entitlement (Free Tier: Score + Breakdown + 3-5 Findings)
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
    findings_list = "\n".join([f"• {f}" for f in filtered_data.get("findings", [])])

    review_msg = (
        "📊 <b>HASIL DIAGNOSIS SKOR CV KAMU</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Overall Score:</b> {filtered_data.get('overall_score', 0)} / 100\n\n"
        "📌 <b>Breakdown Kategori:</b>\n"
        f"• ATS Compatibility: <b>{b.get('ats_compatibility', 0)}/100</b>\n"
        f"• Relevansi Format: <b>{b.get('format_relevance', 0)}/100</b>\n"
        f"• Kualitas Pengalaman: <b>{b.get('experience_impact', 0)}/100</b>\n\n"
        "💡 <b>Poin Evaluasi AI:</b>\n"
        f"{findings_list}\n\n"
        "<i>Gunakan panduan di atas untuk mengoptimalkan CV kamu agar lolos screening HRD & ATS.</i>"
    )