"""tests/test_whatsapp_webhook_ingestion.py
Unit & Integration Tests for WhatsApp Webhook Ingestion & Durable Idempotency (PostgreSQL Authority).

Validates CTO Architectural Decisions:
1. PostgreSQL table `inbound_webhook_events` schema & unique constraint `(channel_provider, provider_message_id)`.
2. Durable Idempotency: INSERT ON CONFLICT DO NOTHING (conflict = no-op return 200, success = dispatch).
3. Ephemeral Redis Accelerator: If Redis is down, system remains safe and functional via PostgreSQL authority.
4. FastAPI endpoints: GET handshake verification & non-blocking POST ingestion with HTTP 200 OK.
"""

import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.models.inbound_webhook_event import InboundWebhookEvent
from app.schemas.whatsapp import (
    WebhookChallenge,
    WhatsAppChange,
    WhatsAppEntry,
    WhatsAppMessage,
    WhatsAppValue,
    WhatsAppWebhookPayload,
)
from app.services.idempotency import IdempotencyService, idempotency_service


class TestInboundWebhookEventModel(unittest.TestCase):
    """Unit tests for SQLAlchemy InboundWebhookEvent model & constraints."""

    def test_model_columns_and_constraints(self):
        table = InboundWebhookEvent.__table__
        self.assertEqual(table.name, "inbound_webhook_events")

        # Verify required columns exist
        col_names = [col.name for col in table.columns]
        self.assertIn("id", col_names)
        self.assertIn("channel_provider", col_names)
        self.assertIn("provider_message_id", col_names)
        self.assertIn("payload", col_names)
        self.assertIn("status", col_names)
        self.assertIn("created_at", col_names)

        # Verify UniqueConstraint on (channel_provider, provider_message_id)
        unique_constraints = [
            c for c in table.constraints if hasattr(c, "columns") and len(c.columns) > 1
        ]
        has_uq = any(
            set(col.name for col in c.columns) == {"channel_provider", "provider_message_id"}
            for c in unique_constraints
        )
        self.assertTrue(has_uq, "UniqueConstraint on (channel_provider, provider_message_id) must exist")


class TestWhatsAppSchemas(unittest.TestCase):
    """Unit tests for Meta WhatsApp Cloud API schemas."""

    def test_webhook_challenge_schema(self):
        data = {
            "hub.mode": "subscribe",
            "hub.challenge": "987654321",
            "hub.verify_token": "secret_token_abc",
        }
        challenge = WebhookChallenge.model_validate(data)
        self.assertEqual(challenge.mode, "subscribe")
        self.assertEqual(challenge.challenge, "987654321")
        self.assertEqual(challenge.verify_token, "secret_token_abc")

    def test_whatsapp_message_and_payload_schema(self):
        payload_data = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID_999",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6285181830080",
                                    "phone_number_id": "1365010890024026",
                                },
                                "contacts": [
                                    {
                                        "profile": {"name": "Test User"},
                                        "wa_id": "628123456789",
                                    }
                                ],
                                "messages": [
                                    {
                                        "from": "628123456789",
                                        "id": "wamid.HBgLNjI4MTIzNDU2Nzg5FQIAEhgg",
                                        "timestamp": "1741350000",
                                        "type": "text",
                                        "text": {"body": "Halo Admin"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        payload = WhatsAppWebhookPayload.model_validate(payload_data)
        self.assertEqual(payload.object, "whatsapp_business_account")
        self.assertEqual(len(payload.entry), 1)

        entry = payload.entry[0]
        self.assertEqual(entry.id, "WABA_ID_999")
        self.assertEqual(len(entry.changes), 1)

        change = entry.changes[0]
        self.assertEqual(change.field, "messages")
        self.assertEqual(change.value.messaging_product, "whatsapp")

        messages = change.value.messages
        self.assertEqual(len(messages), 1)
        msg = messages[0]
        self.assertEqual(msg.from_, "628123456789")
        self.assertEqual(msg.id, "wamid.HBgLNjI4MTIzNDU2Nzg5FQIAEhgg")
        self.assertEqual(msg.text.body, "Halo Admin")


@pytest.mark.asyncio
class TestIdempotencyService:
    """Tests for IdempotencyService with Durable PostgreSQL Authority & Ephemeral Redis Accelerator."""

    async def test_durable_idempotency_postgres_authority(self):
        # Mocking an AsyncSession
        mock_session = AsyncMock()
        mock_result_new = MagicMock()
        mock_result_new.fetchone.return_value = ["e5b8d234-1111-2222-3333-444455556666"]
        mock_session.execute.return_value = mock_result_new

        service = IdempotencyService()
        service._redis_available = False  # Isolate test to PostgreSQL authority

        wamid = "wamid.POSTGRES_DURABLE_TEST_1"

        # 1st: INSERT returns new ID -> is_new is True
        is_new, event_id = await service.record_inbound_event(
            provider_message_id=wamid,
            payload={"body": "Hello"},
            channel_provider="whatsapp_meta",
            session=mock_session,
        )
        assert is_new is True
        assert event_id == "e5b8d234-1111-2222-3333-444455556666"

        # 2nd: ON CONFLICT DO NOTHING returns None -> is_new is False (conflict)
        mock_result_conflict = MagicMock()
        mock_result_conflict.fetchone.return_value = None
        mock_session.execute.return_value = mock_result_conflict

        is_dup_new, dup_event_id = await service.record_inbound_event(
            provider_message_id=wamid,
            payload={"body": "Hello retry"},
            channel_provider="whatsapp_meta",
            session=mock_session,
        )
        assert is_dup_new is False
        assert dup_event_id is None

    async def test_redis_down_fallback_to_postgres_authority(self):
        """When Redis is DOWN (ConnectionError), system remains safe via PostgreSQL authority."""
        import uuid
        mock_redis = AsyncMock()
        # Redis raises ConnectionError when accessed
        mock_redis.set.side_effect = ConnectionError("Redis daemon is down / offline")
        
        service = IdempotencyService(redis_client=mock_redis)

        wamid = f"wamid.REDIS_DOWN_TEST_{uuid.uuid4().hex[:8]}"
        # 1st call: Succeeded via durable fallback
        is_new1, event_id1 = await service.record_inbound_event(
            provider_message_id=wamid,
            payload={"test": "redis down 1"},
        )
        assert is_new1 is True
        assert event_id1 is not None

        # 2nd call: Duplicate caught by durable authority
        is_new2, event_id2 = await service.record_inbound_event(
            provider_message_id=wamid,
            payload={"test": "redis down 2"},
        )
        assert is_new2 is False
        assert event_id2 is None

    async def test_redis_fast_lock_ephemeral_accelerator(self):
        """When Redis is UP, fast-lock accelerates duplicate checking."""
        mock_redis = AsyncMock()
        mock_redis.set.return_value = None  # Key already held in Redis
        service = IdempotencyService(redis_client=mock_redis)

        is_new, event_id = await service.record_inbound_event(
            provider_message_id="wamid.FAST_LOCK_HIT",
            payload={"test": "fastlock"},
        )
        assert is_new is False
        assert event_id is None

    async def test_enqueue_to_stream(self):
        mock_redis = AsyncMock()
        mock_redis.xadd.return_value = "1741350000000-0"
        service = IdempotencyService(redis_client=mock_redis)

        msg_id = await service.enqueue_to_stream(
            "stream:whatsapp:inbound",
            {"wamid": "wamid.123", "text": "test message"},
        )
        assert msg_id == "1741350000000-0"
        mock_redis.xadd.assert_called_once()


class TestWhatsAppWebhookEndpoints(unittest.TestCase):
    """End-to-end tests for FastAPI WhatsApp Webhook GET and POST endpoints."""

    def setUp(self):
        self.client = TestClient(app)
        self.orig_token = os.environ.get("WHATSAPP_VERIFY_TOKEN")
        os.environ["WHATSAPP_VERIFY_TOKEN"] = "boontrack_verify_secret"

    def tearDown(self):
        if self.orig_token is not None:
            os.environ["WHATSAPP_VERIFY_TOKEN"] = self.orig_token
        else:
            os.environ.pop("WHATSAPP_VERIFY_TOKEN", None)

    def test_get_handshake_verification_success(self):
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "boontrack_verify_secret",
                "hub.challenge": "123456789",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "123456789")
        self.assertIn("text/plain", resp.headers["content-type"])

    def test_get_handshake_verification_failure(self):
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_secret_token",
                "hub.challenge": "123456789",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Verification token mismatch", resp.text)

    def test_post_inbound_message_ingestion_and_idempotency(self):
        test_wamid = f"wamid.TEST_IDEMPOTENCY_E2E_{os.urandom(4).hex()}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_TEST_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6285181830080",
                                    "phone_number_id": "1365010890024026",
                                },
                                "contacts": [
                                    {"profile": {"name": "BoonTrack User"}, "wa_id": "628999888777"}
                                ],
                                "messages": [
                                    {
                                        "from": "628999888777",
                                        "id": test_wamid,
                                        "timestamp": "1741350100",
                                        "type": "text",
                                        "text": {"body": "Halo BoonTrack"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        # 1st Request: First time ingestion -> should enqueue and have 0 duplicates
        resp1 = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1.get("status"), "success")
        self.assertEqual(data1.get("enqueued"), 1)
        self.assertEqual(data1.get("duplicates"), 0)

        # 2nd Request (Immediate retry from Meta): same wamid -> should skip as duplicate!
        resp2 = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2.get("status"), "success")
        self.assertEqual(data2.get("enqueued"), 0)
        self.assertEqual(data2.get("duplicates"), 1)

    def test_post_status_update_ignored_gracefully(self):
        status_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_TEST_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6285181830080",
                                    "phone_number_id": "1365010890024026",
                                },
                                "statuses": [
                                    {
                                        "id": "wamid.HBgL...",
                                        "status": "delivered",
                                        "timestamp": "1741350200",
                                        "recipient_id": "628999888777",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        resp = self.client.post("/webhook/whatsapp", json=status_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "status_acknowledged")


if __name__ == "__main__":
    unittest.main()
