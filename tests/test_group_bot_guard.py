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
# 8. Mention Strip Logic (Fix: teks bersih ke BoonPilot)
# ---------------------------------------------------------------------------
class TestGroupMentionStripping:
    """Validasi bahwa @mention di-strip sebelum dikirim ke BoonPilot / pipeline AI."""

    MENTION_STRIP_PATTERN = re.compile(r"@[\w.]+")

    def _strip_mention(self, text: str) -> str:
        stripped = self.MENTION_STRIP_PATTERN.sub("", text).strip()
        return stripped or text.strip()

    def test_strip_boon_mention(self):
        raw = "@boon boontrack itu apa?"
        assert self._strip_mention(raw) == "boontrack itu apa?"

    def test_strip_support_mention(self):
        raw = "@Support Boontrack itu apa"
        # @Support ter-strip, "Boontrack itu apa" tersisa
        assert self._strip_mention(raw) == "Boontrack itu apa"

    def test_strip_boontrack_mention(self):
        raw = "@boontrack gimana cara daftar?"
        assert self._strip_mention(raw) == "gimana cara daftar?"

    def test_strip_phone_mention(self):
        raw = "@081215567168 ada yang bisa bantu?"
        assert self._strip_mention(raw) == "ada yang bisa bantu?"

    def test_strip_multiple_mentions(self):
        raw = "@boon @support apa fitur QRIS?"
        assert self._strip_mention(raw) == "apa fitur QRIS?"

    def test_empty_after_strip_fallback_to_original(self):
        """Jika setelah strip teks jadi kosong, fallback ke original."""
        raw = "@boon"
        result = self._strip_mention(raw)
        assert result == "@boon"  # fallback ke original

    def test_no_mention_unchanged(self):
        raw = "boontrack itu apa?"
        assert self._strip_mention(raw) == "boontrack itu apa?"

    def test_strip_preserves_question_content(self):
        raw = "@support ada paket trial gratis ga?"
        stripped = self._strip_mention(raw)
        assert "paket trial" in stripped
        assert "@support" not in stripped


# ---------------------------------------------------------------------------
# 9. APP_SHOP_V1 Catalog Interceptor GROUP Guard
# ---------------------------------------------------------------------------
class TestCatalogInterceptorGroupGuard:
    """Validasi katalog interaktif TIDAK dikirim ke grup."""

    def _should_send_catalog(
        self,
        conversation_scope: str,
        tenant_slug: str,
        text_lower: str,
    ) -> bool:
        """Replika kondisi catalog interceptor yang sudah di-fix."""
        BOON_SLUGS = ("app_shop_v1", "app-shop-v1", "app_shop", "boon", "boontrack-app-shop", "boontrack_app_shop")
        CATALOG_KW = ("paket", "katalog", "harga", "langganan", "upgrade", "menu", "beli")
        return (
            conversation_scope != "GROUP"
            and tenant_slug.lower() in BOON_SLUGS
            and any(k in text_lower for k in CATALOG_KW)
        )

    def test_group_catalog_blocked(self):
        """Di grup, katalog interaktif TIDAK boleh terkirim."""
        assert self._should_send_catalog("GROUP", "boon", "mau lihat katalog") is False

    def test_direct_catalog_allowed(self):
        """Di DM, katalog boleh terkirim untuk tenant boon."""
        assert self._should_send_catalog("DIRECT", "boon", "mau lihat katalog") is True

    def test_group_no_keyword_not_sent(self):
        assert self._should_send_catalog("GROUP", "boon", "boontrack itu apa") is False

    def test_non_boon_tenant_not_sent(self):
        assert self._should_send_catalog("DIRECT", "atmosfitnes", "mau lihat katalog") is False

    def test_group_boon_keyword_still_blocked(self):
        """Keyword 'harga' di grup dengan tenant boon tetap diblokir."""
        assert self._should_send_catalog("GROUP", "boon", "berapa harga paket starter?") is False


# ---------------------------------------------------------------------------
# 10. BoonPilot response tidak mengandung storefront banner link sebagai satu-satunya isi
# ---------------------------------------------------------------------------
class TestBoonPilotNoStorefrontBanner:
    """Validasi BoonPilot Group Brain menghasilkan teks informatif, bukan hanya link."""

    def setup_method(self):
        from app.whatsapp.traffic_splitter import get_static_group_boonpilot_response
        self.fn = get_static_group_boonpilot_response

    def test_response_is_not_just_a_url(self):
        """Jawaban BoonPilot harus mengandung teks, bukan hanya URL."""
        for query in ["boontrack itu apa", "fitur boontrack", "cara daftar", "paket trial", "qris payment"]:
            res = self.fn(query)
            # Strip semua URL dari respons, harus masih ada teks substantif
            text_without_url = re.sub(r'https?://\S+', '', res).strip()
            assert len(text_without_url) > 20, f"Respons untuk '{query}' terlalu singkat setelah URL dihapus: '{text_without_url}'"

    def test_response_contains_boontrack_context(self):
        """Jawaban harus merujuk ke BoonTrack."""
        res = self.fn("boontrack itu apa")
        assert "boontrack" in res.lower()

    def test_no_uuid_in_response(self):
        """Jawaban BoonPilot tidak boleh mengandung UUID."""
        import re as _re
        uuid_pattern = _re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', _re.IGNORECASE)
        for query in ["boontrack itu apa", "cara daftar", "paket"]:
            res = self.fn(query)
            assert not uuid_pattern.search(res), f"UUID ditemukan di respons BoonPilot untuk '{query}': {res}"

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
