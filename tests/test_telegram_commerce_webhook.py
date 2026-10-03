"""
test_telegram_commerce_webhook.py
Unit & Integration Test Suite untuk Telegram Commerce Engine Handler:
1. Deep Link Handler: /start link_<tenant_id>
2. Command /id (Personal & Grup)
3. Nonaktifkan Alur CV Legacy
4. Endpoint Webhook Telegram FastAPI & Aiohttp
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.telegram_commerce_service import (
    link_tenant_telegram,
    format_id_reply,
    format_start_welcome,
    format_help_reply,
    format_general_reply,
    process_telegram_incoming,
    handle_telegram_update,
)


class TestTelegramCommerceEngine(unittest.IsolatedAsyncioTestCase):

    def test_id_format_private(self):
        """Memvalidasi format command /id pada chat personal (DM)."""
        reply = format_id_reply(
            chat_id="6075596043",
            user_id="6075596043",
            user_name="Oki",
            chat_type="private"
        )
        self.assertIn("6075596043", reply)
        self.assertIn("Oki", reply)
        self.assertIn("Personal (DM)", reply)
        self.assertNotIn("Grup", reply)

    def test_id_format_group(self):
        """Memvalidasi format command /id pada grup/supergroup."""
        reply = format_id_reply(
            chat_id="-1001234567890",
            user_id="6075596043",
            user_name="Oki",
            chat_title="Toko Kura Official Group",
            chat_type="supergroup"
        )
        self.assertIn("-1001234567890", reply)
        self.assertIn("6075596043", reply)
        self.assertIn("Toko Kura Official Group", reply)
        self.assertIn("Grup", reply)

    def test_welcome_start_has_no_cv_reference(self):
        """Memastikan respon /start generik tidak mengandung alur CV / Karier lama."""
        welcome = format_start_welcome()
        self.assertIn("BoonTrack", welcome)
        self.assertIn("/id", welcome)
        self.assertNotIn("CV", welcome)
        self.assertNotIn("Karier", welcome)
        self.assertNotIn("ATS", welcome)
        self.assertNotIn("Langkah 1", welcome)

    @patch("app.services.telegram_commerce_service.httpx.Client")
    def test_link_tenant_success(self, mock_client_cls):
        """Memvalidasi linking tenant_id ke telegram_chat_id berhasil."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        # Mock GET tenant
        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.json.return_value = [{
            "id": "tenant-uuid-12345",
            "name": "Kura Store",
            "slug": "kurastore",
            "telegram_chat_id": None,
            "metadata": {}
        }]
        mock_client.get.return_value = mock_get_res

        # Mock PATCH tenant
        mock_patch_res = MagicMock()
        mock_patch_res.status_code = 204
        mock_client.patch.return_value = mock_patch_res

        res = link_tenant_telegram(
            tenant_ref="kurastore",
            chat_id="-1001234567890",
            from_user={"id": 12345, "first_name": "Oki"}
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["tenant_id"], "tenant-uuid-12345")
        self.assertEqual(res["tenant_name"], "Kura Store")
        expected_msg = (
            "✅ Toko *Kura Store* berhasil terhubung! "
            "Mulai sekarang seluruh notifikasi order baru dan konfirmasi bayar akan dikirim ke sini."
        )
        self.assertEqual(res["message"], expected_msg)

    @patch("app.services.telegram_commerce_service.httpx.Client")
    def test_link_tenant_not_found(self, mock_client_cls):
        """Memvalidasi penanganan toko yang tidak ditemukan."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.json.return_value = []
        mock_client.get.return_value = mock_get_res

        res = link_tenant_telegram(tenant_ref="unknown-store", chat_id="123456")
        self.assertFalse(res["success"])
        self.assertIn("Toko Tidak Ditemukan", res["message"])

    async def test_process_incoming_deep_link(self):
        """Memvalidasi dispatcher memproses /start link_<tenant_id>."""
        with patch("app.services.telegram_commerce_service.link_tenant_telegram") as mock_link:
            mock_link.return_value = {
                "success": True,
                "tenant_name": "Demo Shop",
                "message": "✅ Toko *Demo Shop* berhasil terhubung!"
            }

            reply = await process_telegram_incoming(
                chat_id="6075596043",
                user_id="6075596043",
                text="/start link_demo-shop",
                user_name="Oki"
            )
            self.assertIn("✅ Toko *Demo Shop* berhasil terhubung!", reply)
            mock_link.assert_called_once_with(
                tenant_ref="demo-shop",
                chat_id="6075596043",
                from_user={"id": "6075596043", "first_name": "Oki"}
            )

    async def test_process_incoming_id(self):
        """Memvalidasi dispatcher memproses /id."""
        reply = await process_telegram_incoming(
            chat_id="-1009999",
            user_id="1111",
            text="/id",
            user_name="Owner",
            chat_type="group",
            chat_title="My Store Group"
        )
        self.assertIn("-1009999", reply)
        self.assertIn("1111", reply)

    async def test_process_incoming_group_silent_ignore(self):
        """Memvalidasi pesan percakapan biasa di grup diabaikan (silent ignore)."""
        reply = await process_telegram_incoming(
            chat_id="-1009999",
            user_id="1111",
            text="selamat pagi semuanya",
            user_name="Member",
            chat_type="supergroup"
        )
        self.assertIsNone(reply)

    async def test_process_incoming_group_wake_word(self):
        """Memvalidasi bot merespons jika dipanggil dengan kata pemicu di grup."""
        reply = await process_telegram_incoming(
            chat_id="-1009999",
            user_id="1111",
            text="Boon tolong infokan",
            user_name="Member",
            chat_type="supergroup"
        )
        self.assertIsNotNone(reply)
        self.assertIn("BoonTrack", reply)
        self.assertNotIn("CV", reply)


if __name__ == "__main__":
    unittest.main()
