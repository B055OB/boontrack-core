"""tests/test_service_decoupling.py
Unit tests verifying Phase D Service Decoupling & Tenant Registry Cleanup.
Ensures zero hardcoded tenant slug branching in WhatsApp Routing, Payment Matcher, and Agent Service.
All routing and fulfillment are driven by TenantRuntimeContext and capabilities.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.schemas.context import TenantRuntimeContext, has_capability
from app.services.tenant_context_resolver import (
    tenant_context_resolver,
    build_context_from_dict,
)
from app.services.agent_service import process_incoming_message


@pytest.fixture(autouse=True)
def clear_resolver_cache():
    tenant_context_resolver.clear_cache()
    yield
    tenant_context_resolver.clear_cache()


# =========================================================================
# 1. TEST RESOLVER EXTENSIONS: resolve_tenant & resolve_by_phone_number_id
# =========================================================================

@pytest.mark.asyncio
async def test_resolve_tenant_alias():
    """Memverifikasi bahwa resolve_tenant adalah alias method yang valid untuk resolve_context."""
    mock_supabase = MagicMock()
    mock_supabase.table().select().eq().execute.return_value = MagicMock(data=[{
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Klinik Hukum Pro",
        "slug": "klinik-hukum",
        "business_type": "PROFESSIONAL_SERVICE",
        "tenant_kind": "SAAS",
        "template_code": "PRO_CONSULT",
        "metadata": {
            "capabilities": {
                "consultation": True,
                "booking": True,
            }
        }
    }])

    with patch("app.services.tenant_context_resolver.get_supabase", return_value=mock_supabase):
        ctx = await tenant_context_resolver.resolve_tenant("klinik-hukum")
        assert ctx is not None
        assert ctx.slug == "klinik-hukum"
        assert ctx.business_type == "PROFESSIONAL_SERVICE"
        assert has_capability(ctx, "consultation") is True
        assert has_capability(ctx, "membership") is False


@pytest.mark.asyncio
async def test_resolve_by_phone_number_id_db_and_mapping():
    """Memverifikasi resolusi context berdasarkan WhatsApp Phone Number ID."""
    mock_supabase = MagicMock()
    # Mock lookup by metadata filter
    mock_supabase.table().select().filter().execute.return_value = MagicMock(data=[{
        "id": "77777777-7777-7777-7777-777777777777",
        "name": "Omni Store Official",
        "slug": "omni-store",
        "business_type": "PHYSICAL",
        "tenant_kind": "SAAS",
        "template_code": "RETAIL_PRO",
        "metadata": {
            "phone_number_id": "999888777111",
            "capabilities": {
                "catalog": True,
                "orders": True,
            }
        }
    }])

    with patch("app.services.tenant_context_resolver.get_supabase", return_value=mock_supabase):
        ctx = await tenant_context_resolver.resolve_by_phone_number_id("999888777111")
        assert ctx is not None
        assert ctx.slug == "omni-store"
        assert has_capability(ctx, "catalog") is True


# =========================================================================
# 2. TEST AGENT SERVICE CAPABILITY ROUTING
# =========================================================================

@pytest.mark.asyncio
async def test_agent_service_membership_capability_routing():
    """Memverifikasi routing ke gym/membership service jika tenant memiliki capability membership."""
    custom_gym_ctx = TenantRuntimeContext(
        tenant_id="33333333-3333-3333-3333-333333333333",
        slug="megafit-gym",
        tenant_kind="CUSTOM_APP",
        business_type="MEMBERSHIP",
        template_code="GYM_V1",
        capabilities={"membership": True, "turnstile_iot": True}
    )

    with patch.object(tenant_context_resolver, "resolve_tenant", new_callable=AsyncMock, return_value=custom_gym_ctx), \
         patch("app.tenants.gym.service.gym_service.handle_user_message", new_callable=AsyncMock) as mock_gym:
        
        mock_gym.return_value = {"reply": "Selamat datang di MegaFit! Jadwal gym buka 24 jam."}

        reply = await process_incoming_message(
            tenant_slug="megafit-gym",
            message="info jam buka",
            user_phone="62812345678",
            user_name="Budi"
        )

        assert mock_gym.called
        assert "MegaFit" in reply


@pytest.mark.asyncio
async def test_agent_service_public_service_capability_routing():
    """Memverifikasi routing ke public service jika tenant memiliki capability public_service / B2G."""
    b2g_ctx = TenantRuntimeContext(
        tenant_id="44444444-4444-4444-4444-444444444444",
        slug="layanan-warga-bandung",
        tenant_kind="INTERNAL",
        business_type="B2G",
        template_code="PUBLIC_SERVICE",
        capabilities={"public_service": True, "complaints": True}
    )

    with patch.object(tenant_context_resolver, "resolve_tenant", new_callable=AsyncMock, return_value=b2g_ctx), \
         patch("app.modules.public_services.service.public_service_service.handle_query", new_callable=AsyncMock) as mock_ps:
        
        mock_ps.return_value = {"reply": "Layanan Pengaduan Warga Bandung siap membantu."}

        reply = await process_incoming_message(
            tenant_slug="layanan-warga-bandung",
            message="cara lapor jalan rusak",
            user_phone="62812345678",
            user_name="Ahmad"
        )

        assert mock_ps.called
        assert "Layanan Pengaduan" in reply


@pytest.mark.asyncio
async def test_agent_service_default_commerce_capability_routing():
    """Memverifikasi routing default ke commerce_ai_engine jika tenant bertipe PHYSICAL/SAAS."""
    retail_ctx = TenantRuntimeContext(
        tenant_id="55555555-5555-5555-5555-555555555555",
        slug="sepatu-nusantara",
        tenant_kind="SAAS",
        business_type="PHYSICAL",
        template_code="DEFAULT",
        capabilities={"catalog": True, "orders": True}
    )

    with patch.object(tenant_context_resolver, "resolve_tenant", new_callable=AsyncMock, return_value=retail_ctx), \
         patch("app.services.ai_engine.commerce_ai_engine.generate_commerce_response", new_callable=AsyncMock) as mock_commerce:
        
        mock_commerce.return_value = "Ready stok sepatu sneakers size 42."

        reply = await process_incoming_message(
            tenant_slug="sepatu-nusantara",
            message="apakah sepatu sneakers ada?",
            user_phone="62812345678",
            user_name="Doni"
        )

        assert mock_commerce.called
        assert "Ready stok" in reply


# =========================================================================
# 3. TEST PAYMENT MATCHER CAPABILITY FULFILLMENT
# =========================================================================

@pytest.mark.asyncio
async def test_payment_matcher_digital_fulfillment_capability():
    """Memverifikasi mutasi pembayaran memicu fulfillment otomatis via capability digital_fulfillment."""
    from app.payments.matcher import match_and_fulfill_payment, PAYMENT_INTENTS

    digital_ctx = TenantRuntimeContext(
        tenant_id="66666666-6666-6666-6666-666666666666",
        slug="akademi-ai",
        tenant_kind="SAAS",
        business_type="DIGITAL",
        template_code="DIGITAL_V1",
        capabilities={"digital_fulfillment": True, "qris": True}
    )

    PAYMENT_INTENTS["INV-AI-999"] = {
        "invoice_id": "INV-AI-999",
        "user_id": "123456789",
        "tenant_id": "akademi-ai",
        "product_id": "PROD_EBOOK",
        "total_amount": 15000,
        "status": "PENDING"
    }

    with patch.object(tenant_context_resolver, "resolve_tenant", new_callable=AsyncMock, return_value=digital_ctx), \
         patch("app.tenants.digicorn.service.digicorn_service.deliver_paid_order", new_callable=AsyncMock) as mock_delivery:
        
        mock_delivery.return_value = True

        res = await match_and_fulfill_payment(
            amount=15000,
            tenant_id="akademi-ai"
        )

        assert res["status"] == "SUCCESS"
        assert res["action"] == "AUTO_FULFILLED_DIGITAL"
        assert res["invoice"] == "INV-AI-999"
        assert mock_delivery.called

    PAYMENT_INTENTS.pop("INV-AI-999", None)


@pytest.mark.asyncio
async def test_payment_matcher_membership_capability():
    """Memverifikasi mutasi pembayaran memicu perpanjangan otomatis via capability membership."""
    from app.payments.matcher import match_and_fulfill_payment, PAYMENT_INTENTS

    gym_ctx = TenantRuntimeContext(
        tenant_id="88888888-8888-8888-8888-888888888888",
        slug="prima-fit",
        tenant_kind="CUSTOM_APP",
        business_type="MEMBERSHIP",
        template_code="GYM_TURNSTILE",
        capabilities={"membership": True, "turnstile_iot": True}
    )

    PAYMENT_INTENTS["INV-GYM-123"] = {
        "invoice_id": "INV-GYM-123",
        "user_id": "user_gym_01",
        "member_id": "MEMBER-999",
        "tenant_id": "prima-fit",
        "total_amount": 250000,
        "status": "PENDING"
    }

    with patch.object(tenant_context_resolver, "resolve_tenant", new_callable=AsyncMock, return_value=gym_ctx), \
         patch("app.services.gym_access_service.gym_access_service.process_gym_membership_renewal", new_callable=AsyncMock) as mock_renewal:
        
        mock_renewal.return_value = {"extended_days": 30, "status": "ACTIVE"}

        res = await match_and_fulfill_payment(
            amount=250000,
            tenant_id="prima-fit"
        )

        assert res["status"] == "SUCCESS"
        assert res["action"] == "GYM_MEMBERSHIP_RENEWED"
        assert res["invoice_id"] == "INV-GYM-123"
        assert mock_renewal.called

    PAYMENT_INTENTS.pop("INV-GYM-123", None)
