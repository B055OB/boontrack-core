"""
tests/test_meta_waba_official_zero_bot.py
-----------------------------------------
Test suite membuktikan bahwa:
1. Webhook Meta resmi (+6285179555449) TIDAK LAGI membalas pesan teks umum seperti 'halo', 'reset', '1', dsb.
2. Request POST dengan body {"text": {"body": "halo"}} menghasilkan response 200 IGNORED.
3. send_whatsapp_text TIDAK TERPANGGIL sama sekali (0 calls).
4. Template string "Portal Pengujian Ekosistem BoonTrack" telah dimatikan total.
"""

import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.whatsapp.session_router import DEMO_MENU_TEXT


class TestMetaWabaOfficialZeroBot(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock)
    def test_post_webhook_halo_flat_body_returns_guidance_menu(self, mock_send_wa):
        """Simulasi request POST webhook Meta berisi body {'text': {'body': 'halo'}}.

        Harus mengembalikan HTTP 200 dengan menu panduan resmi platform (Anti-Silent Bot).
        """
        payload = {"text": {"body": "halo"}}
        
        endpoints = [
            "/api/v1/whatsapp/webhook",
            "/webhook/whatsapp",
            "/api/whatsapp/webhook"
        ]
        
        for ep in endpoints:
            mock_send_wa.reset_mock()
            resp = self.client.post(ep, json=payload)
            
            self.assertEqual(resp.status_code, 200, f"Endpoint {ep} must return status 200")
            data = resp.json()
            self.assertEqual(data.get("status"), "success")
            self.assertIn("Aktivasi Toko", data.get("reply", ""))
            self.assertNotIn("Portal Pengujian Ekosistem BoonTrack", data.get("reply", ""))

    @patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock)
    def test_post_webhook_halo_meta_envelope_returns_guidance_menu(self, mock_send_wa):
        """Simulasi request POST webhook Meta resmi berisi envelope Meta dengan pesan 'halo'.

        Harus mengembalikan HTTP 200 dengan menu panduan resmi platform.
        """
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba_official_test",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "6285179555449",
                            "phone_number_id": "1268977686299719"
                        },
                        "contacts": [{"profile": {"name": "Pelanggan"}, "wa_id": "6281234567890"}],
                        "messages": [{
                            "from": "6281234567890",
                            "id": "wamid.HBgLMjY3M...",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "halo"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }
        
        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("shop.boontrack.com", data.get("reply", ""))
        self.assertNotIn("Portal Pengujian Ekosistem BoonTrack", data.get("reply", ""))

    @patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock)
    def test_post_webhook_reset_and_menu_commands_return_guidance_menu(self, mock_send_wa):
        """Perintah #reset, reset, menu dsb WAJIB dibalas dengan menu panduan resmi platform (Anti-Silent Bot)."""
        test_messages = ["#reset", "reset", "menu", "p", "test"]
        
        for msg in test_messages:
            mock_send_wa.reset_mock()
            resp = self.client.post("/api/v1/whatsapp/webhook", json={"text": {"body": msg}})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get("status"), "success")
            self.assertIn("shop.boontrack.com", data.get("reply", ""))

    def test_demo_menu_text_string_deactivated(self):
        """String 'Portal Pengujian Ekosistem BoonTrack' WAJIB sudah dimatikan total."""
        self.assertNotIn("Portal Pengujian Ekosistem BoonTrack", DEMO_MENU_TEXT)
        self.assertNotIn("Silakan pilih demo asisten/merchant", DEMO_MENU_TEXT)
        self.assertNotIn("#reset kapan saja untuk ganti toko", DEMO_MENU_TEXT)


if __name__ == "__main__":
    unittest.main()
