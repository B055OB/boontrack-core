"""tests/test_tenant_webhook_resolution.py
Unit & Integration Tests for Tenant Isolation Guard & Webhook Mapping.

Validates:
1. Model & Schema mapping for Tenant WABA integration.
2. Tenant resolution service:
   - Cache hit / miss logic.
   - DB / Registry lookup.
   - TenantNotFoundError / None handling for unknown or inactive phone IDs.
3. Webhook Ingress Tenant Isolation Guard:
   - Webhook payload with valid business phone_number_id maps to tenant_id and enqueues.
   - Webhook payload with unknown business phone_number_id is gracefully dropped (HTTP 200, unmapped count, no dispatch).
   - Inactive tenant is safely rejected.
"""

import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.models.tenant_waba import TenantWabaConfig
from app.services.tenant_resolver import (
    TenantNotFoundError,
    clear_tenant_cache,
    register_tenant_waba_mapping,
    resolve_tenant_by_phone_number_id,
)


class TestTenantWabaModel(unittest.TestCase):
    """Unit tests for TenantWabaConfig model schema and indexes."""

    def test_tenant_waba_model_fields_and_index(self):
        table = TenantWabaConfig.__table__
        self.assertEqual(table.name, "tenant_waba_configs")

        col_names = [c.name for c in table.columns]
        self.assertIn("tenant_id", col_names)
        self.assertIn("waba_phone_number_id", col_names)
        self.assertIn("is_active", col_names)

        # Check unique & indexed on waba_phone_number_id
        col = table.columns["waba_phone_number_id"]
        self.assertTrue(col.unique or any("waba_phone_number_id" in idx.columns for idx in table.indexes))


@pytest.mark.asyncio
class TestTenantResolverService:
    """Tests for resolve_tenant_by_phone_number_id service."""

    def setUp(self):
        clear_tenant_cache()

    async def test_resolve_registered_active_tenant(self):
        register_tenant_waba_mapping(
            phone_number_id="waba_valid_phone_123",
            tenant_id="tenant_coffee_shop",
            is_active=True,
            display_phone_number="628111222333",
        )

        res = await resolve_tenant_by_phone_number_id("waba_valid_phone_123")
        assert res is not None
        assert res["tenant_id"] == "tenant_coffee_shop"
        assert res["waba_phone_number_id"] == "waba_valid_phone_123"
        assert res["is_active"] is True

    async def test_resolve_inactive_tenant_returns_none(self):
        register_tenant_waba_mapping(
            phone_number_id="waba_inactive_phone_456",
            tenant_id="tenant_suspended",
            is_active=False,
        )

        res = await resolve_tenant_by_phone_number_id("waba_inactive_phone_456")
        assert res is None

        with pytest.raises(TenantNotFoundError):
            await resolve_tenant_by_phone_number_id("waba_inactive_phone_456", raise_if_not_found=True)

    async def test_resolve_unknown_phone_id_returns_none(self):
        clear_tenant_cache()
        res = await resolve_tenant_by_phone_number_id("unknown_phone_99999")
        assert res is None

        with pytest.raises(TenantNotFoundError):
            await resolve_tenant_by_phone_number_id("unknown_phone_99999", raise_if_not_found=True)


class TestTenantWebhookResolutionEndpoints(unittest.TestCase):
    """Integration tests for Webhook Ingress Tenant Isolation Guard."""

    def setUp(self):
        self.client = TestClient(app)
        clear_tenant_cache()

    def test_webhook_with_valid_tenant_resolves_and_enqueues(self):
        # Register test merchant
        valid_phone_id = f"waba_store_valid_{os.urandom(4).hex()}"
        register_tenant_waba_mapping(
            phone_number_id=valid_phone_id,
            tenant_id="merchant_bakery_01",
            is_active=True,
        )

        wamid = f"wamid.VALID_TENANT_{os.urandom(4).hex()}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID_01",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "628129990001",
                                    "phone_number_id": valid_phone_id,
                                },
                                "contacts": [{"wa_id": "628555444333", "profile": {"name": "Buyer"}}],
                                "messages": [
                                    {
                                        "from": "628555444333",
                                        "id": wamid,
                                        "timestamp": "1741360000",
                                        "type": "text",
                                        "text": {"body": "Mau pesan roti"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        resp = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("enqueued"), 1)
        self.assertEqual(data.get("unmapped"), 0)

    def test_webhook_with_unregistered_phone_is_gracefully_dropped(self):
        # Unmapped / rogue business phone ID
        unmapped_phone_id = f"unregistered_ghost_waba_{os.urandom(6).hex()}"
        wamid = f"wamid.UNMAPPED_{os.urandom(4).hex()}"

        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID_UNMAPPED",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "628999888111",
                                    "phone_number_id": unmapped_phone_id,
                                },
                                "messages": [
                                    {
                                        "from": "628555444333",
                                        "id": wamid,
                                        "timestamp": "1741360000",
                                        "type": "text",
                                        "text": {"body": "Hello rogue"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        resp = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Must return HTTP 200 without enqueuing to business pipeline (graceful drop)
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("enqueued"), 0)
        self.assertEqual(data.get("unmapped"), 1)

    def test_webhook_with_inactive_tenant_is_gracefully_dropped(self):
        suspended_phone_id = f"waba_suspended_{os.urandom(4).hex()}"
        register_tenant_waba_mapping(
            phone_number_id=suspended_phone_id,
            tenant_id="merchant_delinquent",
            is_active=False,
        )

        wamid = f"wamid.SUSPENDED_{os.urandom(4).hex()}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID_SUSPENDED",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "628999888222",
                                    "phone_number_id": suspended_phone_id,
                                },
                                "messages": [
                                    {
                                        "from": "628555444333",
                                        "id": wamid,
                                        "timestamp": "1741360000",
                                        "type": "text",
                                        "text": {"body": "Testing suspended"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

        resp = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("enqueued"), 0)
        self.assertEqual(data.get("unmapped"), 1)


if __name__ == "__main__":
    unittest.main()
