import asyncio
import os
import sys
import unittest
from unittest.mock import patch, AsyncMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.routes.whatsapp_gateway_routes import (
    process_evolution_webhook_payload,
    register_whatsapp_gateway_routes,
)

class TestEvolutionWebhookIntegration(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_whatsapp_gateway_routes(app)
        return app

    def test_routes_registered(self):
        registered_paths = [r.get_info().get("path") or r.get_info().get("formatter") for r in self.app.router.routes()]
        print("Registered routes in aiohttp:", registered_paths)
        self.assertIn("/api/v1/whatsapp/webhook/evolution/{tenant_slug}", registered_paths)
        self.assertIn("/api/v1/whatsapp/webhook/evolution", registered_paths)
        self.assertIn("/api/v1/whatsapp/evolution/webhook", registered_paths)
        self.assertIn("/api/v1/whatsapp/inbound-process", registered_paths)

    @unittest_run_loop
    async def test_self_message_filtered(self):
        payload = {
            "event": "messages.upsert",
            "instance": "tenant_kurastorenkrw",
            "data": {
                "key": {
                    "remoteJid": "628123456789@s.whatsapp.net",
                    "fromMe": True
                },
                "message": {
                    "conversation": "Pesan dari bot sendiri"
                }
            }
        }
        res = await process_evolution_webhook_payload(payload)
        self.assertEqual(res.get("status"), "ignored_from_me")

    @unittest_run_loop
    async def test_group_message_filtered(self):
        payload = {
            "event": "messages.upsert",
            "instance": "tenant_kurastorenkrw",
            "data": {
                "key": {
                    "remoteJid": "1203630248292839@g.us",
                    "fromMe": False
                },
                "message": {
                    "conversation": "Pesan di grup"
                }
            }
        }
        res = await process_evolution_webhook_payload(payload)
        self.assertEqual(res.get("status"), "ignored_non_personal")

    @unittest_run_loop
    async def test_broadcast_message_filtered(self):
        payload = {
            "event": "messages.upsert",
            "instance": "tenant_kurastorenkrw",
            "data": {
                "key": {
                    "remoteJid": "status@broadcast",
                    "fromMe": False
                },
                "message": {
                    "conversation": "Status update"
                }
            }
        }
        res = await process_evolution_webhook_payload(payload)
        self.assertEqual(res.get("status"), "ignored_non_personal")

    @unittest_run_loop
    async def test_valid_inbound_customer_message(self):
        payload = {
            "event": "messages.upsert",
            "instance": "tenant_kurastorenkrw",
            "data": {
                "key": {
                    "remoteJid": "628123456789@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG123456"
                },
                "pushName": "Budi Hartono",
                "message": {
                    "conversation": "Halo admin, berapa biaya jasa cuci toren?"
                }
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = '{"success": true}'

            # Test direct POST to aiohttp route
            resp = await self.client.post(
                "/api/v1/whatsapp/webhook/evolution/kurastorenkrw",
                json=payload
            )
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            print("Webhook response:", data)
            self.assertEqual(data.get("status"), "success")
            self.assertEqual(data.get("tenant"), "kurastorenkrw")
            self.assertTrue(bool(data.get("reply")))

            # Verify sendText was called on Evolution API
            self.assertTrue(mock_post.called)
            call_url = mock_post.call_args[0][0]
            call_json = mock_post.call_args[1]["json"]
            print("Dispatched to Evolution URL:", call_url)
            print("Dispatched Payload:", call_json)
            self.assertIn("tenant_kurastorenkrw", call_url)
            self.assertEqual(call_json["number"], "628123456789")
            self.assertIn("text", call_json)
            self.assertEqual(call_json["text"], data.get("reply"))

if __name__ == "__main__":
    unittest.main()
