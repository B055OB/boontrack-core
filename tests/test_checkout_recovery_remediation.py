"""tests/test_checkout_recovery_remediation.py

BT-CORE-CHECKOUT-RECOVERY-001 Comprehensive Integration & Security Test Suite.
Runs strictly against the isolated disposable PostgreSQL test container.

Covers all 10 mandatory CTO recovery proofs:
1. Failed payment_events (and financial_ledger) insert rolls back complete settlement.
2. Failed settlement never returns PAID and leaves zero RAM/entitlement mutation.
3. Successful settlement commits orders, payment_events, checkout_sessions, financial_ledger consistently.
4. Duplicate callbacks cannot double-settle (same or new event_id, even after cache reset).
5. Invoice polling survives process restart.
6. Invoice polling works across separate HTTP workers (FastAPI & aiohttp).
7. Expired and revoked sessions cannot be polled or settled.
8. Cross-tenant invoice access is denied.
9. Concurrent unique-code allocation cannot produce conflicting active codes.
10. Keyring invalid configurations fail at startup with PaymentConfigurationError + rotation matrix.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
import socket
import subprocess
import sys
import textwrap
import time
import uuid

from aiohttp import web
from aiohttp.test_utils import TestClient as AioTestClient, TestServer as AioTestServer
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.core.database import get_db_connection
from app.core.security.payment_auth_guard import (
    CHECKOUT_SECURITY_HEADERS,
    CheckoutSessionTokenManager,
    ENV_APP_MASTER_KEY,
    ENV_BOONTRACK_INTERNAL_HMAC_SECRET,
    ENV_CHECKOUT_SESSION_KEYRING,
    ENV_INTERNAL_HMAC_KEYRING,
    ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
)
import app.routes.academy_routes as academy_routes
from app.routes.academy_routes import academy_router, register_academy_routes
import app.services.academy_service as academy_service
from app.services.academy_service import (
    _ACADEMY_INVOICES,
    _PROCESSED_EVENTS,
    _SETTLED_ORDERS,
    AcademyEntitlementManager,
    TenantContextViolation,
    academy_bot,
    generate_academy_qris_invoice,
    get_academy_invoice,
    get_academy_invoice_scoped,
    reset_academy_test_state,
    revoke_academy_checkout_session,
    settle_academy_invoice,
)
from app.services.payment.base import PaymentAuthorizationError, PaymentConfigurationError

TENANT_ALPHA_UUID = "00000000-0000-0000-0000-00000000000a"
TENANT_ALPHA_SLUG = "tenant_alpha"
TENANT_BETA_UUID = "00000000-0000-0000-0000-00000000000b"
TENANT_BETA_SLUG = "tenant_beta"


@pytest.fixture(autouse=True)
def _clean_academy_memory():
    reset_academy_test_state()
    yield
    reset_academy_test_state()


def _fetch_order_db_snapshot(order_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, tenant_id, tenant_slug, status, payment_status, order_status, gross_amount, paid_at "
            "FROM public.orders WHERE id = %s;",
            (order_id,),
        )
        ord_row = cur.fetchone()
        cur.execute(
            "SELECT order_id, tenant_id, canonical_tenant_id, tenant_slug, base_amount, unique_code, "
            "total_amount, session_state, revoked, expires_at, settled_at "
            "FROM public.checkout_sessions WHERE order_id = %s;",
            (order_id,),
        )
        cs_row = cur.fetchone()
        cur.execute(
            "SELECT provider, event_id, provider_event_id, order_id, tenant_id, status, amount "
            "FROM public.payment_events WHERE order_id = %s;",
            (order_id,),
        )
        evt_rows = cur.fetchall()
        cur.execute(
            "SELECT order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount, "
            "transaction_type, status, transaction_status, reconciliation_status "
            "FROM public.financial_ledger WHERE order_id = %s;",
            (order_id,),
        )
        ledger_rows = cur.fetchall()
        return {
            "order": ord_row,
            "checkout_session": cs_row,
            "payment_events": evt_rows,
            "financial_ledger": ledger_rows,
        }
    finally:
        cur.close()
        conn.close()


def _install_order_scoped_failure_trigger(table_name: str, order_id: str, trigger_suffix: str) -> str:
    """Installs a temporary BEFORE INSERT trigger blocking only one synthetic test order_id."""
    fn_name = f"public.fn_fail_{trigger_suffix}"
    trg_name = f"trg_fail_{trigger_suffix}"
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            CREATE OR REPLACE FUNCTION {fn_name}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.order_id = '{order_id}' THEN
                    RAISE EXCEPTION 'Simulated failure on {table_name} for order {order_id}';
                END IF;
                RETURN NEW;
            END;
            $$;
            DROP TRIGGER IF EXISTS {trg_name} ON public.{table_name};
            CREATE TRIGGER {trg_name}
            BEFORE INSERT ON public.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION {fn_name}();
            """
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return trg_name


def _drop_trigger_and_function(table_name: str, trigger_suffix: str) -> None:
    fn_name = f"public.fn_fail_{trigger_suffix}"
    trg_name = f"trg_fail_{trigger_suffix}"
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"DROP TRIGGER IF EXISTS {trg_name} ON public.{table_name};")
        cur.execute(f"DROP FUNCTION IF EXISTS {fn_name}();")
        conn.commit()
    finally:
        cur.close()
        conn.close()


# =============================================================================
# PROOFS 1, 2, 3, 4: ATOMIC SETTLEMENT, ROLLBACK & IDEMPOTENCY
# =============================================================================


@pytest.mark.asyncio
async def test_proof1_and_2_failed_payment_events_insert_rolls_back_complete_settlement():
    """Proofs 1 & 2: Failed payment_events insert rolls back settlement, never returns PAID,
    never mutates RAM caches, and never grants entitlements.
    """
    inv = generate_academy_qris_invoice(
        customer_name="Rollback User",
        customer_email="rollback.pe@tenant-alpha.test",
        customer_phone="628111000111",
        tenant_id=TENANT_ALPHA_SLUG,
        use_unique_code=True,
    )
    order_id = inv["order_id"]
    event_id = f"evt_fail_pe_{uuid.uuid4().hex[:8]}"
    suffix = f"pe_{uuid.uuid4().hex[:8]}"

    _install_order_scoped_failure_trigger("payment_events", order_id, suffix)
    try:
        res = settle_academy_invoice(
            order_id=order_id,
            event_id=event_id,
            provider="XENDIT",
            amount=inv["total_amount"],
            tenant_id=TENANT_ALPHA_SLUG,
        )
        assert res["status"] == "FAILED_DB_PERSISTENCE"
        assert res["status"] != "PAID"
        assert res["idempotency_hit"] is False

        # RAM state must remain untouched
        assert order_id not in _SETTLED_ORDERS
        assert event_id not in _PROCESSED_EVENTS
        assert _ACADEMY_INVOICES[order_id]["status"] == "PENDING"

        # DB must show zero settlement mutations across all tables
        snap = _fetch_order_db_snapshot(order_id)
        assert snap["order"] is not None
        assert snap["order"][3] == "PENDING"  # orders.status
        assert snap["order"][4] == "PENDING"  # orders.payment_status
        assert snap["order"][7] is None       # orders.paid_at
        assert snap["checkout_session"][7] == "ACTIVE"  # session_state
        assert snap["checkout_session"][10] is None     # settled_at
        assert len(snap["payment_events"]) == 0
        assert len(snap["financial_ledger"]) == 0

        # Webhook bot orchestration must fail closed with 0 entitlements
        bot_res = await academy_bot.handle_webhook_paid(
            order_id=order_id,
            event_id=f"evt_bot_{uuid.uuid4().hex[:8]}",
            provider="XENDIT",
            amount=inv["total_amount"],
            tenant_id=TENANT_ALPHA_SLUG,
            raw_payload={"customer_email": "rollback.pe@tenant-alpha.test"},
        )
        assert bot_res["status"] == "FAILED_DB_PERSISTENCE"
        assert AcademyEntitlementManager.get_entitlements_count(order_id) == 0
    finally:
        _drop_trigger_and_function("payment_events", suffix)


def test_proof1b_failed_financial_ledger_rolls_back_prior_payment_events_and_orders():
    """Proof 1b: If financial_ledger fails AFTER payment_events & orders UPDATE execute inside
    the transaction, payment_events, orders, and checkout_sessions all roll back cleanly.
    """
    inv = generate_academy_qris_invoice(
        customer_name="Ledger Rollback",
        customer_email="rollback.fl@tenant-alpha.test",
        customer_phone="628111000222",
        tenant_id=TENANT_ALPHA_SLUG,
        use_unique_code=True,
    )
    order_id = inv["order_id"]
    event_id = f"evt_fail_fl_{uuid.uuid4().hex[:8]}"
    suffix = f"fl_{uuid.uuid4().hex[:8]}"

    _install_order_scoped_failure_trigger("financial_ledger", order_id, suffix)
    try:
        res = settle_academy_invoice(
            order_id=order_id,
            event_id=event_id,
            provider="XENDIT",
            amount=inv["total_amount"],
            tenant_id=TENANT_ALPHA_SLUG,
        )
        assert res["status"] == "FAILED_DB_PERSISTENCE"
        assert order_id not in _SETTLED_ORDERS
        assert event_id not in _PROCESSED_EVENTS

        snap = _fetch_order_db_snapshot(order_id)
        assert snap["order"][3] == "PENDING"
        assert snap["checkout_session"][7] == "ACTIVE"
        assert len(snap["payment_events"]) == 0, "payment_events insert must roll back with financial_ledger"
        assert len(snap["financial_ledger"]) == 0
    finally:
        _drop_trigger_and_function("financial_ledger", suffix)


def test_proof3_successful_settlement_commits_all_tables_with_canonical_tenant():
    """Proof 3: Successful settlement atomically commits orders, checkout_sessions,
    payment_events (with canonical tenant_id), and financial_ledger (with valid nullable fee/net).
    """
    inv = generate_academy_qris_invoice(
        customer_name="Success Buyer",
        customer_email="success@tenant-alpha.test",
        customer_phone="628111000333",
        tenant_id=TENANT_ALPHA_SLUG,
        use_unique_code=True,
    )
    order_id = inv["order_id"]
    event_id = f"evt_ok_{uuid.uuid4().hex[:8]}"

    res = settle_academy_invoice(
        order_id=order_id,
        event_id=event_id,
        provider="XENDIT",
        amount=inv["total_amount"],
        tenant_id=TENANT_ALPHA_SLUG,
        raw_payload={"provider_event_id": f"prov_{event_id}"},
    )
    assert res["status"] == "PAID"
    assert res["tenant_id"] == TENANT_ALPHA_UUID
    assert res["idempotency_hit"] is False

    snap = _fetch_order_db_snapshot(order_id)
    assert snap["order"][1] == TENANT_ALPHA_UUID
    assert snap["order"][2] == TENANT_ALPHA_SLUG
    assert snap["order"][3] == "PAID"
    assert snap["order"][4] == "PAID"
    assert snap["order"][5] == "PAID"
    assert snap["order"][7] is not None

    assert snap["checkout_session"][1] == TENANT_ALPHA_UUID
    assert snap["checkout_session"][2] == TENANT_ALPHA_UUID
    assert snap["checkout_session"][7] == "SETTLED"
    assert snap["checkout_session"][10] is not None

    assert len(snap["payment_events"]) == 1
    pe = snap["payment_events"][0]
    assert pe[0] == "XENDIT"
    assert pe[1] == event_id
    assert pe[4] == TENANT_ALPHA_UUID  # canonical tenant_id NOT NULL supplied
    assert pe[5] == "PROCESSED"

    assert len(snap["financial_ledger"]) == 1
    fl = snap["financial_ledger"][0]
    assert fl[1] == TENANT_ALPHA_UUID
    assert fl[5] is None  # fee_amount NULL for PENDING_RECONCILIATION
    assert fl[6] is None  # net_amount NULL for PENDING_RECONCILIATION
    assert fl[7] == "PAYMENT_CREDIT"
    assert fl[8] == "SETTLED"
    assert fl[10] == "PENDING_RECONCILIATION"


def test_proof4_duplicate_callbacks_cannot_double_settle():
    """Proof 4: Duplicate event_id or second event_id for the same order_id cannot double-settle,
    even across empty RAM state (restart/cross-worker).
    """
    inv = generate_academy_qris_invoice(
        customer_name="Idemp Buyer",
        customer_email="idemp@tenant-alpha.test",
        customer_phone="628111000444",
        tenant_id=TENANT_ALPHA_SLUG,
        use_unique_code=True,
    )
    order_id = inv["order_id"]
    event_1 = f"evt_first_{uuid.uuid4().hex[:8]}"
    event_2 = f"evt_second_{uuid.uuid4().hex[:8]}"

    r1 = settle_academy_invoice(
        order_id=order_id,
        event_id=event_1,
        provider="XENDIT",
        amount=inv["total_amount"],
        tenant_id=TENANT_ALPHA_SLUG,
    )
    assert r1["status"] == "PAID"

    # Same process duplicate callback
    r2 = settle_academy_invoice(
        order_id=order_id,
        event_id=event_1,
        provider="XENDIT",
        amount=inv["total_amount"],
        tenant_id=TENANT_ALPHA_SLUG,
    )
    assert r2["status"] == "ALREADY_SETTLED"
    assert r2["idempotency_hit"] is True

    # Simulate process restart / second worker with empty RAM caches
    reset_academy_test_state()

    r3 = settle_academy_invoice(
        order_id=order_id,
        event_id=event_1,
        provider="XENDIT",
        amount=inv["total_amount"],
        tenant_id=TENANT_ALPHA_SLUG,
    )
    assert r3["status"] == "ALREADY_SETTLED"
    assert r3["idempotency_hit"] is True

    # Distinct event_id for already-settled order
    r4 = settle_academy_invoice(
        order_id=order_id,
        event_id=event_2,
        provider="XENDIT",
        amount=inv["total_amount"],
        tenant_id=TENANT_ALPHA_SLUG,
    )
    assert r4["status"] == "ALREADY_SETTLED"
    assert r4["idempotency_hit"] is True

    snap = _fetch_order_db_snapshot(order_id)
    assert len(snap["payment_events"]) == 1
    assert len(snap["financial_ledger"]) == 1


# =============================================================================
# PROOFS 5 & 6: CROSS-PROCESS RESTART & SEPARATE HTTP WORKER POLLING
# =============================================================================


def _find_free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.asyncio
async def test_proof5_and_6_polling_survives_restart_and_works_across_separate_workers():
    """Proofs 5 & 6: Invoice created by Worker 1 (FastAPI) is successfully polled by an
    independent OS Worker 2 (both FastAPI and aiohttp) with empty RAM, simulating process restart
    and multi-worker deployment.
    """
    shared_keyring = json.dumps(
        {
            "cs_worker_k1": {
                "secret": secrets.token_hex(32),
                "status": "ACTIVE",
            }
        }
    )
    worker_env = dict(os.environ)
    worker_env[ENV_CHECKOUT_SESSION_KEYRING] = shared_keyring

    # Worker 1 subprocess: creates invoice via FastAPI router and exits completely
    create_script = (
        "import json; from fastapi import FastAPI; from fastapi.testclient import TestClient; "
        "from app.routes.academy_routes import academy_router; "
        "app = FastAPI(); app.include_router(academy_router); "
        "c = TestClient(app); "
        "r = c.post('/api/v1/academy/invoice', json={"
        "'customer_name': 'CrossWorker Alice', "
        "'customer_email': 'alice.worker@example.com', "
        "'customer_phone': '6281299988877', "
        "'tenant_id': 'tenant_alpha', "
        "'use_unique_code': True}); "
        "assert r.status_code == 200, r.text; "
        "print(json.dumps(r.json()))"
    )
    proc_w1 = subprocess.run(
        [sys.executable, "-c", create_script],
        env=worker_env,
        capture_output=True,
        text=True,
        check=True,
    )
    created_payload = json.loads(proc_w1.stdout.strip().splitlines()[-1])
    order_id = created_payload["invoice"]["order_id"]
    token = created_payload["checkout_session_token"]
    assert token

    # Worker 2 subprocess (fresh OS process, zero RAM state): polls via FastAPI AND aiohttp
    poll_script = textwrap.dedent(
        """\
        import asyncio, json, sys
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from aiohttp import web
        from aiohttp.test_utils import TestClient as AioClient, TestServer as AioServer
        from app.routes.academy_routes import academy_router, register_academy_routes
        from app.services.academy_service import _ACADEMY_INVOICES

        assert len(_ACADEMY_INVOICES) == 0
        oid, tok = sys.argv[1], sys.argv[2]

        fapp = FastAPI()
        fapp.include_router(academy_router)
        fc = TestClient(fapp)
        r_fa = fc.get(f"/api/v1/academy/invoice/{oid}", headers={"X-Checkout-Session-Token": tok})
        assert r_fa.status_code == 200, r_fa.text
        r_fa_qs = fc.get(
            f"/api/v1/academy/invoice/{oid}?token={tok}",
            headers={"X-Checkout-Session-Token": tok},
        )
        assert r_fa_qs.status_code == 404

        async def run_aio():
            aapp = web.Application()
            register_academy_routes(aapp)
            async with AioClient(AioServer(aapp)) as ac:
                r_aio = await ac.get(
                    f"/api/v1/academy/invoice/{oid}",
                    cookies={"__Host-bt_checkout_st": tok},
                )
                assert r_aio.status == 200, await r_aio.text()
                data = await r_aio.json()
                assert r_aio.headers.get("Referrer-Policy") == "no-referrer"
                return data

        aio_data = asyncio.run(run_aio())
        print(json.dumps({"fastapi": r_fa.json(), "aiohttp": aio_data}))
        """
    )
    proc_w2 = subprocess.run(
        [sys.executable, "-c", poll_script, order_id, token],
        env=worker_env,
        capture_output=True,
        text=True,
        check=True,
    )
    polled = json.loads(proc_w2.stdout.strip().splitlines()[-1])
    assert polled["fastapi"]["invoice"]["order_id"] == order_id
    assert polled["aiohttp"]["invoice"]["order_id"] == order_id
    assert polled["fastapi"]["invoice"]["status"] == "PENDING"
    assert "***" in polled["fastapi"]["invoice"]["customer_email"]

    # Settle via PostgreSQL and verify Worker 3 observes PAID after Worker 1/2 exited
    snap = _fetch_order_db_snapshot(order_id)
    settle_res = settle_academy_invoice(
        order_id=order_id,
        event_id=f"evt_w3_{uuid.uuid4().hex[:8]}",
        provider="XENDIT",
        amount=int(snap["checkout_session"][6]),
        tenant_id=TENANT_ALPHA_SLUG,
    )
    assert settle_res["status"] == "PAID"

    poll_paid_script = (
        "import json, sys; from fastapi import FastAPI; from fastapi.testclient import TestClient; "
        "from app.routes.academy_routes import academy_router; "
        "oid, tok = sys.argv[1], sys.argv[2]; "
        "app = FastAPI(); app.include_router(academy_router); "
        "r = TestClient(app).get(f'/api/v1/academy/invoice/{oid}', headers={'X-Checkout-Session-Token': tok}); "
        "assert r.status_code == 200, r.text; print(json.dumps(r.json()))"
    )
    proc_w3 = subprocess.run(
        [sys.executable, "-c", poll_paid_script, order_id, token],
        env=worker_env,
        capture_output=True,
        text=True,
        check=True,
    )
    paid_payload = json.loads(proc_w3.stdout.strip().splitlines()[-1])
    assert paid_payload["invoice"]["status"] == "PAID"


# =============================================================================
# PROOF 7: EXPIRED & REVOKED SESSIONS REJECTED
# =============================================================================


@pytest.mark.asyncio
async def test_proof7_expired_and_revoked_sessions_cannot_be_polled_or_settled():
    """Proof 7: Expired and revoked durable sessions return uniform 404 on poll
    (FastAPI & aiohttp) and fail closed on settlement.
    """
    fapp = FastAPI()
    fapp.include_router(academy_router)
    fclient = TestClient(fapp)

    aapp = web.Application()
    register_academy_routes(aapp)

    # 1. Create two durable invoices via FastAPI
    resp_exp = fclient.post(
        "/api/v1/academy/invoice",
        json={
            "customer_name": "Expired Buyer",
            "customer_email": "expired@tenant-alpha.test",
            "customer_phone": "628111000555",
            "tenant_id": TENANT_ALPHA_SLUG,
        },
    )
    assert resp_exp.status_code == 200
    order_exp = resp_exp.json()["invoice"]["order_id"]
    token_exp = resp_exp.json()["checkout_session_token"]
    amt_exp = resp_exp.json()["invoice"]["total_amount"]

    resp_rev = fclient.post(
        "/api/v1/academy/invoice",
        json={
            "customer_name": "Revoked Buyer",
            "customer_email": "revoked@tenant-alpha.test",
            "customer_phone": "628111000666",
            "tenant_id": TENANT_ALPHA_SLUG,
        },
    )
    assert resp_rev.status_code == 200
    order_rev = resp_rev.json()["invoice"]["order_id"]
    token_rev = resp_rev.json()["checkout_session_token"]
    amt_rev = resp_rev.json()["invoice"]["total_amount"]

    # Sanity check: both work before expiry/revocation
    assert fclient.get(f"/api/v1/academy/invoice/{order_exp}", headers={"X-Checkout-Session-Token": token_exp}).status_code == 200
    assert fclient.get(f"/api/v1/academy/invoice/{order_rev}", headers={"X-Checkout-Session-Token": token_rev}).status_code == 200

    # Expire order_exp directly in PostgreSQL
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE public.checkout_sessions SET expires_at = %s WHERE order_id = %s;",
            (datetime.now(timezone.utc) - timedelta(minutes=2), order_exp),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    # Revoke order_rev via authoritative service function
    assert revoke_academy_checkout_session(order_rev, reason="CUSTOMER_CANCELLED") is True

    # Clear all RAM caches so checks rely strictly on PostgreSQL
    reset_academy_test_state()

    # Poll via FastAPI -> uniform 404 + security headers
    r_exp_fa = fclient.get(f"/api/v1/academy/invoice/{order_exp}", headers={"X-Checkout-Session-Token": token_exp})
    r_rev_fa = fclient.get(f"/api/v1/academy/invoice/{order_rev}", headers={"X-Checkout-Session-Token": token_rev})
    for r in (r_exp_fa, r_rev_fa):
        assert r.status_code == 404
        assert r.json() == {"detail": "Invoice not found"}
        for hk, hv in CHECKOUT_SECURITY_HEADERS.items():
            assert r.headers.get(hk) == hv

    # Poll via aiohttp -> uniform 404
    async with AioTestClient(AioTestServer(aapp)) as aclient:
        r_exp_aio = await aclient.get(
            f"/api/v1/academy/invoice/{order_exp}",
            headers={"X-Checkout-Session-Token": token_exp},
        )
        r_rev_aio = await aclient.get(
            f"/api/v1/academy/invoice/{order_rev}",
            headers={"X-Checkout-Session-Token": token_rev},
        )
        assert r_exp_aio.status == 404
        assert await r_exp_aio.json() == {"detail": "Invoice not found"}
        assert r_rev_aio.status == 404
        assert await r_rev_aio.json() == {"detail": "Invoice not found"}

    # Settlement on expired -> MANUAL_RECONCILIATION (zero ledger/payment_events)
    s_exp = settle_academy_invoice(
        order_id=order_exp,
        event_id=f"evt_exp_{uuid.uuid4().hex[:8]}",
        provider="XENDIT",
        amount=amt_exp,
        tenant_id=TENANT_ALPHA_SLUG,
    )
    assert s_exp["status"] == "MANUAL_RECONCILIATION"
    assert len(_fetch_order_db_snapshot(order_exp)["financial_ledger"]) == 0

    # Settlement on revoked -> REJECTED_SESSION_REVOKED (zero ledger/payment_events)
    s_rev = settle_academy_invoice(
        order_id=order_rev,
        event_id=f"evt_rev_{uuid.uuid4().hex[:8]}",
        provider="XENDIT",
        amount=amt_rev,
        tenant_id=TENANT_ALPHA_SLUG,
    )
    assert s_rev["status"] == "REJECTED_SESSION_REVOKED"
    assert len(_fetch_order_db_snapshot(order_rev)["payment_events"]) == 0
    assert len(_fetch_order_db_snapshot(order_rev)["financial_ledger"]) == 0


# =============================================================================
# PROOF 8: CROSS-TENANT INVOICE ACCESS DENIED
# =============================================================================


def test_proof8_cross_tenant_invoice_access_and_settlement_denied():
    """Proof 8: Cross-tenant polling, scoped service lookup, forged tenant token,
    and cross-tenant webhook settlement are strictly denied.
    """
    fapp = FastAPI()
    fapp.include_router(academy_router)
    fclient = TestClient(fapp)

    r_alpha = fclient.post(
        "/api/v1/academy/invoice",
        json={
            "customer_name": "Alpha Owner",
            "customer_email": "alpha@tenant-alpha.test",
            "customer_phone": "628111000777",
            "tenant_id": TENANT_ALPHA_SLUG,
        },
    )
    r_beta = fclient.post(
        "/api/v1/academy/invoice",
        json={
            "customer_name": "Beta User",
            "customer_email": "beta@tenant-beta.test",
            "customer_phone": "628111000888",
            "tenant_id": TENANT_BETA_SLUG,
        },
    )
    assert r_alpha.status_code == 200
    assert r_beta.status_code == 200

    order_alpha = r_alpha.json()["invoice"]["order_id"]
    token_alpha = r_alpha.json()["checkout_session_token"]
    token_beta = r_beta.json()["checkout_session_token"]
    amt_alpha = r_alpha.json()["invoice"]["total_amount"]

    # Forge token bound to order_alpha's ID but TENANT_BETA_UUID using active manager
    forged_beta_token, _ = academy_routes._CHECKOUT_TOKEN_MANAGER.issue_token(
        order_id=order_alpha,
        canonical_tenant_id=TENANT_BETA_UUID,
    )

    reset_academy_test_state()

    # Cross-tenant HTTP polling must return uniform 404
    assert fclient.get(f"/api/v1/academy/invoice/{order_alpha}", headers={"X-Checkout-Session-Token": token_beta}).status_code == 404
    assert fclient.get(f"/api/v1/academy/invoice/{order_alpha}", headers={"X-Checkout-Session-Token": forged_beta_token}).status_code == 404
    assert fclient.get(f"/api/v1/academy/invoice/{order_alpha}", headers={"X-Checkout-Session-Token": token_alpha}).status_code == 200

    # Durable scoped reader enforces strict cross-tenant isolation
    with pytest.raises(TenantContextViolation):
        get_academy_invoice_scoped(order_alpha, requesting_tenant_id=TENANT_BETA_UUID)
    with pytest.raises(TenantContextViolation):
        get_academy_invoice_scoped(order_alpha, requesting_tenant_id=TENANT_BETA_SLUG)

    # Same tenant succeeds with canonical UUID or slug
    assert get_academy_invoice_scoped(order_alpha, requesting_tenant_id=TENANT_ALPHA_UUID)["order_id"] == order_alpha
    assert get_academy_invoice_scoped(order_alpha, requesting_tenant_id=TENANT_ALPHA_SLUG)["order_id"] == order_alpha

    # Cross-tenant webhook settlement rejected without mutating DB
    s_cross = settle_academy_invoice(
        order_id=order_alpha,
        event_id=f"evt_cross_{uuid.uuid4().hex[:8]}",
        provider="XENDIT",
        amount=amt_alpha,
        tenant_id=TENANT_BETA_SLUG,
    )
    assert s_cross["status"] == "REJECTED_TENANT_MISMATCH"
    assert _fetch_order_db_snapshot(order_alpha)["order"][3] == "PENDING"


# =============================================================================
# PROOF 9: CONCURRENT UNIQUE-CODE ALLOCATION & DB INDEX ENFORCEMENT
# =============================================================================


def test_proof9_concurrent_unique_code_allocation_prevents_collisions(monkeypatch):
    """Proof 9: Concurrent & savepoint-retried allocations produce unique active
    (tenant_id, base_amount, unique_code) entries enforced by PostgreSQL partial unique index.
    """
    unique_slug = f"tenant_conc_{uuid.uuid4().hex[:8]}"

    # 9a. Deterministic DB unique constraint collision & SAVEPOINT retry
    picks_1 = iter([777])
    monkeypatch.setattr(academy_service, "generate_unique_code", lambda min_val=100, max_val=999: next(picks_1))
    inv_1 = generate_academy_qris_invoice(
        customer_name="Conc 1",
        customer_email="conc1@test.local",
        customer_phone="628111000901",
        tenant_id=unique_slug,
        use_unique_code=True,
    )
    assert inv_1["unique_code"] == 777

    # Clear RAM so DB unique_code state + savepoint retry are sole protections
    reset_academy_test_state()

    picks_2 = iter([777, 777, 778])
    monkeypatch.setattr(academy_service, "generate_unique_code", lambda min_val=100, max_val=999: next(picks_2))
    inv_2 = generate_academy_qris_invoice(
        customer_name="Conc 2",
        customer_email="conc2@test.local",
        customer_phone="628111000902",
        tenant_id=unique_slug,
        use_unique_code=True,
    )
    assert inv_2["unique_code"] == 778
    assert inv_2["total_amount"] != inv_1["total_amount"]

    # 9b. Real parallel threads competing in PostgreSQL for same tenant_id + base_amount
    monkeypatch.undo()
    parallel_slug = f"tenant_par_{uuid.uuid4().hex[:8]}"

    def _create_one(idx: int) -> int:
        inv = generate_academy_qris_invoice(
            customer_name=f"Parallel Buyer {idx}",
            customer_email=f"par{idx}@test.local",
            customer_phone=f"628112200{idx:03d}",
            tenant_id=parallel_slug,
            use_unique_code=True,
        )
        return int(inv["unique_code"])

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(_create_one, range(12)))

    assert len(codes) == 12
    assert len(set(codes)) == 12, f"Duplicate active unique_codes allocated concurrently: {codes}"

    # Verify DB partial unique index explicitly rejects colliding raw INSERT
    conn = get_db_connection()
    cur = conn.cursor()
    colliding_code = codes[0]
    fake_oid = f"BTA-COLLIDE-{uuid.uuid4().hex[:6]}"
    try:
        cur.execute(
            """
            INSERT INTO public.orders (
                id, tenant_id, tenant_slug, sku_id, product_id, product_title,
                gross_amount, amount, customer_name, customer_phone, customer_email, status
            ) VALUES (%s, %s, %s, 'OB-BATCH1-249K', 'OB-BATCH1-249K', 'Test', %s, %s, 'C', '6281', 'c@t.id', 'PENDING');
            """,
            (fake_oid, parallel_slug, parallel_slug, 249000 + colliding_code, 249000 + colliding_code),
        )
        with pytest.raises(Exception) as uv_exc:
            cur.execute(
                """
                INSERT INTO public.checkout_sessions (
                    order_id, tenant_id, canonical_tenant_id, tenant_slug, sku_id,
                    base_amount, unique_code, total_amount, qr_string, session_state,
                    jti, cs_key_id, iat_epoch, exp_epoch, revoked, expires_at
                ) VALUES (%s, %s, %s, %s, 'OB-BATCH1-249K', 249000, %s, %s, 'qr', 'ACTIVE', %s, 'k1', 1000, 1900, FALSE, NOW() + interval '15 minutes');
                """,
                (fake_oid, parallel_slug, parallel_slug, parallel_slug, colliding_code, 249000 + colliding_code, uuid.uuid4().hex),
            )
        assert getattr(uv_exc.value, "pgcode", None) == "23505"
        conn.rollback()
    finally:
        cur.close()
        conn.close()


# =============================================================================
# PROOF 10: KEYRING HARDENING, KEY SEPARATION & ROTATION MATRIX
# =============================================================================


def test_proof10_keyring_validation_rejects_invalid_configurations_and_supports_rotation():
    """Proof 10: Keyring validation rejects malformed metadata, whitespace/invalid key IDs,
    sibling/master/fallback secret reuse, and zero ACTIVE keys in production;
    also validates ACTIVE -> VERIFY_ONLY -> REVOKED rotation lifecycle.
    """
    valid_s1 = secrets.token_hex(32)
    valid_s2 = secrets.token_hex(32)
    master_s = secrets.token_hex(32)
    internal_hmac_s = secrets.token_hex(32)
    internal_ring_s = secrets.token_hex(32)
    provenance_s = secrets.token_hex(32)

    prod_base_env = {
        "ENV": "production",
        ENV_APP_MASTER_KEY: master_s,
        ENV_BOONTRACK_INTERNAL_HMAC_SECRET: internal_hmac_s,
        ENV_INTERNAL_HMAC_KEYRING: json.dumps({"int_k1": {"secret": internal_ring_s, "status": "ACTIVE"}}),
        ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING: json.dumps({"prov_k1": {"private_key_hex": provenance_s, "status": "ACTIVE"}}),
    }

    # 1. Missing keyring in production
    with pytest.raises(PaymentConfigurationError):
        CheckoutSessionTokenManager(environ=dict(prod_base_env))

    # 2. Non-mapping metadata
    for bad_meta in ("not-a-dict", ["list"], 12345, None):
        env_bad = {**prod_base_env, ENV_CHECKOUT_SESSION_KEYRING: json.dumps({"cs_k1": bad_meta})}
        with pytest.raises(PaymentConfigurationError):
            CheckoutSessionTokenManager(environ=env_bad)

    # 3. Invalid key IDs (whitespace, forbidden chars, length > 64, non-str in explicit map)
    for bad_kid in (" cs_k1", "cs_k1 ", "cs k1", "cs\nk1", "cs.k1", "cs:k1", "", "a" * 65):
        env_kid = {
            **prod_base_env,
            ENV_CHECKOUT_SESSION_KEYRING: json.dumps({bad_kid: {"secret": valid_s1, "status": "ACTIVE"}}),
        }
        with pytest.raises(PaymentConfigurationError):
            CheckoutSessionTokenManager(environ=env_kid)
    with pytest.raises(PaymentConfigurationError):
        CheckoutSessionTokenManager(keys={123: {"secret": valid_s1, "status": "ACTIVE"}}, environ=prod_base_env)

    # 4. Zero ACTIVE keys in production (VERIFY_ONLY or REVOKED only)
    for only_status in ("VERIFY_ONLY", "REVOKED"):
        env_zero_active = {
            **prod_base_env,
            ENV_CHECKOUT_SESSION_KEYRING: json.dumps({"cs_k1": {"secret": valid_s1, "status": only_status}}),
        }
        with pytest.raises(PaymentConfigurationError):
            CheckoutSessionTokenManager(environ=env_zero_active)

    # 5. Forbidden secret reuse: APP_MASTER_KEY, sibling secrets/keyrings, insecure fallback literals
    forbidden_candidates = (
        master_s,
        internal_hmac_s,
        internal_ring_s,
        provenance_s,
        "boontrack_master_security_secret_key_32bytes_len!",
        "boontrack_blind_index_salt_secure_2026",
        "too_short_secret",
    )
    for bad_secret in forbidden_candidates:
        env_reuse = {
            **prod_base_env,
            ENV_CHECKOUT_SESSION_KEYRING: json.dumps({"cs_k1": {"secret": bad_secret, "status": "ACTIVE"}}),
        }
        with pytest.raises(PaymentConfigurationError):
            CheckoutSessionTokenManager(environ=env_reuse)

    # 6. Full Rotation Lifecycle: ACTIVE -> VERIFY_ONLY -> REVOKED
    now_ts = int(time.time())
    mgr_stage1 = CheckoutSessionTokenManager(
        keys={"cs_k1": {"secret": valid_s1, "status": "ACTIVE"}},
        environ=prod_base_env,
    )
    token_k1, meta_k1 = mgr_stage1.issue_token(
        order_id="BTA-ROT-001",
        canonical_tenant_id=TENANT_ALPHA_UUID,
        now_epoch=now_ts,
    )
    inv_rec = {
        "order_id": "BTA-ROT-001",
        "status": "PENDING",
        "tenant_id": TENANT_ALPHA_UUID,
        "canonical_tenant_id": TENANT_ALPHA_UUID,
        "customer_name": "Rot",
        "customer_email": "rot@test.local",
        "customer_phone": "628111",
        "base_amount": 249000,
        "unique_code": 123,
        "total_amount": 249123,
        "currency": "IDR",
        "qr_string": "qr",
        "qr_image_url": "img",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "created_at": "2026-01-01T00:00:00+00:00",
        "checkout_session": meta_k1,
    }

    # Rotate: cs_k1 becomes VERIFY_ONLY, cs_k2 becomes ACTIVE
    mgr_stage2 = CheckoutSessionTokenManager(
        keys={
            "cs_k1": {"secret": valid_s1, "status": "VERIFY_ONLY"},
            "cs_k2": {"secret": valid_s2, "status": "ACTIVE"},
        },
        environ=prod_base_env,
    )
    verified = mgr_stage2.verify_request_and_authorize_invoice(
        requested_order_id="BTA-ROT-001",
        invoice_record=inv_rec,
        headers={"X-Checkout-Session-Token": token_k1},
        now_epoch=now_ts + 10,
    )
    assert verified["order_id"] == "BTA-ROT-001"
    token_k2, meta_k2 = mgr_stage2.issue_token(
        order_id="BTA-ROT-001",
        canonical_tenant_id=TENANT_ALPHA_UUID,
        now_epoch=now_ts,
    )
    assert meta_k2["cs_key_id"] == "cs_k2"

    # Revoke cs_k1: old token_k1 must fail closed while k2 works
    mgr_stage3 = CheckoutSessionTokenManager(
        keys={
            "cs_k1": {"secret": valid_s1, "status": "REVOKED"},
            "cs_k2": {"secret": valid_s2, "status": "ACTIVE"},
        },
        environ=prod_base_env,
    )
    with pytest.raises(PaymentAuthorizationError):
        mgr_stage3.verify_request_and_authorize_invoice(
            requested_order_id="BTA-ROT-001",
            invoice_record=inv_rec,
            headers={"X-Checkout-Session-Token": token_k1},
            now_epoch=now_ts + 20,
        )
    inv_rec_k2 = {**inv_rec, "checkout_session": meta_k2}
    verified_k2 = mgr_stage3.verify_request_and_authorize_invoice(
        requested_order_id="BTA-ROT-001",
        invoice_record=inv_rec_k2,
        headers={"X-Checkout-Session-Token": token_k2},
        now_epoch=now_ts + 20,
    )
    assert verified_k2["order_id"] == "BTA-ROT-001"


@pytest.mark.asyncio
async def test_fail_closed_public_invoice_creation_on_db_outage(monkeypatch):
    """Creating a public SKU invoice must fail closed with HTTP 500 and zero token/RAM leak if PG fails."""
    fapp = FastAPI()
    fapp.include_router(academy_router)
    fclient = TestClient(fapp)

    aapp = web.Application()
    register_academy_routes(aapp)

    def _broken_db():
        raise RuntimeError("Simulated PostgreSQL unavailable")

    monkeypatch.setattr("app.core.database.get_db_connection", _broken_db)

    r_fa = fclient.post(
        "/api/v1/academy/invoice",
        json={
            "customer_name": "Outage Buyer",
            "customer_email": "outage@tenant-alpha.test",
            "customer_phone": "628111000999",
            "tenant_id": TENANT_ALPHA_SLUG,
        },
    )
    assert r_fa.status_code == 500
    assert "checkout_session_token" not in r_fa.json()
    assert len(_ACADEMY_INVOICES) == 0

    async with AioTestClient(AioTestServer(aapp)) as aclient:
        r_aio = await aclient.post(
            "/api/v1/academy/invoice",
            json={
                "customer_name": "Outage Buyer",
                "customer_email": "outage@tenant-alpha.test",
                "customer_phone": "628111000999",
                "tenant_id": TENANT_ALPHA_SLUG,
            },
        )
        assert r_aio.status == 500
        body = await r_aio.json()
        assert "checkout_session_token" not in body
        assert len(_ACADEMY_INVOICES) == 0

