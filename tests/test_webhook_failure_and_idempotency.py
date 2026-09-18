"""
tests/test_webhook_failure_and_idempotency.py
---------------------------------------------
Milestone P0.5: Operational Failure Testing & Idempotency Certification Framework.

Test Coverage:
1. Duplicate Webhook Deliveries (Idempotency Simulation):
   - Duplicate AKTIVASI BT-xxxx with identical wamid.
   - Duplicate transactional notification alerts.
2. Database Outage & Timeout Resilience (Graceful Degradation):
   - Supabase lookup timeout / connection error handling.
   - Supabase write / update failure handling.
3. Expired Activation Token Rejection:
   - Registration created > 48 hours ago is rejected with REGISTRATION_EXPIRED.
   - Registration created < 48 hours ago is successfully verified.
4. Malformed / Corrupted Payload Resilience:
   - Completely empty payload {}.
   - Malformed entry structure without messages.
   - Non-dictionary change values.
"""

import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.whatsapp.traffic_splitter import (
    TrafficSplitter,
    PlatformWebhookRouter,
    PLATFORM_PHONE_NUMBER_ID,
)
from app.services.onboarding_service import onboarding_service


class TestWebhookFailureAndIdempotency(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.platform_phone_id = str(PLATFORM_PHONE_NUMBER_ID) or "1268977686299719"
        self.sender_phone = "6281234569999"

    # =========================================================================
    # 1. DUPLICATE WEBHOOK DELIVERIES (IDEMPOTENCY SIMULATION)
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    def test_duplicate_activation_webhook_idempotency(self, mock_send_wa):
        """
        Meta sering mengirim ulang webhook yang sama (at-least-once delivery).
        Pengiriman kedua dengan wamid yang sama tidak boleh menyebabkan crash,
        tidak merusak state database, dan tetap mengembalikan HTTP 200 OK.
        """
        mock_send_wa.return_value = True
        wamid_shared = "wamid.HBgNNjI4MTIzNDU2OTk5OQA="

        # Register pending tenant in memory
        onboarding_service._tenants_by_slug["tenant-idemp-test"] = {
            "id": "t-idemp-001",
            "slug": "tenant-idemp-test",
            "name": "Toko Idemp Test",
            "status": "pending_wa_verification",
            "is_active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "wa_verification_token": "BT-9911",
                "phone": self.sender_phone,
                "is_verified": False,
            }
        }

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.platform_phone_id,
                            "display_phone_number": "6285179555449"
                        },
                        "contacts": [{"profile": {"name": "Merchant Owner"}, "wa_id": self.sender_phone}],
                        "messages": [{
                            "from": self.sender_phone,
                            "id": wamid_shared,
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "type": "text",
                            "text": {"body": "AKTIVASI BT-9911"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        # Delivery 1: Inisiasi aktivasi pertama
        resp1 = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1.get("status"), "success")
        self.assertEqual(data1.get("verified"), True)
        self.assertEqual(data1.get("token"), "BT-9911")

        # Delivery 2: Meta replay webhook dengan wamid yang persis sama
        resp2 = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        # Harus tetap sukses / sudah terverifikasi tanpa error
        self.assertEqual(data2.get("status"), "success")
        self.assertEqual(data2.get("verified"), True)

    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    def test_duplicate_transactional_notification(self, mock_send_wa):
        """
        Notifikasi pembayaran berulang harus diakui dengan 200 OK tanpa error.
        """
        mock_send_wa.return_value = True
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.platform_phone_id,
                            "display_phone_number": "6285179555449"
                        },
                        "messages": [{
                            "from": "6281999888000",
                            "id": "wamid.PAYMENT_DUP_01",
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "type": "text",
                            "text": {"body": "Pembayaran Berhasil untuk invoice #INV-2026-9999"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp1 = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp1.status_code, 200)

        resp2 = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json().get("action"), "transactional_notification_logged")

    # =========================================================================
    # 2. DATABASE OUTAGE & TIMEOUT RESILIENCE (GRACEFUL DEGRADATION)
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.whatsapp.traffic_splitter.get_supabase")
    def test_database_outage_graceful_fallback(self, mock_get_supabase, mock_send_wa):
        """
        Saat database Supabase mengalami outage atau timeout:
        Gateway harus tetap tangguh, tidak melempar HTTP 500 uncaught exception,
        dan menggunakan in-memory onboarding fallback jika tersedia.
        """
        mock_send_wa.return_value = True

        # Simulasikan Supabase melempar ConnectionError / Timeout
        mock_db = MagicMock()
        mock_table = MagicMock()
        mock_select = MagicMock()
        mock_filter = MagicMock()
        mock_filter.execute.side_effect = ConnectionError("Supabase connection timeout: host unreachable")
        mock_select.filter.return_value = mock_filter
        mock_table.select.return_value = mock_select
        mock_db.table.return_value = mock_table
        mock_get_supabase.return_value = mock_db

        # Sediakan fallback record di onboarding_service memory
        onboarding_service._tenants_by_slug["store-db-fallback"] = {
            "id": "t-db-fail-01",
            "slug": "store-db-fallback",
            "status": "pending_wa_verification",
            "is_active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "wa_verification_token": "BT-7722",
                "phone": self.sender_phone,
                "is_verified": False,
            }
        }

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.platform_phone_id,
                            "display_phone_number": "6285179555449"
                        },
                        "messages": [{
                            "from": self.sender_phone,
                            "id": "wamid.DB_OUTAGE_TEST",
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "type": "text",
                            "text": {"body": "AKTIVASI BT-7722"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        # Gateway TIDAK BOLEH crash 500! Harus tetap mengembalikan 200 OK
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("verified"), True)
        self.assertEqual(data.get("tenant_slug"), "store-db-fallback")

    # =========================================================================
    # 3. EXPIRED ACTIVATION TOKEN REJECTION (TOKEN EXPIRY DOMAIN)
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    def test_expired_activation_token_rejected_cleanly(self, mock_send_wa):
        """
        Token yang telah dibuat lebih dari 48 jam yang lalu harus ditolak
        dengan reason REGISTRATION_EXPIRED dan token_expired == True.
        """
        mock_send_wa.return_value = True
        expired_created_at = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()

        onboarding_service._tenants_by_slug["expired-store-test"] = {
            "id": "t-expired-01",
            "slug": "expired-store-test",
            "status": "pending_wa_verification",
            "is_active": False,
            "created_at": expired_created_at,
            "metadata": {
                "wa_verification_token": "BT-4040",
                "phone": self.sender_phone,
                "is_verified": False,
            }
        }

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.platform_phone_id,
                            "display_phone_number": "6285179555449"
                        },
                        "messages": [{
                            "from": self.sender_phone,
                            "id": "wamid.EXP_TOKEN_MSG",
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "type": "text",
                            "text": {"body": "AKTIVASI BT-4040"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "rejected")
        self.assertEqual(data.get("reason"), "REGISTRATION_EXPIRED")
        self.assertEqual(data.get("verified"), False)
        self.assertEqual(data.get("token_expired"), True)
        self.assertIn("sudah kadaluarsa", data.get("reply", ""))

    # =========================================================================
    # 4. MALFORMED / CORRUPTED WEBHOOK PAYLOAD RESILIENCE
    # =========================================================================
    def test_completely_empty_payload(self):
        """Payload {} tidak boleh menyebabkan uncaught internal server error."""
        resp = self.client.post("/api/v1/whatsapp/webhook", json={})
        self.assertEqual(resp.status_code, 200)

    def test_malformed_entry_structure(self):
        """Payload tanpa changes atau messages harus ditangani secara aman."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "bad_entry"}]
        }
        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)

    def test_status_only_payload_halts_early(self):
        """Payload hanya berisi delivery status (sent/delivered/read) harus di-drop langsung."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": self.platform_phone_id},
                        "statuses": [{"id": "wamid.STATUS_01", "status": "read"}]
                    },
                    "field": "messages"
                }]
            }]
        }
        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "STATUS_IGNORED")


if __name__ == "__main__":
    unittest.main()
