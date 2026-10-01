import pytest
from app.services.ai.grounding import (
    is_setup_toko_intent,
    generate_setup_toko_consultation_reply,
    is_reader_inquiry_intent,
    generate_reader_account_explanation_reply,
)

def test_setup_toko_intent_strictly_limited_to_boontrack():
    """Memastikan is_setup_toko_intent HANYA aktif untuk platform tenant 'boontrack', dan diblokir untuk tenant merchant."""
    query = "Halo min, ada paket layanan apa saja?"

    # Platform tenant 'boontrack' -> ALLOW
    assert is_setup_toko_intent(query, tenant_slug="boontrack") is True

    # Merchant tenants -> STRICTLY BLOCKED / BYPASSED
    assert is_setup_toko_intent(query, tenant_slug="solusi-ads") is False
    assert is_setup_toko_intent(query, tenant_slug="buatinvideo") is False
    assert is_setup_toko_intent(query, tenant_slug="tanev-food") is False
    assert is_setup_toko_intent(query, tenant_slug="career-pro") is False


def test_generate_setup_toko_reply_strictly_limited_to_boontrack():
    """Memastikan respon paket BoonTrack HANYA dikirim jika tenant_slug == 'boontrack'."""
    # boontrack -> returns 3 packages
    reply_platform = generate_setup_toko_consultation_reply(customer_name="Budi", tenant_slug="boontrack")
    assert "Paket 1: Setup Bot WhatsApp Natural" in reply_platform
    assert "BoonTrack Gateway" in reply_platform

    # Non-boontrack merchant tenants -> returns empty string (BLOCKED)
    assert generate_setup_toko_consultation_reply(customer_name="Budi", tenant_slug="solusi-ads") == ""
    assert generate_setup_toko_consultation_reply(customer_name="Budi", tenant_slug="buatinvideo") == ""
    assert generate_setup_toko_consultation_reply(customer_name="Budi", tenant_slug="tanev-food") == ""


def test_reader_inquiry_intent_strictly_limited_to_boontrack():
    """Memastikan inquiry akun reader merchant HANYA aktif untuk 'boontrack'."""
    query = "Akun mutasi reader apa saja min?"

    assert is_reader_inquiry_intent(query, tenant_slug="boontrack") is True
    assert is_reader_inquiry_intent(query, tenant_slug="solusi-ads") is False
    assert is_reader_inquiry_intent(query, tenant_slug="tanev-food") is False
