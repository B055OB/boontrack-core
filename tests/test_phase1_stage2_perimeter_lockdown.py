"""tests/test_phase1_stage2_perimeter_lockdown.py
Phase 1 — Stage 2: High-Risk Perimeter Lockdown Verification Suite.

Covers all CTO Stage 2 acceptance criteria (FastAPI & aiohttp parity):
  - P0-A: Mutation Perimeter Lockdown (/mark-paid, /approve-and-deliver, PATCH /status, APP_MASTER_KEY ban,
          Canonical Tenant Ownership, Internal HMAC + Fail-Closed PostgreSQL Replay Store)
  - P0-B: Dummy Account Elimination ('1234567890', 'BCA', 'Merchant Store', fail-closed PaymentAdapterFactory,
          Native PG Xendit/Duitku preservation)
  - P0-C: Direct Tenant Rail Lockdown (MANUAL_TRANSFER / static QRIS / Tag 54 & CRC16 / reader webhook disabled)
  - P0-D: Checkout Session Security (ownership-bound token, expiry/revocation, anti-enumeration 404,
          PII masking, URL query token rejection, Referrer-Policy & Cache-Control headers)
  - P0-E: Growth Simulation & Subscription Isolation (production hard-block on /growth/simulate/order-paid,
          internal HMAC in non-prod, removal of automatic CHECKOUT_LITE upgrade from D2C fulfillment)
"""

import json
import time
from typing import Dict, Any, Optional, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient as AioTestClient, TestServer as AioTestServer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security.payment_auth_guard import (
    HDR_ACTOR,
    HDR_KEY_ID,
    HDR_NONCE,
    HDR_SIGNATURE,
    HDR_TENANT_ID,
    HDR_TIMESTAMP,
    compute_internal_payment_hmac_signature,
)
from app.api.endpoints import register_api_routes
from app.api.v1.reader import register_reader_routes
from app.api.v1.reader_router import router as reader_router
from app.routes.academy_routes import academy_router, register_academy_routes
from app.routes.checkout_router import checkout_api_router
from app.routes.d2c_order_routes import d2c_router, register_d2c_order_routes
from app.routes.growth_routes import router as growth_router, register_growth_routes
from app.routes.payment import payment_router, register_payment_routes
from app.routes.payment_webhook import register_payment_webhook_routes
from app.schemas.context import TenantRuntimeContext
from app.services.academy_service import _ACADEMY_INVOICES
from app.services.payment.base import PaymentConfigurationError, TransactionRequest
from app.services.payment.factory import PaymentAdapterFactory
from app.services.payment.gateway_duitku import DuitkuAdapter
from app.services.payment.gateway_xendit import XenditAdapter
from app.services.payment.manual_adapter import ManualTransferAdapter


# ============================================================================
# Test Fixtures & Mock Authoritative PostgreSQL Connection
# ============================================================================

TEST_HMAC_KEY_ID = "hk_stage2_active_01"
TEST_HMAC_SECRET = "s2_internal_hmac_secret_key_for_perimeter_lockdown_2026"
TEST_KEYRING_JSON = json.dumps({
    TEST_HMAC_KEY_ID: {
        "secret": TEST_HMAC_SECRET,
        "status": "ACTIVE",
        "bound_principal": "admin_ops_01",
    }
})

CANONICAL_TENANT_A = "11111111-2222-3333-4444-555555555555"
CANONICAL_TENANT_B = "99999999-8888-7777-6666-555555555555"


class FakePostgresCursor:
    """Simulates PostgreSQL cursor for CanonicalTenantResolver, ReplayStore, and orders table."""

    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self._last_result = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, query: str, params: Optional[tuple] = None):
        q_norm = " ".join(query.strip().split()).upper()
        self._last_result = None
        self.rowcount = 0

        if self.state.get("db_down"):
            raise RuntimeError("Simulated PostgreSQL connection failure")

        # 1. CanonicalTenantResolver AUTHORITATIVE_JOIN_SQL (INNER JOIN tenants t)
        if "FROM ORDERS O" in q_norm and "INNER JOIN TENANTS T" in q_norm:
            order_id = params[0]
            order = self.state["orders"].get(order_id)
            if not order:
                self._last_result = None
            else:
                self._last_result = (
                    order["id"],
                    order["tenant_id"],
                    order["tenant_slug"],
                    order["tenant_id"],
                    order["tenant_slug"],
                    order["gross_amount"],
                    "SKU-001",
                    order["status"],
                )
            return

        # 1b. CanonicalTenantResolver ORDER_DIAGNOSTIC_SQL
        if "FROM ORDERS O" in q_norm and "WHERE O.ID =" in q_norm:
            order_id = params[0]
            order = self.state["orders"].get(order_id)
            if not order:
                self._last_result = None
            else:
                self._last_result = (order["id"], order["tenant_id"], order["tenant_slug"])
            return

        # 2. PostgresAuthoritativeReplayStore INSERT INTO public.payment_hmac_replay_nonces
        if "PAYMENT_HMAC_REPLAY_NONCES" in q_norm and "INSERT INTO" in q_norm:
            key_id = params[0]
            nonce = params[1]
            pair = (key_id, nonce)
            if pair in self.state["nonces"]:
                self.rowcount = 0
                self._last_result = None
            else:
                self.state["nonces"].add(pair)
                self.rowcount = 1
                self._last_result = (key_id, nonce)
            return

        # 3. SELECT * FROM orders WHERE id = %s
        if q_norm.startswith("SELECT * FROM ORDERS WHERE ID ="):
            order_id = params[0]
            order = self.state["orders"].get(order_id)
            self._last_result = dict(order) if order else None
            return

        # 4. UPDATE orders SET status = %s
        if q_norm.startswith("UPDATE ORDERS SET STATUS ="):
            new_status, order_id = params[0], params[1]
            order = self.state["orders"].get(order_id)
            if order:
                order["status"] = new_status
                self.rowcount = 1
                self._last_result = dict(order)
            return

    def fetchone(self):
        return self._last_result

    def close(self):
        pass


class FakePostgresConnection:
    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def cursor(self, cursor_factory=None):
        return FakePostgresCursor(self.state)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def pg_state():
    return {
        "db_down": False,
        "nonces": set(),
        "orders": {
            "ORD-PENDING-001": {
                "id": "ORD-PENDING-001",
                "tenant_id": CANONICAL_TENANT_A,
                "tenant_slug": "store-alpha",
                "product_title": "Kelas Scale Ads",
                "gross_amount": 250000,
                "customer_name": "Budi Santoso",
                "customer_phone": "6281234567890",
                "customer_email": "budi@example.com",
                "fbclid": None,
                "status": "PENDING",
                "payment_status": "PENDING",
                "download_url": "https://boontrack.com/access/kelas-scale-ads",
                "updated_at": "2026-11-05T10:00:00Z",
            },
            "ORD-PAID-002": {
                "id": "ORD-PAID-002",
                "tenant_id": CANONICAL_TENANT_A,
                "tenant_slug": "store-alpha",
                "product_title": "Kelas Scale Ads",
                "gross_amount": 250000,
                "customer_name": "Siti Aminah",
                "customer_phone": "6289876543210",
                "customer_email": "siti@example.com",
                "fbclid": None,
                "status": "PAID",
                "payment_status": "PAID",
                "download_url": "https://boontrack.com/access/kelas-scale-ads",
                "updated_at": "2026-11-05T10:05:00Z",
            },
            "ORD-CANCELLED-003": {
                "id": "ORD-CANCELLED-003",
                "tenant_id": CANONICAL_TENANT_A,
                "tenant_slug": "store-alpha",
                "product_title": "Kelas Scale Ads",
                "gross_amount": 250000,
                "customer_name": "Doni Siregar",
                "customer_phone": "6281122334455",
                "customer_email": "doni@example.com",
                "fbclid": None,
                "status": "CANCELLED",
                "payment_status": "CANCELLED",
                "download_url": "https://boontrack.com/access/kelas-scale-ads",
                "updated_at": "2026-11-05T10:10:00Z",
            },
            "ORD-EXPIRED-004": {
                "id": "ORD-EXPIRED-004",
                "tenant_id": CANONICAL_TENANT_A,
                "tenant_slug": "store-alpha",
                "product_title": "Kelas Scale Ads",
                "gross_amount": 250000,
                "customer_name": "Rina Gunawan",
                "customer_phone": "6282233445566",
                "customer_email": "rina@example.com",
                "fbclid": None,
                "status": "EXPIRED",
                "payment_status": "EXPIRED",
                "download_url": "https://boontrack.com/access/kelas-scale-ads",
                "updated_at": "2026-11-05T10:15:00Z",
            },
            "ORD-FAILED-005": {
                "id": "ORD-FAILED-005",
                "tenant_id": CANONICAL_TENANT_A,
                "tenant_slug": "store-alpha",
                "product_title": "Kelas Scale Ads",
                "gross_amount": 250000,
                "customer_name": "Fajar Pratama",
                "customer_phone": "6283344556677",
                "customer_email": "fajar@example.com",
                "fbclid": None,
                "status": "FAILED",
                "payment_status": "FAILED",
                "download_url": "https://boontrack.com/access/kelas-scale-ads",
                "updated_at": "2026-11-05T10:20:00Z",
            },
        },
    }


def make_signed_headers(
    method: str,
    path: str,
    order_id: str,
    canonical_tenant_id: str,
    raw_body_bytes: bytes,
    actor_id: str = "admin_ops_01",
    nonce: Optional[str] = None,
    timestamp: Optional[int] = None,
    secret: str = TEST_HMAC_SECRET,
    key_id: str = TEST_HMAC_KEY_ID,
) -> Dict[str, str]:
    ts = timestamp if timestamp is not None else int(time.time())
    n = nonce or f"nonce_{int(time.time() * 1000000)}_{order_id}"
    sig = compute_internal_payment_hmac_signature(
        secret=secret,
        key_id=key_id,
        timestamp=ts,
        nonce=n,
        http_method=method,
        canonical_path=path,
        order_id=order_id,
        canonical_tenant_id=canonical_tenant_id,
        raw_body=raw_body_bytes,
    )
    return {
        HDR_KEY_ID: key_id,
        HDR_TIMESTAMP: str(ts),
        HDR_NONCE: n,
        HDR_SIGNATURE: sig,
        HDR_ACTOR: actor_id,
        HDR_TENANT_ID: canonical_tenant_id,
        "Content-Type": "application/json",
    }


@pytest.fixture
def fastapi_client(monkeypatch, pg_state):
    monkeypatch.setenv("PAYMENT_INTERNAL_HMAC_KEYRING_JSON", TEST_KEYRING_JSON)
    monkeypatch.setenv("APP_MASTER_KEY", "super_secret_app_master_key_do_not_allow")
    monkeypatch.setenv("BOONTRACK_INTERNAL_HMAC_SECRET", "internal_penny_hmac_secret_2026")
    monkeypatch.setenv("APP_ENV", "development")

    def _fake_get_db():
        if pg_state.get("db_down"):
            raise RuntimeError("PostgreSQL connection refused")
        return FakePostgresConnection(pg_state)

    monkeypatch.setattr("app.routes.d2c_order_routes.get_db_connection", _fake_get_db)
    monkeypatch.setattr("app.services.order_fulfillment_service.get_db_connection", _fake_get_db)
    monkeypatch.setattr("app.core.database.get_db_connection", _fake_get_db)

    app = FastAPI()
    app.include_router(d2c_router)
    app.include_router(academy_router)
    app.include_router(growth_router)
    app.include_router(checkout_api_router)
    app.include_router(payment_router)
    app.include_router(reader_router)
    return TestClient(app)


# ============================================================================
# 1. P0-A: MUTATION PERIMETER LOCKDOWN TESTS (FastAPI & aiohttp)
# ============================================================================

def test_p0a_public_mark_paid_blocked_fastapi(fastapi_client, pg_state):
    """Public /mark-paid must return HTTP 403 PUBLIC_MARK_PAID_DISABLED even with APP_MASTER_KEY."""
    for path in ("/api/v1/orders/ORD-PENDING-001/mark-paid", "/v1/orders/ORD-PENDING-001/mark-paid"):
        resp = fastapi_client.post(
            path,
            json={"agent_id": "attacker", "notes": "force paid"},
            headers={"Authorization": "Bearer super_secret_app_master_key_do_not_allow"},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"]["error_code"] == "PUBLIC_MARK_PAID_DISABLED"
        assert pg_state["orders"]["ORD-PENDING-001"]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_p0a_public_mark_paid_blocked_aiohttp(monkeypatch, pg_state):
    """aiohttp /mark-paid must return HTTP 403 PUBLIC_MARK_PAID_DISABLED without mutating order status."""
    app = web.Application()
    register_d2c_order_routes(app)

    async with AioTestClient(AioTestServer(app)) as client:
        for path in ("/api/v1/orders/ORD-PENDING-001/mark-paid", "/v1/orders/ORD-PENDING-001/mark-paid"):
            resp = await client.post(path, json={"agent_id": "attacker"})
            assert resp.status == 403
            data = await resp.json()
            assert data["error_code"] == "PUBLIC_MARK_PAID_DISABLED"
            assert pg_state["orders"]["ORD-PENDING-001"]["status"] == "PENDING"


def test_p0a_patch_status_rejects_unauthenticated_and_master_key(fastapi_client, pg_state):
    """PATCH /status must reject unauthenticated calls and APP_MASTER_KEY credentials."""
    path = "/api/v1/orders/ORD-PENDING-001/status"
    # 1. Unauthenticated
    r1 = fastapi_client.patch(path, json={"status": "CANCELLED"})
    assert r1.status_code == 401
    assert r1.json()["detail"]["error_code"] == "MISSING_HMAC_HEADERS"

    # 2. APP_MASTER_KEY in Authorization header -> 403 APP_MASTER_KEY_FORBIDDEN
    r2 = fastapi_client.patch(
        path,
        json={"status": "CANCELLED"},
        headers={"Authorization": "Bearer super_secret_app_master_key_do_not_allow"},
    )
    assert r2.status_code == 403
    assert r2.json()["detail"]["error_code"] == "APP_MASTER_KEY_FORBIDDEN"


def test_p0a_patch_status_forbids_settlement_statuses(fastapi_client, pg_state):
    """PATCH /status must reject PAID, LUNAS, SETTLED, SUCCESS even with valid internal HMAC."""
    path = "/api/v1/orders/ORD-PENDING-001/status"
    for forbidden_st in ("PAID", "LUNAS", "SETTLED", "SUCCESS", "COMPLETED", "APPROVED", "VERIFIED"):
        raw_body = json.dumps({"status": forbidden_st, "notes": "attempt settle"}).encode("utf-8")
        headers = make_signed_headers(
            method="PATCH",
            path=path,
            order_id="ORD-PENDING-001",
            canonical_tenant_id=CANONICAL_TENANT_A,
            raw_body_bytes=raw_body,
        )
        resp = fastapi_client.patch(path, content=raw_body, headers=headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN"
        assert pg_state["orders"]["ORD-PENDING-001"]["status"] == "PENDING"


def test_p0a_patch_status_enforces_tenant_ownership_replay_and_allows_non_settlement(fastapi_client, pg_state):
    """PATCH /status enforces canonical tenant ownership, anti-replay, fail-closed DB, and allows CANCELLED."""
    path = "/api/v1/orders/ORD-PENDING-001/status"
    raw_body = json.dumps({"status": "CANCELLED", "notes": "Customer requested cancellation"}).encode("utf-8")

    # 1. Cross-tenant attempt (Tenant B trying to mutate Tenant A's order) -> 403 TENANT_SPOOFING_DETECTED
    bad_tenant_headers = make_signed_headers(
        method="PATCH",
        path=path,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_B,
        raw_body_bytes=raw_body,
    )
    r_cross = fastapi_client.patch(path, content=raw_body, headers=bad_tenant_headers)
    assert r_cross.status_code == 403
    assert r_cross.json()["detail"]["error_code"] in ("TENANT_SPOOFING_DETECTED", "ORDER_TENANT_MISMATCH")

    # 2. Valid HMAC + Canonical Tenant A + Non-settlement status CANCELLED -> 200 OK
    valid_headers = make_signed_headers(
        method="PATCH",
        path=path,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_body,
        nonce="nonce_unique_patch_01",
    )
    r_ok = fastapi_client.patch(path, content=raw_body, headers=valid_headers)
    assert r_ok.status_code == 200
    data = r_ok.json()
    assert data["status"] == "CANCELLED"
    assert data["capi_dispatched"] is False
    assert pg_state["orders"]["ORD-PENDING-001"]["status"] == "CANCELLED"

    # 3. Replay identical request -> 403 DUPLICATE_NONCE_REPLAY
    r_replay = fastapi_client.patch(path, content=raw_body, headers=valid_headers)
    assert r_replay.status_code == 403
    assert r_replay.json()["detail"]["error_code"] == "DUPLICATE_NONCE_REPLAY"

    # 4. Authoritative PostgreSQL down -> 503 fail-closed
    pg_state["db_down"] = True
    outage_headers = make_signed_headers(
        method="PATCH",
        path=path,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_body,
        nonce="nonce_unique_patch_02",
    )
    r_outage = fastapi_client.patch(path, content=raw_body, headers=outage_headers)
    assert r_outage.status_code == 503
    assert r_outage.json()["detail"]["error_code"] in (
        "REPLAY_STORE_UNAVAILABLE",
        "AUTHORITATIVE_TENANT_STORE_UNAVAILABLE",
    )


def test_p0a_approve_and_deliver_lockdown_fastapi(fastapi_client, pg_state, monkeypatch):
    """
    Phase 1 Stage 2 Final Security Containment (P0-A):
    /approve-and-deliver must:
      1. Reject unauthenticated calls (401)
      2. Reject with 403 FULFILLMENT_PREMATURE_STAGE4_HOLD on both PENDING and PAID orders
         even with valid internal HMAC, because internal HMAC is NOT proof of settlement
         and fulfillment is strictly held until Stage 4 cryptographic settlement provenance.
    """
    unpaid_path = "/api/v1/orders/ORD-PENDING-001/approve-and-deliver"
    paid_path = "/api/v1/orders/ORD-PAID-002/approve-and-deliver"
    raw_body = b"{}"

    # 1. Unauthenticated -> 401
    r_unauth = fastapi_client.post(unpaid_path, content=raw_body)
    assert r_unauth.status_code == 401

    # 2. Signed request for PENDING order -> 403 FULFILLMENT_PREMATURE_STAGE4_HOLD
    headers_unpaid = make_signed_headers(
        method="POST",
        path=unpaid_path,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_body,
    )
    r_unpaid = fastapi_client.post(unpaid_path, content=raw_body, headers=headers_unpaid)
    assert r_unpaid.status_code == 403
    assert r_unpaid.json()["detail"]["error_code"] == "FULFILLMENT_PREMATURE_STAGE4_HOLD"

    # 3. Signed request for already PAID order -> 403 FULFILLMENT_PREMATURE_STAGE4_HOLD
    headers_paid = make_signed_headers(
        method="POST",
        path=paid_path,
        order_id="ORD-PAID-002",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_body,
    )
    r_paid = fastapi_client.post(paid_path, content=raw_body, headers=headers_paid)
    assert r_paid.status_code == 403
    assert r_paid.json()["detail"]["error_code"] == "FULFILLMENT_PREMATURE_STAGE4_HOLD"


@pytest.mark.asyncio
async def test_p0a_aiohttp_status_and_approve_and_deliver_parity(monkeypatch, pg_state):
    """aiohttp PATCH /status and POST /approve-and-deliver enforce identical Stage 2 guards."""
    monkeypatch.setenv("PAYMENT_INTERNAL_HMAC_KEYRING_JSON", TEST_KEYRING_JSON)
    monkeypatch.setenv("APP_MASTER_KEY", "super_secret_app_master_key_do_not_allow")
    monkeypatch.setattr(
        "app.routes.d2c_order_routes.get_db_connection",
        lambda: FakePostgresConnection(pg_state),
    )

    app = web.Application()
    register_d2c_order_routes(app)

    async with AioTestClient(AioTestServer(app)) as client:
        # 1. PATCH /status with PAID -> 403 SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN
        patch_path = "/api/v1/orders/ORD-PENDING-001/status"
        raw_paid = json.dumps({"status": "PAID"}).encode("utf-8")
        h_paid = make_signed_headers(
            method="PATCH",
            path=patch_path,
            order_id="ORD-PENDING-001",
            canonical_tenant_id=CANONICAL_TENANT_A,
            raw_body_bytes=raw_paid,
        )
        r1 = await client.patch(patch_path, data=raw_paid, headers=h_paid)
        assert r1.status == 403
        d1 = await r1.json()
        assert d1["error_code"] == "SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN"

        # 2. POST /approve-and-deliver on PENDING order -> 403 FULFILLMENT_PREMATURE_STAGE4_HOLD
        ad_pending_path = "/api/v1/orders/ORD-PENDING-001/approve-and-deliver"
        h_ad_pending = make_signed_headers(
            method="POST",
            path=ad_pending_path,
            order_id="ORD-PENDING-001",
            canonical_tenant_id=CANONICAL_TENANT_A,
            raw_body_bytes=b"{}",
        )
        r2 = await client.post(ad_pending_path, data=b"{}", headers=h_ad_pending)
        assert r2.status == 403
        d2 = await r2.json()
        assert d2["error_code"] == "FULFILLMENT_PREMATURE_STAGE4_HOLD"

        # 3. POST /approve-and-deliver on PAID order -> 403 FULFILLMENT_PREMATURE_STAGE4_HOLD
        ad_paid_path = "/api/v1/orders/ORD-PAID-002/approve-and-deliver"
        h_ad_paid = make_signed_headers(
            method="POST",
            path=ad_paid_path,
            order_id="ORD-PAID-002",
            canonical_tenant_id=CANONICAL_TENANT_A,
            raw_body_bytes=b"{}",
        )
        r3 = await client.post(ad_paid_path, data=b"{}", headers=h_ad_paid)
        assert r3.status == 403
        d3 = await r3.json()
        assert d3["error_code"] == "FULFILLMENT_PREMATURE_STAGE4_HOLD"


def test_p0c_status_transition_matrix_fastapi(fastapi_client, pg_state):
    """Enforces state transition matrix on PATCH /status (FastAPI)."""
    # 1. Terminal order cannot be reactivated
    for terminal_id in ("ORD-CANCELLED-003", "ORD-EXPIRED-004", "ORD-FAILED-005"):
        path = f"/api/v1/orders/{terminal_id}/status"
        raw_reactivate = json.dumps({"status": "PENDING"}).encode("utf-8")
        h_reactivate = make_signed_headers(
            method="PATCH",
            path=path,
            order_id=terminal_id,
            canonical_tenant_id=CANONICAL_TENANT_A,
            raw_body_bytes=raw_reactivate,
        )
        r_react = fastapi_client.patch(path, content=raw_reactivate, headers=h_reactivate)
        assert r_react.status_code == 409
        assert r_react.json()["detail"]["error_code"] == "INVALID_STATUS_TRANSITION"

    # 2. Settled order cannot be mutated via status PATCH
    path_settled = "/api/v1/orders/ORD-PAID-002/status"
    raw_mutate_settled = json.dumps({"status": "CANCELLED"}).encode("utf-8")
    h_settled = make_signed_headers(
        method="PATCH",
        path=path_settled,
        order_id="ORD-PAID-002",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_mutate_settled,
    )
    r_settled = fastapi_client.patch(path_settled, content=raw_mutate_settled, headers=h_settled)
    assert r_settled.status_code == 409
    assert r_settled.json()["detail"]["error_code"] == "INVALID_STATUS_TRANSITION"

    # 3. Target status in FORBIDDEN_SETTLEMENT_STATUS_VALUES -> 403
    path_pending = "/api/v1/orders/ORD-PENDING-001/status"
    raw_settle = json.dumps({"status": "SETTLED"}).encode("utf-8")
    h_settle = make_signed_headers(
        method="PATCH",
        path=path_pending,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_settle,
    )
    r_settle = fastapi_client.patch(path_pending, content=raw_settle, headers=h_settle)
    assert r_settle.status_code == 403
    assert r_settle.json()["detail"]["error_code"] == "SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN"

    # 4. Target status not in allowed non-settlement statuses -> 422
    raw_invalid = json.dumps({"status": "SHIPPED_CUSTOM"}).encode("utf-8")
    h_invalid = make_signed_headers(
        method="PATCH",
        path=path_pending,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_invalid,
    )
    r_invalid = fastapi_client.patch(path_pending, content=raw_invalid, headers=h_invalid)
    assert r_invalid.status_code == 422
    assert r_invalid.json()["detail"]["error_code"] == "INVALID_NON_SETTLEMENT_STATUS"

    # 5. Valid transition PENDING -> HOLD -> 200 OK
    raw_hold = json.dumps({"status": "HOLD"}).encode("utf-8")
    h_hold = make_signed_headers(
        method="PATCH",
        path=path_pending,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_hold,
    )
    r_hold = fastapi_client.patch(path_pending, content=raw_hold, headers=h_hold)
    assert r_hold.status_code == 200
    assert r_hold.json()["status"] == "HOLD"

    # 6. Idempotent same-status transition HOLD -> HOLD -> 200 OK
    h_hold2 = make_signed_headers(
        method="PATCH",
        path=path_pending,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=raw_hold,
    )
    r_hold2 = fastapi_client.patch(path_pending, content=raw_hold, headers=h_hold2)
    assert r_hold2.status_code == 200
    assert r_hold2.json()["status"] == "HOLD"


@pytest.mark.asyncio
async def test_p0c_status_transition_matrix_aiohttp(monkeypatch, pg_state):
    """Enforces state transition matrix on aiohttp PATCH /status."""
    monkeypatch.setenv("PAYMENT_INTERNAL_HMAC_KEYRING_JSON", TEST_KEYRING_JSON)
    monkeypatch.setattr(
        "app.routes.d2c_order_routes.get_db_connection",
        lambda: FakePostgresConnection(pg_state),
    )
    app = web.Application()
    register_d2c_order_routes(app)

    async with AioTestClient(AioTestServer(app)) as client:
        # 1. Terminal order CANCELLED cannot transition to PENDING -> 409
        path_cancel = "/api/v1/orders/ORD-CANCELLED-003/status"
        raw_react = json.dumps({"status": "PENDING"}).encode("utf-8")
        h_react = make_signed_headers(
            method="PATCH",
            path=path_cancel,
            order_id="ORD-CANCELLED-003",
            canonical_tenant_id=CANONICAL_TENANT_A,
            raw_body_bytes=raw_react,
        )
        r1 = await client.patch(path_cancel, data=raw_react, headers=h_react)
        assert r1.status == 409
        d1 = await r1.json()
        assert d1["error_code"] == "INVALID_STATUS_TRANSITION"

        # 2. Settled order PAID cannot transition -> 409
        path_settled = "/api/v1/orders/ORD-PAID-002/status"
        raw_mutate = json.dumps({"status": "CANCELLED"}).encode("utf-8")
        h_settled = make_signed_headers(
            method="PATCH",
            path=path_settled,
            order_id="ORD-PAID-002",
            canonical_tenant_id=CANONICAL_TENANT_A,
            raw_body_bytes=raw_mutate,
        )
        r2 = await client.patch(path_settled, data=raw_mutate, headers=h_settled)
        assert r2.status == 409
        d2 = await r2.json()
        assert d2["error_code"] == "INVALID_STATUS_TRANSITION"


def test_p0b_unverified_webhooks_containment_fastapi(fastapi_client, monkeypatch):
    """Unverified webhook mutation paths are blocked fail-closed."""
    # 1. /webhooks/payment -> 403 UNVERIFIED_WEBHOOK_MUTATION_BLOCKED
    for wh_path in ("/webhooks/payment", "/api/v1/webhooks/payment", "/api/v1/webhook/payment"):
        resp = fastapi_client.post(wh_path, json={"order_id": "ORD-001", "status": "PAID"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED"

    # 2. /api/v1/academy/webhook/paid -> 403 UNVERIFIED_WEBHOOK_MUTATION_BLOCKED
    resp_acad = fastapi_client.post("/api/v1/academy/webhook/paid", json={"order_id": "ORD-ACAD-001", "status": "PAID"})
    assert resp_acad.status_code == 403
    assert resp_acad.json()["detail"]["error_code"] == "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED"

    # 3. Midtrans webhook missing / invalid signature -> 401 INVALID_WEBHOOK_SIGNATURE
    monkeypatch.setattr("app.services.midtrans_service.midtrans_service.server_key", "SB-Mid-server-TESTKEY123")
    r_mid_nosig = fastapi_client.post(
        "/webhook/payment/midtrans",
        json={"order_id": "ORD-MID-001", "transaction_status": "settlement", "status_code": "200", "gross_amount": "10000.00"},
    )
    assert r_mid_nosig.status_code == 401
    assert r_mid_nosig.json()["detail"]["error_code"] == "INVALID_WEBHOOK_SIGNATURE"

    r_mid_badsig = fastapi_client.post(
        "/webhook/payment/midtrans",
        json={
            "order_id": "ORD-MID-001",
            "transaction_status": "settlement",
            "status_code": "200",
            "gross_amount": "10000.00",
            "signature_key": "invalid_sha512_hash",
        },
    )
    assert r_mid_badsig.status_code == 401
    assert r_mid_badsig.json()["detail"]["error_code"] == "INVALID_WEBHOOK_SIGNATURE"

    # 4. Midtrans webhook valid signature -> 200 OK
    import hashlib
    server_key = "SB-Mid-server-TESTKEY123"
    raw_str = f"ORD-MID-00120010000.00{server_key}"
    valid_sig = hashlib.sha512(raw_str.encode("utf-8")).hexdigest()
    monkeypatch.setattr("app.routes.payment.get_supabase", lambda: None)
    r_mid_ok = fastapi_client.post(
        "/webhook/payment/midtrans",
        json={
            "order_id": "ORD-MID-001",
            "transaction_status": "settlement",
            "status_code": "200",
            "gross_amount": "10000.00",
            "signature_key": valid_sig,
        },
    )
    assert r_mid_ok.status_code == 200


@pytest.mark.asyncio
async def test_p0b_unverified_webhooks_containment_aiohttp():
    """aiohttp webhook endpoints enforce unverified mutation containment."""
    app = web.Application()
    register_academy_routes(app)
    register_payment_routes(app)

    async with AioTestClient(AioTestServer(app)) as client:
        # 1. /api/v1/academy/webhook/paid -> 403 UNVERIFIED_WEBHOOK_MUTATION_BLOCKED
        r_acad = await client.post("/api/v1/academy/webhook/paid", json={"order_id": "ORD-001", "status": "PAID"})
        assert r_acad.status == 403
        d_acad = await r_acad.json()
        assert d_acad["error_code"] == "UNVERIFIED_WEBHOOK_MUTATION_BLOCKED"

        # 2. /webhook/payment/midtrans without signature -> 401 INVALID_WEBHOOK_SIGNATURE
        r_mid = await client.post(
            "/webhook/payment/midtrans",
            json={"order_id": "ORD-001", "transaction_status": "settlement", "status_code": "200", "gross_amount": "10000.00"},
        )
        assert r_mid.status == 401
        d_mid = await r_mid.json()
        assert d_mid["error_code"] == "INVALID_WEBHOOK_SIGNATURE"


# ============================================================================
# 2. P0-B & P0-C: DUMMY ACCOUNT ELIMINATION & DIRECT TENANT RAIL LOCKDOWN
# ============================================================================

def test_p0b_manual_adapter_rejects_defaults_and_dummy_accounts():
    """ManualTransferAdapter must reject missing bank fields or dummy '1234567890' / 'Merchant Store'."""
    with pytest.raises(PaymentConfigurationError, match="INVALID_PAYMENT_CONFIG"):
        ManualTransferAdapter()

    with pytest.raises(PaymentConfigurationError, match="DUMMY_BANK_ACCOUNT_FORBIDDEN"):
        ManualTransferAdapter(
            bank_name="BCA",
            account_number="1234567890",
            account_holder="PT Real Holder",
        )

    with pytest.raises(PaymentConfigurationError, match="DUMMY_BANK_ACCOUNT_FORBIDDEN"):
        ManualTransferAdapter(
            bank_name="BCA",
            account_number="8899776655",
            account_holder="Merchant Store",
        )


@pytest.mark.asyncio
async def test_p0c_manual_adapter_create_transaction_and_webhook_disabled():
    """Even with non-dummy bank fields, ManualTransferAdapter blocks create_transaction and webhook settlement."""
    adapter = ManualTransferAdapter(
        bank_name="BRI",
        account_number="8877665544",
        account_holder="PT Nusantara Jaya",
    )
    with pytest.raises(PaymentConfigurationError, match="DIRECT_TENANT_RAIL_DISABLED"):
        await adapter.create_transaction(
            TransactionRequest(
                order_id="ORD-001",
                amount=100000,
                customer_name="Buyer",
                customer_phone="628111222333",
            )
        )

    wh_res = await adapter.handle_webhook({"order_id": "ORD-001", "status": "PAID", "amount": 100000})
    assert wh_res.is_valid is False
    assert wh_res.status == "REJECTED_DIRECT_RAIL_DISABLED"


def test_p0b_p0c_payment_adapter_factory_fail_closed_and_native_pg_preserved():
    """
    PaymentAdapterFactory.resolve must:
      1. Fail closed on None / empty config (no fallback to ManualTransferAdapter)
      2. Fail closed on mode='MANUAL_TRANSFER' or provider='manual' / 'static_qris'
      3. Fail closed on unknown provider or missing Xendit/Duitku credentials
      4. Resolve XenditAdapter and DuitkuAdapter when valid Native PG config is provided
    """
    # 1. Empty config -> MISSING_PAYMENT_CONFIG
    with pytest.raises(PaymentConfigurationError, match="MISSING_PAYMENT_CONFIG"):
        PaymentAdapterFactory.resolve(None)

    with pytest.raises(PaymentConfigurationError, match="MISSING_PAYMENT_CONFIG"):
        PaymentAdapterFactory.resolve({})

    # 2. Direct Tenant Rail -> DIRECT_TENANT_RAIL_DISABLED
    for manual_cfg in (
        {"mode": "MANUAL_TRANSFER", "bank_name": "BCA", "account_number": "99887766", "account_holder": "Toko A"},
        {"provider": "manual"},
        {"provider": "static_qris"},
        {"mode": "STATIC_QRIS"},
    ):
        with pytest.raises(PaymentConfigurationError, match="DIRECT_TENANT_RAIL_DISABLED"):
            PaymentAdapterFactory.resolve(manual_cfg)

    # 3. Unknown provider -> UNSUPPORTED_PAYMENT_PROVIDER
    with pytest.raises(PaymentConfigurationError, match="UNSUPPORTED_PAYMENT_PROVIDER"):
        PaymentAdapterFactory.resolve({"provider": "unknown_pg_xyz"})

    # 4. Missing Xendit / Duitku credentials -> MISSING_PROVIDER_CREDENTIALS
    with pytest.raises(PaymentConfigurationError, match="MISSING_PROVIDER_CREDENTIALS"):
        PaymentAdapterFactory.resolve({"provider": "xendit"})

    with pytest.raises(PaymentConfigurationError, match="MISSING_PROVIDER_CREDENTIALS"):
        PaymentAdapterFactory.resolve({"provider": "duitku", "merchant_code": "D1234"})

    # 5. Valid Xendit Native PG config -> XenditAdapter
    xendit_ctx = TenantRuntimeContext(
        tenant_id=CANONICAL_TENANT_A,
        slug="store-alpha",
        name="Store Alpha",
        metadata={
            "payment_config": {
                "mode": "NATIVE_PG",
                "provider": "xendit",
                "secret_key": "xnd_development_valid_key_123",
                "callback_token": "xnd_cb_tok_123",
                "is_sandbox": True,
            }
        },
    )
    x_adapter = PaymentAdapterFactory.resolve(xendit_ctx)
    assert isinstance(x_adapter, XenditAdapter)

    # 6. Valid Duitku Native PG config -> DuitkuAdapter
    duitku_adapter = PaymentAdapterFactory.resolve({
        "payment_config": {
            "mode": "NATIVE_PG",
            "provider": "duitku",
            "merchant_code": "DS12345",
            "api_key": "duitku_api_key_xyz",
            "is_sandbox": True,
        }
    })
    assert isinstance(duitku_adapter, DuitkuAdapter)


def test_p0b_p0c_checkout_endpoints_fail_closed_on_missing_or_manual_config(fastapi_client, monkeypatch):
    """
    Checkout endpoints must return HTTP 422 when tenant has missing payment_config
    or MANUAL_TRANSFER / static QRIS config, and succeed when valid Native PG is configured.
    """
    # Case 1: Tenant has no payment_config -> HTTP 422 MISSING_PAYMENT_CONFIG
    unconfigured_ctx = TenantRuntimeContext(
        tenant_id=CANONICAL_TENANT_A,
        slug="store-unconfigured",
        name="Store Unconfigured",
        metadata={},
    )
    monkeypatch.setattr(
        "app.services.tenant_context_resolver.tenant_context_resolver.resolve_context",
        AsyncMock(return_value=unconfigured_ctx),
    )

    r1 = fastapi_client.post(
        "/api/v1/orders/qris-checkout",
        json={
            "merchant_slug": "store-unconfigured",
            "product_name": "Ebook Marketing",
            "customer_phone": "081234567890",
            "total_amount": 150000,
        },
    )
    assert r1.status_code == 422
    assert "MISSING_PAYMENT_CONFIG" in r1.json()["detail"]

    # Case 2: Tenant configured with MANUAL_TRANSFER / static_qris_payload -> HTTP 422 DIRECT_TENANT_RAIL_DISABLED
    manual_ctx = TenantRuntimeContext(
        tenant_id=CANONICAL_TENANT_A,
        slug="store-manual",
        name="Store Manual",
        metadata={
            "payment_config": {
                "mode": "MANUAL_TRANSFER",
                "provider": "manual",
                "static_qris_payload": "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI",
            }
        },
    )
    monkeypatch.setattr(
        "app.services.tenant_context_resolver.tenant_context_resolver.resolve_context",
        AsyncMock(return_value=manual_ctx),
    )

    for checkout_url in ("/api/v1/orders/qris-checkout", "/v1/orders/qris-checkout"):
        r_man = fastapi_client.post(
            checkout_url,
            json={
                "merchant_slug": "store-manual",
                "merchant_name": "Store Manual",
                "product_name": "Ebook Marketing",
                "customer_phone": "081234567890",
                "total_amount": 150000,
            },
        )
        assert r_man.status_code == 422
        assert "DIRECT_TENANT_RAIL_DISABLED" in r_man.json()["detail"]

    # Case 3: Tenant configured with valid Xendit Native PG -> HTTP 200 OK
    valid_xendit_ctx = TenantRuntimeContext(
        tenant_id=CANONICAL_TENANT_A,
        slug="store-xendit",
        name="Store Xendit",
        metadata={
            "payment_config": {
                "mode": "NATIVE_PG",
                "provider": "xendit",
                "secret_key": "xnd_development_valid_key_123",
            }
        },
    )
    monkeypatch.setattr(
        "app.services.tenant_context_resolver.tenant_context_resolver.resolve_context",
        AsyncMock(return_value=valid_xendit_ctx),
    )
    monkeypatch.setattr(
        "app.routes.d2c_order_routes.xendit_service.create_qris_invoice",
        AsyncMock(return_value={
            "external_id": "INV-XENDIT-001",
            "amount": 150000,
            "qr_string": "00020101021226660014ID.CO.XENDIT.WWW...",
            "qr_code_url": "https://api.xendit.co/qr/INV-XENDIT-001.png",
            "expires_at": "2026-11-05T12:15:00Z",
        }),
    )
    r_ok = fastapi_client.post(
        "/api/v1/orders/qris-checkout",
        json={
            "merchant_slug": "store-xendit",
            "product_name": "Ebook Marketing",
            "customer_phone": "081234567890",
            "total_amount": 150000,
        },
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["order_id"] == "INV-XENDIT-001"


@pytest.mark.asyncio
async def test_p0c_static_qris_and_reader_webhooks_disabled(fastapi_client):
    """Static QRIS Tag 54 test generator and Direct Tenant Rail DANA/Reader webhooks must return HTTP 403."""
    # 1. FastAPI static QRIS test endpoint -> 403
    r_qris = fastapi_client.get("/api/v1/payment/qris/test/150000")
    assert r_qris.status_code == 403
    assert "DIRECT_TENANT_RAIL_DISABLED" in r_qris.json()["detail"]

    # 2. aiohttp static QRIS test endpoint + DANA / Reader webhooks -> 403
    app = web.Application()
    register_payment_routes(app)
    register_payment_webhook_routes(app)

    async with AioTestClient(AioTestServer(app)) as client:
        r_aio_qris = await client.get("/api/v1/payment/qris/test/150000")
        assert r_aio_qris.status == 403

        for wh_path in ("/api/payments/webhook", "/api/webhook/payment-reader", "/api/webhook/dana"):
            r_wh = await client.post(
                wh_path,
                json={"title": "DANA Masuk", "body": "Rp249.123 diterima", "amount": 249123},
            )
            assert r_wh.status == 403
            wh_json = await r_wh.json()
            assert wh_json["error_code"] == "DIRECT_TENANT_RAIL_DISABLED"


@pytest.mark.asyncio
async def test_p0c_legacy_reader_and_dana_endpoints_containment_and_parity(fastapi_client, monkeypatch, pg_state):
    """
    Phase 1 Stage 2 Final Legacy Reader & DANA Containment (P0-C):
      1. FastAPI POST /api/v1/reader/notification is rejected with HTTP 403 DIRECT_TENANT_RAIL_DISABLED.
      2. aiohttp POST /api/v1/reader/notification is rejected with HTTP 403 DIRECT_TENANT_RAIL_DISABLED.
      3. aiohttp POST /webhook/dana is rejected with HTTP 403 DIRECT_TENANT_RAIL_DISABLED.
      4. Legacy default secret ('boontrack-reader-secret-change-me') is removed and cannot authorize Reader.
      5. Payment matchers and parsers are never called.
      6. No order status mutation occurs in PostgreSQL or Supabase.
      7. No fulfillment, WhatsApp, Telegram, or Meta/TikTok CAPI side effects are triggered.
      8. All route registrations and aliases across FastAPI and aiohttp are mapped and contained.
      9. FastAPI and aiohttp maintain identical containment response contracts.
    """
    import app.api.v1.reader as aio_reader_mod

    # Requirement 4: Verify legacy default static secret fallback is eliminated
    monkeypatch.delenv("READER_WEBHOOK_SECRET", raising=False)
    assert not hasattr(aio_reader_mod, "DEFAULT_SECRET_FALLBACK")
    assert aio_reader_mod.get_reader_secret() == ""

    # Set up strict spy mocks across all reader/DANA matchers, DB, fulfillment, CAPI, and Telegram bot
    mock_parse_reader = MagicMock(side_effect=AssertionError("parse_reader_notification must not be called"))
    mock_get_db = MagicMock(side_effect=AssertionError("get_db_connection must not be called"))
    mock_get_sb = MagicMock(side_effect=AssertionError("get_supabase must not be called"))
    mock_fulfill = AsyncMock(side_effect=AssertionError("handle_order_paid_fulfillment must not be called"))
    mock_capi = AsyncMock(side_effect=AssertionError("send_meta_capi_purchase must not be called"))
    mock_parse_gopay = MagicMock(side_effect=AssertionError("parse_gopay_notification must not be called"))
    mock_hybrid_proc = MagicMock(side_effect=AssertionError("HybridReaderProcessor must not be instantiated"))
    mock_match_order = AsyncMock(side_effect=AssertionError("match_and_complete_order must not be called"))
    mock_match_donation = AsyncMock(side_effect=AssertionError("match_and_complete_donation must not be called"))
    mock_match_fulfill = AsyncMock(side_effect=AssertionError("match_and_fulfill_payment must not be called"))
    mock_bot = MagicMock()
    mock_bot.send_document = AsyncMock(side_effect=AssertionError("bot.send_document must not be called"))
    mock_bot.send_message = AsyncMock(side_effect=AssertionError("bot.send_message must not be called"))

    monkeypatch.setattr("app.api.v1.reader_router.parse_reader_notification", mock_parse_reader)
    monkeypatch.setattr("app.api.v1.reader_router.get_db_connection", mock_get_db)
    monkeypatch.setattr("app.api.v1.reader_router.get_supabase", mock_get_sb)
    monkeypatch.setattr("app.api.v1.reader_router.handle_order_paid_fulfillment", mock_fulfill)
    monkeypatch.setattr("app.api.v1.reader_router.send_meta_capi_purchase", mock_capi)
    monkeypatch.setattr("app.api.v1.reader.parse_gopay_notification", mock_parse_gopay)
    monkeypatch.setattr("app.api.v1.reader.HybridReaderProcessor", mock_hybrid_proc)
    monkeypatch.setattr("app.api.endpoints.dana.match_and_complete_order", mock_match_order)
    monkeypatch.setattr("app.api.endpoints.dana.match_and_complete_donation", mock_match_donation)
    monkeypatch.setattr("app.api.endpoints.dana.bot", mock_bot)
    monkeypatch.setattr("app.routes.payment.match_and_fulfill_payment", mock_match_fulfill)
    # Requirement 1: FastAPI POST /api/v1/reader/notification rejected (with legacy secret, tenant header, etc.)
    fastapi_payload = {
        "tenant_id": "store-alpha",
        "app_source": "id.dana",
        "raw_text": "DANA Masuk Rp250.000 dari Buyer",
        "notification_id": "notif-001",
    }
    r_fastapi = fastapi_client.post(
        "/api/v1/reader/notification",
        json=fastapi_payload,
        headers={
            "X-Tenant-Id": "store-alpha",
            "X-Reader-Secret": "boontrack-reader-secret-change-me",
        },
    )
    assert r_fastapi.status_code == 403
    fastapi_body = r_fastapi.json()
    assert fastapi_body["status"] == "rejected"
    assert fastapi_body["error_code"] == "DIRECT_TENANT_RAIL_DISABLED"
    assert "DIRECT_TENANT_RAIL_DISABLED" in fastapi_body["detail"]

    # Verify FastAPI route registration on reader_router
    fastapi_reader_routes = {
        (getattr(r, "path", None), tuple(sorted(getattr(r, "methods", set()))))
        for r in reader_router.routes
    }
    assert ("/api/v1/reader/notification", ("POST",)) in fastapi_reader_routes

    # Requirements 2, 3, 4, 8, 9: aiohttp route registration, aliases, and containment parity
    aio_app = web.Application()
    register_api_routes(aio_app)
    register_reader_routes(aio_app)
    register_payment_routes(aio_app)
    register_payment_webhook_routes(aio_app)

    registered_post_paths = {
        getattr(getattr(r, "resource", None), "canonical", None)
        for r in aio_app.router.routes()
        if getattr(r, "method", None) == "POST"
    }
    expected_contained_paths = {
        "/api/v1/reader/notification",
        "/webhook/dana",
        "/api/webhook/dana",
        "/api/webhook/payment-reader",
        "/api/payments/webhook",
    }
    assert expected_contained_paths.issubset(registered_post_paths)

    # Also test when READER_WEBHOOK_SECRET is explicitly set in env: still 403
    monkeypatch.setenv("READER_WEBHOOK_SECRET", "custom-configured-secret-123")

    async with AioTestClient(AioTestServer(aio_app)) as client:
        # Requirement 2 & 4: aiohttp POST /api/v1/reader/notification with old default secret & configured secret
        for secret_val in ("boontrack-reader-secret-change-me", "custom-configured-secret-123", ""):
            r_aio_reader = await client.post(
                "/api/v1/reader/notification",
                json={
                    "title": "Pembayaran Masuk",
                    "body": "Rp250.000 diterima GoPay",
                    "package_name": "com.gojek.gopay.merchant",
                    "tenant_id": CANONICAL_TENANT_A,
                },
                headers={"X-Reader-Secret": secret_val, "X-Tenant-Id": CANONICAL_TENANT_A},
            )
            assert r_aio_reader.status == 403
            aio_reader_body = await r_aio_reader.json()
            assert aio_reader_body == fastapi_body

        # Requirement 3: aiohttp POST /webhook/dana
        r_aio_dana = await client.post(
            "/webhook/dana",
            json={
                "source": "id.dana",
                "title": "DANA Masuk",
                "message": "Berhasil menerima Rp250.000 di DANA Bisnis",
            },
        )
        assert r_aio_dana.status == 403
        aio_dana_body = await r_aio_dana.json()
        assert aio_dana_body["status"] == "rejected"
        assert aio_dana_body["error_code"] == "DIRECT_TENANT_RAIL_DISABLED"
        assert "DIRECT_TENANT_RAIL_DISABLED" in aio_dana_body["detail"]

        # Requirement 8: Verify all Direct Tenant Rail webhook aliases on aiohttp return 403 DIRECT_TENANT_RAIL_DISABLED
        for alias_path in expected_contained_paths:
            r_alias = await client.post(
                alias_path,
                json={"source": "id.dana", "message": "DANA Masuk Rp250.000", "amount": 250000},
            )
            assert r_alias.status == 403
            alias_json = await r_alias.json()
            assert alias_json["status"] == "rejected"
            assert alias_json["error_code"] == "DIRECT_TENANT_RAIL_DISABLED"

    # Requirements 5, 6, 7: Prove zero matcher, DB, order status, fulfillment, CAPI, or Telegram calls
    mock_parse_reader.assert_not_called()
    mock_get_db.assert_not_called()
    mock_get_sb.assert_not_called()
    mock_fulfill.assert_not_called()
    mock_capi.assert_not_called()
    mock_parse_gopay.assert_not_called()
    mock_hybrid_proc.assert_not_called()
    mock_match_order.assert_not_called()
    mock_match_donation.assert_not_called()
    mock_match_fulfill.assert_not_called()
    mock_bot.send_document.assert_not_called()
    mock_bot.send_message.assert_not_called()
    assert pg_state["orders"]["ORD-PENDING-001"]["status"] == "PENDING"
    assert pg_state["orders"]["ORD-PENDING-001"]["payment_status"] == "PENDING"


# ============================================================================
# 3. P0-D: CHECKOUT SESSION SECURITY TESTS (FastAPI & aiohttp)
# ============================================================================

def test_p0d_checkout_session_security_fastapi(fastapi_client):
    """
    Verifies P0-D requirements on FastAPI:
      - POST /api/v1/academy/invoice issues checkout_session_token, sets cookie, masks PII
      - GET /api/v1/academy/invoice/{order_id} with valid header token returns 200 with masked PII & stripped internal fields
      - GET without token, with wrong order's token, with query-string token (?token=...), with expired token,
        or with revoked/CANCELLED invoice returns identical HTTP 404 {"detail": "Invoice not found"} + security headers
    """
    _ACADEMY_INVOICES.clear()

    # 1. Create Invoice A (Tenant: onlineboost)
    create_resp_a = fastapi_client.post(
        "/api/v1/academy/invoice",
        json={
            "customer_name": "Andi Wijaya",
            "customer_email": "andi.wijaya@example.com",
            "customer_phone": "081234567890",
            "tenant_id": "onlineboost",
            "use_unique_code": False,
        },
    )
    assert create_resp_a.status_code == 200
    data_a = create_resp_a.json()
    order_id_a = data_a["invoice"]["order_id"]
    token_a = data_a["checkout_session_token"]
    assert token_a.startswith("v1.")
    assert create_resp_a.headers.get("Referrer-Policy") == "no-referrer"
    assert "no-store" in create_resp_a.headers.get("Cache-Control", "")

    # 2. Create Invoice B (different order)
    create_resp_b = fastapi_client.post(
        "/api/v1/academy/invoice",
        json={
            "customer_name": "Rina Kusuma",
            "customer_email": "rina.kusuma@example.com",
            "customer_phone": "089876543210",
            "tenant_id": "onlineboost",
            "use_unique_code": False,
        },
    )
    assert create_resp_b.status_code == 200
    order_id_b = create_resp_b.json()["invoice"]["order_id"]
    token_b = create_resp_b.json()["checkout_session_token"]

    # 3. Valid buyer accessing own Invoice A via X-Checkout-Session-Token header -> 200 OK with masked PII
    get_ok = fastapi_client.get(
        f"/api/v1/academy/invoice/{order_id_a}",
        headers={"X-Checkout-Session-Token": token_a},
    )
    assert get_ok.status_code == 200
    assert get_ok.headers.get("Referrer-Policy") == "no-referrer"
    assert "no-store" in get_ok.headers.get("Cache-Control", "")
    inv_dto = get_ok.json()["invoice"]
    assert inv_dto["order_id"] == order_id_a
    # PII must be masked (never raw email/phone/full name)
    assert inv_dto["customer_email"] != "andi.wijaya@example.com"
    assert "@" in inv_dto["customer_email"] and "*" in inv_dto["customer_email"]
    assert inv_dto["customer_phone"] != "6281234567890"
    assert "*" in inv_dto["customer_phone"]
    assert "*" in inv_dto["customer_name"]
    # Internal fields must be stripped
    assert "idempotency_key" not in inv_dto
    assert "is_internal_only" not in inv_dto
    assert "checkout_session" not in inv_dto
    assert "expires_at_dt" not in inv_dto

    # 4. Unauthenticated GET (no token) -> 404 identical to non-existent order
    unauth_client = TestClient(fastapi_client.app)
    r_no_tok = unauth_client.get(f"/api/v1/academy/invoice/{order_id_a}")
    r_nonexistent = unauth_client.get(
        "/api/v1/academy/invoice/BTA-ALUMNI-NONEXIST",
        headers={"X-Checkout-Session-Token": token_a},
    )
    assert r_no_tok.status_code == 404
    assert r_nonexistent.status_code == 404
    assert r_no_tok.json() == {"detail": "Invoice not found"}
    assert r_no_tok.json() == r_nonexistent.json()
    assert r_no_tok.headers.get("Referrer-Policy") == "no-referrer"

    # 5. Cross-order token (Token B used to read Invoice A) -> 404
    r_cross_order = unauth_client.get(
        f"/api/v1/academy/invoice/{order_id_a}",
        headers={"X-Checkout-Session-Token": token_b},
    )
    assert r_cross_order.status_code == 404
    assert r_cross_order.json() == {"detail": "Invoice not found"}

    # 6. Token in URL query string (?token=...) MUST be rejected even if valid -> 404
    r_url_tok = unauth_client.get(
        f"/api/v1/academy/invoice/{order_id_a}?token={token_a}",
        headers={"X-Checkout-Session-Token": token_a},
    )
    assert r_url_tok.status_code == 404
    assert r_url_tok.json() == {"detail": "Invoice not found"}

    # 7. Expired token -> 404
    _ACADEMY_INVOICES[order_id_a]["checkout_session"]["exp"] = int(time.time()) - 10
    r_expired = unauth_client.get(
        f"/api/v1/academy/invoice/{order_id_a}",
        headers={"X-Checkout-Session-Token": token_a},
    )
    assert r_expired.status_code == 404
    assert r_expired.json() == {"detail": "Invoice not found"}

    # 8. Revoked / CANCELLED invoice -> 404
    _ACADEMY_INVOICES[order_id_b]["status"] = "CANCELLED"
    r_cancelled = unauth_client.get(
        f"/api/v1/academy/invoice/{order_id_b}",
        headers={"X-Checkout-Session-Token": token_b},
    )
    assert r_cancelled.status_code == 404
    assert r_cancelled.json() == {"detail": "Invoice not found"}


@pytest.mark.asyncio
async def test_p0d_checkout_session_security_aiohttp():
    """Verifies P0-D parity on aiohttp Academy invoice endpoints."""
    _ACADEMY_INVOICES.clear()
    app = web.Application()
    register_academy_routes(app)

    async with AioTestClient(AioTestServer(app)) as client:
        resp_create = await client.post(
            "/api/v1/academy/invoice",
            json={
                "customer_name": "Dewi Lestari",
                "customer_email": "dewi@example.com",
                "customer_phone": "081122334455",
                "tenant_id": "onlineboost",
                "use_unique_code": False,
            },
        )
        assert resp_create.status == 200
        body = await resp_create.json()
        order_id = body["invoice"]["order_id"]
        token = body["checkout_session_token"]

        # Valid token in header -> 200 OK
        r_ok = await client.get(
            f"/api/v1/academy/invoice/{order_id}",
            headers={"X-Checkout-Session-Token": token},
        )
        assert r_ok.status == 200
        assert r_ok.headers.get("Referrer-Policy") == "no-referrer"

        # Token in query string -> 404
        r_query = await client.get(
            f"/api/v1/academy/invoice/{order_id}?st={token}",
            headers={"X-Checkout-Session-Token": token},
        )
        assert r_query.status == 404
        assert (await r_query.json()) == {"detail": "Invoice not found"}

        # Missing token (fresh client without cookies) -> 404
        client.session.cookie_jar.clear()
        r_missing = await client.get(f"/api/v1/academy/invoice/{order_id}")
        assert r_missing.status == 404
        assert (await r_missing.json()) == {"detail": "Invoice not found"}


# ============================================================================
# 4. P0-E: GROWTH SIMULATION & SUBSCRIPTION ISOLATION TESTS
# ============================================================================

def test_p0e_growth_simulate_order_paid_blocked_in_production_fastapi(fastapi_client, monkeypatch):
    """POST /api/v1/growth/simulate/order-paid must return HTTP 403 in production."""
    monkeypatch.setenv("APP_ENV", "production")
    resp = fastapi_client.post(
        "/api/v1/growth/simulate/order-paid",
        json={
            "tenant_id": CANONICAL_TENANT_A,
            "order_id": "ORD-PENDING-001",
            "amount": 250000,
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "SIMULATION_PROHIBITED_IN_PRODUCTION"


def test_p0e_growth_simulate_order_paid_requires_internal_hmac_in_non_prod(fastapi_client, monkeypatch):
    """In non-production, /api/v1/growth/simulate/order-paid requires internal HMAC authentication."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(
        "app.routes.growth_routes.process_order_paid_growth_event",
        AsyncMock(return_value=None),
    )
    path = "/api/v1/growth/simulate/order-paid"
    payload_bytes = json.dumps({
        "tenant_id": CANONICAL_TENANT_A,
        "order_id": "ORD-PENDING-001",
        "amount": 250000,
    }).encode("utf-8")

    # 1. Unauthenticated -> 401
    r_unauth = fastapi_client.post(path, content=payload_bytes)
    assert r_unauth.status_code == 401

    # 2. Signed with valid internal HMAC -> 200 OK
    headers = make_signed_headers(
        method="POST",
        path=path,
        order_id="ORD-PENDING-001",
        canonical_tenant_id=CANONICAL_TENANT_A,
        raw_body_bytes=payload_bytes,
    )
    r_ok = fastapi_client.post(path, content=payload_bytes, headers=headers)
    assert r_ok.status_code == 200
    assert r_ok.json()["success"] is True


@pytest.mark.asyncio
async def test_p0e_growth_simulate_order_paid_blocked_in_production_aiohttp(monkeypatch):
    """aiohttp /api/v1/growth/simulate/order-paid must return HTTP 403 in production."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    app = web.Application()
    register_growth_routes(app)

    async with AioTestClient(AioTestServer(app)) as client:
        resp = await client.post(
            "/api/v1/growth/simulate/order-paid",
            json={
                "tenant_id": CANONICAL_TENANT_A,
                "order_id": "ORD-PENDING-001",
                "amount": 250000,
            },
        )
        assert resp.status == 403
        data = await resp.json()
        assert data["error_code"] == "SIMULATION_PROHIBITED_IN_PRODUCTION"


@pytest.mark.asyncio
async def test_p0e_d2c_fulfillment_does_not_upgrade_tenant_to_checkout_lite(monkeypatch, pg_state):
    """
    D2C product purchase fulfillment must NOT mutate tenants.metadata.tier / subscription_tier
    to CHECKOUT_LITE in Supabase or return 'tier': 'CHECKOUT_LITE'.
    """
    from app.services.order_fulfillment_service import handle_order_paid_fulfillment

    mock_sb = MagicMock()
    tenants_table = MagicMock()

    def _table_router(table_name: str):
        if table_name == "tenants":
            return tenants_table
        return MagicMock()

    mock_sb.table.side_effect = _table_router
    monkeypatch.setattr("app.services.order_fulfillment_service.get_supabase", lambda: mock_sb)
    monkeypatch.setattr(
        "app.services.order_fulfillment_service.get_db_connection",
        lambda: FakePostgresConnection(pg_state),
    )

    res = await handle_order_paid_fulfillment(
        order_id="ORD-PAID-002",
        tenant_slug="store-alpha",
        agent_id="system_webhook",
    )
    assert res["success"] is True
    assert "tier" not in res
    # Ensure tenants.update(...) was NEVER called during D2C order fulfillment
    tenants_table.update.assert_not_called()
