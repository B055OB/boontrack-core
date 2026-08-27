"""tests/test_gym_conversational_e2e.py
Comprehensive E2E & Unit Test Suite for:
1. WhatsApp Conversational Flow (5-Tier Packages, Dynamic QRIS, Member Registration)
2. Zumba & Studio Class Booking Engine (Capacity Validation & Overbooking Prevention)
3. Admin Dashboard Endpoints (Members, NFC Pairing, Access Logs, Controller Status)
4. Turnstile Gate Check-In & Auto-Renewal Notification Loop
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.tenants.gym.service import gym_service
from app.services.gym_access_service import gym_access_service
from app.schemas.gym_schema import ControllerStatus, MembershipStatus, CardStatus
from app.payments.matcher import match_and_process_payment
from app.services.reconciliation_service import PAYMENT_INTENTS


class TestGymConversationalAndAdminE2E(unittest.TestCase):
    """E2E Test Suite for Gym Conversational Bot, Class Booking, and Admin Dashboard."""

    def setUp(self):
        self.client = TestClient(app)
        self.tenant_id = "atmosfitnes"
        self.controller_id = "GATE_MAIN_01"
        self.device_token = "esp32_token_test_conv"

        gym_access_service.register_controller_in_memory(
            tenant_id=self.tenant_id,
            controller_id=self.controller_id,
            name="Main Lobby Turnstile",
            raw_device_token=self.device_token,
            status=ControllerStatus.ONLINE,
        )

    # =========================================================================
    # 1. WhatsApp Conversational & Package Purchasing Flow
    # =========================================================================

    @patch("app.tenants.gym.service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.tenants.gym.service.send_whatsapp_image_link", new_callable=AsyncMock)
    def test_whatsapp_conversation_package_order(self, mock_send_img, mock_send_txt):
        """User chats 'daftar member' -> gets catalog -> chooses 4 (All Access) -> gets Dynamic QRIS."""
        import asyncio

        user_phone = "628123450001"
        user_name = "Andi Wijaya"

        # 1. Chat 'daftar member'
        res_cat = asyncio.run(gym_service.handle_user_message(user_phone, "daftar member", user_name))
        self.assertEqual(res_cat["action"], "PACKAGES_CATALOG")
        mock_send_txt.assert_called()
        self.assertIn("KATALOG PAKET MEMBERSHIP", mock_send_txt.call_args[0][1])

        # 2. Select Option 4: All Access (Rp350.000)
        res_order = asyncio.run(gym_service.handle_user_message(user_phone, "4", user_name))
        self.assertEqual(res_order["action"], "INVOICE_CREATED")
        self.assertGreater(res_order["amount"], 350000)
        self.assertIn("GYM-ORD-", res_order["invoice_id"])

        mock_send_img.assert_called_once()
        self.assertEqual(mock_send_img.call_args[1]["to"], user_phone)
        self.assertIn("quickchart.io", mock_send_img.call_args[1]["image_url"])

    # =========================================================================
    # 2. Zumba Class Booking & Capacity Validation
    # =========================================================================

    @patch("app.tenants.gym.service.send_whatsapp_text", new_callable=AsyncMock)
    def test_zumba_booking_capacity_validation(self, mock_send_txt):
        """Tests Zumba class schedule retrieval and capacity limit validation."""
        import asyncio

        user_phone = "628123450002"
        user_name = "Dewi Lestari"

        # 1. Request Class Schedule
        res_sched = asyncio.run(gym_service.handle_user_message(user_phone, "booking zumba", user_name))
        self.assertEqual(res_sched["action"], "CLASS_SCHEDULE")
        self.assertGreaterEqual(res_sched["sessions_count"], 1)

        # 2. Successful Booking on available session (zumba_evening has free slots)
        res_book_ok = asyncio.run(gym_service.handle_user_message(user_phone, "book zumba_evening", user_name))
        self.assertEqual(res_book_ok["action"], "BOOKING_SUCCESS")
        self.assertEqual(res_book_ok["result"]["status"], "CONFIRMED")
        self.assertIn("BOOKING KELAS BERHASIL", mock_send_txt.call_args[0][1])

        # 3. Failed Booking on full session (yoga_weekend is seeded at 10/10)
        res_book_full = asyncio.run(gym_service.handle_user_message(user_phone, "book yoga_weekend", user_name))
        self.assertEqual(res_book_full["action"], "BOOKING_FULL")
        self.assertEqual(res_book_full["result"]["status"], "FULL")
        self.assertIn("KUOTA PENUH", mock_send_txt.call_args[0][1])

    # =========================================================================
    # 3. Admin Dashboard REST Endpoints
    # =========================================================================

    @patch("app.services.gym_access_service.send_whatsapp_text", new_callable=AsyncMock)
    def test_admin_dashboard_endpoints(self, mock_checkin_wa):
        """Tests Admin Dashboard API: list members, pair card, access logs, controllers."""
        now = datetime.now(timezone.utc)

        # 1. Seed Member
        m = gym_access_service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Admin Test Member",
            phone="628199990001",
            expiry_date=now + timedelta(days=30),
            membership_package="GYM_PREMIUM",
            membership_status=MembershipStatus.ACTIVE,
        )

        # 2. GET /api/v1/gym/admin/members
        res_members = self.client.get(f"/api/v1/gym/admin/members?tenant_id={self.tenant_id}")
        self.assertEqual(res_members.status_code, 200)
        members_data = res_members.json()["data"]
        self.assertGreaterEqual(members_data["total"], 1)
        found_m = next((item for item in members_data["members"] if item["id"] == str(m.id)), None)
        self.assertIsNotNone(found_m)
        self.assertFalse(found_m["is_paired"])

        # 3. POST /api/v1/gym/admin/members/{member_id}/pair-card
        pair_payload = {
            "tenant_id": self.tenant_id,
            "uid_hash": "NFC-ADMIN-PAIR-1234",
        }
        res_pair = self.client.post(f"/api/v1/gym/admin/members/{str(m.id)}/pair-card", json=pair_payload)
        self.assertEqual(res_pair.status_code, 200)
        pair_data = res_pair.json()["data"]
        self.assertEqual(pair_data["status"], "PAIRED")
        self.assertEqual(pair_data["uid_hash"], "nfc-admin-pair-1234")

        # Verify member now shows is_paired=True
        res_members_after = self.client.get(f"/api/v1/gym/admin/members?tenant_id={self.tenant_id}")
        found_m_after = next((item for item in res_members_after.json()["data"]["members"] if item["id"] == str(m.id)), None)
        self.assertTrue(found_m_after["is_paired"])
        self.assertEqual(found_m_after["paired_card_hash"], "nfc-admin-pair-1234")

        # 4. Tap in at gate and verify log in GET /api/v1/gym/admin/access-logs
        tap_payload = {
            "tenant_id": self.tenant_id,
            "controller_id": self.controller_id,
            "uid_hash": "nfc-admin-pair-1234",
            "device_token": self.device_token,
        }
        res_tap = self.client.post("/api/v1/gym/access/verify", json=tap_payload)
        self.assertEqual(res_tap.status_code, 200)
        self.assertEqual(res_tap.json()["decision"], "ALLOWED")

        res_logs = self.client.get(f"/api/v1/gym/admin/access-logs?tenant_id={self.tenant_id}&limit=10")
        self.assertEqual(res_logs.status_code, 200)
        logs_data = res_logs.json()["data"]
        self.assertGreaterEqual(logs_data["total"], 1)
        self.assertEqual(logs_data["logs"][0]["decision"], "ALLOWED")

        # 5. GET /api/v1/gym/admin/controllers
        res_ctrls = self.client.get(f"/api/v1/gym/admin/controllers?tenant_id={self.tenant_id}")
        self.assertEqual(res_ctrls.status_code, 200)
        ctrls_data = res_ctrls.json()["data"]
        self.assertGreaterEqual(ctrls_data["total"], 1)
        lobby_ctrl = next((c for c in ctrls_data["controllers"] if c["controller_id"] == self.controller_id), None)
        self.assertIsNotNone(lobby_ctrl)
        self.assertTrue(lobby_ctrl["is_online"])


if __name__ == "__main__":
    unittest.main()
