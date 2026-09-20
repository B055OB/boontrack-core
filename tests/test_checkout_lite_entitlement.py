"""
tests/test_checkout_lite_entitlement.py
=======================================
Unit test suite untuk Plan Entitlement Matrix & Guard Enforcement CHECKOUT_LITE:
1. Konfigurasi Plan & Pricing (Rp 59.000 / bulan, canonical normalization).
2. Verifikasi capability & constraint CHECKOUT_LITE:
   - storefront.single_page = true
   - products.max_active = 3
   - orders.basic = true
   - payment.qris = true
   - checkout.digital = true
   - checkout.physical = true
   - shipping.basic = true (max 1 courier provider)
   - tracking.meta = true (Client-side Pixel)
   - tracking.capi = false (Strictly NO CAPI)
   - analytics.advanced = false
   - multi_user = false
   - broadcast = false
3. Guard Enforcement HTTP 403 FEATURE_NOT_ENTITLED pada route terlarang:
   - GET /api/v1/analytics/campaigns (Advanced Analytics)
   - POST /api/v1/broadcast/meta/send-template (WABA Broadcast)
4. Verifikasi tenant berhak (onlineboost) tetap dapat mengakses HTTP 200.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.subscription_service import (
    PLAN_PRICING,
    normalize_tier_name,
    get_tier_base_price,
)
from app.services.entitlement_service import (
    TenantContextResolver,
    tenant_context_resolver,
    _PLAN_DEFAULTS,
)
from app.services.campaign_analytics_service import campaign_analytics_service


@pytest.fixture(scope="module")
def client():
    campaign_analytics_service.seed_onlineboost_demo_data()
    return TestClient(app)


def test_checkout_lite_pricing_and_tier_normalization():
    """1. Memverifikasi harga bulanan Rp 59.000 dan canonical normalization CHECKOUT_LITE."""
    # Pricing configuration
    assert PLAN_PRICING["checkout_lite"] == 59000
    assert PLAN_PRICING["checkoutlite"] == 59000
    assert PLAN_PRICING["lite"] == 59000

    # Base price getter
    assert get_tier_base_price("CHECKOUT_LITE") == 59000
    assert get_tier_base_price("checkout_lite") == 59000
    assert get_tier_base_price("checkout-lite") == 59000
    assert get_tier_base_price("lite") == 59000

    # Normalization
    assert normalize_tier_name("checkout_lite") == "CHECKOUT_LITE"
    assert normalize_tier_name("checkout-lite") == "CHECKOUT_LITE"
    assert normalize_tier_name("CHECKOUT_LITE") == "CHECKOUT_LITE"
    assert normalize_tier_name("lite") == "CHECKOUT_LITE"


def test_checkout_lite_matrix_defaults_and_constraints():
    """2. Memverifikasi default matrix entitlement dan batasan operasional CHECKOUT_LITE."""
    matrix = _PLAN_DEFAULTS["CHECKOUT_LITE"]
    caps = matrix["capabilities"]
    limits = matrix["limits"]

    # Capabilities diizinkan
    assert caps["single_page"] is True
    assert caps["storefront"]["single_page"] is True
    assert caps["products"]["max_active"] == 3
    assert caps["orders_detail"]["basic"] is True
    assert caps["payment"]["qris"] is True
    assert caps["checkout"]["digital"] is True
    assert caps["checkout"]["physical"] is True
    assert caps["shipping_basic"] is True
    assert caps["shipping_detail"]["basic"] is True
    assert caps["shipping_detail"]["max_providers"] == 1
    assert caps["tracking"]["meta"] is True
    assert caps["meta_pixel"] is True

    # Capabilities dilarang
    assert caps["tracking"]["capi"] is False
    assert caps["meta_capi"] is False
    assert caps["analytics"]["advanced"] is False
    assert caps["analytics_advanced"] is False
    assert caps["multi_user"] is False
    assert caps["broadcast"] is False

    # Limits
    assert limits["max_active_products"] == 3
    assert limits["shipping_providers_max"] == 1


@pytest.mark.asyncio
async def test_checkout_lite_context_resolution_and_can_use():
    """3. Memverifikasi resolusi context runtime dan helper can_use() untuk CHECKOUT_LITE."""
    ctx = await tenant_context_resolver.resolve("toko_checkout_lite")

    assert ctx.plan == "CHECKOUT_LITE"

    # Fitur yang diizinkan (Permitted)
    assert tenant_context_resolver.can_use(ctx, "storefront.single_page") is True
    assert tenant_context_resolver.can_use(ctx, "single_page") is True
    assert tenant_context_resolver.can_use(ctx, "orders.basic") is True
    assert tenant_context_resolver.can_use(ctx, "payment.qris") is True
    assert tenant_context_resolver.can_use(ctx, "qris") is True
    assert tenant_context_resolver.can_use(ctx, "checkout.digital") is True
    assert tenant_context_resolver.can_use(ctx, "checkout.physical") is True
    assert tenant_context_resolver.can_use(ctx, "shipping.basic") is True
    assert tenant_context_resolver.can_use(ctx, "tracking.meta") is True
    assert ctx.limits.max_active_products == 3
    assert ctx.limits.shipping_providers_max == 1

    # Fitur terlarang (Forbidden)
    assert tenant_context_resolver.can_use(ctx, "tracking.capi") is False
    assert tenant_context_resolver.can_use(ctx, "meta_capi") is False
    assert tenant_context_resolver.can_use(ctx, "analytics.advanced") is False
    assert tenant_context_resolver.can_use(ctx, "analytics_advanced") is False
    assert tenant_context_resolver.can_use(ctx, "multi_user") is False
    assert tenant_context_resolver.can_use(ctx, "broadcast") is False


def test_guard_analytics_advanced_returns_403(client):
    """4. Guard Check: Pemanggilan analytics campaign oleh CHECKOUT_LITE WAJIB HTTP 403 FEATURE_NOT_ENTITLED."""
    resp = client.get("/api/v1/analytics/campaigns?tenant_slug=toko_checkout_lite")
    assert resp.status_code == 403
    assert "FEATURE_NOT_ENTITLED" in resp.text


def test_guard_broadcast_returns_403(client):
    """5. Guard Check: Pemanggilan Meta broadcast oleh CHECKOUT_LITE WAJIB HTTP 403 FEATURE_NOT_ENTITLED."""
    payload = {
        "tenant_id": "toko_checkout_lite",
        "template_name": "promo_checkout_lite_test",
        "recipients": ["6281298765432"],
    }
    resp = client.post("/api/v1/broadcast/meta/send-template", json=payload)
    assert resp.status_code == 403
    assert "FEATURE_NOT_ENTITLED" in resp.text


def test_guard_entitled_tenant_analytics_remains_200(client):
    """6. Regression Check: Tenant entitled ('onlineboost' ADS_PERF) tetap berhasil mendapatkan HTTP 200."""
    resp = client.get("/api/v1/analytics/campaigns?tenant_slug=onlineboost")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
