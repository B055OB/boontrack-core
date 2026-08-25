import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from app.tenants.career.service import career_service, GLOBAL_USER_STATES
from app.tenants.career.router import verify_webhook, handle_incoming_whatsapp, register_career_routes
from app.routes.whatsapp_career import (
    handle_incoming_whatsapp as legacy_handle_incoming,
    verify_webhook as legacy_verify_webhook
)


class TestCareerModular(AioHTTPTestCase):

    async def get_application(self):
        app = web.Application()
        register_career_routes(app)
        return app

    def setUp(self):
        super().setUp()
        GLOBAL_USER_STATES.clear()

    @unittest_run_loop
    async def test_verify_webhook_success(self):
        resp = await self.client.get(
            "/api/v1/tenants/boontrack-career/webhook/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "boontrack_career_token", "hub.challenge": "123456"}
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.text(), "123456")

    @unittest_run_loop
    async def test_verify_webhook_failure(self):
        resp = await self.client.get(
            "/api/v1/tenants/boontrack-career/webhook/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong_token", "hub.challenge": "123456"}
        )
        self.assertEqual(resp.status, 403)

    @unittest_run_loop
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_handle_incoming_menu_button(self, mock_log, mock_send_buttons):
        mock_send_buttons.return_value = {"status": "success"}

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "interactive",
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {
                                    "id": "btn_menu",
                                    "title": "🏠 Menu Utama"
                                }
                            }
                        }]
                    }
                }]
            }]
        }

        resp = await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status, 200)
        mock_send_buttons.assert_called_once()
        self.assertEqual(mock_send_buttons.call_args[1]["to_phone"], "62899998888")

    @unittest_run_loop
    @patch("app.tenants.career.service.send_whatsapp_text")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_handle_incoming_review_intent(self, mock_log, mock_send_text):
        mock_send_text.return_value = {"status": "success"}

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "text",
                            "text": {"body": "review cv"}
                        }]
                    }
                }]
            }]
        }

        resp = await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status, 200)
        mock_send_text.assert_called_once()
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["mode"], "review")

    def test_legacy_wrapper_exports(self):
        self.assertEqual(handle_incoming_whatsapp, legacy_handle_incoming)
        self.assertEqual(verify_webhook, legacy_verify_webhook)


if __name__ == "__main__":
    unittest.main()
