import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("TELEGRAM_BOT_CORE")

try:
    from aiogram import Bot, Dispatcher
except ModuleNotFoundError:
    Bot = None
    Dispatcher = None
    bot = None
    dp = None
else:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if BOT_TOKEN:
        try:
            bot = Bot(token=BOT_TOKEN)
            dp = Dispatcher(bot)
        except Exception as e:
            logger.warning(f"[TELEGRAM_BOT_CORE] Failed to initialize bot with token: {e}")
            bot = None
            dp = None
    else:
        bot = None
        dp = None

async def send_chunked_message(chat_id: int, text: str, reply_markup=None, parse_mode="HTML"):
    """Mengirim pesan panjang dengan pemecahan chunk cerdas untuk mencegah error limit Telegram (4096 karakter)."""
    if bot is None:
        logger.warning("[TELEGRAM_BOT_CORE] Bot instance is None, skipping message delivery.")
        return

    MAX_CHUNK = 3800
    clean_text = (text or "").strip()
    
    if len(clean_text) <= MAX_CHUNK:
        await bot.send_message(chat_id, clean_text, reply_markup=reply_markup, parse_mode=parse_mode)
        return

    lines = clean_text.split("\n")
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > MAX_CHUNK:
            chunks.append(current_chunk.strip())
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    for idx, chunk in enumerate(chunks):
        is_last = (idx == len(chunks) - 1)
        k_markup = reply_markup if is_last else None
        await bot.send_message(chat_id, chunk, reply_markup=k_markup, parse_mode=parse_mode)
