import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from app.services.telegram_commerce_service import (
    process_telegram_incoming,
)

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("RUN_BOT")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id if update.message.from_user else chat_id
    user_name = update.message.from_user.first_name if update.message.from_user else "Teman"
    text = update.message.text or ""
    chat_type = update.message.chat.type or "private"
    chat_title = update.message.chat.title

    reply = await process_telegram_incoming(
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        user_name=user_name,
        chat_type=chat_type,
        chat_title=chat_title,
    )
    if reply:
        await update.message.reply_text(reply, parse_mode="Markdown")


async def handle_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id if update.message.from_user else chat_id
    user_name = update.message.from_user.first_name if update.message.from_user else "Pengguna"
    chat_type = update.message.chat.type or "private"
    chat_title = update.message.chat.title

    reply = await process_telegram_incoming(
        chat_id=chat_id,
        user_id=user_id,
        text="/id",
        user_name=user_name,
        chat_type=chat_type,
        chat_title=chat_title,
    )
    if reply:
        await update.message.reply_text(reply, parse_mode="Markdown")


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id if update.message.from_user else chat_id
    user_name = update.message.from_user.first_name if update.message.from_user else "Teman"

    reply = await process_telegram_incoming(
        chat_id=chat_id,
        user_id=user_id,
        text="/help",
        user_name=user_name,
    )
    if reply:
        await update.message.reply_text(reply, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id if update.message.from_user else chat_id
    user_name = update.message.from_user.first_name if update.message.from_user else "Teman"
    text = update.message.text
    chat_type = update.message.chat.type or "private"
    chat_title = update.message.chat.title

    reply = await process_telegram_incoming(
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        user_name=user_name,
        chat_type=chat_type,
        chat_title=chat_title,
    )
    if reply:
        await update.message.reply_text(reply, parse_mode="Markdown")


def run_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN tidak ditemukan di environment!")
        return

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("id", handle_id))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot Telegram BoonTrack Commerce Engine Aktif!")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
