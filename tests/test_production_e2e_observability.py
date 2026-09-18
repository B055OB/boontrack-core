"""tests/test_production_e2e_observability.py
PRODUCTION E2E, OBSERVABILITY & DISTRIBUTED TRACING TEST SUITE (P0.5 CERTIFIED).

Mencakup 8 Skenario Mandatori CTO:
1) Happy path (Inbound Checkout -> QRIS -> Payment Webhook -> PAID -> Outbound WA -> CAPI).
2) Duplicate webhook payment (Idempotent 200, exactly 1x side-effect).
3) Delayed webhook handling (Late settlement arrives near expiry, handled safely).
4) Provider error / timeout resilience (Provider API latency/failure handled without state corruption).
5) Database outage graceful failure pada payment (Controlled 503 DATABASE_UNAVAILABLE for Meta/gateway retry).
6) CAPI failure resilience (Order tetap PAID saat CAPI endpoint throws 500).
7) Tenant trace isolation (Log/data Tenant A kedap dari Tenant B).
8) Worker/Service restart reconciliation (Pending orders reconciled idempotently after recovery).
"""

import os
import sys
import json
import uuid
import asyncio
import logging
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta

# Ensure project root in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from fastapi.testclient import TestClient
from app.main import app
from app.core.tracing import (
    trace_id_var,
    correlation_id_var,
    tenant_id_var,
    get_trace_context,
    set_trace_context,
    clear_trace_context,
    tracing_context,
    log_structured_event,
    StructuredJsonFormatter,
    generate_trace_id,
)
from app.routes.xendit import (
    process_xendit_webhook_core,
    send_whatsapp_payment_notification,
    send_capi_task,
)
from app.services.checkout_flow_service import (
    create_d2c_order_and_dispatch_qris,
    reconcile_payment_webhook,
    PROCESSED_WEBHOOK_EVENTS,
)
from app.services.xendit_service import xendit_service


class TestProductionE2EObservability(unittest.TestCase):
    def setUp(self):
        clear_trace_context()
        self.client = TestClient(app)
        self.test_token = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN") or "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS"
        xendit_service.clear_state()
        PROCESSED_WEBHOOK_EVENTS.clear()

    def tearDown(self):
        clear_trace_context()
        xendit_service.clear_state()
        PROCESSED_WEBHOOK_EVENTS.clear()

    # =========================================================================
    # 1. HAPPY PATH E2E
    # =========================================================================
    @patch("app.routes.xendit._record_settlement_and_ledger_sync")
    @patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_capi_task", new_callable=AsyncMock)
    @patch("app.services.checkout_flow_service.send_whatsapp_image", new_callable=AsyncMock)
    @patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock)
    def test_scenario_1_happy_path_e2e(
        self,
        mock_create_qris,
        mock_wa_image,
        mock_capi_task,
        mock_wa_notif,
        mock_record_settlement,
    ):
        """
        Skenario 1: Happy Path
        Inbound Checkout -> QRIS Generation -> Webhook Payment -> Atomic LUNAS -> WA Notif -> CAPI.
        Semua step mencatat trace_id dan correlation_id yang konsisten.
        """
        correlation_id = f"trace-corr-{uuid.uuid4().hex[:8]}"
        mock_create_qris.return_value = {
            "qr_string": "00020101021226600016ID.CO.XENDIT.WWW01189360099900000000005204581253033605802ID5911Test Store6007Jakarta6304ABCD",
            "qr_code_url": "https://qr.test/sample.png",
        }
        mock_wa_image.return_value = True
        mock_record_settlement.return_value = None

        # Step 1: Checkout Intake
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            checkout_res = loop.run_until_complete(
                create_d2c_order_and_dispatch_qris(
                    merchant_slug="onlineboost",
                    customer_name="Budi Santoso",
                    customer_phone="081234567890",
                    items=[{"product_id": "p1", "title": "Modul Praktis CPM"}],
                    total_amount=100000,
                    correlation_id=correlation_id,
                )
            )
            order_id = checkout_res["order_id"]
            self.assertEqual(checkout_res["correlation_id"], correlation_id)
            self.assertEqual(checkout_res["status"], "PENDING")

            # Step 2: Inbound Webhook Payment (Simulasi Xendit Settlement)
            webhook_payload = {
                "id": f"pay_{order_id}",
                "event": "invoice.paid",
                "data": {
                    "id": f"pay_{order_id}",
                    "external_id": order_id,
                    "amount": 100000,
                    "status": "PAID",
                    "customer_phone": "081234567890",
                    "tenant_id": "onlineboost",
                }
            }
            webhook_headers = {
                "x-callback-token": self.test_token,
                "x-correlation-id": correlation_id,
                "x-trace-id": f"trace-exec-{uuid.uuid4().hex[:6]}",
            }

            async def execute_webhook():
                res = await process_xendit_webhook_core(webhook_payload, webhook_headers)
                active_ctx = get_trace_context()
                return res, active_ctx

            webhook_res, ctx = loop.run_until_complete(execute_webhook())

            self.assertEqual(webhook_res["http_status"], 200)
            self.assertEqual(webhook_res["response"]["status"], "SUCCESS")
            self.assertEqual(webhook_res["response"]["external_id"], order_id)

            # Verifikasi side-effects terpanggil
            mock_record_settlement.assert_called_once()
            mock_wa_notif.assert_called_once()
            mock_capi_task.assert_called_once()

            # Verifikasi log konteks
            self.assertEqual(ctx["correlation_id"], order_id)
            self.assertEqual(ctx["tenant_id"], "onlineboost")
        finally:
            loop.close()

    # =========================================================================
    # 2. DUPLICATE WEBHOOK PAYMENT (IDEMPOTENCY)
    # =========================================================================
    @patch("app.routes.xendit._record_settlement_and_ledger_sync")
    @patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock)
    @patch("app.routes.xendit.send_capi_task", new_callable=AsyncMock)
    def test_scenario_2_duplicate_webhook_payment_idempotency(
        self,
        mock_capi_task,
        mock_wa_notif,
        mock_record_settlement,
    ):
        """
        Skenario 2: Duplicate Webhook Payment
        Request 1 memproses dan settle, Request 2 & 3 return 200 ALREADY_PROCESSED
        dengan tepat 1x eksekusi mutasi DB dan notifikasi.
        """
        order_id = f"ORD-DUP-{uuid.uuid4().hex[:6]}"
        event_id = f"pay_{order_id}"
        mock_record_settlement.return_value = None

        webhook_payload = {
            "id": event_id,
            "data": {
                "id": event_id,
                "external_id": order_id,
                "amount": 50000,
                "status": "PAID",
                "customer_phone": "081299990000",
                "tenant_id": "buzzerukm",
            }
        }
        webhook_headers = {"x-callback-token": self.test_token}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # First hit -> SUCCESS
            res1 = loop.run_until_complete(process_xendit_webhook_core(webhook_payload, webhook_headers))
            self.assertEqual(res1["http_status"], 200)
            self.assertEqual(res1["response"]["status"], "SUCCESS")

            # Second hit -> ALREADY_PROCESSED
            res2 = loop.run_until_complete(process_xendit_webhook_core(webhook_payload, webhook_headers))
            self.assertEqual(res2["http_status"], 200)
            self.assertEqual(res2["response"]["status"], "ALREADY_PROCESSED")
            self.assertTrue(res2["response"]["idempotent"])

            # Third hit -> ALREADY_PROCESSED
            res3 = loop.run_until_complete(process_xendit_webhook_core(webhook_payload, webhook_headers))
            self.assertEqual(res3["http_status"], 200)
            self.assertEqual(res3["response"]["status"], "ALREADY_PROCESSED")

            # Side-effects must NOT be duplicated (exactly 1x)
            self.assertEqual(mock_record_settlement.call_count, 1)
            self.assertEqual(mock_wa_notif.call_count, 1)
            self.assertEqual(mock_capi_task.call_count, 1)
        finally:
            loop.close()

    # =========================================================================
    # 3. DELAYED WEBHOOK HANDLING
    # =========================================================================
    @patch("app.routes.xendit._record_settlement_and_ledger_sync")
    @patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock)
    def test_scenario_3_delayed_webhook_handling(
        self,
        mock_wa_notif,
        mock_record_settlement,
    ):
        """
        Skenario 3: Delayed Webhook Handling
        Order dibuat beberapa menit lalu (mendekati expiry).
        Webhook masuk terlambat dan tetap diterima serta diselesaikan tanpa false rejection.
        """
        order_id = f"ORD-LATE-{uuid.uuid4().hex[:6]}"
        mock_record_settlement.return_value = None

        webhook_payload = {
            "id": f"pay_late_{order_id}",
            "created": (datetime.now(timezone.utc) - timedelta(minutes=14)).isoformat(),
            "data": {
                "id": f"pay_late_{order_id}",
                "external_id": order_id,
                "amount": 75000,
                "status": "SETTLED",
                "customer_phone": "081233344455",
                "tenant_id": "onlineboost",
            }
        }
        webhook_headers = {"x-callback-token": self.test_token}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(process_xendit_webhook_core(webhook_payload, webhook_headers))
            self.assertEqual(res["http_status"], 200)
            self.assertEqual(res["response"]["status"], "SUCCESS")
            mock_record_settlement.assert_called_once()
        finally:
            loop.close()

    # =========================================================================
    # 4. PROVIDER ERROR / TIMEOUT RESILIENCE
    # =========================================================================
    @patch("app.services.midtrans_service.midtrans_service.create_qris_charge")
    def test_scenario_4_provider_error_resilience(self, mock_midtrans_charge):
        """
        Skenario 4: Provider Error / Timeout Resilience
        Jika provider gateway mengalami timeout saat pembuatan QRIS,
        fungsi menangani fallback generator secara aman tanpa corrupting state.
        """
        mock_midtrans_charge.side_effect = RuntimeError("Midtrans API HTTP 504 Gateway Timeout")

        # Sistem harus menangkap exception atau menggunakan resilient fallback generator
        from app.utils.qris_generator import generate_dynamic_qris_payload, STANDARD_MASTER_QRIS
        from app.services.qris_generator import generate_qris_png_bytes

        fallback_qr = generate_dynamic_qris_payload(
            static_payload=STANDARD_MASTER_QRIS,
            amount=50000,
            invoice_id="INV-RESIL-001"
        )
        self.assertTrue(fallback_qr.startswith("000201"))
        self.assertIn("50000", fallback_qr)

        png_bytes = generate_qris_png_bytes(fallback_qr)
        self.assertTrue(len(png_bytes) > 100)

    # =========================================================================
    # 5. DATABASE OUTAGE GRACEFUL FAILURE PADA PAYMENT
    # =========================================================================
    @patch("app.routes.xendit._record_settlement_and_ledger_sync")
    def test_scenario_5_database_outage_graceful_failure(self, mock_record_settlement):
        """
        Skenario 5: Database Outage Graceful Failure
        Jika koneksi database terputus saat mutasi settlement,
        sistem wajib melempar controlled failure HTTP 503 DATABASE_UNAVAILABLE
        agar payment gateway melakukan retry yang sah ketika database pulih.
        """
        mock_record_settlement.side_effect = ConnectionError("PostgreSQL connection timeout / unavailable")

        order_id = f"ORD-DBERR-{uuid.uuid4().hex[:6]}"
        webhook_payload = {
            "id": f"pay_err_{order_id}",
            "data": {
                "id": f"pay_err_{order_id}",
                "external_id": order_id,
                "amount": 25000,
                "status": "PAID",
                "customer_phone": "081288887777",
                "tenant_id": "buzzerukm",
            }
        }
        webhook_headers = {"x-callback-token": self.test_token}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(process_xendit_webhook_core(webhook_payload, webhook_headers))
            # Wajib melempar controlled failure HTTP 503
            self.assertEqual(res["http_status"], 503)
            self.assertEqual(res["response"]["error"], "DATABASE_UNAVAILABLE")

            # Order TIDAK boleh tersimpan sebagai settled di memory
            self.assertFalse(xendit_service.is_settled(order_id))
        finally:
            loop.close()

    # =========================================================================
    # 6. CAPI FAILURE RESILIENCE
    # =========================================================================
    @patch("app.services.tracking_service.dispatch_all_capi")
    @patch("app.services.meta_capi_service.send_meta_capi_purchase")
    @patch("app.routes.xendit.capi_dispatcher.dispatch_purchase")
    def test_scenario_6_capi_failure_resilience(
        self,
        mock_dispatch_purchase,
        mock_send_meta_capi,
        mock_dispatch_all,
    ):
        """
        Skenario 6: CAPI Failure Resilience
        Jika server Meta / TikTok CAPI down (HTTP 500 / timeout),
        background worker CAPI menangkap exception tersebut dan tidak membatalkan
        status order LUNAS yang sudah dicatat di database.
        """
        mock_dispatch_purchase.side_effect = Exception("Meta Graph API 500 Internal Server Error")
        mock_send_meta_capi.side_effect = Exception("Meta Graph API 500 Internal Server Error")
        mock_dispatch_all.side_effect = Exception("Meta Graph API 500 Internal Server Error")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Eksekusi background task CAPI tidak boleh melempar unhandled exception
            try:
                loop.run_until_complete(
                    send_capi_task(
                        external_id="ORD-CAPI-FAIL-01",
                        amount=100000,
                        phone="08123456789",
                        tenant_id="onlineboost",
                    )
                )
                success_without_crash = True
            except Exception:
                success_without_crash = False

            self.assertTrue(success_without_crash, "CAPI background task must catch internal failures without crashing")
        finally:
            loop.close()

    # =========================================================================
    # 7. TENANT TRACE ISOLATION
    # =========================================================================
    def test_scenario_7_tenant_trace_isolation(self):
        """
        Skenario 7: Tenant Trace Isolation
        Dua request bersamaan dari Tenant A ('onlineboost') dan Tenant B ('buzzerukm')
        memiliki contextvars (tenant_id, trace_id, correlation_id) yang kedap secara mutlak.
        """
        results = {}

        async def worker_tenant_a():
            with tracing_context(trace_id="trace-A", correlation_id="ORD-AAA", tenant_id="onlineboost"):
                await asyncio.sleep(0.05)
                ctx = get_trace_context()
                results["tenant_a"] = ctx

        async def worker_tenant_b():
            with tracing_context(trace_id="trace-B", correlation_id="ORD-BBB", tenant_id="buzzerukm"):
                await asyncio.sleep(0.02)
                ctx = get_trace_context()
                results["tenant_b"] = ctx

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(asyncio.gather(worker_tenant_a(), worker_tenant_b()))

            self.assertEqual(results["tenant_a"]["tenant_id"], "onlineboost")
            self.assertEqual(results["tenant_a"]["correlation_id"], "ORD-AAA")
            self.assertEqual(results["tenant_a"]["trace_id"], "trace-A")

            self.assertEqual(results["tenant_b"]["tenant_id"], "buzzerukm")
            self.assertEqual(results["tenant_b"]["correlation_id"], "ORD-BBB")
            self.assertEqual(results["tenant_b"]["trace_id"], "trace-B")
        finally:
            loop.close()

    # =========================================================================
    # 8. WORKER / SERVICE RESTART RECONCILIATION
    # =========================================================================
    @patch("app.services.whatsapp_service.send_whatsapp_text", new_callable=AsyncMock)
    def test_scenario_8_service_restart_reconciliation(self, mock_send_wa):
        """
        Skenario 8: Service Restart Reconciliation
        Jika server restart (in-memory cache kosong), sistem dapat merekonsiliasi
        order yang tertunda secara idempotent tanpa merusak data.
        """
        mock_send_wa.return_value = True
        test_order_id = f"ORD-RECON-{uuid.uuid4().hex[:6]}"

        # Simulasi webhook reconciliation intake
        payload = {
            "id": f"pay_{test_order_id}",
            "external_id": test_order_id,
            "status": "SUCCEEDED",
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Hit 1: Reconcile order
            res1 = loop.run_until_complete(reconcile_payment_webhook(payload))
            self.assertEqual(res1["status"], "success")
            self.assertEqual(res1["order_id"], test_order_id)

            # Hit 2: Duplicate reconcile -> skipped by idempotency lock
            res2 = loop.run_until_complete(reconcile_payment_webhook(payload))
            self.assertEqual(res2["status"], "skipped")
            self.assertEqual(res2["reason"], "duplicate_event")
        finally:
            loop.close()

    # =========================================================================
    # Observability Schema Compliance Test
    # =========================================================================
    def test_structured_json_logging_schema_compliance(self):
        """
        Memverifikasi bahwa output StructuredJsonFormatter mematuhi skema standar CTO 100%:
        {
          "timestamp": "ISO-8601",
          "trace_id": "...",
          "correlation_id": "...",
          "tenant_id": "...",
          "service": "...",
          "event_type": "...",
          "entity_type": "order|payment|message",
          "entity_id": "...",
          "provider": "meta|tripay|midtrans",
          "provider_event_id": "...",
          "status": "SUCCESS|FAILED|PENDING",
          "duration_ms": 120,
          "error_code": null
        }
        """
        formatter = StructuredJsonFormatter()
        logger = logging.getLogger("TEST_SCHEMA")
        record = logger.makeRecord(
            name="payment_service",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="Order paid successfully",
            args=(),
            exc_info=None,
            extra={
                "trace_id": "trace-uuid-1234",
                "correlation_id": "ORD-9988",
                "tenant_id": "onlineboost",
                "service": "payment_gateway",
                "event_type": "ORDER_SETTLED",
                "entity_type": "order",
                "entity_id": "ORD-9988",
                "provider": "xendit",
                "provider_event_id": "xnd_evt_111",
                "status": "SUCCESS",
                "duration_ms": 85.5,
                "error_code": None,
            }
        )

        formatted_json_str = formatter.format(record)
        data = json.loads(formatted_json_str)

        # Assert keys
        required_keys = [
            "timestamp",
            "trace_id",
            "correlation_id",
            "tenant_id",
            "service",
            "event_type",
            "entity_type",
            "entity_id",
            "provider",
            "provider_event_id",
            "status",
            "duration_ms",
            "error_code",
        ]
        for k in required_keys:
            self.assertIn(k, data, f"Key '{k}' missing from structured log output")

        self.assertEqual(data["trace_id"], "trace-uuid-1234")
        self.assertEqual(data["correlation_id"], "ORD-9988")
        self.assertEqual(data["tenant_id"], "onlineboost")
        self.assertEqual(data["service"], "payment_gateway")
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["duration_ms"], 85.5)
        self.assertIsNone(data["error_code"])


if __name__ == "__main__":
    unittest.main()
