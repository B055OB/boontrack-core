"""tests/test_onlineboost_telegram_bot_separation.py
Unit tests verifying Telegram Bot separation of concerns & strict security invariants:
- @onlineboostbot (mocked dummy token) exclusively handles single-use invite link issuance
  and greetings for Supergroup OnlineBoost Batch 1 (-1004371114362).
- @boonshop_bot is isolated for storefront catalog & retail orders.
- Fail-closed invariant: if OnlineBoost bot token is missing, raise RuntimeError immediately
  without falling back to other bot tokens.
- Golden Penny test SKU (TEST-PENNY-1500, Rp1.500) is isolated for internal verification.
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
from app.services.academy_service import (
    generate_academy_qris_invoice,
    settle_academy_invoice,
    TEST_PENNY_SKU_ID,
    TEST_PENNY_SKU_NAME,
    TEST_PENNY_PRICE,
    ACADEMY_SKU_ID,
    ACADEMY_SETTLEMENT_PRICE,
)


DUMMY_ONLINEBOOST_TOKEN = "123456:dummy_test_token"
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
                "id": 123456,
                "is_bot": True,
                "first_name": "OnlineBoost",
                "username": "onlineboostbot",
            },
        },
    }

    with patch.dict(os.environ, {"TELEGRAM_ONLINEBOOST_BOT_TOKEN": DUMMY_ONLINEBOOST_TOKEN, "TELEGRAM_ONLINEBOOST_CHAT_ID": SUPERGROUP_CHAT_ID}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        invite_link = await create_telegram_single_use_invite_link(
            order_id=order_id,
            buyer_name="Peserta Test",
        )

        assert invite_link == expected_invite
        assert mock_post.called

        # Verify correct URL with @onlineboostbot token (NOT @boonshop_bot)
        call_url = mock_post.call_args[0][0]
        assert f"/bot{DUMMY_ONLINEBOOST_TOKEN}/createChatInviteLink" in call_url

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

    with patch.dict(os.environ, {"TELEGRAM_ONLINEBOOST_BOT_TOKEN": DUMMY_ONLINEBOOST_TOKEN, "TELEGRAM_ONLINEBOOST_CHAT_ID": SUPERGROUP_CHAT_ID}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
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
        assert f"/bot{DUMMY_ONLINEBOOST_TOKEN}/createChatInviteLink" in call_url


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

    with patch.dict(os.environ, {"TELEGRAM_ONLINEBOOST_BOT_TOKEN": DUMMY_ONLINEBOOST_TOKEN, "TELEGRAM_ONLINEBOOST_CHAT_ID": SUPERGROUP_CHAT_ID}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        reply = await handle_telegram_link_baru(
            user_id=12345678,
            user_name="Budi",
            tenant_id="onlineboost",
        )

        assert "Tautan Undangan Baru Diterbitkan" in reply
        assert expected_invite in reply
        call_url = mock_post.call_args[0][0]
        assert f"/bot{DUMMY_ONLINEBOOST_TOKEN}/createChatInviteLink" in call_url


@pytest.mark.asyncio
async def test_onlineboost_bot_fail_closed_when_token_missing():
    """Verify strict fail-closed: missing OnlineBoost token raises RuntimeError and prevents fallback."""
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()
    order_id = "ORD-TEST-FAIL-CLOSED-001"

    # Set other bot tokens in environment to prove that system NEVER falls back to them
    env_mock = {
        "TELEGRAM_BOT_TOKEN": "7896599904:boonshop_fallback_token",
        "TELEGRAM_ACADEMY_BOT_TOKEN": "9999999999:academy_fallback_token",
    }

    with patch.dict(os.environ, env_mock, clear=True), \
         patch("app.core.channels.telegram.get_dynamic_telegram_bot_token", side_effect=Exception("Database resolution disabled")):
        with pytest.raises(RuntimeError, match="OnlineBoost bot token is missing or not configured. Fallback to other bot tokens is strictly prohibited."):
            await create_telegram_single_use_invite_link(
                order_id=order_id,
                buyer_name="Peserta Test",
            )


@pytest.mark.asyncio
async def test_golden_penny_test_sku_isolation():
    """Verify Golden Penny (TEST-PENNY-1500) SKU isolation and fulfillment."""
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()

    # 1. Verify Public SKU remains unchanged at Rp249.000
    public_inv = generate_academy_qris_invoice(
        customer_name="Public Customer",
        customer_email="public@example.com",
        customer_phone="08123456789",
        tenant_id="onlineboost",
        use_unique_code=False,
    )
    assert public_inv["sku_id"] == ACADEMY_SKU_ID
    assert public_inv["base_amount"] == ACADEMY_SETTLEMENT_PRICE
    assert public_inv["total_amount"] == 249000
    assert public_inv["is_internal_only"] is False

    # 2. Verify Internal Golden Penny Test SKU is exactly Rp1.500
    penny_inv = generate_academy_qris_invoice(
        customer_name="Founder Test",
        customer_email="founder@example.com",
        customer_phone="08129999999",
        tenant_id="onlineboost",
        sku_id=TEST_PENNY_SKU_ID,
    )
    assert penny_inv["sku_id"] == TEST_PENNY_SKU_ID
    assert penny_inv["sku"] == TEST_PENNY_SKU_NAME
    assert penny_inv["base_amount"] == TEST_PENNY_PRICE
    assert penny_inv["total_amount"] == 1500
    assert penny_inv["unique_code"] == 0
    assert penny_inv["is_internal_only"] is True

    # 3. Verify settlement accepts exact Rp1.500 and transitions status to PAID
    settle_res = settle_academy_invoice(
        order_id=penny_inv["order_id"],
        amount=1500,
        tenant_id="onlineboost",
    )
    assert settle_res["status"] in ("PAID", "ALREADY_SETTLED")

    # 4. Verify fulfillment execution with Rp1.500 works seamlessly
    expected_invite = "https://t.me/+onlineboost_penny_success"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "result": {
            "invite_link": expected_invite,
            "member_limit": 1,
        },
    }

    with patch.dict(os.environ, {"TELEGRAM_ONLINEBOOST_BOT_TOKEN": DUMMY_ONLINEBOOST_TOKEN, "TELEGRAM_ONLINEBOOST_CHAT_ID": SUPERGROUP_CHAT_ID}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa, \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_purchase", new_callable=AsyncMock):

        mock_post.return_value = mock_resp
        mock_wa.return_value = {"messages": [{"id": "wamid.PENNY"}]}

        res = await fulfill_onlineboost_ctwa_order(
            order_id=penny_inv["order_id"],
            buyer_name="Founder Penny",
            buyer_phone="08129999999",
            amount=1500,
            tenant_id="onlineboost",
        )

        assert res["status"] == "SUCCESS"
        assert res["single_use_invite_link"] == expected_invite
        assert "1.500" in res["confirmation_message"]
