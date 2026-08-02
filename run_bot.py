import os
import logging
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PASTE_TOKEN_BOT_KAMU_DISINI")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000/api/v1/search")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "Selamat datang di BoonTrack Assistant! 👋\n\n"
        "Aku siap bantu kamu persiapan karir, bikin CV ATS-friendly, latihan interview, sampe atasi grogi saat wawancara.\n\n"
        "Silakan ceritakan masalah atau pertanyaan kamu langsung di sini ya! 😊"
    )
    await update.message.reply_text(welcome_msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # Kirim indikator typing ke Telegram
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Memanggil API backend core
            response = await client.get(BACKEND_URL, params={"q": user_text})
            
            if response.status_code == 200:
                data = response.json()
                
                # Mengambil teks balasan dari berbagai variasi key backend secara fleksibel
                bot_reply = (
                    data.get("text") or 
                    data.get("response") or 
                    data.get("message") or 
                    "Maaf, saya tidak menemukan jawaban yang cocok."
                )
            else:
                bot_reply = "Waduh, koneksi ke server lagi agak terganggu nih. Coba ketik ulang pesan kamu ya! 😊"

    except Exception as e:
        logger.error(f"Error saat menghubungi backend: {str(e)}")
        bot_reply = "Maaf ya, sempat ada kendala teknis sedikit. Coba kirim ulang pesan kamu! 😊"

    # Kirim balasan ke user di Telegram tanpa parse_mode agar 100% aman anti-crash
    await update.message.reply_text(bot_reply)

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot Telegram BoonTrack siap melayani...")
    app.run_polling()

if __name__ == "__main__":
    main()
