"""test_quota_and_xendit_topup.py
Unit and Integration tests for:
1. Quota Service: 24-hour session windowing and atomic decrement/increment
2. Xendit Official Webhook: TOPUP external_id handling
3. Omnichannel Support Router: Mode VIP greeting and 'Paket Terima Beres' upsell
"""

import os
import sys
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app.services.quota_service import QuotaService, quota_service
from app.services.official_support_router import (
    find_tenant_by_admin_phone_or_text,
    handle_official_support_vip_upsell,
)
from app.routes.xendit import process_xendit_webhook_core


@pytest.mark.asyncio
async def test_session_window_24h():
    """Verify unique phone 24h window tracking per tenant."""
    qs = QuotaService()
    phone = "6281234567890"
    tenant = "onlineboost"

    # Initially not active
    assert not qs.is_session_active(tenant, phone)

    # Mark active
    qs.mark_session_active(tenant, phone)
    assert qs.is_session_active(tenant, phone)


@pytest.mark.asyncio
async def test_decrement_session_quota_logic():
    """Verify decrement updates tenant metadata."""
    qs = QuotaService()
    fake_client = MagicMock()

    fake_tenant = {
        "id": "tenant-123",
        "slug": "onlineboost",
        "tier": "PRO_SCALE",
        "metadata": {
            "sessions_remaining": 300,
            "ai_sessions_used": 0,
        },
    }

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.maybe_single.return_value = mock_query
    mock_query.execute.return_value = MagicMock(data=fake_tenant)
    mock_query.update.return_value = mock_query
    mock_query.upsert.return_value = mock_query

    fake_client.from_.return_value = mock_query

    with patch("app.services.quota_service.get_supabase", return_value=fake_client):
        # Clear any window state
        qs._windows.clear() if hasattr(qs, "_windows") else None

        res = await qs.decrement_session_quota_if_eligible("onlineboost", "6289998887771")
        assert res is not None
        assert res["status"] == "decremented"
        assert res["remaining_sessions"] == 299
        assert res["used_sessions"] == 1


@pytest.mark.asyncio
async def test_increment_session_quota_logic():
    """Verify topup increment updates tenant metadata."""
    qs = QuotaService()
    fake_client = MagicMock()

    fake_tenant = {
        "id": "tenant-123",
        "slug": "onlineboost",
        "tier": "PRO_SCALE",
        "metadata": {
            "sessions_remaining": 50,
            "ai_sessions_used": 250,
            "overage_sessions": 0,
        },
    }

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.maybe_single.return_value = mock_query
    mock_query.execute.return_value = MagicMock(data=fake_tenant)
    mock_query.update.return_value = mock_query
    mock_query.insert.return_value = mock_query
    mock_query.upsert.return_value = mock_query

    fake_client.from_.return_value = mock_query

    with patch("app.services.quota_service.get_supabase", return_value=fake_client):
        res = await qs.increment_session_quota(
            tenant_slug="onlineboost",
            additional_sessions=100,
            invoice_id="inv_test_123",
            package_id="topup_100",
            amount_paid=99000,
        )
        assert res["status"] == "success"
        assert res["new_remaining_sessions"] == 150
        assert res["sessions_added"] == 100


@pytest.mark.asyncio
async def test_official_support_vip_upsell_router():
    """Verify Mode VIP greeting and Paket Terima Beres response."""
    with patch("app.services.official_support_router.find_tenant_by_admin_phone_or_text", new_callable=AsyncMock) as mock_find:
        mock_find.return_value = {
            "slug": "onlineboost",
            "name": "OnlineBoost Official Store",
            "metadata": {
                "owner_name": "Aldi",
                "merchant_name": "Aldi",
            }
        }

        text = "Halo Tim IT BoonTrack, saya pemilik toko onlineboost ingin dibantu Setup Toko Terima Beres"
        res = await handle_official_support_vip_upsell(
            incoming_text=text,
            sender_phone="6281237450222",
        )

        assert res is not None
        reply = res.get("reply_text", "")
        assert "Aldi" in reply
        assert "OnlineBoost Official Store" in reply
        assert "Terima Beres" in reply
        assert "15 SKU" in reply
        assert "Rp 149.000" in reply
        assert "Dynamic QRIS BCA" in reply


@pytest.mark.asyncio
async def test_xendit_topup_webhook_processing():
    """Verify Xendit webhook handling for TOPUP- external_id."""
    payload = {
        "id": "inv_topup_test_999",
        "external_id": "TOPUP-onlineboost-100-1727620000",
        "status": "PAID",
        "amount": 99000,
        "payment_method": "QRIS",
    }
    headers = {"x-callback-token": "test-token"}

    mock_webhook_val = MagicMock(
        is_valid=True,
        amount=99000,
        order_id="TOPUP-onlineboost-100-1727620000",
        status="SUCCESS",
        message="Valid callback token",
    )

    with patch("app.routes.xendit._adapter.handle_webhook", new_callable=AsyncMock) as mock_auth, \
         patch("app.services.quota_service.quota_service.increment_session_quota", new_callable=AsyncMock) as mock_inc:
        mock_auth.return_value = mock_webhook_val
        mock_inc.return_value = {
            "status": "success",
            "tenant_slug": "onlineboost",
            "sessions_remaining": 400,
            "sessions_added": 100,
        }

        res = await process_xendit_webhook_core(payload, headers)
        assert res["http_status"] == 200
        body = res["response"]
        assert body["status"] == "TOPUP_PROCESSED"
        assert body["tenant_slug"] == "onlineboost"
        assert body["sessions_added"] == 100
        mock_inc.assert_called_once_with(
            tenant_slug="onlineboost",
            additional_sessions=100,
            invoice_id="inv_topup_test_999",
            package_id="topup_100",
            amount_paid=99000,
        )
