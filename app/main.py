import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from app.services.solution_engine import SolutionEngine

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="BoonTrack Core API",
    description="Backend engine for BoonTrack Assistant",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

solution_engine = SolutionEngine()


@app.get("/")
async def root():
    return {"status": "online", "message": "BoonTrack Core Engine is Running"}


@app.get("/api/v1/search")
async def search_endpoint(q: str = ""):
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' cannot be empty.")
    
    result = await solution_engine.find_solution(user_message=q)
    return result


# Handler Telegram Bot untuk /start
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

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        result = await solution_engine.find_solution(user_message=user_text)
        reply_message = result.get("text") or result.get("message") or "Ada yang bisa saya bantu lagi?"

        try:
            await update.message.reply_text(reply_message, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(reply_message)

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("Maaf ya, sempat ada kendala teknis sedikit. Coba kirim ulang pesan kamu!")


# Background Task untuk Run Polling Telegram Bot
@app.on_event("startup")
async def startup_event():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        logger.info("Mulai mengaktifkan Bot Telegram Polling di backend...")
        bot_app = ApplicationBuilder().token(token).build()
        bot_app.add_handler(CommandHandler("start", start_command))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
        logger.info("Bot Telegram Berhasil Aktif!")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN tidak ditemukan, bot Telegram di-skip.")
