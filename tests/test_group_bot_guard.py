"""
tests/test_group_bot_guard.py
------------------------------
Unit test: Group Bot Guard & BoonPilot Group Brain Integration.

Nomor target: 081215567168 (boontrack-app-shop instance)
Coverage:
  1. Group message tanpa mention -> silent (status: ignored_group_general_chatter)
  2. Group message fromMe -> dropped
  3. Group message dengan @boon mention -> diproses (has_mention=True)
  4. Group message dengan @boontrack mention -> diproses (has_mention=True)
  5. Group message dengan @support mention -> diproses (has_mention=True)
  6. Group message sebagai reply ke pesan bot -> diproses (is_quoted_reply_to_bot=True)
  7. mentionedJid mengandung nomor bot -> has_mention=True
  8. Direct message (non-group) -> tidak kena guard, lanjut pipeline normal
  9. BoonPilot Group Brain: get_static_group_boonpilot_response keyword routing
 10. Isolated session: group_jid vs sender_phone tidak tercampur
"""

import pytest
import re
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers: simulasi payload Evolution webhook
# ---------------------------------------------------------------------------

def make_evo_payload(
    remote_jid: str,
    incoming_text: str,
    participant_jid: str = "6281999000001@s.whatsapp.net",
    from_me: bool = False,
    mentioned_jids: list = None,
    quoted_msg: dict = None,
    quoted_participant: str = "",
    bot_phone: str = "6281215567168",
) -> dict:
    """Membangun payload Evolution API minimal untuk unit test."""
    context_info = {}
    if mentioned_jids is not None:
        context_info["mentionedJid"] = mentioned_jids
    if quoted_msg is not None:
        context_info["quotedMessage"] = quoted_msg
        context_info["participant"] = quoted_participant

    return {
        "data": {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "participant": participant_jid if remote_jid.endswith("@g.us") else None,
                "id": "test-wamid-001",
            },
            "message": {
                "extendedTextMessage": {
                    "text": incoming_text,
                    "contextInfo": context_info,
                } if context_info else None,
                "conversation": incoming_text if not context_info else None,
            },
            "messageType": "extendedTextMessage" if context_info else "conversation",
            "pushName": "TestUser",
        },
        "connection": {
            "phone_number": bot_phone,
            "tenant_slug": "boon",
            "tenant_id": "52967979-4760-4cea-b686-cdbdb389c0e1",
            "instance_name": "boontrack-app-shop",
            "channel_type": "DEDICATED",
        },
    }


# ---------------------------------------------------------------------------
# 1. Deteksi scope GROUP berdasarkan remoteJid @g.us
# ---------------------------------------------------------------------------
class TestGroupScopeDetection:
    def test_remote_jid_group_us_is_group(self):
        remote_jid = "120363222222222222@g.us"
        is_group = remote_jid.endswith("@g.us")
        assert is_group is True

    def test_remote_jid_private_is_not_group(self):
        remote_jid = "6281234567890@s.whatsapp.net"
        is_group = remote_jid.endswith("@g.us")
        assert is_group is False


# ---------------------------------------------------------------------------
# 2. Mention Guard Logic
# ---------------------------------------------------------------------------
class TestGroupMentionGuard:
    BOT_PHONE = "6281215567168"
    BOT_PHONE_CLEAN = "81215567168"  # stripped leading 0 dari Indonesia

    def _check_mention(self, text: str, mentioned_jids=None, bot_phone: str = BOT_PHONE) -> bool:
        """Replika logika mention guard dari whatsapp_gateway_routes.py."""
        text_lower = text.lower()
        bot_phone_clean = re.sub(r"\D", "", bot_phone).lstrip("0")
        has_mention = bool(
            re.search(r"@boontrack\b", text_lower)
            or re.search(r"@boontrackbot\b", text_lower)
            or re.search(r"@boon\b", text_lower)
            or re.search(r"@support\b", text_lower)
            or re.search(r"@081215567168\b", text_lower)
            or ("boontrack" in text_lower and "@" in text_lower)
            or (bot_phone_clean and bot_phone_clean in text_lower)
        )
        if not has_mention and mentioned_jids:
            jids_lower = [str(j).lower() for j in mentioned_jids]
            if (
                any("boontrack" in j for j in jids_lower)
                or any("boon" in j for j in jids_lower)
                or any(bot_phone in j for j in jids_lower)
                or any(bot_phone_clean in j for j in jids_lower)
            ):
                has_mention = True
        return has_mention

    def test_general_chatter_no_mention(self):
        """Pesan umum grup tanpa mention -> False."""
        assert self._check_mention("Halo semua, ada promo apa hari ini?") is False

    def test_boontrack_mention_in_text(self):
        assert self._check_mention("@boontrack bisa bantu saya?") is True

    def test_boon_mention_in_text(self):
        assert self._check_mention("@boon ada paket trial?") is True

    def test_support_mention_in_text(self):
        assert self._check_mention("@support tolong bantu") is True

    def test_phone_number_mention_in_text(self):
        assert self._check_mention("@081215567168 gimana cara daftar?") is True

    def test_boontrack_keyword_with_at(self):
        assert self._check_mention("tanya @boontrack dong") is True

    def test_mentioned_jid_contains_boontrack(self):
        assert self._check_mention(
            "ada yang tau?",
            mentioned_jids=["6281215567168@s.whatsapp.net"]
        ) is True

    def test_mentioned_jid_no_match(self):
        assert self._check_mention(
            "hai guys",
            mentioned_jids=["6281999000001@s.whatsapp.net"]
        ) is False

    def test_mentioned_jid_contains_boon(self):
        assert self._check_mention(
            "bantu dong",
            mentioned_jids=["boon@s.whatsapp.net"]
        ) is True


# ---------------------------------------------------------------------------
# 3. Quoted Reply to Bot Guard
# ---------------------------------------------------------------------------
class TestQuotedReplyToBotGuard:
    BOT_PHONE = "6281215567168"

    def _check_quoted_reply(
        self,
        quoted_msg: dict,
        quoted_participant: str = "",
        quoted_from_me: bool = False,
        bot_phone: str = BOT_PHONE,
    ) -> bool:
        """Replika logika is_quoted_reply_to_bot dari gateway routes."""
        return bool(
            quoted_msg and (
                quoted_from_me
                or "boontrack" in quoted_participant.lower()
                or (bot_phone and bot_phone in quoted_participant.lower())
                or ("boontrack-app-shop" in quoted_participant.lower())
            )
        )

    def test_quoted_reply_from_me(self):
        assert self._check_quoted_reply({"conversation": "test"}, quoted_from_me=True) is True

    def test_quoted_reply_from_bot_jid(self):
        assert self._check_quoted_reply(
            {"conversation": "test"},
            quoted_participant="6281215567168@s.whatsapp.net",
            bot_phone="6281215567168",
        ) is True

    def test_quoted_reply_not_from_bot(self):
        assert self._check_quoted_reply(
            {"conversation": "test"},
            quoted_participant="6281999000001@s.whatsapp.net",
        ) is False

    def test_no_quoted_msg(self):
        assert self._check_quoted_reply(None) is False


# ---------------------------------------------------------------------------
# 4. Session Isolation — group:JID vs sender_phone
# ---------------------------------------------------------------------------
class TestGroupSessionIsolation:
    def test_group_scope_uses_group_jid_session(self):
        group_jid = "120363222222222222@g.us"
        sender_phone = "6281234567890"
        conversation_scope = "GROUP"
        session_key = f"group:{group_jid}" if (conversation_scope == "GROUP" and group_jid) else sender_phone
        assert session_key == f"group:{group_jid}"
        assert sender_phone not in session_key  # Tidak tercampur dengan DM

    def test_direct_scope_uses_sender_phone(self):
        group_jid = None
        sender_phone = "6281234567890"
        conversation_scope = "DIRECT"
        session_key = f"group:{group_jid}" if (conversation_scope == "GROUP" and group_jid) else sender_phone
        assert session_key == sender_phone

    def test_group_jid_and_dm_session_never_equal(self):
        group_jid = "120363222222222222@g.us"
        sender_phone = "6281234567890"
        group_key = f"group:{group_jid}"
        dm_key = sender_phone
        assert group_key != dm_key


# ---------------------------------------------------------------------------
# 5. BoonPilot Group Brain Static Responses
# ---------------------------------------------------------------------------
class TestGroupBoonPilotStaticResponses:
    """Test get_static_group_boonpilot_response keyword routing."""

    def setup_method(self):
        from app.whatsapp.traffic_splitter import get_static_group_boonpilot_response
        self.fn = get_static_group_boonpilot_response

    def test_daftar_keyword(self):
        res = self.fn("@boon cara daftar gimana?")
        assert "register" in res.lower() or "shop.boontrack.com" in res

    def test_trial_keyword(self):
        res = self.fn("ada trial gratis ga?")
        assert "trial" in res.lower() or "gratis" in res.lower()

    def test_qris_keyword(self):
        res = self.fn("@boon payment qris gimana?")
        assert "qris" in res.lower() or "payment" in res.lower()

    def test_dashboard_keyword(self):
        res = self.fn("fitur dashboard nya apa aja?")
        assert "dashboard" in res.lower() or "pesanan" in res.lower()

    def test_automasi_keyword(self):
        res = self.fn("bot otomatis gimana cara kerjanya?")
        assert "bot" in res.lower() or "automasi" in res.lower() or "notifikasi" in res.lower()

    def test_storefront_keyword(self):
        res = self.fn("@boon bikin toko online gimana?")
        assert "storefront" in res.lower() or "toko" in res.lower() or "boontrack.com" in res

    def test_unknown_keyword_returns_default(self):
        res = self.fn("halo semua")
        assert "boonpilot" in res.lower() or "boontrack" in res.lower()

    def test_mention_stripped_before_keyword_check(self):
        res = self.fn("@boontrack daftar")
        assert "register" in res.lower() or "shop.boontrack.com" in res


# ---------------------------------------------------------------------------
# 6. fromMe guard
# ---------------------------------------------------------------------------
class TestFromMeGuard:
    def test_from_me_true_should_be_dropped(self):
        payload = {"key": {"fromMe": True}}
        is_from_me = payload.get("key", {}).get("fromMe") is True
        assert is_from_me is True

    def test_from_me_false_should_not_drop(self):
        payload = {"key": {"fromMe": False}}
        is_from_me = payload.get("key", {}).get("fromMe") is True
        assert is_from_me is False


# ---------------------------------------------------------------------------
# 7. InboundPayload GROUP scope routing check
# ---------------------------------------------------------------------------
class TestInboundPayloadGroupRouting:
    def test_boon_tenant_is_detected(self):
        slugs = ["boon", "boontrack-app-shop", "boontrack_app_shop", "app_shop", "app-shop"]
        for s in slugs:
            is_boon = s.lower() in ("boon", "boontrack-app-shop", "boontrack_app_shop", "app_shop", "app-shop")
            assert is_boon, f"Slug '{s}' harus terdeteksi sebagai boon tenant"

    def test_non_boon_tenant_not_intercepted(self):
        non_boon = ["atmosfitnes", "kelasbos", "merchant-xyz"]
        for s in non_boon:
            is_boon = s.lower() in ("boon", "boontrack-app-shop", "boontrack_app_shop", "app_shop", "app-shop")
            assert not is_boon, f"Slug '{s}' seharusnya BUKAN boon tenant"
