"""tests/test_shipping_adapters.py
Unit tests for ShippingAdapter, BiteshipAdapter, and ShippingAdapterFactory.
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.schemas.context import TenantRuntimeContext
from app.services.shipping import (
    RateRequest,
    RateOption,
    ShipmentRequest,
    ShipmentResponse,
    TrackingResponse,
    BiteshipAdapter,
    ShippingAdapterFactory,
)


# =========================================================================
# 1. BITESHIP ADAPTER TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_biteship_calculate_rates_instant_and_regular():
    adapter = BiteshipAdapter()

    req = RateRequest(
        origin_postal_code="40287",
        destination_postal_code="10110",
        items=[
            {"name": "Kaos Polos", "value": 50000, "weight": 250, "quantity": 2}
        ]
    )

    rates = await adapter.calculate_rates(req)

    assert len(rates) >= 2
    types = {r.service_type for r in rates}
    assert "instant" in types or "same_day" in types
    assert "standard" in types

    # Cek struktur RateOption
    for r in rates:
        assert isinstance(r, RateOption)
        assert r.rate > 0
        assert r.courier_name
        assert r.service_name
        assert r.etd


@pytest.mark.asyncio
async def test_biteship_create_shipment():
    adapter = BiteshipAdapter()

    req = ShipmentRequest(
        order_id="ORD-SHIP-001",
        courier_code="jne",
        service_type="reg",
        origin_name="Gudang Bandung",
        origin_phone="08122334455",
        origin_address="Jl. Soekarno Hatta No. 123",
        origin_postal_code="40287",
        destination_name="Andi Wijaya",
        destination_phone="08199887766",
        destination_address="Jl. Sudirman No. 45",
        destination_postal_code="10110",
        items=[{"name": "Buku Panduan", "weight": 500, "value": 100000, "quantity": 1}],
    )

    res = await adapter.create_shipment(req)

    assert isinstance(res, ShipmentResponse)
    assert res.shipment_id
    assert res.tracking_number
    assert res.courier_code == "jne"
    assert res.status == "CONFIRMED"
    assert res.shipping_cost > 0


@pytest.mark.asyncio
async def test_biteship_track_airwaybill():
    adapter = BiteshipAdapter()

    tracking = await adapter.track_airwaybill(
        airwaybill_number="TRACK-ORD-SHIP-001",
        courier_code="jne"
    )

    assert isinstance(tracking, TrackingResponse)
    assert tracking.tracking_number == "TRACK-ORD-SHIP-001"
    assert tracking.courier_code == "jne"
    assert tracking.status in ("CONFIRMED", "PICKED_UP", "IN_TRANSIT", "DELIVERED")
    assert len(tracking.history) >= 1


# =========================================================================
# 2. SHIPPING ADAPTER FACTORY & RATE AGGREGATOR TESTS
# =========================================================================

def test_shipping_factory_resolve():
    ctx = TenantRuntimeContext(
        tenant_id="33333333-3333-3333-3333-333333333333",
        slug="toko-biteship",
        tenant_kind="SAAS",
        business_type="PHYSICAL",
        metadata={
            "shipping_config": {
                "provider": "biteship",
                "api_key": "biteship_test_key"
            }
        }
    )

    adapter = ShippingAdapterFactory.resolve(ctx)
    assert isinstance(adapter, BiteshipAdapter)
    assert adapter.api_key == "biteship_test_key"


@pytest.mark.asyncio
async def test_shipping_factory_aggregate_rates_with_markup_and_filters():
    ctx = TenantRuntimeContext(
        tenant_id="44444444-4444-4444-4444-444444444444",
        slug="toko-fashion-bandung",
        tenant_kind="SAAS",
        business_type="PHYSICAL",
        metadata={
            "shipping_config": {
                "provider": "biteship",
                "allowed_couriers": ["gosend", "jne"],
                "markup_flat": 2000,
                "markup_percentage": 10.0,
            }
        }
    )

    req = RateRequest(
        origin_postal_code="40287",
        destination_postal_code="10110",
        items=[{"name": "Baju", "weight": 500, "quantity": 1}]
    )

    aggregated = await ShippingAdapterFactory.aggregate_rates(ctx, req)

    assert len(aggregated) >= 1
    # Pastikan hanya kurir yang di-whitelist yang muncul
    courier_codes = {o.courier_code.lower() for o in aggregated}
    assert courier_codes.issubset({"gosend", "jne"})
    assert "grab" not in courier_codes
    assert "sicepat" not in courier_codes

    # Pastikan diurutkan dari termurah ke termahal
    rates = [o.rate for o in aggregated]
    assert rates == sorted(rates)
