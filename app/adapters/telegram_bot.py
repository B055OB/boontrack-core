import os
import logging
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Mengutamakan host 'backend' bawaan Docker Network
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000/api/v1/search")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Halo! Senang sekali bertemu denganmu! Saya **BoonTrack Assistant**, "
        "konsultan karir yang siap membantu kamu mencapai tujuan karir impianmu. 🚀\n\n"
        "Bagaimana saya bisa membantumu hari ini?\n"
        "1. Memperbarui atau membuat CV\n"
        "2. Mempersiapkan diri untuk wawancara\n"
        "3. Membahas rencana & strategi karir\n"
        "4. Mengatasi tantangan dalam mencari kerja\n\n"
        "Silakan pilih nomor atau ketik langsung kebutuhanmu di sini ya! 😊"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return

    # Indikator typing agar natural
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(BACKEND_URL, params={"q": user_text})
            
            if response.status_code == 200:
                data = response.json()
                
                # Menangkap teks respons dari berbagai kemungkinan kunci (answer, text, message, response)
                reply_message = (
                    data.get("answer") or 
                    data.get("text") or 
                    data.get("message") or 
                    data.get("response")
                )
                
                # Jika data bertingkat / list fallback
                if not reply_message and isinstance(data.get("data"), list) and len(data["data"]) > 0:
                    reply_message = data["data"][0].get("description") or data["data"][0].get("text")

                if not reply_message:
                    reply_message = "Aku paham maksud kamu. Boleh ceritakan lebih spesifik lagi biar aku bisa kasih saran yang pas?"

                # Kirim balasan
                try:
                    await update.message.reply_text(reply_message, parse_mode="Markdown")
                except Exception:
                    # Fallback jika ada error parsing Markdown dari karakter aneh
                    await update.message.reply_text(reply_message)
            else:
                logger.error(f"Backend HTTP status error: {response.status_code}")
                await update.message.reply_text("Waduh, koneksi ke server lagi agak terganggu nih. Coba ketik ulang pesan kamu ya!")

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("Maaf ya, sempat ada kendala teknis sedikit. Coba kirim ulang pesan kamu!")


def run_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN tidak ditemukan di environment variable!")
        return

    app = ApplicationBuilder().token(token).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot Telegram BoonTrack Berhasil Aktif!")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
