"""tests/test_unified_conversation_engine.py
Unit tests untuk Unified Conversation Engine, 6 Kategori Welcome Buttons, dan Zero-Hallucination Guardrail.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.unified_conversation_service import (
    unified_conversation_engine,
    normalize_business_category,
    get_welcome_buttons_for_category,
    CATEGORY_WELCOME_BUTTONS,
    EMPTY_CATALOG_MESSAGE,
    UNKNOWN_PRODUCT_MESSAGE,
)

client = TestClient(app)


def test_business_category_normalization():
    """Memvalidasi normalisasi string input ke 6 kategori bisnis resmi."""
    assert normalize_business_category("physical") == "PHYSICAL"
    assert normalize_business_category("PHYSICAL_RETAIL") == "PHYSICAL"
    assert normalize_business_category("retail") == "PHYSICAL"

    assert normalize_business_category("FOOD") == "FOOD"
    assert normalize_business_category("fnb_culinary") == "FOOD"
    assert normalize_business_category("resto") == "FOOD"

    assert normalize_business_category("FIELD_SERVICE") == "FIELD_SERVICE"
    assert normalize_business_category("kuras_toren") == "FIELD_SERVICE"
    assert normalize_business_category("teknisi") == "FIELD_SERVICE"

    assert normalize_business_category("PROFESSIONAL_SERVICE") == "PROFESSIONAL_SERVICE"
    assert normalize_business_category("pro_service") == "PROFESSIONAL_SERVICE"
    assert normalize_business_category("konsultan") == "PROFESSIONAL_SERVICE"

    assert normalize_business_category("DIGITAL") == "DIGITAL"
    assert normalize_business_category("digital_product") == "DIGITAL"
    assert normalize_business_category("course") == "DIGITAL"

    assert normalize_business_category("CREATOR_AGENCY") == "CREATOR_AGENCY"
    assert normalize_business_category("talent_management") == "CREATOR_AGENCY"
    assert normalize_business_category("influencer") == "CREATOR_AGENCY"

    # Default fallback
    assert normalize_business_category(None) == "PHYSICAL"
    assert normalize_business_category("") == "PHYSICAL"


def test_six_business_categories_static_welcome_buttons():
    """Memvalidasi 3 tombol statis untuk masing-masing dari 6 kategori bisnis."""
    expected_categories = [
        "PHYSICAL", "FOOD", "FIELD_SERVICE", "PROFESSIONAL_SERVICE", "DIGITAL", "CREATOR_AGENCY"
    ]
    for cat in expected_categories:
        buttons = get_welcome_buttons_for_category(cat)
        assert len(buttons) == 3, f"Kategori {cat} harus memiliki tepat 3 tombol statis"
        assert buttons == CATEGORY_WELCOME_BUTTONS[cat]

    # Cek spesifik sesuai permintaan PRD
    assert CATEGORY_WELCOME_BUTTONS["PHYSICAL"] == [
        "📦 Cek Katalog & Promo", "🚚 Cek Ongkir & Resi", "💬 Hubungi Live CS"
    ]
    assert CATEGORY_WELCOME_BUTTONS["FOOD"] == [
        "🛵 Pesan Antar (Delivery)", "🥡 Ambil di Resto (Takeaway)", "📍 Lokasi & Jam Dapur"
    ]
    assert CATEGORY_WELCOME_BUTTONS["FIELD_SERVICE"] == [
        "📅 Jadwalkan Servis/Teknisi", "💰 Tarif & Area Layanan", "🛠️ Konsultasi CS"
    ]
    assert CATEGORY_WELCOME_BUTTONS["PROFESSIONAL_SERVICE"] == [
        "📝 Jadwal Konsultasi/Janji Temu", "📋 Portofolio & Brief", "🚗 Simulasi/Paket Layanan"
    ]
    assert CATEGORY_WELCOME_BUTTONS["DIGITAL"] == [
        "⚡ Akses Download & Materi", "🔑 Kendala Akun & Lisensi", "📚 Kurikulum Produk"
    ]
    assert CATEGORY_WELCOME_BUTTONS["CREATOR_AGENCY"] == [
        "📊 Rate Card & Paket Endorse", "📦 Kirim Brief/Sampel", "📅 Jadwal Live Talent"
    ]


@pytest.mark.asyncio
async def test_initial_greeting_returns_three_welcome_buttons():
    """Memvalidasi saat sapaan awal, bot langsung merespons dengan 3 welcome buttons sesuai kategori."""
    mock_tenant_details = {
        "tenant": {"name": "Resto Sedap", "category": "FOOD"},
        "persona": {"welcome_message": "Halo! Selamat datang di Resto Sedap."},
    }

    with patch("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug", return_value=mock_tenant_details), \
         patch("app.services.unified_conversation_service.get_tenant_products_from_db", return_value=("Resto Sedap", [{"title": "Nasi Goreng", "price": 25000}])):

        res = await unified_conversation_engine.process_chat(
            tenant_slug="resto-sedap",
            message="Halo kak",
            sender_id="user_123",
            channel="webchat",
        )

        assert res["success"] is True
        assert res["business_category"] == "FOOD"
        assert res["quick_actions"] == CATEGORY_WELCOME_BUTTONS["FOOD"]
        assert "1. 🛵 Pesan Antar (Delivery)" in res["reply"]
        assert "2. 🥡 Ambil di Resto (Takeaway)" in res["reply"]
        assert "3. 📍 Lokasi & Jam Dapur" in res["reply"]


@pytest.mark.asyncio
async def test_zero_hallucination_guard_empty_catalog():
    """Memvalidasi guardrail saat katalog kosong: dilarang mengarang produk & alihkan ke CS unassigned."""
    mock_tenant_details = {
        "tenant": {"name": "Toko Baru", "category": "PHYSICAL"},
        "persona": {},
    }

    with patch("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug", return_value=mock_tenant_details), \
         patch("app.services.unified_conversation_service.get_tenant_products_from_db", return_value=("Toko Baru", [])), \
         patch("app.services.rotary_routing_service.rotary_routing_service.ensure_conversation_and_mark_unassigned") as mock_unassigned:

        mock_unassigned.return_value = {"status": "unassigned"}

        res = await unified_conversation_engine.process_chat(
            tenant_slug="toko-baru",
            message="Apakah ada baju warna hitam?",
            sender_id="user_456",
            channel="webchat",
        )

        assert res["success"] is True
        assert res["reply"] == EMPTY_CATALOG_MESSAGE
        assert res["action"] == "CS_HANDOVER"
        assert res["unassigned_triggered"] is True
        mock_unassigned.assert_called_once()
        call_kwargs = mock_unassigned.call_args[1]
        assert call_kwargs["tenant_id"] == "toko-baru"
        assert call_kwargs["reason"] == "EMPTY_CATALOG_HANDOVER"


@pytest.mark.asyncio
async def test_zero_hallucination_guard_unlisted_product_inquiry():
    """Memvalidasi guardrail saat pelanggan menanyakan produk di luar database."""
    mock_tenant_details = {
        "tenant": {"name": "Kuras Toren Jaya", "category": "FIELD_SERVICE"},
        "persona": {},
    }
    # Hanya ada layanan kuras toren di database
    real_catalog = [
        {"title": "Kuras Toren 500L", "price": 150000, "description": "Kuras tangki air 500 liter"},
        {"title": "Kuras Toren 1000L", "price": 200000, "description": "Kuras tangki air 1000 liter"}
    ]

    with patch("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug", return_value=mock_tenant_details), \
         patch("app.services.unified_conversation_service.get_tenant_products_from_db", return_value=("Kuras Toren Jaya", real_catalog)), \
         patch("app.services.rotary_routing_service.rotary_routing_service.ensure_conversation_and_mark_unassigned") as mock_unassigned:

        mock_unassigned.return_value = {"status": "unassigned"}

        # User menanyakan produk yang sama sekali tidak ada di katalog (misal: "sepatu sneakers")
        res = await unified_conversation_engine.process_chat(
            tenant_slug="kuras-toren-jaya",
            message="Apakah ada jual sepatu sneakers ori?",
            sender_id="user_789",
            channel="webchat",
        )

        assert res["success"] is True
        assert res["reply"] == UNKNOWN_PRODUCT_MESSAGE
        assert res["action"] == "CS_HANDOVER"
        assert res["unassigned_triggered"] is True
        mock_unassigned.assert_called_once()
        call_kwargs = mock_unassigned.call_args[1]
        assert call_kwargs["tenant_id"] == "kuras-toren-jaya"
        assert "UNKNOWN_PRODUCT_QUERY" in call_kwargs["reason"]


def test_core_api_v1_chat_endpoint_integration():
    """Memvalidasi endpoint POST /api/v1/chat di boontrack-core terhubung ke unified engine."""
    mock_tenant_details = {
        "tenant": {"name": "Agency Pro", "category": "CREATOR_AGENCY"},
        "persona": {"welcome_message": "Halo! Selamat datang di Agency Pro."},
    }

    with patch("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug", return_value=mock_tenant_details), \
         patch("app.services.unified_conversation_service.get_tenant_products_from_db", return_value=("Agency Pro", [{"title": "Paket Endorse IG", "price": 5000000}])), \
         patch("app.services.whatsapp_service.safe_log_to_supabase_messages"):

        response = client.post(
            "/api/v1/chat",
            json={
                "tenant_slug": "agency-pro",
                "message": "Halo min",
                "session_id": "sess_test_99",
                "user_name": "Prospek Talent"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["slug"] == "agency-pro"
        assert data["business_category"] == "CREATOR_AGENCY"
        assert data["quick_actions"] == CATEGORY_WELCOME_BUTTONS["CREATOR_AGENCY"]
        assert "1. 📊 Rate Card & Paket Endorse" in data["reply"]
