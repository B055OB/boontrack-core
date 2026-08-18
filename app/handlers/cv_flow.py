import os
from aiogram import types
from aiogram.types import InputFile, InlineKeyboardMarkup, InlineKeyboardButton
from app.core.database import (
    save_dropoff,
    save_cv_version,
    track_event,
    count_referrals
)
from app.services.ai_service import enhance_resume_data
from app.services.docx_service import generate_cv_docx
from app.services.analytics_service import analytics_service
from app.handlers.commands import CV_QUESTIONS, TOTAL_STEPS, get_progress_bar

# Path ke gambar QRIS kamu (Pastikan file qris.jpg/png ada di folder assets)
QRIS_IMAGE_PATH = "assets/qris.jpg" 

async def process_cv_step(message: types.Message, user_state: dict, bot):
    user_id = message.from_user.id
    
    if user_id not in user_state or user_state[user_id].get("step", 0) == 0:
        return

    current_step = user_state[user_id]["step"]
    user_data = user_state[user_id]["data"]

    # Simpan jawaban step saat ini
    user_data[current_step] = message.text
    await track_event(user_id, f"step_{current_step}_completed")

    if current_step < TOTAL_STEPS:
        next_step = current_step + 1
        user_state[user_id]["step"] = next_step
        await save_dropoff(user_id, next_step, user_data)
        
        await message.reply(
            f"{get_progress_bar(next_step)}\n{CV_QUESTIONS[next_step]}",
            parse_mode="HTML"
        )
    else:
        # Step 10 Selesai -> Proses Generate CV
        user_state[user_id]["step"] = 0
        await save_dropoff(user_id, TOTAL_STEPS, user_data)
        
        processing_msg = await message.reply(
            "⏳ <b>Sedang memproses & merapikan data CV kamu...</b>\n"
            "AI kami sedang merangkai kata-kata profesional. Mohon tunggu sekitar 15-30 detik ya!",
            parse_mode="HTML"
        )

        try:
            # 1. Poles data dengan AI
            enhanced_data = await enhance_resume_data(user_data)
            
            # 2. Generate File Docx
            file_path = await generate_cv_docx(user_id, enhanced_data)
            
            # 3. Simpan Riwayat versi CV ke DB
            position = enhanced_data.get("position", user_data.get(6, "General"))
            await save_cv_version(user_id, position, enhanced_data)
            await track_event(user_id, "resume_generated", meta={"position": position})

            # 4. Kirimkan File Docx ke User
            document = InputFile(file_path)
            await bot.send_document(
                chat_id=user_id,
                document=document,
                caption="📄 <b>CV ATS-Friendly Kamu Sudah Selesai!</b>\n\nFile .docx telah dilampirkan di atas. Semoga ini menjadi langkah pertama menuju pekerjaan impianmu. 🚀"
            )
            
            # Hapus pesan status tunggu
            await bot.delete_message(chat_id=user_id, message_id=processing_msg.message_id)

            # --- 4.1 HOOK ACQUISITION FUNNEL: FREE CV REVIEW ---
            await analytics_service.log_funnel_event(
                event_name="cv_review_started",
                user_id=user_id,
                metadata={"source": "bot_builder_hook"}
            )
            
            review_keyboard = InlineKeyboardMarkup(row_width=1)
            review_keyboard.add(
                InlineKeyboardButton(
                    text="🔍 REVIEW CV GRATIS SEKARANG",
                    callback_data="trigger_cv_review"
                )
            )
            
            hook_review_text = (
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🎉 <b>CV kamu sudah selesai dibuat!</b>\n\n"
                "Mau tahu seberapa kuat skor CV ini saat diperiksa algoritma ATS recruiter & HR perusahaan?\n\n"
                "Ketahui kelemahan CV-mu sebelum dikirim melamar kerja:"
            )
            await bot