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
    @patch("app.core.channels.telegram.send_telegram_photo")
    @patch("app.core.channels.telegram.safe_log_to_supabase_messages")
    async def test_digicorn_callback_query_buy_qris_photo(self, mock_log, mock_send_photo):
        """Memvalidasi klik tombol pembelian produk (buy_DIGI-001) menghasilkan foto QRIS + 3 digit unik."""
        mock_send_photo.return_value = {"ok": True}

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
        mock_send_photo.assert_called_once()
        self.assertEqual(mock_send_photo.call_args[1]["photo"], "assets/qris.jpg")
        self.assertIn("INVOICE PEMBAYARAN QRIS DIGICORN", mock_send_photo.call_args[1]["caption"])
        self.assertIn("3 Digit Unik", mock_send_photo.call_args[1]["caption"])

    @unittest_run_loop
    @patch("app.core.channels.telegram.send_telegram_message")
    @patch("app.core.channels.telegram.safe_log_to_supabase_messages")
    async def test_digicorn_check_payment_pending_and_paid_flow(self, mock_log, mock_send_msg):
        """Memvalidasi tombol cek status pembayaran (Pending -> Paid via Reader Mutation)."""
        mock_send_msg.return_value = {"ok": True}
        from app.services.reconciliation_service import generate_unique_payment_intent, PAYMENT_INTENTS

        # 1. Buat intent
        intent = generate_unique_payment_intent(
            tenant_id="digicorn",
            base_amount=5000,
            product_id="DIGI-001",
            user_id="123456789"
        )
        inv_id = intent["invoice_id"]
        total_nominal = intent["total_amount"]

        # 2. Cek saat status masih PENDING
        payload_check = {
            "update_id": 10010,
            "callback_query": {
                "id": "cb_1010",
                "from": {"id": 123456789, "first_name": "Alldy"},
                "message": {"message_id": 10, "chat": {"id": 123456789, "type": "private"}},
                "data": f"check_pay_{inv_id}"
            }
        }
        resp = await self.client.post("/webhook/telegram/digicorn", json=payload_check)
        self.assertEqual(resp.status, 200)
        mock_send_msg.assert_called_once()
        self.assertIn("PEMBAYARAN BELUM TERDETEKSI", mock_send_msg.call_args[1]["text"])

        # 3. Reader mengirim mutasi EXACT MATCH
        mutation_payload = {
            "amount": total_nominal,
            "tenant_id": "digicorn",
            "message": f"DANA QRIS Masuk Rp{total_nominal:,}"
        }
        resp_mut = await self.client.post("/api/webhook/payment-reader", json=mutation_payload)
        self.assertEqual(resp_mut.status, 200)
        data_mut = await resp_mut.json()
        self.assertEqual(data_mut.get("status"), "SUCCESS")
        self.assertEqual(data_mut.get("action"), "AUTO_FULFILLED_DIGICORN")

        # 4. Cek lagi via tombol setelah PAID
        mock_send_msg.reset_mock()
        resp_after_paid = await self.client.post("/webhook/telegram/digicorn", json=payload_check)
        self.assertEqual(resp_after_paid.status, 200)
        mock_send_msg.assert_called_once()
        self.assertIn("PEMBAYARAN DIVERIFIKASI", mock_send_msg.call_args[1]["text"])
        self.assertIn("drive.google.com", mock_send_msg.call_args[1]["text"])

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

    @unittest_run_loop
    @patch("app.core.channels.telegram.send_telegram_buttons")
    @patch("app.core.channels.telegram.safe_log_to_supabase_messages")
    async def test_dynamic_tenant_resolution_via_bot_id(self, mock_log, mock_send_buttons):
        """Memvalidasi resolusi tenant otomatis dari bot_id di path URL (e.g. /webhook/telegram/8902407474)."""
        mock_send_buttons.return_value = {"ok": True}

        payload = {
            "update_id": 10005,
            "message": {
                "message_id": 5,
                "from": {"id": 111, "first_name": "BotIdTester"},
                "chat": {"id": 111, "type": "private"},
                "text": "menu"
            }
        }

        # Mengakses endpoint menggunakan bot_id prefix
        resp = await self.client.post("/webhook/telegram/8902407474", json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("tenant_id"), "digicorn")

    @unittest_run_loop
    @patch("app.core.channels.telegram.send_telegram_buttons")
    @patch("app.core.channels.telegram.safe_log_to_supabase_messages")
    async def test_dynamic_tenant_resolution_via_secret_token_header(self, mock_log, mock_send_buttons):
        """Memvalidasi resolusi tenant otomatis dari header X-Telegram-Bot-Api-Secret-Token ke /webhook/telegram."""
        mock_send_buttons.return_value = {"ok": True}

        payload = {
            "update_id": 10006,
            "message": {
                "message_id": 6,
                "from": {"id": 222, "first_name": "SecretTester"},
                "chat": {"id": 222, "type": "private"},
                "text": "/start"
            }
        }

        headers = {"X-Telegram-Bot-Api-Secret-Token": "digicorn_secret_2026"}
        resp = await self.client.post("/webhook/telegram", json=payload, headers=headers)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("tenant_id"), "digicorn")

    def test_dynamic_runtime_tenant_registration(self):
        """Memvalidasi pendaftaran tenant baru secara dinamis di runtime tanpa restart/env var."""
        from app.core.tenants.registry import tenant_registry
        
        # Daftarkan tenant baru
        new_tenant = tenant_registry.register_tenant(
            tenant_id="store-xyz",
            name="Store XYZ Creative",
            telegram_token="99887766:ZZZ_TOKEN_TEST_KEY"
        )
        self.assertEqual(new_tenant["name"], "Store XYZ Creative")

        # Resolusi token dan tenant ID
        token = tenant_registry.get_telegram_token("store-xyz")
        self.assertEqual(token, "99887766:ZZZ_TOKEN_TEST_KEY")

        resolved_tid = tenant_registry.resolve_tenant_from_telegram(path_param="99887766")
        self.assertEqual(resolved_tid, "store-xyz")


if __name__ == "__main__":
    unittest.main()

