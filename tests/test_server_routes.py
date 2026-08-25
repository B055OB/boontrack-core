import unittest
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web
from app.core.server import create_web_app

class TestModularServerRoutes(AioHTTPTestCase):

    async def get_application(self):
        # Create modular aiohttp web app
        return create_web_app()

    @unittest_run_loop
    async def test_health_endpoint(self):
        resp = await self.client.request("GET", "/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "healthy")

    @unittest_run_loop
    async def test_root_endpoint(self):
        resp = await self.client.request("GET", "/")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "healthy")

    @unittest_run_loop
    async def test_source_tracker_redirect(self):
        resp = await self.client.request("GET", "/source?utm_source=test", allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertTrue(resp.headers.get("Location", "").startswith("https://t.me/boontrackbot"))

    @unittest_run_loop
    async def test_webchat_options_cors(self):
        resp = await self.client.request("OPTIONS", "/api/webchat")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")

    @unittest_run_loop
    async def test_webchat_validation_empty_message(self):
        resp = await self.client.request("POST", "/api/webchat", json={"session_id": "test_session", "message": ""})
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertEqual(data.get("status"), "error")

    @unittest_run_loop
    async def test_om_budi_webhook_verification(self):
        # GET with valid token
        resp = await self.client.request(
            "GET",
            "/webhook/om_budi/whatsapp?hub.mode=subscribe&hub.verify_token=om_budi_secure_token_2026&hub.challenge=CHALLENGE_ACCEPTED"
        )
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertEqual(text, "CHALLENGE_ACCEPTED")

        # GET with invalid token
        resp_invalid = await self.client.request(
            "GET",
            "/webhook/om_budi/whatsapp?hub.mode=subscribe&hub.verify_token=wrong_token"
        )
        self.assertEqual(resp_invalid.status, 403)

    @unittest_run_loop
    async def test_dana_webhook_not_dana(self):
        resp = await self.client.request(
            "POST",
            "/webhook/dana",
            json={"source": "random_app", "message": "hello world"}
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "ignored")

if __name__ == "__main__":
    unittest.main()
