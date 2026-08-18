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
    # Ubah <b> atau <strong> menjadi *bold*
    text = re.sub(r"</?(b|strong)>", "*", text)
    # Ubah <i> atau <em> menjadi _italic_
    text = re.sub(r"</?(i|em)>", "_", text)
    # Ubah <code> menjadi ```code```
    text = re.sub(r"</?code>", "```", text)
    # Hapus tag HTML sisa lainnya jika ada
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
        
        return {
            "reply_text": f"📝 *Langkah {next_step}/{TOTAL_STEPS}*\n\n{q_formatted}",
            "file_path": None,
            "is_completed": False
        }

    # Step Terakhir Selesai -> Generate Ringkasan
    session["step"] = 0
    
    try:
        from app.core.database import save_dropoff, save_cv_version, track_event
        await save_dropoff(str(user_id), TOTAL_STEPS, user_data)
        position = user_data.get(6, "General Professional")
        await save_cv_version(str(user_id), position, user_data)
        await track_event(str(user_id), "resume_generated", meta={"position": position})
    except Exception:
        pass

    completion_text = (
        "🎉 *Data Pembuatan CV Selesai Dihimpun!*\n\n"
        "Profil dan riwayat karir kamu telah tersimpan rapi di sistem BoonTrack.\n\n"
        "Ketik *2* untuk melakukan Review Skor ATS, atau ketik *Menu* untuk opsi layanan lainnya."
    )

    return {
        "reply_text": completion_text,
        "file_path": None,
        "is_completed": True
    }