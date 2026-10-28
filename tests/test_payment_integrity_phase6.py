"""tests/test_payment_integrity_phase6.py
P0 Comprehensive Payment Integrity & Cross-Pillar Contract Verification Suite.
Validates:
1. P0-A: Studio Top-Up namespace collision prevention (never enters Shop AI quota).
2. P0-A: Studio credit top-up entitlement and ledger recording via Core StudioCreditService.
3. P0-B: Shop subscription invoices (sub_*) routed cleanly through central webhook without 404.
4. P0-C: Fail-closed constant-time callback token verification on both central and sub endpoints.
5. P0-D: Amount mismatch, unknown tenant, and sandbox guard fail-closed behavior.
6. P0-D: Idempotency replay protection for Studio and Subscriptions.
"""

import os
import uuid
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.xendit_service import xendit_service
from app.routes.xendit import process_xendit_webhook_core
from app.services.studio_credit_service import studio_credit_service

client = TestClient(app)
VALID_TOKEN = os.getenv("XENDIT_CALLBACK_TOKEN", "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS")


# =============================================================================
# 1. P0-A: Studio Top-Up Namespace Collision Prevention
# =============================================================================

@pytest.mark.asyncio
async def test_studio_topup_isolated_from_shop_quota():
    """Verify TOPUP-STUDIO-* external IDs NEVER enter quota_service.increment_session_quota."""
    external_id = f"TOPUP-STUDIO-warungkreatif-creator-50-{uuid.uuid4().hex[:6]}"
    payload = {
        "id": f"inv_studio_{uuid.uuid4().hex[:6]}",
        "external_id": external_id,
        "status": "PAID",
        "amount": 89000,
        "payment_method": "QRIS",
        "metadata": {
            "tenant_slug": "warungkreatif",
            "credits": 50,
            "package_id": "creator",
        }
    }
    headers = {"x-callback-token": VALID_TOKEN}

    mock_tenant = {
        "id": "11111111-2222-3333-4444-555555555555",
        "slug": "warungkreatif",
        "tier": "PRO_SCALE",
        "metadata": {"is_shop_member": True}
    }

    mock_supabase = MagicMock()
    # Mock tenant_credit_ledger select (idempotency check)
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    # Mock tenant_entitlements select
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"credits_remaining": 10, "is_unlimited": False, "tier": "PRO_SCALE"}]
    )
    # Mock upsert & insert
    mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "ent-1"}])
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "led-1"}])

    with patch.object(studio_credit_service, "resolve_tenant", return_value=mock_tenant), \
         patch("app.services.studio_credit_service.get_supabase", return_value=mock_supabase), \
         patch("app.services.studio_credit_service.get_db_connection") as mock_pg, \
         patch("app.services.quota_service.quota_service.increment_session_quota", new_callable=AsyncMock) as mock_quota_inc:

        # Mock Postgres connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        resp = await process_xendit_webhook_core(payload, headers)
        assert resp["http_status"] == 200
        body = resp["response"]
        assert body["status"] == "STUDIO_TOPUP_PROCESSED"
        assert body["tenant_slug"] == "warungkreatif"
        assert body["credits_added"] == 50
        assert body["new_balance"] == 60

        # CRITICAL ASSERTION: Shop quota handler was NEVER called
        mock_quota_inc.assert_not_called()


@pytest.mark.asyncio
async def test_shop_quota_topup_continues_to_credit_shop_quota():
    """Verify regular TOPUP-* (non-studio) still credits Shop AI session quota."""
    external_id = f"TOPUP-warungkreatif-100-{uuid.uuid4().hex[:6]}"
    payload = {
        "id": f"inv_quota_{uuid.uuid4().hex[:6]}",
        "external_id": external_id,
        "status": "PAID",
        "amount": 99000,
        "payment_method": "QRIS",
    }
    headers = {"x-callback-token": VALID_TOKEN}

    with patch("app.services.quota_service.quota_service.increment_session_quota", new_callable=AsyncMock) as mock_quota_inc, \
         patch.object(studio_credit_service, "process_studio_credit_topup", new_callable=AsyncMock) as mock_studio_topup:

        mock_quota_inc.return_value = {
            "status": "success",
            "tenant_slug": "warungkreatif",
            "sessions_remaining": 300,
            "sessions_added": 100,
        }

        resp = await process_xendit_webhook_core(payload, headers)
        assert resp["http_status"] == 200
        body = resp["response"]
        assert body["status"] == "TOPUP_PROCESSED"
        assert body["tenant_slug"] == "warungkreatif"
        assert body["sessions_added"] == 100

        mock_quota_inc.assert_called_once()
        mock_studio_topup.assert_not_called()


# =============================================================================
# 2. P0-B: Shop Subscription Routing via Central Webhook
# =============================================================================

@pytest.mark.asyncio
async def test_subscription_webhook_via_central_callback_succeeds():
    """Verify subscription sub_* external IDs succeed via central /api/v1/payments/xendit/callback without 404."""
    external_id = f"sub_upgrade_warungkreatif_pro_scale_{uuid.uuid4().hex[:6]}"
    payload = {
        "id": f"inv_sub_{uuid.uuid4().hex[:6]}",
        "external_id": external_id,
        "status": "PAID",
        "amount": 50000,
        "metadata": {
            "type": "SUBSCRIPTION_UPGRADE",
            "is_upgrade": True,
            "tenant_slug": "warungkreatif",
            "plan_tier": "pro_scale",
            "new_valid_until": "2026-12-31T23:59:59+00:00",
        }
    }
    headers = {"x-callback-token": VALID_TOKEN}

    mock_supabase = MagicMock()
    def mock_table(name):
        t = MagicMock()
        if name in ("merchants", "tenants"):
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "m-1", "slug": "warungkreatif"}])
        elif name == "shop_subscriptions":
            t.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            t.insert.return_value.execute.return_value = MagicMock(data=[{"id": "sub-1"}])
        t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "m-1"}])
        return t
    mock_supabase.table.side_effect = mock_table

    with patch("app.services.subscription_service.get_supabase", return_value=mock_supabase), \
         patch("app.routes.shop_subscription_routes.get_supabase", return_value=mock_supabase):

        resp = await process_xendit_webhook_core(payload, headers)
        assert resp["http_status"] == 200
        body = resp["response"]
        assert body["status"] == "success"
        assert body["tenant_slug"] == "warungkreatif"
        assert body["plan_tier"] == "pro_scale"
        assert body["is_upgrade"] is True


# =============================================================================
# 3. P0-C: Fail-Closed Callback Token Verification
# =============================================================================

def test_central_webhook_unauthenticated_rejected():
    """Verify invalid token on /api/v1/payments/xendit/callback returns 403 UNAUTHORIZED."""
    resp = client.post(
        "/api/v1/payments/xendit/callback",
        json={"id": "evt_fake", "external_id": "ORD-123", "status": "PAID"},
        headers={"x-callback-token": "WRONG_TOKEN"}
    )
    assert resp.status_code == 403
    detail = resp.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("error") == "Invalid callback token"
    else:
        assert detail == "Invalid callback token"


def test_subscription_webhook_unauthenticated_rejected():
    """Verify invalid token on /api/v1/shop/subscriptions/webhook/xendit returns 403."""
    resp = client.post(
        "/api/v1/shop/subscriptions/webhook/xendit",
        json={"id": "evt_fake", "external_id": "sub_test", "status": "PAID"},
        headers={"x-callback-token": "WRONG_TOKEN"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Invalid callback token"


def test_subscription_webhook_missing_token_rejected():
    """Verify missing token on /api/v1/shop/subscriptions/webhook/xendit returns 403."""
    resp = client.post(
        "/api/v1/shop/subscriptions/webhook/xendit",
        json={"id": "evt_fake", "external_id": "sub_test", "status": "PAID"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Invalid callback token"


# =============================================================================
# 4. P0-D: Validation & Fail-Closed Guards (Amount, Tenant, Sandbox)
# =============================================================================

@pytest.mark.asyncio
async def test_studio_topup_amount_mismatch_rejected():
    """Verify Studio top-up with unexpected amount is rejected with 400 AMOUNT_MISMATCH."""
    external_id = f"TOPUP-STUDIO-warungkreatif-creator-50-{uuid.uuid4().hex[:6]}"
    payload = {
        "id": f"inv_studio_{uuid.uuid4().hex[:6]}",
        "external_id": external_id,
        "status": "PAID",
        "amount": 10000,  # Invalid price for creator 50 package
    }
    headers = {"x-callback-token": VALID_TOKEN}

    mock_tenant = {
        "id": "11111111-2222-3333-4444-555555555555",
        "slug": "warungkreatif",
        "tier": "PRO_SCALE",
        "metadata": {"is_shop_member": True}
    }

    with patch.object(studio_credit_service, "resolve_tenant", return_value=mock_tenant):
        resp = await process_xendit_webhook_core(payload, headers)
        assert resp["http_status"] == 400
        assert resp["response"]["status"] == "AMOUNT_MISMATCH"


@pytest.mark.asyncio
async def test_studio_topup_sandbox_tenant_rejected():
    """Verify Studio top-up with sandbox tenant 'creator' or 'sandbox' fails closed."""
    external_id = f"TOPUP-STUDIO-creator-50-{uuid.uuid4().hex[:6]}"
    payload = {
        "id": f"inv_studio_{uuid.uuid4().hex[:6]}",
        "external_id": external_id,
        "status": "PAID",
        "amount": 89000,
    }
    headers = {"x-callback-token": VALID_TOKEN}

    resp = await process_xendit_webhook_core(payload, headers)
    assert resp["http_status"] == 400
    assert resp["response"]["status"] == "TENANT_NOT_FOUND"


@pytest.mark.asyncio
async def test_studio_topup_idempotency_prevents_double_credit():
    """Verify duplicate webhook for Studio top-up returns ALREADY_PROCESSED and credits 0."""
    external_id = f"TOPUP-STUDIO-warungkreatif-creator-50-{uuid.uuid4().hex[:6]}"
    payload = {
        "id": f"inv_studio_{uuid.uuid4().hex[:6]}",
        "external_id": external_id,
        "status": "PAID",
        "amount": 89000,
    }
    headers = {"x-callback-token": VALID_TOKEN}

    mock_tenant = {
        "id": "11111111-2222-3333-4444-555555555555",
        "slug": "warungkreatif",
        "tier": "PRO_SCALE",
        "metadata": {"is_shop_member": True}
    }

    mock_supabase = MagicMock()
    # Simulate already processed in tenant_credit_ledger
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": "led-exist", "amount": 50, "balance_after": 80}]
    )

    with patch.object(studio_credit_service, "resolve_tenant", return_value=mock_tenant), \
         patch("app.services.studio_credit_service.get_supabase", return_value=mock_supabase):

        resp = await process_xendit_webhook_core(payload, headers)
        assert resp["http_status"] == 200
        body = resp["response"]
        assert body["status"] == "ALREADY_PROCESSED"
        assert body["idempotent"] is True
        assert body["credits_added"] == 0
        assert body["new_balance"] == 80


# =============================================================================
# 5. OnlineBoost Strict Payment Hold Preservation
# =============================================================================

@pytest.mark.asyncio
async def test_onlineboost_strict_hold_blocks_qris_generation():
    """Verify OnlineBoost STRICT HOLD remains active and prevents QRIS creation."""
    from app.services.academy_service import generate_fast_path_xendit_qris_batch1, is_onlineboost_payment_held

    # Ensure ONLINEBOOST_PAYMENT_STRICT_HOLD is active
    with patch.dict(os.environ, {"ONLINEBOOST_PAYMENT_STRICT_HOLD": "true"}):
        assert is_onlineboost_payment_held() is True
        res = await generate_fast_path_xendit_qris_batch1(
            customer_phone="628123456789",
            customer_name="Budi",
            customer_email="budi@example.com"
        )
        assert res["strict_hold"] is True
        assert res["status"] == "STRICT_HOLD"
        assert res["order_id"] is None
        assert res["qr_string"] == ""
        assert "strict hold" in res["message"].lower()
