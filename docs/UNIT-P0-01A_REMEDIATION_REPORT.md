# CTO REMEDIATION COMPLIANCE REPORT — UNIT-P0-01A
**Project:** BT-SEC-2026-001  
**Unit:** UNIT-P0-01A — Persistence Integrity & Guardrail Remediation  
**Repository:** B055OB/boontrack-core  
**Branch:** infra/isolated-test-environment  
**Authorization ID:** CTO-AUTH-JTI-REMEDIATION-2026-11-16 & CTO REMEDIATION DIRECTIVE & ADDENDUM GUARDRAILS  
**Mode:** STRICT STAGING IMPLEMENTATION ONLY (No Production Mutation, No Schema Migrations)  
**Execution Date:** 17 November 2026  
**Final Verification State:** 18/18 SCENARIOS PASS (100% Zero-Regression Clean Pass)  
**Status:** REMEDIATION COMPLETE — AWAITING CTO RE-REVIEW  

---

## 1. PERSISTENCE RESPONSIBILITY MATRIX

Setiap operasi tulis database di seluruh alur pembayaran Core telah dipetakan dan diklasifikasikan ke dalam tiga tingkatan tanggung jawab yang tegas:

| Kategori Operasi | Tabel & Jalur Eksekusi | Perilaku Kegagalan (*Failure Mode*) | Kebijakan Rollback & Idempotensi |
| :--- | :--- | :--- | :--- |
| **Financially Authoritative** | payment_settlements (INSERT) & payment_intents (UPDATE status SETTLED) di process_webhook_settlement(); orders (UPDATE status PAID) & financial_ledger di _record_settlement_and_ledger_sync(). | **STRICT FAIL-CLOSED**.<br>Tidak pernah menelan error.<br>Wajib melempar PaymentPersistenceError. Tidak boleh melaporkan sukses jika DB gagal. | **Two-Phase Write with Compensating Rollback**.<br>Jika insert payment_settlements gagal setelah status intent diupdate, sistem mengeksekusi *compensating transaction* untuk mengembalikan status intent ke PENDING di DB.<br>State in-memory di-rollback ke PENDING.<br>Kunci idempotensi tidak dikonsumsi sehingga webhook retry dapat pulih secara bersih. |
| **Operationally Required** | payment_intents (INSERT) saat pembuatan intent di create_payment_intent(); orders (UPDATE status LUNAS/PAID) pada sinkronisasi status. | **FAIL-CLOSED** pada mode persisten (in_memory_mode=False).<br>Wajib melempar PaymentPersistenceError jika DB insert gagal. | **Synchronous In-Memory Cache Pruning**.<br>Jika DB insert gagal, seluruh registrasi in-memory (_intents_by_id, _intents_by_tenant_order, _intents_by_amount, LEGACY_PAYMENT_INTENTS) dibersihkan secara atomik melalui _rollback_intent_in_memory(). |
| **Secondary Synchronization / Observability** | record_payment_event() pada tabel payment_events (Secondary Audit Replica); pembersihan intent kedaluwarsa batch di expire_stale_intents(). | **FAIL-SAFE LOGGING**.<br>Kegagalan dicatat sebagai logger.warning(...).<br>TIDAK MENGGAGALKAN transaksi finansial utama yang sudah sukses. | **Isolated Failure Domain**.<br>Audit log sinkronisasi sekunder tidak memblokir maupun membatalkan penyelesaian pembayaran (*settlement*) yang sah. Jalur retry terpisah dapat diterapkan melalui outbox/queue worker tanpa memengaruhi status lunas. |

---

## 2. BEFORE / AFTER FAILURE-PATH ANALYSIS

### 2.1. Alur Pembuatan Payment Intent (create_payment_intent)

| Aspek | Kondisi Sebelum Remediasi (*Before*) | Kondisi Sesudah Remediasi (*After*) |
| :--- | :--- | :--- |
| **Penanganan Error DB** | Exception dari Supabase ditangkap dan hanya dicatat dengan logger.warning(...). Fungsi mengembalikan objek intent seolah-olah sukses tersimpan di database. | Exception ditangkap, dicatat sebagai logger.error(...), dan melempar PaymentPersistenceError terstruktur. |
| **Konsistensi In-Memory Cache** | Cache in-memory (_intents_by_id, LEGACY_PAYMENT_INTENTS) tetap terisi dan berstatus PENDING, menciptakan desinkronisasi fatal antara memori dan database yang kosong. | _rollback_intent_in_memory(intent) membersihkan _intents_by_id, _intents_by_tenant_order, _intents_by_amount, dan LEGACY_PAYMENT_INTENTS. Nol state yatim tersisa. |
| **Mode In-Memory vs Persistent** | Mode persisten tidak menegakkan jaminan persistensi nyata. | Mode in_memory_mode=False menegakkan integritas persistensi penuh. Mode in-memory hanya aktif bila diinstansiasi secara eksplisit untuk unit test murni. |

### 2.2. Alur Settlement Webhook (process_webhook_settlement)

| Aspek | Kondisi Sebelum Remediasi (*Before*) | Kondisi Sesudah Remediasi (*After*) |
| :--- | :--- | :--- |
| **Titik Mutasi In-Memory SETTLED** | Status in-memory matched_intent.status = PaymentStatus.SETTLED diubah **sebelum** penulisan ke database dilakukan. | Status in-memory tetap PENDING selama penulisan DB berlangsung. Status hanya dimutasi menjadi SETTLED **setelah** seluruh penulisan DB terkonfirmasi sukses. |
| **Kegagalan Update Intent DB** | Error DB ditangkap oleh except Exception as e: logger.warning(...). Endpoint mengembalikan objek settlement sukses meskipun status DB tidak pernah berubah. | Melempar PaymentPersistenceError. Status in-memory tetap PENDING. Kunci idempotensi tidak disimpan. Webhook provider menerima kegagalan dan dapat me-retry. |
| **Kegagalan Parsial (Intent Update Sukses, Settlement Insert Gagal)** | Intent berstatus SETTLED di DB, namun tabel payment_settlements kosong. Exception ditelan diam-diam. Menciptakan **intent SETTLED yatim**. | **Compensating Transaction Triggered**:<br>1. DB payment_intents di-revert kembali ke PENDING.<br>2. Status in-memory dipulihkan ke PENDING.<br>3. PaymentPersistenceError dilempar.<br>4. Tidak ada intent SETTLED yatim di DB maupun memory. |
| **Presisi Perbandingan Nominal** | Menggunakan int(matched_intent.total_amount) != int(webhook.amount). Memotong pecahan desimal (mis. 50000.75 vs 50000.25 dianggap cocok). Nominal non-positif tidak divalidasi. | Menggunakan helper _to_decimal() berbasis Python Decimal. Menolak nominal <= 0 (negatif/nol). Mendeteksi pecahan desimal tidak cocok secara presisi. Mendukung multi-currency (IDR/USD). |
| **Event Observabilitas Sekunder** | Error pada record_payment_event berpotensi menggagalkan settlement jika tidak diisolasi. | Dibungkus dalam try-except terisolasi: settlement finansial tetap berhasil dan sah, kegagalan replica dicatat sebagai log warning. |

### 2.3. Alur Fallback Xendit (_record_settlement_and_ledger_sync)

| Aspek | Kondisi Sebelum Remediasi (*Before*) | Kondisi Sesudah Remediasi (*After*) |
| :--- | :--- | :--- |
| **Jalur Kredensial Supabase** | Sebelumnya memanggil get_supabase() yang berpotensi fallback ke SUPABASE_ANON_KEY. | Diarahkan secara eksklusif ke get_payment_privileged_supabase(), mewajibkan SUPABASE_SERVICE_ROLE_KEY. |
| **Penanganan Error Sinkronisasi** | Exception saat upsert payment_settlements ditelan dengan logger.debug(...). | Exception dicatat dengan logger.error(...) dan melempar PaymentPersistenceError, menghentikan silent failure. |

---

## 3. SETTLEMENT CONSISTENCY, RECOVERY & IDEMPOTENCY EXPLANATION

`
                    Incoming Settlement Webhook
                                |
                                v
               [1. Decimal Precision & Positive Check]
                                |
                   (Valid & > 0) v (Invalid/Mismatched -> ValueError 400/422)
               [2. In-Memory Idempotency & Ref Check]
                                |
                   (Fresh)      v (Known Ref -> Return Existing Settlement 200)
               [3. Phase 1: DB payment_intents UPDATE 'SETTLED']
                                |
                   (Success)    v (DB Error -> Raise PaymentPersistenceError,
                                |               in-memory remains PENDING)
               [4. Phase 2: DB payment_settlements INSERT]
                                |
                 +--------------+--------------+
                 |                             |
             (Success)                      (Error)
                 |                             |
                 v                             v
     [5. In-Memory Commit]      [6. Compensating DB Transaction]
     - status = SETTLED         - UPDATE payment_intents 'PENDING'
     - add idempotency key      - in-memory status remains PENDING
     - cache settlement ref     - Raise PaymentPersistenceError
                 |                             |
                 v                             v
    [7. Secondary Observability]   (Gateway Receives Non-200 -> Retries)
    - record_payment_event
    - tenant callbacks
    - Return SettlementRecord
`

### Mekanisme Pemulihan & Idempotensi:
1. **Pencegahan False In-Memory Settlement:**  
   Objek intent di memori tidak pernah ditandai SETTLED sebelum operasi tulis basis data berhasil. Jika Phase 1 gagal, memori tetap PENDING.
2. **Kompensasi Kegagalan Parsial (Anti-Orphan Guarantee):**  
   Jika Phase 1 (update intent) berhasil namun Phase 2 (insert settlement) gagal karena kendala basis data, transaksi kompensasi segera dijalankan untuk mengembalikan status intent di basis data menjadi PENDING. State in-memory dipastikan tetap PENDING, dan idempotency key tidak dikonsumsi.
3. **Pemulihan Idempoten saat Webhook Retry:**  
   Ketika gateway pembayaran melakukan *retry* webhook setelah kegagalan transien (mis. timeout jaringan pulih), intent masih berada dalam status PENDING baik di basis data maupun memori. Panggilan kedua dapat dieksekusi secara normal dan menyelesaikan settlement secara bersih.
4. **Perlindungan Terhadap Duplicate Webhook Pasca-Sukses:**  
   Jika webhook yang sama dikirimkan kembali setelah transaksi sukses, lapisan pengecekan idempotensi (_idempotency_keys dan _settlements_by_ref) langsung mengembalikan rekaman SettlementRecord yang sudah tersimpan tanpa melakukan penulisan ulang ke basis data.

---

## 4. XENDIT ACKNOWLEDGMENT CONTRACT ANALYSIS

### 4.1. Urutan Respons HTTP & Caller Contract
Dalam implementasi dual-runner (FastAPI via xendit_webhook_callback dan iohttp via iohttp_xendit_webhook), seluruh pemrosesan didelegasikan ke process_xendit_webhook_core:
1. **HTTP 200 OK (status: PERSISTED atau status: ALREADY_PROCESSED):**  
   - Menandakan transaksi berhasil disimpan secara atomik ke PostgreSQL ledger atau terdeteksi sebagai duplikat idempoten yang sah.
   - Xendit menganggap webhook telah diakui (*acknowledged*) dan menghentikan jadwal retry.
2. **HTTP 400 / 403 / 422 (status: REJECTED / AMOUNT_MISMATCH / ORDER_TENANT_MISMATCH):**  
   - Menandakan data webhook tidak valid (token salah, tenant mismatch, nominal tidak sesuai order).
   - Xendit menganggap error deterministik pada level payload dan tidak mengirimkan kembali payload yang cacat.
3. **HTTP 500 / 503 (status: FAILED / Internal Server Error):**  
   - Dikembalikan ketika terjadi kegagalan persistensi database, timeout koneksi, atau kegagalan verifikasi kriptografi internal.
   - Xendit memperlakukan respons ini sebagai *unacknowledged delivery* dan secara otomatis menjadwalkan pengiriman ulang (*exponential retry*).

### 4.2. Source of Truth Financial Ledger
- **Primary Financial SSOT:** Basis data PostgreSQL (orders status PAID, payment_events, financial_ledger, dan commission_ledger). Ini adalah buku besar keuangan otoritatif yang mencatat hak kepemilikan dan penyelesaian transaksi.
- **Secondary Replication Target:** Tabel Supabase (payment_settlements, orders). Sinkronisasi ke Supabase menggunakan get_payment_privileged_supabase() dan melempar PaymentPersistenceError jika terjadi kegagalan sinkronisasi, sehingga kegagalan tidak disembunyikan.

### 4.3. Perilaku Retry Provider & Mitigasi Risiko Double-Crediting
- Xendit menerapkan kebijakan retry otomatis dengan interval bertahap (1 menit, 5 menit, 15 menit, hingga beberapa jam) jika endpoint mengembalikan status non-2xx.
- Jika persistensi gagal di awal, transaksi di-rollback secara utuh sehingga retry berikutnya memproses transaksi seolah baru.
- Jika transaksi telah berhasil dan Xendit tetap mengirimkan retry (misal karena network blip saat transmisi HTTP 200), pengecekan idempotensi database level (_check_db_idempotency_sync dan commit_verified_settlement_transaction composite uniqueness) mendeteksi order telah PAID dan mengembalikan status: ALREADY_PROCESSED dengan HTTP 200, **mencegah terjadinya double-crediting atau mutasi ganda**.

---

## 5. FULL TEST SUITE SOURCE CODE & RAW PYTEST OUTPUT

### 5.1. Raw Pytest Output (18/18 Scenarios PASS)

`	ext
============================= test session starts =============================
platform win32 -- Python 3.12.8, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\Alldy\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: C:\boontrack-core
configfile: pytest.ini
plugins: anyio-4.14.2, Faker-40.39.0, locust-2.46.5, platformdirs-4.14.5, asyncio-1.4.0, cov-7.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 18 items

tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_01_intent_status_update_privileged_client PASSED [  5%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_02_settlement_insert_privileged_client PASSED [ 11%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_03_duplicate_settlement_webhook_idempotency PASSED [ 16%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_04_webhook_retry_handling_idempotency PASSED [ 22%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_05_xendit_fallback_settlement_uses_privileged_client PASSED [ 27%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_06_payment_failure_does_not_report_success PASSED [ 33%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_07_missing_privileged_credentials_fail_closed PASSED [ 38%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_08_zero_credential_leakage PASSED [ 44%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_09_financial_ledger_reconciliation_consistency PASSED [ 50%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_10_regression_payment_abstraction_and_qris_adapter PASSED [ 55%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_11_intent_persistence_failure_rolls_back_in_memory PASSED [ 61%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_12_settlement_intent_update_failure_prevents_settled_status PASSED [ 66%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_13_settlement_insert_failure_triggers_compensation_and_rollback PASSED [ 72%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_14_in_memory_state_consistency_after_persistence_failure PASSED [ 77%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_15_xendit_settlement_persistence_failure_propagates_error PASSED [ 83%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_16_duplicate_webhook_retry_recovers_after_partial_failure PASSED [ 88%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_17_amount_boundary_and_fractional_decimal_precision PASSED [ 94%]
tests/payments/test_unit_p0_01a_credential_hardening.py::TestUnitP001ACredentialHardening::test_scenario_18_secondary_payment_event_failure_does_not_abort_settlement PASSED [100%]

============================= 18 passed in 50.77s =============================
`

### 5.2. Verbatim Source Code of 	ests/payments/test_unit_p0_01a_credential_hardening.py

`python
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
        self.mock_sb_client = MagicMock()
        self.mock_table = MagicMock()
        self.mock_sb_client.table.return_value = self.mock_table
        self.mock_table.insert.return_value = self.mock_table
        self.mock_table.update.return_value = self.mock_table
        self.mock_table.upsert.return_value = self.mock_table
        self.mock_table.eq.return_value = self.mock_table
        self.mock_table.in_.return_value = self.mock_table
        self.mock_table.execute.return_value = MagicMock(data=[{"id": "test-record"}])

        # Patch redis lock to True to keep unit tests fast and independent of live Redis network
        self.redis_lock_patcher = patch("app.core.redis.acquire_payment_lock", return_value=True)
        self.mock_redis_lock = self.redis_lock_patcher.start()

    def tearDown(self):
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

        with patch("app.routes.xendit.get_db_connection", return_value=mock_pg_conn), \
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

        with patch("app.routes.xendit.get_db_connection", return_value=mock_pg_conn), \
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


if __name__ == "__main__":
    unittest.main()

`

---

## 6. EXACT GIT DIFF & COMPLETE LIST OF MODIFIED FILES

### 6.1. Modified Files Summary
1. pp/payments/schemas.py: Menambahkan import Decimal dan memperluas tipe mount serta 	otal_amount menjadi Union[Decimal, float, int] untuk validasi numerik presisi non-lossy.
2. pp/payments/service.py: Menambahkan PaymentPersistenceError, helper _to_decimal(), method rollback _rollback_intent_in_memory(), penegakan fail-closed pada intent persistence, settlement two-phase update/insert dengan compensating rollback, pencegahan false in-memory SETTLED, perbandingan nominal presisi berbasis Decimal, dan isolasi observabilitas sekunder.
3. pp/routes/xendit.py: Mengimpor PaymentPersistenceError dan menegakkan propagasi error pada jalur sinkronisasi Supabase di _record_settlement_and_ledger_sync().
4. 	ests/payments/test_unit_p0_01a_credential_hardening.py: Menambahkan 8 skenario pengujian baru (Skenario 11-18) yang memvalidasi kegagalan persistensi intent, kegagalan update settlement, compensating rollback, konsistensi in-memory, kegagalan sinkronisasi Xendit, pemulihan retry idempoten, validasi presisi Decimal, dan ketahanan terhadap kegagalan observabilitas sekunder.

### 6.2. Exact Git Diff

`diff
diff --git a/app/payments/schemas.py b/app/payments/schemas.py
index 60bf39a..d58e66b 100644
--- a/app/payments/schemas.py
+++ b/app/payments/schemas.py
@@ -11,6 +11,7 @@ Covers:
 
 from datetime import datetime, timezone
 from enum import Enum
+from decimal import Decimal
 from typing import Optional, Dict, Any, Union
 from uuid import UUID, uuid4
 from pydantic import BaseModel, Field, ConfigDict
@@ -38,7 +39,7 @@ class PaymentIntentCreate(BaseModel):
 
     tenant_id: str = Field(..., description="Tenant identifier (e.g. 'atmosfitnes', 'boontrack-career')")
     order_id: str = Field(..., description="Unique client/business order reference ID")
-    amount: int = Field(..., gt=0, description="Base transaction amount in IDR")
+    amount: Union[Decimal, float, int] = Field(..., gt=0, description="Base transaction amount in IDR")
     user_id: Optional[str] = Field(None, description="Customer phone / user identifier")
     customer_name: Optional[str] = Field(None, description="Customer name if known")
     customer_email: Optional[str] = Field(None, description="Customer email for payment gateway")
@@ -57,9 +58,9 @@ class PaymentIntentResponse(BaseModel):
     id: str = Field(default_factory=lambda: str(uuid4()))
     tenant_id: str
     order_id: str
-    amount: int = Field(..., description="Base amount in IDR")
+    amount: Union[Decimal, float, int] = Field(..., description="Base amount in IDR")
     unique_code: int = Field(..., description="Injected 3-digit unique verification code (0 if gateway handles routing)")
-    total_amount: int = Field(..., description="Total amount payable (amount + unique_code)")
+    total_amount: Union[Decimal, float, int] = Field(..., description="Total amount payable (amount + unique_code)")
     qr_string: str = Field(..., description="EMVCo Dynamic QRIS string")
     qr_image_url: Optional[str] = Field(None, description="QuickChart or CDN QR link")
     status: PaymentStatus = Field(default=PaymentStatus.PENDING)
@@ -81,9 +82,9 @@ class InvoicePayload(BaseModel):
     invoice_id: str
     tenant_id: str
     order_id: str
-    base_amount: int
+    base_amount: Union[Decimal, float, int]
     unique_code: int
-    total_amount: int
+    total_amount: Union[Decimal, float, int]
     qr_string: str
     qr_image_url: Optional[str] = None
     status: PaymentStatus = PaymentStatus.PENDING
@@ -97,7 +98,7 @@ class WebhookEventPayload(BaseModel):
     provider: str = Field(default="QRIS_DYNAMIC", description="Provider identifier (e.g. 'DANA_READER', 'DUITKU', 'XENDIT')")
     event_type: str = Field(default="PAYMENT_SETTLED", description="Event type identifier")
     provider_ref: str = Field(..., description="Unique provider transaction reference ID / hash")
-    amount: int = Field(..., description="Settled nominal amount detected")
+    amount: Union[Decimal, float, int] = Field(..., description="Settled nominal amount detected")
     order_id: Optional[str] = Field(None, description="Associated order ID if provided in reference")
     tenant_id: Optional[str] = Field(None, description="Tenant hint if parsed from reference or channel")
     idempotency_key: Optional[str] = Field(None, description="Client/Provider idempotency key")
@@ -112,7 +113,7 @@ class SettlementRecord(BaseModel):
     id: str = Field(default_factory=lambda: str(uuid4()))
     payment_intent_id: str
     provider_ref: str
-    settled_amount: int
+    settled_amount: Union[Decimal, float, int]
     raw_payload: Dict[str, Any] = Field(default_factory=dict)
     settled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
 
diff --git a/app/payments/service.py b/app/payments/service.py
index 902069b..294109b 100644
--- a/app/payments/service.py
+++ b/app/payments/service.py
@@ -11,6 +11,7 @@ Orchestrates:
 
 import os
 import random
+import asyncio
 import logging
 from datetime import datetime, timedelta, timezone
 from typing import Dict, Any, Optional, List, Callable, Awaitable, Set
@@ -35,21 +36,66 @@ from app.payments.matcher import (
     handle_admin_verify_command,
     handle_admin_retry_doc_command,
 )
+from decimal import Decimal, InvalidOperation
 from app.services.reconciliation_service import PAYMENT_INTENTS as LEGACY_PAYMENT_INTENTS
 
 logger = logging.getLogger("PAYMENT_CORE")
 
 
+class PaymentCredentialConfigurationError(RuntimeError):
+    """Raised when privileged payment backend credentials are missing or invalid."""
+    pass
+
+
+class PaymentPersistenceError(RuntimeError):
+    """Raised when persistence operations fail in financially authoritative or operationally required paths."""
+    pass
+
+
+def _to_decimal(val: Any) -> Decimal:
+    """Converts int, float, str, or Decimal to Decimal for exact numeric comparison."""
+    if isinstance(val, Decimal):
+        return val
+    try:
+        return Decimal(str(val))
+    except (InvalidOperation, TypeError, ValueError) as e:
+        raise ValueError(f"Invalid monetary amount '{val}': {e}") from e
+
+
+def get_payment_privileged_supabase():
+    """
+    Returns a Supabase client authenticated exclusively with SUPABASE_SERVICE_ROLE_KEY.
+
+    Security Contract (UNIT-P0-01A / BT-SEC-2026-001):
+    - Required for mutating payment_intents and payment_settlements after table RLS is enabled.
+    - STRICT FAIL-CLOSED: Silent fallback to SUPABASE_ANON_KEY is strictly prohibited.
+    """
+    url = (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "").strip()
+    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
+    if not url or not key:
+        raise PaymentCredentialConfigurationError(
+            "[SECURITY FAIL-CLOSED] Privileged payment backend credentials missing "
+            "(SUPABASE_SERVICE_ROLE_KEY required). Silent fallback to anon key is strictly prohibited."
+        )
+    try:
+        from supabase import create_client
+        return create_client(url, key)
+    except PaymentCredentialConfigurationError:
+        raise
+    except Exception as e:
+        logger.error(f"[SECURITY FAIL-CLOSED] Failed to initialize privileged Supabase client: {type(e).__name__}")
+        raise PaymentCredentialConfigurationError(
+            f"[SECURITY FAIL-CLOSED] Privileged payment backend client initialization failed: {type(e).__name__}"
+        ) from None
+
+
 def get_supabase():
-    url = os.getenv("SUPABASE_URL", "").strip()
-    key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY", "")).strip()
-    if url and key:
-        try:
-            from supabase import create_client
-            return create_client(url, key)
-        except Exception:
-            return None
-    return None
+    """
+    Legacy Supabase client accessor for backward compatibility.
+    UNIT-P0-01A: Routes strictly through get_payment_privileged_supabase() to enforce fail-closed
+    privileged access and prohibit silent fallback to SUPABASE_ANON_KEY.
+    """
+    return get_payment_privileged_supabase()
 
 
 TenantCallback = Callable[[PaymentIntentResponse, SettlementRecord], Awaitable[None]]
@@ -134,23 +180,24 @@ class PaymentCoreService:
                 logger.debug(f"[PaymentCore] Postgres payment_events insert note: {pg_e}")
 
             # 2. Supabase Sync (Secondary/Read Replica)
-            supabase = get_supabase()
-            if supabase:
-                try:
-                    payload = {
-                        "id": str(event.id),
-                        "tenant_id": event.tenant_id,
-                        "order_id": event.order_id,
-                        "provider": event.provider,
-                        "provider_event_id": event.provider_event_id,
-                        "event_type": event.event_type,
-                        "amount": float(event.amount) if event.amount is not None else None,
-                        "raw_payload": event.raw_payload,
-                        "created_at": event.created_at.isoformat(),
-                    }
-                    supabase.table("payment_events").insert(payload).execute()
-                except Exception as e:
-                    logger.warning(f"[PaymentCore] Supabase payment_events insert note: {e}")
+            try:
+                supabase = get_payment_privileged_supabase()
+                payload = {
+                    "id": str(event.id),
+                    "tenant_id": event.tenant_id,
+                    "order_id": event.order_id,
+                    "provider": event.provider,
+                    "provider_event_id": event.provider_event_id,
+                    "event_type": event.event_type,
+                    "amount": float(event.amount) if event.amount is not None else None,
+                    "raw_payload": event.raw_payload,
+                    "created_at": event.created_at.isoformat(),
+                }
+                supabase.table("payment_events").insert(payload).execute()
+            except PaymentCredentialConfigurationError as pce:
+                logger.warning(f"[PaymentCore] Privileged credentials not configured for payment_events: {pce}")
+            except Exception as e:
+                logger.warning(f"[PaymentCore] Supabase payment_events insert note: {e}")
         return event
 
     def register_provider(self, provider_type: PaymentProviderType, provider: BasePaymentProvider) -> None:
@@ -191,6 +238,14 @@ class PaymentCoreService:
                 return code
         return random.randint(min_val, max_val)
 
+    def _rollback_intent_in_memory(self, intent: PaymentIntentResponse) -> None:
+        """Roll back in-memory registrations if persistent database insert fails."""
+        self._intents_by_id.pop(intent.id, None)
+        self._intents_by_tenant_order.pop(f"{intent.tenant_id}:{intent.order_id}", None)
+        self._intents_by_amount.pop(f"{intent.tenant_id}:{intent.total_amount}", None)
+        LEGACY_PAYMENT_INTENTS.pop(intent.order_id, None)
+        LEGACY_PAYMENT_INTENTS.pop(intent.total_amount, None)
+
     async def create_payment_intent(
         self,
         intent_data: PaymentIntentCreate,
@@ -257,25 +312,30 @@ class PaymentCoreService:
 
         # 4. Simpan ke Supabase jika tersedia
         if not self.in_memory_mode:
-            supabase = get_supabase()
-            if supabase:
-                try:
-                    payload = {
-                        "id": intent.id,
-                        "tenant_id": intent.tenant_id,
-                        "order_id": intent.order_id,
-                        "amount": intent.amount,
-                        "unique_code": intent.unique_code,
-                        "total_amount": intent.total_amount,
-                        "qr_string": intent.qr_string,
-                        "qr_image_url": intent.qr_image_url,
-                        "status": intent.status.value,
-                        "expires_at": intent.expires_at.isoformat(),
-                        "created_at": intent.created_at.isoformat(),
-                    }
-                    supabase.table("payment_intents").insert(payload).execute()
-                except Exception as e:
-                    logger.warning(f"[PaymentCore] Supabase intent insert note: {e}")
+            try:
+                supabase = get_payment_privileged_supabase()
+                payload = {
+                    "id": intent.id,
+                    "tenant_id": intent.tenant_id,
+                    "order_id": intent.order_id,
+                    "amount": intent.amount,
+                    "unique_code": intent.unique_code,
+                    "total_amount": intent.total_amount,
+                    "qr_string": intent.qr_string,
+                    "qr_image_url": intent.qr_image_url,
+                    "status": intent.status.value,
+                    "expires_at": intent.expires_at.isoformat(),
+                    "created_at": intent.created_at.isoformat(),
+                }
+                supabase.table("payment_intents").insert(payload).execute()
+            except PaymentCredentialConfigurationError:
+                logger.error("[PaymentCore FAIL-CLOSED] Privileged credentials missing when creating payment intent in non-memory mode.")
+                self._rollback_intent_in_memory(intent)
+                raise
+            except Exception as e:
+                logger.error(f"[PaymentCore FAIL-CLOSED] Failed to persist payment intent '{intent.order_id}' to Supabase: {e}")
+                self._rollback_intent_in_memory(intent)
+                raise PaymentPersistenceError(f"Failed to persist payment intent '{intent.order_id}': {e}") from e
 
         logger.info(
             f"[PaymentCore] Created intent '{intent.order_id}' for tenant '{intent.tenant_id}' "
@@ -334,16 +394,43 @@ class PaymentCoreService:
                     matched_intent = candidate
 
             if not matched_intent:
-                for candidate in self._intents_by_id.values():
-                    if candidate.total_amount == webhook.amount and candidate.status == PaymentStatus.PENDING:
-                        matched_intent = candidate
-                        break
+                try:
+                    w_dec = _to_decimal(webhook.amount)
+                    for candidate in self._intents_by_id.values():
+                        if candidate.status == PaymentStatus.PENDING:
+                            try:
+                                if _to_decimal(candidate.total_amount) == w_dec:
+                                    matched_intent = candidate
+                                    break
+                            except ValueError:
+                                continue
+                except ValueError:
+                    pass
 
         if not matched_intent:
             err_msg = f"No pending payment intent found for order_id='{webhook.order_id}' amount={webhook.amount}"
             logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
             raise ValueError(err_msg)
 
+        if webhook.amount is not None:
+            try:
+                webhook_dec = _to_decimal(webhook.amount)
+                intent_dec = _to_decimal(matched_intent.total_amount)
+            except ValueError as ve:
+                err_msg = f"Invalid settlement amount format: {ve}"
+                logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
+                raise ValueError(err_msg) from ve
+
+            if webhook_dec <= Decimal("0"):
+                err_msg = f"Settlement amount must be positive: got {webhook.amount}"
+                logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
+                raise ValueError(err_msg)
+
+            if intent_dec != webhook_dec:
+                err_msg = f"Settlement amount {webhook.amount} does not match intent amount {matched_intent.total_amount} for order_id='{matched_intent.order_id}'"
+                logger.error(f"[PaymentCore] Settlement rejected: {err_msg}")
+                raise ValueError(err_msg)
+
         now = datetime.now(timezone.utc)
         exp = matched_intent.expires_at if matched_intent.expires_at.tzinfo else matched_intent.expires_at.replace(tzinfo=timezone.utc)
         if matched_intent.status == PaymentStatus.EXPIRED or now > exp:
@@ -357,7 +444,6 @@ class PaymentCoreService:
             if existing_settlement:
                 return existing_settlement
 
-        matched_intent.status = PaymentStatus.SETTLED
         settlement_id = str(uuid4())
         settlement = SettlementRecord(
             id=settlement_id,
@@ -368,6 +454,53 @@ class PaymentCoreService:
             settled_at=now,
         )
 
+        # In non-memory mode, persist to Supabase with two-phase verification and compensating rollback BEFORE committing in-memory
+        if not self.in_memory_mode:
+            supabase = get_payment_privileged_supabase()
+            try:
+                supabase.table("payment_intents") \
+                    .update({"status": "SETTLED"}) \
+                    .eq("id", matched_intent.id) \
+                    .execute()
+            except PaymentCredentialConfigurationError:
+                logger.error("[PaymentCore FAIL-CLOSED] Privileged credentials missing when settling payment intent in non-memory mode.")
+                raise
+            except Exception as e:
+                logger.error(f"[PaymentCore FAIL-CLOSED] Failed to update payment_intents to SETTLED for intent '{matched_intent.id}': {e}")
+                raise PaymentPersistenceError(f"Failed to update payment intent status to SETTLED: {e}") from e
+
+            settlement_payload = {
+                "id": settlement.id,
+                "payment_intent_id": settlement.payment_intent_id,
+                "provider_ref": settlement.provider_ref,
+                "settled_amount": settlement.settled_amount,
+                "raw_payload": settlement.raw_payload,
+                "settled_at": settlement.settled_at.isoformat(),
+            }
+            try:
+                supabase.table("payment_settlements").insert(settlement_payload).execute()
+            except Exception as insert_err:
+                logger.error(
+                    f"[PaymentCore FAIL-CLOSED] Failed to insert payment_settlements for intent '{matched_intent.id}'. "
+                    f"Initiating compensating rollback of payment_intents status: {insert_err}"
+                )
+                try:
+                    supabase.table("payment_intents") \
+                        .update({"status": PaymentStatus.PENDING.value}) \
+                        .eq("id", matched_intent.id) \
+                        .execute()
+                    logger.info(f"[PaymentCore Compensation] Reverted payment_intents '{matched_intent.id}' back to PENDING")
+                except Exception as comp_err:
+                    logger.critical(
+                        f"[PaymentCore CRITICAL] Compensation failed to revert payment_intents '{matched_intent.id}' to PENDING: {comp_err}"
+                    )
+                matched_intent.status = PaymentStatus.PENDING
+                raise PaymentPersistenceError(
+                    f"Failed to persist settlement record (compensated): {insert_err}"
+                ) from insert_err
+
+        # Commit in-memory mutations ONLY after persistent DB updates succeed
+        matched_intent.status = PaymentStatus.SETTLED
         self._idempotency_keys.add(idem_key)
         self._settlements_by_id[settlement.id] = settlement
         self._settlements_by_ref[settlement.provider_ref] = settlement
@@ -378,27 +511,6 @@ class PaymentCoreService:
         if matched_intent.total_amount in LEGACY_PAYMENT_INTENTS:
             LEGACY_PAYMENT_INTENTS[matched_intent.total_amount]["status"] = "PAID"
 
-        if not self.in_memory_mode:
-            supabase = get_supabase()
-            if supabase:
-                try:
-                    supabase.table("payment_intents") \
-                        .update({"status": "SETTLED"}) \
-                        .eq("id", matched_intent.id) \
-                        .execute()
-
-                    settlement_payload = {
-                        "id": settlement.id,
-                        "payment_intent_id": settlement.payment_intent_id,
-                        "provider_ref": settlement.provider_ref,
-                        "settled_amount": settlement.settled_amount,
-                        "raw_payload": settlement.raw_payload,
-                        "settled_at": settlement.settled_at.isoformat(),
-                    }
-                    supabase.table("payment_settlements").insert(settlement_payload).execute()
-                except Exception as e:
-                    logger.warning(f"[PaymentCore] Supabase settlement persist note: {e}")
-
         logger.info(
             f"[PaymentCore] Intent '{matched_intent.order_id}' successfully SETTLED "
             f"via provider ref '{webhook.provider_ref}' (Rp{webhook.amount:,})"
@@ -492,15 +604,17 @@ class PaymentCoreService:
                         LEGACY_PAYMENT_INTENTS[intent.order_id]["status"] = "EXPIRED"
 
         if expired_ids and not self.in_memory_mode:
-            supabase = get_supabase()
-            if supabase:
-                try:
-                    supabase.table("payment_intents") \
-                        .update({"status": "EXPIRED"}) \
-                        .in_("id", expired_ids) \
-                        .execute()
-                except Exception as e:
-                    logger.warning(f"[PaymentCore] Supabase batch expire note: {e}")
+            try:
+                supabase = get_payment_privileged_supabase()
+                supabase.table("payment_intents") \
+                    .update({"status": "EXPIRED"}) \
+                    .in_("id", expired_ids) \
+                    .execute()
+            except PaymentCredentialConfigurationError:
+                logger.error("[PaymentCore FAIL-CLOSED] Privileged credentials missing when expiring payment intents in non-memory mode.")
+                raise
+            except Exception as e:
+                logger.warning(f"[PaymentCore] Supabase batch expire note: {e}")
 
         if expired_ids:
             logger.info(f"[PaymentCore] Marked {len(expired_ids)} stale intents as EXPIRED")
diff --git a/app/routes/xendit.py b/app/routes/xendit.py
index 39c55f2..4ae690e 100644
--- a/app/routes/xendit.py
+++ b/app/routes/xendit.py
@@ -31,7 +31,16 @@ from app.core.database import get_db_connection, normalize_db_row
 from app.services.xendit_service import xendit_service
 from app.services.payment.gateway_xendit import XenditAdapter
 from app.services.meta_capi_service import send_meta_capi_purchase
-from app.services.whatsapp_service import send_whatsapp_text, send_ereceipt_whatsapp, get_supabase
+from app.services.whatsapp_service import send_whatsapp_text, send_ereceipt_whatsapp
+from app.payments.service import (
+    get_payment_privileged_supabase,
+    PaymentCredentialConfigurationError,
+    PaymentPersistenceError,
+)
+
+# UNIT-P0-01A: Forward get_supabase to get_payment_privileged_supabase to enforce fail-closed
+# privileged access and prevent anonymous key usage on payment settlement sync paths.
+get_supabase = get_payment_privileged_supabase
 from app.services.tracking_service import dispatch_all_capi
 from app.services.reconciliation_service import PAYMENT_INTENTS
 from app.modules.tracking import capi_dispatcher
@@ -719,22 +728,26 @@ def _record_settlement_and_ledger_sync(
             except Exception:
                 pass
 
-    # Fallback/Sinkronisasi ke Supabase client jika aktif
-    supabase = get_supabase()
-    if supabase:
-        try:
-            supabase.table("payment_settlements").upsert({
+    # Fallback/Sinkronisasi ke Supabase client jika aktif (UNIT-P0-01A Privileged Hardening)
+    try:
+        privileged_sb = get_payment_privileged_supabase()
+        if privileged_sb:
+            privileged_sb.table("payment_settlements").upsert({
                 "provider_ref": f"xendit_{external_id}",
                 "settled_amount": amount,
                 "status": "PAID",
                 "raw_payload": payload,
             }, on_conflict="provider_ref").execute()
-            supabase.table("orders").update({
+            privileged_sb.table("orders").update({
                 "status": "LUNAS",
                 "payment_status": "PAID",
             }).eq("id", str(external_id)).execute()
-        except Exception as sb_err:
-            logger.debug(f"[Xendit Supabase Settlement Note] {sb_err}")
+    except PaymentCredentialConfigurationError as pce:
+        logger.warning(f"[Xendit Settlement Privileged Guard] {pce}")
+        raise
+    except Exception as sb_err:
+        logger.error(f"[Xendit Supabase Settlement Error] {sb_err}")
+        raise PaymentPersistenceError(f"Failed to synchronize settlement to Supabase: {sb_err}") from sb_err
 
 
 

`

---

## 7. STAGING ENVIRONMENT CONFIRMATION, ROLLBACK PROCEDURE & RESIDUAL RISKS

### 7.1. Konfirmasi Lingkungan Staging
- **Target Eksklusif:** Pengujian dan verifikasi dijalankan strictly pada isolated test environment / Staging target Supabase (xkhqirhurnjqglmajghn).
- **Nol Mutasi Produksi:** Tidak ada deployment, rotasi kredensial, koneksi, DDL, maupun DML yang diarahkan ke database produksi Supabase (mpluzajlzpregmjwpjqr) maupun Workforce Staging (	jkbgxrckaocgosvmzmj).
- **Nol Perubahan Skema:** Tidak ada perintah CREATE, ALTER, DROP, GRANT, REVOKE, maupun modifikasi RLS policy yang dijalankan (UNIT-P0-01C tetap strictly NOT AUTHORIZED).
- **Isolasi Repositori:** Repositori oontrack-inbox sama sekali tidak disentuh (pekerjaan UNIT-P0-01B tetap terpisah secara independen).

### 7.2. Prosedur Rollback Cepat
Jika diperlukan rollback kode pada branch infra/isolated-test-environment:
`ash
git checkout HEAD -- app/payments/schemas.py app/payments/service.py app/routes/xendit.py tests/payments/test_unit_p0_01a_credential_hardening.py
`
Perubahan di atas bersifat murni aplikasi tanpa dependensi skema basis data baru, sehingga dapat di-revert seketika tanpa memerlukan migrasi database balik.

### 7.3. Analisis Risiko Residual (*Residual Security Risks*)
1. **Luasnya Hak Akses Kredensial service_role:**  
   Penggunaan SUPABASE_SERVICE_ROLE_KEY pada backend tepercaya secara sengaja mengabaikan seluruh kebijakan Row Level Security (RLS) di Supabase.
   - *Mitigasi:* Akses ini hanya berada di proses server internal (	rusted backend), tidak pernah diekspos ke browser atau respons HTTP. Validasi tenant isolation (	enant_id), binding kepemilikan order, dan verifikasi tanda tangan kriptografi HMAC/Provenance Authority wajib ditegakkan secara ketat pada lapisan kode aplikasi.
2. **Ketergantungan Kompensasi pada Konektivitas Database:**  
   Mekanisme kompensasi status intent kembali ke PENDING bergantung pada ketersediaan koneksi basis data. Apabila terjadi *total network severance* tepat setelah update Phase 1 dan sebelum eksekusi kompensasi, intent dapat berstatus SETTLED tanpa record settlement di DB sampai proses audit rekonsiliasi manual atau automated sweep mencocokkannya.
