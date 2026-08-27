"""tests/test_gym_e2e_lifecycle.py
End-to-End Definition of Done (DoD) Lifecycle Integration Test Suite for Atmosfitnes (Gym & IoT Access Control).

Scenarios:
- Scenario 1: Active Member -> Tap NFC -> Gate ALLOWED (unlock_gate=True)
- Scenario 2: Expired Member -> Tap NFC -> Gate DENIED (unlock_gate=False, reason=EXPIRED_MEMBERSHIP) -> WA Renewal Notification + Dynamic QRIS Dispatched
- Scenario 3: QRIS Payment Simulation -> Member auto-reactivated to ACTIVE + Expiry extended 30 days -> Tap NFC again -> Gate ALLOWED (unlock_gate=True)
- Scenario 4: Multi-Tenant Data & Access Isolation (Other tenants cannot view or verify Atmosfitnes members/cards)
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.gym_schema import (
    MembershipStatus,
    CardStatus,
    ControllerStatus,
    AccessDecision,
    AccessReason,
)
from app.services.gym_access_service import (
    gym_access_service,
    GymAccessService,
)
from app.payments.matcher import match_and_process_payment
from app.services.reconciliation_service import PAYMENT_INTENTS


class TestGymE2ELifecycle(unittest.TestCase):
    """End-to-End DoD Integration Tests for Gym IoT Access & WhatsApp Renewal Loop."""

    def setUp(self):
        self.client = TestClient(app)
        self.tenant_id = "atmosfitnes"
        self.controller_id = "GATE_E2E_TURNSTILE"
        self.device_token = "esp32_e2e_token_key_123"

        # Register Controller in Global Singleton
        gym_access_service.register_controller_in_memory(
            tenant_id=self.tenant_id,
            controller_id=self.controller_id,
            name="Main Lobby Turnstile",
            raw_device_token=self.device_token,
            status=ControllerStatus.ONLINE,
        )

    @patch("app.services.gym_access_service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.services.gym_access_service.send_whatsapp_image_link", new_callable=AsyncMock)
    def test_scenario_1_active_member_tap_allowed(self, mock_send_img, mock_send_txt):
        """Scenario 1: Active Member -> Tap NFC -> Gate ALLOWED (unlock_gate=True)."""
        now = datetime.now(timezone.utc)
        active_member = gym_access_service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Dimas Pratama",
            phone="628111222333",
            expiry_date=now + timedelta(days=25),
            membership_status=MembershipStatus.ACTIVE,
        )
        card_hash = "uid_hash_active_scenario_1"
        gym_access_service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(active_member.id),
            uid_hash=card_hash,
            status=CardStatus.ACTIVE,
        )

        payload = {
            "tenant_id": self.tenant_id,
            "controller_id": self.controller_id,
            "uid_hash": card_hash,
            "device_token": self.device_token,
        }
        res = self.client.post("/api/v1/gym/access/verify", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["decision"], "ALLOWED")
        self.assertEqual(data["reason"], "VALID")
        self.assertTrue(data["unlock_gate"])
        self.assertEqual(data["member_name"], "Dimas Pratama")
        self.assertEqual(data["membership_status"], "ACTIVE")

    @patch("app.services.gym_access_service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.services.gym_access_service.send_whatsapp_image_link", new_callable=AsyncMock)
    def test_scenario_2_and_3_expired_member_renewal_and_reactivation_lifecycle(
        self, mock_send_img, mock_send_txt
    ):
        """Scenario 2 & 3:
        - Scenario 2: Expired Member -> Tap NFC -> DENIED -> WA Renewal + QRIS sent.
        - Scenario 3: QRIS Payment Simulation -> Member auto-reactivated to ACTIVE -> Re-tap NFC -> ALLOWED.
        """
        import asyncio

        now = datetime.now(timezone.utc)
        expired_date = now - timedelta(days=2)
        expired_member = gym_access_service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Siti Rahayu",
            phone="6281298765432",
            expiry_date=expired_date,
            membership_status=MembershipStatus.EXPIRED,
        )
        card_hash = "uid_hash_expired_scenario_2_3"
        gym_access_service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(expired_member.id),
            uid_hash=card_hash,
            status=CardStatus.ACTIVE,
        )

        # ---------------------------------------------------------------------
        # STEP 1 (Scenario 2): Tap while EXPIRED -> DENIED + WA QRIS sent
        # ---------------------------------------------------------------------
        payload = {
            "tenant_id": self.tenant_id,
            "controller_id": self.controller_id,
            "uid_hash": card_hash,
            "device_token": self.device_token,
        }
        res = self.client.post("/api/v1/gym/access/verify", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["decision"], "DENIED")
        self.assertEqual(data["reason"], "EXPIRED_MEMBERSHIP")
        self.assertFalse(data["unlock_gate"])
        self.assertIn("berakhir", data["message"].lower())

        # Verify WhatsApp Renewal Notification was dispatched
        mock_send_txt.assert_called_once()
        self.assertEqual(mock_send_txt.call_args[0][0], "6281298765432")
        self.assertIn("Siti Rahayu", mock_send_txt.call_args[0][1])
        self.assertIn("QRIS", mock_send_txt.call_args[0][1])

        # Verify Dynamic QRIS Image was dispatched
        mock_send_img.assert_called_once()
        self.assertEqual(mock_send_img.call_args[1]["to"], "6281298765432")
        self.assertIn("quickchart.io", mock_send_img.call_args[1]["image_url"])

        # Check that Whitelist currently DOES NOT include this expired member
        headers = {"X-Device-Token": self.device_token}
        res_wl_before = self.client.get(
            f"/api/v1/gym/controllers/{self.controller_id}/whitelist?tenant_id={self.tenant_id}",
            headers=headers,
        )
        self.assertEqual(res_wl_before.status_code, 200)
        wl_hashes_before = [w["uid_hash"] for w in res_wl_before.json()["whitelist"]]
        self.assertNotIn(card_hash, wl_hashes_before)

        # ---------------------------------------------------------------------
        # STEP 2 (Scenario 3): Simulate Payment Verification via Matcher
        # ---------------------------------------------------------------------
        # Find the generated payment intent amount
        created_intent_amount = None
        for amt, intent in PAYMENT_INTENTS.items():
            if isinstance(amt, int) and intent.get("member_id") == str(expired_member.id):
                created_intent_amount = amt
                break

        self.assertIsNotNone(created_intent_amount, "Payment intent was not created during renewal flow")

        # Simulate DANA webhook incoming payment with exact amount
        dana_notification_payload = {
            "title": "Pembayaran Masuk",
            "body": f"Rp{created_intent_amount:,} diterima DANA dari Siti Rahayu",
            "amount": created_intent_amount,
        }

        match_result = asyncio.run(
            match_and_process_payment(
                amount=created_intent_amount,
                raw_payload=dana_notification_payload,
                tenant_id=self.tenant_id,
            )
        )

        self.assertEqual(match_result["status"], "SUCCESS")
        self.assertEqual(match_result["action"], "GYM_MEMBERSHIP_RENEWED")
        self.assertEqual(match_result["member_id"], str(expired_member.id))

        # Member status in memory is now ACTIVE and expiry date is extended
        self.assertEqual(expired_member.membership_status, MembershipStatus.ACTIVE)
        self.assertGreater(expired_member.expiry_date, now + timedelta(days=28))

        # Check that Whitelist now AUTOMATICALLY includes this reactivated member
        res_wl_after = self.client.get(
            f"/api/v1/gym/controllers/{self.controller_id}/whitelist?tenant_id={self.tenant_id}",
            headers=headers,
        )
        self.assertEqual(res_wl_after.status_code, 200)
        wl_hashes_after = [w["uid_hash"] for w in res_wl_after.json()["whitelist"]]
        self.assertIn(card_hash, wl_hashes_after)

        # ---------------------------------------------------------------------
        # STEP 3: Re-tap NFC Card -> Gate ALLOWED (Instant auto-unlock)
        # ---------------------------------------------------------------------
        res_retap = self.client.post("/api/v1/gym/access/verify", json=payload)
        self.assertEqual(res_retap.status_code, 200)
        data_retap = res_retap.json()

        self.assertEqual(data_retap["decision"], "ALLOWED")
        self.assertEqual(data_retap["reason"], "VALID")
        self.assertTrue(data_retap["unlock_gate"])
        self.assertEqual(data_retap["member_name"], "Siti Rahayu")
        self.assertEqual(data_retap["membership_status"], "ACTIVE")

    def test_scenario_4_tenant_data_and_access_isolation(self):
        """Scenario 4: Tenant Isolation -> Other tenants cannot view or verify Atmosfitnes members/cards."""
        now = datetime.now(timezone.utc)
        atmos_member = gym_access_service.register_member_in_memory(
            tenant_id="atmosfitnes",
            name="Atmos Member Exclusive",
            phone="6281999888777",
            expiry_date=now + timedelta(days=30),
            membership_status=MembershipStatus.ACTIVE,
        )
        atmos_card_hash = "uid_hash_atmos_exclusive_999"
        gym_access_service.register_nfc_card_in_memory(
            tenant_id="atmosfitnes",
            member_id=str(atmos_member.id),
            uid_hash=atmos_card_hash,
            status=CardStatus.ACTIVE,
        )

        # Register controller for competitor tenant
        other_tenant = "other_fitness_club"
        other_controller_id = "GATE_OTHER_01"
        other_token = "other_token_secret"
        gym_access_service.register_controller_in_memory(
            tenant_id=other_tenant,
            controller_id=other_controller_id,
            name="Competitor Gate",
            raw_device_token=other_token,
            status=ControllerStatus.ONLINE,
        )

        # 1. Attempting to tap Atmosfitnes card at other tenant's gate -> DENIED (UNKNOWN_CARD)
        payload_other = {
            "tenant_id": other_tenant,
            "controller_id": other_controller_id,
            "uid_hash": atmos_card_hash,
            "device_token": other_token,
        }
        res_other = self.client.post("/api/v1/gym/access/verify", json=payload_other)
        self.assertEqual(res_other.status_code, 200)
        data_other = res_other.json()
        self.assertEqual(data_other["decision"], "DENIED")
        self.assertEqual(data_other["reason"], "UNKNOWN_CARD")
        self.assertFalse(data_other["unlock_gate"])

        # 2. Whitelist of other tenant DOES NOT leak Atmosfitnes card
        headers_other = {"X-Device-Token": other_token}
        res_wl_other = self.client.get(
            f"/api/v1/gym/controllers/{other_controller_id}/whitelist?tenant_id={other_tenant}",
            headers=headers_other,
        )
        self.assertEqual(res_wl_other.status_code, 200)
        other_wl_hashes = [w["uid_hash"] for w in res_wl_other.json()["whitelist"]]
        self.assertNotIn(atmos_card_hash, other_wl_hashes)


if __name__ == "__main__":
    unittest.main()
