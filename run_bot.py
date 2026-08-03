import os
import logging
import httpx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Definisi State/Tahapan Wawancara
NAMA, POSISI, PENDIDIKAN, PENGALAMAN, SKILL = range(5)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1/search")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    welcome_text = (
        "Halo! Saya **BoonTrack Assistant**, konsultan karir impianmu. 🚀\n\n"
        "Mari kita buat CV ATS-Friendly kamu secara sistematis.\n"
        "Pertama-tama, **siapa nama lengkap kamu?**"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")
    return NAMA


async def get_nama(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['nama'] = update.message.text
    await update.message.reply_text(
        f"Salam kenal, **{context.user_data['nama']}**! 😊\n\n"
        "Selanjutnya, **posisi atau bidang pekerjaan apa yang ingin kamu lamar?** (Contoh: Admin, Auditor, Digital Marketing)",
        parse_mode="Markdown"
    )
    return POSISI


async def get_posisi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['posisi'] = update.message.text
    await update.message.reply_text(
        f"Sip! Untuk posisi **{context.user_data['posisi']}**, apa **pendidikan terakhir kamu**? (Sebutkan Nama Sekolah/Kampus & Jurusan)",
        parse_mode="Markdown"
    )
    return PENDIDIKAN


async def get_pendidikan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['pendidikan'] = update.message.text
    await update.message.reply_text(
        "Oke terdata! Apa **pengalaman kerja atau organisasi** yang pernah kamu ikuti?\n"
        "*(Jika belum pernah kerja, ketik: 'Belum ada pengalaman')*",
        parse_mode="Markdown"
    )
    return PENGALAMAN


async def get_pengalaman(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['pengalaman'] = update.message.text
    await update.message.reply_text(
        "Terakhir, apa saja **keahlian (skill) utama, software, atau sertifikasi** yang kamu miliki?",
        parse_mode="Markdown"
    )
    return SKILL


async def get_skill_and_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['skill'] = update.message.text

    await update.message.reply_text("Sedang meracik dan menyusun draft CV ATS-friendly kamu... Tunggu sebentar ya! ⏳")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Susun prompt utuh berisi seluruh data yang sudah dikumpulkan secara pasti
    prompt_final = (
        f"Tolong buatkan draft struktur CV ATS-Friendly lengkap dalam format Markdown berdasarkan data berikut:\n"
        f"- Nama Lengkap: {context.user_data.get('nama')}\n"
        f"- Posisi Dilamar: {context.user_data.get('posisi')}\n"
        f"- Pendidikan Terakhir: {context.user_data.get('pendidikan')}\n"
        f"- Pengalaman Kerja/Organisasi: {context.user_data.get('pengalaman')}\n"
        f"- Keahlian / Skill: {context.user_data.get('skill')}\n\n"
        f"Buat dengan struktur rapi: Ringkasan Profil, Pendidikan, Pengalaman, dan Skill."
    )

    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.get(BACKEND_URL, params={"q": prompt_final})
            if response.status_code == 200:
                data = response.json()
                reply = data.get("text") or data.get("message") or "Draft CV berhasil dibuat!"
                await update.message.reply_text(reply, parse_mode="Markdown")
            else:
                await update.message.reply_text("Maaf, terjadi kendala saat meracik CV. Silakan coba lagi nanti.")
    except Exception as e:
        logger.error(f"Error generating CV: {e}")
        await update.message.reply_text("Maaf, terjadi kendala teknis saat menyusun CV.")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Proses pembuatan CV dibatalkan. Ketik /start kapan saja untuk mulai lagi ya!")
    return ConversationHandler.END


def run_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN tidak ditemukan!")
        return

    app = ApplicationBuilder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_nama)],
            POSISI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_posisi)],
            PENDIDIKAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pendidikan)],
            PENGALAMAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pengalaman)],
            SKILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_skill_and_generate)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    logger.info("Bot Telegram BoonTrack (Mode Form Wizard) Berhasil Aktif!")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
