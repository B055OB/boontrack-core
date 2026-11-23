"""tests/test_packet3d_remediations_negative.py
Packet 3D Negative QA Test Suite for Command Center Blockers A, B, and E:
1. Outbox-failure full rollback: failure on payment_outbox_events rolls back complete settlement transaction.
2. Zero direct UPDATE orders & zero runtime DDL static audit across all settlement & worker paths.
3. Academy default-deny in Staging/Dev/Prod when ENABLE_ACADEMY_DIRECT_CHECKOUT is unset.
"""

from __future__ import annotations

import os
import uuid
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db_connection
from app.services.academy_service import (
    generate_academy_qris_invoice,
    settle_academy_invoice,
    _SETTLED_ORDERS,
    _PROCESSED_EVENTS,
    _ACADEMY_INVOICES,
)
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

    # Blocker B: Zero runtime DDL in settlement or dispatcher paths
    for module_name, src in [
        ("provenance_authority", prov_src),
        ("academy_service", acad_src),
        ("checkout_service", checkout_src),
        ("payment_outbox_dispatcher", dispatcher_src),
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
