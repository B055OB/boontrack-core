"""tests/test_meta_webhook_p0_authentication.py
Comprehensive P0 Cryptographic Authentication & Regression Suite for Meta WhatsApp Webhooks.

Validates:
1. Valid signature accepted (HTTP 200).
2. Missing signature rejected (HTTP 401).
3. Invalid signature rejected (HTTP 401).
4. Missing META_APP_SECRET fails closed (HTTP 500).
5. Modified payload rejected (HTTP 401).
6. Invalid signature does not modify `phone_suppressions` (zero mutation).
7. Invalid signature does not trigger outbound WhatsApp dispatch.
8. Duplicate valid webhook remains idempotent.
9. Valid opt-out is successfully persisted.
10. WABA status callback only accepts valid signature.
11. All route aliases have identical cryptographic protection.
12. Raw verify token, App Secret, and signature do not leak into logs.
"""

import json
import logging
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.security.test_isolation_guard import (
    bootstrap_isolated_test_env,
    is_disposable_services_required,
)

bootstrap_isolated_test_env()

from app.core.security.meta_webhook_verifier import compute_meta_webhook_signature
from app.main import app
from app.services.idempotency import idempotency_service


class TestMetaWebhookP0Authentication(unittest.TestCase):
    def setUp(self):
        self.app_secret = "test_meta_app_secret_deterministic_998877"
        self.verify_token = "test_meta_verify_token_deterministic_112233"
        self.xendit_key = "xnd_development_dummy_key_for_test"
        self.xendit_token = "dummy_token_123"

        self.env_patcher = patch.dict(
            os.environ,
            {
                "META_APP_SECRET": self.app_secret,
                "WHATSAPP_VERIFY_TOKEN": self.verify_token,
                "XENDIT_SECRET_KEY": self.xendit_key,
                "XENDIT_CALLBACK_TOKEN": self.xendit_token,
            },
        )
        self.env_patcher.start()
        if is_disposable_services_required():
            idempotency_service._in_memory_durable_events.clear()
        self.client = TestClient(app)

    def tearDown(self):
        self.env_patcher.stop()

    def _build_sample_payload(self, text_body: str = "Halo Test", wamid: str = "wamid.SAMPLE_TEST_001"):
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1365010890024026",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6285181830080",
                                    "phone_number_id": "1365010890024026",
                                },
                                "contacts": [{"profile": {"name": "Test User"}, "wa_id": "6281234567890"}],
                                "messages": [
                                    {
                                        "from": "6281234567890",
                                        "id": wamid,
                                        "timestamp": "1731112233",
                                        "type": "text",
                                        "text": {"body": text_body},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }

    # -------------------------------------------------------------------------
    # 1. Valid signature accepted
    # -------------------------------------------------------------------------
    @patch("app.api.v1.endpoints.whatsapp_webhook._dispatch_to_traffic_splitter", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock)
    def test_01_valid_signature_accepted(self, mock_resolve, mock_dispatch):
        mock_resolve.return_value = {"tenant_id": "onlineboost", "is_active": True}
        raw_bytes = json.dumps(self._build_sample_payload()).encode("utf-8")
        sig = compute_meta_webhook_signature(raw_bytes, self.app_secret)

        resp = self.client.post(
            "/webhook/whatsapp",
            content=raw_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("enqueued"), 1)
        if is_disposable_services_required():
            self.assertEqual(len(idempotency_service._in_memory_durable_events), 0)

    # -------------------------------------------------------------------------
    # 2. Missing signature rejected (HTTP 401)
    # -------------------------------------------------------------------------
    def test_02_missing_signature_rejected(self):
        raw_bytes = json.dumps(self._build_sample_payload()).encode("utf-8")
        resp = self.client.post(
            "/webhook/whatsapp",
            content=raw_bytes,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertEqual(data.get("status"), "error")
        self.assertIn("Missing X-Hub-Signature-256", data.get("message"))

    # -------------------------------------------------------------------------
    # 3. Invalid signature rejected (HTTP 401)
    # -------------------------------------------------------------------------
    def test_03_invalid_signature_rejected(self):
        raw_bytes = json.dumps(self._build_sample_payload()).encode("utf-8")
        forged_sig = "sha256=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        resp = self.client.post(
            "/webhook/whatsapp",
            content=raw_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": forged_sig},
        )
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertEqual(data.get("status"), "error")
        self.assertIn("Invalid webhook signature", data.get("message"))

    # -------------------------------------------------------------------------
    # 4. Missing META_APP_SECRET fails closed (HTTP 500)
    # -------------------------------------------------------------------------
    def test_04_missing_meta_app_secret_fails_closed(self):
        with patch.dict(os.environ, {"META_APP_SECRET": "", "META_WHATSAPP_APP_SECRET": "", "WHATSAPP_APP_SECRET": ""}):
            raw_bytes = json.dumps(self._build_sample_payload()).encode("utf-8")
            sig = compute_meta_webhook_signature(raw_bytes, "arbitrary_key")

            resp = self.client.post(
                "/webhook/whatsapp",
                content=raw_bytes,
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
            )
            self.assertEqual(resp.status_code, 500)
            data = resp.json()
            self.assertEqual(data.get("status"), "error")
            self.assertIn("META_APP_SECRET not configured", data.get("message"))

    # -------------------------------------------------------------------------
    # 5. Modified payload rejected (HTTP 401)
    # -------------------------------------------------------------------------
    def test_05_modified_payload_rejected(self):
        original_bytes = json.dumps(self._build_sample_payload(text_body="Original text")).encode("utf-8")
        sig = compute_meta_webhook_signature(original_bytes, self.app_secret)

        tampered_bytes = json.dumps(self._build_sample_payload(text_body="Tampered text")).encode("utf-8")
        resp = self.client.post(
            "/webhook/whatsapp",
            content=tampered_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertIn("Invalid webhook signature", data.get("message"))

    # -------------------------------------------------------------------------
    # 6. Invalid signature does not modify phone_suppressions
    # -------------------------------------------------------------------------
    @patch("app.services.phone_suppression_service.record_durable_suppression")
    def test_06_invalid_signature_does_not_modify_suppressions(self, mock_suppress):
        opt_out_bytes = json.dumps(self._build_sample_payload(text_body="STOP")).encode("utf-8")
        forged_sig = "sha256=ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"

        resp = self.client.post(
            "/webhook/whatsapp",
            content=opt_out_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": forged_sig},
        )
        self.assertEqual(resp.status_code, 401)
        mock_suppress.assert_not_called()

    # -------------------------------------------------------------------------
    # 7. Invalid signature does not trigger outbound WhatsApp
    # -------------------------------------------------------------------------
    @patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock)
    def test_07_invalid_signature_does_not_trigger_outbound_whatsapp(self, mock_send):
        opt_out_bytes = json.dumps(self._build_sample_payload(text_body="STOP")).encode("utf-8")
        forged_sig = "sha256=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

        resp = self.client.post(
            "/webhook/whatsapp",
            content=opt_out_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": forged_sig},
        )
        self.assertEqual(resp.status_code, 401)
        mock_send.assert_not_called()

    # -------------------------------------------------------------------------
    # 8. Duplicate valid webhook remains idempotent
    # -------------------------------------------------------------------------
    @patch("app.api.v1.endpoints.whatsapp_webhook._dispatch_to_traffic_splitter", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock)
    def test_08_duplicate_valid_webhook_remains_idempotent(self, mock_resolve, mock_dispatch):
        mock_resolve.return_value = {"tenant_id": "onlineboost", "is_active": True}
        unique_wamid = f"wamid.IDEMPOTENT_TEST_{os.urandom(4).hex()}"
        raw_bytes = json.dumps(self._build_sample_payload(wamid=unique_wamid)).encode("utf-8")
        sig = compute_meta_webhook_signature(raw_bytes, self.app_secret)

        # 1st dispatch -> enqueued
        resp1 = self.client.post(
            "/webhook/whatsapp",
            content=raw_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json().get("enqueued"), 1)
        self.assertEqual(resp1.json().get("duplicates"), 0)

        # 2nd dispatch -> caught as duplicate, zero duplicate enqueue
        resp2 = self.client.post(
            "/webhook/whatsapp",
            content=raw_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json().get("enqueued"), 0)
        self.assertEqual(resp2.json().get("duplicates"), 1)
        if is_disposable_services_required():
            self.assertEqual(len(idempotency_service._in_memory_durable_events), 0)

    # -------------------------------------------------------------------------
    # 9. Valid opt-out is successfully persisted
    # -------------------------------------------------------------------------
    @patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.services.phone_suppression_service.record_durable_suppression")
    @patch("app.api.v1.endpoints.whatsapp_webhook.resolve_tenant_by_phone_number_id", new_callable=AsyncMock)
    def test_09_valid_opt_out_is_successfully_persisted(self, mock_resolve, mock_suppress, mock_send):
        mock_resolve.return_value = {"tenant_id": "onlineboost", "is_active": True}
        mock_suppress.return_value = (True, "mock_pg_source")

        raw_bytes = json.dumps(self._build_sample_payload(text_body="UNSUBSCRIBE")).encode("utf-8")
        sig = compute_meta_webhook_signature(raw_bytes, self.app_secret)

        resp = self.client.post(
            "/webhook/whatsapp",
            content=raw_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("action"), "opt_out_confirmed")
        mock_suppress.assert_called_once()
        mock_send.assert_called_once()

    # -------------------------------------------------------------------------
    # 10. WABA status callback only accepts valid signature
    # -------------------------------------------------------------------------
    @patch("app.routes.meta_waba_routes.update_message_status_idempotent", new_callable=AsyncMock)
    def test_10_waba_status_callback_signature_enforcement(self, mock_update):
        mock_update.return_value = True
        status_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID_01",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "statuses": [
                                    {
                                        "id": "wamid.STATUS_TEST_01",
                                        "status": "delivered",
                                        "timestamp": "1731112244",
                                        "recipient_id": "628999999",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }
        raw_bytes = json.dumps(status_payload).encode("utf-8")

        # Missing signature -> rejected
        resp_missing = self.client.post(
            "/api/v1/webhook/waba",
            content=raw_bytes,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp_missing.status_code, 401)
        mock_update.assert_not_called()

        # Invalid signature -> rejected
        resp_invalid = self.client.post(
            "/api/v1/webhook/waba",
            content=raw_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=invalid"},
        )
        self.assertEqual(resp_invalid.status_code, 401)
        mock_update.assert_not_called()

        # Valid signature -> accepted
        valid_sig = compute_meta_webhook_signature(raw_bytes, self.app_secret)
        resp_valid = self.client.post(
            "/api/v1/webhook/waba",
            content=raw_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": valid_sig},
        )
        self.assertEqual(resp_valid.status_code, 200)
        self.assertEqual(resp_valid.json().get("status"), "ok")
        mock_update.assert_called_once()

    # -------------------------------------------------------------------------
    # 11. All route aliases have identical protection
    # -------------------------------------------------------------------------
    def test_11_all_route_aliases_have_identical_protection(self):
        raw_bytes = json.dumps(self._build_sample_payload()).encode("utf-8")
        sig = compute_meta_webhook_signature(raw_bytes, self.app_secret)

        routes = [
            "/webhook/whatsapp",
            "/api/v1/webhook/whatsapp",
            "/api/webhook/whatsapp",
            "/api/v1/whatsapp/webhook",
            "/api/whatsapp/webhook",
        ]

        for route in routes:
            # 1. Without signature -> rejected 401
            resp_no_sig = self.client.post(route, content=raw_bytes, headers={"Content-Type": "application/json"})
            self.assertEqual(
                resp_no_sig.status_code,
                401,
                f"Route {route} did not enforce signature verification (expected 401, got {resp_no_sig.status_code})",
            )

            # 2. With invalid signature -> rejected 401
            resp_bad_sig = self.client.post(
                route,
                content=raw_bytes,
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=bad123"},
            )
            self.assertEqual(
                resp_bad_sig.status_code,
                401,
                f"Route {route} did not reject invalid signature (expected 401, got {resp_bad_sig.status_code})",
            )

    # -------------------------------------------------------------------------
    # 12. Raw verify token, App Secret, and signature do not leak to logs
    # -------------------------------------------------------------------------
    def test_12_raw_credentials_do_not_leak_to_logs(self):
        sensitive_attempt_token = "ultra_sensitive_token_leak_attempt_7788"

        with self.assertLogs("WHATSAPP_WEBHOOK_INGESTION", level="WARNING") as log_cm_warn:
            self.client.get(
                "/webhook/whatsapp",
                params={"hub.mode": "subscribe", "hub.verify_token": sensitive_attempt_token, "hub.challenge": "123"},
            )
            for log_msg in log_cm_warn.output:
                self.assertNotIn(sensitive_attempt_token, log_msg)
                self.assertNotIn(self.app_secret, log_msg)
                self.assertNotIn(self.verify_token, log_msg)

        with self.assertLogs("META_WABA_ROUTES", level="WARNING") as log_cm_waba:
            self.client.get(
                "/api/v1/webhook/waba",
                params={"hub.mode": "subscribe", "hub.verify_token": sensitive_attempt_token, "hub.challenge": "123"},
            )
            for log_msg in log_cm_waba.output:
                self.assertNotIn(sensitive_attempt_token, log_msg)
                self.assertNotIn(self.app_secret, log_msg)
                self.assertNotIn(self.verify_token, log_msg)


if __name__ == "__main__":
    unittest.main()

