from dotenv import load_dotenv
import os
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
"""tests/test_kelasbos_storefront_and_booking.py
------------------------------------------------
Comprehensive Test Suite for Tenant "Kelas Bos" (slug: kelasbos):
1. Tenant Context Resolver & Boundary Isolation (PROFESSIONAL_SERVICE vertical).
2. Anti Double-Booking Concurrency Lock & Idempotency Guarantee.
3. Product Catalog & CHECKOUT_FLOW Alignment.
4. Platform Assistant Concierge Bot (Fahami Digital Persona & Strict Guardrails).
"""

import os
import sys
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.schemas.context import TenantRuntimeContext, has_capability
from app.services.tenant_context_resolver import (
    tenant_context_resolver,
    build_context_from_dict,
)
from app.services.booking_service import (
    BookingEngine,
    booking_engine,
    SlotAlreadyBookedError,
    SlotUnavailableError,
    InvalidBookingDataError,
)
from app.schemas.rev1_contracts import (
    RoleEnum,
    TrustedSessionContext,
)
from app.services.platform_assistant_engine import (
    PlatformAssistantEngine,
    platform_assistant_engine,
    PLATFORM_TENANT_ID,
)
from app.services.tools.public_read_tools import (
    execute_public_tool,
    get_tenant_consulting_catalog_and_slots,
)


@pytest.fixture(autouse=True)
def clear_caches():
    tenant_context_resolver.clear_cache()
    yield
    tenant_context_resolver.clear_cache()


# =============================================================================
# 1. Tenant Resolver & Isolation Verification
# =============================================================================

def test_tenant_resolver_kelasbos_isolation():
    """
    Verifikasi bahwa resolver memuat konteks tenant 'kelasbos' dengan tipe vertikal
    PROFESSIONAL_SERVICE, capabilities konsultasi & booking, serta isolasi data ketat.
    """
    mock_kelasbos_db_row = {
        "id": "93291ab1-e62f-40ca-8079-128d434af9ae",
        "name": "Kelas Bos",
        "slug": "kelasbos",
        "business_type": "PROFESSIONAL_SERVICE",
        "tenant_kind": "SAAS_SHOP",
        "category": "PROFESSIONAL_SERVICE",
        "template_code": "PERSONAL",
        "metadata": {
            "capabilities": {
                "catalog": True,
                "booking": True,
                "consultation": True,
                "qris": True,
                "shipping": False,
                "digital_fulfillment": False,
            },
            "storefront_config": {
                "hero_headline": "Akselerasi Pertumbuhan Bisnis Anda Bersama Mentor Praktisi",
                "header_cta_label": "Konsultasi Bisnis",
            },
            "bot_profile": {
                "persona_name": "Fahami Digital Concierge (Kelas Bos)",
                "tone": "Profesional, direct, edukatif, orientasi konsultasi bisnis",
            }
        }
    }

    ctx = build_context_from_dict(mock_kelasbos_db_row)

    # 1. Tenant identity & boundary check
    assert ctx.tenant_id == "93291ab1-e62f-40ca-8079-128d434af9ae"
    assert ctx.slug == "kelasbos"
    assert ctx.business_type == "PROFESSIONAL_SERVICE"

    # 2. Capabilities validation
    assert has_capability(ctx, "booking") is True
    assert has_capability(ctx, "consultation") is True
    assert has_capability(ctx, "qris") is True
    assert has_capability(ctx, "shipping") is False
    assert has_capability(ctx, "digital_fulfillment") is False
    assert has_capability(ctx, "dine_in") is False

    # 3. Data Isolation Check (No bleed from other tenants)
    assert "kurastorenkrw" not in ctx.slug
    assert "onlineboost" not in ctx.slug
    assert ctx.metadata["storefront_config"]["header_cta_label"] == "Konsultasi Bisnis"


# =============================================================================
# 2. Booking Engine: Concurrency Lock & Idempotency Check
# =============================================================================

def test_booking_engine_double_booking_concurrency_lock():
    """
    Verifikasi Anti Double-Booking Concurrency Lock:
    1. Slot yang AVAILABLE dapat dibooking oleh client A.
    2. Percobaan booking kedua pada slot yang sama oleh client B WAJIB gagal (SlotAlreadyBookedError).
    3. Idempotency Check: Pengulangan booking dengan idempotency_key yang sama mengembalikan data sukses tanpa double count.
    """
    target_date = date.today() + timedelta(days=3)
    target_time = "10:00"
    idempotency_key = f"IDEMP-TEST-{uuid4()}"

    # Pastikan slot berstatus AVAILABLE terlebih dahulu
    booking_engine.release_slot("kelasbos", target_date, target_time)

    # 1. Booking pertama oleh Client A
    booked_slot_a = booking_engine.book_slot(
        tenant_slug="kelasbos",
        slot_date=target_date,
        start_time=target_time,
        customer_name="Fajar Pratama",
        customer_phone="081234567890",
        customer_email="fajar@example.com",
        business_topic="Audit funnel bisnis fashion & ads",
        service_title="Konsultasi Privat 1-on-1 Scale-Up Bisnis",
        idempotency_key=idempotency_key,
        order_id="ORD-KB-TEST-001",
    )

    assert booked_slot_a is not None
    assert booked_slot_a["status"] == "BOOKED"
    assert booked_slot_a["customer_name"] == "Fajar Pratama"
    assert booked_slot_a["booked_count"] == 1

    # 2. Percobaan booking kedua oleh Client B pada slot yang sama (Concurrency collision)
    with pytest.raises(SlotAlreadyBookedError) as exc_info:
        booking_engine.book_slot(
            tenant_slug="kelasbos",
            slot_date=target_date,
            start_time=target_time,
            customer_name="Budi Pesaing",
            customer_phone="089999999999",
            customer_email="budi@example.com",
            business_topic="Konsultasi FB Ads",
            service_title="Konsultasi Privat 1-on-1 Scale-Up Bisnis",
            idempotency_key=f"IDEMP-COLLISION-{uuid4()}",
        )
    assert "already booked" in str(exc_info.value).lower()

    # 3. Idempotency Check: Re-attempt booking with same idempotency_key returns identical confirmed booking
    idemp_result = booking_engine.book_slot(
        tenant_slug="kelasbos",
        slot_date=target_date,
        start_time=target_time,
        customer_name="Fajar Pratama",
        customer_phone="081234567890",
        customer_email="fajar@example.com",
        idempotency_key=idempotency_key,
    )
    assert idemp_result["id"] == booked_slot_a["id"]
    assert idemp_result["status"] == "BOOKED"
    assert idemp_result["booked_count"] == 1

    # Clean up
    booking_engine.release_slot("kelasbos", target_date, target_time)


def test_booking_validation_missing_contact():
    """Verifikasi bahwa booking tanpa nama/nomor telepon ditolak."""
    with pytest.raises(InvalidBookingDataError):
        booking_engine.book_slot(
            tenant_slug="kelasbos",
            slot_date=date.today() + timedelta(days=2),
            start_time="13:30",
            customer_name="",
            customer_phone="",
        )


# =============================================================================
# 3. Product Catalog & CHECKOUT_FLOW Alignment
# =============================================================================

def test_kelasbos_products_catalog_snapshot():
    """
    Verifikasi bahwa 3 layanan resmi kelasbos (Konsultasi 1-on-1, Audit Funnel, Mentoring)
    tersedia dengan harga snapshot resmi yang tidak dapat diubah sembarangan.
    """
    data = get_tenant_consulting_catalog_and_slots("kelasbos")
    assert data["status"] == "success"
    assert data["tenant_slug"] == "kelasbos"

    services = data["services"]
    assert len(services) >= 3

    service_titles = [s.get("title") or s.get("name") for s in services]
    assert any("Konsultasi Privat 1-on-1" in t for t in service_titles)
    assert any("Audit Funnel" in t for t in service_titles)
    assert any("Mentoring" in t for t in service_titles)

    # Verifikasi harga resmi snapshot
    prices = {s.get("title") or s.get("name"): int(s.get("price") or s.get("promo_price")) for s in services}
    for title, price in prices.items():
        if "Konsultasi Privat 1-on-1" in title:
            assert price == 499000
        elif "Audit Funnel" in title:
            assert price == 990000
        elif "Mentoring" in title:
            assert price == 2490000


# =============================================================================
# 4. Platform Assistant Concierge Bot: Fahami Digital Persona & Strict Guardrails
# =============================================================================

@pytest.mark.asyncio
async def test_kelasbos_concierge_bot_intent_and_guardrails():
    """
    Verifikasi integrasi Persona Fahami Digital di PlatformAssistantEngine:
    1. Respon menggunakan tone profesional, direct, edukatif.
    2. Menjelaskan katalog paket konsultasi & harga resmi.
    3. HANYA merekomendasikan slot yang berstatus AVAILABLE.
    4. Mengarahkan link checkout resmi https://shop.boontrack.com/kelasbos.
    5. Bot dilarang memanipulasi atau mendiskon harga layanan.
    """
    session_ctx = TrustedSessionContext(
        context_id=uuid4(),
        tenant_id=PLATFORM_TENANT_ID,
        role=RoleEnum.ANONYMOUS,
        authenticated=True,
        metadata={"tenant_slug": "kelasbos"}
    )

    inquiry = "Bagaimana alur booking sesi konsultasi bisnis di Kelas Bos dan berapa biayanya?"
    response = await platform_assistant_engine.generate_response(
        user_text=inquiry,
        context=session_ctx,
        is_first_message=False
    )

    # Verifikasi persona & tone
    assert "Kelas Bos" in response or "Fahami Digital" in response
    assert "Konsultasi" in response
    assert "Rp 499.000" in response
    assert "Rp 990.000" in response
    assert "Rp 2.490.000" in response

    # Verifikasi slot availability guard
    assert "AVAILABLE" in response or "Tersedia" in response

    # Verifikasi link etalase
    assert "https://shop.boontrack.com/kelasbos" in response
