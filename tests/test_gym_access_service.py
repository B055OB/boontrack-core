"""tests/test_gym_access_service.py
Unit tests for Gym Access Service, Atmosfitnes Tenant Config, and API Endpoints.

Tests:
1. Atmosfitnes Tenant Configuration loading & schema validity
2. Real-time NFC tap for active member -> ALLOWED (unlock_gate=True)
3. Real-time NFC tap for expired, unmapped, blocked, or suspended member -> DENIED (unlock_gate=False)
4. Controller device token authentication & 401 Unauthorized handling
5. Whitelist retrieval for ESP32 offline caching
6. Offline event batch synchronization & idempotency anti-duplication
7. Controller heartbeat updates
8. FastAPI / HTTP Endpoint integration via TestClient
"""

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.core.tenant_loader import load_tenant_configs
from app.schemas.gym_schema import (
    MembershipStatus,
    CardStatus,
    ControllerStatus,
    AccessEventType,
    AccessDecision,
    AccessReason,
    TapAccessRequest,
    TapAccessResponse,
)
from app.services.gym_access_service import (
    GymAccessService,
    gym_access_service,
    ControllerAuthenticationError,
)


class TestAtmosfitnesTenantConfig(unittest.TestCase):
    """Test Atmosfitnes Tenant JSON Config loading and schema compliance."""

    def test_load_atmosfitnes_config(self):
        """Ensure atmosfitnes.json is loaded and validated properly by tenant_loader."""
        configs = load_tenant_configs()
        self.assertIn("atmosfitnes", configs, "atmosfitnes.json was not loaded by load_tenant_configs")
        cfg = configs["atmosfitnes"]

        self.assertEqual(cfg.identity.tenant_id, "atmosfitnes")
        self.assertEqual(cfg.identity.name, "Atmosfitnes Gym")
        self.assertTrue(cfg.is_active())
        self.assertIn("Atmosfitnes", cfg.persona.welcome_message)
        self.assertEqual(cfg.payment_config.provider, "DANA_DYNAMIC")
        self.assertGreater(len(cfg.menu_config.options), 0)


class TestGymAccessService(unittest.TestCase):
    """Test GymAccessService core business logic in isolation."""

    def setUp(self):
        # Create fresh isolated service instance
        self.service = GymAccessService(in_memory_mode=True)
        self.tenant_id = "atmosfitnes"
        self.controller_id = "GATE_MAIN_01"
        self.raw_token = "secret_esp32_device_token_2026"

        # Register Controller
        self.controller = self.service.register_controller_in_memory(
            tenant_id=self.tenant_id,
            controller_id=self.controller_id,
            name="Main Entrance Turnstile",
            raw_device_token=self.raw_token,
            status=ControllerStatus.ONLINE,
        )

        now = datetime.now(timezone.utc)
        # Register Active Member (Future Expiry)
        self.active_member = self.service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Andi Wijaya",
            phone="6281234567890",
            expiry_date=now + timedelta(days=30),
            membership_status=MembershipStatus.ACTIVE,
        )
        self.active_uid_hash = "hash_card_active_12345678"
        self.service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(self.active_member.id),
            uid_hash=self.active_uid_hash,
            status=CardStatus.ACTIVE,
        )

        # Register Expired Member (Past Expiry)
        self.expired_member = self.service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Budi Expired",
            phone="6281987654321",
            expiry_date=now - timedelta(days=5),
            membership_status=MembershipStatus.EXPIRED,
        )
        self.expired_uid_hash = "hash_card_expired_87654321"
        self.service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(self.expired_member.id),
            uid_hash=self.expired_uid_hash,
            status=CardStatus.ACTIVE,
        )

        # Register Blocked Card
        self.blocked_uid_hash = "hash_card_blocked_11223344"
        self.service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(self.active_member.id),
            uid_hash=self.blocked_uid_hash,
            status=CardStatus.BLOCKED,
        )

        # Register Suspended Member
        self.suspended_member = self.service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Charlie Suspended",
            phone="6281555555555",
            expiry_date=now + timedelta(days=30),
            membership_status=MembershipStatus.SUSPENDED,
        )
        self.suspended_uid_hash = "hash_card_suspended_99887766"
        self.service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(self.suspended_member.id),
            uid_hash=self.suspended_uid_hash,
            status=CardStatus.ACTIVE,
        )

    async def asyncSetUp(self):
        pass

    def test_verify_access_active_member_allowed(self):
        """Active member with valid NFC card -> ALLOWED and unlock_gate=True."""
        import asyncio
        response: TapAccessResponse = asyncio.run(
            self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                uid_hash=self.active_uid_hash,
                device_token=self.raw_token,
            )
        )
        self.assertEqual(response.decision, AccessDecision.ALLOWED)
        self.assertEqual(response.reason, AccessReason.VALID)
        self.assertTrue(response.unlock_gate)
        self.assertEqual(response.member_name, "Andi Wijaya")
        self.assertEqual(response.membership_status, MembershipStatus.ACTIVE)

    def test_verify_access_expired_member_denied(self):
        """Expired member -> DENIED with EXPIRED_MEMBERSHIP and unlock_gate=False."""
        import asyncio
        response: TapAccessResponse = asyncio.run(
            self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                uid_hash=self.expired_uid_hash,
                device_token=self.raw_token,
            )
        )
        self.assertEqual(response.decision, AccessDecision.DENIED)
        self.assertEqual(response.reason, AccessReason.EXPIRED_MEMBERSHIP)
        self.assertFalse(response.unlock_gate)
        self.assertIn("berakhir", response.message.lower())

    def test_verify_access_blocked_card_denied(self):
        """Blocked NFC card -> DENIED with CARD_BLOCKED."""
        import asyncio
        response: TapAccessResponse = asyncio.run(
            self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                uid_hash=self.blocked_uid_hash,
                device_token=self.raw_token,
            )
        )
        self.assertEqual(response.decision, AccessDecision.DENIED)
        self.assertEqual(response.reason, AccessReason.CARD_BLOCKED)
        self.assertFalse(response.unlock_gate)

    def test_verify_access_unmapped_card_denied(self):
        """Unregistered / unknown NFC card -> DENIED with UNKNOWN_CARD."""
        import asyncio
        response: TapAccessResponse = asyncio.run(
            self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                uid_hash="completely_unknown_hash_9999",
                device_token=self.raw_token,
            )
        )
        self.assertEqual(response.decision, AccessDecision.DENIED)
        self.assertEqual(response.reason, AccessReason.UNKNOWN_CARD)
        self.assertFalse(response.unlock_gate)

    def test_verify_access_suspended_member_denied(self):
        """Suspended member -> DENIED with MEMBER_SUSPENDED."""
        import asyncio
        response: TapAccessResponse = asyncio.run(
            self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                uid_hash=self.suspended_uid_hash,
                device_token=self.raw_token,
            )
        )
        self.assertEqual(response.decision, AccessDecision.DENIED)
        self.assertEqual(response.reason, AccessReason.MEMBER_SUSPENDED)
        self.assertFalse(response.unlock_gate)

    def test_verify_access_controller_auth_failure(self):
        """Invalid controller token -> raises ControllerAuthenticationError."""
        import asyncio
        with self.assertRaises(ControllerAuthenticationError):
            asyncio.run(
                self.service.verify_access(
                    tenant_id=self.tenant_id,
                    controller_id=self.controller_id,
                    uid_hash=self.active_uid_hash,
                    device_token="wrong_password_token",
                )
            )

    def test_get_active_whitelist(self):
        """Whitelist only includes active cards of active non-expired members."""
        import asyncio
        whitelist = asyncio.run(
            self.service.get_active_whitelist(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                device_token=self.raw_token,
            )
        )
        # Should include active_member only (not expired, blocked, or suspended)
        uid_list = [w["uid_hash"] for w in whitelist]
        self.assertIn(self.active_uid_hash, uid_list)
        self.assertNotIn(self.expired_uid_hash, uid_list)
        self.assertNotIn(self.blocked_uid_hash, uid_list)
        self.assertNotIn(self.suspended_uid_hash, uid_list)

    def test_sync_offline_events_and_idempotency(self):
        """Batch offline event sync inserts new events and skips duplicates."""
        import asyncio
        events_payload = [
            {
                "member_id": str(self.active_member.id),
                "card_id": str(uuid4()),
                "event_type": "TAP_IN",
                "decision": "ALLOWED",
                "reason": "VALID",
                "idempotency_key": "offline_event_key_001",
            },
            {
                "member_id": str(self.active_member.id),
                "card_id": str(uuid4()),
                "event_type": "TAP_OUT",
                "decision": "ALLOWED",
                "reason": "VALID",
                "idempotency_key": "offline_event_key_002",
            },
        ]

        # First sync -> 2 synced, 0 duplicates
        result1 = asyncio.run(
            self.service.sync_offline_events(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                events_list=events_payload,
                device_token=self.raw_token,
            )
        )
        self.assertEqual(result1["synced_count"], 2)
        self.assertEqual(result1["duplicate_count"], 0)

        # Second sync with same payload -> 0 synced, 2 duplicates skipped
        result2 = asyncio.run(
            self.service.sync_offline_events(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                events_list=events_payload,
                device_token=self.raw_token,
            )
        )
        self.assertEqual(result2["synced_count"], 0)
        self.assertEqual(result2["duplicate_count"], 2)

    def test_record_heartbeat(self):
        """Heartbeat updates last_seen_at and acknowledges online status."""
        import asyncio
        res = asyncio.run(
            self.service.record_heartbeat(
                tenant_id=self.tenant_id,
                controller_id=self.controller_id,
                device_token=self.raw_token,
                firmware_version="v2.4.1-esp32",
            )
        )
        self.assertEqual(res["status"], "ONLINE")
        self.assertTrue(res["acknowledged"])


class TestGymAccessAPIEndpoints(unittest.TestCase):
    """Test FastAPI Endpoints via TestClient."""

    def setUp(self):
        self.client = TestClient(app)
        self.tenant_id = "atmosfitnes"
        self.controller_id = "GATE_TEST_CLIENT"
        self.device_token = "valid_client_device_token"

        # Register in global singleton service
        gym_access_service.register_controller_in_memory(
            tenant_id=self.tenant_id,
            controller_id=self.controller_id,
            name="Turnstile Test Client",
            raw_device_token=self.device_token,
        )

        now = datetime.now(timezone.utc)
        self.member = gym_access_service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Rian Pratama",
            phone="6281122334455",
            expiry_date=now + timedelta(days=60),
            membership_status=MembershipStatus.ACTIVE,
        )
        self.card_hash = "hash_endpoint_test_active_card"
        gym_access_service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(self.member.id),
            uid_hash=self.card_hash,
            status=CardStatus.ACTIVE,
        )

    def test_http_verify_access_allowed(self):
        """POST /api/v1/gym/access/verify with valid active card -> 200 OK ALLOWED."""
        payload = {
            "tenant_id": self.tenant_id,
            "controller_id": self.controller_id,
            "uid_hash": self.card_hash,
            "device_token": self.device_token,
        }
        res = self.client.post("/api/v1/gym/access/verify", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["decision"], "ALLOWED")
        self.assertEqual(data["reason"], "VALID")
        self.assertTrue(data["unlock_gate"])
        self.assertEqual(data["member_name"], "Rian Pratama")

    def test_http_verify_access_unauthorized_controller(self):
        """POST /api/v1/gym/access/verify with wrong token -> 401 Unauthorized."""
        payload = {
            "tenant_id": self.tenant_id,
            "controller_id": self.controller_id,
            "uid_hash": self.card_hash,
            "device_token": "wrong_token_123",
        }
        res = self.client.post("/api/v1/gym/access/verify", json=payload)
        self.assertEqual(res.status_code, 401)
        self.assertIn("Unauthorized", res.json()["detail"])

    def test_http_get_whitelist(self):
        """GET /api/v1/gym/controllers/{controller_id}/whitelist -> 200 OK with list."""
        headers = {"X-Device-Token": self.device_token}
        res = self.client.get(
            f"/api/v1/gym/controllers/{self.controller_id}/whitelist?tenant_id={self.tenant_id}",
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIsInstance(data["whitelist"], list)
        self.assertGreater(data["count"], 0)

    def test_http_sync_offline_events(self):
        """POST /api/v1/gym/access/sync-events -> 200 OK."""
        headers = {"X-Device-Token": self.device_token}
        payload = {
            "tenant_id": self.tenant_id,
            "controller_id": self.controller_id,
            "events": [
                {
                    "event_type": "TAP_IN",
                    "decision": "ALLOWED",
                    "idempotency_key": "http_sync_test_key_001",
                }
            ],
        }
        res = self.client.post("/api/v1/gym/access/sync-events", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["synced_count"], 1)

    def test_http_heartbeat(self):
        """POST /api/v1/gym/controllers/{controller_id}/heartbeat -> 200 OK ONLINE."""
        headers = {"X-Device-Token": self.device_token}
        res = self.client.post(
            f"/api/v1/gym/controllers/{self.controller_id}/heartbeat",
            json={"tenant_id": self.tenant_id, "firmware_version": "v1.0.0"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ONLINE")
        self.assertTrue(data["acknowledged"])


if __name__ == "__main__":
    unittest.main()
