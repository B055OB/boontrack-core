"""tests/test_gym_tenant.py
Unit tests for Atmosfitnes Gym Tenant Service and Router (app/tenants/gym/).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web

from app.tenants.gym.config import TENANT_ID, VERIFY_TOKEN, MEMBERSHIP_PACKAGES
from app.tenants.gym.service import gym_service, GymTenantService
from app.tenants.gym.router import register_gym_routes
from app.services.gym_access_service import gym_access_service
from app.schemas.gym_schema import MembershipStatus


class TestGymTenantService(unittest.TestCase):
    """Test conversational bot dispatching for Atmosfitnes Gym."""

    def setUp(self):
        self.service = GymTenantService()
        self.user_phone = "628123456789"
        self.user_name = "Doni Pratama"

    @patch("app.tenants.gym.service.send_whatsapp_text", new_callable=AsyncMock)
    def test_handle_menu_keyword(self, mock_send_wa):
        """User sends 'menu' -> main menu sent."""
        import asyncio
        res = asyncio.run(self.service.handle_user_message("628123456781", "menu", "User Menu"))
        self.assertEqual(res["action"], "MAIN_MENU")
        mock_send_wa.assert_called_once()
        self.assertIn("PUSAT LAYANAN & AKSES ATMOSFITNES", mock_send_wa.call_args[0][1])

    @patch("app.tenants.gym.service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.tenants.gym.service.send_whatsapp_image_link", new_callable=AsyncMock)
    def test_handle_package_order(self, mock_send_img, mock_send_txt):
        """User sends '1' -> generates invoice for Gym Basic."""
        import asyncio
        res = asyncio.run(self.service.handle_user_message("628123456782", "1", "User Basic"))
        self.assertEqual(res["action"], "INVOICE_CREATED")
        self.assertGreater(res["amount"], 150000)
        mock_send_txt.assert_called_once()
        mock_send_img.assert_called_once()
        self.assertIn("INVOICE PEMBAYARAN MEMBERSHIP", mock_send_txt.call_args[0][1])

    @patch("app.tenants.gym.service.send_whatsapp_text", new_callable=AsyncMock)
    def test_handle_status_check(self, mock_send_wa):
        """User sends 'cek status' -> checks membership status."""
        import asyncio
        phone_status = "628123456783"
        now = datetime.now(timezone.utc)
        gym_access_service.register_member_in_memory(
            tenant_id="atmosfitnes",
            name="Doni Pratama",
            phone=phone_status,
            expiry_date=now + timedelta(days=20),
            membership_status=MembershipStatus.ACTIVE,
        )

        res = asyncio.run(self.service.handle_user_message(phone_status, "cek status", "Doni Pratama"))
        self.assertEqual(res["action"], "STATUS_CHECK")
        self.assertTrue(res["is_valid"])
        mock_send_wa.assert_called_once()
        self.assertIn("STATUS MEMBERSHIP ATMOSFITNES", mock_send_wa.call_args[0][1])

    @patch("app.tenants.gym.service.send_whatsapp_text", new_callable=AsyncMock)
    def test_handle_facility_info(self, mock_send_wa):
        """User sends '8' -> sends facility info."""
        import asyncio
        res = asyncio.run(self.service.handle_user_message("628123456784", "8", "User Info"))
        self.assertEqual(res["action"], "FACILITY_INFO")
        mock_send_wa.assert_called_once()
        self.assertIn("INFORMASI FASILITAS", mock_send_wa.call_args[0][1])


class TestGymTenantRouter(AioHTTPTestCase):
    """Test aiohttp webhook router for Atmosfitnes Gym."""

    async def get_application(self):
        app = web.Application()
        register_gym_routes(app)
        return app

    @unittest_run_loop
    async def test_webhook_verify_challenge_success(self):
        """GET /webhook/atmosfitnes/whatsapp with valid token -> 200 challenge."""
        resp = await self.client.get(
            f"/webhook/atmosfitnes/whatsapp?hub.mode=subscribe&hub.verify_token={VERIFY_TOKEN}&hub.challenge=test_123"
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.text(), "test_123")

    @unittest_run_loop
    async def test_webhook_verify_challenge_forbidden(self):
        """GET /webhook/atmosfitnes/whatsapp with wrong token -> 403."""
        resp = await self.client.get(
            "/webhook/atmosfitnes/whatsapp?hub.mode=subscribe&hub.verify_token=wrong_tok&hub.challenge=test_123"
        )
        self.assertEqual(resp.status, 403)


if __name__ == "__main__":
    unittest.main()
