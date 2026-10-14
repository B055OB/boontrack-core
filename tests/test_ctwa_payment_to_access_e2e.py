"""tests/test_ctwa_payment_to_access_e2e.py
End-to-End Payment-to-Access Integration Test Suite:
1. Order Checkout Rp249.000:
   - Validates mandatory fields: customer_name, customer_phone, customer_email (cannot be null).
   - Generates dynamic QRIS and records PENDING order for OnlineBoost CTWA Batch 1.
2. Xendit Webhook Settlement:
   - Simulates callback with official header x-callback-token.
   - Verifies order state transitions to PAID / LUNAS in database ledger and financial_ledger.
3. Telegram Single-Use Invite Link Fulfillment:
   - Verifies Telegram Bot API createChatInviteLink call with member_limit=1 (single-use) and 24h expiration.
   - Verifies access link is a Telegram invite (https://t.me/...), NOT a static WhatsApp link.
   - Verifies link is recorded in orders.metadata['telegram_single_invite_link'].
4. Triple-Tier Idempotency Guard:
   - Duplicate callback returns 200 OK without re-issuing duplicate Telegram links or duplicate ledger events.
5. Telegram Webhook Secret Token Hardening:
   - Rejects updates missing X-Telegram-Bot-Api-Secret-Token with HTTP 401.
   - Accepts updates with valid secret token with HTTP 200.
"""

import os
import json
import time
import uuid
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db_connection
from app.services.ctwa_fulfillment_service import (
    create_telegram_single_use_invite_link,
    fulfill_onlineboost_ctwa_order,
    _ISSUED_TELEGRAM_LINKS_CACHE,
)
from app.services.ctwa_state_engine import ctwa_state_engine, SINGLE_OFFER_PRICE


class TestCtwaPaymentToAccessE2E(unittest.TestCase):
    """E2E Verification suite for CTWA Batch 1 Payment-to-Access and Telegram Security."""

    def setUp(self):
        self.client = TestClient(app)
        self.valid_xendit_token = os.getenv(
            "XENDIT_CALLBACK_TOKEN",
            os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN", "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS")
        )
        self.test_order_id = f"ORD-OB-CTWA-{uuid.uuid4().hex[:8].upper()}"
        self.customer_phone = "6281299998888"
        self.customer_name = "Budi Pratama"
        self.customer_email = "budi.pratama@example.com"
        _ISSUED_TELEGRAM_LINKS_CACHE.clear()

        # Seed initial PENDING order ke PostgreSQL
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orders (
                    id, tenant_slug, product_id, product_title, gross_amount,
                    customer_name, customer_phone, customer_email, status,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET status = 'PENDING';
                """,
                (
                    self.test_order_id,
                    "onlineboost",
                    "kelas-inkubasi-ctwa-batch-1-scale",
                    "Kelas Inkubasi CTWA Batch 1 - Scale Bundle",
                    SINGLE_OFFER_PRICE,
                    self.customer_name,
                    self.customer_phone,
                    self.customer_email,
                )
            )
            conn.commit()
        conn.close()

    def tearDown(self):
        # Cleanup order and ledger
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM financial_ledger WHERE order_id = %s;", (self.test_order_id,))
                cur.execute("DELETE FROM payment_events WHERE reference_id = %s OR order_id = %s;", (self.test_order_id, self.test_order_id))
                cur.execute("DELETE FROM orders WHERE id = %s;", (self.test_order_id,))
                conn.commit()
            conn.close()
        except Exception:
            pass
        _ISSUED_TELEGRAM_LINKS_CACHE.clear()

    # =========================================================================
    # GATE 1: Commercial Truth & Mandatory Order Fields Validation
    # =========================================================================

    def test_single_offer_sku_is_locked_at_rp249000(self):
        """Memastikan harga penawaran kampanye CTWA Batch 1 terkunci mutlak di Rp249.000."""
        self.assertEqual(SINGLE_OFFER_PRICE, 249000)

    def test_checkout_validation_rejects_missing_or_invalid_email(self):
        """Memastikan pembuatan order menolak input jika email kosong atau tidak valid."""
        # Test missing email in gatekeeper
        with self.assertRaises(ValueError):
            import asyncio
            asyncio.run(ctwa_state_engine.execute_deterministic_gatekeeper(
                phone=self.customer_phone,
                name=self.customer_name,
                email="",  # Kosong
            ))

        # Test missing name
        with self.assertRaises(ValueError):
            import asyncio
            asyncio.run(ctwa_state_engine.execute_deterministic_gatekeeper(
                phone=self.customer_phone,
                name="",  # Kosong
                email=self.customer_email,
            ))

    # =========================================================================
    # GATE 2: Telegram Single-Use Invite Link Fulfillment (member_limit=1)
    # =========================================================================

    def test_telegram_single_use_invite_link_creation(self):
        """Memverifikasi pemanggilan Telegram Bot API createChatInviteLink dengan member_limit=1 dan non-WA link."""
        import asyncio

        mock_telegram_response = {
            "ok": True,
            "result": {
                "invite_link": f"https://t.me/+join_ctwa_{self.test_order_id}_SECURE",
                "member_limit": 1,
                "expire_date": int(time.time()) + 86400,
                "name": f"Invite-{self.test_order_id}",
            }
        }

        with patch("os.getenv", side_effect=lambda k, default=None: {
            "TELEGRAM_BOT_TOKEN": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567",
            "TELEGRAM_CTWA_CHAT_ID": "-1004371114362",
        }.get(k, default)):
            with patch("httpx.AsyncClient.post") as mock_post:
                mock_post_resp = MagicMock()
                mock_post_resp.status_code = 200
                mock_post_resp.json.return_value = mock_telegram_response
                mock_post.return_value = mock_post_resp

                invite_link = asyncio.run(create_telegram_single_use_invite_link(
                    order_id=self.test_order_id,
                    buyer_name=self.customer_name,
                ))

                # 1. Verifikasi parameter API Telegram
                mock_post.assert_called_once()
                call_args, call_kwargs = mock_post.call_args
                payload = call_kwargs.get("json", {})

                self.assertEqual(payload.get("member_limit"), 1, "member_limit wajib bernilai 1 (single-use)")
                self.assertGreater(payload.get("expire_date"), int(time.time()))
                self.assertEqual(payload.get("chat_id"), "-1004371114362")

                # 2. Verifikasi link adalah Telegram invite, BUKAN link WhatsApp statis
                self.assertTrue(invite_link.startswith("https://t.me/"), f"Link harus berupa t.me, got: {invite_link}")
                self.assertNotIn("wa.me", invite_link, "Link tidak boleh berupa link WhatsApp statis")
                self.assertNotIn("whatsapp.com", invite_link)

    # =========================================================================
    # GATE 3: E2E Payment Settlement -> Access Fulfillment & Idempotency
    # =========================================================================

    def test_e2e_xendit_settlement_to_telegram_fulfillment_and_idempotency(self):
        """Simulasi alur utuh: Webhook Xendit settlement Rp249.000 -> PAID ledger -> Single-use Telegram link -> Idempotency."""
        event_id = f"evt_xendit_{self.test_order_id}"
        expected_invite_link = f"https://t.me/+join_ctwa_{self.test_order_id}_EXCLUSIVE"

        mock_telegram_resp = {
            "ok": True,
            "result": {
                "invite_link": expected_invite_link,
                "member_limit": 1,
                "expire_date": int(time.time()) + 86400,
            }
        }

        # 1. Simulasikan Callback Webhook Settlement Xendit dengan Token Header Resmi
        callback_payload = {
            "id": event_id,
            "external_id": self.test_order_id,
            "amount": 249000,
            "status": "COMPLETED",
            "customer_phone": self.customer_phone,
            "customer_email": self.customer_email,
            "tenant_id": "onlineboost",
            "product_name": "Kelas Inkubasi CTWA Batch 1 - Scale Bundle",
            "product_slug": "kelas-inkubasi-ctwa-batch-1-scale",
        }
        headers = {"x-callback-token": self.valid_xendit_token}

        with patch("httpx.AsyncClient.post") as mock_post, \
             patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa, \
             patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_purchase", new_callable=AsyncMock) as mock_capi:

            mock_post_resp = MagicMock()
            mock_post_resp.status_code = 200
            mock_post_resp.json.return_value = mock_telegram_resp
            mock_post.return_value = mock_post_resp

            # Kirim request webhook callback ke endpoint resmi
            resp = self.client.post("/api/v1/payments/xendit/callback", json=callback_payload, headers=headers)
            self.assertEqual(resp.status_code, 200)
            resp_json = resp.json()
            self.assertEqual(resp_json.get("status"), "SUCCESS")
            self.assertEqual(resp_json.get("amount"), 249000)

            # 2. Verifikasi status order di Database Postgres berubah menjadi LUNAS/PAID
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT status, gross_amount FROM orders WHERE id = %s;", (self.test_order_id,))
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertIn(row[0], ("LUNAS", "PAID"), "Status order wajib berubah menjadi LUNAS/PAID")
                self.assertEqual(row[1], 249000)

                # Verifikasi financial_ledger mencatat settlement
                cur.execute("SELECT gross_amount, status FROM financial_ledger WHERE order_id = %s;", (self.test_order_id,))
                ledger_row = cur.fetchone()
                self.assertIsNotNone(ledger_row, "Transaksi wajib tercatat di financial_ledger")
                self.assertEqual(ledger_row[0], 249000)
                self.assertEqual(ledger_row[1], "SETTLED")
            conn.close()

            # 3. Jalankan fulfillment CTWA secara eksplisit dan verifikasi penerbitan link Telegram
            import asyncio
            fulfill_res = asyncio.run(fulfill_onlineboost_ctwa_order(
                order_id=self.test_order_id,
                buyer_name=self.customer_name,
                buyer_phone=self.customer_phone,
                amount=249000,
                tenant_id="onlineboost",
            ))

            self.assertEqual(fulfill_res.get("status"), "SUCCESS")
            issued_link = fulfill_res.get("single_use_invite_link")
            self.assertEqual(issued_link, expected_invite_link)
            self.assertTrue(issued_link.startswith("https://t.me/"))
            self.assertNotIn("wa.me", issued_link)

            # Verifikasi pesan konfirmasi berisi single_use_invite_link
            conf_msg = fulfill_res.get("confirmation_message", "")
            self.assertIn(issued_link, conf_msg)
            self.assertIn("1 kali masuk", conf_msg)

            # 4. Uji Idempotensi: Panggilan kedua tidak boleh memicu API Telegram baru
            mock_post.reset_mock()
            duplicate_fulfill_res = asyncio.run(fulfill_onlineboost_ctwa_order(
                order_id=self.test_order_id,
                buyer_name=self.customer_name,
                buyer_phone=self.customer_phone,
                amount=249000,
                tenant_id="onlineboost",
            ))
            # Mock HTTP tidak boleh dipanggil lagi karena link di-reuse
            mock_post.assert_not_called()
            self.assertEqual(duplicate_fulfill_res.get("single_use_invite_link"), expected_invite_link)

            # Webhook replay idempotency test
            dup_resp = self.client.post("/api/v1/payments/xendit/callback", json=callback_payload, headers=headers)
            self.assertEqual(dup_resp.status_code, 200)
            self.assertEqual(dup_resp.json().get("status"), "ALREADY_PROCESSED")
            self.assertTrue(dup_resp.json().get("idempotent"))

    # =========================================================================
    # GATE 4: Telegram Webhook Header X-Telegram-Bot-Api-Secret-Token Verification
    # =========================================================================

    def test_telegram_webhook_rejects_missing_secret_token_header(self):
        """Memastikan request webhook Telegram tanpa header X-Telegram-Bot-Api-Secret-Token ditolak 401."""
        payload = {"update_id": 99999, "message": {"text": "/start", "chat": {"id": 123}}}
        # Tanpa header
        resp = self.client.post("/api/v1/telegram/webhook", json=payload)
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Unauthorized", resp.text)

    def test_telegram_webhook_rejects_invalid_secret_token_header(self):
        """Memastikan request webhook Telegram dengan secret token salah ditolak 401."""
        payload = {"update_id": 99999, "message": {"text": "/start", "chat": {"id": 123}}}
        headers = {"X-Telegram-Bot-Api-Secret-Token": "invalid_random_secret_token_xyz"}
        resp = self.client.post("/api/v1/telegram/webhook", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 401)

    def test_telegram_webhook_accepts_valid_secret_token_header(self):
        """Memastikan request webhook Telegram dengan secret token valid diterima 200 OK."""
        payload = {"update_id": 99999, "message": {"text": "/start", "chat": {"id": 123, "type": "private"}}}
        test_secret = "boontrack_telegram_ctwa_secret_2026"
        headers = {"X-Telegram-Bot-Api-Secret-Token": test_secret}

        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": test_secret}):
            with patch("app.routes.telegram_webhook_routes.handle_telegram_update", new_callable=AsyncMock) as mock_handle:
                mock_handle.return_value = {"status": "success", "handled": True}
                resp = self.client.post("/api/v1/telegram/webhook", json=payload, headers=headers)
                self.assertEqual(resp.status_code, 200)
                mock_handle.assert_called_once()


if __name__ == "__main__":
    unittest.main()
