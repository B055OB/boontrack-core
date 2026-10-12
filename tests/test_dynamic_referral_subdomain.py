"""tests/test_dynamic_referral_subdomain.py
Unit & Integration tests for Dynamic Referral & Subdomain URL Generator pada WhatsApp Bot BoonPilot.

Requirements:
1. Skema VIP Subdomain (Kang Sakti / buzzerukm):
   - register_url -> https://{subdomain}.boontrack.com/register (bukan fallback ke shop.boontrack.com)
   - demo_url -> https://{subdomain}.boontrack.com/p/{product_slug}
2. Skema Standard Referral Link (Affiliate reguler lainnya):
   - register_url -> https://shop.boontrack.com/register?ref={slug}
   - demo_url -> https://shop.boontrack.com/{slug}/p/{product_slug} (atau binding demo_url)
3. Custom Subdomain / Whitelabel Partners (dict metadata).
4. Integrasi resolve_official_bot_dual_role pada group scope WhatsApp.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.affiliate_service import resolve_dynamic_referral_urls
from app.services.official_support_router import resolve_official_bot_dual_role


# =============================================================================
# 1. Unit Tests: resolve_dynamic_referral_urls
# =============================================================================

class TestDynamicReferralUrlGenerator:

    def test_vip_subdomain_buzzerukm_direct_slug(self):
        """Untuk kasus Kang Sakti (buzzerukm), tautan pendaftaran wajib ke buzzerukm.boontrack.com/register."""
        urls = resolve_dynamic_referral_urls(affiliate_slug_or_id="buzzerukm")
        assert urls["register_url"] == "https://buzzerukm.boontrack.com/register"
        assert urls["subdomain"] == "buzzerukm"
        assert urls["has_custom_subdomain"] is True
        assert "shop.boontrack.com/register" not in urls["register_url"]

    def test_vip_subdomain_buzzerukm_with_product_slug(self):
        """VIP Subdomain dengan product_slug menghasilkan demo URL ber-subdomain."""
        urls = resolve_dynamic_referral_urls(
            affiliate_slug_or_id="buzzerukm",
            product_slug="ctwa-mastery-7day",
        )
        assert urls["register_url"] == "https://buzzerukm.boontrack.com/register"
        assert urls["demo_url"] == "https://buzzerukm.boontrack.com/p/ctwa-mastery-7day"
        assert urls["has_custom_subdomain"] is True

    def test_custom_subdomain_affiliate_dict(self):
        """Affiliate dengan custom subdomain whitelabel (misal: partner VIP)."""
        affiliate_data = {
            "has_custom_subdomain": True,
            "subdomain": "vipmafia",
            "slug": "vipmafia",
        }
        urls = resolve_dynamic_referral_urls(
            affiliate_data=affiliate_data,
            product_slug="secret-course",
        )
        assert urls["register_url"] == "https://vipmafia.boontrack.com/register"
        assert urls["demo_url"] == "https://vipmafia.boontrack.com/p/secret-course"
        assert urls["has_custom_subdomain"] is True

    def test_regular_affiliate_standard_query_param(self):
        """Affiliate reguler (bukan VIP subdomain) wajib menggunakan format query param https://shop.boontrack.com/register?ref={slug}."""
        urls = resolve_dynamic_referral_urls(
            affiliate_slug_or_id="hendraty474",
            product_slug="bundle-ebook",
        )
        assert urls["register_url"] == "https://shop.boontrack.com/register?ref=hendraty474"
        assert urls["demo_url"] == "https://shop.boontrack.com/hendraty474/p/bundle-ebook"
        assert urls["has_custom_subdomain"] is False

    def test_regular_affiliate_onlineboost_ob(self):
        """Affiliate ob (OnlineBoost) menggunakan format standar query param."""
        urls = resolve_dynamic_referral_urls(affiliate_slug_or_id="ob")
        assert urls["register_url"] == "https://shop.boontrack.com/register?ref=ob"
        assert urls["has_custom_subdomain"] is False

    def test_channel_binding_buzzerukm_group(self):
        """Simulasi konteks grup WhatsApp Kang Sakti (120363430879517540@g.us)."""
        mock_binding = {
            "id": "70b4872c-3b19-4425-a6d6-4ee126548b19",
            "community_source_id": "120363430879517540@g.us",
            "affiliate_id": "buzzerukm",
            "demo_url": "https://shop.boontrack.com/buzzerukm/p/ctwa-mastery-7day",
            "metadata": {
                "register_url": "https://buzzerukm.boontrack.com/register",
                "fallback_register": "https://buzzerukm.boontrack.com/register",
            },
            "is_active": True,
        }
        urls = resolve_dynamic_referral_urls(
            group_jid="120363430879517540@g.us",
            channel_binding=mock_binding,
        )
        assert urls["register_url"] == "https://buzzerukm.boontrack.com/register"
        assert urls["demo_url"] == "https://shop.boontrack.com/buzzerukm/p/ctwa-mastery-7day"
        assert urls["has_custom_subdomain"] is True

    def test_channel_binding_regular_affiliate_group(self):
        """Simulasi konteks grup WhatsApp Affiliate reguler (ob)."""
        mock_binding = {
            "id": "7b0e67d7-0c7f-4f8e-ab82-bcc0aa825a2c",
            "community_source_id": "1203630248292839@g.us",
            "affiliate_id": "ob",
            "demo_url": "https://shop.boontrack.com/onlineboost/p/starter-pack",
            "metadata": {"test": True},
            "is_active": True,
        }
        urls = resolve_dynamic_referral_urls(
            group_jid="1203630248292839@g.us",
            channel_binding=mock_binding,
        )
        assert urls["register_url"] == "https://shop.boontrack.com/register?ref=ob"
        assert urls["demo_url"] == "https://shop.boontrack.com/onlineboost/p/starter-pack"
        assert urls["has_custom_subdomain"] is False

    def test_default_fallback_no_affiliate(self):
        """Fallback umum jika tanpa afiliasi dan tanpa binding komunitas."""
        urls = resolve_dynamic_referral_urls()
        assert urls["register_url"] == "https://shop.boontrack.com/register"
        assert urls["demo_url"] == "https://shop.boontrack.com/boon"
        assert urls["has_custom_subdomain"] is False


# =============================================================================
# 2. Integration Tests: resolve_official_bot_dual_role pada Group Scope
# =============================================================================

class TestOfficialSupportRouterIntegration:

    @pytest.mark.asyncio
    async def test_group_greeting_uses_buzzerukm_subdomain(self):
        """Salam sapaan sederhana di grup buzzerukm harus memuat https://buzzerukm.boontrack.com/register."""
        mock_binding = {
            "id": "70b4872c-3b19-4425-a6d6-4ee126548b19",
            "community_source_id": "120363430879517540@g.us",
            "affiliate_id": "buzzerukm",
            "demo_url": "https://shop.boontrack.com/buzzerukm/p/ctwa-mastery-7day",
            "metadata": {"register_url": "https://buzzerukm.boontrack.com/register"},
            "is_active": True,
        }

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [mock_binding]

        with patch("app.services.official_support_router.get_supabase", return_value=mock_supabase), \
             patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase):
            result = await resolve_official_bot_dual_role(
                incoming_text="halo",
                sender_phone="6285816332926",
                conversation_scope="GROUP",
                group_jid="120363430879517540@g.us",
            )

        assert result["status"] == "success"
        assert result["role"] == "SALES_REP_GROUP"
        assert result["register_url"] == "https://buzzerukm.boontrack.com/register"
        assert "https://buzzerukm.boontrack.com/register" in result["reply_text"]
        assert "shop.boontrack.com/register?ref=" not in result["reply_text"]

    @pytest.mark.asyncio
    async def test_group_ai_sales_rep_prompt_and_reply_append(self):
        """Pertanyaan spesifik di grup mengoper register_url subdomain ke prompt AI dan fallback append."""
        mock_binding = {
            "id": "70b4872c-3b19-4425-a6d6-4ee126548b19",
            "community_source_id": "120363430879517540@g.us",
            "affiliate_id": "buzzerukm",
            "demo_url": "https://shop.boontrack.com/buzzerukm/p/ctwa-mastery-7day",
            "metadata": {"register_url": "https://buzzerukm.boontrack.com/register"},
            "is_active": True,
        }

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [mock_binding]

        captured_prompt = {}

        async def fake_ai_reply(text, image_base64=None, mime_type=None, custom_system_prompt=None):
            captured_prompt["prompt"] = custom_system_prompt
            return "Halo kak, di BoonTrack checkout WhatsApp serba otomatis!"

        with patch("app.services.official_support_router.get_supabase", return_value=mock_supabase), \
             patch("app.services.affiliate_service.get_supabase", return_value=mock_supabase), \
             patch("app.whatsapp.traffic_splitter.generate_group_boonpilot_reply", side_effect=fake_ai_reply):
            result = await resolve_official_bot_dual_role(
                incoming_text="@boon bagaimana alur checkout kurir di BoonTrack?",
                sender_phone="6285816332926",
                conversation_scope="GROUP",
                group_jid="120363430879517540@g.us",
            )

        assert result["status"] == "success"
        assert result["register_url"] == "https://buzzerukm.boontrack.com/register"
        # Prompt AI harus berisi tautan pendaftaran subdomain
        assert "https://buzzerukm.boontrack.com/register" in captured_prompt["prompt"]
        # Balasan final wajib memiliki tautan pendaftaran subdomain
        assert "https://buzzerukm.boontrack.com/register" in result["reply_text"]
