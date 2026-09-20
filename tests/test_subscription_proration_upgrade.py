import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.subscription_service import (
    calculate_upgrade_proration,
    normalize_tier_name,
    get_tier_base_price,
    create_subscription_invoice,
    process_successful_subscription,
    ProrationResult,
)
from app.routes.shop_subscription_routes import (
    create_subscription_logic,
    handle_xendit_subscription_webhook_logic,
    CreateSubPayload,
)

client = TestClient(app)


def test_normalize_tier_name_and_pricing():
    assert normalize_tier_name("solo") == "STARTER"
    assert normalize_tier_name("growth") == "STARTER"
    assert normalize_tier_name("starter") == "STARTER"
    assert normalize_tier_name("pro_scale") == "PRO_SCALE"
    assert normalize_tier_name("ads_performance") == "PRO_SCALE"
    assert normalize_tier_name("team_scale") == "ENTERPRISE"
    assert normalize_tier_name("enterprise") == "ENTERPRISE"
    assert normalize_tier_name("free") == "FREE"
    assert normalize_tier_name(None) == "FREE"

    assert get_tier_base_price("STARTER") == 199000
    assert get_tier_base_price("PRO_SCALE") == 299000
    assert get_tier_base_price("ENTERPRISE") == 499000
    assert get_tier_base_price("FREE") == 0


def test_trial_and_free_tier_proration():
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    
    # 1. Trial tenant
    res_trial = calculate_upgrade_proration(
        tenant_id="tenant_trial_1",
        target_tier="PRO_SCALE",
        current_tier="FREE",
        status="TRIAL",
        valid_until=None,
        now=now
    )
    assert res_trial["current_tier"] == "FREE"
    assert res_trial["target_tier"] == "PRO_SCALE"
    assert res_trial["days_remaining"] == 0
    assert res_trial["credit_amount"] == 0
    assert res_trial["new_tier_cost"] == 299000
    assert res_trial["final_upgrade_amount"] == 299000
    assert res_trial["new_valid_until"] == (now + timedelta(days=30)).isoformat()

    # 2. None tier with pending status
    res_none = calculate_upgrade_proration(
        tenant_id="tenant_none",
        target_tier="STARTER",
        current_tier=None,
        status="PENDING_PAYMENT",
        valid_until=None,
        now=now
    )
    assert res_none["days_remaining"] == 0
    assert res_none["credit_amount"] == 0
    assert res_none["final_upgrade_amount"] == 199000


def test_starter_to_pro_scale_active_proration():
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    valid_until = now + timedelta(days=15)

    res = calculate_upgrade_proration(
        tenant_id="tenant_starter",
        target_tier="PRO_SCALE",
        current_tier="STARTER",
        status="ACTIVE",
        valid_until=valid_until,
        now=now
    )
    assert res["current_tier"] == "STARTER"
    assert res["target_tier"] == "PRO_SCALE"
    assert res["days_remaining"] == 15
    # credit = round((15/30) * 199000) = 99500
    assert res["credit_amount"] == 99500
    # new_cost = round((15/30) * 299000) = 149500
    assert res["new_tier_cost"] == 149500
    # upgrade_amount = max(10000, 149500 - 99500) = 50000
    assert res["final_upgrade_amount"] == 50000
    assert res["new_valid_until"] == valid_until.isoformat()


def test_starter_to_enterprise_proration():
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    valid_until = now + timedelta(days=20)

    res = calculate_upgrade_proration(
        tenant_id="tenant_starter",
        target_tier="ENTERPRISE",
        current_tier="STARTER",
        status="ACTIVE",
        valid_until=valid_until,
        now=now
    )
    assert res["current_tier"] == "STARTER"
    assert res["target_tier"] == "ENTERPRISE"
    assert res["days_remaining"] == 20
    # credit = round((20/30) * 199000) = 132667
    assert res["credit_amount"] == 132667
    # new_cost = round((20/30) * 499000) = 332667
    assert res["new_tier_cost"] == 332667
    # upgrade_amount = max(10000, 332667 - 132667) = 200000
    assert res["final_upgrade_amount"] == 200000
    assert res["new_valid_until"] == valid_until.isoformat()


def test_gateway_minimum_transaction_guard():
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    # 1 day remaining: credit=6633, new_cost=9967, diff=3334 < 10000
    valid_until = now + timedelta(days=1)

    res = calculate_upgrade_proration(
        tenant_id="tenant_min",
        target_tier="PRO_SCALE",
        current_tier="STARTER",
        status="ACTIVE",
        valid_until=valid_until,
        now=now
    )
    assert res["days_remaining"] == 1
    assert res["credit_amount"] == 6633
    assert res["new_tier_cost"] == 9967
    # Must clamp to gateway minimum Rp 10.000
    assert res["final_upgrade_amount"] == 10000
    assert res["new_valid_until"] == valid_until.isoformat()


@pytest.mark.asyncio
async def test_dual_sync_and_async_awaitable():
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    valid_until = now + timedelta(days=10)

    # Sync access
    sync_res = calculate_upgrade_proration("t1", "PRO_SCALE", current_tier="STARTER", status="ACTIVE", valid_until=valid_until, now=now)
    assert isinstance(sync_res, dict)
    assert sync_res["days_remaining"] == 10

    # Async access with await
    async_res = await calculate_upgrade_proration("t1", "PRO_SCALE", current_tier="STARTER", status="ACTIVE", valid_until=valid_until, now=now)
    assert isinstance(async_res, dict)
    assert async_res["days_remaining"] == 10
    assert async_res["final_upgrade_amount"] == sync_res["final_upgrade_amount"]


def test_preview_upgrade_fastapi_endpoint():
    # 1. Call /api/v1/subscription/preview-upgrade
    response = client.get("/api/v1/subscription/preview-upgrade?target_tier=PRO_SCALE&tenant=onlineboost")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "target_tier" in data
    assert data["target_tier"] == "PRO_SCALE"
    assert "final_upgrade_amount" in data
    assert "credit_amount" in data
    assert "days_remaining" in data

    # 2. Call /api/v1/shop/subscriptions/preview-upgrade
    resp_shop = client.get("/api/v1/shop/subscriptions/preview-upgrade?target_tier=ENTERPRISE&tenant=onlineboost")
    assert resp_shop.status_code == 200
    shop_data = resp_shop.json()
    assert shop_data["target_tier"] == "ENTERPRISE"


@pytest.mark.asyncio
async def test_create_subscription_invoice_upgrade_mode():
    payload = CreateSubPayload(
        tenant_slug="test-upgrade-store",
        plan_tier="PRO_SCALE",
        customer_email="merchant@boontrack.com",
        is_upgrade=True
    )

    with patch("app.services.subscription_service.calculate_upgrade_proration") as mock_calc:
        mock_calc.return_value = ProrationResult({
            "current_tier": "STARTER",
            "target_tier": "PRO_SCALE",
            "days_remaining": 15,
            "credit_amount": 99500,
            "new_tier_cost": 149500,
            "final_upgrade_amount": 50000,
            "new_valid_until": "2026-10-04T12:00:00+00:00"
        })

        res = await create_subscription_logic(payload)
        assert res["status"] == "success"
        assert res["amount"] == 50000
        assert res["is_upgrade"] is True
        assert res["external_id"].startswith("sub_upgrade_")
        assert res["proration"]["final_upgrade_amount"] == 50000


@pytest.mark.asyncio
async def test_webhook_upgrade_preserves_valid_until():
    fixed_valid_until = "2026-10-15T12:00:00+00:00"
    mock_payload = {
        "status": "PAID",
        "amount": 50000,
        "external_id": "sub_upgrade_teststore_pro_scale_123456",
        "metadata": {
            "type": "SUBSCRIPTION_UPGRADE",
            "is_upgrade": True,
            "tenant_slug": "teststore",
            "plan_tier": "pro_scale",
            "new_valid_until": fixed_valid_until
        }
    }

    mock_supabase = MagicMock()
    # Mock shop_subscriptions insert
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "sub-123"}])
    # Mock merchants update
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "m-123"}])
    # Mock tenants select and update
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{
        "subscription_ends_at": fixed_valid_until,
        "metadata": {"plan_tier": "STARTER", "subscription_ends_at": fixed_valid_until}
    }])

    with patch("app.services.subscription_service.get_supabase", return_value=mock_supabase):
        res, status_code = await handle_xendit_subscription_webhook_logic(mock_payload)
        assert status_code == 200
        assert res["status"] == "success"
        assert res["plan_tier"] == "pro_scale"
        assert res["canonical_tier"] == "PRO_SCALE"
        assert res["is_upgrade"] is True
        # Pastikan valid_until TETAP (Preserved), TIDAK DIMAJUKAN 30 hari dari now!
        assert res["valid_until"] == fixed_valid_until
