"""tests/test_onlineboost_telegram_bot_separation.py
Unit tests verifying Telegram Bot separation of concerns:
- @onlineboostbot (token: 8788492843:AAEDoHaqbBSFWeA7HWoSmEYv0FytibL8yus) exclusively handles
  single-use invite link issuance and greetings for Supergroup OnlineBoost Batch 1 (-1004371114362).
- @boonshop_bot is isolated for storefront catalog & retail orders.
"""

import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ctwa_fulfillment_service import (
    create_telegram_single_use_invite_link,
    fulfill_onlineboost_ctwa_order,
    _ISSUED_TELEGRAM_LINKS_CACHE,
    DEFAULT_CTWA_CHAT_ID,
)
from app.services.telegram_commerce_service import handle_telegram_link_baru


ONLINEBOOST_TOKEN = "8788492843:AAEDoHaqbBSFWeA7HWoSmEYv0FytibL8yus"
SUPERGROUP_CHAT_ID = "-1004371114362"


@pytest.mark.asyncio
async def test_onlineboost_bot_token_and_supergroup_routing():
    """Verify create_telegram_single_use_invite_link routes exclusively to @onlineboostbot."""
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()
    order_id = "ORD-TEST-OB-BOT-001"
    expected_invite = "https://t.me/+onlineboost_batch1_singleuse"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "result": {
            "invite_link": expected_invite,
            "member_limit": 1,
            "expire_date": int(time.time()) + 86400,
            "creates_join_request": False,
            "creator": {
                "id": 8788492843,
                "is_bot": True,
                "first_name": "OnlineBoost",
                "username": "onlineboostbot",
            },
        },
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        invite_link = await create_telegram_single_use_invite_link(
            order_id=order_id,
            buyer_name="Peserta Test",
        )

        assert invite_link == expected_invite
        assert mock_post.called

        # Verify correct URL with @onlineboostbot token (NOT @boonshop_bot)
        call_url = mock_post.call_args[0][0]
        assert f"/bot{ONLINEBOOST_TOKEN}/createChatInviteLink" in call_url

        # Verify payload parameters
        payload = mock_post.call_args[1]["json"]
        assert payload["chat_id"] == SUPERGROUP_CHAT_ID
        assert payload["member_limit"] == 1
        assert payload["expire_date"] >= int(time.time()) + 86300
        assert payload["creates_join_request"] is False


@pytest.mark.asyncio
async def test_fulfillment_onlineboost_uses_onlineboost_token():
    """Verify fulfill_onlineboost_ctwa_order dispatches using @onlineboostbot token."""
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()
    order_id = "ORD-TEST-OB-FULFILL-002"
    expected_invite = "https://t.me/+onlineboost_fulfill_link"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "result": {
            "invite_link": expected_invite,
            "member_limit": 1,
        },
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa, \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_purchase", new_callable=AsyncMock):

        mock_post.return_value = mock_resp
        mock_wa.return_value = {"messages": [{"id": "wamid.TEST"}]}

        res = await fulfill_onlineboost_ctwa_order(
            order_id=order_id,
            buyer_name="Kak Budi",
            buyer_phone="6281234567890",
            amount=249000,
            tenant_id="onlineboost",
        )

        assert res["status"] == "SUCCESS"
        assert res["single_use_invite_link"] == expected_invite
        assert "t.me" in res["confirmation_message"]

        # Assert token in call URL is @onlineboostbot
        call_url = mock_post.call_args[0][0]
        assert f"/bot{ONLINEBOOST_TOKEN}/createChatInviteLink" in call_url


@pytest.mark.asyncio
async def test_fallback_link_baru_uses_onlineboost_token():
    """Verify fallback command 'LINK BARU' generates invite using @onlineboostbot token."""
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()
    expected_invite = "https://t.me/+onlineboost_refreshed_link"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "result": {
            "invite_link": expected_invite,
            "member_limit": 1,
        },
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        reply = await handle_telegram_link_baru(
            user_id=12345678,
            user_name="Budi",
            tenant_id="onlineboost",
        )

        assert "Tautan Undangan Baru Diterbitkan" in reply
        assert expected_invite in reply
        call_url = mock_post.call_args[0][0]
        assert f"/bot{ONLINEBOOST_TOKEN}/createChatInviteLink" in call_url

