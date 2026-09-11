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

    @unittest_run_loop
    async def test_aiohttp_media_upload_endpoint(self):
        import io
        from PIL import Image
        from aiohttp import FormData

        buf = io.BytesIO()
        img = Image.new("RGB", (200, 200), (0, 255, 0))
        img.save(buf, format="JPEG")
        buf.seek(0)

        data = FormData()
        data.add_field("file", buf.read(), filename="aiohttp_test.jpg", content_type="image/jpeg")

        resp = await self.client.request(
            "POST",
            "/api/v1/media/upload",
            data=data,
            headers={"Origin": "https://shop.boontrack.com"}
        )
        self.assertEqual(resp.status, 200)
        res_data = await resp.json()
        self.assertEqual(res_data.get("status"), "success")
        self.assertIn("url", res_data)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "https://shop.boontrack.com")

    @unittest_run_loop
    async def test_aiohttp_media_options_cors_shop(self):
        resp = await self.client.request(
            "OPTIONS",
            "/api/v1/upload",
            headers={"Origin": "https://shop.boontrack.com"}
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "https://shop.boontrack.com")

    @unittest_run_loop
    async def test_aiohttp_qris_upload_endpoint(self):
        import io
        from PIL import Image
        from aiohttp import FormData

        buf = io.BytesIO()
        img = Image.new("RGBA", (300, 300), (0, 0, 0, 255))
        img.save(buf, format="PNG")
        buf.seek(0)

        data = FormData()
        data.add_field("qris", buf.read(), filename="toko_qris.png", content_type="image/png")

        resp = await self.client.request(
            "POST",
            "/api/v1/qris/upload",
            data=data,
            headers={"Origin": "https://shop.boontrack.com"}
        )
        self.assertEqual(resp.status, 200)
        res_data = await resp.json()
        self.assertEqual(res_data.get("status"), "success")
        self.assertEqual(res_data.get("folder"), "qris")
        self.assertTrue(res_data.get("is_qris"))
        self.assertTrue(res_data.get("filename").startswith("qris_"))
        self.assertTrue(res_data.get("filename").endswith(".png"))
        self.assertIn("qris_url", res_data)

    @unittest_run_loop
    async def test_aiohttp_product_update_slug_endpoint(self):
        from app.services.onboarding_service import onboarding_service
        onboarding_service._tenants_by_slug["demo-aio"] = {"id": "t-aio-1", "slug": "demo-aio", "name": "Demo AIO"}
        onboarding_service.upsert_tenant_product("demo-aio", {
            "id": "prod-aio-1",
            "title": "Aiohttp Product",
            "price": 99000
        })

        resp = await self.client.request(
            "PUT",
            "/api/v1/products/prod-aio-1",
            json={
                "tenant_slug": "demo-aio",
                "title": "Aiohttp Product Updated",
                "slug": "  Aiohttp NEW Slug 2026!  ",
                "price": 125000
            },
            headers={"Origin": "https://shop.boontrack.com"}
        )
        self.assertEqual(resp.status, 200)
        res_data = await resp.json()
        self.assertEqual(res_data.get("status"), "success")
        self.assertEqual(res_data.get("product", {}).get("slug"), "aiohttp-new-slug-2026")
        self.assertEqual(res_data.get("product", {}).get("price"), 125000)

    @unittest_run_loop
    async def test_aiohttp_custom_domain_endpoints(self):
        # 1. OPTIONS preflight CORS
        resp_options = await self.client.request("OPTIONS", "/api/v1/store/custom-domain")
        self.assertEqual(resp_options.status, 200)
        self.assertEqual(resp_options.headers.get("Access-Control-Allow-Origin"), "*")

        # 2. GET status when not configured
        from unittest.mock import patch
        with patch("app.routes.custom_domain_routes._get_tenant_record_from_db", return_value=({"slug": "onlineboost"}, {})):
            resp = await self.client.request("GET", "/api/v1/store/custom-domain/status?tenant_slug=onlineboost")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data.get("status"), "not_configured")
            self.assertIsNone(data.get("custom_domain"))

if __name__ == "__main__":
    unittest.main()


