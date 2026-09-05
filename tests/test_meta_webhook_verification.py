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

    def test_verify_webhook_success_default_token(self):
        """Verifikasi berhasil dengan token default boontrack_verify_secret."""
        resp = self.client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "boontrack_verify_secret",
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
                "token": "boontrack_verify_secret",
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
                "hub.verify_token": "boontrack_verify_secret",
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
                "hub.verify_token": "boontrack_verify_secret",
                "hub.challenge": "778899",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "778899")


if __name__ == "__main__":
    unittest.main()
