import pytest
import asyncio
from unittest.mock import MagicMock, patch
from app.services.unified_conversation_service import unified_conversation_engine

@pytest.mark.asyncio
async def test_solusi_ads_greeting_has_no_menu_appended():
    """Memverifikasi bahwa greeting solusi-ads tidak ditempeli 'Silakan pilih menu cepat berikut'."""
    custom_greeting = (
        "Halo Kak! Selamat datang di Solusi Ads Official. 👋\n"
        "Kami siap bantu scale-up omset toko kakak lewat Meta Ads, Shopee Ads, TikTok Ads, dan Creator Affiliate.\n\n"
        "Sebelum mulai, boleh bantu lengkapi data singkat ini kak?\n"
        "• Nama:\n"
        "• Domisili:\n"
        "• Nama Toko:\n"
        "• Link Toko (TikTok / Shopee):\n"
        "• Omset Rata-rata per Bulan:\n\n"
        "Setelah ini tim konsultan kami akan langsung review toko kakak!"
    )
    mock_details = {
        "tenant": {
            "name": "Solusi Ads Official",
            "category": "CREATOR_AGENCY",
            "metadata": {
                "show_menu_on_greeting": False,
                "greeting_message": custom_greeting,
                "quick_replies": [],
                "static_buttons": [],
            }
        },
        "persona": {
            "welcome_message": custom_greeting
        }
    }

    with patch("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug", return_value=mock_details), \
         patch("app.services.unified_conversation_service.get_tenant_products_from_db", return_value=("Solusi Ads Official", [])), \
         patch("app.services.whatsapp_service.get_supabase", return_value=None):

        res = await unified_conversation_engine.process_chat(
            tenant_slug="solusi-ads",
            message="Halo",
            sender_id="6285113636165",
            sender_name="Penguji Solusi Ads",
            channel="whatsapp",
        )

        assert res["success"] is True
        assert res["action"] == "GREETING"
        assert res["quick_actions"] == []
        assert "Silakan pilih menu cepat berikut untuk memulai" not in res["reply"]
        assert "Rate Card & Paket Endorse" not in res["reply"]
        assert res["reply"] == custom_greeting


@pytest.mark.asyncio
async def test_default_tenant_without_custom_greeting_appends_menu():
    """Memverifikasi bahwa tenant default tanpa custom greeting tetap mendapatkan menu cepat default."""
    mock_details = {
        "tenant": {
            "name": "Toko Kopi Santai",
            "category": "CULINARY",
            "metadata": {}
        },
        "persona": {}
    }

    with patch("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug", return_value=mock_details), \
         patch("app.services.unified_conversation_service.get_tenant_products_from_db", return_value=("Toko Kopi Santai", [])), \
         patch("app.services.whatsapp_service.get_supabase", return_value=None):

        res = await unified_conversation_engine.process_chat(
            tenant_slug="toko-kopi-santai",
            message="Halo",
            sender_id="6281234567890",
            sender_name="Customer Baru",
            channel="whatsapp",
        )

        assert res["success"] is True
        assert res["action"] == "SHOW_MENU"
        assert "Silakan pilih menu cepat berikut untuk memulai" in res["reply"]
        assert len(res["quick_actions"]) > 0


@pytest.mark.asyncio
async def test_custom_greeting_with_explicit_show_menu_true():
    """Memverifikasi bahwa jika tenant kustom menyalakan show_menu_on_greeting = True, menu cepat dimunculkan."""
    mock_details = {
        "tenant": {
            "name": "Agensi Custom",
            "category": "CREATOR_AGENCY",
            "metadata": {
                "greeting_message": "Halo kak! Selamat datang di Agensi Custom.",
                "show_menu_on_greeting": True
            }
        },
        "persona": {}
    }

    with patch("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug", return_value=mock_details), \
         patch("app.services.unified_conversation_service.get_tenant_products_from_db", return_value=("Agensi Custom", [])), \
         patch("app.services.whatsapp_service.get_supabase", return_value=None):

        res = await unified_conversation_engine.process_chat(
            tenant_slug="agensi-custom",
            message="Hai",
            sender_id="6281234567891",
            sender_name="Client",
            channel="whatsapp",
        )

        assert res["success"] is True
        assert res["action"] == "SHOW_MENU"
        assert "Silakan pilih menu cepat berikut untuk memulai" in res["reply"]
        assert "Rate Card & Paket Endorse" in res["reply"]
