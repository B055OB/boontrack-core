import os
import logging
from app.handlers.commands import CV_QUESTIONS, TOTAL_STEPS

logger = logging.getLogger(__name__)

# State memori percakapan per user ID / No WA
GLOBAL_USER_STATES = {}

async def process_unified_cv_step(user_id: str, text_input: str, platform: str = "whatsapp") -> dict:
    """
    Memproses langkah demi langkah pembuatan CV secara universal.
    """
    if user_id not in GLOBAL_USER_STATES:
        GLOBAL_USER_STATES[user_id] = {"step": 0, "data": {}}

    session = GLOBAL_USER_STATES[user_id]
    current_step = session.get("step", 0)
    user_data = session.setdefault("data", {})

    # Inisiasi Step 1 (Mulai Buat CV)
    if current_step == 0:
        session["step"] = 1
        q_text = CV_QUESTIONS.get(1, "Siapa nama lengkapmu?")
        return {
            "reply_text": f"🚀 *Langkah 1/{TOTAL_STEPS}*\n\n{q_text}",
            "file_path": None,
            "is_completed": False
        }

    # Simpan jawaban step saat ini
    user_data[current_step] = text_input.strip()

    # Track event database secara aman (opsional)
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
        
        q_text = CV_QUESTIONS.get(next_step, "")
        return {
            "reply_text": f"📝 *Langkah {next_step}/{TOTAL_STEPS}*\n\n{q_text}",
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