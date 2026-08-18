import os
import re
import logging
from app.handlers.commands import CV_QUESTIONS, TOTAL_STEPS

logger = logging.getLogger(__name__)

# State memori percakapan per user ID / No WA
GLOBAL_USER_STATES = {}

LANGUAGE_OPTIONS_TEXT = (
    "Sebelum kita lanjut, CV kamu ingin dibuat dalam bahasa apa?\n\n"
    "1️⃣ *CV English (Ngobrol B. Indonesia)*\n"
    "2️⃣ *CV Bahasa Indonesia*\n"
    "3️⃣ *Full English*\n\n"
    "_Ketik angka 1, 2, atau 3 untuk memilih._"
)

def format_text_for_whatsapp(text: str) -> str:
    """Mengubah format HTML Telegram menjadi Markdown WhatsApp yang rapi"""
    if not text:
        return ""
    text = re.sub(r"</?(b|strong)>", "*", text)
    text = re.sub(r"</?(i|em)>", "_", text)
    text = re.sub(r"</?code>", "```", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()

async def process_unified_cv_step(user_id: str, text_input: str, platform: str = "whatsapp") -> dict:
    """
    Memproses alur pembuatan CV: Bahasa -> Step Data Diri 1 s/d 10.
    """
    if user_id not in GLOBAL_USER_STATES:
        GLOBAL_USER_STATES[user_id] = {"step": 0, "sub_step": "init", "lang": "id", "data": {}}

    session = GLOBAL_USER_STATES[user_id]
    user_data = session.setdefault("data", {})
    sub_step = session.get("sub_step", "init")

    # Inisiasi Awal -> Tampilkan Pilihan 3 Bahasa
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

    # Tangkap Pilihan Bahasa -> Masuk ke Step 1 (Nama Lengkap)
    if sub_step == "choose_lang":
        clean_input = text_input.strip()
        lang_map = {
            "1": "en_id",   # CV English (Ngobrol ID)
            "2": "id",      # Full Indo
            "3": "en"       # Full English
        }
        selected_lang = lang_map.get(clean_input, "id")
        session["lang"] = selected_lang
        session["sub_step"] = "steps"
        session["step"] = 1

        lang_label = "CV English" if selected_lang == "en_id" else ("CV Bahasa Indonesia" if selected_lang == "id" else "Full English")
        
        q_raw = CV_QUESTIONS.get(1, "Siapa nama lengkapmu?")
        q_formatted = format_text_for_whatsapp(q_raw)
        
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

    # Simpan jawaban step aktif saat ini
    current_step = session.get("step", 1)
    user_data[current_step] = text_input.strip()

    try:
        from app.core.database import track_event
        await track_event(str(user_id), f"step_{current_step}_completed")
    except Exception:
        pass

    # Lanjut ke langkah berikutnya
    if current_step < TOTAL_STEPS:
        next_step = current_step + 1
        session["step"] = next_step
        
        try:
            from app.core.database import save_dropoff
            await save_dropoff(str(user_id), next_step, user_data)
        except Exception:
            pass
        
        q_raw = CV_QUESTIONS.get(next_step, "")
        q_formatted = format_text_for_whatsapp(q_raw)
        
        reply_msg = f"📝 *Langkah {next_step}/{TOTAL_STEPS}*\n\n{q_formatted}"
        return {
            "reply_text": reply_msg,
            "messages": [reply_msg],
            "file_path": None,
            "is_completed": False
        }

    # Step 10 Selesai -> Generate & Kirim Penawaran Funnel
    session["step"] = 0
    session["sub_step"] = "init"
    
    try:
        from app.core.database import save_dropoff, save_cv_version, track_event
        await save_dropoff(str(user_id), TOTAL_STEPS, user_data)
        position = user_data.get(6, "General Professional")
        await save_cv_version(str(user_id), position, user_data)
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
        "Data riwayat karir dan profilmu sudah selesai diproses dan dirapikan oleh sistem BoonTrack. 🚀"
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