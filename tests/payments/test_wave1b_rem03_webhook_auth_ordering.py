"""tests/payments/test_wave1b_rem03_webhook_auth_ordering.py
Wave 1B (REM-03) Regression Test Suite:
Webhook Auth Ordering, Malformed JSON Validation, Anti-Oracle & Route Deduplication.

Mandatory Acceptance Criteria Covered:
1. x-callback-token verification enforced BEFORE returning any response/error leaking order existence,
   amount match/mismatch, tenant conflict, or settlement status.
2. Indistinguishable auth-failure response (HTTP 403 INVALID_WEBHOOK_TOKEN) across missing/invalid tokens
   and combinations of existing vs non-existing external_id and matching vs mismatching amounts.
3. Fail-closed & strictly tenant-isolated credential resolution (zero cross-tenant fallback/leakage).
4. Strict JSON object (dict) payload validation: [], str, int, float, bool, null, and malformed JSON
   rejected with HTTP 400 error_code=INVALID_JSON_PAYLOAD across core, FastAPI, aiohttp, and delegates.
5. Constant-time token comparison via hmac.compare_digest (verified statically and at runtime).
6. expected_provider_account_id enforcement preserved across existing & unmatched order paths.
7. Clean /webhook/xendit route deduplication in FastAPI (app.main) and aiohttp without breaking
   any official/active Xendit webhook routes.
9. Zero settlement commits, zero email dispatches, zero WhatsApp dispatches, and zero CAPI dispatches
   when authentication fails.
"""

from __future__ import annotations

import ast
import inspect
import json
import hmac
from datetime import datetime, timezone
from pathlib import Path
import smtplib
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Ensure repository root is on sys.path and enforce isolated synthetic env before `app.*` imports
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.security.test_isolation_guard import bootstrap_isolated_test_env  # noqa: E402

bootstrap_isolated_test_env(REPO_ROOT)

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient as AioTestClient, TestServer as AioTestServer  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402

import app.api.webhook_payment as webhook_payment_mod  # noqa: E402
from app.core.database import get_db_connection  # noqa: E402
from app.core.security.payment_auth_guard import CredentialProfileMapper  # noqa: E402
import app.main as main_mod  # noqa: E402
import app.routes.payment as payment_routes  # noqa: E402
import app.routes.xendit as xendit_routes  # noqa: E402
import app.services.digital_fulfillment_service as digital_fulfill_mod  # noqa: E402
import app.services.email_service as email_service_mod  # noqa: E402


TENANT_ALPHA_UUID = "3b300000-0000-0000-0000-000000000001"
TENANT_BETA_UUID = "3b300000-0000-0000-0000-000000000002"
TENANT_NOCFG_UUID = "3b300000-0000-0000-0000-000000000003"

ALPHA_TOKEN_ACTIVE = "xen_rem03_alpha_active_secret_token_001"
ALPHA_TOKEN_SECONDARY = "xen_rem03_alpha_secondary_secret_token_002"
ALPHA_TOKEN_GRACE = "xen_rem03_alpha_grace_verify_only_token_003"
ALPHA_TOKEN_EXPIRED = "xen_rem03_alpha_expired_verify_only_token_004"
ALPHA_TOKEN_REVOKED = "xen_rem03_alpha_revoked_secret_token_005"
BETA_TOKEN_ACTIVE = "xen_rem03_beta_active_secret_token_999"

ALPHA_BIZ_ID = "xnd_biz_rem03_alpha_01"
ALPHA_BIZ_SECONDARY = "xnd_biz_rem03_alpha_02"
BETA_BIZ_ID = "xnd_biz_rem03_beta_01"

REM03_MOCK_VAULT: Dict[str, str] = {
    "vault://rem03/alpha/active": ALPHA_TOKEN_ACTIVE,
    "vault://rem03/alpha/secondary": ALPHA_TOKEN_SECONDARY,
    "vault://rem03/alpha/grace": ALPHA_TOKEN_GRACE,
    "vault://rem03/alpha/expired": ALPHA_TOKEN_EXPIRED,
    "vault://rem03/alpha/revoked": ALPHA_TOKEN_REVOKED,
    "vault://rem03/beta/active": BETA_TOKEN_ACTIVE,
}

EXPECTED_AUTH_FAILURE_BODY = {
    "status": "REJECTED",
    "error": "INVALID_WEBHOOK_TOKEN",
    "error_code": "INVALID_WEBHOOK_TOKEN",
    "detail": "Webhook authentication failed.",
}

EXPECTED_INVALID_JSON_BODY = {
    "status": "REJECTED",
    "error": "INVALID_JSON_PAYLOAD",
    "error_code": "INVALID_JSON_PAYLOAD",
    "detail": "Webhook JSON payload must be a valid JSON object.",
}


def _make_alpha_metadata() -> Dict[str, Any]:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    return {
        "payment_config": {
            "mode": "NATIVE_PG",
            "active_provider": "XENDIT",
            "default_credential_profile_id": "cred_rem03_alpha_primary",
            "credential_profiles": {
                "cred_rem03_alpha_primary": {
                    "credential_profile_id": "cred_rem03_alpha_primary",
                    "canonical_tenant_id": TENANT_ALPHA_UUID,
                    "provider": "XENDIT",
                    "verification_method": "XENDIT_CALLBACK_TOKEN",
                    "expected_provider_account_id": ALPHA_BIZ_ID,
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "verification_secrets": [
                        {
                            "secret_version_id": "sec_alpha_active_v1",
                            "secret_ref": "vault://rem03/alpha/active",
                            "status": "ACTIVE",
                        },
                        {
                            "secret_version_id": "sec_alpha_grace_v0",
                            "secret_ref": "vault://rem03/alpha/grace",
                            "status": "VERIFY_ONLY",
                            "not_after_epoch": now_epoch + 3600,
                        },
                        {
                            "secret_version_id": "sec_alpha_expired_v0",
                            "secret_ref": "vault://rem03/alpha/expired",
                            "status": "VERIFY_ONLY",
                            "not_after_epoch": now_epoch - 3600,
                        },
                        {
                            "secret_version_id": "sec_alpha_revoked_v0",
                            "secret_ref": "vault://rem03/alpha/revoked",
                            "status": "REVOKED",
                        },
                    ],
                },
                "cred_rem03_alpha_secondary": {
                    "credential_profile_id": "cred_rem03_alpha_secondary",
                    "canonical_tenant_id": TENANT_ALPHA_UUID,
                    "provider": "XENDIT",
                    "verification_method": "XENDIT_CALLBACK_TOKEN",
                    "expected_provider_account_id": ALPHA_BIZ_SECONDARY,
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "verification_secrets": [
                        {
                            "secret_version_id": "sec_alpha_secondary_v1",
                            "secret_ref": "vault://rem03/alpha/secondary",
                            "status": "ACTIVE",
                        }
                    ],
                },
            },
        }
    }


def _make_beta_metadata() -> Dict[str, Any]:
    return {
        "payment_config": {
            "mode": "NATIVE_PG",
            "active_provider": "XENDIT",
            "credential_profiles": {
                "cred_rem03_beta_primary": {
                    "credential_profile_id": "cred_rem03_beta_primary",
                    "canonical_tenant_id": TENANT_BETA_UUID,
                    "provider": "XENDIT",
                    "verification_method": "XENDIT_CALLBACK_TOKEN",
                    "expected_provider_account_id": BETA_BIZ_ID,
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "verification_secrets": [
                        {
                            "secret_version_id": "sec_beta_active_v1",
                            "secret_ref": "vault://rem03/beta/active",
                            "status": "ACTIVE",
                        }
                    ],
                }
            },
        }
    }


@pytest.fixture(scope="session", autouse=True)
def setup_rem03_tenants() -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata, slug = EXCLUDED.slug;
            """,
            (TENANT_ALPHA_UUID, "REM03 Alpha", "tenant-rem03-alpha", json.dumps(_make_alpha_metadata())),
        )
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata, slug = EXCLUDED.slug;
            """,
            (TENANT_BETA_UUID, "REM03 Beta", "tenant-rem03-beta", json.dumps(_make_beta_metadata())),
        )
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata, slug = EXCLUDED.slug;
            """,
            (TENANT_NOCFG_UUID, "REM03 Unconfigured", "tenant-rem03-nocfg", json.dumps({})),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


@pytest.fixture(autouse=True)
def patch_rem03_vault_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    orig_resolve = CredentialProfileMapper._resolve_secret_ref

    def _mock_resolve(self: CredentialProfileMapper, ref: str) -> str:
        if ref in REM03_MOCK_VAULT:
            return REM03_MOCK_VAULT[ref]
        return orig_resolve(self, ref)

    monkeypatch.setattr(CredentialProfileMapper, "_resolve_secret_ref", _mock_resolve)


def _insert_order(
    order_id: str,
    *,
    tenant_id: str = TENANT_ALPHA_UUID,
    tenant_slug: str = "tenant-rem03-alpha",
    gross_amount: int = 249000,
    status: str = "PENDING",
    product_id: str = "prod_digital",
    credential_profile_id: str = "cred_rem03_alpha_primary",
) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    meta: Dict[str, Any] = {}
    if credential_profile_id:
        meta["credential_profile_id"] = credential_profile_id
        meta["provider"] = "XENDIT"
    try:
        cur.execute(
            """
            INSERT INTO orders (
                id, tenant_id, tenant_slug, product_id, product_title, gross_amount,
                customer_name, customer_phone, customer_email, status, payment_status,
                metadata, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                payment_status = EXCLUDED.payment_status,
                gross_amount = EXCLUDED.gross_amount,
                metadata = EXCLUDED.metadata;
            """,
            (
                order_id,
                tenant_id,
                tenant_slug,
                product_id,
                "REM03 Security Product",
                gross_amount,
                "Buyer REM03",
                "6281234567890",
                "buyer-rem03@example.com",
                status,
                status,
                json.dumps(meta),
                now_iso,
                now_iso,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _get_order_status(order_id: str) -> Optional[str]:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT status FROM orders WHERE id = %s;", (order_id,))
        row = cur.fetchone()
        return str(row[0]) if row else None
    finally:
        cur.close()
        conn.close()


def _count_settlement_artifacts(order_id: str) -> Dict[str, int]:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM payment_events WHERE order_id = %s;", (order_id,))
        pe_cnt = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM financial_ledger WHERE order_id = %s;", (order_id,))
        fl_cnt = int(cur.fetchone()[0])
        return {"payment_events": pe_cnt, "financial_ledger": fl_cnt}
    finally:
        cur.close()
        conn.close()


def _build_payload(
    external_id: Optional[str],
    amount: Any = 249000,
    *,
    status_str: str = "COMPLETED",
    business_id: Optional[str] = ALPHA_BIZ_ID,
    currency: Optional[str] = "IDR",
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": f"qr_pay_rem03_{uuid.uuid4().hex[:8]}",
        "amount": amount,
        "status": status_str,
    }
    if external_id is not None:
        data["external_id"] = external_id
    if business_id is not None:
        data["business_id"] = business_id
    if currency is not None:
        data["currency"] = currency
    payload: Dict[str, Any] = {
        "event": "qr.payment",
        "data": data,
    }
    if business_id is not None:
        payload["business_id"] = business_id
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return payload


def _build_fastapi_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(xendit_routes.xendit_router)
    app.include_router(payment_routes.payment_router)
    return TestClient(app)


# =============================================================================
# 1. Zero Existence / Amount / Status / Tenant Oracle Matrix (Criteria 1 & 2)
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_headers",
    [
        {},
        {"x-callback-token": ""},
        {"x-callback-token": "   "},
        {"x-callback-token": "forged-wrong-token-123"},
        {"X-Callback-Token": "forged-mixed-case-header-token"},
        {"x-callback-token": "app_master_key_super_secret"},
        {"x-callback-token": ALPHA_TOKEN_REVOKED},
        {"x-callback-token": ALPHA_TOKEN_EXPIRED},
    ],
)
async def test_rem03_zero_oracle_indistinguishable_auth_failure_matrix(
    bad_headers: Dict[str, str],
) -> None:
    """Criteria 1 & 2: Invalid/missing tokens yield byte-identical 403 across all existence/amount/status probes."""
    pending_order_id = f"ORD-REM03-PEND-{uuid.uuid4().hex[:8]}"
    paid_order_id = f"ORD-REM03-PAID-{uuid.uuid4().hex[:8]}"
    expired_order_id = f"ORD-REM03-EXP-{uuid.uuid4().hex[:8]}"
    ghost_order_id = f"ORD-REM03-GHOST-{uuid.uuid4().hex[:8]}"

    _insert_order(pending_order_id, gross_amount=249000, status="PENDING")
    _insert_order(paid_order_id, gross_amount=249000, status="PAID")
    _insert_order(expired_order_id, gross_amount=249000, status="EXPIRED")

    probe_payloads = [
        # Existing order, matching amount, matching biz
        _build_payload(pending_order_id, 249000, business_id=ALPHA_BIZ_ID),
        # Existing order, mismatching amount (over/under/penny)
        _build_payload(pending_order_id, 999999, business_id=ALPHA_BIZ_ID),
        _build_payload(pending_order_id, 1500, business_id=ALPHA_BIZ_ID),
        # Existing order, malformed amount, boolean amount, non-IDR currency
        _build_payload(pending_order_id, "not-a-number", business_id=ALPHA_BIZ_ID),
        _build_payload(pending_order_id, True, business_id=ALPHA_BIZ_ID),
        _build_payload(pending_order_id, 249000, currency="USD", business_id=ALPHA_BIZ_ID),
        # Existing order, non-paid status (must NOT return 200 IGNORED!)
        _build_payload(pending_order_id, 249000, status_str="PENDING", business_id=ALPHA_BIZ_ID),
        # Existing order, spoofed tenant_id (must NOT leak ORDER_TENANT_MISMATCH)
        _build_payload(pending_order_id, 249000, tenant_id=TENANT_BETA_UUID, business_id=ALPHA_BIZ_ID),
        # Existing order, missing business_id
        _build_payload(pending_order_id, 249000, business_id=None),
        # Already PAID and EXPIRED orders
        _build_payload(paid_order_id, 249000, business_id=ALPHA_BIZ_ID),
        _build_payload(expired_order_id, 249000, business_id=ALPHA_BIZ_ID),
        # Non-existing ghost order, matching & mismatching amounts, missing biz
        _build_payload(ghost_order_id, 249000, business_id=ALPHA_BIZ_ID),
        _build_payload(ghost_order_id, 999999, business_id=ALPHA_BIZ_ID),
        _build_payload(ghost_order_id, 249000, business_id=None),
        # Missing external_id
        _build_payload(None, 249000, business_id=ALPHA_BIZ_ID),
    ]

    for payload in probe_payloads:
        res = await xendit_routes.process_xendit_webhook_core(payload, bad_headers)
        assert res["http_status"] == 403, f"Expected 403 for probe {payload}, got {res}"
        assert res["response"] == EXPECTED_AUTH_FAILURE_BODY
        assert ALPHA_BIZ_ID not in json.dumps(res)

    assert _get_order_status(pending_order_id) == "PENDING"
    assert _get_order_status(expired_order_id) == "EXPIRED"
    assert _count_settlement_artifacts(pending_order_id) == {
        "payment_events": 0,
        "financial_ledger": 0,
    }


@pytest.mark.asyncio
async def test_rem03_zero_oracle_across_fastapi_and_aiohttp_routes() -> None:
    """Criteria 1, 2 & 7: All active FastAPI and aiohttp Xendit webhook paths enforce identical anti-oracle 403."""
    order_id = f"ORD-REM03-ROUTES-{uuid.uuid4().hex[:8]}"
    ghost_id = f"ORD-REM03-GHOST-R-{uuid.uuid4().hex[:8]}"
    _insert_order(order_id, gross_amount=150000, status="PENDING")

    existing_wrong_amt = _build_payload(order_id, 999999, business_id=ALPHA_BIZ_ID)
    ghost_payload = _build_payload(ghost_id, 150000, business_id=ALPHA_BIZ_ID)

    fa_client = _build_fastapi_test_client()
    fastapi_paths = [
        "/api/v1/webhooks/xendit",
        "/webhook/payment/xendit",
        "/api/v1/payments/xendit/callback",
        "/api/v1/payment/xendit/callback",
        "/webhook/xendit",
        "/api/v1/payments/webhook/xendit",
        "/api/v1/payment/webhook/xendit",
        "/api/webhook/payment/xendit",
    ]
    for path in fastapi_paths:
        for body_payload in (existing_wrong_amt, ghost_payload):
            resp_missing = fa_client.post(path, json=body_payload)
            assert resp_missing.status_code == 403, f"{path} missing token returned {resp_missing.status_code}"
            assert resp_missing.json() == EXPECTED_AUTH_FAILURE_BODY

            resp_bad = fa_client.post(
                path,
                json=body_payload,
                headers={"x-callback-token": "wrong-token"},
            )
            assert resp_bad.status_code == 403, f"{path} bad token returned {resp_bad.status_code}"
            assert resp_bad.json() == EXPECTED_AUTH_FAILURE_BODY

    aio_x_app = web.Application()
    xendit_routes.register_xendit_routes(aio_x_app)
    aio_p_app = web.Application()
    payment_routes.register_payment_routes(aio_p_app)

    async with AioTestClient(AioTestServer(aio_x_app)) as client_x:
        for path in (
            "/webhook/payment/xendit",
            "/api/v1/payments/xendit/callback",
            "/api/v1/payment/xendit/callback",
            "/webhook/xendit",
        ):
            for body_payload in (existing_wrong_amt, ghost_payload):
                r = await client_x.post(path, json=body_payload, headers={"x-callback-token": "wrong-token"})
                assert r.status == 403
                assert await r.json() == EXPECTED_AUTH_FAILURE_BODY

    async with AioTestClient(AioTestServer(aio_p_app)) as client_p:
        for path in (
            "/webhook/payment/xendit",
            "/api/v1/payments/webhook/xendit",
            "/api/v1/payments/xendit/callback",
        ):
            for body_payload in (existing_wrong_amt, ghost_payload):
                r = await client_p.post(path, json=body_payload, headers={"x-callback-token": "wrong-token"})
                assert r.status == 403
                assert await r.json() == EXPECTED_AUTH_FAILURE_BODY


# =============================================================================
# 2. Tenant Isolation, Profile Binding & Post-Auth Behavior (Criteria 3 & 6)
# =============================================================================

@pytest.mark.asyncio
async def test_rem03_strict_tenant_isolation_and_account_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criteria 3 & 6: Fail-closed tenant isolation, profile binding, and expected_provider_account_id check."""
    # Even if legacy global XENDIT_CALLBACK_TOKEN is set in env, it MUST NEVER authorize tenant orders.
    monkeypatch.setenv("XENDIT_CALLBACK_TOKEN", "legacy_global_token_must_be_ignored")

    order_alpha = f"ORD-REM03-ALPHA-{uuid.uuid4().hex[:8]}"
    order_nocfg = f"ORD-REM03-NOCFG-{uuid.uuid4().hex[:8]}"
    ghost_order = f"ORD-REM03-GHOST-AUTH-{uuid.uuid4().hex[:8]}"

    _insert_order(
        order_alpha,
        tenant_id=TENANT_ALPHA_UUID,
        tenant_slug="tenant-rem03-alpha",
        gross_amount=249000,
        status="PENDING",
        credential_profile_id="cred_rem03_alpha_primary",
    )
    _insert_order(
        order_nocfg,
        tenant_id=TENANT_NOCFG_UUID,
        tenant_slug="tenant-rem03-nocfg",
        gross_amount=249000,
        status="PENDING",
        credential_profile_id="",
    )

    # 1. Global env token rejected fail-closed
    res_global = await xendit_routes.process_xendit_webhook_core(
        _build_payload(order_alpha, 249000, business_id=ALPHA_BIZ_ID),
        {"x-callback-token": "legacy_global_token_must_be_ignored"},
    )
    assert res_global["http_status"] == 403
    assert res_global["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 2. Tenant Beta credentials cannot settle Tenant Alpha's order (zero cross-tenant fallback)
    res_cross = await xendit_routes.process_xendit_webhook_core(
        _build_payload(order_alpha, 249000, business_id=BETA_BIZ_ID),
        {"x-callback-token": BETA_TOKEN_ACTIVE},
    )
    assert res_cross["http_status"] == 403
    assert res_cross["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 3. Same-tenant secondary profile cannot bypass primary credential_profile_id binding
    res_secondary = await xendit_routes.process_xendit_webhook_core(
        _build_payload(order_alpha, 249000, business_id=ALPHA_BIZ_SECONDARY),
        {"x-callback-token": ALPHA_TOKEN_SECONDARY},
    )
    assert res_secondary["http_status"] == 403
    assert res_secondary["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 4. Unconfigured tenant fails closed (no cross-tenant fallback)
    res_nocfg = await xendit_routes.process_xendit_webhook_core(
        _build_payload(order_nocfg, 249000, business_id=ALPHA_BIZ_ID),
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_nocfg["http_status"] == 403
    assert res_nocfg["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 5. Valid token with missing or wrong expected_provider_account_id fails closed
    res_missing_biz = await xendit_routes.process_xendit_webhook_core(
        _build_payload(order_alpha, 249000, business_id=None),
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_missing_biz["http_status"] == 403
    assert res_missing_biz["response"] == EXPECTED_AUTH_FAILURE_BODY

    res_wrong_biz = await xendit_routes.process_xendit_webhook_core(
        _build_payload(order_alpha, 249000, business_id="xnd_biz_spoofed"),
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_wrong_biz["http_status"] == 403
    assert res_wrong_biz["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 6. Conflicting top-level business_id vs data.business_id fails closed even with valid token
    conflict_payload = _build_payload(order_alpha, 249000, business_id=ALPHA_BIZ_ID)
    conflict_payload["business_id"] = BETA_BIZ_ID
    res_conflict_biz = await xendit_routes.process_xendit_webhook_core(
        conflict_payload,
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_conflict_biz["http_status"] == 403
    assert res_conflict_biz["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 7. Unmatched order + valid Alpha token + Beta tenant_id claim fails closed (zero cross-tenant ghost leak)
    res_ghost_cross = await xendit_routes.process_xendit_webhook_core(
        _build_payload(ghost_order, 249000, business_id=ALPHA_BIZ_ID, tenant_id=TENANT_BETA_UUID),
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_ghost_cross["http_status"] == 403
    assert res_ghost_cross["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 8. Unmatched order + valid Alpha token + wrong business_id fails closed (never leaks 404)
    res_ghost_wrong_biz = await xendit_routes.process_xendit_webhook_core(
        _build_payload(ghost_order, 249000, business_id="xnd_biz_wrong"),
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_ghost_wrong_biz["http_status"] == 403
    assert res_ghost_wrong_biz["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 9. Authenticated caller on ghost order WITH valid tenant claim STILL returns 404 ORDER_NOT_FOUND
    res_ghost_authed = await xendit_routes.process_xendit_webhook_core(
        _build_payload(ghost_order, 249000, business_id=ALPHA_BIZ_ID, tenant_id=TENANT_ALPHA_UUID),
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_ghost_authed["http_status"] == 404
    assert res_ghost_authed["response"]["error_code"] == "ORDER_NOT_FOUND"

    # 9b. Valid token on ghost order WITHOUT tenant claim fails closed (never scans all tenants)
    res_ghost_no_tenant = await xendit_routes.process_xendit_webhook_core(
        _build_payload(ghost_order, 249000, business_id=ALPHA_BIZ_ID, tenant_id=None),
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_ghost_no_tenant["http_status"] == 403
    assert res_ghost_no_tenant["response"] == EXPECTED_AUTH_FAILURE_BODY

    # 10. Authenticated caller on existing order with mismatched amount returns 400 AMOUNT_MISMATCH
    res_amt_mismatch = await xendit_routes.process_xendit_webhook_core(
        _build_payload(order_alpha, 199000, business_id=ALPHA_BIZ_ID),
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res_amt_mismatch["http_status"] == 400
    assert res_amt_mismatch["response"]["error_code"] == "AMOUNT_MISMATCH"
    assert _get_order_status(order_alpha) == "PENDING"

    # 11. Authenticated caller with matching amount + grace VERIFY_ONLY or ACTIVE token settles cleanly
    with patch("app.routes.xendit.sync_xendit_settlement_to_supabase_catchup", return_value=True), \
         patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock), \
         patch("app.routes.xendit.send_capi_task", new_callable=AsyncMock):
        res_ok = await xendit_routes.process_xendit_webhook_core(
            _build_payload(order_alpha, 249000, business_id=ALPHA_BIZ_ID),
            {"X-Callback-Token": ALPHA_TOKEN_GRACE},
        )
    assert res_ok["http_status"] == 200
    assert res_ok["response"]["status"] == "SUCCESS"
    assert _get_order_status(order_alpha) == "PAID"


# =============================================================================
# 3. Malformed & Non-Object JSON Payload Validation (Criterion 4)
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "non_dict_payload",
    [
        [],
        [{"external_id": "ORD-1"}],
        "not-a-json-object",
        12345,
        99.95,
        True,
        False,
        None,
    ],
)
async def test_rem03_core_rejects_non_dict_payloads_with_400_invalid_json_payload(
    non_dict_payload: Any,
) -> None:
    """Criterion 4: process_xendit_webhook_core rejects non-dict payloads with HTTP 400 INVALID_JSON_PAYLOAD."""
    res = await xendit_routes.process_xendit_webhook_core(
        non_dict_payload,  # type: ignore[arg-type]
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert res["http_status"] == 400
    assert res["response"] == EXPECTED_INVALID_JSON_BODY

    res_p, code_p = await payment_routes.handle_xendit_notification_logic(
        non_dict_payload,
        {"x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert code_p == 400
    assert res_p == EXPECTED_INVALID_JSON_BODY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_body",
    [
        b"[]",
        b'[{"external_id": "ORD-1"}]',
        b'"plain-string"',
        b"12345",
        b"true",
        b"false",
        b"null",
        b"{malformed-json",
        b"",
    ],
)
async def test_rem03_http_endpoints_reject_malformed_and_non_object_json_with_400(
    raw_body: bytes,
) -> None:
    """Criterion 4: Every FastAPI and aiohttp Xendit endpoint rejects malformed/non-object JSON with 400 INVALID_JSON_PAYLOAD."""
    fa_client = _build_fastapi_test_client()
    headers = {"Content-Type": "application/json", "x-callback-token": ALPHA_TOKEN_ACTIVE}

    for path in (
        "/api/v1/webhooks/xendit",
        "/webhook/payment/xendit",
        "/api/v1/payments/xendit/callback",
        "/api/v1/payment/xendit/callback",
        "/webhook/xendit",
        "/api/v1/payments/webhook/xendit",
        "/api/v1/payment/webhook/xendit",
        "/api/webhook/payment/xendit",
    ):
        resp = fa_client.post(path, content=raw_body, headers=headers)
        assert resp.status_code == 400, f"Path {path} returned {resp.status_code} for {raw_body!r}: {resp.text}"
        assert resp.json()["error_code"] == "INVALID_JSON_PAYLOAD"
        assert resp.json()["error"] == "INVALID_JSON_PAYLOAD"

    aio_x_app = web.Application()
    xendit_routes.register_xendit_routes(aio_x_app)
    aio_p_app = web.Application()
    payment_routes.register_payment_routes(aio_p_app)

    async with AioTestClient(AioTestServer(aio_x_app)) as client_x:
        for path in (
            "/webhook/payment/xendit",
            "/api/v1/payments/xendit/callback",
            "/api/v1/payment/xendit/callback",
            "/webhook/xendit",
        ):
            r = await client_x.post(path, data=raw_body, headers=headers)
            assert r.status == 400
            body = await r.json()
            assert body["error_code"] == "INVALID_JSON_PAYLOAD"

    async with AioTestClient(AioTestServer(aio_p_app)) as client_p:
        for path in (
            "/webhook/payment/xendit",
            "/api/v1/payments/webhook/xendit",
            "/api/v1/payments/xendit/callback",
        ):
            r = await client_p.post(path, data=raw_body, headers=headers)
            assert r.status == 400
            body = await r.json()
            assert body["error_code"] == "INVALID_JSON_PAYLOAD"


# =============================================================================
# 4. Constant-Time Token Comparison Verification (Criterion 5)
# =============================================================================

def test_rem03_constant_time_hmac_compare_digest_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 5: Token comparisons use hmac.compare_digest statically and at runtime."""
    # 1. Static check: webhook_payment.py must not contain raw `!=` or `==` on token strings
    wp_src = inspect.getsource(webhook_payment_mod)
    assert "hmac.compare_digest" in wp_src
    wp_tree = ast.parse(wp_src)
    for node in ast.walk(wp_tree):
        if isinstance(node, ast.Compare):
            names = [
                n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            ]
            if any("token" in name.lower() for name in names):
                raise AssertionError(f"Non-constant-time token comparison found in webhook_payment.py: {ast.dump(node)}")

    # 2. Runtime spy on hmac.compare_digest inside webhook_payment.get_verified_webhook_supabase_client
    monkeypatch.setenv("XENDIT_CALLBACK_TOKEN", "rem03_verified_secret_123")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "rem03_service_role_key_abc")
    monkeypatch.setenv("SUPABASE_URL", "https://synthetic-test.supabase.invalid")

    with patch("app.api.webhook_payment.hmac.compare_digest", wraps=hmac.compare_digest) as spy_cmp:
        sb = webhook_payment_mod.get_verified_webhook_supabase_client({"X-Callback-Token": "rem03_verified_secret_123"})
        assert sb is not None
        assert spy_cmp.call_count >= 1
        with pytest.raises(PermissionError):
            webhook_payment_mod.get_verified_webhook_supabase_client({"x-callback-token": "wrong_secret"})
        assert spy_cmp.call_count >= 2


@pytest.mark.asyncio
async def test_rem03_core_runtime_uses_hmac_compare_digest() -> None:
    """Criterion 5: Runtime Xendit auth invokes hmac.compare_digest on both matched & unmatched orders."""
    order_id = f"ORD-REM03-HMAC-{uuid.uuid4().hex[:8]}"
    _insert_order(order_id, gross_amount=249000, status="PENDING")

    with patch("app.core.security.payment_auth_guard.hmac.compare_digest", wraps=hmac.compare_digest) as spy_guard:
        res_exist = await xendit_routes.process_xendit_webhook_core(
            _build_payload(order_id, 249000, business_id=ALPHA_BIZ_ID),
            {"x-callback-token": "invalid-candidate"},
        )
        assert res_exist["http_status"] == 403
        assert spy_guard.call_count >= 1

    with patch("app.routes.xendit.hmac.compare_digest", wraps=hmac.compare_digest) as spy_xendit:
        res_ghost = await xendit_routes.process_xendit_webhook_core(
            _build_payload(f"GHOST-{uuid.uuid4().hex[:6]}", 249000, business_id=ALPHA_BIZ_ID),
            {"x-callback-token": "invalid-candidate"},
        )
        assert res_ghost["http_status"] == 403
        assert spy_xendit.call_count >= 1


# =============================================================================
# 5. /webhook/xendit Deduplication & Active Routes Preservation (Criterion 7)
# =============================================================================

def _collect_fastapi_post_path_counts(routes: Any, prefix: str = "") -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for route in routes:
        if hasattr(route, "original_router"):
            inc_prefix = str(getattr(getattr(route, "include_context", None), "prefix", "") or "")
            sub_counts = _collect_fastapi_post_path_counts(route.original_router.routes, prefix=prefix + inc_prefix)
            for p, c in sub_counts.items():
                counts[p] = counts.get(p, 0) + c
        elif hasattr(route, "routes") and not hasattr(route, "methods"):
            sub_counts = _collect_fastapi_post_path_counts(route.routes, prefix=prefix)
            for p, c in sub_counts.items():
                counts[p] = counts.get(p, 0) + c
        else:
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", None)
            if "POST" in methods and path:
                full_path = f"{prefix}{path}" if prefix and not path.startswith(prefix) else path
                counts[full_path] = counts.get(full_path, 0) + 1
    return counts


@pytest.mark.asyncio
async def test_rem03_webhook_xendit_deduplicated_without_breaking_active_routes() -> None:
    """Criterion 7: FastAPI app.main and aiohttp mount exactly one /webhook/xendit and keep all active routes."""
    post_path_counts = _collect_fastapi_post_path_counts(main_mod.app.routes)

    # webhook_payment_router must not carry a colliding /webhook/xendit route
    assert len(webhook_payment_mod.router.routes) == 0

    # Exactly 1 /webhook/xendit route in app.main (no collision from webhook_payment_router)
    assert post_path_counts.get("/webhook/xendit") == 1, f"Unexpected /webhook/xendit count: {post_path_counts}"

    # All official/active Xendit routes remain mounted
    expected_active_routes = (
        "/api/v1/webhooks/xendit",
        "/webhook/payment/xendit",
        "/api/v1/payments/xendit/callback",
        "/api/v1/payment/xendit/callback",
        "/webhook/xendit",
        "/api/v1/payments/webhook/xendit",
        "/api/v1/payment/webhook/xendit",
        "/api/webhook/payment/xendit",
    )
    for active_path in expected_active_routes:
        assert post_path_counts.get(active_path) == 1, f"Expected active route {active_path} count=1, got {post_path_counts.get(active_path)}"

    # Exercise main.app directly over /webhook/xendit and /api/v1/payments/xendit/callback
    order_id = f"ORD-REM03-MAIN-{uuid.uuid4().hex[:8]}"
    _insert_order(order_id, gross_amount=249000, status="PENDING")
    main_client = TestClient(main_mod.app)

    r_bad = main_client.post(
        "/webhook/xendit",
        json=_build_payload(order_id, 999999, business_id=ALPHA_BIZ_ID),
        headers={"x-callback-token": "bad-token"},
    )
    assert r_bad.status_code == 403
    assert r_bad.json() == EXPECTED_AUTH_FAILURE_BODY

    r_arr = main_client.post(
        "/webhook/xendit",
        content=b"[]",
        headers={"Content-Type": "application/json", "x-callback-token": ALPHA_TOKEN_ACTIVE},
    )
    assert r_arr.status_code == 400
    assert r_arr.json()["error_code"] == "INVALID_JSON_PAYLOAD"

    with patch("app.routes.xendit.sync_xendit_settlement_to_supabase_catchup", return_value=True), \
         patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock), \
         patch("app.routes.xendit.send_capi_task", new_callable=AsyncMock):
        r_ok = main_client.post(
            "/webhook/xendit",
            json=_build_payload(order_id, 249000, business_id=ALPHA_BIZ_ID),
            headers={"x-callback-token": ALPHA_TOKEN_ACTIVE},
        )
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "SUCCESS"

    # aiohttp deduplication check when both register_xendit_routes and register_webhook_payment_routes run
    aio_app = web.Application()
    xendit_routes.register_xendit_routes(aio_app)
    webhook_payment_mod.register_webhook_payment_routes(aio_app)
    aio_xendit_count = sum(
        1
        for r in aio_app.router.routes()
        if getattr(r, "method", None) == "POST"
        and getattr(getattr(r, "resource", None), "canonical", None) == "/webhook/xendit"
    )
    assert aio_xendit_count == 1

    # Also verify standalone register_webhook_payment_routes registers canonical hardened handler
    aio_wp_only = web.Application()
    webhook_payment_mod.register_webhook_payment_routes(aio_wp_only)
    async with AioTestClient(AioTestServer(aio_wp_only)) as wp_client:
        r_wp_bad_json = await wp_client.post(
            "/webhook/xendit",
            data=b"{bad",
            headers={"Content-Type": "application/json", "x-callback-token": ALPHA_TOKEN_ACTIVE},
        )
        assert r_wp_bad_json.status == 400
        assert (await r_wp_bad_json.json())["error_code"] == "INVALID_JSON_PAYLOAD"

        r_wp_bad_tok = await wp_client.post(
            "/webhook/xendit",
            json=_build_payload(order_id, 249000, business_id=ALPHA_BIZ_ID),
            headers={"x-callback-token": "wrong-token"},
        )
        assert r_wp_bad_tok.status == 403
        assert await r_wp_bad_tok.json() == EXPECTED_AUTH_FAILURE_BODY


# =============================================================================
# 6. Zero Settlement / Email / WhatsApp / CAPI Side-Effects on Auth Failure (Criterion 9)
# =============================================================================

@pytest.mark.asyncio
async def test_rem03_zero_settlement_email_whatsapp_capi_dispatches_on_auth_failure() -> None:
    """Criterion 9: Auth failures produce zero settlement commits and zero email/WA/CAPI dispatches."""
    order_id = f"ORD-REM03-SIDEFX-{uuid.uuid4().hex[:8]}"
    _insert_order(order_id, gross_amount=249000, status="PENDING")

    with patch("app.routes.xendit.commit_verified_settlement_transaction") as spy_commit, \
         patch("app.routes.xendit.sync_xendit_settlement_to_supabase_catchup") as spy_sb_sync, \
         patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock) as spy_wa_notif, \
         patch("app.routes.xendit.send_whatsapp_text", new_callable=AsyncMock) as spy_wa_text, \
         patch("app.routes.xendit.send_ereceipt_whatsapp", new_callable=AsyncMock) as spy_wa_receipt, \
         patch("app.routes.xendit.dispatch_payment_success_notifications", new_callable=AsyncMock) as spy_waba_disp, \
         patch("app.routes.xendit.send_capi_task", new_callable=AsyncMock) as spy_capi_task, \
         patch("app.routes.xendit.send_meta_capi_purchase", new_callable=AsyncMock) as spy_meta_capi, \
         patch("app.routes.xendit.dispatch_all_capi", new_callable=AsyncMock) as spy_all_capi, \
         patch.object(xendit_routes.capi_dispatcher, "dispatch_purchase", new_callable=AsyncMock) as spy_capi_disp, \
         patch.object(email_service_mod.EmailService, "send_email_sync") as spy_email_sync, \
         patch.object(email_service_mod.EmailService, "send_email_async", new_callable=AsyncMock) as spy_email_async, \
         patch.object(smtplib, "SMTP") as spy_smtp, \
         patch.object(digital_fulfill_mod, "fulfill_if_digital", new_callable=AsyncMock) as spy_digital_if, \
         patch.object(digital_fulfill_mod, "fulfill_digital_order", new_callable=AsyncMock) as spy_digital_ord:

        fa_client = _build_fastapi_test_client()

        # 1. Core call with missing token & matching amount
        r1 = await xendit_routes.process_xendit_webhook_core(
            _build_payload(order_id, 249000, business_id=ALPHA_BIZ_ID),
            {},
        )
        assert r1["http_status"] == 403

        # 2. Core call with wrong token & tampered amount
        r2 = await xendit_routes.process_xendit_webhook_core(
            _build_payload(order_id, 1, business_id=ALPHA_BIZ_ID),
            {"x-callback-token": "wrong-token"},
        )
        assert r2["http_status"] == 403

        # 3. Core call with valid token but mismatched expected_provider_account_id
        r3 = await xendit_routes.process_xendit_webhook_core(
            _build_payload(order_id, 249000, business_id=BETA_BIZ_ID),
            {"x-callback-token": ALPHA_TOKEN_ACTIVE},
        )
        assert r3["http_status"] == 403

        # 4. FastAPI /webhook/xendit and /api/v1/payments/webhook/xendit auth failures
        for path in ("/webhook/xendit", "/api/v1/payments/webhook/xendit", "/api/v1/payments/xendit/callback"):
            resp = fa_client.post(
                path,
                json=_build_payload(order_id, 249000, business_id=ALPHA_BIZ_ID),
                headers={"x-callback-token": "forged-token"},
            )
            assert resp.status_code == 403

        # 5. aiohttp auth failures
        aio_app = web.Application()
        xendit_routes.register_xendit_routes(aio_app)
        async with AioTestClient(AioTestServer(aio_app)) as aio_client:
            r_aio = await aio_client.post(
                "/webhook/xendit",
                json=_build_payload(order_id, 249000, business_id=ALPHA_BIZ_ID),
                headers={"x-callback-token": "forged-token"},
            )
            assert r_aio.status == 403

        # Assert zero commits, zero Supabase catch-up, zero WA, zero Email, zero CAPI, zero digital fulfillment
        spy_commit.assert_not_called()
        spy_sb_sync.assert_not_called()
        spy_wa_notif.assert_not_called()
        spy_wa_text.assert_not_called()
        spy_wa_receipt.assert_not_called()
        spy_waba_disp.assert_not_called()
        spy_capi_task.assert_not_called()
        spy_meta_capi.assert_not_called()
        spy_all_capi.assert_not_called()
        spy_capi_disp.assert_not_called()
        spy_email_sync.assert_not_called()
        spy_email_async.assert_not_called()
        spy_smtp.assert_not_called()
        spy_digital_if.assert_not_called()
        spy_digital_ord.assert_not_called()

    assert _get_order_status(order_id) == "PENDING"
    assert _count_settlement_artifacts(order_id) == {
        "payment_events": 0,
        "financial_ledger": 0,
    }


# =============================================================================
# 7. Explicit Cross-Tenant Anti-Oracle Regression Matrix (CTO Blocker Remediation)
# =============================================================================

@pytest.mark.asyncio
async def test_rem03_cross_tenant_anti_oracle_strict_matrix(
    setup_rem03_tenants: None,
) -> None:
    """CTO Blocker Remediation: Proves cross-tenant anti-oracle hardening across all permutations.

    1. Tenant A token + unmatched order + NO tenant claim -> 403 INVALID_WEBHOOK_TOKEN
    2. Tenant A token + unmatched order + Tenant B claim -> 403 INVALID_WEBHOOK_TOKEN
    3. Tenant A token + Tenant B existing order -> 403 INVALID_WEBHOOK_TOKEN
    4. Tenant B token + Tenant B existing order -> passes auth and proceeds to order validation
    5. Assert identical HTTP status & response envelope across all auth-failure cases,
       and prove ZERO settlement commits, ZERO email, ZERO WhatsApp, and ZERO CAPI dispatches.
    """
    order_alpha = f"ORD-REM03-ALPHA-XOR-{uuid.uuid4().hex[:8]}"
    order_beta = f"ORD-REM03-BETA-XOR-{uuid.uuid4().hex[:8]}"
    _insert_order(
        order_alpha,
        tenant_id=TENANT_ALPHA_UUID,
        tenant_slug="tenant-rem03-alpha",
        gross_amount=249000,
        status="PENDING",
        credential_profile_id="cred_rem03_alpha_primary",
    )
    _insert_order(
        order_beta,
        tenant_id=TENANT_BETA_UUID,
        tenant_slug="tenant-rem03-beta",
        gross_amount=150000,
        status="PENDING",
        credential_profile_id="cred_rem03_beta_primary",
    )
    unmatched_order_id = f"ORD-REM03-UNMATCHED-{uuid.uuid4().hex[:8]}"

    with patch("app.routes.xendit.commit_verified_settlement_transaction") as spy_commit, \
         patch("app.routes.xendit.sync_xendit_settlement_to_supabase_catchup") as spy_sb_sync, \
         patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock) as spy_wa_notif, \
         patch("app.routes.xendit.send_capi_task", new_callable=AsyncMock) as spy_capi_task, \
         patch.object(email_service_mod.EmailService, "send_email_sync") as spy_email_sync, \
         patch.object(email_service_mod.EmailService, "send_email_async", new_callable=AsyncMock) as spy_email_async:

        # Case 1: Tenant A token + unmatched order + NO tenant claim -> 403 INVALID_WEBHOOK_TOKEN
        r1 = await xendit_routes.process_xendit_webhook_core(
            _build_payload(unmatched_order_id, 249000, business_id=ALPHA_BIZ_ID, tenant_id=None),
            {"x-callback-token": ALPHA_TOKEN_ACTIVE},
        )
        assert r1["http_status"] == 403
        assert r1["response"] == EXPECTED_AUTH_FAILURE_BODY

        # Case 2: Tenant A token + unmatched order + Tenant B claim -> 403 INVALID_WEBHOOK_TOKEN
        r2 = await xendit_routes.process_xendit_webhook_core(
            _build_payload(unmatched_order_id, 249000, business_id=ALPHA_BIZ_ID, tenant_id=TENANT_BETA_UUID),
            {"x-callback-token": ALPHA_TOKEN_ACTIVE},
        )
        assert r2["http_status"] == 403
        assert r2["response"] == EXPECTED_AUTH_FAILURE_BODY

        # Case 3: Tenant A token + Tenant B existing order -> 403 INVALID_WEBHOOK_TOKEN
        r3 = await xendit_routes.process_xendit_webhook_core(
            _build_payload(order_beta, 150000, business_id=BETA_BIZ_ID),
            {"x-callback-token": ALPHA_TOKEN_ACTIVE},
        )
        assert r3["http_status"] == 403
        assert r3["response"] == EXPECTED_AUTH_FAILURE_BODY

        # Invariant check across all 3 auth-failure responses: identical envelope
        assert r1["response"] == r2["response"] == r3["response"] == EXPECTED_AUTH_FAILURE_BODY
        assert r1["http_status"] == r2["http_status"] == r3["http_status"] == 403

        # Assert ZERO side-effects dispatched on all auth failures
        spy_commit.assert_not_called()
        spy_sb_sync.assert_not_called()
        spy_wa_notif.assert_not_called()
        spy_capi_task.assert_not_called()
        spy_email_sync.assert_not_called()
        spy_email_async.assert_not_called()

    # Case 4: Tenant B token + Tenant B existing order -> passes auth and proceeds to order validation
    with patch("app.routes.xendit.sync_xendit_settlement_to_supabase_catchup", return_value=True), \
         patch("app.routes.xendit.send_whatsapp_payment_notification", new_callable=AsyncMock), \
         patch("app.routes.xendit.send_capi_task", new_callable=AsyncMock):
        r4 = await xendit_routes.process_xendit_webhook_core(
            _build_payload(order_beta, 150000, business_id=BETA_BIZ_ID),
            {"x-callback-token": BETA_TOKEN_ACTIVE},
        )
    assert r4["http_status"] == 200
    assert r4["response"]["status"] == "SUCCESS"
    assert _get_order_status(order_beta) == "PAID"

