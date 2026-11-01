"""tests/test_handover_intent_and_group_scope.py
Unit tests verifying tightened handover intent detection and group conversation scope protection:
1. Strict multi-word explicit intent requirement (no loose single-word triggers like 'manusia', 'admin', 'cs', 'orang').
2. Casual tech/AI/marketing discussions never trigger handover.
3. Group conversation scope (conversation_scope="GROUP") is strictly exempt from handover and pause locks.
4. WhatsApp inbound processing routes group discussions cleanly to BoonPilot without locking sessions to HUMAN_ACTIVE.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.grounding import (
    is_handover_intent,
    HANDOVER_HUMAN_KEYWORDS,
    HANDOVER_INTENT_PATTERNS,
    HANDOVER_TRANSITION_REPLY,
)
from app.routes.whatsapp_gateway_routes import (
    check_and_handle_session_handover_and_toggle,
    process_inbound_message,
    InboundPayload,
)


class TestHandoverIntentDetectionTightened:
    """Verifikasi bahwa deteksi intent handover ke CS manusia hanya merespons frasa eksplisit."""

    def test_explicit_positive_handover_phrases(self):
        positive_phrases = [
            "bicara dengan manusia",
            "bicara sama manusia",
            "hubungkan ke manusia",
            "hubungkan dengan manusia",
            "minta cs manusia",
            "mau cs manusia",
            "mau admin manusia",
            "bicara langsung",
            "mau bicara langsung",
            "hubungkan saya dengan admin",
            "tolong sambungkan ke cs",
            "panggil admin dong",
            "Mau bicara langsung dengan orang",
            "Bisa hubungi orang sekarang?",
            "Saya mau ngobrol sama admin",
            "bantuan manusia",
            "live cs",
            "human cs",
            "chat owner",
            "chat admin",
            "Tolong hubungkan saya dengan customer service",
            "Mau admin dong",
            "Mau cs dong",
        ]
        for phrase in positive_phrases:
            assert is_handover_intent(phrase) is True, f"Failed to match positive intent: '{phrase}'"

    def test_casual_discussion_negative_cases(self):
        """Kata 'manusia', 'orang', 'admin', 'cs' dalam konteks diskusi santai/teknologi/iklan TIDAK boleh memicu handover."""
        negative_phrases = [
            "bagus asli ada manusia atau pakai ai",
            "...bagus asli ada manusia atau pakai ai...",
            "iklan fb bagusnya pakai foto manusia atau animasi?",
            "apakah produk ini cocok untuk orang dewasa?",
            "saya admin toko sebelah yang mau order",
            "berapa orang yang bisa ikut webinar?",
            "cs 1.6 game favorit saya",
            "apakah ai bisa menggantikan pekerjaan manusia di masa depan?",
            "owner rekening ini bank bca ya kak?",
            "halo kak mau tanya harga produk",
            "bisa kirim ke surabaya hari ini?",
            "apakah sistem ini otomatis atau manual?",
        ]
        for phrase in negative_phrases:
            assert is_handover_intent(phrase) is False, f"False positive triggered for: '{phrase}'"

    def test_single_word_negative_cases(self):
        """Kata tunggal tanpa frasa intensi tidak boleh memicu handover."""
        single_words = ["manusia", "orang", "admin", "cs", "owner", "pemilik"]
        for word in single_words:
            assert is_handover_intent(word) is False, f"False positive triggered for single word: '{word}'"

    def test_empty_or_none_text(self):
        assert is_handover_intent("") is False
        assert is_handover_intent(None) is False


class TestCheckAndHandleSessionHandoverGroupScope:
    """Verifikasi bahwa check_and_handle_session_handover_and_toggle mengecualikan scope GROUP."""

    @pytest.mark.asyncio
    async def test_group_scope_returns_none_and_does_not_mutate_db(self):
        tenant = "boon"
        phone = "6281234567890"

        with patch("app.routes.whatsapp_gateway_routes.get_supabase") as mock_sb:
            mock_client = MagicMock()
            mock_sb.return_value = mock_client

            # Pesan diskusi di grup yang memuat kata 'manusia'
            res = await check_and_handle_session_handover_and_toggle(
                tenant_slug=tenant,
                sender_phone=phone,
                incoming_text="...bagus asli ada manusia atau pakai ai...",
                sender_name="Member Group",
                conversation_scope="GROUP",
            )

            assert res is None, "Group scope should return None"
            # Pastikan tidak ada mutasi DB yang mengunci sesi ke HUMAN_ACTIVE
            mock_client.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_group_scope_exempts_even_explicit_handover_phrase(self):
        """Di dalam grup, permintaan handover personal tidak boleh mengunci grup ke status HUMAN_ACTIVE."""
        tenant = "boon"
        phone = "6281234567890"

        with patch("app.routes.whatsapp_gateway_routes.get_supabase") as mock_sb:
            mock_client = MagicMock()
            mock_sb.return_value = mock_client

            res = await check_and_handle_session_handover_and_toggle(
                tenant_slug=tenant,
                sender_phone=phone,
                incoming_text="bicara dengan manusia",
                sender_name="Member Group",
                conversation_scope="GROUP",
            )

            assert res is None
            mock_client.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_direct_scope_casual_discussion_does_not_trigger_handover(self):
        tenant = "boon"
        phone = "6281234567890"

        with patch("app.routes.whatsapp_gateway_routes.get_supabase") as mock_sb:
            mock_client = MagicMock()
            mock_sb.return_value = mock_client
            mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=None)

            res = await check_and_handle_session_handover_and_toggle(
                tenant_slug=tenant,
                sender_phone=phone,
                incoming_text="...bagus asli ada manusia atau pakai ai...",
                sender_name="Direct Customer",
                conversation_scope="DIRECT",
            )

            assert res is None

    @pytest.mark.asyncio
    async def test_direct_scope_explicit_phrase_triggers_handover(self):
        tenant = "boon"
        phone = "6281234567890"

        with patch("app.routes.whatsapp_gateway_routes.get_supabase") as mock_sb:
            mock_client = MagicMock()
            mock_sb.return_value = mock_client
            mock_table = MagicMock()
            mock_client.table.return_value = mock_table
            mock_table.upsert.return_value.execute.return_value = MagicMock(data=[])
            mock_table.update.return_value.or_().eq().execute.return_value = MagicMock(data=[])

            res = await check_and_handle_session_handover_and_toggle(
                tenant_slug=tenant,
                sender_phone=phone,
                incoming_text="Mau bicara langsung dengan manusia dong",
                sender_name="Direct Customer",
                conversation_scope="DIRECT",
            )

            assert res is not None
            assert res.get("handled") is True
            assert res.get("action") == "HANDOVER_TO_HUMAN"
            assert res.get("bot_paused") is True
            assert res.get("reply_text") == HANDOVER_TRANSITION_REPLY


class TestProcessInboundMessageGroupRouting:
    """Verifikasi integrasi gateway saat pesan grup masuk."""

    @pytest.mark.asyncio
    async def test_group_message_with_manusia_routes_to_boonpilot_not_handover(self):
        payload = InboundPayload(
            tenant_slug="boon",
            sender_phone="6281999000001",
            message_body="@boon ...bagus asli ada manusia atau pakai ai...",
            sender_name="Budi Group",
            conversation_scope="GROUP",
            group_jid="120363222222222222@g.us",
        )

        with patch("app.routes.whatsapp_gateway_routes.onboarding_service.get_tenant_details_by_slug") as mock_details, \
             patch("app.whatsapp.traffic_splitter.generate_group_boonpilot_reply", new_callable=AsyncMock) as mock_boonpilot:

            mock_details.return_value = {
                "tenant": {"name": "BoonTrack Official", "tier": "SCALE", "is_bot_active": True},
                "persona": {"bot_strategy": "boonpilot"},
            }
            mock_boonpilot.return_value = "BoonPilot: Keduanya saling melengkapi! AI untuk respon cepat, manusia untuk sentuhan personal."

            res = await process_inbound_message(payload)

            assert res.get("status") == "success"
            assert res.get("conversation_scope") == "GROUP"
            assert res.get("group_jid") == "120363222222222222@g.us"
            assert res.get("bot_strategy") in ("boonpilot_group", "SALES_REP_GROUP")
            assert "BoonPilot:" in res.get("reply_text", "")
            # Pastikan BUKAN template auto-handover
            assert HANDOVER_TRANSITION_REPLY not in res.get("reply_text", "")
            assert res.get("bot_paused") is not True
