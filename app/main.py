import sys
import os
import asyncio
import logging
from dotenv import load_dotenv

# Setup path aplikasi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MAIN")

from app.core.bot import bot, dp
from app.core.database import init_db
from app.core.server import create_web_app, start_web_server, start_telegram_polling
from app.handlers.telegram_bot_handlers import register_all_bot_handlers

async def start_application():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    print("========================================", flush=True)
    print("[BOOT] BoonTrack Core Service Starting", flush=True)
    print(f"[BOOT] PID          : {os.getpid()}", flush=True)
    print(f"[BOOT] HOSTNAME     : {os.getenv('HOSTNAME', 'unknown')}", flush=True)
    print(f"[BOOT] PORT         : {os.getenv('PORT', '8080')}", flush=True)
    print(f"[BOOT] TOKEN STATUS : {'TERBACA OK' if bot_token else 'KOSONG / UNDEFINED'}", flush=True)
    print("========================================", flush=True)

    # 1. Inisialisasi Skema Database
    print("[BOOT] Initializing database...", flush=True)
    await init_db()

    # 2. Daftarkan Semua Handler Bot Telegram
    register_all_bot_handlers(dp, bot)

    # 3. Buat dan Jalankan Web Server aiohttp
    print("[BOOT] Starting Web Server...", flush=True)
    app = create_web_app()
    port = int(os.getenv("PORT", 8080))
    await start_web_server(app, port=port)

    # 4. Jalankan Background Polling Telegram
    asyncio.create_task(start_telegram_polling(bot, dp))
    print("[BOOT] Telegram & Web Server running concurrently.", flush=True)

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(start_application())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("[SHUTDOWN] Server stopped by user.", flush=True)
    finally:
        loop.stop()
        loop.close()