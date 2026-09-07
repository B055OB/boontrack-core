"""tests/test_xendit_whatsapp_checkout.py
Verifikasi Pengalihan Sepenuhnya ke Xendit Production untuk WhatsApp Checkout & Webhook Callback:
1. Flow WhatsApp Checkout (whatsapp_service.py / payment_orchestrator.py) memanggil Xendit Service tanpa DANA Bisnis.
2. Mengambil qr_string resmi dari respons API Xendit untuk produk 'cpm-24jam' senilai Rp1.000.
3. Merender QR code ke WhatsApp menggunakan URL/string resmi dari respons Xendit.
4. Webhook Xendit /api/v1/payments/xendit/callback menandai order menjadi LUNAS di database Supabase.
"""

import os
import io
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.xendit_service import xendit_service, XenditService
from app.services.payment_orchestrator import PaymentOrchestrator
from app.services.whatsapp_service import (
    generate_fast_track_checkout_response,
    generate_cart_checkout_response,
)


class TestXenditWhatsAppCheckout(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.valid_token = os.getenv(
            "XENDIT_WEBHOOK_VERIFICATION_TOKEN",
            "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS",
        )
        xendit_service.clear_state()

    async def test_fast_track_checkout_uses_xendit_and_cpm_rp1000(self):
        """Memastikan WhatsApp fast-track checkout mengambil qr_string resmi dari Xendit untuk cpm-24jam senilai Rp1.000."""
        mock_xendit_qr_string = "00020101021226540014ID.LINKAJA.WWW0118936009143000000000520459995303360540410005802ID5911XENDIT_PROD6007JAKARTA6304ABCD"
        mock_xendit_api_resp = {
            "id": "qr_xendit_live_test_01",
            "reference_id": "INV-ONLINEBO-001",
            "type": "DYNAMIC",
            "currency": "IDR",
            "amount": 1000,
            "status": "ACTIVE",
            "qr_string": mock_xendit_qr_string,
        }

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post_resp = MagicMock()
            mock_post_resp.status_code = 201
            mock_post_resp.json.return_value = mock_xendit_api_resp
            mock_post.return_value = mock_post_resp

            caption, invoice, qr_bytes = await generate_fast_track_checkout_response(
                tenant_slug="onlineboost",
                from_phone="081234567890",
                contact_name="Budi",
                product_key="cpm-24jam",
            )

            # 1. Pastikan produk adalah 'Modul Praktis CPM 24 Jam' dan nominal Rp1.000
            self.assertEqual(invoice["amount"], 1000)
            self.assertIn("Modul Praktis CPM 24 Jam", caption)
            self.assertIn("Rp1.000", caption)

            # 2. Pastikan qr_string langsung menggunakan respons resmi Xendit
            self.assertEqual(invoice["qr_string"], mock_xendit_qr_string)
            self.assertIn(mock_xendit_qr_string, caption)

            # 3. Pastikan string DANA Bisnis lokal TIDAK digunakan
            self.assertNotIn("ID.DANA.WWW", invoice["qr_string"])
            self.assertNotIn("ID.DANA.WWW", caption)

            # 4. Pastikan gambar QR code PNG berhasil dirender dari string Xendit
            self.assertGreater(len(qr_bytes), 100)
            self.assertTrue(qr_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    async def test_payment_orchestrator_create_qr_code_delegation(self):
        """Memastikan PaymentOrchestrator.create_qr_code mendelegasikan ke Xendit Service tanpa DANA Bisnis."""
        mock_supabase = MagicMock()
        orchestrator = PaymentOrchestrator(supabase_client=mock_supabase)

        with patch.object(xendit_service, "create_qr_code", new_callable=AsyncMock) as mock_create_qr:
            mock_create_qr.return_value = {
                "qr_string": "xendit_official_qr_code_sample",
                "qr_code_url": "https://api.qrserver.com/v1/create-qr-code/?data=sample",
                "amount": 1000,
                "status": "ACTIVE",
                "external_id": "ORD-CPM-99",
            }

            res = await orchestrator.create_qr_code(
                external_id="ORD-CPM-99",
                amount=1000,
                tenant_id="onlineboost",
                customer_phone="081299990000",
                product_name="Modul Praktis CPM 24 Jam",
            )

            mock_create_qr.assert_called_once()
            self.assertEqual(res["amount"], 1000)
            self.assertEqual(res["qr_string"], "xendit_official_qr_code_sample")
            self.assertNotIn("ID.DANA.WWW", res["qr_string"])

    async def test_payment_orchestrator_webhook_marks_lunas(self):
        """Memastikan PaymentOrchestrator.process_xendit_webhook menandai order menjadi LUNAS di database."""
        mock_supabase = MagicMock()
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.update.return_value = mock_table
        # select orders returns existing pending order
        mock_table.execute.side_effect = [
            MagicMock(data=[]),  # 1. payment_events check
            MagicMock(data=[]),  # 2. payment_events insert
            MagicMock(data=[{"id": "ORD-TEST-LUNAS-1", "status": "PENDING"}]),  # 3. orders select
            MagicMock(data=[{"id": "ORD-TEST-LUNAS-1", "status": "LUNAS"}]),  # 4. orders update
            MagicMock(data=[]),  # 5. payment_events update PROCESSED
        ]

        orchestrator = PaymentOrchestrator(supabase_client=mock_supabase)
        payload = {
            "id": "qr_settlement_001",
            "external_id": "ORD-TEST-LUNAS-1",
            "status": "COMPLETED",
            "amount": 1000,
        }

        res = await orchestrator.process_xendit_webhook(payload)
        self.assertEqual(res["status"], "success")

        # Verifikasi update dipanggil dengan status LUNAS
        update_calls = mock_table.update.call_args_list
        statuses_updated = [c[0][0].get("status") for c in update_calls if isinstance(c[0][0], dict)]
        self.assertIn("LUNAS", statuses_updated)

    def test_api_v1_payments_xendit_callback_marks_lunas_cpm24jam(self):
        """Memvalidasi endpoint /api/v1/payments/xendit/callback merespons 200 OK dan mencatat LUNAS."""
        with patch("app.routes.xendit.get_supabase") as mock_get_sb, \
             patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock) as mock_wa:
            mock_sb = MagicMock()
            mock_tbl = MagicMock()
            mock_get_sb.return_value = mock_sb
            mock_sb.table.return_value = mock_tbl
            mock_tbl.update.return_value = mock_tbl
            mock_tbl.upsert.return_value = mock_tbl
            mock_tbl.insert.return_value = mock_tbl
            mock_tbl.eq.return_value = mock_tbl
            mock_tbl.execute.return_value = MagicMock(data=[{"id": "INV-CPM-XENDIT-01", "status": "LUNAS"}])

            headers = {"x-callback-token": self.valid_token}
            payload = {
                "event": "qr.payment",
                "data": {
                    "id": "qrpy_cpm_live_123",
                    "qr_id": "qr_cpm_live_123",
                    "amount": 1000,
                    "status": "COMPLETED",
                    "reference_id": "INV-CPM-XENDIT-01",
                    "customer_phone": "081211112222",
                    "product_name": "Modul Praktis CPM 24 Jam",
                }
            }

            resp = self.client.post("/api/v1/payments/xendit/callback", json=payload, headers=headers)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["status"], "SUCCESS")
            self.assertEqual(resp.json()["amount"], 1000)

            # Pastikan status LUNAS dicatat
            update_calls = mock_tbl.update.call_args_list
            statuses = [c[0][0].get("status") for c in update_calls if isinstance(c[0][0], dict)]
            self.assertIn("LUNAS", statuses)
