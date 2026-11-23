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
async def test_negative_outbox_failure_aborts_and_rolls_back_entire_settlement(monkeypatch):
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

    monkeypatch.setenv("ENABLE_ACADEMY_DIRECT_CHECKOUT", "true")
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


# =============================================================================
# 4. ACADEMY CROSS-CHANNEL ISOLATION MATRIX (HTTP + SERVICE + PLATFORM WA + TENANT WA)
# =============================================================================

_ACADEMY_DENY_ENV_MATRIX = [
    ("unset_default", None, "staging", "true", ""),
    ("explicit_false", "false", "development", "true", ""),
    ("hold_false_whitelisted_prod", "false", "production", "false", "6288226098088"),
    ("unset_hold_false_whitelisted_dev", None, "development", "false", "6288226098088"),
]


def _apply_academy_deny_env(
    monkeypatch,
    flag_val,
    app_env: str,
    strict_hold: str,
    whitelist: str,
) -> None:
    if flag_val is None:
        monkeypatch.delenv("ENABLE_ACADEMY_DIRECT_CHECKOUT", raising=False)
    else:
        monkeypatch.setenv("ENABLE_ACADEMY_DIRECT_CHECKOUT", flag_val)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("ONLINEBOOST_PAYMENT_STRICT_HOLD", strict_hold)
    monkeypatch.setenv("PILOT_INTERNAL_WHITELIST", whitelist)


@pytest.mark.parametrize("case_id,flag_val,app_env,strict_hold,whitelist", _ACADEMY_DENY_ENV_MATRIX)
@pytest.mark.parametrize("tenant_slug", ["onlineboost", "boon", "other-tenant"])
def test_negative_academy_http_and_service_boundary_default_deny_matrix(
    monkeypatch, case_id, flag_val, app_env, strict_hold, whitelist, tenant_slug
):
    """P0 Academy Cross-Channel Isolation (Entrypoints 1 & 2):
    Proves BOTH `POST /api/v1/academy/invoice` AND direct service calls
    (`generate_academy_qris_invoice`, `_persist_order_and_checkout_session_tx`)
    fail closed BEFORE any DB connection, `orders` insert, `checkout_sessions`,
    `payment_intents`, or QRIS payload across ALL matrix conditions and tenants.
    """
    from unittest.mock import patch, MagicMock
    from app.services.academy_service import (
        AcademyDirectCheckoutDisabledError,
        ACADEMY_CHECKOUT_DISABLED_ERROR_CODE,
        _persist_order_and_checkout_session_tx,
        reset_academy_test_state,
    )

    reset_academy_test_state()
    _apply_academy_deny_env(monkeypatch, flag_val, app_env, strict_hold, whitelist)

    caller_phone = "6288226098088"
    client = TestClient(app)

    with patch("app.core.database.get_db_connection") as mock_db_conn, \
         patch("app.services.academy_service.get_supabase") as mock_sb:
        # Entrypoint 1: HTTP POST /api/v1/academy/invoice
        http_res = client.post(
            "/api/v1/academy/invoice",
            json={
                "customer_name": "Matrix Buyer",
                "customer_email": "matrix@example.id",
                "customer_phone": caller_phone,
                "tenant_id": tenant_slug,
            },
        )
        assert http_res.status_code == 503, f"[{case_id}/{tenant_slug}] Expected 503, got {http_res.status_code}"
        assert http_res.json()["detail"]["error_code"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE

        # Entrypoint 2a: Direct generate_academy_qris_invoice()
        with pytest.raises(AcademyDirectCheckoutDisabledError) as exc_inv:
            generate_academy_qris_invoice(
                customer_name="Matrix Buyer",
                customer_email="matrix@example.id",
                customer_phone=caller_phone,
                tenant_id=tenant_slug,
                use_unique_code=True,
            )
        assert exc_inv.value.error_code == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE

        # Entrypoint 2b: Direct _persist_order_and_checkout_session_tx()
        with pytest.raises(AcademyDirectCheckoutDisabledError) as exc_tx:
            _persist_order_and_checkout_session_tx(
                order_id="BTA-BLOCKED-001",
                requested_tenant=tenant_slug,
                resolved_sku_id="OB-BATCH1-249K",
                resolved_sku_name="BoonTrack Academy",
                base_price=249000,
                use_unique_code=True,
                is_penny_test=False,
                static_qris_override=None,
                customer_name="Matrix Buyer",
                customer_phone=caller_phone,
                customer_email="matrix@example.id",
                token_mgr=MagicMock(),
                now_epoch=1763860000,
            )
        assert exc_tx.value.error_code == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE

        # Zero DB connections, zero Supabase writes, zero in-memory invoices
        assert not mock_db_conn.called, f"[{case_id}/{tenant_slug}] DB connection must never be opened"
        assert not mock_sb.called, f"[{case_id}/{tenant_slug}] Supabase client must never be called"
        assert len(_ACADEMY_INVOICES) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,flag_val,app_env,strict_hold,whitelist", _ACADEMY_DENY_ENV_MATRIX)
@pytest.mark.parametrize("tenant_slug", ["onlineboost", "boon", "other-tenant"])
async def test_negative_academy_fast_path_and_ctwa_service_boundary_default_deny(
    monkeypatch, case_id, flag_val, app_env, strict_hold, whitelist, tenant_slug
):
    """P0 Academy Service-Level Isolation for Fast-Path QRIS & CTWA Gatekeeper:
    Even with ONLINEBOOST_PAYMENT_STRICT_HOLD=false and whitelisted phone, neither
    `generate_fast_path_xendit_qris_batch1` nor `ctwa_state_engine.execute_deterministic_gatekeeper`
    may invoke Xendit or mutate `orders` when ENABLE_ACADEMY_DIRECT_CHECKOUT != 'true'.
    """
    from unittest.mock import patch, AsyncMock
    from app.services.academy_service import (
        AcademyDirectCheckoutDisabledError,
        ACADEMY_CHECKOUT_DISABLED_ERROR_CODE,
        generate_fast_path_xendit_qris_batch1,
        reset_academy_test_state,
    )
    from app.services.ctwa_state_engine import ctwa_state_engine

    reset_academy_test_state()
    ctwa_state_engine.sessions.clear()
    _apply_academy_deny_env(monkeypatch, flag_val, app_env, strict_hold, whitelist)
    caller_phone = "6288226098088"

    with patch("app.core.database.get_db_connection") as mock_db_conn, \
         patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http_post:
        with pytest.raises(AcademyDirectCheckoutDisabledError) as exc_fp:
            await generate_fast_path_xendit_qris_batch1(
                customer_phone=caller_phone,
                customer_name="Whitelisted Pilot",
                customer_email="pilot@onlineboost.id",
                tenant_id=tenant_slug,
            )
        assert exc_fp.value.error_code == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE

        with pytest.raises(AcademyDirectCheckoutDisabledError) as exc_gk:
            await ctwa_state_engine.execute_deterministic_gatekeeper(
                phone=caller_phone,
                name="Whitelisted Pilot",
                email="pilot@onlineboost.id",
                phone_number_id="1419090974617162",
            )
        assert exc_gk.value.error_code == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE

        assert not mock_db_conn.called
        assert not mock_xendit.called
        assert not mock_http_post.called


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,flag_val,app_env,strict_hold,whitelist", _ACADEMY_DENY_ENV_MATRIX)
@pytest.mark.parametrize("resolved_tenant", ["onlineboost", "boon", "other-tenant"])
async def test_negative_academy_platform_webhook_router_isolation_matrix(
    monkeypatch, case_id, flag_val, app_env, strict_hold, whitelist, resolved_tenant
):
    """P0 Academy Cross-Channel Isolation (Entrypoint 3 — PlatformWebhookRouter):
    Proves `PlatformWebhookRouter.handle()` -> `academy_bot.process_inbound()` NEVER generates
    an invoice, QRIS payload, `orders` row, or `checkout_sessions` entry under any matrix
    condition (unset, false, strict_hold=false + whitelisted phone, onlineboost vs non-onlineboost).
    """
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.whatsapp.platform_webhook_router import PlatformWebhookRouter
    from app.whatsapp.traffic_splitter import WebhookExecutionTrace
    from app.services.academy_service import (
        ACADEMY_CHECKOUT_DISABLED_ERROR_CODE,
        STATE_1_AWAITING_EMAIL,
        academy_bot,
        reset_academy_test_state,
    )

    reset_academy_test_state()
    PlatformWebhookRouter.reset_state()
    _apply_academy_deny_env(monkeypatch, flag_val, app_env, strict_hold, whitelist)

    caller_phone = "6288226098088"
    mock_resolved = MagicMock()
    mock_resolved.slug = resolved_tenant

    mock_ingress = MagicMock()
    mock_ingress.allowed = True

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock, return_value=mock_resolved), \
         patch("app.services.ingress_pipeline.ingress_pipeline.evaluate_ingress", new_callable=AsyncMock, return_value=mock_ingress), \
         patch("app.services.phone_suppression_service.is_phone_suppressed", return_value=False), \
         patch("app.services.whatsapp.cloud_api.log_to_supabase_messages", new_callable=AsyncMock), \
         patch("app.whatsapp.platform_webhook_router.send_whatsapp_text", new_callable=AsyncMock), \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock), \
         patch("app.services.academy_service.generate_academy_qris_invoice") as mock_gen_inv, \
         patch("app.services.academy_service._persist_order_and_checkout_session_tx") as mock_persist_tx, \
         patch("app.core.database.get_db_connection") as mock_db_conn:

        # Path A: Route C storefront_direct message (would otherwise call generate_academy_qris_invoice)
        trace_c = WebhookExecutionTrace(f"msg_plat_c_{case_id}_{resolved_tenant}", "1365010890024026", caller_phone, "storefront")
        res_c = await PlatformWebhookRouter.handle(
            sender_phone=caller_phone,
            incoming_text="Halo kak, saya mau konfirmasi pemesanan Inkubasi CTWA Batch 1.",
            phone_number_id="1365010890024026",
            raw_msg={"id": f"wamid_plat_c_{case_id}_{resolved_tenant}", "type": "text"},
            trace=trace_c,
        )
        assert res_c["handled"] is True
        assert res_c["action"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
        assert res_c["error_code"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
        assert res_c.get("order_id") is None
        assert res_c.get("qr_string", "") == ""
        assert res_c.get("qr_image_url", "") == ""

        # Path B: Active STATE_1_AWAITING_EMAIL session receiving email (would otherwise call generate_academy_qris_invoice)
        academy_bot.set_session(
            caller_phone,
            state=STATE_1_AWAITING_EMAIL,
            name="Whitelisted Buyer",
            tenant_id=resolved_tenant,
            campaign="alumni_cpm",
        )
        trace_s1 = WebhookExecutionTrace(f"msg_plat_s1_{case_id}_{resolved_tenant}", "1365010890024026", caller_phone, "email")
        res_s1 = await PlatformWebhookRouter.handle(
            sender_phone=caller_phone,
            incoming_text="whitelisted.buyer@example.id",
            phone_number_id="1365010890024026",
            raw_msg={"id": f"wamid_plat_s1_{case_id}_{resolved_tenant}", "type": "text"},
            trace=trace_s1,
        )
        assert res_s1["handled"] is True
        assert res_s1["action"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
        assert res_s1["error_code"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
        assert res_s1.get("order_id") is None
        assert res_s1.get("qr_string", "") == ""

        # Prove zero invoice generation, zero DB mutations, zero checkout sessions
        assert not mock_gen_inv.called
        assert not mock_persist_tx.called
        assert not mock_db_conn.called
        assert len(_ACADEMY_INVOICES) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,flag_val,app_env,strict_hold,whitelist", _ACADEMY_DENY_ENV_MATRIX)
@pytest.mark.parametrize("tenant_slug", ["onlineboost", "boon", "other-tenant"])
async def test_negative_academy_tenant_webhook_router_isolation_matrix(
    monkeypatch, case_id, flag_val, app_env, strict_hold, whitelist, tenant_slug
):
    """P0 Academy Cross-Channel Isolation (Entrypoint 4 — TenantWebhookRouter in traffic_splitter.py):
    Proves `TenantWebhookRouter.handle()` blocks Academy direct invoice/QRIS/order generation
    across storefront_direct, STATE_1_AWAITING_EMAIL, direct QRIS keywords, and nfm_reply Flow
    submissions for BOTH `onlineboost` and non-`onlineboost` tenants under all matrix conditions.
    """
    import json as _json
    from unittest.mock import patch, AsyncMock
    from app.whatsapp.traffic_splitter import (
        TenantWebhookRouter,
        TenantRuntimeContext,
        WebhookExecutionTrace,
    )
    from app.services.academy_service import (
        ACADEMY_CHECKOUT_DISABLED_ERROR_CODE,
        STATE_1_AWAITING_EMAIL,
        academy_bot,
        reset_academy_test_state,
    )
    from app.services.ctwa_state_engine import ctwa_state_engine

    reset_academy_test_state()
    ctwa_state_engine.sessions.clear()
    _apply_academy_deny_env(monkeypatch, flag_val, app_env, strict_hold, whitelist)

    caller_phone = "6288226098088"
    tenant_ctx = TenantRuntimeContext(
        tenant_id=tenant_slug,
        slug=tenant_slug,
        business_type="DIGITAL",
        capabilities={"catalog": True, "order": True},
        metadata={"name": f"Tenant {tenant_slug}"},
    )

    with patch("app.services.phone_suppression_service.is_phone_suppressed", return_value=False), \
         patch("app.services.whatsapp.cloud_api.log_to_supabase_messages", new_callable=AsyncMock), \
         patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock), \
         patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock), \
         patch("app.services.academy_service.generate_academy_qris_invoice") as mock_gen_inv, \
         patch("app.services.academy_service._persist_order_and_checkout_session_tx") as mock_persist_tx, \
         patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit, \
         patch("app.core.database.get_db_connection") as mock_db_conn:

        # 1. Storefront direct trigger (Route C)
        res_sf = await TenantWebhookRouter.handle(
            tenant_context=tenant_ctx,
            sender_phone=caller_phone,
            incoming_text="Halo kak, saya mau konfirmasi pemesanan Inkubasi CTWA Batch 1.",
            phone_number_id="1419090974617162",
            contact_name="Whitelisted Buyer",
            raw_msg={"id": f"wamid_ten_sf_{case_id}_{tenant_slug}", "type": "text"},
            trace=WebhookExecutionTrace("tr_sf", "1419090974617162", caller_phone, "storefront"),
        )
        assert res_sf["action"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
        assert res_sf["error_code"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
        assert res_sf.get("order_id") is None
        assert res_sf.get("qr_string", "") == ""

        # 2. Active STATE_1_AWAITING_EMAIL session receiving email
        academy_bot.set_session(
            caller_phone,
            state=STATE_1_AWAITING_EMAIL,
            name="Whitelisted Buyer",
            tenant_id=tenant_slug,
            campaign="ads_ctwa",
        )
        res_email = await TenantWebhookRouter.handle(
            tenant_context=tenant_ctx,
            sender_phone=caller_phone,
            incoming_text="whitelisted.buyer@example.id",
            phone_number_id="1419090974617162",
            contact_name="Whitelisted Buyer",
            raw_msg={"id": f"wamid_ten_em_{case_id}_{tenant_slug}", "type": "text"},
            trace=WebhookExecutionTrace("tr_em", "1419090974617162", caller_phone, "email"),
        )
        assert res_email["action"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
        assert res_email["error_code"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
        assert res_email.get("order_id") is None

        # 3. Direct QRIS fast-path keyword and nfm_reply Flow submission on onlineboost
        if tenant_slug == "onlineboost":
            reset_academy_test_state()
            res_qris = await TenantWebhookRouter.handle(
                tenant_context=tenant_ctx,
                sender_phone=caller_phone,
                incoming_text="bayar via qris",
                phone_number_id="1419090974617162",
                contact_name="Whitelisted Buyer",
                raw_msg={"id": f"wamid_ten_qr_{case_id}", "type": "text"},
                trace=WebhookExecutionTrace("tr_qr", "1419090974617162", caller_phone, "bayar via qris"),
            )
            assert res_qris["action"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
            assert res_qris.get("order_id") is None
            assert res_qris.get("qr_string", "") == ""

            flow_raw = {
                "id": f"wamid_ten_flow_{case_id}",
                "type": "interactive",
                "interactive": {
                    "type": "nfm_reply",
                    "nfm_reply": {
                        "response_json": _json.dumps({"name": "Whitelisted Buyer", "email": "pilot@onlineboost.id"})
                    },
                },
            }
            res_flow = await TenantWebhookRouter.handle(
                tenant_context=tenant_ctx,
                sender_phone=caller_phone,
                incoming_text="",
                phone_number_id="1419090974617162",
                contact_name="Whitelisted Buyer",
                raw_msg=flow_raw,
                trace=WebhookExecutionTrace("tr_flow", "1419090974617162", caller_phone, "nfm_reply"),
            )
            assert res_flow["action"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
            assert res_flow.get("order_id") is None

        # Zero invoice, zero QRIS, zero orders, zero Xendit calls across ALL paths
        assert not mock_gen_inv.called
        assert not mock_persist_tx.called
        assert not mock_xendit.called
        assert not mock_db_conn.called
        assert len(_ACADEMY_INVOICES) == 0


@pytest.mark.asyncio
async def test_negative_academy_bot_direct_process_inbound_blocks_payment_but_preserves_conversational(monkeypatch):
    """Direct call to `academy_bot.process_inbound()` blocks ALL payment-issuing paths even with
    ONLINEBOOST_PAYMENT_STRICT_HOLD=false + whitelisted phone (and for non-onlineboost tenants),
    while preserving approved non-payment conversational qualification ('MAU').
    """
    from unittest.mock import patch, AsyncMock
    from app.services.academy_service import (
        ACADEMY_CHECKOUT_DISABLED_ERROR_CODE,
        STATE_1_AWAITING_EMAIL,
        STATE_QUALIFYING,
        academy_bot,
        reset_academy_test_state,
    )

    reset_academy_test_state()
    _apply_academy_deny_env(monkeypatch, None, "development", "false", "6288226098088")
    caller_phone = "6288226098088"

    with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock), \
         patch("app.services.academy_service.generate_academy_qris_invoice") as mock_gen_inv, \
         patch("app.core.database.get_db_connection") as mock_db_conn:

        # 1. Approved non-payment conversational reply ('MAU') still works with zero orders/invoices
        res_mau = await academy_bot.process_inbound(
            sender_phone=caller_phone,
            incoming_text="MAU",
            contact_name="Alumni",
            tenant_id="onlineboost",
        )
        assert res_mau["handled"] is True
        assert res_mau["state"] == STATE_QUALIFYING
        assert res_mau["action"] == "ALUMNI_MAU_QUALIFY"
        assert not mock_gen_inv.called

        # 2. Direct payment triggers across onlineboost & non-onlineboost ('boon', 'other-tenant') are blocked
        for t_slug in ("onlineboost", "boon", "other-tenant"):
            reset_academy_test_state()
            academy_bot.set_session(
                caller_phone,
                state=STATE_1_AWAITING_EMAIL,
                name="Buyer",
                tenant_id=t_slug,
                campaign="alumni_cpm",
            )
            res_s1 = await academy_bot.process_inbound(
                sender_phone=caller_phone,
                incoming_text="buyer@example.id",
                contact_name="Buyer",
                tenant_id=t_slug,
            )
            assert res_s1["action"] == ACADEMY_CHECKOUT_DISABLED_ERROR_CODE
            assert res_s1["order_id"] is None
            assert res_s1["qr_string"] == ""

        assert not mock_gen_inv.called
        assert not mock_db_conn.called
        assert len(_ACADEMY_INVOICES) == 0


# =============================================================================
# 5. PG17 REPLAY RUNNER FAIL-CLOSED GATE & PROVENANCE UNIT + CLI TESTS (P1)
# =============================================================================

def _load_pg17_runner_module():
    import importlib.util

    runner_path = CORE_ROOT / "tools" / "packet3d-e2e" / "replay_manifest_pg17.py"
    spec = importlib.util.spec_from_file_location("replay_manifest_pg17", runner_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_valid_pg17_report(mod) -> dict:
    return {
        "manifest_path": str(CORE_ROOT / "migrations" / "reconciliation" / "shared_db_migration_manifest.json"),
        "strict_json_valid": True,
        "strict_json_error": None,
        "executed_count": 110,
        "total_manifest_entries": 110,
        "replay_ratio": "110/110",
        "sql_failures": [],
        "c01_to_c08": {
            "C-01": "PASS (verified)",
            "C-02": "PASS (verified)",
            "C-03": "PASS (verified)",
            "C-04": "PASS (verified)",
            "C-05/C-06": "PASS (verified)",
            "C-07": "PASS (113/113 tenant-scoped tables have RLS=true & FORCE=true; 0 wildcard policies)",
            "C-08": "PASS (verified)",
        },
        "p3d_schema_audit": {
            "payment_outbox_events_columns_from_037": {
                col: ["text", "YES"] for col in mod.DISPATCHER_REQUIRED_OUTBOX_COLS
            },
            "missing_columns": [],
            "payment_outbox_events_missing_columns_expected_by_A3_dispatcher_and_provenance": [],
            "rls_status": {
                tbl: {"rls": True, "force_rls": True} for tbl in mod.REQUIRED_RLS_TABLES
            },
            "wildcard_policies_count": 0,
            "wildcard_policies": [],
            "tenant_tables_missing_rls_or_force_rls": [],
            "payment_outbox_events_unique_constraints": {
                "uq_payment_outbox_events_event_id": "UNIQUE (event_id)",
                "uq_payment_outbox_events_idempotency_key": "UNIQUE (idempotency_key)",
            },
            "payment_outbox_events_on_conflict_idempotency_key_probe": "PASS (duplicate ignored)",
            "payment_outbox_events_on_conflict_probe_passed": True,
        },
        "provenance": {
            "source_head_sha": "a" * 40,
            "inbox_head_sha": "b" * 40,
            "generated_at_utc": "2026-11-23T00:00:00+00:00",
            "sha256": {
                req: "0" * 64 for req in mod.REQUIRED_PROVENANCE_SHA256_FILES
            },
        },
    }


def test_negative_pg17_replay_gate_fail_closed_matrix_and_cli_exit(tmp_path):
    """P1 Fail-Closed PG17 Replay Gate Unit + CLI Tests:
    Proves `evaluate_replay_gate(report)` returns False AND the CLI exits non-zero (1)
    under every mandatory failure condition:
    - strict_json_valid != True, non-empty sql_failures, bad replay_ratio
    - C-01..C-08 failure or missing assertion key
    - Missing required dispatcher column
    - RLS / FORCE RLS failure or wildcard_policies_count > 0
    - Outbox unique constraint missing or ON CONFLICT (idempotency_key) probe failure
    - Missing/invalid provenance source_head_sha or required file sha256 hashes
    """
    import copy
    import json
    import subprocess
    import sys

    mod = _load_pg17_runner_module()
    runner_path = CORE_ROOT / "tools" / "packet3d-e2e" / "replay_manifest_pg17.py"

    # Baseline valid report MUST pass both evaluate_replay_gate() and CLI --verify-report
    valid_rep = _make_valid_pg17_report(mod)
    ok, failures = mod.evaluate_replay_gate(valid_rep)
    assert ok is True, f"Expected valid baseline report to pass, got failures: {failures}"
    assert failures == []

    valid_file = tmp_path / "valid_report.json"
    valid_file.write_text(json.dumps(valid_rep), encoding="utf-8")
    proc_ok = subprocess.run(
        [sys.executable, str(runner_path), "--verify-report", str(valid_file)],
        capture_output=True,
        text=True,
    )
    assert proc_ok.returncode == 0, f"Expected exit 0 for valid report, got {proc_ok.returncode}: {proc_ok.stdout} {proc_ok.stderr}"

    # Build comprehensive fail-closed mutation matrix
    def _mutate(fn):
        r = copy.deepcopy(valid_rep)
        fn(r)
        return r

    failing_cases = {
        "strict_json_false": _mutate(lambda r: r.update({"strict_json_valid": False})),
        "sql_failures_non_empty": _mutate(lambda r: r.update({"sql_failures": [{"entry": "037", "error": "boom"}]})),
        "replay_ratio_mismatch": _mutate(lambda r: r.update({"executed_count": 109, "replay_ratio": "109/110"})),
        "c03_failed": _mutate(lambda r: r["c01_to_c08"].update({"C-03": "FAIL (invalid status accepted)"})),
        "c07_missing": _mutate(lambda r: r["c01_to_c08"].pop("C-07")),
        "c05_c06_missing": _mutate(lambda r: r["c01_to_c08"].pop("C-05/C-06")),
        "c01_to_c08_error_set": _mutate(lambda r: r.update({"c01_to_c08_error": "AssertionError: C-08 failed"})),
        "missing_dispatcher_column_flag": _mutate(
            lambda r: r["p3d_schema_audit"].update(
                {
                    "missing_columns": ["provenance_envelope"],
                    "payment_outbox_events_missing_columns_expected_by_A3_dispatcher_and_provenance": [
                        "provenance_envelope"
                    ],
                }
            )
        ),
        "missing_dispatcher_column_in_schema": _mutate(
            lambda r: r["p3d_schema_audit"]["payment_outbox_events_columns_from_037"].pop("locked_by")
        ),
        "force_rls_false": _mutate(
            lambda r: r["p3d_schema_audit"]["rls_status"]["payment_outbox_events"].update({"force_rls": False})
        ),
        "rls_false": _mutate(
            lambda r: r["p3d_schema_audit"]["rls_status"]["orders"].update({"rls": False})
        ),
        "wildcard_policies_nonzero": _mutate(
            lambda r: r["p3d_schema_audit"].update({"wildcard_policies_count": 1})
        ),
        "missing_outbox_uq_idempotency": _mutate(
            lambda r: r["p3d_schema_audit"]["payment_outbox_events_unique_constraints"].pop(
                "uq_payment_outbox_events_idempotency_key"
            )
        ),
        "missing_outbox_uq_event_id": _mutate(
            lambda r: r["p3d_schema_audit"]["payment_outbox_events_unique_constraints"].pop(
                "uq_payment_outbox_events_event_id"
            )
        ),
        "on_conflict_probe_failed": _mutate(
            lambda r: r["p3d_schema_audit"].update(
                {
                    "payment_outbox_events_on_conflict_idempotency_key_probe": "FAIL (InvalidColumnReference: 42P10)",
                    "payment_outbox_events_on_conflict_probe_passed": False,
                }
            )
        ),
        "provenance_missing_entirely": _mutate(lambda r: r.pop("provenance")),
        "provenance_head_sha_missing": _mutate(lambda r: r["provenance"].update({"source_head_sha": None})),
        "provenance_manifest_hash_missing": _mutate(
            lambda r: r["provenance"]["sha256"].pop("migrations/reconciliation/shared_db_migration_manifest.json")
        ),
        "provenance_inbox_mig_hash_missing": _mutate(
            lambda r: r["provenance"]["sha256"].pop(
                "inbox:supabase/migrations/20261123_orders_idempotency_and_projection.sql"
            )
        ),
    }

    for case_name, bad_report in failing_cases.items():
        passed, reasons = mod.evaluate_replay_gate(bad_report)
        assert passed is False, f"[{case_name}] evaluate_replay_gate MUST fail closed, but passed!"
        assert len(reasons) >= 1, f"[{case_name}] Expected at least 1 failure reason"

        # Verify main() returns non-zero (1) when replay_all returns this failing report
        orig_replay_all = mod.replay_all
        try:
            mod.replay_all = lambda dsn, inbox_dir, source_head_sha=None, _r=copy.deepcopy(bad_report): _r
            exit_code = mod.main(["--dsn", "postgresql://postgres:pw@127.0.0.1:15432/test_db"])
            assert exit_code != 0, f"[{case_name}] CLI main() MUST exit non-zero, got {exit_code}"
        finally:
            mod.replay_all = orig_replay_all

    # End-to-end subprocess non-zero exit verification on representative failing report
    bad_file = tmp_path / "failing_report.json"
    bad_file.write_text(json.dumps(failing_cases["on_conflict_probe_failed"]), encoding="utf-8")
    proc_fail = subprocess.run(
        [sys.executable, str(runner_path), "--verify-report", str(bad_file)],
        capture_output=True,
        text=True,
    )
    assert proc_fail.returncode == 1, f"Expected exit 1 for failing report, got {proc_fail.returncode}"
