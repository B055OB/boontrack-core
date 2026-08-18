import os
import logging
from app.core.database import (
    save_dropoff,
    save_cv_version,
    track_event
)
from app.services.ai_service import enhance_resume_data
from app.services.docx_service import generate_cv_docx
from app.handlers.commands import CV_QUESTIONS, TOTAL_STEPS

logger = logging.getLogger(__name__)

# State memori sementara (bisa dialihkan ke Redis di masa mendatang)
GLOBAL_USER_STATES = {}

async def process_unified_cv_step(user_id: str, text_input: str, platform: str = "whatsapp") -> dict:
    """
    Memproses langkah demi langkah pembuatan CV secara universal.
    Return dictionary berisi teks balasan dan data file jika selesai.
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
    await track_event(str(user_id), f"step_{current_step}_completed")

    # Lanjut ke langkah berikutnya
    if current_step < TOTAL_STEPS:
        next_step = current_step + 1
        session["step"] = next_step
        await save_dropoff(str(user_id), next_step, user_data)
        
        q_text = CV_QUESTIONS.get(next_step, "")
        return {
            "reply_text": f"📝 *Langkah {next_step}/{TOTAL_STEPS}*\n\n{q_text}",
            "file_path": None,
            "is_completed": False
        }

    # Step Terakhir Selesai -> Generate Dokumen
    session["step"] = 0
    await save_dropoff(str(user_id), TOTAL_STEPS, user_data)

    try:
        enhanced_data = await enhance_resume_data(user_data)
        file_path = await generate_cv_docx(user_id, enhanced_data)
        
        position = enhanced_data.get("position", user_data.get(6, "General Professional"))
        await save_cv_version(str(user_id), position, enhanced_data)
        await track_event(str(user_id), "resume_generated", meta={"position": position})

        completion_text = (
            "🎉 *CV ATS-Friendly Kamu Sudah Selesai!*\n\n"
            "File dokumen telah selesai diproses oleh AI BoonTrack.\n\n"
            "Ketik *2* jika ingin mengecek skor & rekomendasi ATS, atau ketik *Menu* untuk opsi lain."
        )

        return {
            "reply_text": completion_text,
            "file_path": file_path,
            "is_completed": True
        }

    except Exception as e:
        logger.error(f"[CV Engine] Error generating CV for {user_id}: {e}")
        return {
            "reply_text": "❌ Terjadi kendala saat memproses CV kamu. Ketik *Menu* untuk mencoba kembali.",
            "file_path": None,
            "is_completed": False
        }