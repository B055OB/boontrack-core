"""tests/test_official_bot_and_tenant_isolation.py
Unit tests for Official Bot Knowledge Base (Platform Concierge) and Static Tenant & Category Isolation.

Audit Requirements:
1. Official Bot Knowledge Base:
   a. Kelebihan BoonTrack Shop (WhatsApp checkout, QRIS real-time, Server-side CAPI/GTM, multi-tenant isolation).
   b. Fitur per Paket Layanan (Trial: 30 order / 50 AI / 15 WA, Starter/Pro: Unlimited / CAPI / Whitelist FB Ads).
   c. Panduan Pengguna Baru (BoonPilot & 6 Langkah Cepat Dashboard).
2. Static Tenant Isolation & Category Boundaries:
   a. Zero Memory Leakage (Deepcopy cache and default matrix immutability).
   b. Strict Category Boundaries for F&B, Retail/Fashion, Digital, and Services.
"""

import pytest
from unittest.mock import patch, MagicMock

from app.whatsapp.traffic_splitter import (
    CONCIERGE_SYSTEM_PROMPT,
    OFFICIAL_KNOWLEDGE_BASE,
    get_static_concierge_response,
    generate_concierge_reply,
)
from app.services.tenant_context_resolver import (
    tenant_context_resolver,
    build_context_from_dict,
    has_capability,
    DEFAULT_CAPABILITIES_BY_VERTICAL,
)
from app.services.unified_conversation_service import (
    get_welcome_buttons_for_category,
    normalize_business_category,
    CATEGORY_WELCOME_BUTTONS,
)


# =============================================================================
# 1. Knowledge Base Bot Resmi BoonTrack (Platform Concierge / Official Bot)
# =============================================================================

def test_official_bot_knowledge_base_kelebihan():
    """Memverifikasi bahwa knowledge base bot resmi memuat 4 kelebihan utama BoonTrack Shop."""
    # Verifikasi dalam System Prompt LLM
    assert "Checkout Instan" in CONCIERGE_SYSTEM_PROMPT
    assert "QRIS" in CONCIERGE_SYSTEM_PROMPT
    assert "Meta CAPI" in CONCIERGE_SYSTEM_PROMPT
    assert "GTM DataLayer" in CONCIERGE_SYSTEM_PROMPT
    assert "PII" in CONCIERGE_SYSTEM_PROMPT
    assert "Multi-Tenant" in CONCIERGE_SYSTEM_PROMPT or "multi-tenant" in CONCIERGE_SYSTEM_PROMPT.lower()

    # Verifikasi dalam dictionary deterministik
    resp = get_static_concierge_response("Apa kelebihan dan keunggulan BoonTrack Shop?")
    assert "Kelebihan Utama BoonTrack Shop" in resp
    assert "Checkout Instan Terintegrasi WhatsApp & Web" in resp
    assert "Auto-Verifikasi Pembayaran QRIS Real-Time" in resp
    assert "Server-Side Tracking Bawaan" in resp
    assert "Perlindungan Kuota Trial Cerdas & Isolasi Multi-Tenant" in resp


def test_official_bot_knowledge_base_paket():
    """Memverifikasi bahwa knowledge base memuat perbandingan paket Trial vs Berbayar secara akurat."""
    # Verifikasi System Prompt
    assert "30 Pesanan" in CONCIERGE_SYSTEM_PROMPT
    assert "50 Interaksi AI" in CONCIERGE_SYSTEM_PROMPT
    assert "15 Notifikasi" in CONCIERGE_SYSTEM_PROMPT
    assert "Whitelist Ads" in CONCIERGE_SYSTEM_PROMPT

    # Verifikasi dictionary deterministik
    resp = get_static_concierge_response("Berapa harga paket dan kuota langganan?")
    assert "Paket Trial (Gratis)" in resp
    assert "30 Pesanan Masuk" in resp
    assert "50 Interaksi AI Chatbot" in resp
    assert "15 Notifikasi WA Otomatis" in resp
    assert "Paket Berbayar (Starter / Pro)" in resp
    assert "Whitelist Ads FB" in resp
    assert "https://buzzerukm.adsolution.co.id/register" in resp


def test_official_bot_knowledge_base_onboarding_guide():
    """Memverifikasi panduan pengguna baru: asisten BoonPilot dan 6 Langkah Cepat Dashboard."""
    # Verifikasi System Prompt
    assert "BoonPilot" in CONCIERGE_SYSTEM_PROMPT
    assert "6 Langkah Cepat di Dashboard" in CONCIERGE_SYSTEM_PROMPT
    assert "Lengkapi Profil & Nama Toko" in CONCIERGE_SYSTEM_PROMPT
    assert "Masukkan Produk Perdana" in CONCIERGE_SYSTEM_PROMPT
    assert "Hubungkan Nomor WhatsApp Bisnis" in CONCIERGE_SYSTEM_PROMPT
    assert "Aktivasi Akun Pembayaran (QRIS)" in CONCIERGE_SYSTEM_PROMPT
    assert "Pasang Pixel" in CONCIERGE_SYSTEM_PROMPT
    assert "Jalankan Transaksi Uji Coba" in CONCIERGE_SYSTEM_PROMPT

    # Verifikasi dictionary deterministik
    resp = get_static_concierge_response("Saya baru daftar dan bingung cara mulai, ada panduan onboarding?")
    assert "Panduan Pengguna Baru (Onboarding Guide)" in resp
    assert "BoonPilot" in resp
    assert "sudut kanan bawah dashboard" in resp
    assert "6 Langkah Cepat di Dashboard" in resp
    assert "1. Lengkapi Profil & Nama Toko" in resp
    assert "2. Masukkan Produk Perdana" in resp
    assert "3. Hubungkan Nomor WhatsApp Bisnis" in resp
    assert "4. Aktivasi Akun Pembayaran (QRIS)" in resp
    assert "5. Pasang Pixel / Meta CAPI / GTM di menu Ads Tracking Pro" in resp
    assert "6. Jalankan Transaksi Uji Coba & Sebarkan Link Toko" in resp


@pytest.mark.asyncio
async def test_generate_concierge_reply_fallback_mode():
    """Memverifikasi bahwa generate_concierge_reply memberikan jawaban deterministik akurat saat offline / tanpa API key."""
    with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
        resp_kelebihan = await generate_concierge_reply("Apa keunggulan toko ini?")
        assert "Kelebihan Utama BoonTrack Shop" in resp_kelebihan

        resp_paket = await generate_concierge_reply("Berapa biaya langganan paket pro?")
        assert "Pilihan Paket Layanan" in resp_paket

        resp_guide = await generate_concierge_reply("Bagaimana langkah awal di dashboard?")
        assert "Panduan Pengguna Baru" in resp_guide

        resp_default = await generate_concierge_reply("Halo bot selamat siang")
        assert "AKTIVASI BT-XXXX" in resp_default


# =============================================================================
# 2. Audit Cepat Isolasi Statis & Menu Kategori
# =============================================================================

def test_static_tenant_memory_isolation_no_cache_leakage():
    """
    Memverifikasi tidak adanya shared memory / memory leakage antar-tenant:
    1. Mengubah objek context hasil cache tidak boleh mengubah cache internal.
    2. Mengubah context tenant A tidak boleh mempengaruhi context tenant B.
    3. DEFAULT_CAPABILITIES_BY_VERTICAL tidak boleh bermutasi.
    """
    tenant_context_resolver.clear_cache()

    row_a = {
        "id": "tenant-a-uuid",
        "slug": "tenant-a",
        "business_type": "PHYSICAL",
        "metadata": {"capabilities": {"shipping": True}}
    }
    ctx_a = build_context_from_dict(row_a)
    tenant_context_resolver.set_cached("tenant-a", ctx_a)

    # Ambil ctx_a dari cache dan coba lakukan mutasi kotor (tampering)
    cached_a = tenant_context_resolver.get_cached("tenant-a")
    assert cached_a is not None
    cached_a.capabilities["POLLUTED_KEY"] = True
    cached_a.metadata["TAMPERED"] = "LEAKED_VALUE"

    # Ambil kembali dari cache: harus bersih (tidak boleh terpolusi)
    fresh_a = tenant_context_resolver.get_cached("tenant-a")
    assert "POLLUTED_KEY" not in fresh_a.capabilities
    assert "TAMPERED" not in fresh_a.metadata

    # Pastikan DEFAULT_CAPABILITIES_BY_VERTICAL tetap murni
    assert "POLLUTED_KEY" not in DEFAULT_CAPABILITIES_BY_VERTICAL["PHYSICAL"]

    # Uji tenant B yang independen
    row_b = {
        "id": "tenant-b-uuid",
        "slug": "tenant-b",
        "business_type": "PHYSICAL",
        "metadata": {"capabilities": {"shipping": True}}
    }
    ctx_b = build_context_from_dict(row_b)
    tenant_context_resolver.set_cached("tenant-b", ctx_b)

    cached_b = tenant_context_resolver.get_cached("tenant-b")
    assert "POLLUTED_KEY" not in cached_b.capabilities
    assert cached_b.slug == "tenant-b"

    tenant_context_resolver.clear_cache()


def test_category_boundaries_retail_fashion():
    """Kategori Retail/Fashion (PHYSICAL): Mendukung shipping & varian, dilarang memiliki digital fulfillment & dine-in."""
    row = {"id": "t1", "slug": "fashion-store", "business_type": "PHYSICAL"}
    ctx = build_context_from_dict(row)

    assert has_capability(ctx, "shipping") is True
    assert has_capability(ctx, "variants") is True
    assert has_capability(ctx, "digital_fulfillment") is False
    assert has_capability(ctx, "dine_in") is False
    assert has_capability(ctx, "booking") is False

    buttons = get_welcome_buttons_for_category("PHYSICAL")
    assert "📦 Cek Katalog & Promo" in buttons
    assert "🚚 Cek Ongkir & Resi" in buttons
    assert "💬 Hubungi Live CS" in buttons

    # Mutasi list tombol tidak boleh merusak master dictionary
    buttons.append("HACKED_BUTTON")
    fresh_buttons = get_welcome_buttons_for_category("PHYSICAL")
    assert "HACKED_BUTTON" not in fresh_buttons


def test_category_boundaries_food_and_beverage():
    """Kategori F&B (FOOD_BEVERAGE / FOOD): Mendukung delivery, takeaway, dine-in; dilarang memiliki shipping ekspedisi reguler atau digital fulfillment."""
    row = {"id": "t2", "slug": "kopi-kenangan", "business_type": "FOOD_BEVERAGE"}
    ctx = build_context_from_dict(row)

    assert has_capability(ctx, "dine_in") is True
    assert has_capability(ctx, "takeaway") is True
    assert has_capability(ctx, "delivery") is True
    assert has_capability(ctx, "shipping") is False
    assert has_capability(ctx, "digital_fulfillment") is False
    assert has_capability(ctx, "booking") is False

    buttons = get_welcome_buttons_for_category("FOOD")
    assert "🛵 Pesan Antar (Delivery)" in buttons
    assert "🥡 Ambil di Resto (Takeaway)" in buttons
    assert "📍 Lokasi & Jam Dapur" in buttons


def test_category_boundaries_digital_products():
    """Kategori Digital (DIGITAL): Mendukung digital fulfillment; dilarang memiliki shipping ekspedisi fisik atau booking teknisi."""
    row = {"id": "t3", "slug": "ecourse-mastery", "business_type": "DIGITAL"}
    ctx = build_context_from_dict(row)

    assert has_capability(ctx, "digital_fulfillment") is True
    assert has_capability(ctx, "shipping") is False
    assert has_capability(ctx, "variants") is False
    assert has_capability(ctx, "booking") is False
    assert has_capability(ctx, "dine_in") is False

    buttons = get_welcome_buttons_for_category("DIGITAL")
    assert "⚡ Akses Download & Materi" in buttons
    assert "🔑 Kendala Akun & Lisensi" in buttons
    assert "📚 Kurikulum Produk" in buttons


def test_category_boundaries_field_and_pro_service():
    """Kategori Servis/Jasa (FIELD_SERVICE & PROFESSIONAL_SERVICE): Mendukung booking & jadwal; dilarang memiliki shipping ekspedisi barang fisik."""
    row_field = {"id": "t4", "slug": "servis-ac-pro", "business_type": "FIELD_SERVICE"}
    ctx_field = build_context_from_dict(row_field)

    assert has_capability(ctx_field, "booking") is True
    assert has_capability(ctx_field, "schedule") is True
    assert has_capability(ctx_field, "service_area") is True
    assert has_capability(ctx_field, "shipping") is False
    assert has_capability(ctx_field, "digital_fulfillment") is False

    buttons_field = get_welcome_buttons_for_category("FIELD_SERVICE")
    assert "📅 Jadwalkan Servis/Teknisi" in buttons_field
    assert "💰 Tarif & Area Layanan" in buttons_field
    assert "🛠️ Konsultasi CS" in buttons_field
