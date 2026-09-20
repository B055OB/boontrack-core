"""tests/test_boonpilot_scope_lock.py
Unit Tests untuk Kontrak Arsitektur BoonPilot Scope Lock.
Memverifikasi:
1. Tenant & RBAC Isolation: Penolakan arbitrary tenant_id dari client.
2. Capability Resolver (Dynamic Button-Driven Menu):
   - Tenant tanpa CAPI tidak menerima menu CAPI.
   - Tenant tanpa entitlement affiliate tidak menerima menu Affiliate.
   - Tenant dengan CAPI & Affiliate menerima opsi yang relevan.
3. WhatsApp Isolation: Memastikan isolasi ketat terhadap nomor resmi WABA platform (+6285139555449).
4. No LLM Business Truth: Memastikan pertanyaan harga, prorata, dan komisi dilayani langsung oleh engine backend.
"""

import pytest
import asyncio
from app.services.boonpilot_service import (
    boonpilot_service,
    assert_whatsapp_isolation,
    OFFICIAL_PLATFORM_WABA_NUMBER,
)
from app.services.entitlement_service import (
    TenantRuntimeContext,
    TenantCapabilities,
    TenantLimits,
)


@pytest.mark.asyncio
async def test_boonpilot_tenant_rbac_isolation_rejects_arbitrary_client_tenant_id():
    """
    Test 1: Memverifikasi bahwa BoonPilot menolak arbitrary untrusted tenant_id
    yang dikirimkan dari client jika tidak cocok dengan konteks runtime tenant yang sah.
    """
    # 1. Kasus arbitrary tenant_id tidak cocok -> Wajib tolak dengan PermissionError
    with pytest.raises(PermissionError) as exc_info:
        await boonpilot_service.chat(
            tenant_slug="onlineboost",
            message="Halo, tolong cek status toko",
            untrusted_client_tenant_id="attacker_hacked_tenant_999",
        )
    assert "Arbitrary tenant_id 'attacker_hacked_tenant_999' tidak cocok" in str(exc_info.value)

    # 2. Kasus tenant_id cocok dengan slug yang sah -> Berhasil
    response = await boonpilot_service.chat(
        tenant_slug="onlineboost",
        message="Halo",
        untrusted_client_tenant_id="onlineboost",
    )
    assert response is not None
    assert response.get("type") == "text"


@pytest.mark.asyncio
async def test_boonpilot_capability_resolver_dynamic_menu_filtering():
    """
    Test 2: Memverifikasi Capability Resolver (Dynamic Button-Driven Menu):
    - SOLO Tier: Tidak memiliki CAPI dan tidak memiliki Affiliate -> Menu CAPI & Affiliate TIDAK BOLEH tampil.
    - ADS_PERF Tier: Memiliki CAPI, tapi tidak memiliki Affiliate -> Menu CAPI tampil, Affiliate TIDAK BOLEH tampil.
    - TEAM_SCALE Tier: Memiliki CAPI dan Affiliate -> Kedua menu TAMPIL.
    """
    # 1. SOLO Tenant Context (Tanpa CAPI, Tanpa Affiliate)
    solo_context = TenantRuntimeContext(
        tenant_id="toko_solo_basic",
        business_type="PHYSICAL",
        plan="SOLO",
        status="ACTIVE",
        capabilities=TenantCapabilities(
            catalog=True,
            orders=True,
            qris=True,
            ai_bot=True,
            meta_capi=False,
            powertools=False,
            affiliate=False,
        ),
        limits=TenantLimits(order_quota=0, ai_conversations=250),
    )
    solo_menu = boonpilot_service.resolve_dynamic_menu(solo_context, rbac_role="MERCHANT")
    solo_button_ids = [btn["id"] for btn in solo_menu["menu"]]

    assert "catalog" in solo_button_ids
    assert "sales_report" in solo_button_ids
    assert "stock_check" in solo_button_ids
    assert "proration_quote" in solo_button_ids
    # CAPI dan Affiliate WAJIB TIDAK ADA
    assert "meta_capi" not in solo_button_ids
    assert "powertools_diagnostic" not in solo_button_ids
    assert "affiliate_hub" not in solo_button_ids
    assert "affiliate_estimate" not in solo_button_ids
    assert solo_menu["has_capi"] is False
    assert solo_menu["has_affiliate"] is False

    # 2. ADS_PERF Tenant Context (Ada CAPI, Tanpa Affiliate)
    ads_context = TenantRuntimeContext(
        tenant_id="toko_ads_perf",
        business_type="PHYSICAL",
        plan="ADS_PERF",
        status="ACTIVE",
        capabilities=TenantCapabilities(
            catalog=True,
            orders=True,
            qris=True,
            ai_bot=True,
            meta_capi=True,
            powertools=True,
            affiliate=False,
        ),
        limits=TenantLimits(order_quota=0, ai_conversations=500),
    )
    ads_menu = boonpilot_service.resolve_dynamic_menu(ads_context, rbac_role="MERCHANT")
    ads_button_ids = [btn["id"] for btn in ads_menu["menu"]]

    # CAPI WAJIB ADA
    assert "meta_capi" in ads_button_ids
    assert "powertools_diagnostic" in ads_button_ids
    # Affiliate WAJIB TIDAK ADA
    assert "affiliate_hub" not in ads_button_ids
    assert "affiliate_estimate" not in ads_button_ids
    assert ads_menu["has_capi"] is True
    assert ads_menu["has_affiliate"] is False

    # 3. TEAM_SCALE Tenant Context (Ada CAPI, Ada Affiliate)
    team_context = TenantRuntimeContext(
        tenant_id="toko_team_scale",
        business_type="PHYSICAL",
        plan="TEAM_SCALE",
        status="ACTIVE",
        capabilities=TenantCapabilities(
            catalog=True,
            orders=True,
            qris=True,
            ai_bot=True,
            meta_capi=True,
            powertools=True,
            affiliate=True,
        ),
        limits=TenantLimits(order_quota=0, ai_conversations=1000),
    )
    team_menu = boonpilot_service.resolve_dynamic_menu(team_context, rbac_role="MERCHANT")
    team_button_ids = [btn["id"] for btn in team_menu["menu"]]

    # Keduanya WAJIB ADA
    assert "meta_capi" in team_button_ids
    assert "powertools_diagnostic" in team_button_ids
    assert "affiliate_hub" in team_button_ids
    assert "affiliate_estimate" in team_button_ids
    assert team_menu["has_capi"] is True
    assert team_menu["has_affiliate"] is True


@pytest.mark.asyncio
async def test_whatsapp_isolation_guard():
    """
    Test 3: Memverifikasi WhatsApp Isolation:
    Pastikan BoonPilot TIDAK MEMILIKI akses ke router inbound/outbound nomor WABA resmi platform (+6285139555449).
    """
    # 1. Langsung panggil guard assertion dengan nomor WABA resmi platform
    with pytest.raises(PermissionError) as exc_info:
        assert_whatsapp_isolation("+6285139555449")
    assert "Akses ditolak: BoonPilot terisolasi secara ketat" in str(exc_info.value)

    # Format variasi nomor (tanpa plus, spasi, dsb)
    with pytest.raises(PermissionError):
        assert_whatsapp_isolation("6285139555449")

    with pytest.raises(PermissionError):
        assert_whatsapp_isolation("085139555449")

    # 2. Panggil via chat entrypoint
    with pytest.raises(PermissionError):
        await boonpilot_service.chat(
            tenant_slug="onlineboost",
            message="Kirim pesan lewat WABA",
            target_whatsapp_phone="+6285139555449",
        )

    # Nomor merchant biasa diizinkan tanpa error
    assert_whatsapp_isolation("+6281234567890")


@pytest.mark.asyncio
async def test_no_llm_business_truth_authoritative_tools():
    """
    Test 4: Memverifikasi 'No LLM Business Truth':
    Pertanyaan harga prorata upgrade wajib dilayani oleh engine billing backend resmi,
    bukan reka hitung mandiri oleh LLM.
    """
    # 1. Tanya Prorata Upgrade untuk tenant SOLO (naik ke PRO_SCALE)
    res_prorate = await boonpilot_service.chat(
        tenant_slug="toko_solo_demo",
        message="Berapa biaya hitung prorata upgrade ke pro_scale?",
    )
    assert res_prorate.get("type") == "text"
    assert "Kalkulasi Resmi Prorata Upgrade (Otoritas Backend)" in res_prorate["reply"]
    data = res_prorate.get("data", {})
    assert data.get("authority") == "BACKEND_BILLING_ENGINE"
    assert data.get("tool") == "calculate_upgrade_proration"
    proration = data.get("proration", {})
    assert proration.get("new_tier") == "PRO_SCALE"
    assert proration.get("prorated_amount") > 0
    assert proration.get("invoice_type") == "UPGRADE_PRORATION"

    # 2. Tanya Komisi Affiliate untuk tenant tanpa entitlement affiliate
    res_aff = await boonpilot_service.chat(
        tenant_slug="toko_solo_demo",
        message="Bagaimana komisi affiliate toko saya?",
    )
    assert res_aff.get("type") == "text"
    assert "Program Mitra Affiliate Belum Aktif" in res_aff["reply"]
    assert res_aff.get("data", {}).get("status") == "NOT_ENTITLED"
