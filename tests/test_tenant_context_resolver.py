import pytest
import asyncio
from unittest.mock import patch, MagicMock

from app.schemas.context import TenantRuntimeContext, has_capability
from app.services.tenant_context_resolver import (
    tenant_context_resolver,
    normalize_business_type,
    normalize_tenant_kind,
    build_context_from_dict,
)

@pytest.fixture(autouse=True)
def clear_resolver_cache():
    tenant_context_resolver.clear_cache()
    yield
    tenant_context_resolver.clear_cache()


def test_standard_saas_tenant_resolution():
    """Menguji resolusi tenant SaaS retail fisik standar."""
    mock_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Batik Nusantara Store",
        "slug": "batik-nusantara",
        "business_type": "PHYSICAL",
        "tenant_kind": "SAAS",
        "template_code": "RETAIL_PRO",
        "metadata": {
            "capabilities": {
                "catalog": True,
                "shipping": True,
                "qris": True,
                "capi": True,
            },
            "persona": {
                "system_prompt": "Kamu asisten toko Batik Nusantara.",
                "tone": "Ramah & Elegan",
                "faq": [{"q": "Bisa kirim ke Papua?", "a": "Bisa via JNE/J&T."}],
            }
        }
    }

    ctx = build_context_from_dict(mock_row)

    assert ctx.tenant_id == "11111111-1111-1111-1111-111111111111"
    assert ctx.slug == "batik-nusantara"
    assert ctx.tenant_kind == "SAAS"
    assert ctx.business_type == "PHYSICAL"
    assert ctx.template_code == "RETAIL_PRO"
    assert has_capability(ctx, "shipping") is True
    assert has_capability(ctx, "qris") is True
    assert has_capability(ctx, "membership") is False
    assert ctx.ai_persona is not None
    assert ctx.ai_persona["tone"] == "Ramah & Elegan"


def test_custom_app_gym_membership_resolution():
    """Menguji resolusi tenant Custom App (Gym/Fitness dengan capability membership & turnstile IoT)."""
    mock_row = {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "Titan Fitness Hub",
        "slug": "titan-fitness",
        "business_type": "MEMBERSHIP",
        "tenant_kind": "CUSTOM_APP",
        "template_code": "GYM_TURNSTILE_V2",
        "metadata": {
            "capabilities": {
                "membership": True,
                "turnstile_iot": True,
                "classes": True,
                "pos": True,
                "qris": True,
                "shipping": False,
            },
            "ai_persona": {
                "system_prompt": "Kamu adalah asisten kebugaran Titan Fitness Hub.",
                "tone": "Sporty & Energik",
            }
        }
    }

    ctx = build_context_from_dict(mock_row)

    assert ctx.tenant_id == "22222222-2222-2222-2222-222222222222"
    assert ctx.slug == "titan-fitness"
    assert ctx.tenant_kind == "CUSTOM_APP"
    assert ctx.business_type == "MEMBERSHIP"
    assert ctx.template_code == "GYM_TURNSTILE_V2"
    assert has_capability(ctx, "membership") is True
    assert has_capability(ctx, "turnstile_iot") is True
    assert has_capability(ctx, "classes") is True
    assert has_capability(ctx, "shipping") is False
    assert ctx.has_capability("POS") is True  # Case-insensitive helper test


def test_b2g_public_service_resolution():
    """Menguji resolusi tenant B2G (Pelayanan Publik / Aduan Warga)."""
    mock_row = {
        "id": "33333333-3333-3333-3333-333333333333",
        "name": "Pelayanan Publik Warga Mandiri",
        "slug": "pelayanan-warga",
        "business_type": "B2G",
        "tenant_kind": "CUSTOM_APP",
        "template_code": "PUBLIC_SERVICE_V1",
        "metadata": {
            "capabilities": {
                "public_service": True,
                "complaints": True,
                "document_intake": True,
                "qris": False,
                "shipping": False,
            },
            "persona": {
                "system_prompt": "Kamu adalah asisten pelayanan kelurahan digital.",
                "tone": "Birokrat Ramah & Solutif",
            }
        }
    }

    ctx = build_context_from_dict(mock_row)

    assert ctx.tenant_id == "33333333-3333-3333-3333-333333333333"
    assert ctx.slug == "pelayanan-warga"
    assert ctx.tenant_kind == "CUSTOM_APP"
    assert ctx.business_type == "B2G"
    assert has_capability(ctx, "public_service") is True
    assert has_capability(ctx, "complaints") is True
    assert has_capability(ctx, "document_intake") is True
    assert has_capability(ctx, "qris") is False
    assert has_capability(ctx, "shipping") is False


@pytest.mark.asyncio
async def test_async_resolver_with_in_memory_cache():
    """Menguji eksekusi query asinkron ke Supabase dan pemanfaatan in-memory cache (<10ms)."""
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()

    fake_db_record = {
        "id": "44444444-4444-4444-4444-444444444444",
        "name": "Digital Mastery Academy",
        "slug": "digital-academy",
        "business_type": "DIGITAL",
        "tenant_kind": "SAAS",
        "template_code": "DIGITAL_COURSE_V1",
        "metadata": {
            "capabilities": {
                "catalog": True,
                "digital_fulfillment": True,
                "qris": True,
            }
        }
    }

    mock_eq.execute.return_value = MagicMock(data=[fake_db_record])
    mock_select.eq.return_value = mock_eq
    mock_table.select.return_value = mock_select
    mock_supabase.table.return_value = mock_table

    with patch("app.services.tenant_context_resolver.get_supabase", return_value=mock_supabase):
        # 1. Panggilan Pertama: Harus query ke Supabase
        ctx1 = await tenant_context_resolver.resolve_context("digital-academy")
        assert ctx1 is not None
        assert ctx1.slug == "digital-academy"
        assert ctx1.business_type == "DIGITAL"
        assert has_capability(ctx1, "digital_fulfillment") is True
        assert mock_supabase.table.call_count == 1

        # 2. Panggilan Kedua: Harus ambil dari cache tanpa menyentuh Supabase lagi
        ctx2 = await tenant_context_resolver.resolve_context("digital-academy")
        assert ctx2 is not None
        assert ctx2.tenant_id == ctx1.tenant_id
        assert mock_supabase.table.call_count == 1  # Tetap 1 karena hit dari memory cache

        # 3. Invalidasi Cache: Panggilan berikutnya query ulang
        tenant_context_resolver.invalidate_cache("digital-academy")
        ctx3 = await tenant_context_resolver.resolve_context("digital-academy")
        assert ctx3 is not None
        assert mock_supabase.table.call_count == 2


@pytest.mark.asyncio
async def test_fail_closed_zero_hardcode_non_existent_tenant():
    """Menguji kepatuhan Rule 1 (Zero Hardcode): Tenant yang tidak ada harus mengembalikan None, bukan fallback mock."""
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()

    # Database return empty
    mock_eq.execute.return_value = MagicMock(data=[])
    mock_select.eq.return_value = mock_eq
    mock_table.select.return_value = mock_select
    mock_supabase.table.return_value = mock_table

    with patch("app.services.tenant_context_resolver.get_supabase", return_value=mock_supabase):
        # Tenant tidak dikenal
        ctx = await tenant_context_resolver.resolve_context("toko-tidak-ada-xyz")
        assert ctx is None

        # Empty slug
        ctx_empty = await tenant_context_resolver.resolve_context("")
        assert ctx_empty is None
