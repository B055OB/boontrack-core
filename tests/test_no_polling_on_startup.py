import os
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

# 1. Pastikan environment dummy minimal terpasang sebelum app.main dimuat
os.environ.setdefault("DATABASE_URL", "postgresql://mock_user:mock_pass@localhost:5432/mock_db")
os.environ.setdefault("SUPABASE_URL", "https://mock-supabase.boontrack.io")
os.environ.setdefault("SUPABASE_ANON_KEY", "mock-anon-key-boontrack-2026")
os.environ.setdefault("EVOLUTION_API_KEY", "mock-evolution-key")
os.environ.setdefault("XENDIT_SECRET_KEY", "mock-xendit-secret")
os.environ.setdefault("XENDIT_CALLBACK_TOKEN", "mock-callback-token")

# Target pengujian: TELEGRAM_BOT_TOKEN terpasang di env
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:TEST_MOCK_TOKEN_FORMAT_ABCDEF123456"


class TestNoPollingOnStartup(unittest.TestCase):
    """Regression test: Membuktikan Web API startup tidak memicu polling Telegram sama sekali."""

    def test_web_api_startup_zero_polling_with_token_present(self):
        """Memvalidasi bahwa saat FastAPI app di-boot dengan TELEGRAM_BOT_TOKEN terpasang,
        aiogram Dispatcher.start_polling dan runner polling lainnya terpanggil tepat 0 kali.
        """
        from aiogram import Dispatcher
        from app.core import server as core_server

        with patch.object(Dispatcher, "start_polling", new_callable=AsyncMock) as mock_aiogram_polling, \
             patch.object(core_server, "start_telegram_polling", new_callable=AsyncMock) as mock_core_polling:
            
            # Boot FastAPI app via TestClient (mengeksekusi lifespan / startup events)
            from fastapi.testclient import TestClient
            from app.main import app

            with TestClient(app) as client:
                response = client.get("/health")
                # Health endpoint bisa 200 (connected/active) atau format respons valid
                self.assertIn(response.status_code, [200, 503])
                self.assertIn("status", response.json())
            
            # Buktikan dengan assert bahwa fungsi polling terpanggil 0 kali saat Web API startup
            self.assertEqual(
                mock_aiogram_polling.call_count,
                0,
                f"aiogram Dispatcher.start_polling was called {mock_aiogram_polling.call_count} times! Expected 0.",
            )
            self.assertEqual(
                mock_core_polling.call_count,
                0,
                f"app.core.server.start_telegram_polling was called {mock_core_polling.call_count} times! Expected 0.",
            )
            mock_aiogram_polling.assert_not_called()
            mock_core_polling.assert_not_called()

    def test_run_bot_isolation_from_web_api(self):
        """Membuktikan run_bot.py murni berdiri sendiri tanpa dependensi web server FastAPI."""
        import run_bot

        self.assertFalse(hasattr(run_bot, "app"), "run_bot.py should not export or declare FastAPI 'app'")
        self.assertTrue(callable(run_bot.run_bot), "run_bot.py should export a callable run_bot function")

    def test_run_bot_initialization_with_mock_token(self):
        """Memvalidasi bahwa ApplicationBuilder pada run_bot.py mendaftarkan semua handler
        (start, id, help, message) dan siap polling tanpa crash runtime import.
        """
        from telegram.ext import Application
        import run_bot

        created_apps = []
        orig_init = Application.__init__

        def spy_init(self, *args, **kwargs):
            orig_init(self, *args, **kwargs)
            created_apps.append(self)

        with patch.object(Application, "__init__", spy_init), patch.object(Application, "run_polling") as mock_polling:
            run_bot.run_bot()

        self.assertEqual(len(created_apps), 1, "Application should be created once")
        app = created_apps[0]
        handlers = app.handlers.get(0, [])
        self.assertEqual(len(handlers), 4, "run_bot must register exactly 4 handlers (start, id, help, message)")
        self.assertEqual(mock_polling.call_count, 1, "run_bot must call app.run_polling() once")
