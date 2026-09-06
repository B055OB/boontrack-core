import pytest
from fastapi import HTTPException
from app.schemas.context import (
    RequestContext,
    resolve_tenant_context,
    ChannelType,
    SurfaceType,
    ActorType
)
from app.core.security_context import (
    assert_tenant_integrity,
    format_composite_session_key,
    TenantContextViolation
)
from app.services.onboarding_service import onboarding_service
from app.services.sales_agent_guard import format_tenant_session_key

def setup_module(module):
    # Setup dua tenant terpisah
    onboarding_service.clear_state()
    onboarding_service.upsert_tenant_product("tenant-alpha", {
        "id": "prod-alpha-1",
        "title": "Produk Eksklusif Alpha",
        "price": 100000,
        "stock": 10
    })
    onboarding_service.upsert_tenant_product("tenant-beta", {
        "id": "prod-beta-1",
        "title": "Produk Rahasia Beta",
        "price": 200000,
        "stock": 20
    })

def test_tenant_resolver_does_not_trust_client_tenant_id():
    # Client mencoba spoof tenant_id milik Beta saat mengakses slug Alpha
    ctx = resolve_tenant_context(
        tenant_slug="tenant-alpha",
        channel=ChannelType.WEBCHAT.value,
        surface=SurfaceType.STOREFRONT.value,
        actor_type=ActorType.CUSTOMER.value,
        session_id="sess_client_spoof",
        untrusted_client_tenant_id="tenant-beta-internal-uuid"
    )

    # Server resolver harus mengabaikan spoofed ID dan menyelesaikan tenant_slug "tenant-alpha"
    assert ctx.tenant_slug == "tenant-alpha"
    # Internal tenant_id harus milik Alpha
    alpha_details = onboarding_service.get_tenant_details_by_slug("tenant-alpha")
    expected_alpha_id = str(alpha_details["tenant"]["id"])
    assert ctx.tenant_id == expected_alpha_id
    assert ctx.tenant_id != "tenant-beta-internal-uuid"

def test_tenant_isolation_positive():
    # Tenant Alpha hanya membaca data milik Tenant Alpha
    ctx_alpha = resolve_tenant_context(tenant_slug="tenant-alpha")
    alpha_products = onboarding_service.get_tenant_products("tenant-alpha")
    
    alpha_tids = [p["tenant_id"] for p in alpha_products]
    # Assert integrity check harus lulus
    assert_tenant_integrity(ctx_alpha, alpha_tids)
    assert len(alpha_products) == 1
    assert alpha_products[0]["title"] == "Produk Eksklusif Alpha"

    # Tenant Beta hanya membaca data milik Tenant Beta
    ctx_beta = resolve_tenant_context(tenant_slug="tenant-beta")
    beta_products = onboarding_service.get_tenant_products("tenant-beta")
    beta_tids = [p["tenant_id"] for p in beta_products]
    assert_tenant_integrity(ctx_beta, beta_tids)
    assert len(beta_products) == 1
    assert beta_products[0]["title"] == "Produk Rahasia Beta"

def test_tenant_isolation_negative_fail_closed(caplog):
    # Simulasi Tenant Alpha mencoba mengakses atau menerima produk milik Tenant Beta
    ctx_alpha = resolve_tenant_context(tenant_slug="tenant-alpha")
    beta_products = onboarding_service.get_tenant_products("tenant-beta")
    
    beta_tids = [p["tenant_id"] for p in beta_products]
    
    # Aturan FAIL-CLOSED: Wajib melempar TenantContextViolation (HTTP 403)
    with pytest.raises(TenantContextViolation) as exc_info:
        assert_tenant_integrity(ctx_alpha, beta_tids)

    assert exc_info.value.status_code == 403
    assert "SECURITY_TENANT_CONTEXT_MISMATCH" in exc_info.value.detail
    # Pastikan log keamanan SECURITY_TENANT_CONTEXT_MISMATCH tercatat
    assert "SECURITY_TENANT_CONTEXT_MISMATCH" in caplog.text

def test_redis_composite_session_key_isolation():
    # Test Redis Composite Key standard
    ctx_web = RequestContext(
        environment="production",
        tenant_id="tenant-123",
        tenant_slug="tenant-slug",
        channel="webchat",
        surface="STOREFRONT",
        actor_type="CUSTOMER",
        session_id="sess-abc"
    )
    key_web = format_composite_session_key(ctx_web)
    assert key_web == "bt:production:tenant:tenant-123:channel:webchat:session:sess-abc"

    # Ganti channel ke whatsapp
    ctx_wa = RequestContext(
        environment="production",
        tenant_id="tenant-123",
        tenant_slug="tenant-slug",
        channel="whatsapp",
        surface="STOREFRONT",
        actor_type="CUSTOMER",
        session_id="sess-abc"
    )
    key_wa = format_composite_session_key(ctx_wa)
    assert key_wa == "bt:production:tenant:tenant-123:channel:whatsapp:session:sess-abc"
    
    # Keduanya tidak boleh collision meskipun session_id sama
    assert key_web != key_wa

    # Ganti tenant_id
    ctx_other = RequestContext(
        environment="production",
        tenant_id="tenant-456",
        tenant_slug="other-slug",
        channel="webchat",
        surface="STOREFRONT",
        actor_type="CUSTOMER",
        session_id="sess-abc"
    )
    key_other = format_composite_session_key(ctx_other)
    assert key_other == "bt:production:tenant:tenant-456:channel:webchat:session:sess-abc"
    assert key_web != key_other

    # Test format_tenant_session_key dari sales_agent_guard
    guard_key = format_tenant_session_key(
        tenant_id="tenant-123",
        session_id="sess-abc",
        channel="webchat",
        env="production"
    )
    assert guard_key == "bt:production:tenant:tenant-123:channel:webchat:session:sess-abc"