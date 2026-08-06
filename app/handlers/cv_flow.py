import os
from aiogram import types
from aiogram.types import InputFile
from app.core.database import (
    save_dropoff,
    save_cv_version,
    track_event,
    count_referrals
)
from app.services.ai_service import enhance_resume_data
from app.services.docx_service import generate_cv_docx
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

            # --- 5. PESAN DONASI SESUAI INSTRUKSI CTO (CHAT 1) ---
            donation_text = (
                "🎉 <b>CV kamu sudah selesai.</b>\n"
                "Semoga ini menjadi langkah pertama menuju pekerjaan impianmu.\n\n"
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

            # --- 7. PESAN PENUTUP & PROGRAM REFERRAL (WEBSITE REWARD) ---
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