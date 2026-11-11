"""tests/test_phase1_stage3_step2b2_webhook_binding.py
Phase 1 Stage 3 Step 2B.2: Inbound Settlement & Webhook Credential Profile Binding Rail.

Covers all 20 Required Scenarios (S3-T01 through S3-T20):
- S3-T01: Missing / Invalid Xendit Token (Xendit)
- S3-T02: Tampered Midtrans Signature (Midtrans)
- S3-T03: Tampered Duitku Signature (Duitku)
- S3-T04: Cross-Merchant Account Replay Rejection (HTTP 403 PROVIDER_ACCOUNT_BINDING_MISMATCH)
- S3-T05: Direct merchant_id == tenant_id Spoofing Rejection
- S3-T06: Payload Tenant Switching Attempt Rejection (HTTP 403 ORDER_TENANT_MISMATCH)
- S3-T07: Lockdown Legacy String Parsing (TOPUP- & sub_ routes -> HTTP 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD)
- S3-T08: Ghost Order Auto-Creation Prevention (HTTP 404 ORDER_NOT_FOUND)
- S3-T09: Underpayment / Overpayment Amount Mismatch (HTTP 400/422)
- S3-T10: Non-Integer / Float Amount Injection (HTTP 400/422 PROVENANCE_INVALID_AMOUNT)
- S3-T11: Non-IDR Currency Rejection (HTTP 422 PROVENANCE_INVALID_CURRENCY)
- S3-T12: Non-Final Status Callback Acknowledged Without Settlement (HTTP 200)
- S3-T13: Midtrans Capture Fraud Status Guard (capture requires fraud_status == 'accept')
- S3-T14: Duitku S2S Verification Failure (HTTP 503 DUITKU_S2S_VERIFICATION_FAILED)
- S3-T15: 5x Concurrent Duplicate Callback (Exactly 1 settles, 4 return HTTP 200 already_processed)
- S3-T16: Conflicting Payload Replay Collision (HTTP 409 CONFLICTING_PAYMENT_EVENT_REPLAY)
- S3-T17: Late Settlement Quarantine on EXPIRED/CANCELLED Orders (HTTP 200 QUARANTINED_LATE_SETTLEMENT)
- S3-T18: Secret Key Rotation Lifecycle (ACTIVE, VERIFY_ONLY, REVOKED)
- S3-T19: Database Outage Fail-Closed Protection (HTTP 503 DATABASE_UNAVAILABLE, 0 Supabase fallback)
- S3-T20: Dual-Runner Parity & Deprecated Route Lock (HTTP 403 across FastAPI & aiohttp)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Ensure repository root is on sys.path and enforce isolated synthetic env before `app.*` imports
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.security.test_isolation_guard import bootstrap_isolated_test_env
bootstrap_isolated_test_env(REPO_ROOT)

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from aiohttp import web
from aiohttp.test_utils import TestClient as AioTestClient, TestServer as AioTestServer

from app.core.database import get_db_connection
from app.core.security.payment_auth_guard import CredentialProfileMapper
from app.routes.payment import (
    payment_router,
    handle_midtrans_notification_logic,
    handle_xendit_notification_logic,
    register_payment_routes,
)
from app.routes.xendit import process_xendit_webhook_core
from app.routes.duitku_routes import (
    router as duitku_router,
    process_duitku_callback_core,
    set_duitku_s2s_verifier,
    register_duitku_routes,
)
from app.routes.shop_subscription_routes import (
    shop_subscription_fastapi_router,
    register_shop_subscription_routes,
)
from app.api.v1.endpoints.payment_webhook import router as generic_webhook_router

# Test Identifiers
TENANT_ALPHA_ID = "2b200000-0000-0000-0000-000000000001"
TENANT_BETA_ID = "2b200000-0000-0000-0000-000000000002"

XENDIT_TOKEN_ALPHA = "xen_token_alpha_secret_key_123"
MIDTRANS_SERVER_KEY_ALPHA = "mid_server_key_alpha_secret_456"
DUITKU_API_KEY_ALPHA = "dk_api_key_alpha_secret_789"

XENDIT_TOKEN_BETA = "xen_token_beta_secret_key_999"
MIDTRANS_SERVER_KEY_BETA = "mid_server_key_beta_secret_888"
DUITKU_API_KEY_BETA = "dk_api_key_beta_secret_777"

MOCK_VAULT: Dict[str, str] = {
    "vault://tenants/alpha/xendit/active": XENDIT_TOKEN_ALPHA,
    "vault://tenants/alpha/midtrans/active": MIDTRANS_SERVER_KEY_ALPHA,
    "vault://tenants/alpha/duitku/active": DUITKU_API_KEY_ALPHA,
    "vault://tenants/beta/xendit/active": XENDIT_TOKEN_BETA,
    "vault://tenants/beta/midtrans/active": MIDTRANS_SERVER_KEY_BETA,
    "vault://tenants/beta/duitku/active": DUITKU_API_KEY_BETA,
}


def _make_tenant_metadata(slug: str, tenant_uuid: str) -> Dict[str, Any]:
    is_beta = (tenant_uuid == TENANT_BETA_ID or "beta" in slug)
    key_prefix = "beta" if is_beta else "alpha"
    return {
        "payment_config": {
            "mode": "NATIVE_PG",
            "active_provider": "XENDIT",
            "credential_profiles": {
                f"cred_xendit_{key_prefix}": {
                    "credential_profile_id": f"cred_xendit_{key_prefix}",
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "XENDIT",
                    "verification_method": "XENDIT_CALLBACK_TOKEN",
                    "expected_provider_account_id": f"xnd_biz_{key_prefix}_01",
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "verification_secrets": [
                        {
                            "secret_version_id": f"xnd_sec_{key_prefix}_v1",
                            "secret_ref": f"vault://tenants/{key_prefix}/xendit/active",
                            "status": "ACTIVE",
                        }
                    ],
                },
                f"cred_midtrans_{key_prefix}": {
                    "credential_profile_id": f"cred_midtrans_{key_prefix}",
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "MIDTRANS",
                    "verification_method": "MIDTRANS_SHA512",
                    "expected_provider_account_id": f"M_{key_prefix.upper()}_123",
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "verification_secrets": [
                        {
                            "secret_version_id": f"mid_sec_{key_prefix}_v1",
                            "secret_ref": f"vault://tenants/{key_prefix}/midtrans/active",
                            "status": "ACTIVE",
                        }
                    ],
                },
                f"cred_duitku_{key_prefix}": {
                    "credential_profile_id": f"cred_duitku_{key_prefix}",
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "DUITKU",
                    "verification_method": "DUITKU_CALLBACK_HMAC_SHA256",
                    "expected_provider_account_id": f"D_{key_prefix.upper()}",
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "verification_secrets": [
                        {
                            "secret_version_id": f"dk_sec_{key_prefix}_v1",
                            "secret_ref": f"vault://tenants/{key_prefix}/duitku/active",
                            "status": "ACTIVE",
                        }
                    ],
                },
            },
        }
    }


@pytest.fixture(scope="session", autouse=True)
def setup_test_database_tenants():
    """Seeds test tenants into PostgreSQL cluster on 55439."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Tenant Alpha
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata, slug = EXCLUDED.slug;
            """,
            (
                TENANT_ALPHA_ID,
                "Tenant Alpha Store",
                "tenant-2b2-alpha",
                json.dumps(_make_tenant_metadata("alpha", TENANT_ALPHA_ID)),
            ),
        )
        # Tenant Beta
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata, slug = EXCLUDED.slug;
            """,
            (
                TENANT_BETA_ID,
                "Tenant Beta Store",
                "tenant-2b2-beta",
                json.dumps(_make_tenant_metadata("beta", TENANT_BETA_ID)),
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


@pytest.fixture(autouse=True)
def patch_vault_resolver(monkeypatch):
    """Patches CredentialProfileMapper secret resolution to mock vault store."""
    orig_resolve = CredentialProfileMapper._resolve_secret_ref

    def _mock_resolve(self, ref: str) -> str:
        if ref in MOCK_VAULT:
            return MOCK_VAULT[ref]
        return orig_resolve(self, ref)

    monkeypatch.setattr(CredentialProfileMapper, "_resolve_secret_ref", _mock_resolve)


@pytest.fixture(autouse=True)
def default_duitku_s2s():
    """Sets a successful Duitku S2S verifier stub by default."""
    def _success_verifier(req: Any) -> Dict[str, Any]:
        return {
            "statusCode": "00",
            "statusMessage": "SUCCESS",
            "merchantOrderId": str(req.get("merchantOrderId")),
            "reference": str(req.get("reference") or f"REF-{uuid.uuid4().hex[:6]}"),
            "amount": req.get("amount"),
        }
    set_duitku_s2s_verifier(_success_verifier)
    yield
    set_duitku_s2s_verifier(None)


@pytest.fixture
def fastapi_client():
    app = FastAPI()
    app.include_router(payment_router)
    app.include_router(duitku_router)
    app.include_router(shop_subscription_fastapi_router)
    app.include_router(generic_webhook_router)
    return TestClient(app)


def _insert_test_order(
    order_id: str,
    tenant_id: str = TENANT_ALPHA_ID,
    tenant_slug: str = "tenant-2b2-alpha",
    gross_amount: int = 249000,
    status: str = "PENDING",
    product_id: str = "prod_digital",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    now_utc = datetime.now(timezone.utc).isoformat()
    try:
        cur.execute(
            """
            INSERT INTO orders (
                id, tenant_id, tenant_slug, product_id, product_title, gross_amount,
                customer_name, customer_phone, customer_email, status, metadata, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                gross_amount = EXCLUDED.gross_amount,
                metadata = EXCLUDED.metadata;
            """,
            (
                order_id,
                tenant_id,
                tenant_slug,
                product_id,
                "Course ATS Masterclass",
                gross_amount,
                "Budi Pratama",
                "081234567890",
                "budi@example.com",
                status,
                json.dumps(metadata or {}),
                now_utc,
                now_utc,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _get_order_state(order_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, status, payment_status, gross_amount FROM orders WHERE id = %s", (order_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "status": row[1], "payment_status": row[2], "gross_amount": int(row[3])}
    finally:
        cur.close()
        conn.close()


def _count_payment_events(order_id: str) -> int:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM payment_events WHERE order_id = %s", (order_id,))
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()


def _count_ledger_entries(order_id: str) -> int:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM financial_ledger WHERE order_id = %s", (order_id,))
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()


# =============================================================================
# S3-T01: Missing / Invalid Xendit Token
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t01_missing_or_invalid_xendit_token():
    order_id = f"ORD-T01-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    payload = {
        "event": "qr.payment",
        "business_id": "xnd_biz_alpha_01",
        "data": {
            "id": f"qr_pay_{uuid.uuid4().hex[:8]}",
            "external_id": order_id,
            "amount": 249000,
            "status": "COMPLETED",
            "business_id": "xnd_biz_alpha_01",
        },
    }

    # 1. Missing token header
    res_no_tok = await process_xendit_webhook_core(payload, {})
    assert res_no_tok["http_status"] in (401, 403)
    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 0

    # 2. Invalid token
    res_bad_tok = await process_xendit_webhook_core(payload, {"x-callback-token": "wrong_invalid_token"})
    assert res_bad_tok["http_status"] in (401, 403)
    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 0

    # 3. APP_MASTER_KEY rejection
    res_master = await process_xendit_webhook_core(payload, {"x-callback-token": "app_master_key_super_secret"})
    assert res_master["http_status"] in (401, 403)
    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 0
    assert _count_ledger_entries(order_id) == 0


# =============================================================================
# S3-T02: Tampered Midtrans Signature (SHA-512)
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t02_tampered_midtrans_signature():
    order_id = f"ORD-T02-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # 1. Missing signature
    payload_nosig = {
        "order_id": order_id,
        "transaction_status": "settlement",
        "status_code": "200",
        "gross_amount": "249000.00",
        "merchant_id": "M_ALPHA_123",
    }
    res_nosig, code_nosig = await handle_midtrans_notification_logic(payload_nosig)
    assert code_nosig == 401
    assert res_nosig["error_code"] == "INVALID_WEBHOOK_SIGNATURE"
    assert _get_order_state(order_id)["status"] == "PENDING"

    # 2. Tampered signature
    payload_badsig = dict(payload_nosig)
    payload_badsig["signature_key"] = "deadbeef" * 16  # 64 hex chars of garbage
    res_badsig, code_badsig = await handle_midtrans_notification_logic(payload_badsig)
    assert code_badsig in (401, 403)
    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 0
    assert _count_ledger_entries(order_id) == 0


# =============================================================================
# S3-T03: Tampered Duitku Signature (HMAC-SHA256)
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t03_tampered_duitku_signature():
    order_id = f"ORD-T03-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # 1. Missing signature
    payload_nosig = {
        "merchantOrderId": order_id,
        "merchantCode": "D_ALPHA",
        "amount": "249000",
        "resultCode": "00",
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
    }
    res_nosig, code_nosig = await process_duitku_callback_core(payload_nosig)
    assert code_nosig in (401, 403, 404)
    assert _get_order_state(order_id)["status"] == "PENDING"

    # 2. Bad signature
    payload_badsig = dict(payload_nosig)
    payload_badsig["signature"] = "bad" * 21 + "a"  # 64 chars
    res_badsig, code_badsig = await process_duitku_callback_core(payload_badsig)
    assert code_badsig in (401, 403)
    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 0
    assert _count_ledger_entries(order_id) == 0


# =============================================================================
# S3-T04: Cross-Merchant Account Replay Rejection
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t04_cross_merchant_account_replay():
    # Order belongs to Tenant Alpha (expects M_ALPHA_123 / xnd_biz_alpha_01 / D_ALPHA)
    order_id = f"ORD-T04-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, tenant_id=TENANT_ALPHA_ID, gross_amount=249000, status="PENDING")

    # Midtrans with Tenant Beta's merchant_id (M_BETA_123)
    raw_sig_mid = f"{order_id}200249000.00{MIDTRANS_SERVER_KEY_BETA}"
    sig_mid = hashlib.sha512(raw_sig_mid.encode("utf-8")).hexdigest()
    res_mid, code_mid = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_BETA_999",  # Account B sent for Tenant A order!
        "signature_key": sig_mid,
        "transaction_id": f"tx_mid_{uuid.uuid4().hex[:6]}",
    })
    assert code_mid == 403
    assert res_mid["error_code"] == "PROVIDER_ACCOUNT_BINDING_MISMATCH"

    # Xendit with Tenant Beta's business_id (xnd_biz_beta_99)
    res_xen = await process_xendit_webhook_core({
        "event": "qr.payment",
        "business_id": "xnd_biz_beta_99",  # Account B
        "data": {
            "id": f"qr_pay_{uuid.uuid4().hex[:8]}",
            "external_id": order_id,
            "amount": 249000,
            "status": "COMPLETED",
            "business_id": "xnd_biz_beta_99",
        },
    }, {"x-callback-token": XENDIT_TOKEN_BETA})
    assert res_xen["http_status"] == 403
    assert res_xen["response"]["error_code"] in ("PROVIDER_ACCOUNT_BINDING_MISMATCH", "PROVIDER_ACCOUNT_MISMATCH", "INVALID_WEBHOOK_TOKEN")

    # Duitku with Tenant Beta's merchantCode (D_BETA)
    dk_raw = f"D_BETA249000{order_id}"
    dk_sig = hmac.new(DUITKU_API_KEY_BETA.encode("utf-8"), dk_raw.encode("utf-8"), hashlib.sha256).hexdigest()
    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": order_id,
        "merchantCode": "D_BETA",  # Account B
        "amount": "249000",
        "resultCode": "00",
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
        "signature": dk_sig,
    })
    assert code_dk == 403
    assert res_dk["error_code"] == "PROVIDER_ACCOUNT_BINDING_MISMATCH"

    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 0
    assert _count_ledger_entries(order_id) == 0


# =============================================================================
# S3-T05: Direct merchant_id == tenant_id Spoofing Rejection
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t05_direct_merchant_id_spoofing():
    order_id = f"ORD-T05-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, tenant_id=TENANT_ALPHA_ID, gross_amount=249000, status="PENDING")

    # Attacker passes tenant UUID as merchant_id
    res_mid, code_mid = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": TENANT_ALPHA_ID,  # Spoofed tenant UUID as merchant_id
        "signature_key": "some_sig",
    })
    assert code_mid in (401, 403)
    assert res_mid["error_code"] in ("PROVIDER_ACCOUNT_BINDING_MISMATCH", "INVALID_WEBHOOK_SIGNATURE")

    # Attacker passes tenant slug as merchantCode
    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": order_id,
        "merchantCode": "tenant-2b2-alpha",  # Spoofed slug
        "amount": "249000",
        "resultCode": "00",
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
        "signature": "some_sig",
    })
    assert code_dk in (401, 403)
    assert res_dk["error_code"] in ("PROVIDER_ACCOUNT_BINDING_MISMATCH", "INVALID_DUITKU_SIGNATURE")
    assert _get_order_state(order_id)["status"] == "PENDING"


# =============================================================================
# S3-T06: Payload Tenant Switching Attempt Rejection
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t06_payload_tenant_switching_attempt():
    order_id = f"ORD-T06-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, tenant_id=TENANT_ALPHA_ID, gross_amount=249000, status="PENDING")

    # Payload claims tenant_id is Tenant Beta
    res_mid, code_mid = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_ALPHA_123",
        "signature_key": "some_sig",
        "tenant_id": TENANT_BETA_ID,  # Switching attempt
    })
    assert code_mid == 403
    assert res_mid["error_code"] == "ORDER_TENANT_MISMATCH"

    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": order_id,
        "merchantCode": "D_ALPHA",
        "amount": "249000",
        "resultCode": "00",
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
        "signature": "some_sig",
        "tenant_id": TENANT_BETA_ID,  # Switching attempt
    })
    assert code_dk == 403
    assert res_dk["error_code"] == "ORDER_TENANT_MISMATCH"
    assert _get_order_state(order_id)["status"] == "PENDING"


# =============================================================================
# S3-T07: Lockdown Legacy String Parsing (TOPUP- & sub_ routes)
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t07_lockdown_legacy_topup_and_sub_routes(fastapi_client):
    # 1. TOPUP- prefixed external_id sent to Xendit webhook
    res_topup = await process_xendit_webhook_core({
        "external_id": "TOPUP-onlineboost-123",
        "amount": 50000,
        "status": "PAID",
    }, {"x-callback-token": "any_token"})
    assert res_topup["http_status"] == 403
    assert res_topup["response"]["error_code"] == "SAAS_BILLING_WEBHOOK_STAGE3_HOLD"

    # 2. FastAPI endpoint /api/v1/shop/subscriptions/webhook/xendit
    resp_sub = fastapi_client.post(
        "/api/v1/shop/subscriptions/webhook/xendit",
        json={"external_id": "sub_12345", "status": "PAID"},
    )
    assert resp_sub.status_code == 403
    assert resp_sub.json()["detail"]["error_code"] == "SAAS_BILLING_WEBHOOK_STAGE3_HOLD"


# =============================================================================
# S3-T08: Ghost Order Auto-Creation Prevention
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t08_ghost_order_auto_creation_prevention():
    ghost_order_id = f"ORD-GHOST-404-{uuid.uuid4().hex[:6]}"

    # Midtrans with valid signature format for ghost order
    res_mid, code_mid = await handle_midtrans_notification_logic({
        "order_id": ghost_order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_ALPHA_123",
        "signature_key": "some_dummy_signature",
    })
    assert code_mid in (401, 404)
    assert res_mid["error_code"] in ("ORDER_NOT_FOUND", "INVALID_WEBHOOK_SIGNATURE")

    # Xendit with ghost order
    res_xen = await process_xendit_webhook_core({
        "external_id": ghost_order_id,
        "amount": 249000,
        "status": "PAID",
    }, {"x-callback-token": XENDIT_TOKEN_ALPHA})
    assert res_xen["http_status"] == 404
    assert res_xen["response"]["error_code"] == "ORDER_NOT_FOUND"

    # Duitku with ghost order
    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": ghost_order_id,
        "merchantCode": "D_ALPHA",
        "amount": "249000",
        "resultCode": "00",
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
        "signature": "some_dummy_signature",
    })
    assert code_dk == 404
    assert res_dk["error_code"] == "ORDER_NOT_FOUND"

    # Verify zero ghost orders inserted into database
    assert _get_order_state(ghost_order_id) is None
    assert _count_payment_events(ghost_order_id) == 0


# =============================================================================
# S3-T09: Underpayment / Overpayment Amount Mismatch
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t09_amount_mismatch_underpayment_and_overpayment():
    order_id = f"ORD-T09-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # 1. Underpayment (amount = 10000 instead of 249000)
    raw_sig_under = f"{order_id}20010000.00{MIDTRANS_SERVER_KEY_ALPHA}"
    sig_under = hashlib.sha512(raw_sig_under.encode("utf-8")).hexdigest()
    res_under, code_under = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "10000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_ALPHA_123",
        "signature_key": sig_under,
        "transaction_id": f"tx_under_{uuid.uuid4().hex[:6]}",
    })
    assert code_under in (400, 422)
    assert res_under["error_code"] in ("PROVENANCE_AMOUNT_MISMATCH", "AMOUNT_MISMATCH")

    # 2. Overpayment (amount = 300000 instead of 249000)
    res_over = await process_xendit_webhook_core({
        "event": "qr.payment",
        "business_id": "xnd_biz_alpha_01",
        "data": {
            "id": f"qr_pay_{uuid.uuid4().hex[:8]}",
            "external_id": order_id,
            "amount": 300000,
            "status": "COMPLETED",
            "business_id": "xnd_biz_alpha_01",
        },
    }, {"x-callback-token": XENDIT_TOKEN_ALPHA})
    assert res_over["http_status"] in (400, 422)
    assert res_over["response"]["error_code"] in ("PROVENANCE_AMOUNT_MISMATCH", "AMOUNT_MISMATCH")

    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 0
    assert _count_ledger_entries(order_id) == 0


# =============================================================================
# S3-T10: Non-Integer / Float Amount Injection
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t10_non_integer_float_amount_injection():
    order_id = f"ORD-T10-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # Fractional float 249000.50
    res_xen = await process_xendit_webhook_core({
        "event": "qr.payment",
        "business_id": "xnd_biz_alpha_01",
        "data": {
            "id": f"qr_pay_{uuid.uuid4().hex[:8]}",
            "external_id": order_id,
            "amount": 249000.50,
            "status": "COMPLETED",
            "business_id": "xnd_biz_alpha_01",
        },
    }, {"x-callback-token": XENDIT_TOKEN_ALPHA})
    assert res_xen["http_status"] in (400, 422)
    assert res_xen["response"]["error_code"] in ("PROVENANCE_INVALID_AMOUNT", "INVALID_AMOUNT")

    # Boolean amount True
    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": order_id,
        "merchantCode": "D_ALPHA",
        "amount": True,
        "resultCode": "00",
        "reference": f"REF-{uuid.uuid4().hex[:6]}",
        "signature": "some_sig",
    })
    assert code_dk in (400, 422)
    assert res_dk["error_code"] in ("PROVENANCE_INVALID_AMOUNT", "INVALID_AMOUNT")
    assert _get_order_state(order_id)["status"] == "PENDING"


# =============================================================================
# S3-T11: Non-IDR Currency Rejection
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t11_non_idr_currency_rejection():
    order_id = f"ORD-T11-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # Midtrans with USD
    raw_sig = f"{order_id}200249000.00{MIDTRANS_SERVER_KEY_ALPHA}"
    sig = hashlib.sha512(raw_sig.encode("utf-8")).hexdigest()
    res_mid, code_mid = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_ALPHA_123",
        "currency": "USD",  # Non-IDR currency
        "signature_key": sig,
        "transaction_id": f"tx_mid_{uuid.uuid4().hex[:6]}",
    })
    assert code_mid == 422
    assert res_mid["error_code"] == "PROVENANCE_INVALID_CURRENCY"

    # Duitku with SGD
    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": order_id,
        "merchantCode": "D_ALPHA",
        "amount": "249000",
        "currency": "SGD",
        "resultCode": "00",
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
        "signature": "some_sig",
    })
    assert code_dk == 422
    assert res_dk["error_code"] == "PROVENANCE_INVALID_CURRENCY"
    assert _get_order_state(order_id)["status"] == "PENDING"


# =============================================================================
# S3-T12: Non-Final Status Callback Acknowledged Without Settlement
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t12_non_final_status_callback():
    order_id = f"ORD-T12-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # Midtrans pending status
    res_mid, code_mid = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "201",
        "gross_amount": "249000.00",
        "transaction_status": "pending",
        "signature_key": "some_sig",
    })
    assert code_mid == 200
    assert "acknowledged without settlement" in res_mid.get("message", "")
    assert _get_order_state(order_id)["status"] == "PENDING"

    # Duitku non-settled resultCode="01"
    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": order_id,
        "merchantCode": "D_ALPHA",
        "amount": "249000",
        "resultCode": "01",  # Not 00
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
        "signature": "some_sig",
    })
    assert code_dk == 200
    assert res_dk.get("status") == "ignored"
    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_ledger_entries(order_id) == 0


# =============================================================================
# S3-T13: Midtrans Capture Fraud Status Guard
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t13_midtrans_capture_fraud_status_guard():
    order_id = f"ORD-T13-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # 1. capture with fraud_status = challenge -> non-settled acknowledged (HTTP 200)
    res_chal, code_chal = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "capture",
        "fraud_status": "challenge",
        "signature_key": "some_sig",
    })
    assert code_chal == 200
    assert _get_order_state(order_id)["status"] == "PENDING"

    # 2. capture with fraud_status = "" (empty) -> non-settled acknowledged (HTTP 200)
    res_emp, code_emp = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "capture",
        "fraud_status": "",
        "signature_key": "some_sig",
    })
    assert code_emp == 200
    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 0


# =============================================================================
# S3-T14: Duitku S2S Verification Failure
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t14_duitku_s2s_verification_failure():
    order_id = f"ORD-T14-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # Injected S2S stub returns non-00 or raises error
    def _failing_s2s(req: Any) -> Dict[str, Any]:
        return {"statusCode": "02", "statusMessage": "FAILED_TRANSACTION"}

    set_duitku_s2s_verifier(_failing_s2s)

    dk_raw = f"D_ALPHA249000{order_id}"
    dk_sig = hmac.new(DUITKU_API_KEY_ALPHA.encode("utf-8"), dk_raw.encode("utf-8"), hashlib.sha256).hexdigest()

    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": order_id,
        "merchantCode": "D_ALPHA",
        "amount": "249000",
        "resultCode": "00",
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
        "signature": dk_sig,
    })
    assert code_dk == 503
    assert res_dk["error_code"] == "DUITKU_S2S_VERIFICATION_FAILED"
    assert _get_order_state(order_id)["status"] == "PENDING"
    assert _count_ledger_entries(order_id) == 0


# =============================================================================
# S3-T15: 5x Concurrent Duplicate Callback
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t15_5x_concurrent_duplicate_callback():
    order_id = f"ORD-T15-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    event_id = f"evt_xendit_{uuid.uuid4().hex[:8]}"
    payload = {
        "event": "qr.payment",
        "business_id": "xnd_biz_alpha_01",
        "data": {
            "id": event_id,
            "external_id": order_id,
            "amount": 249000,
            "status": "COMPLETED",
            "business_id": "xnd_biz_alpha_01",
        },
    }
    headers = {"x-callback-token": XENDIT_TOKEN_ALPHA}

    # Dispatch 5 identical requests concurrently
    tasks = [process_xendit_webhook_core(payload, headers) for _ in range(5)]
    results = await asyncio.gather(*tasks)

    # All must return 200 HTTP status
    for res in results:
        assert res["http_status"] == 200

    # Exactly 1 settles; 4 return ALREADY_SETTLED / ALREADY_PROCESSED
    settled_count = sum(1 for r in results if r["response"].get("status") in ("SUCCESS", "ok") and not r["response"].get("idempotent"))
    already_count = sum(1 for r in results if r["response"].get("status") in ("ALREADY_SETTLED", "ALREADY_PROCESSED", "ok") and (r["response"].get("idempotent") or r["response"].get("status") == "ALREADY_SETTLED"))
    assert settled_count == 1
    assert already_count == 4

    # DB Invariants: exactly 1 payment_events row, 1 financial_ledger row, order PAID
    assert _get_order_state(order_id)["status"] == "PAID"
    assert _count_payment_events(order_id) == 1
    assert _count_ledger_entries(order_id) == 1


# =============================================================================
# S3-T16: Conflicting Payload Replay Collision
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t16_conflicting_payload_replay_collision():
    order_id = f"ORD-T16-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    tx_id = f"tx_mid_{uuid.uuid4().hex[:8]}"
    raw_sig = f"{order_id}200249000.00{MIDTRANS_SERVER_KEY_ALPHA}"
    sig = hashlib.sha512(raw_sig.encode("utf-8")).hexdigest()

    valid_payload = {
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_ALPHA_123",
        "signature_key": sig,
        "transaction_id": tx_id,
    }

    # First delivery settles
    res1, code1 = await handle_midtrans_notification_logic(valid_payload)
    assert code1 == 200
    assert _get_order_state(order_id)["status"] == "PAID"

    # Conflicting replay: same event_id / transaction_id replayed on a different order (order_id_2)
    order_id_2 = f"ORD-T16-2-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id_2, gross_amount=249000, status="PENDING")

    raw_sig_2 = f"{order_id_2}200249000.00{MIDTRANS_SERVER_KEY_ALPHA}"
    sig_2 = hashlib.sha512(raw_sig_2.encode("utf-8")).hexdigest()

    conflicting_payload = {
        "order_id": order_id_2,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_ALPHA_123",
        "signature_key": sig_2,
        "transaction_id": tx_id,  # Replayed identical transaction_id
    }

    res2, code2 = await handle_midtrans_notification_logic(conflicting_payload)
    # Must reject with 409 Conflict
    assert code2 == 409
    assert res2["error_code"] == "CONFLICTING_PAYMENT_EVENT_REPLAY"
    assert _get_order_state(order_id)["status"] == "PAID"
    assert _get_order_state(order_id_2)["status"] == "PENDING"
    assert _count_payment_events(order_id) == 1
    assert _count_payment_events(order_id_2) == 0
    assert _count_ledger_entries(order_id) == 1
    assert _count_ledger_entries(order_id_2) == 0


# =============================================================================
# S3-T17: Late Settlement Quarantine (CTO Decision #4)
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t17_late_settlement_quarantine():
    # Order 1: EXPIRED
    order_id_exp = f"ORD-T17-EXP-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id_exp, gross_amount=249000, status="EXPIRED")

    tx_id = f"tx_late_{uuid.uuid4().hex[:8]}"
    raw_sig = f"{order_id_exp}200249000.00{MIDTRANS_SERVER_KEY_ALPHA}"
    sig = hashlib.sha512(raw_sig.encode("utf-8")).hexdigest()

    res_exp, code_exp = await handle_midtrans_notification_logic({
        "order_id": order_id_exp,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_ALPHA_123",
        "signature_key": sig,
        "transaction_id": tx_id,
    })
    # CTO Decision #4: Returns HTTP 200 acknowledged as quarantined late settlement
    assert code_exp == 200
    assert "quarantined" in str(res_exp.get("message", "")).lower()

    # Order status MUST remain EXPIRED (never mutated to PAID)
    assert _get_order_state(order_id_exp)["status"] == "EXPIRED"
    # Zero financial ledger entries created
    assert _count_ledger_entries(order_id_exp) == 0

    # Order 2: CANCELLED
    order_id_cnc = f"ORD-T17-CNC-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id_cnc, gross_amount=249000, status="CANCELLED")

    res_cnc = await process_xendit_webhook_core({
        "event": "qr.payment",
        "business_id": "xnd_biz_alpha_01",
        "data": {
            "id": f"qr_pay_{uuid.uuid4().hex[:8]}",
            "external_id": order_id_cnc,
            "amount": 249000,
            "status": "COMPLETED",
            "business_id": "xnd_biz_alpha_01",
        },
    }, {"x-callback-token": XENDIT_TOKEN_ALPHA})
    assert res_cnc["http_status"] == 200
    assert "quarantined" in str(res_cnc["response"].get("message", "")).lower()
    assert _get_order_state(order_id_cnc)["status"] == "CANCELLED"
    assert _count_ledger_entries(order_id_cnc) == 0


# =============================================================================
# S3-T18: Secret Key Rotation Lifecycle (ACTIVE, VERIFY_ONLY, REVOKED)
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t18_secret_key_rotation_lifecycle():
    order_id = f"ORD-T18-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    # Profile with VERIFY_ONLY secret
    meta_verify_only = {
        "payment_config": {
            "mode": "NATIVE_PG",
            "active_provider": "XENDIT",
            "credential_profiles": {
                "cred_xen_rot": {
                    "credential_profile_id": "cred_xen_rot",
                    "canonical_tenant_id": TENANT_ALPHA_ID,
                    "provider": "XENDIT",
                    "verification_method": "XENDIT_CALLBACK_TOKEN",
                    "expected_provider_account_id": "xnd_biz_alpha_01",
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "verification_secrets": [
                        {
                            "secret_version_id": "xnd_sec_rot_v1",
                            "secret_ref": "vault://tenants/alpha/xendit/active",
                            "status": "VERIFY_ONLY",  # Allowed during grace period
                            "not_after_epoch": int(datetime.now(timezone.utc).timestamp()) + 3600,
                        }
                    ],
                }
            },
        }
    }
    _insert_test_order(order_id, gross_amount=249000, status="PENDING", metadata={"credential_profile_id": "cred_xen_rot"})

    # Update tenant metadata temporarily with VERIFY_ONLY
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tenants SET metadata = %s WHERE id = %s", (json.dumps(meta_verify_only), TENANT_ALPHA_ID))
    conn.commit()
    cur.close()
    conn.close()

    # Valid secret under VERIFY_ONLY succeeds
    res_v = await process_xendit_webhook_core({
        "event": "qr.payment",
        "business_id": "xnd_biz_alpha_01",
        "data": {
            "id": f"qr_pay_{uuid.uuid4().hex[:8]}",
            "external_id": order_id,
            "amount": 249000,
            "status": "COMPLETED",
            "business_id": "xnd_biz_alpha_01",
        },
    }, {"x-callback-token": XENDIT_TOKEN_ALPHA})
    assert res_v["http_status"] == 200

    # Profile with REVOKED secret
    meta_revoked = dict(meta_verify_only)
    meta_revoked["payment_config"]["credential_profiles"]["cred_xen_rot"]["verification_secrets"][0]["status"] = "REVOKED"
    order_id_rev = f"ORD-T18-REV-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id_rev, gross_amount=249000, status="PENDING", metadata={"credential_profile_id": "cred_xen_rot"})

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tenants SET metadata = %s WHERE id = %s", (json.dumps(meta_revoked), TENANT_ALPHA_ID))
    conn.commit()
    cur.close()
    conn.close()

    # Revoked secret fails closed (401/403)
    res_rev = await process_xendit_webhook_core({
        "event": "qr.payment",
        "business_id": "xnd_biz_alpha_01",
        "data": {
            "id": f"qr_pay_{uuid.uuid4().hex[:8]}",
            "external_id": order_id_rev,
            "amount": 249000,
            "status": "COMPLETED",
            "business_id": "xnd_biz_alpha_01",
        },
    }, {"x-callback-token": XENDIT_TOKEN_ALPHA})
    assert res_rev["http_status"] in (401, 403)
    assert _get_order_state(order_id_rev)["status"] == "PENDING"

    # Restore tenant Alpha metadata
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tenants SET metadata = %s WHERE id = %s", (json.dumps(_make_tenant_metadata("alpha", TENANT_ALPHA_ID)), TENANT_ALPHA_ID))
    conn.commit()
    cur.close()
    conn.close()


# =============================================================================
# S3-T19: Database Outage Fail-Closed Protection
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t19_database_failure_fail_closed_guard(monkeypatch):
    order_id = f"ORD-T19-{uuid.uuid4().hex[:6]}"
    _insert_test_order(order_id, gross_amount=249000, status="PENDING")

    def _broken_get_db():
        raise psycopg2.OperationalError("Simulated database outage during settlement")

    monkeypatch.setattr("app.core.database.get_db_connection", _broken_get_db)
    monkeypatch.setattr("app.routes.payment.get_db_connection", _broken_get_db)
    monkeypatch.setattr("app.routes.duitku_routes.get_db_connection", _broken_get_db)

    # Webhook fails closed with HTTP 503 DATABASE_UNAVAILABLE
    res_mid, code_mid = await handle_midtrans_notification_logic({
        "order_id": order_id,
        "status_code": "200",
        "gross_amount": "249000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_ALPHA_123",
        "signature_key": "any_signature",
    })
    assert code_mid == 503
    assert res_mid["error_code"] == "DATABASE_UNAVAILABLE"

    res_dk, code_dk = await process_duitku_callback_core({
        "merchantOrderId": order_id,
        "merchantCode": "D_ALPHA",
        "amount": "249000",
        "resultCode": "00",
        "reference": f"DUITKU_TX_{uuid.uuid4().hex[:8]}",
        "signature": "any_signature",
    })
    assert code_dk == 503
    assert res_dk["error_code"] == "DATABASE_UNAVAILABLE"


# =============================================================================
# S3-T20: Dual-Runner Parity & Deprecated Route Lock
# =============================================================================
@pytest.mark.asyncio
async def test_s3_t20_dual_runner_parity_and_deprecated_route_lock(fastapi_client):
    # 1. FastAPI deprecated generic webhooks return 403
    for path in ("/api/v1/payments/webhook", "/api/v1/payments/callback", "/api/v1/payment/webhook"):
        r = fastapi_client.post(path, json={"order_id": "ORD-001"})
        assert r.status_code == 403
        assert "DEPRECATED_GENERIC_WEBHOOK" in str(r.json())

    # 2. aiohttp deprecated route lockdown parity
    app = web.Application()
    register_payment_routes(app)
    register_duitku_routes(app)

    async with AioTestClient(AioTestServer(app)) as aio_client:
        # DANA / Direct Tenant Rail endpoint
        r_dana = await aio_client.post("/api/payments/webhook", json={"amount": 10000})
        assert r_dana.status == 403
        d_dana = await r_dana.json()
        assert d_dana["error_code"] == "DIRECT_TENANT_RAIL_DISABLED"
