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
MENU, NAMA, POSISI, PENDIDIKAN, PENGALAMAN, SKILL = range(6)

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
    welcome_text = (
        "Selamat datang di **BoonTrack Assistant**! 👋\n\n"
        "Aku siap bantu kamu persiapan karir, bikin CV ATS-friendly, latihan interview, sampe atasi grogi saat wawancara.\n\n"
        "Bagaimana saya bisa membantumu hari ini?\n"
        "1. Memperbarui atau membuat CV\n"
        "2. Mempersiapkan diri untuk wawancara\n"
        "3. Membahas rencana & strategi karir\n"
        "4. Mengatasi tantangan dalam mencari kerja\n\n"
        "Silakan pilih nomor atau ketik langsung kebutuhanmu di sini ya! 😊"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")
    return MENU


async def handle_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()

    if text == "1" or "cv" in text or "buat" in text or "perbarui" in text:
        await update.message.reply_text(
            "Siap, mari kita buat/perbarui CV kamu! Pertama-tama, siapa **nama lengkap kamu**?",
            parse_mode="Markdown"
        )
        return NAMA
    else:
        try:
            res = await ai_gateway.generate(prompt=text)
            reply = res.text if hasattr(res, 'text') else str(res)
            await update.message.reply_text(reply, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error AI Menu: {e}")
            await update.message.reply_text("Ada yang bisa saya bantu lagi? Ketik /start untuk kembali ke menu utama.")

        return ConversationHandler.END


async def get_nama(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['nama'] = update.message.text.strip()
    await update.message.reply_text(
        f"Salam kenal, **{context.user_data['nama']}**! 😊\n\n"
        "Selanjutnya, **posisi atau bidang pekerjaan apa yang ingin kamu lamar?** (Contoh: Admin, Auditor, Digital Marketing)",
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
        await update.message.reply_text(
            "\n✨ **Draft CV kamu sudah selesai dibuat!**\n"
            "Ketik /start kapan saja jika ingin membuat CV baru atau memilih menu lainnya.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error generating CV: {e}")
        # Fallback manual jika API Groq mengalami timeout / limit
        fallback_text = (
            f"📄 **DRAFT CV ATS-FRIENDLY**\n\n"
            f"**Nama:** {context.user_data.get('nama')}\n"
            f"**Posisi Dilamar:** {context.user_data.get('posisi')}\n\n"
            f"--- **RINGKASAN PROFIL** ---\n"
            f"Kandidat profesional berdedikasi yang melamar untuk posisi {context.user_data.get('posisi')}. "
            f"Memiliki latar belakang pendidikan dari {context.user_data.get('pendidikan')} serta didukung oleh keahlian {context.user_data.get('skill')}.\n\n"
            f"--- **PENDIDIKAN** ---\n"
            f"• {context.user_data.get('pendidikan')}\n\n"
            f"--- **PENGALAMAN** ---\n"
            f"• {context.user_data.get('pengalaman')}\n\n"
            f"--- **KEAHLIAN / SKILL** ---\n"
            f"• {context.user_data.get('skill')}\n\n"
            f"✨ Ketik /start untuk kembali ke menu utama."
        )
        await update.message.reply_text(fallback_text, parse_mode="Markdown")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Proses dibatalkan. Ketik /start kapan saja untuk membuka menu utama lagi ya!")
    return ConversationHandler.END


# --- BACKEND STARTUP EVENT ---

@app.on_event("startup")
async def startup_event():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        logger.info("Mulai mengaktifkan Bot Telegram ConversationHandler di backend...")
        bot_app = ApplicationBuilder().token(token).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_choice)],
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
