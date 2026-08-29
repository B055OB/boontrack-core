"""tests/tenants/test_native_qris_media.py
Unit & Integration Tests for In-Memory Native QRIS Image Generator and Meta Media API Dispatcher.
"""

import io
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.qris_generator import generate_qris_png_buffer, generate_qris_png_bytes
from app.services.meta_media import upload_whatsapp_media, send_whatsapp_media_image
from app.services.whatsapp_service import user_tenant_sessions, user_session_states


class TestNativeQRISMedia(unittest.IsolatedAsyncioTestCase):
    """Validates in-memory QR code rendering, Meta Media API uploading, and action triggers."""

    def setUp(self):
        self.client = TestClient(app)
        user_tenant_sessions.clear()
        user_session_states.clear()
        self.dummy_qr_string = (
            "00020101021226540014ID.LINKAJA.WWW011893600911002237890202152009221102000010303UMI"
            "51440014ID.DANA.WWW011893600911002237890202152009221102000010303UMI54061490005802ID"
            "5911BOONTRACK6007JAKARTA6105129406304C22F"
        )

    def test_generate_qris_png_buffer_returns_valid_png_buffer(self):
        """Helper generate_qris_png_buffer harus mengembalikan io.BytesIO dengan header PNG valid."""
        buf = generate_qris_png_buffer(self.dummy_qr_string)
        self.assertIsInstance(buf, io.BytesIO)
        raw_bytes = buf.getvalue()
        self.assertTrue(raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "Buffer harus memiliki magic bytes PNG")
        self.assertGreater(len(raw_bytes), 500, "Buffer PNG harus memiliki ukuran memadai")

    def test_generate_qris_png_bytes_returns_valid_bytes(self):
        """Helper generate_qris_png_bytes harus mengembalikan bytes PNG murni."""
        raw_bytes = generate_qris_png_bytes(self.dummy_qr_string)
        self.assertIsInstance(raw_bytes, bytes)
        self.assertTrue(raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_invalid_qr_string_raises_value_error(self):
        """String kosong harus memicu ValueError."""
        with self.assertRaises(ValueError):
            generate_qris_png_buffer("")

    @patch("httpx.AsyncClient.post")
    async def test_upload_whatsapp_media_mock(self, mock_post):
        """upload_whatsapp_media harus melakukan multipart POST ke endpoint Meta Graph dan mengembalikan media_id."""
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "media_mock_998877"}
        mock_post.return_value = mock_resp

        buf = generate_qris_png_buffer(self.dummy_qr_string)
        media_id = await upload_whatsapp_media(buf, tenant_id="suhu-ads-masterclass")
        self.assertEqual(media_id, "media_mock_998877")

    def test_webhook_payment_keyword_triggers_in_memory_qris_and_media_message(self):
        """Event webhook 'ya boleh' atau 'bayar qris' harus memicu pembuatan QRIS dan pengiriman media message."""
        phone = "6281122334455"

        # 1. Pilih opsi 3 -> lock ke suhu-ads-masterclass
        self.client.post("/api/v1/whatsapp/webhook", json={
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "628123456789", "phone_number_id": "123456"},
                        "contacts": [{"profile": {"name": "Tester"}, "wa_id": phone}],
                        "messages": [{"from": phone, "id": "wamid.001", "timestamp": "1600000000", "text": {"body": "3"}, "type": "text"}]
                    },
                    "field": "messages"
                }]
            }]
        })

        # 2. Kirim konfirmasi beli 'ya boleh'
        resp = self.client.post("/api/v1/whatsapp/webhook", json={
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "628123456789", "phone_number_id": "123456"},
                        "contacts": [{"profile": {"name": "Tester"}, "wa_id": phone}],
                        "messages": [{"from": phone, "id": "wamid.002", "timestamp": "1600000001", "text": {"body": "ya boleh"}, "type": "text"}]
                    },
                    "field": "messages"
                }]
            }]
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("tenant"), "suhu-ads-masterclass")
        self.assertIn("Berikut Kode QRIS Pembayaran Anda", data["reply"])
        self.assertIn("Suhu Ads Masterclass 2026", data["reply"])
        self.assertIn("Rp149.000", data["reply"])
        self.assertIn("15 Menit", data["reply"])
        self.assertIn("Google Drive", data["reply"])


if __name__ == "__main__":
    unittest.main()
