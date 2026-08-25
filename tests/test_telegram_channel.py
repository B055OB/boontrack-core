import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from app.core.server import create_web_app
from app.core.channels.telegram import resolve_tenant_telegram_token, send_telegram_message, send_telegram_buttons
from app.tenants.digicorn.config import DIGICORN_TELEGRAM_TOKEN, DIGICORN_TENANT_ID


class TestTelegramCentralChannel(AioHTTPTestCase):

    async def get_application(self):
        return create_web_app()

    def test_token_resolution(self):
        """Memvalidasi pemetaan token multi-tenant."""
        # 1. Digicorn token
        digicorn_token = resolve_tenant_telegram_token("digicorn")
        self.assertEqual(digicorn_token, "8902407474:AAEewbDZ8tddpVLtRI7xowIy6nWV1cW8KNA")

        # 2. Case insensitive & hyphen format
        self.assertEqual(resolve_tenant_telegram_token("DIGICORN"), "8902407474:AAEewbDZ8tddpVLtRI7xowIy6nWV1cW8KNA")

    @unittest_run_loop
    async def test_webhook_ping(self):
        """Memvalidasi endpoint health check / ping webhook Telegram."""
        resp = await self.client.get("/webhook/telegram/digicorn")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "active")
        self.assertEqual(data.get("tenant_id"), "digicorn")

    @unittest_run_loop
    @patch("app.core.channels.telegram.send_telegram_buttons")
    @patch("app.core.channels.telegram.safe_log_to_supabase_messages")
    @patch("app.core.channels.telegram.ai_gateway.generate")
    async def test_digicorn_start_command_flow(self, mock_ai, mock_log, mock_send_buttons):
        """Memvalidasi alur perintah /start pada bot Telegram Digicorn."""
        mock_ai.return_value = "Hai! Selamat berbelanja produk digital serba 5rb!"
        mock_send_buttons.return_value = {"ok": True}

        payload = {
            "update_id": 10001,
            "message": {
                "message_id": 1,
                "from": {"id": 123456789, "first_name": "Alldy", "username": "alldy_dev"},
                "chat": {"id": 123456789, "type": "private"},
                "text": "/start"
            }
        }

        resp = await self.client.post("/webhook/telegram/digicorn", json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("tenant_id"), "digicorn")

        # Pastikan tombol produk & pesan terkirim
        mock_send_buttons.assert_called_once()
        self.assertEqual(mock_send_buttons.call_args[1]["chat_id"], 123456789)
        self.assertEqual(mock_send_buttons.call_args[1]["bot_token"], DIGICORN_TELEGRAM_TOKEN)

        # Pastikan logging Supabase inbound & outbound dipanggil
        self.assertEqual(mock_log.call_count, 2)

    @unittest_run_loop
    @patch("app.core.channels.telegram.send_telegram_buttons")
    @patch("app.core.channels.telegram.safe_log_to_supabase_messages")
    @patch("app.core.channels.telegram.ai_gateway.generate")
    async def test_digicorn_product_search_flow(self, mock_ai, mock_log, mock_send_buttons):
        """Memvalidasi pencarian produk digital via AI Gateway & Commerce."""
        mock_ai.return_value = "Ini pilihan template excel terbaik untuk Anda:"
        mock_send_buttons.return_value = {"ok": True}

        payload = {
            "update_id": 10002,
            "message": {
                "message_id": 2,
                "from": {"id": 987654321, "first_name": "Budi", "username": "budi_user"},
                "chat": {"id": 987654321, "type": "private"},
                "text": "excel keuangan"
            }
        }

        resp = await self.client.post("/webhook/telegram/digicorn", json=payload)
        self.assertEqual(resp.status, 200)
        mock_send_buttons.assert_called_once()
        self.assertIn("HASIL PENCARIAN", mock_send_buttons.call_args[1]["text"])

    @unittest_run_loop
    @patch("app.core.channels.telegram.send_telegram_buttons")
    @patch("app.core.channels.telegram.safe_log_to_supabase_messages")
    async def test_digicorn_callback_query_buy(self, mock_log, mock_send_buttons):
        """Memvalidasi klik tombol callback pembelian produk (buy_DIGI-001)."""
        mock_send_buttons.return_value = {"ok": True}

        payload = {
            "update_id": 10003,
            "callback_query": {
                "id": "cb_999",
                "from": {"id": 123456789, "first_name": "Alldy"},
                "message": {
                    "message_id": 3,
                    "chat": {"id": 123456789, "type": "private"}
                },
                "data": "buy_DIGI-001"
            }
        }

        resp = await self.client.post("/webhook/telegram/digicorn", json=payload)
        self.assertEqual(resp.status, 200)
        mock_send_buttons.assert_called_once()
        self.assertIn("PEMESANAN PRODUK DIGITAL", mock_send_buttons.call_args[1]["text"])

    @unittest_run_loop
    @patch("app.core.channels.telegram.send_telegram_message")
    @patch("app.core.channels.telegram.safe_log_to_supabase_messages")
    @patch("app.core.channels.telegram.ai_gateway.generate")
    async def test_universal_tenant_ai_fallback(self, mock_ai, mock_log, mock_send_msg):
        """Memvalidasi routing AI Gateway untuk tenant umum."""
        mock_ai.return_value = "Konsultasi dari AI Gateway berhasil."
        mock_send_msg.return_value = {"ok": True}

        payload = {
            "update_id": 10004,
            "message": {
                "message_id": 4,
                "from": {"id": 55555, "first_name": "Tester"},
                "chat": {"id": 55555, "type": "private"},
                "text": "Bagaimana tips karir di bidang data science?"
            }
        }

        resp = await self.client.post("/webhook/telegram/career", json=payload)
        self.assertEqual(resp.status, 200)
        mock_send_msg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
