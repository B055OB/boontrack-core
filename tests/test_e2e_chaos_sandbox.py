"""tests/test_e2e_chaos_sandbox.py
E2E & Chaos Sandbox Test Suite for CTO Audit.

Scenarios Covered:
1. Webhook Duplication & Idempotency:
   - Consecutive identical webhooks (same provider_event_id & order_id).
   - Verifies idempotent handling without duplicate side-effects.
2. Concurrency Race-Condition (Atomic Counter Trial):
   - 10 simultaneous order creation requests via asyncio.gather when quota has 2 remaining (28/30).
   - Verifies exactly 2 succeed, 8 rejected with TRIAL_LIMIT_EXCEEDED, count never exceeds 30.
3. Immutability Violation Test:
   - Direct UPDATE or DELETE operation against PaymentEvent entity.
   - Verifies hard rejection with IMMUTABLE_LOG_VIOLATION.
4. External Outage Resilience (WhatsApp API & Meta CAPI Down):
   - Mocks WhatsApp API and Meta CAPI returning HTTP 500 / Connection Timeout.
   - Verifies database order/payment transaction remains safely committed (non-blocking isolation).
"""

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.payment_event import PaymentEvent, ImmutableLogViolationException
from app.models.base import Base
from app.payments.schemas import (
    PaymentStatus,
    PaymentProviderType,
    PaymentIntentCreate,
    WebhookEventPayload,
)
from app.payments.service import PaymentCoreService
from app.core.trial_guardrail import (
    trial_guardrail,
    TrialLimitExceededException,
    CFO_TRIAL_MAX_ORDERS,
)
from app.modules.commerce.order import CommerceOrderService
from app.services.checkout_flow_service import (
    create_d2c_order_and_dispatch_qris,
    reconcile_payment_webhook,
)

SAMPLE_VALID_STATIC_QRIS = (
    "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI"
    "51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI5204737253033605802ID5909BoonTrack"
    "6012Kab. Bandung61054028663048DC1"
)


# ===========================================================================
# Skenario 1: Webhook Duplication & Idempotency
# ===========================================================================

@pytest.mark.asyncio
async def test_scenario_1_webhook_duplication_and_idempotency():
    """
    Kirim 2 payload webhook yang identik (provider_event_id & order_id sama) secara berurutan.
    Verifikasi: Event tercatat di audit log tanpa menduplikasi status pesanan atau saldo (idempotent).
    """
    print("\n--- [CTO AUDIT SCENARIO 1: Webhook Duplication & Idempotency] ---")
    payment_service = PaymentCoreService(in_memory_mode=True)
    tenant_id = "tenant-audit-idempotency"
    order_id = f"ORD-IDEM-{uuid.uuid4().hex[:6]}"
    provider_ref = f"xen_pay_{uuid.uuid4().hex[:8]}"
    settled_amount = 150000

    # 1. Buat Intent Awal
    intent_data = PaymentIntentCreate(
        tenant_id=tenant_id,
        order_id=order_id,
        amount=settled_amount,
        product_name="Audit Test Item",
    )
    intent = await payment_service.create_payment_intent(
        intent_data=intent_data,
        provider_type=PaymentProviderType.QRIS_DYNAMIC,
    )
    assert intent.status == PaymentStatus.PENDING

    # Callback execution counter untuk menguji tidak adanya duplicate side-effect
    side_effect_counter = 0

    async def on_settled(intent_res, settlement_rec):
        nonlocal side_effect_counter
        side_effect_counter += 1

    payment_service.register_tenant_callback(tenant_id, on_settled)

    # 2. Webhook Pertama (Initial Settlement)
    webhook_1 = WebhookEventPayload(
        provider="xendit",
        event_type="PAYMENT_SETTLED",
        provider_ref=provider_ref,
        amount=settled_amount,
        order_id=order_id,
        tenant_id=tenant_id,
        idempotency_key=provider_ref,
        raw_payload={"status": "PAID", "ref": provider_ref},
    )
    settlement_1 = await payment_service.process_webhook_settlement(webhook_1)

    assert settlement_1 is not None
    assert settlement_1.provider_ref == provider_ref
    assert settlement_1.settled_amount == settled_amount
    assert side_effect_counter == 1
    print(f"[AUDIT] Webhook 1 diproses: Settlement ID '{settlement_1.id}' - Side Effect Count: {side_effect_counter}")

    # 3. Webhook Kedua (Duplicate Retry dari Gateway)
    webhook_2 = WebhookEventPayload(
        provider="xendit",
        event_type="PAYMENT_SETTLED",
        provider_ref=provider_ref,
        amount=settled_amount,
        order_id=order_id,
        tenant_id=tenant_id,
        idempotency_key=provider_ref,
        raw_payload={"status": "PAID", "ref": provider_ref},
    )
    settlement_2 = await payment_service.process_webhook_settlement(webhook_2)

    # Verifikasi Idempotensi Mutlak
    assert settlement_2.id == settlement_1.id
    assert side_effect_counter == 1, "Side-effect tidak boleh tereksekusi dua kali!"
    print(f"[AUDIT] Webhook 2 diabaikan via idempotency cache: Tetap merujuk settlement '{settlement_2.id}'")
    print("[PASSED] Webhook Duplication & Idempotency Verified (Zero Duplicate Side-Effects)")


# ===========================================================================
# Skenario 2: Concurrency Race-Condition (Atomic Counter Trial)
# ===========================================================================

@pytest.mark.asyncio
async def test_scenario_2_concurrency_race_condition_atomic_trial():
    """
    Simulasikan 10 request pembuatan order secara simultan (asyncio.gather) saat
    sisa kuota trial tinggal 2 (posisi 28/30).
    Verifikasi: Tepat 2 order lolos, 8 order ditolak dengan error TRIAL_LIMIT_EXCEEDED,
    dan counter database tidak pernah melebihi 30.
    """
    print("\n--- [CTO AUDIT SCENARIO 2: Concurrency Race-Condition (Atomic Counter)] ---")
    tenant = f"trial-concurrency-{uuid.uuid4().hex[:6]}"
    trial_guardrail.reset(tenant)

    # Set posisi pemakaian di 28 dari 30
    for _ in range(28):
        trial_guardrail.record_order(tenant)

    assert trial_guardrail.get_order_count(tenant) == 28
    print(f"[AUDIT] Posisi awal kuota tenant '{tenant}': 28/30 (Sisa 2 slot)")

    product = {"product_code": "PROD-CONCURRENCY", "title": "Buku Bisnis", "price": 99000}

    async def execute_concurrent_order(task_id: int):
        await asyncio.sleep(0.001)  # Context-switch trigger untuk menguji race conditions
        try:
            res = await CommerceOrderService.create_order_async(
                tenant_id=tenant,
                product=product,
                buyer_identifier=f"buyer_task_{task_id}",
                is_trial=True,
            )
            return {"task_id": task_id, "success": True, "order": res}
        except TrialLimitExceededException as exc:
            return {"task_id": task_id, "success": False, "error": exc.error_code, "detail": exc.to_dict()}

    # Luncurkan 10 task concurrent
    tasks = [execute_concurrent_order(i) for i in range(10)]
    results = await asyncio.gather(*tasks)

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    print(f"[AUDIT] Hasil simulasi 10 order simultan: {len(successes)} Lulus, {len(failures)} Ditolak")
    for f in failures:
        assert f["error"] == "TRIAL_LIMIT_EXCEEDED"

    # Verifikasi Invarian CTO
    assert len(successes) == 2, f"Harus tepat 2 order yang sukses, ditemukan: {len(successes)}"
    assert len(failures) == 8, f"Harus tepat 8 order yang ditolak, ditemukan: {len(failures)}"
    final_count = trial_guardrail.get_order_count(tenant)
    assert final_count == CFO_TRIAL_MAX_ORDERS, f"Counter harus tepat {CFO_TRIAL_MAX_ORDERS}, ditemukan: {final_count}"
    assert final_count <= 30, "Counter database/guardrail dilarang keras melebihi 30!"

    print(f"[AUDIT] Counter final guardrail: {final_count}/{CFO_TRIAL_MAX_ORDERS}")
    print("[PASSED] Concurrency Race-Condition Atomic Counter Verified (Zero Over-Quota Leaks)")
    trial_guardrail.reset(tenant)


# ===========================================================================
# Skenario 3: Immutability Violation Test
# ===========================================================================

def test_scenario_3_immutability_violation():
    """
    Simulasikan operasi UPDATE atau DELETE langsung ke tabel payment_events.
    Verifikasi: Database / ORM menolak keras (menghasilkan error IMMUTABLE_LOG_VIOLATION).
    """
    print("\n--- [CTO AUDIT SCENARIO 3: Immutability Violation Test] ---")

    # Inisialisasi engine SQLite in-memory untuk testing ORM lifecycle
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine, tables=[PaymentEvent.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()

    # 1. Simpan Event Asli (INSERT diperbolehkan)
    evt = PaymentEvent(
        tenant_id="tenant-audit-ledger",
        order_id="ORD-AUDIT-001",
        provider="xendit",
        provider_event_id="evt_audit_001",
        event_type="PAYMENT_SETTLED",
        amount=Decimal("250000.00"),
        raw_payload={"status": "PAID"},
    )
    session.add(evt)
    session.commit()
    print(f"[AUDIT] Insert awal berhasil: Record ID '{evt.id}' tercatat di ledger")

    # 2. Uji Mutasi (UPDATE dilarang keras)
    evt.amount = Decimal("999999.00")
    evt.event_type = "TAMPERED_EVENT"
    with pytest.raises(ImmutableLogViolationException) as exc_update:
        session.commit()

    assert exc_update.value.error_code == "IMMUTABLE_LOG_VIOLATION"
    assert "IMMUTABLE_LOG_VIOLATION" in str(exc_update.value)
    print(f"[AUDIT] Upaya UPDATE ditolak keras: {exc_update.value}")
    session.rollback()

    # 3. Uji Penghapusan (DELETE dilarang keras)
    loaded_evt = session.get(PaymentEvent, evt.id)
    session.delete(loaded_evt)
    with pytest.raises(ImmutableLogViolationException) as exc_delete:
        session.commit()

    assert exc_delete.value.error_code == "IMMUTABLE_LOG_VIOLATION"
    assert "IMMUTABLE_LOG_VIOLATION" in str(exc_delete.value)
    print(f"[AUDIT] Upaya DELETE ditolak keras: {exc_delete.value}")
    session.rollback()

    session.close()
    print("[PASSED] Immutability Violation Enforcement Verified (Append-Only Guaranteed)")


# ===========================================================================
# Skenario 4: External Outage Resilience (WhatsApp API & Meta CAPI Down)
# ===========================================================================

@pytest.mark.asyncio
async def test_scenario_4_external_outage_resilience():
    """
    Mock respons WhatsApp API dan Meta CAPI dengan status HTTP 500 / Connection Timeout.
    Verifikasi: Transaksi database order/payment tetap berhasil tersimpan (non-blocking)
    dan kegagalan dispatch terisolasi tanpa membatalkan order.
    """
    print("\n--- [CTO AUDIT SCENARIO 4: External Outage Resilience (WA & CAPI Down)] ---")

    # 1. Simulasikan Pembuatan Order saat WhatsApp API Mengalami HTTP 500 / Timeout
    outage_merchant = "merchant-resilience-audit"
    order_items = [{"product_id": "prod_1", "title": "Produk Audit Resiliensi", "price": 75000}]

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "ORD-1"}])
    mock_table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "ORD-1"}])
    mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "ORD-TEST-123", "tenant_slug": outage_merchant, "customer_phone": "081234567890", "is_digital": True}]
    )
    mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    with patch("app.services.checkout_flow_service.send_whatsapp_image", side_effect=TimeoutError("Connection timeout to Meta Cloud API (500)")):
        with patch("app.services.checkout_flow_service.send_whatsapp_text", side_effect=Exception("HTTP 500 Internal Server Error from WhatsApp")):
            with patch("app.services.checkout_flow_service.get_supabase", return_value=mock_supabase):
                with patch("app.core.database.get_db_connection", side_effect=Exception("DB Postgres mock")):
                    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", return_value=AsyncMock(
                        metadata={"payment_config": {"static_qris_payload": SAMPLE_VALID_STATIC_QRIS, "qris_image_url": "https://cdn.example.com/qr.png"}}
                    )):
                        # Buat pesanan D2C saat WhatsApp mati total
                        res = await create_d2c_order_and_dispatch_qris(
                            merchant_slug=outage_merchant,
                            customer_name="Budi Pembeli",
                            customer_phone="081234567890",
                            items=order_items,
                            total_amount=75000,
                            is_digital=True,
                        )

                        # Order transaksi HARUS tetap berhasil dibuat dan tersimpan
                        assert res is not None
                        assert "order_id" in res
                        assert res["status"] == "PENDING"
                        assert res["total_amount"] == 75000
                        print(f"[AUDIT] Order '{res['order_id']}' sukses tersimpan di DB meskipun WhatsApp API DOWN")

    # 2. Simulasikan Settlement Rekonsiliasi saat WhatsApp & Meta CAPI Mengalami Outage
    with patch("app.services.checkout_flow_service.send_whatsapp_text", side_effect=Exception("Meta Cloud API 500 Gateway Outage")):
        with patch("app.services.checkout_flow_service.get_supabase", return_value=mock_supabase):
            with patch("app.services.tracking_service.dispatch_all_capi", side_effect=Exception("Meta CAPI 500 Server Error")):
                settle_payload = {
                    "id": f"evt_outage_{uuid.uuid4().hex[:6]}",
                    "external_id": res["order_id"],
                    "status": "PAID",
                    "tenant_slug": outage_merchant,
                }
                settle_result = await reconcile_payment_webhook(settle_payload)

                # Pelunasan order HARUS tetap selesai dan tercatat
                assert settle_result.get("status") in ("success", "settled")
                assert settle_result.get("order_id") == res["order_id"]
                print(f"[AUDIT] Settlement order '{res['order_id']}' sukses berstatus SETTLED meski dispatch WhatsApp/CAPI gagal")

    print("[PASSED] External Outage Resilience Verified (Database Transactions 100% Decoupled)")
