"""tests/adversarial/test_gym_resilience.py
Edge Resilience & Adversarial Test Suite for Gym & IoT Access Control.

Failure & Edge Scenarios:
1. Duplicate & Rapid Tap (<500ms): First tap ALLOWED, second tap throttled/denied cooldown.
2. Concurrent Controllers: Multiple gates verifying concurrently for the same tenant.
3. Offline Sync & Idempotency: Batch of 20 offline logs sent 2x, exact 20 events recorded (anti-duplikasi).
4. Cache Invalidation: Member ACTIVE changed to EXPIRED in DB -> subsequent tap & whitelist sync immediately reject.
5. Security & Sanitization: Invalid controller tokens return 401/403, and malformed card UIDs are safely handled as UNKNOWN_CARD without 500 errors.
"""

import asyncio
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


class TestGymEdgeResilienceAndAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial and Edge Resilience Test Suite for IoT Turnstiles."""

    def setUp(self):
        self.tenant_id = "atmosfitnes"
        self.raw_token_gate1 = "esp32_secret_token_gate_west_2026"
        self.raw_token_gate2 = "esp32_secret_token_gate_east_2026"
        self.controller_gate1 = "GATE_WEST_01"
        self.controller_gate2 = "GATE_EAST_02"

        # Initialize fresh isolated service with 500ms cooldown in in_memory_mode
        self.service = GymAccessService(in_memory_mode=True, cooldown_ms=500)

        # Register Gate 1 (West Turnstile)
        self.service.register_controller_in_memory(
            tenant_id=self.tenant_id,
            controller_id=self.controller_gate1,
            name="West Turnstile Gate",
            raw_device_token=self.raw_token_gate1,
            status=ControllerStatus.ONLINE,
        )

        # Register Gate 2 (East Turnstile)
        self.service.register_controller_in_memory(
            tenant_id=self.tenant_id,
            controller_id=self.controller_gate2,
            name="East Turnstile Gate",
            raw_device_token=self.raw_token_gate2,
            status=ControllerStatus.ONLINE,
        )

        # Setup Active Member & NFC Card
        now = datetime.now(timezone.utc)
        self.active_member = self.service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Budi Pratama",
            phone="6281234567890",
            expiry_date=now + timedelta(days=30),
            membership_status=MembershipStatus.ACTIVE,
        )

        self.valid_card_hash = "nfc_hash_budi_active_card_12345"
        self.service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(self.active_member.id),
            uid_hash=self.valid_card_hash,
            status=CardStatus.ACTIVE,
        )

        # Configure global singleton for HTTP integration tests
        gym_access_service.in_memory_mode = True
        gym_access_service.cooldown_ms = 500
        gym_access_service.invalidate_all_caches(self.tenant_id)
        gym_access_service.register_controller_in_memory(
            tenant_id=self.tenant_id,
            controller_id=self.controller_gate1,
            name="West Turnstile Gate",
            raw_device_token=self.raw_token_gate1,
            status=ControllerStatus.ONLINE,
        )
        gym_access_service.register_member_in_memory(
            tenant_id=self.tenant_id,
            name="Budi Pratama",
            phone="6281234567890",
            expiry_date=now + timedelta(days=30),
            membership_status=MembershipStatus.ACTIVE,
            member_id=str(self.active_member.id),
        )
        gym_access_service.register_nfc_card_in_memory(
            tenant_id=self.tenant_id,
            member_id=str(self.active_member.id),
            uid_hash=self.valid_card_hash,
            status=CardStatus.ACTIVE,
        )

        # HTTP TestClient
        self.client = TestClient(app)

    # =========================================================================
    # Skenario 1: Duplicate & Rapid Tap (<500ms)
    # =========================================================================

    async def test_rapid_tap_under_500ms_cooldown_throttling(self):
        """Memvalidasi tap pertama ALLOWED, dan tap kedua (<500ms) di-throttle/denied cooldown."""
        with patch("app.services.gym_access_service.send_whatsapp_text", new_callable=AsyncMock):
            # 1. Tap Pertama -> ALLOWED
            res1 = await self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                uid_hash=self.valid_card_hash,
                device_token=self.raw_token_gate1,
                event_type=AccessEventType.TAP_IN,
            )
            self.assertEqual(res1.decision, AccessDecision.ALLOWED)
            self.assertEqual(res1.reason, AccessReason.VALID)
            self.assertTrue(res1.unlock_gate)

            # 2. Tap Kedua langsung (< 500ms) -> DENIED dengan COOLDOWN_ACTIVE
            res2 = await self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                uid_hash=self.valid_card_hash,
                device_token=self.raw_token_gate1,
                event_type=AccessEventType.TAP_IN,
            )
            self.assertEqual(res2.decision, AccessDecision.DENIED)
            self.assertEqual(res2.reason, AccessReason.COOLDOWN_ACTIVE)
            self.assertFalse(res2.unlock_gate)
            self.assertIn("Cooldown", res2.message)

            # 3. Tunggu hingga lewat batas cooldown (> 500ms)
            await asyncio.sleep(0.55)

            # 4. Tap Ketiga setelah cooldown lewat -> ALLOWED kembali
            res3 = await self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                uid_hash=self.valid_card_hash,
                device_token=self.raw_token_gate1,
                event_type=AccessEventType.TAP_IN,
            )
            self.assertEqual(res3.decision, AccessDecision.ALLOWED)
            self.assertEqual(res3.reason, AccessReason.VALID)
            self.assertTrue(res3.unlock_gate)

    def test_rapid_tap_via_http_endpoint(self):
        """Memvalidasi throttling rapid tap lewat endpoint HTTP FastAPI."""
        with patch("app.services.gym_access_service.send_whatsapp_text", new_callable=AsyncMock):
            payload = {
                "tenant_id": self.tenant_id,
                "controller_id": self.controller_gate1,
                "uid_hash": self.valid_card_hash,
                "event_type": "TAP_IN",
                "device_token": self.raw_token_gate1,
            }

            # Tap 1 -> HTTP 200 ALLOWED
            resp1 = self.client.post(
                "/api/v1/gym/access/verify",
                json=payload,
                headers={"X-Device-Token": self.raw_token_gate1},
            )
            self.assertEqual(resp1.status_code, 200)
            data1 = resp1.json()
            self.assertEqual(data1["decision"], "ALLOWED")
            self.assertTrue(data1["unlock_gate"])

            # Immediate Tap 2 (<500ms) -> HTTP 200 DENIED Cooldown
            resp2 = self.client.post(
                "/api/v1/gym/access/verify",
                json=payload,
                headers={"X-Device-Token": self.raw_token_gate1},
            )
            self.assertEqual(resp2.status_code, 200)
            data2 = resp2.json()
            self.assertEqual(data2["decision"], "DENIED")
            self.assertEqual(data2["reason"], "COOLDOWN_ACTIVE")
            self.assertFalse(data2["unlock_gate"])

    # =========================================================================
    # Skenario 2: Concurrent Controllers
    # =========================================================================

    async def test_concurrent_verification_across_multiple_controllers(self):
        """Memvalidasi dua gerbang berbeda memverifikasi kartu secara bersamaan pada 1 tenant."""
        with patch("app.services.gym_access_service.send_whatsapp_text", new_callable=AsyncMock):
            now = datetime.now(timezone.utc)

            # Setup Member 2 & Card 2
            member_2 = self.service.register_member_in_memory(
                tenant_id=self.tenant_id,
                name="Siti Rahma",
                phone="6281987654321",
                expiry_date=now + timedelta(days=60),
                membership_status=MembershipStatus.ACTIVE,
            )
            card_2_hash = "nfc_hash_siti_active_card_67890"
            self.service.register_nfc_card_in_memory(
                tenant_id=self.tenant_id,
                member_id=str(member_2.id),
                uid_hash=card_2_hash,
                status=CardStatus.ACTIVE,
            )

            # Dispatch verifikasi secara paralel / concurrent via asyncio.gather
            task_gate1 = self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                uid_hash=self.valid_card_hash,
                device_token=self.raw_token_gate1,
                event_type=AccessEventType.TAP_IN,
            )

            task_gate2 = self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate2,
                uid_hash=card_2_hash,
                device_token=self.raw_token_gate2,
                event_type=AccessEventType.TAP_IN,
            )

            res_gate1, res_gate2 = await asyncio.gather(task_gate1, task_gate2)

            # Kedua gate harus sukses tanpa deadlock atau interferensi data
            self.assertEqual(res_gate1.decision, AccessDecision.ALLOWED)
            self.assertTrue(res_gate1.unlock_gate)
            self.assertEqual(res_gate1.member_name, "Budi Pratama")

            self.assertEqual(res_gate2.decision, AccessDecision.ALLOWED)
            self.assertTrue(res_gate2.unlock_gate)
            self.assertEqual(res_gate2.member_name, "Siti Rahma")

            # Pastikan audit logs mencatat kedua controller ID dengan tepat
            events = list(self.service._events.get(self.tenant_id, {}).values())
            logged_controllers = {e.controller_id for e in events}
            self.assertIn(self.controller_gate1, logged_controllers)
            self.assertIn(self.controller_gate2, logged_controllers)

    # =========================================================================
    # Skenario 3: Offline Sync & Idempotency
    # =========================================================================

    async def test_offline_sync_idempotency_anti_duplication(self):
        """Batch 20 offline logs dikirim 2x, pastikan tepat mencatat 20 event tanpa duplikasi."""
        now = datetime.now(timezone.utc)

        # Buat batch 20 event offline dengan idempotency_key unik
        batch_events = []
        for i in range(1, 21):
            batch_events.append({
                "idempotency_key": f"offline_event_turnstile_{i:03d}",
                "member_id": str(self.active_member.id),
                "card_id": f"card_offline_{i:03d}",
                "event_type": AccessEventType.TAP_IN,
                "decision": AccessDecision.ALLOWED,
                "reason": AccessReason.VALID,
                "created_at": now - timedelta(minutes=(20 - i)),
            })

        self.assertEqual(len(batch_events), 20)

        # 1. Kirim Batch Pertama
        sync_result_1 = await self.service.sync_offline_events(
            tenant_id=self.tenant_id,
            controller_id=self.controller_gate1,
            events_list=batch_events,
            device_token=self.raw_token_gate1,
        )

        self.assertEqual(sync_result_1["status"], "success")
        self.assertEqual(sync_result_1["synced_count"], 20)
        self.assertEqual(sync_result_1["duplicate_count"], 0)
        self.assertEqual(sync_result_1["total_received"], 20)

        # 2. Kirim Batch yang Sama Persis untuk Kedua Kalinya (Replay / Network Duplicate)
        sync_result_2 = await self.service.sync_offline_events(
            tenant_id=self.tenant_id,
            controller_id=self.controller_gate1,
            events_list=batch_events,
            device_token=self.raw_token_gate1,
        )

        self.assertEqual(sync_result_2["status"], "success")
        self.assertEqual(sync_result_2["synced_count"], 0)
        self.assertEqual(sync_result_2["duplicate_count"], 20)
        self.assertEqual(sync_result_2["total_received"], 20)

        # 3. Verifikasi jumlah total event tersimpan tepat 20
        stored_events = self.service._events.get(self.tenant_id, {})
        offline_event_keys = [k for k in stored_events if k.startswith("offline_event_turnstile_")]
        self.assertEqual(len(offline_event_keys), 20)

    # =========================================================================
    # Skenario 4: Cache Invalidation
    # =========================================================================

    async def test_cache_invalidation_reflects_expired_status(self):
        """Member ACTIVE diubah EXPIRED di DB -> Verifikasi tap & whitelist sync berikutnya langsung menolak."""
        with patch("app.services.gym_access_service.send_whatsapp_text", new_callable=AsyncMock), \
             patch("app.services.gym_access_service.send_whatsapp_image_link", new_callable=AsyncMock):
            # 1. Pastikan kondisi awal: Member ACTIVE -> Tap ALLOWED
            res_initial = await self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                uid_hash=self.valid_card_hash,
                device_token=self.raw_token_gate1,
                event_type=AccessEventType.TAP_IN,
            )
            self.assertEqual(res_initial.decision, AccessDecision.ALLOWED)

            # Whitelist awal menyertakan kartu
            whitelist_initial = await self.service.get_active_whitelist(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                device_token=self.raw_token_gate1,
            )
            whitelist_card_hashes = [item["uid_hash"] for item in whitelist_initial]
            self.assertIn(self.valid_card_hash, whitelist_card_hashes)

            # 2. Simulasi update status di DB: Member diubah menjadi EXPIRED
            now = datetime.now(timezone.utc)
            self.service.update_member_status(
                tenant_id=self.tenant_id,
                member_id=str(self.active_member.id),
                status=MembershipStatus.EXPIRED,
                expiry_date=now - timedelta(days=1),
            )

            # Reset cooldown agar tidak tertahan oleh rate limit tap sebelumnya
            self.service._last_tap_timestamps.clear()

            # 3. Verifikasi tap berikutnya -> Langsung DENIED (EXPIRED_MEMBERSHIP)
            res_expired = await self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                uid_hash=self.valid_card_hash,
                device_token=self.raw_token_gate1,
                event_type=AccessEventType.TAP_IN,
            )
            self.assertEqual(res_expired.decision, AccessDecision.DENIED)
            self.assertEqual(res_expired.reason, AccessReason.EXPIRED_MEMBERSHIP)
            self.assertFalse(res_expired.unlock_gate)

            # 4. Whitelist sync berikutnya langsung menolak / tidak menyertakan kartu
            whitelist_updated = await self.service.get_active_whitelist(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                device_token=self.raw_token_gate1,
            )
            updated_hashes = [item["uid_hash"] for item in whitelist_updated]
            self.assertNotIn(self.valid_card_hash, updated_hashes)

    # =========================================================================
    # Skenario 5: Security & Sanitization
    # =========================================================================

    async def test_security_unauthorized_controller_token(self):
        """Controller token tidak sah return 401 Unauthorized."""
        # 1. Direct Service Call
        with self.assertRaises(ControllerAuthenticationError):
            await self.service.verify_access(
                tenant_id=self.tenant_id,
                controller_id=self.controller_gate1,
                uid_hash=self.valid_card_hash,
                device_token="wrong_malicious_token_xyz",
            )

        # 2. HTTP Endpoint Call -> 401
        payload = {
            "tenant_id": self.tenant_id,
            "controller_id": self.controller_gate1,
            "uid_hash": self.valid_card_hash,
            "device_token": "wrong_token_123",
        }
        resp = self.client.post("/api/v1/gym/access/verify", json=payload)
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Unauthorized controller", resp.json().get("detail", ""))

    async def test_security_malformed_card_uid_sanitization_zero_500_errors(self):
        """Malformed card UID dicatat aman sebagai UNKNOWN_CARD tanpa error 500."""
        adversarial_uids = [
            "",                                        # Empty string
            "   ",                                     # Whitespace only
            "'; DROP TABLE gym_members; --",           # SQL Injection payload
            "<script>alert('xss_turnstile')</script>", # XSS payload
            "a" * 1000,                                # Buffer / length payload
            "!@#$%^&*()_+=~`{}[]|:;'<>,.?/",          # Special symbols
            "NON_HEX_CHARACTERS_XYZ_999",              # Invalid hex
        ]

        for malformed_uid in adversarial_uids:
            with self.subTest(uid=malformed_uid[:20]):
                # 1. Direct Service Call
                res = await self.service.verify_access(
                    tenant_id=self.tenant_id,
                    controller_id=self.controller_gate1,
                    uid_hash=malformed_uid,
                    device_token=self.raw_token_gate1,
                    event_type=AccessEventType.TAP_IN,
                )

                self.assertEqual(res.decision, AccessDecision.DENIED)
                self.assertEqual(res.reason, AccessReason.UNKNOWN_CARD)
                self.assertFalse(res.unlock_gate)

                # 2. HTTP Endpoint Call -> 200 OK with DENIED / UNKNOWN_CARD (Never 500)
                http_payload = {
                    "tenant_id": self.tenant_id,
                    "controller_id": self.controller_gate1,
                    "uid_hash": malformed_uid,
                    "event_type": "TAP_IN",
                    "device_token": self.raw_token_gate1,
                }
                http_resp = self.client.post(
                    "/api/v1/gym/access/verify",
                    json=http_payload,
                    headers={"X-Device-Token": self.raw_token_gate1},
                )
                self.assertEqual(http_resp.status_code, 200)
                data = http_resp.json()
                self.assertEqual(data["decision"], "DENIED")
                self.assertEqual(data["reason"], "UNKNOWN_CARD")
                self.assertFalse(data["unlock_gate"])


if __name__ == "__main__":
    unittest.main()
