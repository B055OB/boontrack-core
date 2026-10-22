"""scripts/verify_run_bot_init.py
Uji inisialisasi run_bot.py dengan environment mock token format valid.
Membuktikan ApplicationBuilder berhasil mendaftarkan seluruh handler dan siap polling
tanpa crash runtime import.
"""
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Set mock token valid format
MOCK_TOKEN = "123456789:TEST_MOCK_TOKEN_FORMAT_ABCDEF123456"
os.environ["TELEGRAM_BOT_TOKEN"] = MOCK_TOKEN

from unittest.mock import patch
from telegram.ext import Application, CommandHandler, MessageHandler
import run_bot

def verify_initialization():
    print("=" * 60)
    print("[TEST] Memulai Uji Inisialisasi run_bot.py...")
    print(f"[TEST] TELEGRAM_BOT_TOKEN: {MOCK_TOKEN[:10]}... (Valid Format)")
    print("=" * 60)

    created_apps = []
    orig_init = Application.__init__

    def spy_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        created_apps.append(self)

    # Intercept run_polling agar tidak menghubungi server Telegram publik saat uji inisialisasi
    with patch.object(Application, "__init__", spy_init), patch.object(Application, "run_polling") as mock_polling:
        run_bot.run_bot()

    assert len(created_apps) == 1, "ApplicationBuilder gagal menginisialisasi Application instance!"
    app = created_apps[0]
    
    # Verifikasi group 0 handler
    handlers = app.handlers.get(0, [])
    print(f"[OK] ApplicationBuilder berhasil dibuat.")
    print(f"[OK] Jumlah handler terdaftar: {len(handlers)}")
    
    for idx, handler in enumerate(handlers, 1):
        if isinstance(handler, CommandHandler):
            print(f"     {idx}. CommandHandler -> {list(handler.commands)}")
        elif isinstance(handler, MessageHandler):
            print(f"     {idx}. MessageHandler -> {handler.filters}")
        else:
            print(f"     {idx}. {type(handler).__name__}")

    assert len(handlers) == 4, f"Diharapkan 4 handlers, ditemukan {len(handlers)}"
    assert mock_polling.call_count == 1, "app.run_polling() tidak terpanggil saat inisialisasi selesai!"
    print("[OK] app.run_polling() siap dan terpanggil tepat 1 kali.")
    print("[SUCCESS] run_bot.py lulus uji inisialisasi tanpa runtime crash!")
    print("=" * 60)

if __name__ == "__main__":
    verify_initialization()
