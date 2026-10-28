"""tests/test_webhook_url_reconciliation.py
Focused test suite verifying Meta WhatsApp Webhook URL Reconciliation & Routing:
1. GET verification handshake succeeds with configured token & challenge on /webhook/whatsapp
2. Invalid verification token or missing env token fails closed with HTTP 403
3. POST inbound events reach authoritative handler through /webhook/whatsapp
4. OnlineBoost Phone Number ID (1419090974617162) resolves to 'onlineboost'
5. BoonTrack Phone Number ID (1365010890024026) resolves to platform/holding tenant
6. Duplicate events (wamid) do not create duplicate processing (durable idempotency)
7. Opt-out events (STOP / BERHENTI) synchronously persist suppression and never trigger promotional replies (fail closed on persistence failure)
8. Existing routes (/api/v1/webhook/whatsapp and /api/webhook/whatsapp) remain fully compatible
9. Invalid requests fail safely without bypassing webhook verification
"""

import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.services.tenant_resolver import resolve_tenant_by_phone_number_id
from app.services.tenant_context_resolver import tenant_context_resolver


class TestWebhookUrlReconciliation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.test_token = "boontrack_meta_verify_deterministic_secret_2026"
        cls.onlineboost_phone_id = "1419090974617162"
        cls.boontrack_phone_id = "1365010890024026"

    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {
            "WHATSAPP_VERIFY_TOKEN": self.test_token,
            "ONLINEBOOST_PHONE_NUMBER_ID": self.onlineboost_phone_id,
            "PLATFORM_PHONE_NUMBER_ID": self.boontrack_phone_id,
            "ONLINEBOOST_PAYMENT_STRICT_HOLD": "true",
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    # -------------------------------------------------------------------------
    # 1. GET Verification Handshake on Configured Callback URL
    # -------------------------------------------------------------------------
    def test_01_get_handshake_success_on_configured_url(self):
        """Meta GET /webhook/whatsapp handshake succeeds with configured token and challenge."""
        challenge_val = "998877665544"
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": self.test_token,
                "hub.challenge": challenge_val,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, challenge_val)
        self.assertIn("text/plain", resp.headers["content-type"])

    # -------------------------------------------------------------------------
    # 2. Token Mismatch & Missing Token Fails Closed (HTTP 403)
    # -------------------------------------------------------------------------
    def test_02_get_handshake_invalid_token_rejected_fail_closed(self):
        """Invalid verification token is rejected with HTTP 403 on /webhook/whatsapp."""
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_unauthorized_token",
                "hub.challenge": "12345",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Verification token mismatch", resp.text)

    def test_02b_get_handshake_missing_env_token_fails_closed(self):
        """If no verification token is configured in environment, verification fails closed."""
        env_without_tokens = {
            k: v for k, v in os.environ.items()
            if k not in (
                "WHATSAPP_VERIFY_TOKEN",
                "META_WHATSAPP_VERIFY_TOKEN",
                "META_WEBHOOK_VERIFY_TOKEN",
                "ONLINEBOOST_WEBHOOK_VERIFY_TOKEN",
            )
        }
        with patch.dict(os.environ, env_without_tokens, clear=True):
            resp = self.client.get(
                "/webhook/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "attempted_token",
                    "hub.challenge": "12345",
                },
            )
            self.assertEqual(resp.status_code, 403)
            self.assertIn("Verification token mismatch", resp.text)

    # -------------------------------------------------------------------------
    # 3. POST Inbound Events Reach Correct Handler through /webhook/whatsapp
    # -------------------------------------------------------------------------
    def test_03_post_inbound_event_reaches_handler_on_configured_url(self):
        """Inbound message payload on /webhook/whatsapp reaches ingest_whatsapp_webhook."""
        wamid = f"wamid.RECON_TEST_{os.urandom(4).hex()}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": self.onlineboost_phone_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6288226098088",
                                    "phone_number_id": self.onlineboost_phone_id,
                                },
                                "messages": [
                                    {
                                        "from": "6288226098088",
                                        "id": wamid,
                                        "timestamp": "1730000000",
                                        "text": {"body": "Halo OnlineBoost"},
                                        "type": "text",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

        with patch("app.api.v1.endpoints.whatsapp_webhook._dispatch_to_traffic_splitter", new_callable=AsyncMock) as mock_dispatch:
            resp = self.client.post("/webhook/whatsapp", json=payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get("status"), "success")
            self.assertEqual(data.get("enqueued"), 1)
            self.assertEqual(data.get("duplicates"), 0)
            self.assertEqual(data.get("unmapped"), 0)

    # -------------------------------------------------------------------------
    # 4. OnlineBoost Phone Number ID Resolves to 'onlineboost'
    # -------------------------------------------------------------------------
    def test_04_onlineboost_phone_number_id_resolves_to_onlineboost(self):
        """Phone Number ID 1419090974617162 resolves strictly to tenant 'onlineboost'."""
        import asyncio
        tenant_info = asyncio.run(resolve_tenant_by_phone_number_id(self.onlineboost_phone_id))
        self.assertIsNotNone(tenant_info)
        self.assertEqual(tenant_info.get("tenant_id"), "onlineboost")
        self.assertTrue(tenant_info.get("is_active"))

        # Also verify through tenant_context_resolver
        context = asyncio.run(tenant_context_resolver.resolve_by_phone_number_id(self.onlineboost_phone_id))
        self.assertIsNotNone(context)
        self.assertEqual(context.tenant_slug, "onlineboost")

    # -------------------------------------------------------------------------
    # 5. BoonTrack Phone Number ID Resolves to Proper Platform Tenant
    # -------------------------------------------------------------------------
    def test_05_boontrack_phone_number_id_resolves_to_platform(self):
        """Phone Number ID 1365010890024026 resolves strictly to BoonTrack platform/holding."""
        import asyncio
        tenant_info = asyncio.run(resolve_tenant_by_phone_number_id(self.boontrack_phone_id))
        self.assertIsNotNone(tenant_info)
        self.assertEqual(tenant_info.get("tenant_id"), "boontrack-platform")
        self.assertTrue(tenant_info.get("is_active"))

        # Also verify through tenant_context_resolver
        context = asyncio.run(tenant_context_resolver.resolve_by_phone_number_id(self.boontrack_phone_id))
        self.assertIsNotNone(context)
        self.assertIn(context.tenant_slug, ("boontrack-holding", "boontrack-platform"))

    # -------------------------------------------------------------------------
    # 6. Duplicate Events Do Not Create Duplicate Processing (Idempotency)
    # -------------------------------------------------------------------------
    def test_06_duplicate_events_idempotent_deduplication(self):
        """Identical wamid sent twice to /webhook/whatsapp results in no-op duplicate acknowledgment."""
        fixed_wamid = f"wamid.DEDUP_TEST_{os.urandom(6).hex()}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": self.onlineboost_phone_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6288226098088",
                                    "phone_number_id": self.onlineboost_phone_id,
                                },
                                "messages": [
                                    {
                                        "from": "6281234567890",
                                        "id": fixed_wamid,
                                        "timestamp": "1730000000",
                                        "text": {"body": "Pesan pertama"},
                                        "type": "text",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

        with patch("app.api.v1.endpoints.whatsapp_webhook._dispatch_to_traffic_splitter", new_callable=AsyncMock) as mock_dispatch:
            # First delivery -> new event, enqueued
            resp1 = self.client.post("/webhook/whatsapp", json=payload)
            self.assertEqual(resp1.status_code, 200)
            self.assertEqual(resp1.json().get("enqueued"), 1)

            # Second delivery -> duplicate detected via durable idempotency
            resp2 = self.client.post("/webhook/whatsapp", json=payload)
            self.assertEqual(resp2.status_code, 200)
            data2 = resp2.json()
            self.assertEqual(data2.get("duplicates"), 1)
            self.assertEqual(data2.get("enqueued"), 0)

    # -------------------------------------------------------------------------
    # 7. Opt-Out Events Cannot Trigger Promotional Replies & Fail-Closed Policy
    # -------------------------------------------------------------------------
    def test_07_opt_out_keyword_triggers_suppression_and_no_promo_reply(self):
        """Keyword STOP synchronously persists durable suppression and returns confirmation, not promotional bot response."""
        opt_wamid = f"wamid.OPTOUT_TEST_{os.urandom(6).hex()}"
        sender_num = "628999888777"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": self.onlineboost_phone_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6288226098088",
                                    "phone_number_id": self.onlineboost_phone_id,
                                },
                                "messages": [
                                    {
                                        "from": sender_num,
                                        "id": opt_wamid,
                                        "timestamp": "1730000000",
                                        "text": {"body": "STOP"},
                                        "type": "text",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

        with patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send, \
             patch("app.services.phone_suppression_service.record_durable_suppression", return_value=(True, "test_store")) as mock_suppress:
            resp = self.client.post("/webhook/whatsapp", json=payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get("action"), "opt_out_confirmed")
            self.assertEqual(data.get("phone"), sender_num)
            self.assertEqual(data.get("tenant"), "onlineboost")

            # Verify that only the opt-out confirmation text is sent, never promo/sales CTA
            if mock_send.called:
                call_args = mock_send.call_args[1]
                msg_sent = call_args.get("text", "")
                self.assertIn("berhenti berlangganan", msg_sent)
                self.assertNotIn("Rp249.000", msg_sent)
                self.assertNotIn("QRIS", msg_sent)

    def test_07b_opt_out_persistence_failure_fails_closed_503(self):
        """Failed opt-out persistence returns HTTP 503 so Meta will retry (fail-closed policy)."""
        opt_wamid = f"wamid.OPTOUT_FAIL_{os.urandom(6).hex()}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": self.onlineboost_phone_id,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6288226098088",
                                    "phone_number_id": self.onlineboost_phone_id,
                                },
                                "messages": [
                                    {
                                        "from": "628999888777",
                                        "id": opt_wamid,
                                        "timestamp": "1730000000",
                                        "text": {"body": "BERHENTI"},
                                        "type": "text",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

        with patch("app.services.phone_suppression_service.record_durable_suppression", return_value=(False, None)):
            resp = self.client.post("/webhook/whatsapp", json=payload)
            self.assertEqual(resp.status_code, 503)
            data = resp.json()
            self.assertEqual(data.get("status"), "error")
            self.assertIn("Suppression persistence unavailable", data.get("message"))

    # -------------------------------------------------------------------------
    # 8. Existing Routes Compatibility (/api/v1/webhook/whatsapp & /api/webhook/whatsapp)
    # -------------------------------------------------------------------------
    def test_08_alias_routes_compatibility(self):
        """Both /api/v1/webhook/whatsapp and /api/webhook/whatsapp maintain parity with /webhook/whatsapp."""
        challenge = "alias_challenge_12345"
        for path in ("/api/v1/webhook/whatsapp", "/api/webhook/whatsapp"):
            # GET handshake verification
            resp_get = self.client.get(
                path,
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": self.test_token,
                    "hub.challenge": challenge,
                },
            )
            self.assertEqual(resp_get.status_code, 200, f"GET {path} failed")
            self.assertEqual(resp_get.text, challenge)

            # POST message ingestion
            test_wamid = f"wamid.ALIAS_TEST_{os.urandom(4).hex()}"
            alias_payload = {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "id": self.onlineboost_phone_id,
                        "changes": [
                            {
                                "value": {
                                    "messaging_product": "whatsapp",
                                    "metadata": {
                                        "display_phone_number": "6288226098088",
                                        "phone_number_id": self.onlineboost_phone_id,
                                    },
                                    "messages": [
                                        {
                                            "from": "628111222333",
                                            "id": test_wamid,
                                            "timestamp": "1730000000",
                                            "text": {"body": f"Testing via {path}"},
                                            "type": "text",
                                        }
                                    ],
                                },
                                "field": "messages",
                            }
                        ],
                    }
                ],
            }
            with patch("app.api.v1.endpoints.whatsapp_webhook._dispatch_to_traffic_splitter", new_callable=AsyncMock):
                resp_post = self.client.post(path, json=alias_payload)
                self.assertEqual(resp_post.status_code, 200, f"POST {path} failed")
                self.assertEqual(resp_post.json().get("status"), "success")

    # -------------------------------------------------------------------------
    # 9. Invalid Requests Fail Safely Without Bypassing Verification
    # -------------------------------------------------------------------------
    def test_09_invalid_requests_fail_safely(self):
        """Malformed or unmapped requests fail safely without bypassing security or crashing server."""
        # A. Empty body returns empty_body status safely
        resp_empty = self.client.post("/webhook/whatsapp", content="")
        self.assertEqual(resp_empty.status_code, 200)
        self.assertEqual(resp_empty.json().get("status"), "empty_body")

        # B. Malformed JSON returns error safely
        resp_bad_json = self.client.post(
            "/webhook/whatsapp",
            content="not a json string",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(resp_bad_json.status_code, 200)
        self.assertEqual(resp_bad_json.json().get("status"), "error")
        self.assertEqual(resp_bad_json.json().get("message"), "invalid_json_format")

        # C. Unmapped Phone Number ID is safely dropped with unmapped count
        unmapped_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "9999999999999999",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "628999999999",
                                    "phone_number_id": "9999999999999999",
                                },
                                "messages": [
                                    {
                                        "from": "628999999999",
                                        "id": f"wamid.UNMAPPED_{os.urandom(4).hex()}",
                                        "timestamp": "1730000000",
                                        "text": {"body": "Unmapped tenant test"},
                                        "type": "text",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }
        resp_unmapped = self.client.post("/webhook/whatsapp", json=unmapped_payload)
        self.assertEqual(resp_unmapped.status_code, 200)
        data = resp_unmapped.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("unmapped"), 1)
        self.assertEqual(data.get("enqueued"), 0)


if __name__ == "__main__":
    unittest.main()
