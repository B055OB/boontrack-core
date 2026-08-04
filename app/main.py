import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

from app.intelligence.gateway import AIGateway

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Definisi State untuk ConversationHandler
NAMA, POSISI, PENDIDIKAN, PENGALAMAN, SKILL = range(5)

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

ai_gateway = AIGateway()


@app.get("/")
async def root():
    return {"status": "online", "message": "BoonTrack Core Engine is Running"}


# --- HANDLER CONVERSATION TELEGRAM BOT ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    welcome_text = (
        "Selamat datang di **BoonTrack Assistant**! 👋\n\n"
        "Mari kita buat CV ATS-Friendly kamu secara sistematis.\n\n"
        "Pertama-tama, **siapa nama lengkap kamu?**"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")
    return NAMA


async def get_nama(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['nama'] = update.message.text.strip()
    await update.message.reply_text(
        f"Salam kenal, **{context.user_data['nama']}**! 😊\n\n"
        "Selanjutnya, **posisi atau bidang pekerjaan apa yang ingin kamu lamar?** (Contoh: Developer, Admin, Auditor)",
        parse_mode="Markdown"
    )
    return POSISI


async def get_posisi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['posisi'] = update.message.text.strip()
    await update.message.reply_text(
        f"Sip! Untuk posisi **{context.user_data['posisi']}**, apa **pendidikan terakhir kamu**? (Sebutkan Nama Sekolah/Kampus & Jurusan)",
        parse_mode="Markdown"
    )
    return PENDIDIKAN


async def get_pendidikan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['pendidikan'] = update.message.text.strip()
    await update.message.reply_text(
        "Oke terdata! Apa **pengalaman kerja terakhir atau organisasi** yang pernah kamu ikuti?\n"
        "*(Jika belum pernah kerja, ketik: 'Belum ada pengalaman')*",
        parse_mode="Markdown"
    )
    return PENGALAMAN


async def get_pengalaman(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['pengalaman'] = update.message.text.strip()
    await update.message.reply_text(
        "Terakhir, apa saja **keahlian (skill) utama, software, atau sertifikasi** yang kamu miliki?",
        parse_mode="Markdown"
    )
    return SKILL


async def get_skill_and_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['skill'] = update.message.text.strip()

    await update.message.reply_text("Sedang meracik dan menyusun draft CV ATS-friendly kamu... Tunggu sebentar ya! ⏳")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    prompt_final = (
        f"Tolong buatkan draft struktur CV ATS-Friendly lengkap dalam format Markdown berdasarkan data berikut:\n\n"
        f"Nama Lengkap: {context.user_data.get('nama')}\n"
        f"Posisi Dilamar: {context.user_data.get('posisi')}\n"
        f"Pendidikan Terakhir: {context.user_data.get('pendidikan')}\n"
        f"Pengalaman Kerja/Organisasi: {context.user_data.get('pengalaman')}\n"
        f"Keahlian / Skill: {context.user_data.get('skill')}\n\n"
        f"Format susunan rapi:\n"
        f"1. Ringkasan Profil\n"
        f"2. Pendidikan\n"
        f"3. Pengalaman\n"
        f"4. Keahlian/Skill\n\n"
        f"Berikan juga 2-3 tips singkat peningkat daya saing untuk posisi tersebut."
    )

    try:
        res = await ai_gateway.generate(prompt=prompt_final)
        reply = res.text if hasattr(res, 'text') else str(res)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error generating CV: {e}")
        fallback_text = (
            f"📄 **DRAFT CV ATS-FRIENDLY**\n\n"
            f"**Nama:** {context.user_data.get('nama')}\n"
            f"**Posisi Dilamar:** {context.user_data.get('posisi')}\n\n"
            f"--- **RINGKASAN PROFIL** ---\n"
            f"Kandidat profesional berdedikasi yang melamar untuk posisi {context.user_data.get('posisi')}.\n\n"
            f"--- **PENDIDIKAN** ---\n"
            f"• {context.user_data.get('pendidikan')}\n\n"
            f"--- **PENGALAMAN** ---\n"
            f"• {context.user_data.get('pengalaman')}\n\n"
            f"--- **KEAHLIAN / SKILL** ---\n"
            f"• {context.user_data.get('skill')}\n"
        )
        await update.message.reply_text(fallback_text, parse_mode="Markdown")

    await update.message.reply_text(
        "\n✨ **Selesai!** Ketik /start jika ingin membuat CV lagi dari awal ya! 😊",
        parse_mode="Markdown"
    )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Proses dibatalkan. Ketik /start kapan saja untuk mulai lagi ya!")
    return ConversationHandler.END


# --- BACKEND STARTUP EVENT ---

@app.on_event("startup")
async def startup_event():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        logger.info("Mulai mengaktifkan Bot Telegram ConversationHandler di backend...")
        bot_app = ApplicationBuilder().token(token).build()

        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, start)
            ],
            states={
                NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_nama)],
                POSISI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_posisi)],
                PENDIDIKAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pendidikan)],
                PENGALAMAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pengalaman)],
                SKILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_skill_and_generate)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )

        bot_app.add_handler(conv_handler)

        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
        logger.info("Bot Telegram Berhasil Aktif dengan Mode State Wizard!")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN tidak ditemukan, bot Telegram di-skip.")
