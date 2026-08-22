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
from app.services.whatsapp_service import log_to_supabase_messages

# Path ke gambar QRIS (Pastikan file qris.jpg/png ada di folder assets)
QRIS_IMAGE_PATH = "assets/qris.jpg" 

async def process_cv_step(message: types.Message, user_state: dict, bot):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Teman"
    raw_input = (message.text or "").strip()

    # 1. Catat setiap jawaban / input teks user Telegram ke Supabase
    if raw_input:
        await log_to_supabase_messages(
            sender=f"Telegram / {first_name}",
            text=raw_input,
            tenant_id="boontrack-career",
            channel="telegram",
            user_id=str(user_id),
            user_name=first_name
        )

    # Jika user tidak dalam alur step builder (step == 0), perlakukan pesan teks sebagai input Review CV instan
    if user_id not in user_state or user_state[user_id].get("step", 0) == 0:
        if len(raw_input) > 40:
            from app.handlers.commands import render_free_cv_review
            await analytics_service.log_funnel_event("cv_uploaded", user_id=user_id, metadata={"type": "raw_text"})
            await render_free_cv_review(user_id, bot, raw_input, target_position="General Professional")
        return

    current_step = user_state[user_id]["step"]
    user_data = user_state[user_id]["data"]

    # Simpan jawaban step saat ini
    user_data[current_step] = raw_input
    await track_event(user_id, f"step_{current_step}_completed")

    if current_step < TOTAL_STEPS:
        next_step = current_step + 1
        user_state[user_id]["step"] = next_step
        await save_dropoff(user_id, next_step, user_data)
        
        step_reply_text = f"{get_progress_bar(next_step)}\n{CV_QUESTIONS[next_step]}"
        await message.reply(step_reply_text, parse_mode="HTML")

        # Catat pertanyaan bot ke Supabase
        await log_to_supabase_messages(
            sender="BoonTrack AI",
            text=step_reply_text,
            tenant_id="boontrack-career",
            channel="telegram",
            user_id=str(user_id),
            user_name=first_name
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
            doc_caption = "📄 <b>CV ATS-Friendly Kamu Sudah Selesai!</b>\n\nFile .docx telah dilampirkan di atas. Semoga ini menjadi langkah pertama menuju pekerjaan impianmu. 🚀"
            await bot.send_document(
                chat_id=user_id,
                document=document,
                caption=doc_caption,
                parse_mode="HTML"
            )
            
            # Catat pengiriman CV selesai ke Supabase
            await log_to_supabase_messages(
                sender="BoonTrack AI",
                text=doc_caption,
                tenant_id="boontrack-career",
                channel="telegram",
                user_id=str(user_id),
                user_name=first_name
            )

            # Hapus pesan status tunggu
            try:
                await bot.delete_message(chat_id=user_id, message_id=processing_msg.message_id)
            except Exception:
                pass

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
            await bot.send_message(
                chat_id=user_id,
                text=hook_review_text,
                reply_markup=review_keyboard,
                parse_mode="HTML"
            )

            # --- 5. PESAN DONASI (CHAT 1) ---
            donation_text = (
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "BoonTrack saat ini masih dikembangkan secara mandiri (bootstrap) tanpa investor.\n"
                "Kalau hasil CV ini menurutmu bermanfaat, kamu boleh mendukung pengembangannya melalui donasi seikhlasnya.\n"
                "Tidak wajib.\n"
                "Tapi setiap dukungan akan membantu kami terus membuat layanan ini tetap gratis untuk banyak pencari kerja.\n"
                "❤️"
            )
            await bot.send_message(user_id, donation_text, parse_mode="HTML")

            # --- 6. KIRIM GAMBAR QRIS (CHAT 2) ---
            if os.path.exists(QRIS_IMAGE_PATH):
                qris_img = InputFile(QRIS_IMAGE_PATH)
                await bot.send_photo(
                    chat_id=user_id,
                    photo=qris_img,
                    caption="Dukungan donasi seikhlasnya melalui QRIS di atas. Terima kasih! 🙏"
                )

            # --- 7. PESAN PENUTUP & PROGRAM REFERRAL ---
            referral_link = f"https://t.me/BoonTrackBot?start=ref_{user_id}"
            
            referral_text = (
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🎁 <b>BONUS TAMBAHAN: WEBSITE LANDING PAGE/PORTOFOLIO GRATIS!</b>\n\n"
                "Mau dibuatkan **Website Portfolio Personal** otomatis dengan domain khusus (contoh: <code>namamu.boontrack.com</code>)?\n\n"
                "Cukup rekomendasikan BoonTrack ke 3 teman pencari kerja menggunakan link ini:\n"
                f"👉 <code>{referral_link}</code>\n\n"
                "Setelah 3 temanmu berhasil membuat CV, bot akan otomatis membukakan akses pembuatan website gratis untukmu! 🚀"
            )
            await bot.send_message(user_id, referral_text, parse_mode="HTML")

            # Hapus file temporer .docx dari server setelah dikirim
            if os.path.exists(file_path):
                os.remove(file_path)

            # --- 8. CEK & KIRIM REWARD UNTUK REFERRER ---
            referrer_id = user_state.get(user_id, {}).get("meta", {}).get("referrer_id")
            if referrer_id:
                total_refs = await count_referrals(referrer_id)
                
                if total_refs == 3:
                    reward_text = (
                        "🎉 <b>SELAMAT! Target 3 Referral Tercapai!</b>\n\n"
                        "3 teman yang kamu rekomendasikan telah berhasil membuat CV di BoonTrack.\n\n"
                        "Sesuai janji, kamu berhak mendapatkan **Website Portfolio Personal Gratis**!\n\n"
                        "Ketik /claim_website untuk mulai memasukkan data website landing page milikmu! 🌐"
                    )
                    try:
                        await bot.send_message(chat_id=int(referrer_id), text=reward_text, parse_mode="HTML")
                        await track_event(int(referrer_id), "referral_reward_unlocked", meta={"total_referrals": 3})
                    except Exception as e:
                        print(f"Gagal mengirimkan pesan reward ke referrer {referrer_id}: {e}")

        except Exception as e:
            print(f"Error Generate CV Flow: {e}")
            await message.reply(
                "❌ Terjadi kendala saat memproses CV kamu. Silakan coba tekan /start kembali ya!",
                parse_mode="HTML"
            )