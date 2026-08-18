import os
import re
import logging
from app.handlers.commands import CV_QUESTIONS, TOTAL_STEPS
from app.core.database import get_user_history, save_dropoff, save_cv_version, track_event

logger = logging.getLogger(__name__)

GLOBAL_USER_STATES = {}

LANGUAGE_OPTIONS_TEXT = (
    "Sebelum kita mulai, CV kamu ingin dibuat dalam bahasa apa?\n\n"
    "1️⃣ *CV English (Ngobrol B. Indonesia)*\n"
    "2️⃣ *CV Bahasa Indonesia*\n"
    "3️⃣ *Full English*\n\n"
    "_Ketik angka 1, 2, atau 3 untuk memilih._"
)

def format_text_for_whatsapp(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", text)
    text = re.sub(r"</?(b|strong)>", "*", text)
    text = re.sub(r"</?(i|em)>", "_", text)
    text = re.sub(r"</?code>", "```", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()

async def process_unified_cv_step(user_id: str, text_input: str, platform: str = "whatsapp") -> dict:
    # 1. Pulihkan State dari Database jika memori kosong (Anti-Hilang saat Server Restart)
    if user_id not in GLOBAL_USER_STATES:
        db_progress = None
        try:
            db_progress, _ = await get_user_history(user_id)
        except Exception as e:
            logger.error(f"[DB Resume Fetch Error] {e}")

        if db_progress and db_progress.get("last_step", 0) > 0 and db_progress.get("last_step", 0) < TOTAL_STEPS:
            # Konversi key string dari JSON DB ke integer
            raw_db_data = db_progress.get("data", {})
            restored_data = {int(k): v for k, v in raw_db_data.items() if str(k).isdigit()}
            
            GLOBAL_USER_STATES[user_id] = {
                "step": db_progress["last_step"],
                "sub_step": "steps",
                "lang": db_progress.get("lang", "id"),
                "data": restored_data,
                "resumed": True
            }
        else:
            GLOBAL_USER_STATES[user_id] = {"step": 0, "sub_step": "init", "lang": "id", "data": {}}

    session = GLOBAL_USER_STATES[user_id]
    user_data = session.setdefault("data", {})
    sub_step = session.get("sub_step", "init")

    # 2. Tangani User yang Datanya Berhasil Dipulihkan (Auto-Resume Hook)
    if session.get("resumed"):
        session["resumed"] = False
        last_step = session["step"]
        q_formatted = format_text_for_whatsapp(CV_QUESTIONS.get(last_step, ""))
        
        resume_msg = (
            f"👋 *Draft CV Kamu Ditemukan!*\n\n"
            f"Kita lanjutkan dari *Langkah {last_step}/{TOTAL_STEPS}* yang terakhir kamu isi ya. Semua data sebelumnya sudah tersimpan aman. 💾\n\n"
            f"{q_formatted}"
        )
        return {
            "reply_text": resume_msg,
            "messages": [resume_msg],
            "file_path": None,
            "is_completed": False
        }

    # 3. Inisiasi Pilihan Bahasa
    if session.get("step", 0) == 0 and sub_step == "init":
        session["sub_step"] = "choose_lang"
        intro_text = (
            "Baik! Untuk pembuatan CV ATS, saya akan bantu pandu langkah demi langkah secara bertahap sampai selesai. 🚀\n\n"
            f"{LANGUAGE_OPTIONS_TEXT}"
        )
        return {
            "reply_text": intro_text,
            "messages": [intro_text],
            "file_path": None,
            "is_completed": False
        }

    # 4. Tangkap Pilihan Bahasa -> Masuk Langkah 1
    if sub_step == "choose_lang":
        clean_input = text_input.strip()
        lang_map = {"1": "en_id", "2": "id", "3": "en"}
        selected_lang = lang_map.get(clean_input, "id")
        session["lang"] = selected_lang
        session["sub_step"] = "steps"
        session["step"] = 1

        lang_label = "CV English" if selected_lang == "en_id" else ("CV Bahasa Indonesia" if selected_lang == "id" else "Full English")
        q_formatted = format_text_for_whatsapp(CV_QUESTIONS.get(1, "Siapa nama lengkapmu?"))
        
        reply_text = (
            f"✅ Bahasa terpilih: *{lang_label}*\n\n"
            f"📝 *Langkah 1/{TOTAL_STEPS}*\n"
            f"{q_formatted}"
        )
        return {
            "reply_text": reply_text,
            "messages": [reply_text],
            "file_path": None,
            "is_completed": False
        }

    # 5. Simpan Jawaban Step Aktif & Simpan Permanen ke DB
    current_step = session.get("step", 1)
    cleaned_val = text_input.strip()

    if current_step == 2 and cleaned_val.lower() in ["pakai wa", "pake wa", "wa ini", "nomor ini", "sama"]:
        cleaned_val = str(user_id)
    elif cleaned_val == "-":
        cleaned_val = ""

    user_data[current_step] = cleaned_val

    # Auto-Save Permanen setiap user submit pesan
    try:
        await save_dropoff(str(user_id), current_step, user_data)
        await track_event(str(user_id), f"step_{current_step}_completed")
    except Exception as e:
        logger.error(f"[DB Auto-Save Error] {e}")

    # 6. Lanjut ke Langkah Berikutnya
    if current_step < TOTAL_STEPS:
        next_step = current_step + 1
        session["step"] = next_step
        
        try:
            await save_dropoff(str(user_id), next_step, user_data)
        except Exception:
            pass

        q_formatted = format_text_for_whatsapp(CV_QUESTIONS.get(next_step, ""))
        reply_msg = f"📝 *Langkah {next_step}/{TOTAL_STEPS}*\n\n{q_formatted}"
        return {
            "reply_text": reply_msg,
            "messages": [reply_msg],
            "file_path": None,
            "is_completed": False
        }

    # 7. Selesai Semua Langkah -> Poles dengan AI & Render Dokumen
    session["step"] = 0
    session["sub_step"] = "init"

    try:
        position = user_data.get(5, "General Professional")
        await save_cv_version(str(user_id), position, user_data)
        await save_dropoff(str(user_id), 0, {}) # Reset status dropoff karena sudah beres
        await track_event(str(user_id), "resume_generated", meta={"position": position, "lang": session.get("lang")})
    except Exception:
        pass

    file_path = None
    try:
        from app.services.cv_generator_service import cv_generator_service
        file_path = await cv_generator_service.polish_and_build_cv(
            user_id=str(user_id), 
            raw_data=user_data, 
            lang_mode=session.get("lang", "id")
        )
    except Exception as e:
        logger.error(f"[CV Polisher] {e}")

    msg_1 = (
        "📄 *CV ATS-Friendly Kamu Berhasil Dibuat!*\n\n"
        "Data riwayat karir dan profilmu sudah selesai dipoles dan dirapikan oleh AI BoonTrack. 🚀"
    )
    msg_2 = (
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 *BONUS: WEBSITE CAREER PAGE & PORTOFOLIO GRATIS!*\n\n"
        "Mau dibuatkan *Website Portfolio Personal* otomatis siap pakai untuk melamar kerja (contoh: _namamu.boontrack.com_)?\n\n"
        "Cukup bagikan layanan BoonTrack ke 3 teman pencari kerja. Ketik *Career Page* untuk informasi klaim selengkapnya! 🌐"
    )
    msg_3 = (
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "BoonTrack dikembangkan secara mandiri untuk membantu pencari kerja di Indonesia.\n\n"
        "Ketik *2* jika ingin mengecek skor ATS & optimasi kata kunci, atau ketik *Menu* untuk opsi layanan lainnya. ☕"
    )

    return {
        "reply_text": msg_1,
        "messages": [msg_1, msg_2, msg_3],
        "file_path": file_path,
        "is_completed": True
    }