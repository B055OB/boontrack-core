"""tests/test_tenant_waba_resolution.py
Unit tests verifying WABA phone number ID resolution for TrafficSplitter and TenantContextResolver.
Tests verify:
1. Direct physical column lookup: .eq("waba_phone_number_id", str(phone_id))
2. JSONB containment filter: .contains("metadata", {"waba_phone_number_id": str(phone_id)})
3. Fallback when metadata contains {"phone_number_id": str(phone_id)}
4. TrafficSplitter dispatch: ensures event is routed to TenantWebhookRouter and NOT dropped.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.tenant_context_resolver import (
    tenant_context_resolver,
    TenantRuntimeContext,
)
from app.whatsapp.traffic_splitter import TrafficSplitter


@pytest.mark.asyncio
async def test_resolve_by_physical_column_waba_phone_number_id():
    """Memverifikasi resolusi tenant via kolom fisik waba_phone_number_id: .eq('waba_phone_number_id', phone_id)."""
    test_phone_id = "1365099988877766"
    tenant_context_resolver.clear_cache()

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "11111111-2222-3333-4444-555555555555",
            "name": "Physical Column Merchant",
            "slug": "physical-merchant",
            "waba_phone_number_id": test_phone_id,
            "status": "active",
            "metadata": {
                "name": "Physical Column Merchant",
            }
        }]
    )

    with patch("app.services.tenant_context_resolver.get_supabase", return_value=mock_supabase):
        ctx = await tenant_context_resolver.resolve_by_phone_number_id(test_phone_id, force_refresh=True)
        assert ctx is not None
        assert ctx.slug == "physical-merchant"
        assert ctx.name == "Physical Column Merchant"
        mock_supabase.table.assert_called_with("tenants")
        mock_supabase.table().select().eq.assert_called_with("waba_phone_number_id", test_phone_id)


@pytest.mark.asyncio
async def test_resolve_by_jsonb_contains_waba_phone_number_id():
    """Memverifikasi resolusi tenant via JSONB filter: .contains('metadata', {'waba_phone_number_id': phone_id})."""
    test_phone_id = "1365011122233344"
    tenant_context_resolver.clear_cache()

    mock_supabase = MagicMock()
    # Physical column returns empty list
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    # JSONB contains returns matching tenant
    mock_supabase.table.return_value.select.return_value.contains.return_value.execute.return_value = MagicMock(
        data=[{
            "id": "22222222-3333-4444-5555-666666666666",
            "name": "JSONB Merchant",
            "slug": "jsonb-merchant",
            "status": "active",
            "metadata": {
                "name": "JSONB Merchant",
                "waba_phone_number_id": test_phone_id,
            }
        }]
    )

    with patch("app.services.tenant_context_resolver.get_supabase", return_value=mock_supabase):
        ctx = await tenant_context_resolver.resolve_by_phone_number_id(test_phone_id, force_refresh=True)
        assert ctx is not None
        assert ctx.slug == "jsonb-merchant"
        mock_supabase.table().select().contains.assert_called_with(
            "metadata", {"waba_phone_number_id": test_phone_id}
        )


@pytest.mark.asyncio
async def test_traffic_splitter_routes_resolved_tenant_without_dropping():
    """
    Memverifikasi bahwa TrafficSplitter berhasil me-route pesan masuk ke TenantWebhookRouter
    ketika tenant di-resolve via waba_phone_number_id, dan tidak memicu 'Dropping event for unknown phone_id'.
    """
    test_phone_id = "1365077788899900"
    tenant_context_resolver.clear_cache()

    mock_ctx = TenantRuntimeContext(
        tenant_id="33333333-4444-5555-6666-777777777777",
        slug="kopi-nusantara",
        name="Kopi Nusantara",
        business_type="PHYSICAL",
        metadata={"name": "Kopi Nusantara"}
    )

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_TEST_ENTRY",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": test_phone_id,
                        "display_phone_number": "6281234567890",
                    },
                    "contacts": [{"wa_id": "62899998888", "profile": {"name": "Customer"}}],
                    "messages": [{
                        "from": "62899998888",
                        "id": "wamid.TEST_RESOLVED_WABA_01",
                        "timestamp": "1741360000",
                        "type": "text",
                        "text": {"body": "Halo mau beli biji kopi"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.whatsapp.traffic_splitter.TenantWebhookRouter.handle", new_callable=AsyncMock) as mock_tenant_handle:
        
        mock_resolve.return_value = mock_ctx
        mock_tenant_handle.return_value = {"status": "success", "tenant": "kopi-nusantara"}

        status_code, response, trace = await TrafficSplitter.split_and_dispatch(payload)

        assert status_code == 200
        assert trace.route_type == "TENANT_SALES"
        assert trace.target_tenant == "kopi-nusantara"
        mock_tenant_handle.assert_called_once()
        assert response.get("status") == "success"


@pytest.mark.asyncio
async def test_tenant_cache_refresh_handler():
    """Memverifikasi endpoint /api/v1/system/cache/refresh melakukan clear cache dan diagnostic probe."""
    import json
    from aiohttp.test_utils import make_mocked_request
    from app.api.endpoints.health import tenant_cache_refresh_handler

    req = make_mocked_request("GET", "/api/v1/system/cache/refresh?phone_number_id=541699802061762&slug=onlineboost")

    mock_ctx = TenantRuntimeContext(
        tenant_id="e12acd29-6c18-487b-ade7-5422878c1c36",
        slug="onlineboost",
        name="OnlineBoost ID",
        business_type="PHYSICAL",
        metadata={"waba_phone_number_id": "541699802061762"}
    )
    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_res_ctx, \
         patch("app.services.tenant_resolver.resolve_tenant_by_phone_number_id", new_callable=AsyncMock) as mock_res_waba, \
         patch("app.services.tenant_resolver.async_clear_tenant_cache", new_callable=AsyncMock):
        mock_res_ctx.return_value = mock_ctx
        mock_res_waba.return_value = {"tenant_id": "onlineboost", "waba_phone_number_id": "541699802061762", "is_active": True}

        resp = await tenant_cache_refresh_handler(req)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["status"] == "success"
        assert body["cache_flushed"]["tenant_context_resolver_l1"] is True
        assert body["target_probed"]["phone_number_id"] == "541699802061762"
        assert body["target_probed"]["tenant_context_resolver"]["resolved"] is True
        assert body["target_probed"]["tenant_resolver"]["tenant_id"] == "onlineboost"

