import os
import re
import logging
from app.handlers.commands import CV_QUESTIONS, TOTAL_STEPS

logger = logging.getLogger(__name__)

# State memori percakapan per user ID / No WA
GLOBAL_USER_STATES = {}

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
    Memproses langkah demi langkah pembuatan CV secara universal.
    """
    if user_id not in GLOBAL_USER_STATES:
        GLOBAL_USER_STATES[user_id] = {"step": 0, "data": {}}

    session = GLOBAL_USER_STATES[user_id]
    current_step = session.get("step", 0)
    user_data = session.setdefault("data", {})

    # Inisiasi Step 1 (Mulai Buat CV + Kalimat Pengantar)
    if current_step == 0:
        session["step"] = 1
        q_raw = CV_QUESTIONS.get(1, "Siapa nama lengkapmu?")
        q_formatted = format_text_for_whatsapp(q_raw)
        
        intro_text = (
            "Baik! Untuk pembuatan CV ATS, saya akan bantu pandu langkah demi langkah secara bertahap sampai selesai. 🚀\n\n"
            f"📝 *Langkah 1/{TOTAL_STEPS}*\n"
            f"{q_formatted}"
        )
        return {
            "reply_text": intro_text,
            "messages": [intro_text],
            "file_path": None,
            "is_completed": False
        }

    # Simpan jawaban step saat ini
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

    # Step 10 Selesai -> Generate & Kirim Penawaran Lengkap
    session["step"] = 0
    
    # 1. Simpan versi ke DB
    try:
        from app.core.database import save_dropoff, save_cv_version, track_event
        await save_dropoff(str(user_id), TOTAL_STEPS, user_data)
        position = user_data.get(6, "General Professional")
        await save_cv_version(str(user_id), position, user_data)
        await track_event(str(user_id), "resume_generated", meta={"position": position})
    except Exception:
        pass

    # 2. Generate File Docx
    file_path = None
    try:
        import app.services.docx_service as docx_srv
        if hasattr(docx_srv, "generate_cv_docx"):
            file_path = await docx_srv.generate_cv_docx(user_id, user_data)
    except Exception as e:
        logger.error(f"[CV Generate File] {e}")

    # 3. Kumpulan Pesan Akhir Funnel
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