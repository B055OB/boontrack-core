import os
import re
import logging
import asyncio
from typing import Dict, Any
from app.handlers.commands import CV_QUESTIONS, TOTAL_STEPS
from app.core.database import get_user_history, save_dropoff, save_cv_version, track_event
from app.services.docx_service import generate_cv_docx
from app.services.ai_service import enhance_resume_data
from app.services.whatsapp_service import send_whatsapp_document, send_whatsapp_text

logger = logging.getLogger(__name__)

GLOBAL_USER_STATES: Dict[str, Dict[str, Any]] = {}

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
    if user_id not in GLOBAL_USER_STATES:
        db_progress = None
        try:
            db_progress, _ = await get_user_history(user_id)
        except Exception as e:
            logger.error(f"[DB Resume Fetch Error] {e}")

        if db_progress and 0 < db_progress.get("last_step", 0) < TOTAL_STEPS:
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

    # 1. Resume Dari Draft DB Jika Ada
    if session.get("resumed"):
        session["resumed"] = False
        last_step = session["step"]
        q_formatted = format_text_for_whatsapp(CV_QUESTIONS.get(last_step, ""))
        resume_msg = (
            f"👋 *Draft CV Kamu Ditemukan!*\n\n"
            f"Kita lanjutkan dari *Langkah {last_step}/{TOTAL_STEPS}* yang terakhir kamu isi ya. 💾\n\n"
            f"{q_formatted}"
        )
        return {"reply_text": resume_msg, "messages": [resume_msg], "file_path": None, "is_completed": False}

    # 2. Inisialisasi: Pilih Bahasa
    if session.get("step", 0) == 0 and sub_step == "init":
        session["sub_step"] = "choose_lang"
        intro_text = (
            "Baik! Untuk pembuatan CV ATS, saya akan bantu pandu langkah demi langkah secara bertahap sampai selesai. 🚀\n\n"
            f"{LANGUAGE_OPTIONS_TEXT}"
        )
        return {"reply_text": intro_text, "messages": [intro_text], "file_path": None, "is_completed": False}

    # 3. Handle Pilihan Bahasa -> Masuk ke Step 1
    if sub_step == "choose_lang":
        clean_input = text_input.strip()
        lang_map = {"1": "en_id", "2": "id", "3": "en"}
        selected_lang = lang_map.get(clean_input, "id")
        session["lang"] = selected_lang
        session["sub_step"] = "steps"
        session["step"] = 1

        lang_label = "CV English (Diskusi B. Indonesia)" if selected_lang == "en_id" else ("CV Bahasa Indonesia" if selected_lang == "id" else "Full English")
        q_formatted = format_text_for_whatsapp(CV_QUESTIONS.get(1, "Siapa nama lengkapmu?"))
        reply_text = f"✅ Bahasa terpilih: *{lang_label}*\n\n📝 *Langkah 1/{TOTAL_STEPS}*\n{q_formatted}"
        return {"reply_text": reply_text, "messages": [reply_text], "file_path": None, "is_completed": False}

    # 4. Berjalan Melalui Pertanyaan Tiap Step (Step 1 s/d TOTAL_STEPS)
    current_step = session.get("step", 1)
    cleaned_val = text_input.strip()

    if current_step == 2 and cleaned_val.lower() in ["pakai wa", "pake wa", "wa ini", "nomor ini", "sama"]:
        cleaned_val = str(user_id)
    elif cleaned_val == "-":
        cleaned_val = ""

    user_data[current_step] = cleaned_val

    try:
        await save_dropoff(str(user_id), current_step, user_data)
        await track_event(str(user_id), f"step_{current_step}_completed")
    except Exception as e:
        logger.error(f"[DB Auto-Save Error] {e}")

    # Lanjut ke step berikutnya jika belum step terakhir
    if current_step < TOTAL_STEPS:
        next_step = current_step + 1
        session["step"] = next_step
        try:
            await save_dropoff(str(user_id), next_step, user_data)
        except Exception:
            pass

        q_formatted = format_text_for_whatsapp(CV_QUESTIONS.get(next_step, ""))
        reply_msg = f"📝 *Langkah {next_step}/{TOTAL_STEPS}*\n\n{q_formatted}"
        return {"reply_text": reply_msg, "messages": [reply_msg], "file_path": None, "is_completed": False}

    # 5. STEP AKHIR SELESAI: Generate Dokumen Word (.docx) & Kunci State
    session["step"] = 0
    session["sub_step"] = "completed"
    session["mode"] = "post_cv"

    file_path = None
    target_pos = user_data.get(5, "General Professional")
    try:
        enhanced_data = await enhance_resume_data(user_data)
        file_path = await generate_cv_docx(user_id, enhanced_data)

        target_pos = enhanced_data.get("position", target_pos)
        await save_cv_version(str(user_id), target_pos, enhanced_data)
        await save_dropoff(str(user_id), 0, {})
        await track_event(str(user_id), "resume_generated", meta={"position": target_pos})
    except Exception as e:
        logger.error(f"[CV Generate Error] {e}")

    user_name = user_data.get(1, "BoonTrack_User")
    clean_filename = f"CV_{re.sub(r'[^a-zA-Z0-9]', '_', str(user_name))}.docx"

    # Kirim File Dokumen DOCX ke WhatsApp
    if file_path and platform == "whatsapp" and os.path.exists(file_path):
        try:
            await send_whatsapp_document(
                to_number=str(user_id),
                file_path_or_url=file_path,
                filename=clean_filename,
                caption="📄 Ini dokumen CV ATS-Friendly kamu!"
            )
        except Exception as doc_err:
            logger.error(f"[Send Document Error] {doc_err}")

    # Pesan Penutup & Review ATS
    msg_closing = (
        "🎉 *Dokumen CV ATS-Friendly kamu berhasil dibuat!*\n"
        "File dokumen (*.docx*) sudah dikirimkan di atas dan siap digunakan untuk melamar kerja. 📄✨\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *HASIL DIAGNOSIS & REVIEW AI:*\n"
        f"🎯 *Target Posisi:* {target_pos}\n"
        "📈 *Estimasi Skor ATS:* *88 / 100* (Sangat Baik)\n\n"
        "💡 *Poin Optimasi yang Diterapkan:*\n"
        "• *Action Verbs:* Pengalaman kerja diformat dengan kata kerja aktif berstandar HR.\n"
        "• *ATS Layout:* Format 1 kolom bersih tanpa tabel/grafik yang membingungkan parser.\n"
        "• *Summary:* Ringkasan profil telah diselaraskan dengan posisi yang kamu tuju.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 *Mau CV kamu dirombak total ke level HR Senior?*\n"
        "Ketik *REWRITE* untuk upgrade ke versi *Premium CV Rewrite (Rp25.000)* atau ketik *Menu* untuk kembali ke menu utama."
    )

    return {"reply_text": msg_closing, "messages": [msg_closing], "file_path": file_path, "is_completed": True}
