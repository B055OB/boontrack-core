import os
import logging
from app.core.database import (
    save_dropoff,
    save_cv_version,
    track_event
)
from app.services.docx_service import generate_cv_docx
from app.handlers.commands import CV_QUESTIONS, TOTAL_STEPS

logger = logging.getLogger(__name__)

# State memori sementara per user ID / No WA
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
    try:
        await track_event(str(user_id), f"step_{current_step}_completed")
    except Exception as e:
        logger.warning(f"Track event skipped: {e}")

    # Lanjut ke langkah berikutnya
    if current_step < TOTAL_STEPS:
        next_step = current_step + 1
        session["step"] = next_step
        try:
            await save_dropoff(str(user_id), next_step, user_data)
        except Exception as e:
            logger.warning(f"Save dropoff skipped: {e}")
        
        q_text = CV_QUESTIONS.get(next_step, "")
        return {
            "reply_text": f"📝 *Langkah {next_step}/{TOTAL_STEPS}*\n\n{q_text}",
            "file_path": None,
            "is_completed": False
        }

    # Step Terakhir Selesai -> Generate Dokumen
    session["step"] = 0
    try:
        await save_dropoff(str(user_id), TOTAL_STEPS, user_data)
    except Exception:
        pass

    try:
        # Panggil enhance_resume_data secara dinamis jika tersedia di ai_service
        enhanced_data = user_data
        try:
            import app.services.ai_service as ai_srv
            if hasattr(ai_srv, "enhance_resume_data"):
                enhanced_data = await ai_srv.enhance_resume_data(user_data)
        except Exception as e:
            logger.warning(f"AI resume enhancement fallback: {e}")

        file_path = await generate_cv_docx(user_id, enhanced_data)
        position = user_data.get(6, "General Professional")
        
        try:
            await save_cv_version(str(user_id), position, enhanced_data)
            await track_event(str(user_id), "resume_generated", meta={"position": position})
        except Exception:
            pass

        completion_text = (
            "🎉 *CV ATS-Friendly Kamu Sudah Selesai!*\n\n"
            "Draf CV kamu telah berhasil dibuat dan dirapikan oleh sistem BoonTrack.\n\n"
            "Ketik *2* untuk melakukan Review Skor ATS, atau ketik *Menu* untuk opsi lain."
        )

        return {
            "reply_text": completion_text,
            "file_path": file_path,
            "is_completed": True
        }

    except Exception as e:
        logger.error(f"[CV Engine] Error generating CV for {user_id}: {e}")
        return {
            "reply_text": "❌ Terjadi kendala saat memproses file CV. Ketik *Menu* untuk mencoba kembali.",
            "file_path": None,
            "is_completed": False
        }