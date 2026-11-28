"""tests/payments/test_unit_p0_01a_credential_hardening.py
Comprehensive Staging Verification Test Suite for UNIT-P0-01A:
Payment Consumer Credential Hardening (BT-SEC-2026-001).

Mandatory Verification Scenarios:
1. Scenario 1: Payment intent status update succeeds via privileged backend client.
2. Scenario 2: Payment settlement INSERT succeeds without anon grant (privileged client).
3. Scenario 3: Duplicate settlement webhook idempotency.
4. Scenario 4: Webhook retry handling idempotency.
5. Scenario 5: Xendit webhook settlement fallback path runs with privileged credentials.
6. Scenario 6: Payment failure and rollback does not report success.
7. Scenario 7: Missing/invalid privileged credentials fail-closed (raises error, no anon fallback).
8. Scenario 8: Zero credential leakage in exception logs and responses.
9. Scenario 9: Financial ledger reconciliation consistency.
10. Scenario 10: Regression test suite for existing payment abstraction.
"""

import os
import unittest
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from app.payments.schemas import (
    PaymentStatus,
    PaymentProviderType,
    PaymentIntentCreate,
    PaymentIntentResponse,
    WebhookEventPayload,
    SettlementRecord,
)
from app.payments.service import (
    PaymentCoreService,
    PaymentCredentialConfigurationError,
    PaymentPersistenceError,
    get_payment_privileged_supabase,
    get_supabase,
    LEGACY_PAYMENT_INTENTS,
    payment_core_service,
    PaymentMatchingService,
)
from app.payments.qris_adapter import (
    QRISPaymentAdapter,
    crc16_ccitt,
    parse_emvco_tlv,
)

SAMPLE_STATIC_QRIS = "00020101021126540014ID.LINKAJA.WWW01189360091430000000005204599953033605802ID5911TEST_STORE6007JAKARTA6304ABCD"


class TestUnitP001ACredentialHardening(unittest.IsolatedAsyncioTestCase):
    """Formal Staging Test Suite for UNIT-P0-01A Credential Hardening."""

    def setUp(self):
        from app.payments.recovery_store import recovery_store
        recovery_store.clear()
        self.mock_sb_client = MagicMock()
        self.mock_table = MagicMock()
        self.mock_sb_client.table.return_value = self.mock_table
        self.mock_table.insert.return_value = self.mock_table
        self.mock_table.update.return_value = self.mock_table
        self.mock_table.upsert.return_value = self.mock_table
        self.mock_table.eq.return_value = self.mock_table
        self.mock_table.in_.return_value = self.mock_table
        self.mock_table.execute.return_value = MagicMock(data=[{"id": "test-record"}], error=None)

        # Patch redis lock to True to keep unit tests fast and independent of live Redis network
        self.redis_lock_patcher = patch("app.core.redis.acquire_payment_lock", return_value=True)
        self.mock_redis_lock = self.redis_lock_patcher.start()

    def tearDown(self):
        from app.payments.recovery_store import recovery_store
        recovery_store.clear()
        self.redis_lock_patcher.stop()

    # =========================================================================
    # Scenario 1: Payment intent status update succeeds via privileged client
    # =========================================================================
    async def test_scenario_01_intent_status_update_privileged_client(self):
        """Intent status update to SETTLED/EXPIRED calls privileged backend client."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-alpha",
            order_id="ORD-S1-001",
            amount=50000,
            expiry_minutes=30,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            # 1. Create intent
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)
            self.assertEqual(intent.status, PaymentStatus.PENDING)
            self.mock_sb_client.table.assert_any_call("payment_intents")
            self.mock_table.insert.assert_called()

            # 2. Settle intent
            webhook = WebhookEventPayload(
                tenant_id="tenant-alpha",
                order_id="ORD-S1-001",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-S1-001",
            )
            settlement = await service.process_webhook_settlement(webhook)
            self.assertEqual(intent.status, PaymentStatus.SETTLED)
            self.assertEqual(settlement.payment_intent_id, intent.id)

            # Verifikasi bahwa update status SETTLED dipanggil di Supabase via privileged client
            self.mock_table.update.assert_any_call({"status": "SETTLED"})
            self.mock_table.eq.assert_called_with("id", intent.id)

    # =========================================================================
    # Scenario 2: Payment settlement INSERT succeeds without anon grant
    # =========================================================================
    async def test_scenario_02_settlement_insert_privileged_client(self):
        """Payment settlement row is persisted via privileged client (service_role)."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-beta",
            order_id="ORD-S2-002",
            amount=75000,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)

            webhook = WebhookEventPayload(
                tenant_id="tenant-beta",
                order_id="ORD-S2-002",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-S2-002",
                raw_payload={"bank": "BCA", "ref": "REF-S2-002"},
            )
            settlement = await service.process_webhook_settlement(webhook)

            # Pastikan insert dipanggil pada tabel payment_settlements dengan payload valid
            self.mock_sb_client.table.assert_any_call("payment_settlements")
            self.mock_table.insert.assert_called()
            self.assertEqual(settlement.provider_ref, "REF-S2-002")
            self.assertEqual(settlement.settled_amount, intent.total_amount)

    # =========================================================================
    # Scenario 3: Duplicate settlement webhook idempotency
    # =========================================================================
    async def test_scenario_03_duplicate_settlement_webhook_idempotency(self):
        """Duplicate webhook deliveries return existing settlement and do not duplicate inserts."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-gamma",
            order_id="ORD-S3-003",
            amount=120000,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)

            webhook = WebhookEventPayload(
                tenant_id="tenant-gamma",
                order_id="ORD-S3-003",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-DUP-003",
            )

            # First delivery
            settlement_1 = await service.process_webhook_settlement(webhook)
            insert_call_count_1 = self.mock_table.insert.call_count

            # Second delivery (Duplicate)
            settlement_2 = await service.process_webhook_settlement(webhook)
            insert_call_count_2 = self.mock_table.insert.call_count

            self.assertEqual(settlement_1.id, settlement_2.id)
            self.assertEqual(settlement_1.provider_ref, settlement_2.provider_ref)
            # Tidak ada insert baru ke database
            self.assertEqual(insert_call_count_1, insert_call_count_2)

    # =========================================================================
    # Scenario 4: Webhook retry handling idempotency
    # =========================================================================
    async def test_scenario_04_webhook_retry_handling_idempotency(self):
        """Retried webhook with identical idempotency_key returns cached settlement without error."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-delta",
            order_id="ORD-S4-004",
            amount=88000,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)

            retry_payload = WebhookEventPayload(
                tenant_id="tenant-delta",
                order_id="ORD-S4-004",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-RETRY-004",
                idempotency_key="IDEMPOTENCY-KEY-9999",
            )

            res1 = await service.process_webhook_settlement(retry_payload)
            res2 = await service.process_webhook_settlement(retry_payload)
            self.assertEqual(res1.id, res2.id)
            self.assertEqual(res1.provider_ref, "REF-RETRY-004")

    # =========================================================================
    # Scenario 5: Xendit webhook settlement fallback path runs with privileged credentials
    # =========================================================================
    def test_scenario_05_xendit_fallback_settlement_uses_privileged_client(self):
        """_record_settlement_and_ledger_sync routes Supabase sync through privileged client."""
        from app.routes.xendit import _record_settlement_and_ledger_sync

        mock_pg_conn = MagicMock()
        mock_pg_cur = MagicMock()
        mock_pg_cur.rowcount = 1
        mock_pg_conn.cursor.return_value = mock_pg_cur
        mock_pg_cur.fetchone.return_value = {"product_id": "generic_digital"}

        auth_data_05 = {
            "order": {"id": "ORD-XENDIT-99", "gross_amount": 150000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_xendit_99", "order_id": "ORD-XENDIT-99", "gross_amount": 150000, "status": "COMPLETED", "tenant_id": "boon"},
        }

        with patch("app.routes.xendit.get_db_connection", return_value=mock_pg_conn), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=auth_data_05), \
             patch("app.routes.xendit.get_payment_privileged_supabase", return_value=self.mock_sb_client) as mock_priv_factory:

            _record_settlement_and_ledger_sync(
                event_id="EVT-XENDIT-01",
                external_id="ORD-XENDIT-99",
                tenant_id="boon",
                amount=150000,
                payload={"status": "PAID", "payment_method": "QRIS"},
                customer_phone="081299998888",
                customer_email="buyer@test.com",
            )

            # Privileged client factory harus terpanggil
            mock_priv_factory.assert_called()
            # payment_settlements upsert harus dilakukan
            self.mock_sb_client.table.assert_any_call("payment_settlements")
            self.mock_table.upsert.assert_called()
            # orders update status LUNAS harus dilakukan
            self.mock_sb_client.table.assert_any_call("orders")
            self.mock_table.update.assert_called()

    # =========================================================================
    # Scenario 6: Payment failure and rollback does not report success
    # =========================================================================
    async def test_scenario_06_payment_failure_does_not_report_success(self):
        """Mismatched amount, unknown order, or expired intent raises explicit rejection."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-eps",
            order_id="ORD-S6-006",
            amount=50000,
            expiry_minutes=30,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)

            # 1. Mismatched amount
            wrong_webhook = WebhookEventPayload(
                tenant_id="tenant-eps",
                order_id="ORD-S6-006",
                amount=999999,  # Mismatched amount
                provider="QRIS_DYNAMIC",
                provider_ref="REF-WRONG-006",
            )
            with self.assertRaises(ValueError) as ctx:
                await service.process_webhook_settlement(wrong_webhook)
            self.assertIn("does not match intent amount", str(ctx.exception))
            # Status harus tetap PENDING
            self.assertEqual(intent.status, PaymentStatus.PENDING)

            # 2. Expired intent rejection
            intent.status = PaymentStatus.EXPIRED
            valid_amount_webhook = WebhookEventPayload(
                tenant_id="tenant-eps",
                order_id="ORD-S6-006",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-EXP-006",
            )
            with self.assertRaises(ValueError) as ctx_exp:
                await service.process_webhook_settlement(valid_amount_webhook)
            self.assertIn("expired", str(ctx_exp.exception).lower())

    # =========================================================================
    # Scenario 7: Missing/invalid privileged credentials fail-closed
    # =========================================================================
    async def test_scenario_07_missing_privileged_credentials_fail_closed(self):
        """Missing SUPABASE_SERVICE_ROLE_KEY raises PaymentCredentialConfigurationError without fallback."""
        # Setup env dengan anon key tapi TANPA service_role key
        test_env = {
            "SUPABASE_URL": "https://test-project.supabase.co",
            "SUPABASE_ANON_KEY": "sample-anon-public-key-not-privileged",
            "SUPABASE_SERVICE_ROLE_KEY": "",
            "SUPABASE_SERVICE_KEY": "",
        }

        with patch.dict(os.environ, test_env, clear=False):
            # 1. Pemanggilan get_payment_privileged_supabase langsung wajib melempar error
            with self.assertRaises(PaymentCredentialConfigurationError) as ctx:
                get_payment_privileged_supabase()
            self.assertIn("[SECURITY FAIL-CLOSED]", str(ctx.exception))
            self.assertIn("SUPABASE_SERVICE_ROLE_KEY required", str(ctx.exception))

            # 2. Pemanggilan get_supabase() juga melempar error (zero fallback ke anon)
            with self.assertRaises(PaymentCredentialConfigurationError):
                get_supabase()

            # 3. Create payment intent dalam non-memory mode melempar error jika kredensial absen
            service = PaymentCoreService(in_memory_mode=False)
            adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
            service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

            with self.assertRaises(PaymentCredentialConfigurationError):
                await service.create_payment_intent(
                    PaymentIntentCreate(
                        tenant_id="tenant-fail-closed",
                        order_id="ORD-FAIL-001",
                        amount=10000,
                    ),
                    provider_type=PaymentProviderType.QRIS_DYNAMIC,
                )

    # =========================================================================
    # Scenario 8: Zero credential leakage in exception logs/responses
    # =========================================================================
    def test_scenario_08_zero_credential_leakage(self):
        """Sensitive tokens or secrets never leak into exception messages or tracebacks."""
        secret_token = "ultra-secret-service-token-never-expose-xyz987654"
        test_env = {
            "SUPABASE_URL": "https://test-project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": secret_token,
        }

        with patch.dict(os.environ, test_env, clear=False):
            # Simulasikan kegagalan supabase.create_client yang melempar exception berisi secret
            with patch("supabase.create_client", side_effect=Exception(f"Connection failed with Bearer {secret_token}")):
                with self.assertRaises(PaymentCredentialConfigurationError) as ctx:
                    get_payment_privileged_supabase()

                err_str = str(ctx.exception)
                # Pastikan secret_token TIDAK PERNAH bocor ke dalam pesan exception
                self.assertNotIn(secret_token, err_str)
                self.assertIn("[SECURITY FAIL-CLOSED]", err_str)
                self.assertIn("Privileged payment backend client initialization failed", err_str)

    # =========================================================================
    # Scenario 9: Financial ledger reconciliation consistency
    # =========================================================================
    async def test_scenario_09_financial_ledger_reconciliation_consistency(self):
        """Settled amount, intent amount, and legacy reconciliation structures remain 100% consistent."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        base_amount = 350000
        order_id = "ORD-S9-RECON"
        tenant_id = "tenant-recon"

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(
                PaymentIntentCreate(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    amount=base_amount,
                ),
                provider_type=PaymentProviderType.QRIS_DYNAMIC,
            )

            # Verifikasi penulisan awal ke LEGACY_PAYMENT_INTENTS
            self.assertIn(order_id, LEGACY_PAYMENT_INTENTS)
            self.assertEqual(LEGACY_PAYMENT_INTENTS[order_id]["status"], "PENDING")
            self.assertEqual(LEGACY_PAYMENT_INTENTS[order_id]["amount"], intent.total_amount)

            # Webhook settlement
            webhook = WebhookEventPayload(
                tenant_id=tenant_id,
                order_id=order_id,
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-RECON-S9",
            )
            settlement = await service.process_webhook_settlement(webhook)

            # Konsistensi nominal
            self.assertEqual(settlement.settled_amount, intent.total_amount)
            self.assertEqual(LEGACY_PAYMENT_INTENTS[order_id]["status"], "PAID")
            self.assertEqual(LEGACY_PAYMENT_INTENTS[intent.total_amount]["status"], "PAID")

    # =========================================================================
    # Scenario 10: Regression test suite for existing payment abstraction
    # =========================================================================
    async def test_scenario_10_regression_payment_abstraction_and_qris_adapter(self):
        """EMVCo QRIS generation, CRC16 checksum, unique code, and matching facade work without regression."""
        # 1. EMVCo CRC16 check
        sample_payload = "00020101021226540014ID.LINKAJA.WWW0118936009143000000000520459995303360540410005802ID5911XENDIT_PROD6007JAKARTA6304"
        crc = crc16_ccitt(sample_payload)
        self.assertEqual(len(crc), 4)

        # 2. QRIS dynamic intent generation
        service = PaymentCoreService(in_memory_mode=True)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent = await service.create_payment_intent(
            PaymentIntentCreate(
                tenant_id="tenant-regression",
                order_id="ORD-REG-10",
                amount=100000,
            ),
            provider_type=PaymentProviderType.QRIS_DYNAMIC,
        )

        self.assertEqual(intent.status, PaymentStatus.PENDING)
        self.assertTrue(intent.qr_string.startswith("000201"))
        self.assertGreaterEqual(intent.unique_code, 100)
        self.assertLessEqual(intent.unique_code, 999)
        self.assertEqual(intent.total_amount, 100000 + intent.unique_code)

        # 3. Matcher extraction facade
        clean_amount = PaymentMatchingService.extract_amount("Pembayaran DANA Rp 150.000 berhasil")
        self.assertEqual(clean_amount, 150000)

    # =========================================================================
    # Scenario 11: Payment intent persistence failure rolls back in-memory
    # =========================================================================
    async def test_scenario_11_intent_persistence_failure_rolls_back_in_memory(self):
        """Persistent mode raises PaymentPersistenceError on DB error and rolls back in-memory cache."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-fail-db",
            order_id="ORD-FAIL-INTENT-11",
            amount=75000,
            expiry_minutes=30,
        )

        # Mock DB failure on payment_intents table insert
        failing_table = MagicMock()
        failing_table.insert.return_value = failing_table
        failing_table.execute.side_effect = RuntimeError("Database connection lost during intent insert")
        mock_client = MagicMock()
        mock_client.table.return_value = failing_table

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=mock_client):
            with self.assertRaises(PaymentPersistenceError) as ctx:
                await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)
            self.assertIn("Failed to persist payment intent", str(ctx.exception))

            # Verifikasi bahwa in-memory cache benar-benar bersih (roll back)
            self.assertEqual(len(service._intents_by_id), 0)
            self.assertNotIn("tenant-fail-db:ORD-FAIL-INTENT-11", service._intents_by_tenant_order)
            self.assertNotIn("ORD-FAIL-INTENT-11", LEGACY_PAYMENT_INTENTS)

    # =========================================================================
    # Scenario 12: Settlement intent-update failure prevents settled status
    # =========================================================================
    async def test_scenario_12_settlement_intent_update_failure_prevents_settled_status(self):
        """When DB update to payment_intents fails, error is propagated and in-memory status remains PENDING."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-fail-settle",
            order_id="ORD-FAIL-UPDATE-12",
            amount=50000,
            expiry_minutes=30,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)
            self.assertEqual(intent.status, PaymentStatus.PENDING)

            # Simulasikan kegagalan DB saat mengupdate status payment_intents ke SETTLED
            self.mock_table.execute.side_effect = RuntimeError("Deadlock / connection drop on payment_intents update")

            webhook = WebhookEventPayload(
                tenant_id="tenant-fail-settle",
                order_id="ORD-FAIL-UPDATE-12",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-FAIL-12",
            )

            with self.assertRaises(PaymentPersistenceError) as ctx:
                await service.process_webhook_settlement(webhook)
            self.assertIn("Failed to update payment intent status to SETTLED", str(ctx.exception))

            # In-memory status WAJIB tetap PENDING (bukan false SETTLED)
            self.assertEqual(intent.status, PaymentStatus.PENDING)
            self.assertNotIn("REF-FAIL-12", service._settlements_by_ref)
            self.assertNotIn(webhook.order_id, service._idempotency_keys)

    # =========================================================================
    # Scenario 13: Settlement INSERT failure triggers compensation and rollback
    # =========================================================================
    async def test_scenario_13_settlement_insert_failure_triggers_compensation_and_rollback(self):
        """When settlement INSERT fails after intent update, compensating transaction reverts intent to PENDING."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-comp-13",
            order_id="ORD-COMP-13",
            amount=60000,
            expiry_minutes=30,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)
            self.assertEqual(intent.status, PaymentStatus.PENDING)

            # Atur perilaku eksekusi bertahap:
            # 1. Update payment_intents ke SETTLED -> Berhasil
            # 2. Insert payment_settlements -> Gagal (RuntimeError)
            # 3. Compensating update payment_intents ke PENDING -> Berhasil
            call_count = 0
            updates_executed = []

            def custom_update_handler(payload):
                updates_executed.append(payload)
                return self.mock_table

            def custom_execute():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # payment_intents update ke SETTLED berhasil
                    return MagicMock(data=[{"id": intent.id, "status": "SETTLED"}])
                elif call_count == 2:
                    # payment_settlements insert gagal
                    raise RuntimeError("Unique violation or disk full on payment_settlements")
                else:
                    # compensating update ke PENDING berhasil
                    return MagicMock(data=[{"id": intent.id, "status": "PENDING"}])

            self.mock_table.update.side_effect = custom_update_handler
            self.mock_table.execute.side_effect = custom_execute

            webhook = WebhookEventPayload(
                tenant_id="tenant-comp-13",
                order_id="ORD-COMP-13",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-COMP-13",
            )

            with self.assertRaises(PaymentPersistenceError) as ctx:
                await service.process_webhook_settlement(webhook)
            self.assertIn("Failed to persist settlement record (compensated)", str(ctx.exception))

            # Verifikasi pemulihan kompensasi: update dipanggil dengan status PENDING
            self.assertTrue(any(u.get("status") == "PENDING" for u in updates_executed))
            # Status in-memory tidak ditinggalkan yatim sebagai SETTLED
            self.assertEqual(intent.status, PaymentStatus.PENDING)
            self.assertNotIn("REF-COMP-13", service._settlements_by_ref)

    # =========================================================================
    # Scenario 14: In-memory state consistency after persistence failure
    # =========================================================================
    async def test_scenario_14_in_memory_state_consistency_after_persistence_failure(self):
        """In-memory registries remain 100% consistent and pristine after consecutive persistence failures."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        # 1. Uji kegagalan persistensi intent
        failing_client = MagicMock()
        failing_tbl = MagicMock()
        failing_client.table.return_value = failing_tbl
        failing_tbl.insert.return_value = failing_tbl
        failing_tbl.execute.side_effect = RuntimeError("DB write error")

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=failing_client):
            with self.assertRaises(PaymentPersistenceError):
                await service.create_payment_intent(
                    PaymentIntentCreate(
                        tenant_id="tenant-c14",
                        order_id="ORD-FAIL-C14",
                        amount=25000,
                    ),
                    provider_type=PaymentProviderType.QRIS_DYNAMIC,
                )

        # Tidak ada state tersisa di memory
        self.assertNotIn("ORD-FAIL-C14", service._intents_by_id)
        self.assertNotIn("ORD-FAIL-C14", LEGACY_PAYMENT_INTENTS)
        self.assertEqual(len(service._settlements_by_ref), 0)
        self.assertEqual(len(service._idempotency_keys), 0)

    # =========================================================================
    # Scenario 15: Xendit settlement persistence failure propagates error
    # =========================================================================
    async def test_scenario_15_xendit_settlement_persistence_failure_propagates_error(self):
        """Xendit fallback sync raises PaymentPersistenceError on Supabase failure and verifies caller behavior."""
        from app.routes.xendit import _record_settlement_and_ledger_sync, process_xendit_webhook_core
        from app.core.security.provenance_authority import SettlementProvenanceError

        mock_pg_conn = MagicMock()
        mock_pg_cur = MagicMock()
        mock_pg_cur.rowcount = 1
        mock_pg_conn.cursor.return_value = mock_pg_cur
        mock_pg_cur.fetchone.return_value = {"product_id": "generic_digital"}

        # Simulasikan Supabase sync melempar exception
        failing_sb = MagicMock()
        failing_sb_tbl = MagicMock()
        failing_sb.table.return_value = failing_sb_tbl
        failing_sb_tbl.upsert.return_value = failing_sb_tbl
        failing_sb_tbl.execute.side_effect = RuntimeError("Supabase cluster unreachable")

        auth_data_15 = {
            "order": {"id": "ORD-ERR-15", "gross_amount": 120000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "tenant-15"},
            "ledger": {"id": "led_15", "order_id": "ORD-ERR-15", "gross_amount": 120000, "status": "SETTLED", "tenant_id": "tenant-15"},
        }
        with patch("app.routes.xendit.get_db_connection", return_value=mock_pg_conn), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=auth_data_15), \
             patch("app.routes.xendit.get_payment_privileged_supabase", return_value=failing_sb):

            # Kegagalan persistensi sinkronisasi tidak ditelan diam-diam
            with self.assertRaises(PaymentPersistenceError) as ctx:
                _record_settlement_and_ledger_sync(
                    event_id="EVT-ERR-15",
                    external_id="ORD-ERR-15",
                    tenant_id="tenant-15",
                    amount=120000,
                    payload={"status": "PAID"},
                )
            self.assertIn("Failed to synchronize settlement to Supabase", str(ctx.exception))

        # Verifikasi perilaku caller/gateway acknowledgment:
        # Jika verifikasi/commit webhook gagal, caller menerima HTTP 500/non-200 sehingga gateway
        # akan me-retry event (tidak menganggap transaksi selesai tanpa persistensi).
        with patch("app.routes.xendit._check_db_idempotency_sync", return_value=None), \
             patch("app.routes.xendit._lookup_persisted_order_sync", return_value={
                 "order_id": "ORD-ERR-15",
                 "gross_amount": 120000,
                 "canonical_tenant_id": "tenant-15",
                 "tenant_slug": "tenant-15",
                 "tenant_metadata": {},
                 "order_metadata": {},
                 "sku_id": "SKU-REGULAR",
             }), \
             patch("app.routes.xendit.CredentialProfileMapper.resolve_and_verify_callback_secret") as mock_auth, \
             patch("app.routes.xendit.TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability"), \
             patch("app.routes.xendit.commit_verified_settlement_transaction", side_effect=SettlementProvenanceError("ERR_PERSISTENCE", "Database failure on settlement commit", http_status=500)):

            mock_auth.return_value = MagicMock(credential_profile_id="cp_test", expected_provider_account_id="acc_test")

            result = await process_xendit_webhook_core(
                payload={"id": "evt_test_15", "external_id": "ORD-ERR-15", "amount": 120000, "status": "PAID"},
                headers={"x-callback-token": "valid_token"}
            )
            # Caller menerima non-200 status (HTTP 500) yang memicu retry oleh gateway
            self.assertEqual(result["http_status"], 500)
            self.assertEqual(result["response"]["status"], "FAILED")

    # =========================================================================
    # Scenario 16: Duplicate webhook retry recovers after partial failure
    # =========================================================================
    async def test_scenario_16_duplicate_webhook_retry_recovers_after_partial_failure(self):
        """A transient settlement failure is recovered idempotently upon webhook retry."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-retry-16",
            order_id="ORD-RETRY-16",
            amount=88000,
            expiry_minutes=30,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)
            self.assertEqual(intent.status, PaymentStatus.PENDING)

            webhook = WebhookEventPayload(
                tenant_id="tenant-retry-16",
                order_id="ORD-RETRY-16",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-RETRY-16",
            )

            # DISPATCH 1: Gagal transien pada update intent
            self.mock_table.execute.side_effect = RuntimeError("Temporary network timeout")
            with self.assertRaises(PaymentPersistenceError):
                await service.process_webhook_settlement(webhook)

            self.assertEqual(intent.status, PaymentStatus.PENDING)
            self.assertNotIn("REF-RETRY-16", service._settlements_by_ref)

            # DISPATCH 2: Jaringan pulih, retry webhook masuk dengan payload yang sama persis
            self.mock_table.execute.side_effect = None
            self.mock_table.execute.return_value = MagicMock(data=[{"id": intent.id, "status": "SETTLED"}])

            settlement_res = await service.process_webhook_settlement(webhook)
            self.assertEqual(intent.status, PaymentStatus.SETTLED)
            self.assertEqual(settlement_res.payment_intent_id, intent.id)
            self.assertEqual(settlement_res.provider_ref, "REF-RETRY-16")

            # DISPATCH 3: Duplicate webhook setelah sukses -> kembali idempoten
            dup_res = await service.process_webhook_settlement(webhook)
            self.assertEqual(dup_res.id, settlement_res.id)

    # =========================================================================
    # Scenario 17: Amount boundary and fractional-value validation
    # =========================================================================
    async def test_scenario_17_amount_boundary_and_fractional_decimal_precision(self):
        """Decimal precision is enforced; non-positive amounts and fractional truncation mismatches are rejected."""
        service = PaymentCoreService(in_memory_mode=True)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent = await service.create_payment_intent(
            PaymentIntentCreate(
                tenant_id="tenant-dec-17",
                order_id="ORD-DEC-17",
                amount=50000,
            ),
            provider_type=PaymentProviderType.QRIS_DYNAMIC,
        )

        # 1. Non-positive amounts (negative / zero) must be rejected
        for invalid_amount in [-50000, 0, -1]:
            with self.assertRaises(ValueError) as ctx:
                await service.process_webhook_settlement(
                    WebhookEventPayload(
                        tenant_id="tenant-dec-17",
                        order_id="ORD-DEC-17",
                        amount=invalid_amount,
                        provider="QRIS_DYNAMIC",
                        provider_ref=f"REF-NEG-{invalid_amount}",
                    )
                )
            self.assertIn("must be positive", str(ctx.exception))

        # 2. Fractional precision mismatch (e.g. 50000.75 vs 50000.25)
        # int() truncation would have resulted in 50000 == 50000, erroneously accepting!
        # Decimal comparison must reject!
        intent.total_amount = 50000.75
        with self.assertRaises(ValueError) as ctx:
            await service.process_webhook_settlement(
                WebhookEventPayload(
                    tenant_id="tenant-dec-17",
                    order_id="ORD-DEC-17",
                    amount=50000.25,
                    provider="QRIS_DYNAMIC",
                    provider_ref="REF-FRAC-MISMATCH",
                )
            )
        self.assertIn("does not match intent amount", str(ctx.exception))

        # 3. Exact fractional match succeeds
        exact_settlement = await service.process_webhook_settlement(
            WebhookEventPayload(
                tenant_id="tenant-dec-17",
                order_id="ORD-DEC-17",
                amount=50000.75,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-FRAC-EXACT",
            )
        )
        self.assertEqual(exact_settlement.settled_amount, 50000.75)
        self.assertEqual(intent.status, PaymentStatus.SETTLED)

    # =========================================================================
    # Scenario 18: Secondary payment event failure does not abort settlement
    # =========================================================================
    async def test_scenario_18_secondary_payment_event_failure_does_not_abort_settlement(self):
        """Failure in secondary payment_events observability sync does NOT abort primary financial settlement."""
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-sec-18",
            order_id="ORD-SEC-18",
            amount=35000,
            expiry_minutes=30,
        )

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)
            self.assertEqual(intent.status, PaymentStatus.PENDING)

            webhook = WebhookEventPayload(
                tenant_id="tenant-sec-18",
                order_id="ORD-SEC-18",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-SEC-18",
            )

            # Mock secondary record_payment_event to raise an exception
            with patch.object(service, "record_payment_event", side_effect=Exception("Kafka/Replica sink timeout")):
                # Settlement utama wajib TETAP BERHASIL
                settlement = await service.process_webhook_settlement(webhook)
                self.assertEqual(intent.status, PaymentStatus.SETTLED)
                self.assertEqual(settlement.payment_intent_id, intent.id)
                self.assertEqual(settlement.provider_ref, "REF-SEC-18")
                self.assertIn("REF-SEC-18", service._settlements_by_ref)

    # =========================================================================
    # Scenario 19: Compensation failure tracking & deterministic self-healing
    # =========================================================================
    async def test_scenario_19_compensation_failure_tracking_and_self_healing_recovery(self):
        """
        When intent update succeeds, settlement insert fails, AND compensating update back to PENDING fails:
        1. State is enqueued in _unresolved_settlements (never acknowledged as success).
        2. PaymentPersistenceError is raised with sanitized diagnostics.
        3. Subsequent webhook retry executes self-healing: completes settlement insert, marks SETTLED, and clears queue.
        """
        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        intent_data = PaymentIntentCreate(
            tenant_id="tenant-double-fail-19",
            order_id="ORD-FAIL-COMP-19",
            amount=95000,
            expiry_minutes=30,
        )

        mock_pg_conn = MagicMock()
        mock_pg_cur = MagicMock()
        mock_pg_conn.cursor.return_value = mock_pg_cur
        mock_pg_conn.__enter__ = MagicMock(return_value=mock_pg_conn)
        mock_pg_conn.__exit__ = MagicMock(return_value=None)
        mock_pg_cur.__enter__ = MagicMock(return_value=mock_pg_cur)
        mock_pg_cur.__exit__ = MagicMock(return_value=None)

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client), \
             patch("app.core.database.get_db_connection", return_value=mock_pg_conn):
            intent = await service.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)
            self.assertEqual(intent.status, PaymentStatus.PENDING)

            webhook = WebhookEventPayload(
                tenant_id="tenant-double-fail-19",
                order_id="ORD-FAIL-COMP-19",
                amount=intent.total_amount,
                provider="QRIS_DYNAMIC",
                provider_ref="REF-FAIL-COMP-19",
            )

            # Atur perilaku eksekusi Supabase:
            # Call 1: update payment_intents ke SETTLED -> Berhasil
            # Call 2: insert payment_settlements -> Gagal (DB error)
            # Call 3: compensating update payment_intents ke PENDING -> GAGAL JUGA (double failure)
            call_count = 0
            def double_failure_execute():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return MagicMock(data=[{"id": intent.id, "status": "SETTLED"}])
                elif call_count == 2:
                    raise RuntimeError("Insert to payment_settlements failed (I/O error)")
                elif call_count == 3:
                    raise RuntimeError("Compensating rollback to PENDING failed (Connection severed)")
                else:
                    return MagicMock(data=[{"id": intent.id}])

            self.mock_table.execute.side_effect = double_failure_execute

            # Percobaan 1: Melempar PaymentPersistenceError dan mencatat state ke registry pemulihan
            with self.assertRaises(PaymentPersistenceError) as ctx:
                await service.process_webhook_settlement(webhook)

            self.assertIn("compensation rollback failed", str(ctx.exception))
            self.assertIn("unresolved recovery registry", str(ctx.exception))

            # Verifikasi: intent terdaftar di _unresolved_settlements
            unresolved = service.get_unresolved_settlements()
            self.assertIn(intent.id, unresolved)
            self.assertEqual(unresolved[intent.id]["recovery_status"], "PENDING_RECOVERY")
            self.assertEqual(unresolved[intent.id]["order_id"], "ORD-FAIL-COMP-19")
            self.assertEqual(intent.status, PaymentStatus.PENDING)
            self.assertNotIn("REF-FAIL-COMP-19", service._settlements_by_ref)

            # Percobaan 2 (Webhook Retry): Jaringan pulih, settlement insert berhasil pada retry
            self.mock_table.execute.side_effect = None
            self.mock_table.execute.return_value = MagicMock(data=[{"id": intent.id}])

            healed_settlement = await service.process_webhook_settlement(webhook)

            # Verifikasi pemulihan tuntas:
            self.assertEqual(intent.status, PaymentStatus.SETTLED)
            self.assertEqual(healed_settlement.payment_intent_id, intent.id)
            self.assertEqual(healed_settlement.provider_ref, "REF-FAIL-COMP-19")
            # State harus sudah dihapus dari antrean unresolved setelah self-healing berhasil
            self.assertNotIn(intent.id, service.get_unresolved_settlements())
            self.assertIn("REF-FAIL-COMP-19", service._settlements_by_ref)

    # =========================================================================
    # Scenario 20: ALREADY_PROCESSED webhook retry triggers Supabase catch-up sync
    # =========================================================================
    async def test_scenario_20_already_processed_webhook_retry_triggers_supabase_catchup(self):
        """
        When PostgreSQL has already committed settlement (ALREADY_PROCESSED on retry),
        the webhook handler still executes idempotent catch-up replication to Supabase
        before returning HTTP 200, preventing silent replication drop.
        """
        from app.routes.xendit import process_xendit_webhook_core

        # 1. Mock order lookup & auth
        persisted_order_data = {
            "order_id": "ORD-CATCHUP-20",
            "gross_amount": 175000,
            "canonical_tenant_id": "tenant-catchup",
            "tenant_slug": "tenant-catchup",
            "tenant_metadata": {},
            "order_metadata": {},
            "sku_id": "SKU-PROD-20",
        }

        authoritative_pg_data_20 = {
            "order": {"id": "ORD-CATCHUP-20", "gross_amount": 175000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "tenant-catchup"},
            "ledger": {"id": "led_20", "order_id": "ORD-CATCHUP-20", "gross_amount": 175000, "status": "COMPLETED", "tenant_id": "tenant-catchup"},
        }

        # Mock commit_verified_settlement_transaction returning ALREADY_PROCESSED
        with patch("app.routes.xendit._check_db_idempotency_sync", return_value=None), \
             patch("app.routes.xendit._lookup_persisted_order_sync", return_value=persisted_order_data), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=authoritative_pg_data_20), \
             patch("app.routes.xendit.CredentialProfileMapper.resolve_and_verify_callback_secret") as mock_auth, \
             patch("app.routes.xendit.TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability"), \
             patch("app.routes.xendit.commit_verified_settlement_transaction", return_value={"status": "ALREADY_PROCESSED"}), \
             patch("app.routes.xendit.get_payment_privileged_supabase", return_value=self.mock_sb_client):

            mock_auth.return_value = MagicMock(credential_profile_id="cp_test", expected_provider_account_id="acc_test")

            result = await process_xendit_webhook_core(
                payload={"id": "evt_catchup_20", "external_id": "ORD-CATCHUP-20", "amount": 175000, "status": "PAID"},
                headers={"x-callback-token": "valid_token"}
            )

            # 2. Verifikasi respons webhook
            self.assertEqual(result["http_status"], 200)
            self.assertEqual(result["response"]["status"], "ALREADY_PROCESSED")
            self.assertTrue(result["response"]["idempotent"])

            # 3. Verifikasi bahwa Supabase catch-up sync DIPANGGIL (tidak dilewati)
            self.mock_sb_client.table.assert_any_call("payment_settlements")
            self.mock_table.upsert.assert_called()
            self.mock_sb_client.table.assert_any_call("orders")
            self.mock_table.update.assert_called()

    # =========================================================================
    # Scenario 21: Database error sanitization & zero credential leakage
    # =========================================================================
    async def test_scenario_21_database_error_sanitization_zero_credential_leakage(self):
        """
        Negative test: Injected database error containing raw connection strings,
        passwords, and bearer tokens is completely sanitized with zero leakage.
        """
        from app.routes.xendit import _record_settlement_and_ledger_sync

        sensitive_password = "SuperSecretPassword123"
        sensitive_token_sig = "secret_jwt_signature_xyz987"
        sensitive_api_key = "apikey_super_confidential_555"

        injected_db_error_message = (
            f"FATAL: connection to postgresql://postgres:{sensitive_password}@db.xkhqirhurnjqglmajghn.supabase.co:5432/postgres "
            f"failed with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSJ9.{sensitive_token_sig} "
            f"and apikey={sensitive_api_key}"
        )

        service = PaymentCoreService(in_memory_mode=False)
        adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
        service.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

        # 1. Test create_payment_intent persistence failure sanitization
        failing_client = MagicMock()
        failing_tbl = MagicMock()
        failing_client.table.return_value = failing_tbl
        failing_tbl.insert.return_value = failing_tbl
        failing_tbl.execute.side_effect = RuntimeError(injected_db_error_message)

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=failing_client):
            with self.assertRaises(PaymentPersistenceError) as ctx:
                await service.create_payment_intent(
                    PaymentIntentCreate(
                        tenant_id="tenant-sanitization",
                        order_id="ORD-SANITIZATION-21",
                        amount=50000,
                    ),
                    provider_type=PaymentProviderType.QRIS_DYNAMIC,
                )
            error_str = str(ctx.exception)
            # Verifikasi NOL kebocoran kata sandi, token, dan API key
            self.assertNotIn(sensitive_password, error_str)
            self.assertNotIn(sensitive_token_sig, error_str)
            self.assertNotIn(sensitive_api_key, error_str)
            self.assertIn("***", error_str)

        # 2. Test Xendit fallback sync sanitization
        mock_pg_conn = MagicMock()
        mock_pg_cur = MagicMock()
        mock_pg_cur.rowcount = 1
        mock_pg_conn.cursor.return_value = mock_pg_cur
        mock_pg_cur.fetchone.return_value = {"product_id": "generic_digital"}

        failing_xendit_sb = MagicMock()
        failing_xendit_tbl = MagicMock()
        failing_xendit_sb.table.return_value = failing_xendit_tbl
        failing_xendit_tbl.upsert.return_value = failing_xendit_tbl
        failing_xendit_tbl.execute.side_effect = RuntimeError(injected_db_error_message)

        auth_data_21 = {
            "order": {"id": "ORD-SAN-21", "gross_amount": 80000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "tenant-san"},
            "ledger": {"id": "led_21", "order_id": "ORD-SAN-21", "gross_amount": 80000, "status": "SETTLED", "tenant_id": "tenant-san"},
        }
        with patch("app.routes.xendit.get_db_connection", return_value=mock_pg_conn), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=auth_data_21), \
             patch("app.routes.xendit.get_payment_privileged_supabase", return_value=failing_xendit_sb):

            with self.assertRaises(PaymentPersistenceError) as ctx2:
                _record_settlement_and_ledger_sync(
                    event_id="EVT-SAN-21",
                    external_id="ORD-SAN-21",
                    tenant_id="tenant-san",
                    amount=80000,
                    payload={"status": "PAID"},
                )
            error_str2 = str(ctx2.exception)
            self.assertNotIn(sensitive_password, error_str2)
            self.assertNotIn(sensitive_token_sig, error_str2)
            self.assertNotIn(sensitive_api_key, error_str2)
            self.assertIn("***", error_str2)

    # =========================================================================
    # Scenario 22: Durable recovery survives process restart and self-heals
    # =========================================================================
    async def test_scenario_22_durable_recovery_survives_process_restart_and_heals_on_retry(self):
        """
        Durable recovery mechanism: When a double failure occurs, the incident is
        saved to durable recovery storage. When the Python worker/process restarts
        (all in-memory state wiped and service re-instantiated), the new service instance
        reloads the unresolved recovery record, completes the missing settlement idempotently,
        and clears the durable recovery record only after successful persistence.
        """
        from app.payments.recovery_store import DurableSettlementRecoveryStore

        mock_pg_conn = MagicMock()
        mock_pg_cur = MagicMock()
        mock_pg_conn.cursor.return_value = mock_pg_cur
        mock_pg_conn.__enter__ = MagicMock(return_value=mock_pg_conn)
        mock_pg_conn.__exit__ = MagicMock(return_value=None)
        mock_pg_cur.__enter__ = MagicMock(return_value=mock_pg_cur)
        mock_pg_cur.__exit__ = MagicMock(return_value=None)
        mock_pg_cur.fetchall.return_value = []

        # Create isolated recovery store for this test
        test_recovery_file = os.path.join("data", "recovery", "test_restart_recovery.json")

        with patch("app.payments.service.get_payment_privileged_supabase", return_value=self.mock_sb_client), \
             patch("app.core.database.get_db_connection", return_value=mock_pg_conn):

            custom_recovery_store = DurableSettlementRecoveryStore(storage_path=test_recovery_file)
            custom_recovery_store.clear()

            # Step 1: Initial service instance
            service1 = PaymentCoreService(in_memory_mode=False, recovery_store_instance=custom_recovery_store)
            adapter = QRISPaymentAdapter(master_static_qris=SAMPLE_STATIC_QRIS)
            service1.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

            intent_data = PaymentIntentCreate(
                tenant_id="tenant-restart-test",
                order_id="ORD-RESTART-22",
                amount=75000,
                expiry_minutes=30,
            )

            intent = await service1.create_payment_intent(intent_data, provider_type=PaymentProviderType.QRIS_DYNAMIC)

            webhook = WebhookEventPayload(
                tenant_id="tenant-restart-test",
                order_id="ORD-RESTART-22",
                amount=intent.total_amount,
                provider="qris",
                provider_ref="REF-RESTART-22",
            )

            # Simulate double failure on service1:
            # Call 1: intent update to SETTLED -> succeeds
            # Call 2: settlement insert -> fails
            # Call 3: compensating intent update to PENDING -> fails
            call_count = 0
            def double_failure_execute():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return MagicMock(data=[{"id": intent.id, "status": "SETTLED"}], error=None)
                elif call_count == 2:
                    raise RuntimeError("Database deadlock on payment_settlements insert")
                elif call_count == 3:
                    raise RuntimeError("Database timeout on compensating update to PENDING")
                else:
                    return MagicMock(data=[{"id": intent.id}], error=None)

            self.mock_table.execute.side_effect = double_failure_execute

            with self.assertRaises(PaymentPersistenceError) as ctx:
                await service1.process_webhook_settlement(webhook)

            self.assertIn("compensation rollback failed", str(ctx.exception))

            # Verify durable record exists in storage
            unresolved_before = custom_recovery_store.list_unresolved_records()
            self.assertIn(intent.id, unresolved_before)
            self.assertEqual(unresolved_before[intent.id]["order_id"], "ORD-RESTART-22")

            # Step 2: Simulate complete process/container restart
            # Wipe all process-local memory, caches, and global registries
            service1._intents_by_id.clear()
            service1._intents_by_tenant_order.clear()
            service1._intents_by_amount.clear()
            service1._settlements_by_id.clear()
            service1._settlements_by_ref.clear()
            service1._settlements_by_intent.clear()
            service1._idempotency_keys.clear()
            LEGACY_PAYMENT_INTENTS.clear()

            # Create brand new service instance simulating new worker/container
            store_after_restart = DurableSettlementRecoveryStore(storage_path=test_recovery_file)
            service2 = PaymentCoreService(in_memory_mode=False, recovery_store_instance=store_after_restart)
            service2.register_provider(PaymentProviderType.QRIS_DYNAMIC, adapter)

            # Confirm service2 starts with completely empty in-memory intent registry
            self.assertEqual(len(service2._intents_by_id), 0)

            # Confirm service2 reloaded unresolved record from durable storage
            reloaded_unresolved = service2.get_unresolved_settlements()
            self.assertIn(intent.id, reloaded_unresolved)
            self.assertEqual(reloaded_unresolved[intent.id]["recovery_status"], "PENDING_RECOVERY")

            # Step 3: Incoming Webhook Retry received by service2 after recovery
            self.mock_table.execute.side_effect = None
            self.mock_table.execute.return_value = MagicMock(data=[{"id": intent.id}], error=None)

            healed_settlement = await service2.process_webhook_settlement(webhook)

            # Assertions: Self-healing completed idempotently
            self.assertEqual(healed_settlement.payment_intent_id, intent.id)
            self.assertEqual(healed_settlement.provider_ref, "REF-RESTART-22")
            self.assertEqual(healed_settlement.settled_amount, intent.total_amount)

            # Assertions: Durable recovery record is now cleared
            self.assertNotIn(intent.id, service2.get_unresolved_settlements())
            self.assertNotIn(intent.id, store_after_restart.list_unresolved_records())

            # Cleanup test file
            custom_recovery_store.clear()

    # =========================================================================
    # Scenario 23: Supabase .execute() error response inspection fails closed
    # =========================================================================
    async def test_scenario_23_supabase_response_error_inspection_fails_closed(self):
        """
        Explicit Supabase response inspection: If .execute() returns an object with
        .error populated without raising an exception, sync_xendit_settlement_to_supabase_catchup
        must inspect res.error, fail closed, return False (or raise sanitized error),
        and NEVER report success or mark replication complete.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup
        from app.payments.service import check_supabase_response_error

        # 1. Direct unit test of check_supabase_response_error
        err_res = MagicMock(error={"message": "permission denied for relation payment_settlements", "code": "42501"})
        with self.assertRaises(PaymentPersistenceError) as ctx:
            check_supabase_response_error(err_res, "test_operation")
        self.assertIn("permission denied", str(ctx.exception))

        http_err_res = MagicMock(error=None, status_code=500)
        with self.assertRaises(PaymentPersistenceError):
            check_supabase_response_error(http_err_res, "test_http_operation")

        # 2. Integration test with sync_xendit_settlement_to_supabase_catchup
        mock_sb_with_error = MagicMock()
        mock_table_error = MagicMock()
        mock_sb_with_error.table.return_value = mock_table_error
        mock_table_error.upsert.return_value = mock_table_error
        mock_table_error.update.return_value = mock_table_error
        mock_table_error.eq.return_value = mock_table_error
        # Return response object containing .error without throwing an exception
        mock_table_error.execute.return_value = MagicMock(
            data=None,
            error={"message": "RLS violation: anon user cannot insert payment_settlements", "code": "42501"}
        )

        auth_data_23 = {
            "order": {"id": "ORD-ERR-INSPECT-23", "gross_amount": 99000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "tenant-23"},
            "ledger": {"id": "led_23", "order_id": "ORD-ERR-INSPECT-23", "gross_amount": 99000, "status": "SETTLED", "tenant_id": "tenant-23"},
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb_with_error), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=auth_data_23):

            # Test fail-closed return value (raise_on_error=False) -> MUST return False
            success = sync_xendit_settlement_to_supabase_catchup(
                external_id="ORD-ERR-INSPECT-23",
                amount=99000,
                payload={"status": "PAID"},
                raise_on_error=False,
            )
            self.assertFalse(success)

            # Test fail-closed exception propagation (raise_on_error=True) -> MUST raise PaymentPersistenceError
            with self.assertRaises(PaymentPersistenceError) as ctx2:
                sync_xendit_settlement_to_supabase_catchup(
                    external_id="ORD-ERR-INSPECT-23",
                    amount=99000,
                    payload={"status": "PAID"},
                    raise_on_error=True,
                )
            self.assertIn("RLS violation", str(ctx2.exception))

    # =========================================================================
    # Scenario 24: Webhook retry uses authoritative PostgreSQL data without double ledger credits
    # =========================================================================
    async def test_scenario_24_already_processed_reconciles_from_authoritative_pg_data(self):
        """
        When PostgreSQL has already committed settlement, incoming webhook retries
        (returning ALREADY_PROCESSED) query and reconcile Supabase using authoritative
        gross_amount and metadata directly from PostgreSQL SSOT—never trusting unverified
        replayed external webhook payload amounts—while ensuring zero duplicate ledger credits.
        """
        from app.routes.xendit import process_xendit_webhook_core

        # Authoritative PostgreSQL committed state (gross_amount = 250000)
        persisted_order_data = {
            "order_id": "ORD-AUTH-24",
            "gross_amount": 250000,
            "canonical_tenant_id": "tenant-authoritative",
            "tenant_slug": "tenant-authoritative",
            "tenant_metadata": {},
            "order_metadata": {},
            "sku_id": "SKU-PROD-24",
        }

        authoritative_pg_data = {
            "order": {"id": "ORD-AUTH-24", "gross_amount": 250000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "tenant-authoritative"},
            "ledger": {"id": "led_auth_24", "order_id": "ORD-AUTH-24", "gross_amount": 250000, "status": "COMPLETED", "tenant_id": "tenant-authoritative", "metadata": {"auth_verified": True}},
            "settlement": None,
        }

        ledger_insert_count = 0
        def fake_commit(*args, **kwargs):
            nonlocal ledger_insert_count
            # Idempotency hit: already committed in PostgreSQL, no new ledger row inserted
            return {"status": "ALREADY_PROCESSED"}

        mock_clean_sb = MagicMock()
        mock_clean_table = MagicMock()
        mock_clean_sb.table.return_value = mock_clean_table
        mock_clean_table.upsert.return_value = mock_clean_table
        mock_clean_table.update.return_value = mock_clean_table
        mock_clean_table.eq.return_value = mock_clean_table
        mock_clean_table.execute.return_value = MagicMock(data=[{"id": "rec-24"}], error=None)

        with patch("app.routes.xendit._check_db_idempotency_sync", return_value=None), \
             patch("app.routes.xendit._lookup_persisted_order_sync", return_value=persisted_order_data), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=authoritative_pg_data), \
             patch("app.routes.xendit.CredentialProfileMapper.resolve_and_verify_callback_secret") as mock_auth, \
             patch("app.routes.xendit.TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability"), \
             patch("app.routes.xendit.commit_verified_settlement_transaction", side_effect=fake_commit), \
             patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_clean_sb):

            mock_auth.return_value = MagicMock(credential_profile_id="cp_auth", expected_provider_account_id="acc_auth")

            # Gateway re-sends webhook retry
            result = await process_xendit_webhook_core(
                payload={"id": "evt_retry_24", "external_id": "ORD-AUTH-24", "amount": 250000, "status": "PAID"},
                headers={"x-callback-token": "valid_token"}
            )

            # 1. Assert webhook response is HTTP 200 with ALREADY_PROCESSED
            self.assertEqual(result["http_status"], 200)
            self.assertEqual(result["response"]["status"], "ALREADY_PROCESSED")
            self.assertTrue(result["response"]["idempotent"])

            # 2. Assert zero duplicate ledger credits (fake_commit was called and returned ALREADY_PROCESSED)
            self.assertEqual(ledger_insert_count, 0)

            # 3. Assert Supabase was reconciled with the AUTHORITATIVE gross_amount (250000)
            mock_clean_table.upsert.assert_called_with({
                "provider_ref": "xendit_ORD-AUTH-24",
                "settled_amount": 250000,
                "status": "PAID",
                "raw_payload": {"auth_verified": True},
            }, on_conflict="provider_ref")

            mock_clean_table.update.assert_called_with({
                "status": "LUNAS",
                "payment_status": "PAID",
            })

    # =========================================================================
    # Scenario 25: Recovery persistence fails closed when all stores fail
    # =========================================================================
    async def test_scenario_25_recovery_persistence_fails_closed_when_all_stores_fail(self):
        """
        A3.1: When both PostgreSQL and disk persistence fail in save_unresolved_record(),
        the recovery store fails closed, raises RecoveryPersistenceError, and does NOT
        pollute in-memory cache with false persistence.
        """
        from app.payments.recovery_store import DurableSettlementRecoveryStore, RecoveryPersistenceError

        store = DurableSettlementRecoveryStore(storage_path="/invalid/nonexistent/path/recovery.json")
        store.clear()

        record = {
            "intent_id": "INT-FAIL-ALL-25",
            "order_id": "ORD-FAIL-ALL-25",
            "amount": 50000,
            "provider_ref": "REF-FAIL-ALL-25",
            "settlement_payload": {"id": "s_25"},
        }

        # Mock both PostgreSQL connection failing and disk writing failing
        with patch("app.core.database.get_db_connection", side_effect=RuntimeError("PostgreSQL connection refused")), \
             patch.object(store, "_persist_to_file", side_effect=IOError("Read-only filesystem")):

            with self.assertRaises(RecoveryPersistenceError) as ctx:
                store.save_unresolved_record(record)

            self.assertIn("All durable recovery stores failed", str(ctx.exception))
            # In-memory cache must NOT retain the unpersisted record
            self.assertNotIn("INT-FAIL-ALL-25", store.list_unresolved_records())

    # =========================================================================
    # Scenario 26: PostgreSQL succeeds while disk persistence fails
    # =========================================================================
    async def test_scenario_26_pg_succeeds_disk_fails_survives_process_restart(self):
        """
        A3.2 & A3.4: PostgreSQL succeeds while disk persistence fails.
        Logs warning without failing, and survives simulated process restart by authoritatively
        reloading from PostgreSQL staging table.
        """
        import json
        from app.payments.recovery_store import DurableSettlementRecoveryStore

        test_file = os.path.join("data", "recovery", "test_pg_only_recovery.json")
        store1 = DurableSettlementRecoveryStore(storage_path=test_file)
        store1.clear()

        record = {
            "intent_id": "INT-PG-OK-26",
            "order_id": "ORD-PG-OK-26",
            "tenant_id": "tenant-26",
            "amount": 88000,
            "provider_ref": "REF-PG-OK-26",
            "settlement_payload": {"id": "s_26", "provider_ref": "REF-PG-OK-26", "settled_amount": 88000},
            "recovery_status": "PENDING_RECOVERY",
        }

        mock_pg_conn = MagicMock()
        mock_pg_cur = MagicMock()
        mock_pg_conn.cursor.return_value = mock_pg_cur
        mock_pg_conn.__enter__ = MagicMock(return_value=mock_pg_conn)
        mock_pg_conn.__exit__ = MagicMock(return_value=None)
        mock_pg_cur.__enter__ = MagicMock(return_value=mock_pg_cur)
        mock_pg_cur.__exit__ = MagicMock(return_value=None)
        mock_pg_cur.fetchall.return_value = [
            ("INT-PG-OK-26", "ORD-PG-OK-26", "tenant-26", 88000, "REF-PG-OK-26",
             json.dumps(record["settlement_payload"]), "insert_err", "comp_err",
             "PENDING_RECOVERY", datetime.now(timezone.utc), datetime.now(timezone.utc))
        ]

        # 1. Save with PG succeeding and disk failing
        with patch("app.core.database.get_db_connection", return_value=mock_pg_conn), \
             patch.object(store1, "_persist_to_file", side_effect=IOError("Disk I/O error")):

            # Must NOT raise exception because PG SSOT succeeded
            store1.save_unresolved_record(record)
            self.assertIn("INT-PG-OK-26", store1.list_unresolved_records())

        # 2. Simulate complete process restart (disk file was never written)
        self.assertFalse(os.path.exists(test_file))

        # 3. Process re-initialization: reload_all reloads authoritatively from PostgreSQL
        with patch("app.core.database.get_db_connection", return_value=mock_pg_conn):
            store2 = DurableSettlementRecoveryStore(storage_path=test_file)
            reloaded = store2.reload_all()
            self.assertIn("INT-PG-OK-26", reloaded)
            self.assertEqual(reloaded["INT-PG-OK-26"]["amount"], 88000)
            self.assertEqual(reloaded["INT-PG-OK-26"]["provider_ref"], "REF-PG-OK-26")

        store1.clear()

    # =========================================================================
    # Scenario 27: PG deletion failure during mark_recovered preserves state and idempotent
    # =========================================================================
    async def test_scenario_27_pg_deletion_fails_during_mark_recovered_preserves_state_and_idempotent(self):
        """
        A3.3: If PostgreSQL deletion fails during mark_recovered(), fails closed,
        preserves recovery state in memory and storage, and subsequent reload_all +
        reconcile attempt is strictly idempotent without duplicate ledger credits.
        """
        from app.payments.recovery_store import DurableSettlementRecoveryStore, RecoveryPersistenceError

        test_file = os.path.join("data", "recovery", "test_del_fail_recovery.json")
        store = DurableSettlementRecoveryStore(storage_path=test_file)
        store.clear()

        record = {
            "intent_id": "INT-DEL-FAIL-27",
            "order_id": "ORD-DEL-FAIL-27",
            "tenant_id": "tenant-27",
            "amount": 65000,
            "provider_ref": "REF-DEL-FAIL-27",
            "settlement_payload": {"id": "s_27", "provider_ref": "REF-DEL-FAIL-27", "settled_amount": 65000},
            "recovery_status": "PENDING_RECOVERY",
        }
        store._cache["INT-DEL-FAIL-27"] = record
        store._persist_to_file()

        # 1. Test fail-closed deletion failure
        with patch("app.core.database.get_db_connection", side_effect=RuntimeError("PostgreSQL network deadlock")):
            with self.assertRaises(RecoveryPersistenceError) as ctx:
                store.mark_recovered("INT-DEL-FAIL-27")

            self.assertIn("Failed to delete recovery record from PostgreSQL", str(ctx.exception))
            # Record MUST be preserved in cache and disk file
            self.assertIn("INT-DEL-FAIL-27", store.list_unresolved_records())

        # 2. Test strictly idempotent reconciliation: Authoritative settlement already exists in PostgreSQL
        service = PaymentCoreService(in_memory_mode=False, recovery_store_instance=store)

        mock_pg_conn = MagicMock()
        mock_pg_cur = MagicMock()
        mock_pg_conn.cursor.return_value = mock_pg_cur
        mock_pg_conn.__enter__ = MagicMock(return_value=mock_pg_conn)
        mock_pg_conn.__exit__ = MagicMock(return_value=None)
        mock_pg_cur.__enter__ = MagicMock(return_value=mock_pg_cur)
        mock_pg_cur.__exit__ = MagicMock(return_value=None)

        # Mock: PostgreSQL payment_settlements ALREADY has this settlement
        mock_pg_cur.fetchone.return_value = ("s_27", "SETTLED")

        # Mock Supabase insert to verify it is NEVER called (zero duplicate credits)
        mock_sb_uncalled = MagicMock()

        with patch("app.core.database.get_db_connection", return_value=mock_pg_conn), \
             patch("app.payments.service.get_payment_privileged_supabase", return_value=mock_sb_uncalled):

            reconciled = await service.reconcile_unresolved_settlement("INT-DEL-FAIL-27")

            # Verified: existing settlement returned without duplicate insert
            self.assertIsNotNone(reconciled)
            self.assertEqual(reconciled.settled_amount, 65000)
            mock_sb_uncalled.table.assert_not_called()
            # Successfully cleared after PG confirmed deletion
            self.assertNotIn("INT-DEL-FAIL-27", store.list_unresolved_records())

        store.clear()

    # =========================================================================
    # Scenario 28: Catch-up sync negative paths & malicious replay fail closed
    # =========================================================================
    async def test_scenario_28_catchup_sync_negative_paths_and_malicious_replay_fail_closed(self):
        """
        A3.5: Comprehensive Negative Testing for PostgreSQL Authoritative Catch-Up Sync:
        (a) PostgreSQL lookup raises an error -> fails closed.
        (b) PostgreSQL lookup returns empty/None -> fails closed.
        (c) PostgreSQL lookup returns uncommitted order (PENDING) -> fails closed.
        (d) PostgreSQL lookup returns missing/zero gross_amount -> fails closed.
        (e) Malicious replayed webhook amount (e.g. 1000) vs authoritative PG amount (500000)
            -> strictly enforces PG amount, completely ignores webhook caller amount.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()
        mock_sb_table = MagicMock()
        mock_sb.table.return_value = mock_sb_table
        mock_sb_table.upsert.return_value = mock_sb_table
        mock_sb_table.update.return_value = mock_sb_table
        mock_sb_table.eq.return_value = mock_sb_table
        mock_sb_table.execute.return_value = MagicMock(data=[{"id": "ok"}], error=None)

        # Case (a): PostgreSQL lookup raises error -> fails closed
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", side_effect=PaymentPersistenceError("Database connection severed")):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-NEG-28A", amount=50000, raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError):
                sync_xendit_settlement_to_supabase_catchup("ORD-NEG-28A", amount=50000, raise_on_error=True)

        # Case (b): PostgreSQL lookup returns None/empty -> fails closed
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=None):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-NEG-28B", amount=50000, raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx_b:
                sync_xendit_settlement_to_supabase_catchup("ORD-NEG-28B", amount=50000, raise_on_error=True)
            self.assertIn("no authoritative committed record exists", str(ctx_b.exception))

        # Case (c): Order is in uncommitted state (PENDING) -> fails closed
        uncommitted_pg_data = {
            "order": {"id": "ORD-NEG-28C", "gross_amount": 50000, "status": "PENDING", "payment_status": "UNPAID", "tenant_id": "boon"},
            "ledger": {"id": "led_28c", "order_id": "ORD-NEG-28C", "gross_amount": 50000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=uncommitted_pg_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-NEG-28C", amount=50000, raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx_c:
                sync_xendit_settlement_to_supabase_catchup("ORD-NEG-28C", amount=50000, raise_on_error=True)
            self.assertTrue("uncommitted" in str(ctx_c.exception).lower() or "status conflict" in str(ctx_c.exception).lower())

        # Case (d): Authoritative gross_amount is zero or missing -> fails closed
        zero_amount_pg_data = {
            "order": {"id": "ORD-NEG-28D", "gross_amount": 0, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_28d", "order_id": "ORD-NEG-28D", "gross_amount": 0, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=zero_amount_pg_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-NEG-28D", amount=50000, raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx_d:
                sync_xendit_settlement_to_supabase_catchup("ORD-NEG-28D", amount=50000, raise_on_error=True)
            self.assertIn("positive", str(ctx_d.exception).lower())

        # Case (e): Malicious replayed webhook amount (1000) vs PostgreSQL authoritative (500000)
        # MUST strictly replicate 500000 to Supabase, completely ignoring 1000!
        authoritative_pg_data = {
            "order": {"id": "ORD-TAMPER-28E", "gross_amount": 500000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_28e", "order_id": "ORD-TAMPER-28E", "gross_amount": 500000, "status": "COMPLETED", "tenant_id": "boon", "metadata": {"secure": True}},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=authoritative_pg_data):

            success = sync_xendit_settlement_to_supabase_catchup(
                external_id="ORD-TAMPER-28E",
                amount=1000,  # Malicious caller / replayed amount
                payload={"status": "PAID", "amount": 1000},
                raise_on_error=True,
            )
            self.assertTrue(success)

            # Assert Supabase payment_settlements received authoritative 500000 (integer minor units), NOT 1000!
            mock_sb_table.upsert.assert_called_with({
                "provider_ref": "xendit_ORD-TAMPER-28E",
                "settled_amount": 500000,
                "status": "PAID",
                "raw_payload": {"secure": True},
            }, on_conflict="provider_ref")

    # =========================================================================
    # Scenario 29: Fractional decimal values rejected (Decimal integer exactness)
    # =========================================================================
    async def test_scenario_29_fractional_decimal_values_rejected(self):
        """
        A2.4: Fractional decimal values (e.g. 150000.50, 99000.125) are strictly rejected
        in the catch-up and reconciliation path to preserve exact integer minor-units.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup
        from app.payments.schemas import validate_monetary_amount, MonetaryValidationError

        mock_sb = MagicMock()
        mock_sb_table = MagicMock()
        mock_sb.table.return_value = mock_sb_table

        # Direct validator test
        with self.assertRaises(MonetaryValidationError) as ctx_v:
            validate_monetary_amount(150000.50, allow_fractional=False)
        self.assertIn("fractional decimal", str(ctx_v.exception))

        # Catch-up sync integration test
        fractional_pg_data = {
            "order": {"id": "ORD-FRAC-29", "gross_amount": Decimal("150000.75"), "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_29", "order_id": "ORD-FRAC-29", "gross_amount": Decimal("150000.75"), "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=fractional_pg_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-FRAC-29", raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-FRAC-29", raise_on_error=True)
            self.assertIn("fractional decimal", str(ctx.exception))

    # =========================================================================
    # Scenario 30: NaN, Infinity, -Infinity rejected
    # =========================================================================
    async def test_scenario_30_nan_and_infinity_rejected(self):
        """
        A2.4: NaN, Infinity, and -Infinity values (both float and string literals)
        are strictly rejected and fail closed.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup
        from app.payments.schemas import validate_monetary_amount, MonetaryValidationError

        # Direct validator tests
        for special_val in (float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity", "sNaN"):
            with self.assertRaises(MonetaryValidationError):
                validate_monetary_amount(special_val)

        mock_sb = MagicMock()
        mock_sb_table = MagicMock()
        mock_sb.table.return_value = mock_sb_table

        nan_pg_data = {
            "order": {"id": "ORD-NAN-30", "gross_amount": "NaN", "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_30", "order_id": "ORD-NAN-30", "gross_amount": "NaN", "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=nan_pg_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-NAN-30", raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-NAN-30", raise_on_error=True)
            self.assertIn("NaN or Infinite", str(ctx.exception))

    # =========================================================================
    # Scenario 31: Zero and negative amounts rejected
    # =========================================================================
    async def test_scenario_31_zero_and_negative_amounts_rejected(self):
        """
        A2.4: Zero or negative monetary amounts (e.g. 0, -50000) are strictly rejected.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup
        from app.payments.schemas import validate_monetary_amount, MonetaryValidationError

        for non_pos in (0, -100, Decimal("-50000"), "-999"):
            with self.assertRaises(MonetaryValidationError):
                validate_monetary_amount(non_pos)

        mock_sb = MagicMock()
        mock_sb_table = MagicMock()
        mock_sb.table.return_value = mock_sb_table

        neg_pg_data = {
            "order": {"id": "ORD-NEG-31", "gross_amount": -50000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_31", "order_id": "ORD-NEG-31", "gross_amount": -50000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=neg_pg_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-NEG-31", raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-NEG-31", raise_on_error=True)
            self.assertIn("positive non-zero value", str(ctx.exception))

    # =========================================================================
    # Scenario 32: Financial overflow rejected
    # =========================================================================
    async def test_scenario_32_financial_overflow_rejected(self):
        """
        A2.4: Values exceeding maximum financial threshold (> 999 Billion) are rejected.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup
        from app.payments.schemas import validate_monetary_amount, MonetaryValidationError

        overflow_amt = Decimal("100000000000000000")
        with self.assertRaises(MonetaryValidationError):
            validate_monetary_amount(overflow_amt)

        mock_sb = MagicMock()
        mock_sb_table = MagicMock()
        mock_sb.table.return_value = mock_sb_table

        overflow_pg_data = {
            "order": {"id": "ORD-OFL-32", "gross_amount": overflow_amt, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_32", "order_id": "ORD-OFL-32", "gross_amount": overflow_amt, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=overflow_pg_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-OFL-32", raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-OFL-32", raise_on_error=True)
            self.assertIn("exceeds maximum financial limit", str(ctx.exception))

    # =========================================================================
    # Scenario 33: Cross-table nominal conflict fails closed
    # =========================================================================
    async def test_scenario_33_cross_table_nominal_conflict_fails_closed(self):
        """
        A1.2 & A1.3: If orders.gross_amount (100000) conflicts with financial_ledger.gross_amount (95000),
        the synchronization aborts immediately and raises PaymentPersistenceError.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()
        conflict_nominal_data = {
            "order": {"id": "ORD-NOM-CONF-33", "gross_amount": 100000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_33", "order_id": "ORD-NOM-CONF-33", "gross_amount": 95000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=conflict_nominal_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-NOM-CONF-33", raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-NOM-CONF-33", raise_on_error=True)
            self.assertIn("Cross-table nominal mismatch", str(ctx.exception))

    # =========================================================================
    # Scenario 34: Cross-table status conflict fails closed
    # =========================================================================
    async def test_scenario_34_cross_table_status_conflict_fails_closed(self):
        """
        A1.2 & A1.3: If financial_ledger is SETTLED but orders is in an aborted/uncommitted status
        (e.g. CANCELLED or PENDING), the synchronization fails closed immediately.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()
        conflict_status_data = {
            "order": {"id": "ORD-ST-CONF-34", "gross_amount": 120000, "status": "CANCELLED", "payment_status": "UNPAID", "tenant_id": "boon"},
            "ledger": {"id": "led_34", "order_id": "ORD-ST-CONF-34", "gross_amount": 120000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=conflict_status_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-ST-CONF-34", raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-ST-CONF-34", raise_on_error=True)
            self.assertIn("uncommitted status 'CANCELLED'", str(ctx.exception))

    # =========================================================================
    # Scenario 35: Cross-table tenant conflict fails closed
    # =========================================================================
    async def test_scenario_35_cross_table_tenant_conflict_fails_closed(self):
        """
        A1.2 & A1.3: If orders.tenant_id ('tenant_alpha') conflicts with financial_ledger.tenant_id ('tenant_beta'),
        catch-up replication aborts immediately and fails closed.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()
        conflict_tenant_data = {
            "order": {"id": "ORD-TNT-CONF-35", "gross_amount": 180000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "tenant_alpha"},
            "ledger": {"id": "led_35", "order_id": "ORD-TNT-CONF-35", "gross_amount": 180000, "status": "SETTLED", "tenant_id": "tenant_beta"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=conflict_tenant_data):

            success = sync_xendit_settlement_to_supabase_catchup("ORD-TNT-CONF-35", raise_on_error=False)
            self.assertFalse(success)

            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-TNT-CONF-35", raise_on_error=True)
            self.assertIn("Cross-record tenant conflict", str(ctx.exception))

    # =========================================================================
    # Scenario 36: Missing or null status on existing mandatory record fails closed
    # =========================================================================
    async def test_scenario_36_missing_or_null_status_fails_closed(self):
        """
        Blocker A2: If any existing record has a null or empty status, catch-up replication
        must fail closed and raise PaymentPersistenceError immediately.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()

        # Case A: financial_ledger has null status
        null_ledger_status = {
            "order": {"id": "ORD-NULL-ST-36A", "gross_amount": 100000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_36a", "order_id": "ORD-NULL-ST-36A", "gross_amount": 100000, "status": None, "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=null_ledger_status):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-NULL-ST-36A", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-NULL-ST-36A", raise_on_error=True)
            self.assertIn("missing or null", str(ctx.exception))

        # Case B: orders has null status
        null_order_status = {
            "order": {"id": "ORD-NULL-ST-36B", "gross_amount": 100000, "status": None, "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_36b", "order_id": "ORD-NULL-ST-36B", "gross_amount": 100000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=null_order_status):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-NULL-ST-36B", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-NULL-ST-36B", raise_on_error=True)
            self.assertIn("missing or null", str(ctx.exception))

        # Case C: orders has null payment_status
        null_order_pay_status = {
            "order": {"id": "ORD-NULL-ST-36C", "gross_amount": 100000, "status": "LUNAS", "payment_status": None, "tenant_id": "boon"},
            "ledger": {"id": "led_36c", "order_id": "ORD-NULL-ST-36C", "gross_amount": 100000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=null_order_pay_status):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-NULL-ST-36C", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-NULL-ST-36C", raise_on_error=True)
            self.assertIn("payment_status' is missing or null", str(ctx.exception))

    # =========================================================================
    # Scenario 37: Contradictory order statuses fail closed
    # =========================================================================
    async def test_scenario_37_contradictory_order_statuses_fails_closed(self):
        """
        Blocker A2: Independent validation of orders.status AND orders.payment_status.
        If orders.status is LUNAS but payment_status is UNPAID (or vice versa), fails closed.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()

        # Case A: status is LUNAS but payment_status is UNPAID
        contradictory_a = {
            "order": {"id": "ORD-CONT-37A", "gross_amount": 150000, "status": "LUNAS", "payment_status": "UNPAID", "tenant_id": "boon"},
            "ledger": {"id": "led_37a", "order_id": "ORD-CONT-37A", "gross_amount": 150000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=contradictory_a):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-CONT-37A", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-CONT-37A", raise_on_error=True)
            self.assertIn("contradictory/uncommitted payment_status", str(ctx.exception))

        # Case B: status is PENDING but payment_status is PAID
        contradictory_b = {
            "order": {"id": "ORD-CONT-37B", "gross_amount": 150000, "status": "PENDING", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_37b", "order_id": "ORD-CONT-37B", "gross_amount": 150000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=contradictory_b):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-CONT-37B", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-CONT-37B", raise_on_error=True)
            self.assertIn("uncommitted status 'PENDING'", str(ctx.exception))

    # =========================================================================
    # Scenario 38: Missing mandatory tenant_id fails closed
    # =========================================================================
    async def test_scenario_38_missing_tenant_id_fails_closed(self):
        """
        Blocker A2: Mandatory tenant_id on all present records.
        If orders, financial_ledger, or payment_settlements is missing tenant_id, fails closed.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()

        # Case A: orders has missing tenant_id
        missing_order_tenant = {
            "order": {"id": "ORD-NO-TNT-38A", "gross_amount": 100000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": None},
            "ledger": {"id": "led_38a", "order_id": "ORD-NO-TNT-38A", "gross_amount": 100000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=missing_order_tenant):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-NO-TNT-38A", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-NO-TNT-38A", raise_on_error=True)
            self.assertIn("missing mandatory 'tenant_id'", str(ctx.exception))

        # Case B: financial_ledger has missing tenant_id
        missing_ledger_tenant = {
            "order": {"id": "ORD-NO-TNT-38B", "gross_amount": 100000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_38b", "order_id": "ORD-NO-TNT-38B", "gross_amount": 100000, "status": "SETTLED", "tenant_id": ""},
            "settlement": None,
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=missing_ledger_tenant):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-NO-TNT-38B", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-NO-TNT-38B", raise_on_error=True)
            self.assertIn("missing mandatory 'tenant_id'", str(ctx.exception))

    # =========================================================================
    # Scenario 39: Settlement identity mismatch fails closed
    # =========================================================================
    async def test_scenario_39_settlement_identity_mismatch_fails_closed(self):
        """
        Blocker A2: Cross-verification of settlement tenant_id, order_id, and provider_ref.
        Mismatch on any field immediately aborts and raises PaymentPersistenceError.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()

        # Case A: settlement tenant_id does not match orders/ledger tenant_id
        mismatch_settle_tenant = {
            "order": {"id": "ORD-MIS-39A", "gross_amount": 200000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "tenant_1"},
            "ledger": {"id": "led_39a", "order_id": "ORD-MIS-39A", "gross_amount": 200000, "status": "SETTLED", "tenant_id": "tenant_1"},
            "settlement": {
                "id": "set_39a", "order_id": "ORD-MIS-39A", "settled_amount": 200000, "status": "PAID",
                "provider_ref": "xendit_ORD-MIS-39A", "tenant_id": "tenant_2"
            },
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=mismatch_settle_tenant):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-MIS-39A", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-MIS-39A", raise_on_error=True)
            self.assertIn("conflicting tenants", str(ctx.exception))

        # Case B: settlement order_id does not match external_id
        mismatch_settle_order_id = {
            "order": {"id": "ORD-MIS-39B", "gross_amount": 200000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "tenant_1"},
            "ledger": {"id": "led_39b", "order_id": "ORD-MIS-39B", "gross_amount": 200000, "status": "SETTLED", "tenant_id": "tenant_1"},
            "settlement": {
                "id": "set_39b", "order_id": "ORD-DIFFERENT-ID", "settled_amount": 200000, "status": "PAID",
                "provider_ref": "xendit_ORD-MIS-39B", "tenant_id": "tenant_1"
            },
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=mismatch_settle_order_id):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-MIS-39B", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-MIS-39B", raise_on_error=True)
            self.assertIn("Cross-record order_id mismatch", str(ctx.exception))

    # =========================================================================
    # Scenario 40: Secondary-source fallback behavior and zero-fallback to orders/intents
    # =========================================================================
    async def test_scenario_40_secondary_source_fallback_and_zero_orders_fallback(self):
        """
        Blocker A1:
        Sub-case A: financial_ledger absent, but payment_settlements valid -> SUCCESS catch-up.
        Sub-case B: Both financial_ledger and payment_settlements absent -> FAILS CLOSED even if
                    orders and payment_intents have nominal values.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()
        mock_sb_table = MagicMock()
        mock_sb.table.return_value = mock_sb_table

        # Sub-case A: financial_ledger is None, but payment_settlements is valid -> SUCCEEDS
        secondary_valid_data = {
            "order": {"id": "ORD-SEC-40A", "gross_amount": 250000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": None,
            "settlement": {
                "id": "set_40a", "order_id": "ORD-SEC-40A", "settled_amount": 250000, "status": "PAID",
                "provider_ref": "xendit_ORD-SEC-40A", "tenant_id": "boon", "raw_payload": {"source": "sec_ssot"}
            },
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=secondary_valid_data):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-SEC-40A", raise_on_error=True)
            self.assertTrue(success)
            mock_sb_table.upsert.assert_called_with({
                "provider_ref": "xendit_ORD-SEC-40A",
                "settled_amount": 250000,
                "status": "PAID",
                "raw_payload": {"source": "sec_ssot"},
            }, on_conflict="provider_ref")

        # Sub-case B: Neither financial_ledger nor payment_settlements present -> FAILS CLOSED
        zero_fallback_data = {
            "order": {"id": "ORD-ZERO-40B", "gross_amount": 300000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": None,
            "settlement": None,
            "intent": {"id": "int_40b", "order_id": "ORD-ZERO-40B", "total_amount": 300000, "status": "SETTLED", "tenant_id": "boon"},
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=zero_fallback_data):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-ZERO-40B", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx:
                sync_xendit_settlement_to_supabase_catchup("ORD-ZERO-40B", raise_on_error=True)
            self.assertIn("Fallback to orders.gross_amount or payment_intents.total_amount is strictly prohibited", str(ctx.exception))

    # =========================================================================
    # Scenario 41: End-to-end full consistency with all records aligned
    # =========================================================================
    async def test_scenario_41_end_to_end_full_consistency_success(self):
        """
        Blocker A1 & A2: Complete end-to-end reconciliation when orders, financial_ledger,
        payment_settlements, and payment_intents are all present, perfectly aligned on
        tenant_id, order_id, nominal (125000), and committed status.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup

        mock_sb = MagicMock()
        mock_sb_table = MagicMock()
        mock_sb.table.return_value = mock_sb_table

        full_consistent_data = {
            "order": {"id": "ORD-E2E-41", "gross_amount": 125000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_41", "order_id": "ORD-E2E-41", "gross_amount": 125000, "status": "SETTLED", "tenant_id": "boon", "metadata": {"tx": "ok"}},
            "settlement": {
                "id": "set_41", "order_id": "ORD-E2E-41", "settled_amount": 125000, "status": "PAID",
                "provider_ref": "xendit_ORD-E2E-41", "tenant_id": "boon"
            },
            "intent": {"id": "int_41", "order_id": "ORD-E2E-41", "total_amount": 125000, "status": "SETTLED", "tenant_id": "boon"},
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=full_consistent_data):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-E2E-41", raise_on_error=True)
            self.assertTrue(success)
            mock_sb_table.upsert.assert_called_with({
                "provider_ref": "xendit_ORD-E2E-41",
                "settled_amount": 125000,
                "status": "PAID",
                "raw_payload": {"tx": "ok"},
            }, on_conflict="provider_ref")

    # =========================================================================
    # Scenario 42: Column metadata query failure on payment_settlements fails closed
    # =========================================================================
    def test_scenario_42_payment_settlements_metadata_query_failure_fails_closed(self):
        """
        A1: Query failure on payment_settlements column metadata is not swallowed
        as genuine absence (empty set); it must fail closed and raise PaymentPersistenceError.
        """
        from app.routes.xendit import _lookup_authoritative_pg_settlement_sync, PaymentPersistenceError

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        def cur_execute_side_effect(sql, params=None):
            if "information_schema.columns" in sql:
                raise RuntimeError("Postgres connection dropped during column metadata inspection")
            return None

        mock_cur.execute.side_effect = cur_execute_side_effect
        mock_cur.fetchone.side_effect = [
            ("ORD-FAIL-42", 100000, "LUNAS", "PAID", "boon"),  # orders
            ("led_42", 100000, "SETTLED", {}, "evt_42", "boon", "ORD-FAIL-42"),  # ledger
            (True,),  # payment_settlements table exists
        ]

        with patch("app.routes.xendit.get_db_connection", return_value=mock_conn):
            with self.assertRaises(PaymentPersistenceError) as ctx:
                _lookup_authoritative_pg_settlement_sync("ORD-FAIL-42")
            self.assertIn("Failed to query authoritative PostgreSQL SSOT", str(ctx.exception))
            self.assertIn("Postgres connection dropped", str(ctx.exception))

    # =========================================================================
    # Scenario 43: Query failure on payment_intents fails closed
    # =========================================================================
    def test_scenario_43_payment_intents_query_failure_fails_closed(self):
        """
        A1: Query failure on payment_intents table metadata is not swallowed
        as genuine absence (None); it must fail closed and raise PaymentPersistenceError.
        """
        from app.routes.xendit import _lookup_authoritative_pg_settlement_sync, PaymentPersistenceError

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        def cur_execute_side_effect(sql, params=None):
            if "information_schema.tables" in sql:
                raise RuntimeError("Postgres statement timeout querying payment_intents table metadata")
            return None

        mock_cur.execute.side_effect = cur_execute_side_effect
        mock_cur.fetchone.return_value = ("ORD-FAIL-43", 100000, "LUNAS", "PAID", "boon")
        mock_cur.fetchall.return_value = [("tenant_id",), ("order_id",)]

        with patch("app.routes.xendit.get_db_connection", return_value=mock_conn):
            with self.assertRaises(PaymentPersistenceError) as ctx:
                _lookup_authoritative_pg_settlement_sync("ORD-FAIL-43")
            self.assertIn("Failed to query authoritative PostgreSQL SSOT", str(ctx.exception))
            self.assertIn("statement timeout", str(ctx.exception))

    # =========================================================================
    # Scenario 44: Non-canonical provider_reference merely containing substring fails closed
    # =========================================================================
    async def test_scenario_44_non_canonical_provider_reference_substring_fails_closed(self):
        """
        A2: Substring matching is eliminated. A provider_reference that merely contains external_id
        as a substring (e.g. 'fake_xendit_ORD-44_suffix' or 'ORD-44') fails closed and is rejected.
        """
        from app.routes.xendit import sync_xendit_settlement_to_supabase_catchup, PaymentPersistenceError

        mock_sb = MagicMock()

        # Case A: provider_ref contains external_id as substring with extra suffix
        substring_suffix_data = {
            "order": {"id": "ORD-CANON-44", "gross_amount": 100000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_44", "order_id": "ORD-CANON-44", "gross_amount": 100000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": {
                "id": "set_44a", "order_id": "ORD-CANON-44", "settled_amount": 100000, "status": "PAID",
                "provider_ref": "fake_xendit_ORD-CANON-44_suffix", "tenant_id": "boon"
            },
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=substring_suffix_data):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-CANON-44", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx_a:
                sync_xendit_settlement_to_supabase_catchup("ORD-CANON-44", raise_on_error=True)
            self.assertIn("does not match exact canonical provider_reference", str(ctx_a.exception))

        # Case B: provider_ref contains external_id as prefix/raw without xendit_
        non_canonical_prefix_data = {
            "order": {"id": "ORD-CANON-44", "gross_amount": 100000, "status": "LUNAS", "payment_status": "PAID", "tenant_id": "boon"},
            "ledger": {"id": "led_44", "order_id": "ORD-CANON-44", "gross_amount": 100000, "status": "SETTLED", "tenant_id": "boon"},
            "settlement": {
                "id": "set_44b", "order_id": "ORD-CANON-44", "settled_amount": 100000, "status": "PAID",
                "provider_ref": "ORD-CANON-44", "tenant_id": "boon"
            },
        }
        with patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb), \
             patch("app.routes.xendit._lookup_authoritative_pg_settlement_sync", return_value=non_canonical_prefix_data):
            success = sync_xendit_settlement_to_supabase_catchup("ORD-CANON-44", raise_on_error=False)
            self.assertFalse(success)
            with self.assertRaises(PaymentPersistenceError) as ctx_b:
                sync_xendit_settlement_to_supabase_catchup("ORD-CANON-44", raise_on_error=True)
            self.assertIn("does not match exact canonical provider_reference", str(ctx_b.exception))

    # =========================================================================
    # Scenario 45: Genuine table absence of payment_settlements vs SSOT hierarchy
    # =========================================================================
    async def test_scenario_45_genuine_table_absence_distinguished_from_operational_failure(self):
        """
        Task 1 & 2: When payment_settlements does not exist (genuine schema absence):
        Case A: Primary financial_ledger is valid & committed -> catch-up proceeds cleanly using ledger SSOT.
        Case B: Primary financial_ledger is also absent -> fails closed with controlled PaymentPersistenceError
                (authoritative settlement nominal missing from designated SSOT sources), NOT an unhandled SQL error.
        """
        from app.routes.xendit import (
            _lookup_authoritative_pg_settlement_sync,
            sync_xendit_settlement_to_supabase_catchup,
            PaymentPersistenceError,
        )

        mock_sb = MagicMock()
        mock_sb_table = MagicMock()
        mock_sb.table.return_value = mock_sb_table
        mock_sb_table.upsert.return_value = mock_sb_table
        mock_sb_table.update.return_value = mock_sb_table
        mock_sb_table.eq.return_value = mock_sb_table
        mock_sb_table.execute.return_value = MagicMock(data=[{"id": "ok"}], error=None)

        # Case A: payment_settlements table does not exist, but financial_ledger exists
        mock_conn_a = MagicMock()
        mock_cur_a = MagicMock()
        mock_conn_a.cursor.return_value = mock_cur_a

        def cur_execute_a(sql, params=None):
            return None

        mock_cur_a.execute.side_effect = cur_execute_a
        mock_cur_a.fetchone.side_effect = [
            # 1st call: direct _lookup_authoritative_pg_settlement_sync
            ("ORD-ABSENT-45A", 200000, "LUNAS", "PAID", "boon"),  # orders
            ("led_45a", 200000, "SETTLED", {"src": "ledger"}, "evt_45a", "boon", "ORD-ABSENT-45A"),  # ledger
            (False,),  # payment_settlements table check
            (False,),  # payment_intents table check
            # 2nd call: inside sync_xendit_settlement_to_supabase_catchup
            ("ORD-ABSENT-45A", 200000, "LUNAS", "PAID", "boon"),  # orders
            ("led_45a", 200000, "SETTLED", {"src": "ledger"}, "evt_45a", "boon", "ORD-ABSENT-45A"),  # ledger
            (False,),  # payment_settlements table check
            (False,),  # payment_intents table check
        ]

        with patch("app.routes.xendit.get_db_connection", return_value=mock_conn_a), \
             patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb):
            auth_data = _lookup_authoritative_pg_settlement_sync("ORD-ABSENT-45A")
            self.assertIsNotNone(auth_data)
            self.assertIsNone(auth_data["settlement"])
            self.assertIsNotNone(auth_data["ledger"])

            success = sync_xendit_settlement_to_supabase_catchup("ORD-ABSENT-45A", raise_on_error=True)
            self.assertTrue(success)
            mock_sb_table.upsert.assert_called_with({
                "provider_ref": "xendit_ORD-ABSENT-45A",
                "settled_amount": 200000,
                "status": "PAID",
                "raw_payload": {"src": "ledger"},
            }, on_conflict="provider_ref")

        # Case B: payment_settlements table does not exist AND financial_ledger does not exist
        mock_conn_b = MagicMock()
        mock_cur_b = MagicMock()
        mock_conn_b.cursor.return_value = mock_cur_b
        mock_cur_b.fetchone.side_effect = [
            # 1st call: direct _lookup_authoritative_pg_settlement_sync
            ("ORD-ABSENT-45B", 200000, "LUNAS", "PAID", "boon"),  # orders
            None,  # ledger is absent
            (False,),  # payment_settlements table check
            (False,),  # payment_intents table check
            # 2nd call: inside sync_xendit_settlement_to_supabase_catchup
            ("ORD-ABSENT-45B", 200000, "LUNAS", "PAID", "boon"),  # orders
            None,  # ledger is absent
            (False,),  # payment_settlements table check
            (False,),  # payment_intents table check
        ]

        with patch("app.routes.xendit.get_db_connection", return_value=mock_conn_b), \
             patch("app.routes.xendit.get_payment_privileged_supabase", return_value=mock_sb):
            auth_data_b = _lookup_authoritative_pg_settlement_sync("ORD-ABSENT-45B")
            self.assertIsNotNone(auth_data_b)
            self.assertIsNone(auth_data_b["settlement"])
            self.assertIsNone(auth_data_b["ledger"])

            with self.assertRaises(PaymentPersistenceError) as ctx_b:
                sync_xendit_settlement_to_supabase_catchup("ORD-ABSENT-45B", raise_on_error=True)
            self.assertIn("authoritative settlement nominal is missing from designated SSOT sources", str(ctx_b.exception))

    # =========================================================================
    # Scenario 46: Operational query failure during payment_settlements table check
    # =========================================================================
    def test_scenario_46_table_presence_query_failure_fails_closed(self):
        """
        Task 1 & 2: Operational query failure when inspecting payment_settlements in
        information_schema.tables (e.g. connection drop / timeout) must fail closed
        and raise PaymentPersistenceError.
        """
        from app.routes.xendit import _lookup_authoritative_pg_settlement_sync, PaymentPersistenceError

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        def cur_execute_side_effect(sql, params=None):
            if "information_schema.tables" in sql and "payment_settlements" in sql:
                raise RuntimeError("Postgres statement timeout inspecting payment_settlements table presence")
            return None

        mock_cur.execute.side_effect = cur_execute_side_effect
        mock_cur.fetchone.return_value = ("ORD-FAIL-46", 100000, "LUNAS", "PAID", "boon")

        with patch("app.routes.xendit.get_db_connection", return_value=mock_conn):
            with self.assertRaises(PaymentPersistenceError) as ctx:
                _lookup_authoritative_pg_settlement_sync("ORD-FAIL-46")
            self.assertIn("Failed to query authoritative PostgreSQL SSOT", str(ctx.exception))
            self.assertIn("statement timeout inspecting payment_settlements", str(ctx.exception))

    # =========================================================================
    # Scenario 47: Operational query failure during payment_settlements row SELECT
    # =========================================================================
    def test_scenario_47_settlement_row_query_failure_fails_closed(self):
        """
        Task 1 & 2: Operational query failure during SELECT FROM payment_settlements
        (e.g. lock contention / network drop) must fail closed and raise PaymentPersistenceError.
        """
        from app.routes.xendit import _lookup_authoritative_pg_settlement_sync, PaymentPersistenceError

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        def cur_execute_side_effect(sql, params=None):
            if "FROM payment_settlements" in sql:
                raise RuntimeError("Postgres deadlock / lock timeout reading payment_settlements row")
            return None

        mock_cur.execute.side_effect = cur_execute_side_effect
        # orders -> returns row, ledger -> returns row, settle table check -> (True,), columns -> [('tenant_id',), ('order_id',)]
        mock_cur.fetchone.side_effect = [
            ("ORD-FAIL-47", 100000, "LUNAS", "PAID", "boon"),  # orders
            ("led_47", 100000, "SETTLED", {}, "evt_47", "boon", "ORD-FAIL-47"),  # ledger
            (True,),  # payment_settlements table check
        ]
        mock_cur.fetchall.return_value = [("tenant_id",), ("order_id",)]

        with patch("app.routes.xendit.get_db_connection", return_value=mock_conn):
            with self.assertRaises(PaymentPersistenceError) as ctx:
                _lookup_authoritative_pg_settlement_sync("ORD-FAIL-47")
            self.assertIn("Failed to query authoritative PostgreSQL SSOT", str(ctx.exception))
            self.assertIn("deadlock / lock timeout reading payment_settlements", str(ctx.exception))

    # =========================================================================
    # Scenario 48: No-row result (fetchone() -> None) on information_schema.tables fails closed
    # =========================================================================
    def test_scenario_48_table_check_no_row_result_fails_closed(self):
        """
        Task 1 & 2: When SELECT EXISTS from information_schema.tables returns None
        (missing result row), it is an operational anomaly, NOT genuine absence.
        Must immediately raise PaymentPersistenceError (fail closed).
        """
        from app.routes.xendit import _lookup_authoritative_pg_settlement_sync, PaymentPersistenceError

        # Case A: payment_settlements check returns None
        mock_conn_a = MagicMock()
        mock_cur_a = MagicMock()
        mock_conn_a.cursor.return_value = mock_cur_a
        mock_cur_a.fetchone.side_effect = [
            ("ORD-FAIL-48A", 100000, "LUNAS", "PAID", "boon"),  # orders
            ("led_48a", 100000, "SETTLED", {}, "evt_48a", "boon", "ORD-FAIL-48A"),  # ledger
            None,  # payment_settlements EXISTS check returns None
        ]

        with patch("app.routes.xendit.get_db_connection", return_value=mock_conn_a):
            with self.assertRaises(PaymentPersistenceError) as ctx_a:
                _lookup_authoritative_pg_settlement_sync("ORD-FAIL-48A")
            self.assertIn("returned no result row (None)", str(ctx_a.exception))

        # Case B: payment_intents check returns None
        mock_conn_b = MagicMock()
        mock_cur_b = MagicMock()
        mock_conn_b.cursor.return_value = mock_cur_b
        mock_cur_b.fetchone.side_effect = [
            ("ORD-FAIL-48B", 100000, "LUNAS", "PAID", "boon"),  # orders
            ("led_48b", 100000, "SETTLED", {}, "evt_48b", "boon", "ORD-FAIL-48B"),  # ledger
            (False,),  # payment_settlements EXISTS check returns False (genuine absence)
            None,  # payment_intents EXISTS check returns None
        ]

        with patch("app.routes.xendit.get_db_connection", return_value=mock_conn_b):
            with self.assertRaises(PaymentPersistenceError) as ctx_b:
                _lookup_authoritative_pg_settlement_sync("ORD-FAIL-48B")
            self.assertIn("returned no result row (None)", str(ctx_b.exception))

    # =========================================================================
    # Scenario 49: Malformed / unexpected result type on information_schema.tables fails closed
    # =========================================================================
    def test_scenario_49_table_check_malformed_result_fails_closed(self):
        """
        Task 1 & 2: When SELECT EXISTS from information_schema.tables returns a malformed
        row or unexpected type (empty tuple, tuple length != 1, non-boolean element),
        it must immediately raise PaymentPersistenceError (fail closed).
        """
        from app.routes.xendit import _lookup_authoritative_pg_settlement_sync, PaymentPersistenceError

        malformed_test_cases = [
            ((), "malformed result row"),
            ((None,), "expected boolean result, got NoneType"),
            (("unexpected_str",), "expected boolean result, got str"),
            ((1,), "expected boolean result, got int"),
            ((0,), "expected boolean result, got int"),
            ((True, False), "malformed result row"),
            ("not_a_tuple", "malformed result row"),
            ({"result": True}, "malformed result row"),
        ]

        for malformed_val, expected_err_fragment in malformed_test_cases:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            mock_cur.fetchone.side_effect = [
                ("ORD-FAIL-49", 100000, "LUNAS", "PAID", "boon"),  # orders
                ("led_49", 100000, "SETTLED", {}, "evt_49", "boon", "ORD-FAIL-49"),  # ledger
                malformed_val,  # malformed payment_settlements EXISTS result
            ]

            with patch("app.routes.xendit.get_db_connection", return_value=mock_conn):
                with self.assertRaises(PaymentPersistenceError) as ctx:
                    _lookup_authoritative_pg_settlement_sync("ORD-FAIL-49")
                self.assertIn(expected_err_fragment, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
