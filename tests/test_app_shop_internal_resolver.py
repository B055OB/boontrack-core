import pytest
from app.services.tenant_context_resolver import tenant_context_resolver
from app.services.whatsapp.evolution import normalize_evolution_instance

OFFICIAL_BOON_UUID = "52967979-4760-4cea-b686-cdbdb389c0e1"


@pytest.fixture(autouse=True)
def clear_resolver_cache():
    tenant_context_resolver.clear_cache()
    yield
    tenant_context_resolver.clear_cache()


@pytest.mark.asyncio
async def test_tenant_resolver_by_official_uuid():
    """Memastikan resolver mengenali UUID resmi internal tenant boon."""
    ctx = await tenant_context_resolver.resolve_context(OFFICIAL_BOON_UUID)
    assert ctx is not None
    assert ctx.tenant_id == OFFICIAL_BOON_UUID
    assert ctx.slug == "boon"
    assert ctx.metadata.get("tenant_type") == "APP_SHOP_V1"
    assert ctx.metadata.get("whatsapp_instance") == "boontrack-app-shop"
    assert ctx.metadata.get("phone") == "081215567168"
    assert ctx.capabilities.get("qris") is True
    assert ctx.capabilities.get("digital_fulfillment") is True


@pytest.mark.asyncio
async def test_tenant_resolver_by_slug_boon():
    """Memastikan slug 'boon' terselesaikan dengan UUID resmi 52967979-4760-4cea-b686-cdbdb389c0e1."""
    ctx = await tenant_context_resolver.resolve_context("boon")
    assert ctx is not None
    assert ctx.tenant_id == OFFICIAL_BOON_UUID
    assert ctx.slug == "boon"
    assert ctx.metadata.get("storefront_url") == "https://shop.boontrack.com/boon"


@pytest.mark.asyncio
async def test_tenant_resolver_by_phone_and_instance():
    """Memastikan resolusi by phone number ID dan instance name sinkron ke UUID resmi."""
    for identifier in ["081215567168", "6281215567168", "boontrack-app-shop", OFFICIAL_BOON_UUID]:
        ctx = await tenant_context_resolver.resolve_by_phone_number_id(identifier)
        assert ctx is not None, f"Failed resolving identifier: {identifier}"
        assert ctx.tenant_id == OFFICIAL_BOON_UUID
        assert ctx.slug == "boon"


def test_normalize_evolution_instance_boontrack_app_shop():
    """Memastikan instance name dinormalisasi ke boontrack-app-shop."""
    assert normalize_evolution_instance("app_shop_v1") == "boontrack-app-shop"
    assert normalize_evolution_instance("app_shop") == "boontrack-app-shop"
    assert normalize_evolution_instance("boon") == "boontrack-app-shop"
    assert normalize_evolution_instance("boontrack-app-shop") == "boontrack-app-shop"
    assert normalize_evolution_instance("") == "boontrack-app-shop"
