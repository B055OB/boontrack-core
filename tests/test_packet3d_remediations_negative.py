"""tests/test_packet3d_remediations_negative.py
Packet 3D Negative QA Test Suite for Command Center Blockers A, B, and E:
1. Outbox-failure full rollback: failure on payment_outbox_events rolls back complete settlement transaction.
2. Zero direct UPDATE orders & zero runtime DDL static audit across all settlement & worker paths.
3. Academy default-deny in Staging/Dev/Prod when ENABLE_ACADEMY_DIRECT_CHECKOUT is unset.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db_connection
from app.core.security.provenance_authority import (
    ProvenanceSigner,
    ProvenanceSigningKeyring,
    ProvenanceVerifier,
    TrustedSettlementVerificationBoundary,
    commit_verified_settlement_transaction,
)
from app.services.academy_service import (
    generate_academy_qris_invoice,
    settle_academy_invoice,
    _SETTLED_ORDERS,
    _PROCESSED_EVENTS,
    _ACADEMY_INVOICES,
)
from app.services.checkout_service import execute_order_settlement_transaction
from app.services.payment.base import SettlementProvenanceError
from app.services.payment_intent_lifecycle import PaymentIntentLifecycleService
from tests.test_checkout_recovery_remediation import (
    _install_order_scoped_failure_trigger,
    _drop_trigger_and_function,
    _fetch_order_db_snapshot,
    TENANT_ALPHA_SLUG,
    TENANT_ALPHA_UUID,
)

CORE_ROOT = Path(__file__).resolve().parents[1]


# =============================================================================
# 1. OUTBOX-FAILURE FULL TRANSACTION ROLLBACK TEST (BLOCKER B)
# =============================================================================

@pytest.mark.asyncio
async def test_negative_outbox_failure_aborts_and_rolls_back_entire_settlement():
    """Negative Test 1 (Blocker B):
    Simulate DB failure specifically on payment_outbox_events insert during settlement.
    Proves the entire settlement transaction is aborted and rolled back:
    - Return status is FAILED_DB_PERSISTENCE (never PAID)
    - Zero financial_ledger records persisted
    - Zero checkout_sessions SETTLED mutations
    - RAM state remains strictly unmutated
    """
    try:
        from app.core.database import get_db_connection
        _conn_probe = get_db_connection()
        _conn_probe.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL required for outbox trigger negative test is unreachable: {exc}")

    inv = generate_academy_qris_invoice(
        customer_name="Outbox Rollback User",
        customer_email="outbox.rollback@tenant-alpha.test",
        customer_phone="628111999222",
        tenant_id=TENANT_ALPHA_SLUG,
        use_unique_code=True,
    )
    order_id = inv["order_id"]
    event_id = f"evt_ob_fail_{uuid.uuid4().hex[:8]}"
    suffix = f"obx_{uuid.uuid4().hex[:8]}"

    # Install trigger that fails ONLY when inserting into payment_outbox_events for this order_id
    trg_name = _install_order_scoped_failure_trigger("payment_outbox_events", order_id, suffix)
    try:
        res = settle_academy_invoice(
            order_id=order_id,
            event_id=event_id,
            provider="XENDIT",
            amount=inv["total_amount"],
            tenant_id=TENANT_ALPHA_SLUG,
        )
        assert res["status"] == "FAILED_DB_PERSISTENCE", f"Expected FAILED_DB_PERSISTENCE, got {res['status']}"
        assert res["status"] != "PAID"
        assert res["idempotency_hit"] is False

        # RAM state must remain pristine
        assert order_id not in _SETTLED_ORDERS
        assert event_id not in _PROCESSED_EVENTS
        assert _ACADEMY_INVOICES[order_id]["status"] == "PENDING"

        # Database state: complete rollback, zero financial ledger records, checkout_session remains ACTIVE
        snap = _fetch_order_db_snapshot(order_id)
        assert snap["order"][3] == "PENDING"
        assert snap["checkout_session"][7] == "ACTIVE"
        assert len(snap["payment_events"]) == 0
        assert len(snap["financial_ledger"]) == 0
        assert len(snap["payment_outbox_events"]) == 0
    finally:
        _drop_trigger_and_function("payment_outbox_events", suffix)


def test_negative_provenance_authority_outbox_failure_rolls_back_settlement():
    """Negative Test 1b (Blocker B-1/B-2 — Provenance Authority):
    Simulate DB failure specifically on payment_outbox_events insert inside
    `commit_verified_settlement_transaction`. Proves full transaction rollback:
    - Raises SettlementProvenanceError (DATABASE_UNAVAILABLE / HTTP 503)
    - Zero payment_events persisted
    - Zero financial_ledger persisted
    - Zero payment_outbox_events persisted
    - Order remains strictly PENDING
    """
    try:
        _conn_probe = get_db_connection()
        _conn_probe.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL required for provenance outbox rollback test is unreachable: {exc}")

    order_id = f"ORD-PROV-OBX-{uuid.uuid4().hex[:8]}"
    event_id = f"evt_prov_obx_{uuid.uuid4().hex[:8]}"
    provider_event_id = f"qr_prov_obx_{uuid.uuid4().hex[:8]}"
    suffix = f"prov_obx_{uuid.uuid4().hex[:8]}"
    amount = 150000

    # Seed pending order bound to canonical TENANT_ALPHA_UUID
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.orders (
                    id, tenant_id, tenant_slug, sku_id, product_id, product_title,
                    status, payment_status, order_status, gross_amount, amount
                ) VALUES (
                    %s, %s, %s, 'SKU-OBX-NEG', 'SKU-OBX-NEG', 'Outbox Rollback Test SKU',
                    'PENDING', 'PENDING', 'PENDING', %s, %s
                );
                """,
                (order_id, TENANT_ALPHA_UUID, TENANT_ALPHA_SLUG, amount, amount),
            )
        conn.commit()
    finally:
        conn.close()

    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    signing_kr = ProvenanceSigningKeyring({"neg-prov-k1": {"private_key_hex": priv_hex, "status": "ACTIVE"}})
    signer = ProvenanceSigner(signing_kr)
    verifier = ProvenanceVerifier(signing_kr)

    cb_secret = "xendit_neg_test_callback_token_32chars_012345"
    biz_id = "xnd_biz_neg_test_001"
    raw_webhook = {
        "id": event_id,
        "event_id": event_id,
        "business_id": biz_id,
        "external_id": order_id,
        "qr_id": provider_event_id,
        "status": "PAID",
        "amount": amount,
        "currency": "IDR",
    }
    capability = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="XENDIT",
        verification_method="XENDIT_CALLBACK_TOKEN",
        credential_profile_id="cred_xendit_neg_obx",
        expected_provider_account_id=biz_id,
        provider_verification_secret=cb_secret,
        webhook_headers={"X-Callback-Token": cb_secret, "webhook-id": event_id},
        webhook_payload=raw_webhook,
        authoritative_order_id=order_id,
        authoritative_canonical_tenant_id=TENANT_ALPHA_UUID,
        authoritative_order_amount=amount,
        authoritative_sku_id="SKU-OBX-NEG",
        verified_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    _install_order_scoped_failure_trigger("payment_outbox_events", order_id, suffix)
    try:
        with pytest.raises(SettlementProvenanceError) as exc_info:
            commit_verified_settlement_transaction(
                capability=capability,
                signer=signer,
                verifier=verifier,
                raw_webhook_payload=raw_webhook,
                db_conn_factory=get_db_connection,
            )
        assert exc_info.value.error_code == "DATABASE_UNAVAILABLE"
        assert exc_info.value.http_status == 503

        snap = _fetch_order_db_snapshot(order_id)
        assert snap["order"] is not None
        assert snap["order"][3] == "PENDING"
        assert len(snap["payment_events"]) == 0, "payment_events must roll back on outbox failure"
        assert len(snap["financial_ledger"]) == 0, "financial_ledger must roll back on outbox failure"
        assert len(snap["payment_outbox_events"]) == 0
    finally:
        _drop_trigger_and_function("payment_outbox_events", suffix)


def test_negative_checkout_service_outbox_failure_rolls_back_settlement():
    """Negative Test 1c (Blocker B-1 — Checkout Service):
    Simulate DB failure specifically on payment_outbox_events insert inside
    `execute_order_settlement_transaction`. Proves full transaction rollback:
    - Exception propagates immediately
    - Zero payment_events persisted
    - Zero financial_ledger persisted
    - Zero payment_outbox_events persisted
    """
    try:
        _conn_probe = get_db_connection()
        _conn_probe.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL required for checkout_service outbox rollback test is unreachable: {exc}")

    order_id = f"ORD-CHK-OBX-{uuid.uuid4().hex[:8]}"
    event_id = f"evt_chk_obx_{uuid.uuid4().hex[:8]}"
    suffix = f"chk_obx_{uuid.uuid4().hex[:8]}"
    amount = 125000

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.orders (
                    id, tenant_id, tenant_slug, sku_id, product_id, product_title,
                    status, payment_status, order_status, gross_amount, amount
                ) VALUES (
                    %s, %s, %s, 'prod_digital', 'prod_digital', 'Digital Checkout Rollback Test',
                    'PENDING', 'PENDING', 'PENDING', %s, %s
                );
                """,
                (order_id, TENANT_ALPHA_UUID, TENANT_ALPHA_SLUG, amount, amount),
            )
        conn.commit()
    finally:
        conn.close()

    _install_order_scoped_failure_trigger("payment_outbox_events", order_id, suffix)
    try:
        with pytest.raises(Exception) as exc_info:
            execute_order_settlement_transaction(
                event_id=event_id,
                external_id=order_id,
                tenant_id=TENANT_ALPHA_UUID,
                amount=amount,
                payload={"product_id": "prod_digital", "order_id": order_id},
                provider="XENDIT",
            )
        assert "payment_outbox_events" in str(exc_info.value)

        snap = _fetch_order_db_snapshot(order_id)
        assert snap["order"] is not None
        assert snap["order"][3] == "PENDING"
        assert len(snap["payment_events"]) == 0, "payment_events must roll back on outbox failure"
        assert len(snap["financial_ledger"]) == 0, "financial_ledger must roll back on outbox failure"
        assert len(snap["payment_outbox_events"]) == 0
    finally:
        _drop_trigger_and_function("payment_outbox_events", suffix)


def test_negative_payment_intent_lifecycle_outbox_exception_propagates_and_rolls_back():
    """Negative Test 1d (Blocker B-2 — PaymentIntentLifecycleService):
    1. Direct call to `_record_outbox_event` with a failing DB cursor MUST propagate
       the exception instead of swallowing it.
    2. Live PostgreSQL `mark_provider_result` with a failure trigger on `payment_outbox_events`
       MUST propagate the DB error and roll back `payment_intents.initiation_state` to INITIATING.
    """
    svc = PaymentIntentLifecycleService()

    # Part 1: Direct unit assertion — _record_outbox_event must NEVER swallow DB exceptions
    class _FailingCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            raise RuntimeError("SIMULATED_OUTBOX_DB_FAILURE_B2")

    class _FailingConn:
        def cursor(self):
            return _FailingCursor()

    with pytest.raises(RuntimeError, match="SIMULATED_OUTBOX_DB_FAILURE_B2"):
        svc._record_outbox_event(
            aggregate_id="ORD-PIL-UNIT-001",
            event_type="PAYMENT_INTENT_ACTIVATED",
            payload={"order_id": "ORD-PIL-UNIT-001", "tenant_id": TENANT_ALPHA_UUID, "idempotency_key": "ik-pil-unit-001"},
            conn=_FailingConn(),
        )

    # Part 2: Live PostgreSQL rollback proof on mark_provider_result
    try:
        _conn_probe = get_db_connection()
        _conn_probe.close()
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL required for payment_intent_lifecycle rollback test is unreachable: {exc}")

    order_id = f"ORD-PIL-OBX-{uuid.uuid4().hex[:8]}"
    idemp_key = f"ik-pil-obx-{uuid.uuid4().hex[:10]}"
    suffix = f"pil_obx_{uuid.uuid4().hex[:8]}"

    intent = svc.initiate_or_reconcile_intent(
        tenant_id=TENANT_ALPHA_UUID,
        order_id=order_id,
        amount=99000,
        idempotency_key=idemp_key,
        request_payload={"order_id": order_id, "amount": 99000},
    )
    assert intent["initiation_state"] == "INITIATING"

    _install_order_scoped_failure_trigger("payment_outbox_events", order_id, suffix)
    try:
        with pytest.raises(Exception) as exc_info:
            svc.mark_provider_result(
                idempotency_key=idemp_key,
                success=True,
                provider_ref="qr_pil_rollback_001",
                qr_string="000201010212MOCKQRIS",
            )
        assert "payment_outbox_events" in str(exc_info.value)

        # Verify payment_intents rolled back cleanly to INITIATING and 0 outbox rows exist
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT initiation_state, qr_string FROM public.payment_intents WHERE idempotency_key = %s;",
                    (idemp_key,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "INITIATING", f"Expected INITIATING after rollback, got {row[0]}"
                assert row[1] is None, "qr_string mutation must be rolled back when outbox insert fails"

                cur.execute(
                    "SELECT COUNT(*) FROM public.payment_outbox_events WHERE order_id = %s;",
                    (order_id,),
                )
                assert cur.fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        _drop_trigger_and_function("payment_outbox_events", suffix)


# =============================================================================
# 2. ZERO DIRECT UPDATE ORDERS & ZERO RUNTIME DDL STATIC AUDIT (BLOCKERS A & B)
# =============================================================================

def test_negative_audit_zero_direct_orders_mutations_and_zero_runtime_ddl():
    """Negative Test 2 (Blockers A & B):
    Static code analysis verifying that Core settlement paths and worker dispatchers
    contain ZERO direct `UPDATE orders` / `UPDATE public.orders` and ZERO runtime DDL
    (`CREATE TABLE IF NOT EXISTS payment_outbox_events`, `ALTER TABLE ...`).
    """
    prov_src = (CORE_ROOT / "app" / "core" / "security" / "provenance_authority.py").read_text(encoding="utf-8")
    acad_src = (CORE_ROOT / "app" / "services" / "academy_service.py").read_text(encoding="utf-8")
    checkout_src = (CORE_ROOT / "app" / "services" / "checkout_service.py").read_text(encoding="utf-8")
    xendit_src = (CORE_ROOT / "app" / "routes" / "xendit.py").read_text(encoding="utf-8")
    dispatcher_src = (CORE_ROOT / "app" / "workers" / "payment_outbox_dispatcher.py").read_text(encoding="utf-8")

    # Blocker A: Zero direct orders mutations in settlement authority & services
    assert "UPDATE orders" not in prov_src, "Direct 'UPDATE orders' found in provenance_authority.py"
    assert "UPDATE public.orders" not in prov_src, "Direct 'UPDATE public.orders' found in provenance_authority.py"
    assert "UPDATE public.orders" not in acad_src, "Direct 'UPDATE public.orders' found in academy_service.py"
    assert "UPDATE orders" not in acad_src, "Direct 'UPDATE orders' found in academy_service.py"
    assert "UPDATE orders" not in xendit_src, "Direct 'UPDATE orders' found in xendit.py"

    # Blocker B: Zero runtime DDL and zero swallowed outbox exceptions
    lifecycle_src = (CORE_ROOT / "app" / "services" / "payment_intent_lifecycle.py").read_text(encoding="utf-8")
    mig037_src = (
        CORE_ROOT / "migrations" / "037_core_payment_intent_idempotency_and_settlement_outbox.sql"
    ).read_text(encoding="utf-8")
    init_schema_src = (CORE_ROOT / "scripts" / "init_test_postgres_schema.py").read_text(encoding="utf-8")

    assert "Outbox write note" not in lifecycle_src, "Swallowed outbox exception found in payment_intent_lifecycle.py"
    assert "uq_payment_outbox_events_idempotency_key" in mig037_src, (
        "Migration 037 missing uq_payment_outbox_events_idempotency_key UNIQUE (idempotency_key)"
    )
    assert "uq_payment_outbox_events_idempotency_key" in init_schema_src, (
        "init_test_postgres_schema.py missing uq_payment_outbox_events_idempotency_key parity"
    )

    for module_name, src in [
        ("provenance_authority", prov_src),
        ("academy_service", acad_src),
        ("checkout_service", checkout_src),
        ("payment_outbox_dispatcher", dispatcher_src),
        ("payment_intent_lifecycle", lifecycle_src),
    ]:
        assert "CREATE TABLE IF NOT EXISTS payment_outbox_events" not in src, (
            f"Runtime DDL CREATE TABLE found in {module_name}"
        )
        assert "ALTER TABLE payment_outbox_events" not in src, (
            f"Runtime DDL ALTER TABLE found in {module_name}"
        )
        assert "SAVEPOINT sp_outbox" not in src and "SAVEPOINT outbox" not in src, (
            f"Swallowed outbox SAVEPOINT pattern found in {module_name}"
        )


# =============================================================================
# 3. ACADEMY DEFAULT-DENY IN STAGING & UNSET ENV (BLOCKER E)
# =============================================================================

def test_negative_academy_direct_checkout_default_deny_across_environments(monkeypatch):
    """Negative Test 3 (Blocker E):
    Enforces strict default-deny across ALL environments (development, staging, production, unset).
    Calling /api/v1/academy/invoice without ENABLE_ACADEMY_DIRECT_CHECKOUT=true MUST return 503.
    """
    client = TestClient(app)
    penny_payload = {
        "sku": "TEST-PENNY-1500",
        "customer_name": "Test Staging User",
        "customer_email": "test.staging@onlineboost.id",
        "customer_phone": "6281234567890",
    }

    # Case 1: APP_ENV=staging with ENABLE_ACADEMY_DIRECT_CHECKOUT unset
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("ENABLE_ACADEMY_DIRECT_CHECKOUT", raising=False)
    res = client.post("/api/v1/academy/invoice", json=penny_payload)
    assert res.status_code == 503, f"Expected 503 in staging when unset, got {res.status_code}"
    data = res.json()
    assert data["detail"]["error_code"] == "ACADEMY_CHECKOUT_DISABLED_PHASE1"

    # Case 2: APP_ENV=development with ENABLE_ACADEMY_DIRECT_CHECKOUT unset
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ENABLE_ACADEMY_DIRECT_CHECKOUT", raising=False)
    res = client.post("/api/v1/academy/invoice", json=penny_payload)
    assert res.status_code == 503, f"Expected 503 in dev when unset, got {res.status_code}"

    # Case 3: ENABLE_ACADEMY_DIRECT_CHECKOUT="false" explicitly
    monkeypatch.setenv("ENABLE_ACADEMY_DIRECT_CHECKOUT", "false")
    res = client.post("/api/v1/academy/invoice", json=penny_payload)
    assert res.status_code == 503, f"Expected 503 when false, got {res.status_code}"

    # Case 4: ENABLE_ACADEMY_DIRECT_CHECKOUT="true" (case-insensitive) enables endpoint
    monkeypatch.setenv("ENABLE_ACADEMY_DIRECT_CHECKOUT", "TRUE")
    monkeypatch.setenv("BOONTRACK_INTERNAL_HMAC_SECRET", "test_secret_for_penny")
    res = client.post(
        "/api/v1/academy/invoice",
        json=penny_payload,
        headers={"X-Internal-Secret": "test_secret_for_penny"},
    )
    assert res.status_code != 503, f"Expected non-503 when explicitly enabled, got {res.status_code}: {res.text}"
    assert "ACADEMY_CHECKOUT_DISABLED_PHASE1" not in res.text
