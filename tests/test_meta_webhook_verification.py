"""tests/test_meta_webhook_verification.py
Unit & Integration tests for Meta WhatsApp GET /webhook/whatsapp endpoint.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app


class TestMetaWebhookVerification(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.deterministic_token = "test_meta_verify_secret_deterministic"
        self.env_patcher = patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": self.deterministic_token})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_verify_webhook_success_default_token(self):
        """Verifikasi berhasil dengan token yang diset secara deterministik di environment."""
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": self.deterministic_token,
                "hub.challenge": "1122334455",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "1122334455")
        self.assertIn("text/plain", resp.headers["content-type"])

    def test_verify_webhook_success_env_token(self):
        """Verifikasi berhasil saat WHATSAPP_VERIFY_TOKEN diset di environment."""
        with patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "custom_meta_token_123"}):
            resp = self.client.get(
                "/webhook/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "custom_meta_token_123",
                    "hub.challenge": "99887766",
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.text, "99887766")

    def test_verify_webhook_success_without_hub_prefix(self):
        """Verifikasi query params fleksibel (mode, token, challenge)."""
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "mode": "subscribe",
                "token": self.deterministic_token,
                "challenge": "55443322",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "55443322")

    def test_verify_webhook_token_mismatch(self):
        """Token salah mengembalikan 403 Forbidden."""
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "invalid_wrong_token",
                "hub.challenge": "1122334455",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Verification token mismatch", resp.text)

    def test_verify_webhook_invalid_mode(self):
        """Mode selain 'subscribe' mengembalikan 403 Forbidden."""
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": self.deterministic_token,
                "hub.challenge": "1122334455",
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_verify_webhook_alias_endpoint(self):
        """Memastikan endpoint alias /api/v1/whatsapp/webhook juga bekerja."""
        resp = self.client.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": self.deterministic_token,
                "hub.challenge": "778899",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "778899")

    def test_verify_webhook_missing_configuration_fails_closed(self):
        """Memastikan jika tidak ada token terkonfigurasi di environment, handshake gagal (403 fail-closed)."""
        # Bersihkan seluruh token kandidat dari env
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
                    "hub.verify_token": "any_attempted_token",
                    "hub.challenge": "12345",
                },
            )
            self.assertEqual(resp.status_code, 403)
            self.assertIn("Verification token mismatch", resp.text)


if __name__ == "__main__":
    unittest.main()
