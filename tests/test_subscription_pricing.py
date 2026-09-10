import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.services.subscription_service import (
    PLAN_PRICING,
    TIER_PRICING,
    get_plan_pricing,
    create_subscription_invoice,
    process_successful_subscription,
)

client = TestClient(app)


def test_plan_pricing_mapping():
    """Validasi konstanta harga paket langganan."""
    assert PLAN_PRICING["solo"] == 199000
    assert PLAN_PRICING["ads_performance"] == 299000
    assert PLAN_PRICING["team_scale"] == 499000
    # Synonyms / legacy aliases
    assert PLAN_PRICING["growth"] == 199000
    assert PLAN_PRICING["growth_tracking"] == 299000
    assert PLAN_PRICING["pro_scale"] == 499000
    # Backward compatibility
    assert TIER_PRICING == PLAN_PRICING


def test_get_plan_pricing_resolution():
    """Validasi fungsi kalkulasi harga untuk berbagai variasi input."""
    assert get_plan_pricing("solo") == 199000
    assert get_plan_pricing("SOLO") == 199000
    assert get_plan_pricing("ads_performance") == 299000
    assert get_plan_pricing("ADS_PERFORMANCE") == 299000
    assert get_plan_pricing("Ads Performance") == 299000
    assert get_plan_pricing("ads-performance") == 299000
    assert get_plan_pricing("team_scale") == 499000
    assert get_plan_pricing("Team Scale") == 499000
    # Fallback to amount if tier is unknown
    assert get_plan_pricing("custom_enterprise", 799000) == 799000
    # Default fallback
    assert get_plan_pricing("unknown_tier") == 199000


@pytest.mark.asyncio
async def test_create_subscription_invoice_ads_performance_amount():
    """Uji create_subscription_invoice mengirimkan amount 299000 ke Xendit untuk Ads Performance."""
    mock_post = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": "xnd_inv_mock_ads",
        "invoice_url": "https://checkout.xendit.co/web/xnd_inv_mock_ads"
    }

    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_http_post:
        with patch("app.services.subscription_service.get_supabase", return_value=None):
            result = await create_subscription_invoice(
                tenant_slug="sandbox-store",
                plan_tier="ads_performance",
                customer_email="owner@store.com"
            )

            assert result["status"] == "success"
            assert result["amount"] == 299000
            assert result["plan_tier"] == "ads_performance"

            # Periksa payload yang dikirim ke Xendit
            mock_http_post.assert_called_once()
            call_kwargs = mock_http_post.call_args.kwargs
            sent_payload = call_kwargs["json"]
            assert sent_payload["amount"] == 299000
            assert sent_payload["payment_methods"] == ["QRIS"]
            assert sent_payload["metadata"]["plan_tier"] == "ads_performance"
            assert sent_payload["metadata"]["amount"] == 299000
            assert "ads_performance" in sent_payload["external_id"]


@pytest.mark.asyncio
async def test_process_successful_subscription_split():
    """Uji perhitungan komisi untuk paket Ads Performance (299.000)."""
    mock_supabase = MagicMock()
    mock_sub_insert = MagicMock()
    mock_sub_insert.insert.return_value.execute.return_value.data = [{"id": "sub-123"}]
    mock_supabase.table.return_value = mock_sub_insert

    with patch("app.services.subscription_service.get_supabase", return_value=mock_supabase):
        result = await process_successful_subscription(
            tenant_slug="toko-budi",
            plan_tier="ads_performance",
            xendit_invoice_id="sub_toko-budi_ads_performance_123",
            affiliate_id="aff-456",
            am_id="am-789"
        )

        assert result["status"] == "success"
        assert result["gross_amount"] == 299000
        # Split rule: 25% affiliate (74750), 5% AM (14950), 70% platform (209300)
        split = result["split_ledger"]
        assert split["affiliate_share"] == int(299000 * 0.25)
        assert split["am_share"] == int(299000 * 0.05)
        assert split["platform_net_70_percent"] == 299000 - split["affiliate_share"] - split["am_share"]


def test_api_create_subscription_endpoint():
    """Uji endpoint API /api/v1/shop/subscriptions/create dengan payload Ads Performance."""
    with patch("app.routes.shop_subscription_routes.create_subscription_invoice") as mock_invoice:
        mock_invoice.return_value = {
            "status": "success",
            "tenant_slug": "tokokeren",
            "plan_tier": "ads_performance",
            "amount": 299000,
            "invoice_url": "https://checkout.xendit.co/web/test",
            "external_id": "sub_tokokeren_ads_performance_123"
        }
        with patch("app.routes.shop_subscription_routes.get_supabase", return_value=None):
            resp = client.post(
                "/api/v1/shop/subscriptions/create",
                json={
                    "tenant_slug": "tokokeren",
                    "plan_tier": "ads_performance",
                    "amount": 299000,
                    "merchant_name": "Pak Budi",
                    "merchant_phone": "08123456789",
                    "customer_email": "budi@example.com"
                }
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert data["amount"] == 299000
            assert data["plan_tier"] == "ads_performance"

            # Pastikan amount diteruskan ke create_subscription_invoice
            mock_invoice.assert_called_once()
            call_kwargs = mock_invoice.call_args.kwargs
            assert call_kwargs["plan_tier"] == "ads_performance"
            assert call_kwargs["amount"] == 299000
