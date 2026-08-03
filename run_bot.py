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

# Definisi State / Tahapan Wawancara
MENU, NAMA, POSISI, PENDIDIKAN, PENGALAMAN, SKILL = range(6)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1/search")


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

    # Jika user memilih angka 1 atau kata kunci buat CV
    if text == "1" or "cv" in text or "buat" in text or "perbarui" in text:
        await update.message.reply_text(
            "Siap, mari kita buat/perbarui CV kamu! Pertama-tama, boleh tahu siapa **nama lengkap kamu**?",
            parse_mode="Markdown"
        )
        return NAMA
    else:
        # Jika memilih menu 2, 3, 4 atau pertanyaan bebas lainnya
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                response = await client.get(BACKEND_URL, params={"q": text})
                if response.status_code == 200:
                    data = response.json()
                    reply = data.get("text") or data.get("message") or "Ada yang bisa saya bantu lagi?"
                    await update.message.reply_text(reply, parse_mode="Markdown")
                else:
                    await update.message.reply_text("Maaf, terjadi kendala saat memproses jawaban.")
        except Exception as e:
            logger.error(f"Error pada handle_menu_choice: {e}")
            await update.message.reply_text("Ada yang bisa saya bantu lagi?")

        return ConversationHandler.END


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
        "Oke terdata! Apa **pengalaman kerja terakhir atau organisasi** yang pernah kamu ikuti?\n"
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
    await update.message.reply_text("Proses dibatalkan. Ketik /start kapan saja untuk membuka menu utama lagi ya!")
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
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_choice)],
            NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_nama)],
            POSISI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_posisi)],
            PENDIDIKAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pendidikan)],
            PENGALAMAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pengalaman)],
            SKILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_skill_and_generate)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    logger.info("Bot Telegram BoonTrack (Mode Form Wizard + Menu) Berhasil Aktif!")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
