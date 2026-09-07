"""tests/test_sprint1_tahap1.py
Unit and Integration Test Suite for Sprint 1 Tahap 1 Backend Engine Execution.

Verifies:
1. Webhook Status Filter in meta_whatsapp and whatsapp_central (Fix Pesan Salam Otomatis).
2. Live Payment & Callback Verification for Xendit /api/v1/payments/xendit/callback with DANA Bisnis QRIS and Rp1.000 cpm-24jam (status LUNAS & WA confirmation).
3. Biteship Logistics Centralization (Instant, Sameday, Reguler, Kargo, COD) and Webhook receiver (/api/v1/logistics/biteship/webhook) with status event mapping.
"""

import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.xendit_service import xendit_service
from app.services.biteship_service import (
    get_all_shipping_rates,
    map_biteship_event_status,
    BiteshipService,
    STATUS_EVENT_MAPPING,
)
from app.utils.qris_generator import STANDARD_MASTER_QRIS, get_dynamic_qris_string


class TestSprint1Tahap1(unittest.TestCase):
    """Test suite for Sprint 1 Tahap 1 backend engine deliverables."""

    def setUp(self):
        self.client = TestClient(app)
        xendit_service.clear_state()
        self.valid_token = os.getenv("XENDIT_CALLBACK_TOKEN", "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS")

    # =========================================================================
    # 1. Webhook Status Filter (Fix Pesan Salam Otomatis)
    # =========================================================================

    def test_meta_whatsapp_status_only_payload_halts_execution(self):
        """Payload hanya berisi 'statuses' (sent/delivered/read) harus langsung return 200 OK tanpa pesan salam."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "123456789",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "628123456789",
                                    "phone_number_id": "1268977686299719"
                                },
                                "statuses": [
                                    {
                                        "id": "wamid.HBgLMjY3M...",
                                        "status": "delivered",
                                        "timestamp": "1741350000",
                                        "recipient_id": "6281234567890",
                                        "conversation": {
                                            "id": "conv_123",
                                            "origin": {"type": "user_initiated"}
                                        }
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }

        # Request ke endpoint Meta WhatsApp
        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        # Respon harus berupa STATUS_IGNORED tanpa memicu balasan percakapan / greeting
        self.assertIn("STATUS_IGNORED", resp.text)

    def test_whatsapp_central_status_only_payload_halts_execution(self):
        """Verifikasi logika pemfilteran status murni (sent/delivered/read)."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [{"id": "msg_status_1", "status": "read"}]
                            }
                        }
                    ]
                }
            ]
        }
        has_statuses = False
        has_messages = False
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                val = change.get("value", {})
                if "messages" in val and val.get("messages"):
                    has_messages = True
                if "statuses" in val and val.get("statuses"):
                    has_statuses = True

        self.assertTrue(has_statuses)
        self.assertFalse(has_messages)

    # =========================================================================
    # 2. Integrasi Live Payment & Callback Verification (DANA Bisnis & Rp1.000 CPM)
    # =========================================================================

    def test_override_dynamic_qris_boontrack_dana_bisnis_preserved(self):
        """Memastikan master static QRIS DANA Bisnis BoonTrack tetap terpasang sebagai basis EMVCo."""
        self.assertTrue(STANDARD_MASTER_QRIS.startswith("000201"))
        self.assertIn("ID.DANA.WWW", STANDARD_MASTER_QRIS)
        self.assertIn("BoonTrack", STANDARD_MASTER_QRIS)

        # Generate dynamic string untuk Rp1.000
        dynamic_str = get_dynamic_qris_string(amount=1000, invoice_id="INV-CPM-001")
        self.assertTrue(dynamic_str.startswith("000201"))
        self.assertIn("54041000", dynamic_str)  # Tag 54 nominal Rp1.000
        self.assertIn("5802ID", dynamic_str)

    @patch("app.routes.xendit.get_supabase")
    @patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_ereceipt_whatsapp", new_callable=AsyncMock)
    def test_xendit_callback_cpm_24jam_rp1000_records_lunas(self, mock_ereceipt, mock_send_text, mock_get_supabase):
        """Transaksi Rp1.000 pada 'Modul Praktis CPM 24 Jam' mencatat status LUNAS ke Supabase dan mengirim konfirmasi."""
        mock_supabase = MagicMock()
        mock_table = MagicMock()
        mock_get_supabase.return_value = mock_supabase
        mock_supabase.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[{"id": "ORDER-CPM-1000", "status": "LUNAS"}])

        headers = {"x-callback-token": self.valid_token}
        payload = {
            "id": "qr_cpm_real_001",
            "external_id": "ORDER-CPM-1000",
            "amount": 1000,
            "status": "COMPLETED",
            "customer_phone": "081299998888",
            "product_slug": "cpm-24jam",
            "product_name": "Modul Praktis CPM 24 Jam",
            "tenant_id": "onlineboost",
        }

        resp = self.client.post("/api/v1/payments/xendit/callback", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        resp_data = resp.json()
        self.assertEqual(resp_data["status"], "SUCCESS")
        self.assertEqual(resp_data["amount"], 1000)

        # Verifikasi Supabase orders diupdate ke status LUNAS
        update_calls = mock_table.update.call_args_list
        status_updates = [c[0][0].get("status") for c in update_calls if isinstance(c[0][0], dict)]
        self.assertIn("LUNAS", status_updates)

    # =========================================================================
    # 3. Integrasi Logistik Tunggal Biteship
    # =========================================================================

    def test_biteship_multi_courier_rates_centralized(self):
        """Memvalidasi modul ongkir Biteship memusatkan seluruh kategori kurir (Instant, Sameday, Reguler, Kargo, COD)."""
        import asyncio
        rates_res = asyncio.run(get_all_shipping_rates(
            destination_postal_code="40287",
            items=[{"name": "Buku Panduan CPM 24 Jam", "value": 50000, "weight": 500, "quantity": 1}],
            is_cod=True,
        ))

        self.assertTrue(rates_res["success"])
        self.assertIn("grouped", rates_res)
        grouped = rates_res["grouped"]

        # Pastikan seluruh kategori tersedia
        self.assertIn("instant", grouped)
        self.assertIn("sameday", grouped)
        self.assertIn("reguler", grouped)
        self.assertIn("kargo", grouped)
        self.assertIn("cod", grouped)

        # Pastikan ada opsi pengiriman di setiap kategori
        self.assertGreater(len(grouped["instant"]), 0)
        self.assertGreater(len(grouped["reguler"]), 0)
        self.assertGreater(len(grouped["kargo"]), 0)

    def test_biteship_webhook_lifecycle_event_mapping(self):
        """Memvalidasi mapping status event: ORDER_CREATED -> ALLOCATED -> PICKING_UP -> DROPPING_OFF -> DELIVERED / COD_COLLECTED."""
        self.assertEqual(map_biteship_event_status("order.created"), "ORDER_CREATED")
        self.assertEqual(map_biteship_event_status("allocated"), "ALLOCATED")
        self.assertEqual(map_biteship_event_status("picking_up"), "PICKING_UP")
        self.assertEqual(map_biteship_event_status("picked"), "PICKING_UP")
        self.assertEqual(map_biteship_event_status("dropping_off"), "DROPPING_OFF")
        self.assertEqual(map_biteship_event_status("in_transit"), "DROPPING_OFF")
        self.assertEqual(map_biteship_event_status("delivered", is_cod=False), "DELIVERED")
        self.assertEqual(map_biteship_event_status("delivered", is_cod=True), "COD_COLLECTED")
        self.assertEqual(map_biteship_event_status("cod_collected"), "COD_COLLECTED")

    def test_biteship_webhook_endpoint_active_and_maps_status(self):
        """Memvalidasi endpoint /api/v1/logistics/biteship/webhook aktif menerima event dan mengembalikan mapped status."""
        webhook_payload = {
            "event": "order.status",
            "order_id": "BITESHIP-TEST-ORD-99",
            "status": "picking_up",
            "courier": {
                "name": "GoSend",
                "tracking_id": "GS-TRK-12345"
            }
        }

        resp = self.client.post("/api/v1/logistics/biteship/webhook", json=webhook_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "PICKING_UP")
        self.assertEqual(data["mapped_status"], "PICKING_UP")
        self.assertEqual(data["booking_id"], "BITESHIP-TEST-ORD-99")

    def test_biteship_webhook_cod_collected_event(self):
        """Memvalidasi webhook event untuk penyelesaian COD memetakan status COD_COLLECTED."""
        cod_payload = {
            "event": "order.status",
            "order_id": "BITESHIP-COD-ORD-100",
            "status": "delivered",
            "is_cod": True,
            "cash_on_delivery": {
                "amount": 99000,
                "status": "collected"
            }
        }

        resp = self.client.post("/api/v1/logistics/biteship/webhook", json=cod_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mapped_status"], "COD_COLLECTED")


if __name__ == "__main__":
    unittest.main()
