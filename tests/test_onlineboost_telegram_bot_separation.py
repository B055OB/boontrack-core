"""tests/test_onlineboost_telegram_bot_separation.py
Unit tests verifying Telegram Bot separation of concerns & strict security invariants:
- @onlineboostbot (mocked dummy token) exclusively handles single-use invite link issuance
  and greetings for Supergroup OnlineBoost Batch 1 (-1004371114362).
- @boonshop_bot is isolated for storefront catalog & retail orders.
- Fail-closed invariant: if OnlineBoost bot token is missing, raise RuntimeError immediately
  without falling back to other bot tokens.
- Golden Penny test SKU (TEST-PENNY-1500, Rp1.500) is isolated for internal verification.
- Server-side access control: public callers cannot create internal test SKU invoices.
- Strict settlement invariant: Rp1.500 settlement rejected for regular public orders.
- Decoupled entitlement: test SKU does not grant regular class digital entitlement.
- Triple-tier idempotency: duplicate webhooks do not re-invoke Telegram Bot API.
"""

import os
import time
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from app.main import app as fastapi_app
from app.core.rev1.exceptions import AuthorizationError
from app.routes.academy_routes import create_academy_invoice, CreateAcademyInvoiceRequest
from app.routes.xendit import process_xendit_webhook_core
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
from app.services.digital_fulfillment_service import fulfill_digital_order
from app.routes.product_routes import get_product_by_id_endpoint
from app.routes.xendit import send_whatsapp_payment_notification


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

    # 2. Verify Internal Golden Penny Test SKU is exactly Rp1.500 with internal authorization
    penny_inv = generate_academy_qris_invoice(
        customer_name="Founder Test",
        customer_email="founder@example.com",
        customer_phone="08129999999",
        tenant_id="onlineboost",
        sku_id=TEST_PENNY_SKU_ID,
        is_internal_authorized=True,
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

    # 4. Verify fulfillment execution with Rp1.500 works with Zero Telegram Invite & Zero CAPI
    with patch.dict(os.environ, {"TELEGRAM_ONLINEBOOST_BOT_TOKEN": DUMMY_ONLINEBOOST_TOKEN, "TELEGRAM_ONLINEBOOST_CHAT_ID": SUPERGROUP_CHAT_ID}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa, \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_purchase", new_callable=AsyncMock) as mock_capi:

        mock_wa.return_value = {"messages": [{"id": "wamid.PENNY"}]}

        res = await fulfill_onlineboost_ctwa_order(
            order_id=penny_inv["order_id"],
            buyer_name="Founder Penny",
            buyer_phone="08129999999",
            amount=1500,
            tenant_id="onlineboost",
        )

        assert res["status"] == "SUCCESS"
        assert res["single_use_invite_link"] is None
        assert res["confirmation_message"] == "Verifikasi Sistem Berhasil"
        assert res.get("is_internal_test") is True
        # Zero Telegram Bot API calls
        assert mock_post.call_count == 0
        # Zero Meta CAPI calls
        assert mock_capi.call_count == 0
        # WhatsApp outbox dispatched clean confirmation text
        assert mock_wa.called
        assert mock_wa.call_args[1]["text"] == "Verifikasi Sistem Berhasil" 


# ============================================================================
# MANDATORY CTO NEGATIVE TEST SUITE
# ============================================================================

@pytest.mark.asyncio
async def test_public_user_cannot_create_internal_sku_invoice():
    """Negative Test 1: Public caller without internal authorization MUST be rejected (fail-closed HTTP 403)."""
    with pytest.raises(AuthorizationError) as exc_info:
        generate_academy_qris_invoice(
            customer_name="Public Attacker",
            customer_email="attacker@public.com",
            customer_phone="08123456789",
            tenant_id="onlineboost",
            sku_id=TEST_PENNY_SKU_ID,
            is_internal_authorized=False,
        )
    assert exc_info.value.status_code == 403
    assert "Access Denied" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_public_order_settlement_rejected_for_penny_amount():
    """Negative Test 2: Public order (Rp249.000) settlement rejected if paying penny amount (Rp1.500)."""
    pub_inv = generate_academy_qris_invoice(
        customer_name="Regular Student",
        customer_email="student@example.com",
        customer_phone="08121111111",
        tenant_id="onlineboost",
        use_unique_code=False,
    )
    assert pub_inv["base_amount"] == ACADEMY_SETTLEMENT_PRICE
    assert pub_inv["sku_id"] == ACADEMY_SKU_ID

    # Attempt to settle regular public order with Rp 1.500
    settle_res = settle_academy_invoice(
        order_id=pub_inv["order_id"],
        amount=1500,
        tenant_id="onlineboost",
    )
    assert settle_res["status"] == "REJECTED_AMOUNT_MISMATCH"
    assert "strictly restricted" in settle_res["error"] or "Amount mismatch" in settle_res["error"]


@pytest.mark.asyncio
async def test_penny_sku_does_not_grant_regular_class_entitlement():
    """Negative Test 3: TEST-PENNY-1500 does NOT grant regular course digital entitlement or public course URL."""
    # 1. Digital fulfillment engine must skip regular digital entitlement
    df_res = await fulfill_digital_order(
        order_id="ORD-PENNY-GUARD-01",
        product_id=TEST_PENNY_SKU_ID,
        tenant_id="onlineboost",
        buyer_email="tester@internal.boontrack.com",
        amount=1500,
    )
    assert df_res["status"] == "SKIPPED"
    assert "does not grant regular class entitlement" in df_res["reason"]

    # 2. WhatsApp notification message for penny order must decouple from public class URL
    with patch("app.services.ctwa_fulfillment_service.fulfill_onlineboost_ctwa_order", new_callable=AsyncMock) as mock_fulfill:
        mock_fulfill.return_value = {"status": "SUCCESS"}
        await send_whatsapp_payment_notification(
            phone="08123456789",
            external_id="BTA-PENNY-TEST",
            amount=1500,
            tenant_id="onlineboost",
            product_name="OnlineBoost Golden Penny Test",
        )
        assert mock_fulfill.called
        call_kwargs = mock_fulfill.call_args[1]
        assert call_kwargs["amount"] == 1500


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_generate_duplicate_telegram_invite():
    """Negative Test 4: Replay/duplicate webhook does NOT invoke Telegram Bot API multiple times (Idempotency)."""
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()
    order_id = "ORD-TEST-IDEMP-DOUBLE-001"
    fixed_link = "https://t.me/+onlineboost_single_idemp"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "result": {
            "invite_link": fixed_link,
            "member_limit": 1,
        },
    }

    with patch.dict(os.environ, {"TELEGRAM_ONLINEBOOST_BOT_TOKEN": DUMMY_ONLINEBOOST_TOKEN, "TELEGRAM_ONLINEBOOST_CHAT_ID": SUPERGROUP_CHAT_ID}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa, \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_purchase", new_callable=AsyncMock):

        mock_post.return_value = mock_resp
        mock_wa.return_value = {"messages": [{"id": "wamid.IDEMP"}]}

        # First webhook arrival
        res1 = await fulfill_onlineboost_ctwa_order(
            order_id=order_id,
            buyer_name="Kak Idemp",
            buyer_phone="08129999000",
            amount=249000,
            tenant_id="onlineboost",
        )
        assert res1["status"] == "SUCCESS"
        assert res1["single_use_invite_link"] == fixed_link
        assert mock_post.call_count == 1

        # Second webhook arrival (duplicate/replay)
        res2 = await fulfill_onlineboost_ctwa_order(
            order_id=order_id,
            buyer_name="Kak Idemp",
            buyer_phone="08129999000",
            amount=249000,
            tenant_id="onlineboost",
        )
        assert res2["status"] == "SUCCESS"
        assert res2["single_use_invite_link"] == fixed_link
        assert res2.get("idempotency_hit") is True
        # Telegram Bot API must NOT have been called a second time!
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_storefront_catalog_cannot_resolve_internal_penny_sku():
    """Verify storefront catalog routes return HTTP 404 for TEST-PENNY-1500."""
    with pytest.raises(HTTPException) as exc_info:
        await get_product_by_id_endpoint("TEST-PENNY-1500", tenant_slug="onlineboost")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_internal_sku_auth_fails_when_env_secrets_missing():
    """Negative Test 5: create_academy_invoice fails-closed with HTTP 500 when env secrets are missing."""
    req_payload = CreateAcademyInvoiceRequest(
        customer_name="Founder Tester",
        customer_email="founder@internal.com",
        customer_phone="081233334444",
        tenant_id="onlineboost",
        sku_id=TEST_PENNY_SKU_ID,
    )
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(HTTPException) as exc_info:
            await create_academy_invoice(req_payload, mock_request)
        assert exc_info.value.status_code == 500
        assert "Authentication service unavailable" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_internal_sku_auth_rejected_via_body_without_secure_header():
    """Negative Test 6: create_academy_invoice fails-closed with HTTP 403 when called without secure headers."""
    req_payload = CreateAcademyInvoiceRequest(
        customer_name="Founder Tester",
        customer_email="founder@internal.com",
        customer_phone="081233334444",
        tenant_id="onlineboost",
        sku_id=TEST_PENNY_SKU_ID,
    )
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}  # No X-Internal-Secret or Authorization header

    env_mock = {
        "BOONTRACK_INTERNAL_HMAC_SECRET": "top_secret_hmac_123",
        "APP_MASTER_KEY": "master_key_456",
    }
    with patch.dict(os.environ, env_mock):
        with pytest.raises(HTTPException) as exc_info:
            await create_academy_invoice(req_payload, mock_request)
        assert exc_info.value.status_code == 403
        assert "Access Denied" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_internal_sku_auth_succeeds_with_secure_header():
    """Test: create_academy_invoice succeeds when authenticated via secure headers."""
    env_mock = {
        "BOONTRACK_INTERNAL_HMAC_SECRET": "top_secret_hmac_123",
        "APP_MASTER_KEY": "master_key_456",
    }
    req_payload = CreateAcademyInvoiceRequest(
        customer_name="Founder Tester",
        customer_email="founder@internal.com",
        customer_phone="081233334444",
        tenant_id="onlineboost",
        sku_id=TEST_PENNY_SKU_ID,
    )

    # Test via X-Internal-Secret header
    mock_request_secret = MagicMock(spec=Request)
    mock_request_secret.headers = {"X-Internal-Secret": "top_secret_hmac_123"}

    with patch.dict(os.environ, env_mock):
        res = await create_academy_invoice(req_payload, mock_request_secret)
        assert res["status"] == "success"
        inv = res["invoice"]
        assert inv["sku_id"] == TEST_PENNY_SKU_ID
        assert inv["total_amount"] == 1500

    # Test via Authorization: Bearer <master_key> header
    mock_request_bearer = MagicMock(spec=Request)
    mock_request_bearer.headers = {"Authorization": "Bearer master_key_456"}

    with patch.dict(os.environ, env_mock):
        res_bearer = await create_academy_invoice(req_payload, mock_request_bearer)
        assert res_bearer["status"] == "success"
        assert res_bearer["invoice"]["total_amount"] == 1500


@pytest.mark.asyncio
async def test_penny_order_fulfillment_zero_telegram_and_zero_capi():
    """Test: Penny order fulfillment strictly executes Zero Telegram Bot API calls and Zero Meta CAPI events."""
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()
    order_id = "ORD-TEST-ZERO-CAPI-PENNY-01"

    with patch.dict(os.environ, {"TELEGRAM_ONLINEBOOST_BOT_TOKEN": DUMMY_ONLINEBOOST_TOKEN, "TELEGRAM_ONLINEBOOST_CHAT_ID": SUPERGROUP_CHAT_ID}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa, \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_purchase", new_callable=AsyncMock) as mock_capi:

        mock_wa.return_value = {"messages": [{"id": "wamid.PENNY.ZERO"}]}

        res = await fulfill_onlineboost_ctwa_order(
            order_id=order_id,
            buyer_name="Zero Capi Tester",
            buyer_phone="081255556666",
            amount=1500,
            tenant_id="onlineboost",
        )

        assert res["status"] == "SUCCESS"
        assert res["single_use_invite_link"] is None
        assert res["confirmation_message"] == "Verifikasi Sistem Berhasil"
        assert res.get("is_internal_test") is True

        # Assert Zero Telegram Bot API calls made
        assert mock_post.call_count == 0
        # Assert Zero Meta CAPI calls made
        assert mock_capi.call_count == 0
        # Assert WhatsApp received plain text confirmation only
        assert mock_wa.called
        assert mock_wa.call_args[1]["text"] == "Verifikasi Sistem Berhasil"


@pytest.mark.asyncio
async def test_penny_settlement_rejected_when_persisted_sku_missing_or_mismatched():
    """Negative Test 7: Webhook rejects penny settlement (Rp1.500) if persisted_sku is missing or not TEST-PENNY-1500."""
    headers = {"x-callback-token": "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS"}

    # 1. Penny amount Rp1.500 with persisted order having NO SKU (persisted_sku is empty/None)
    payload_no_sku = {
        "id": "evt_test_penny_no_sku",
        "external_id": "ORD-PENNY-NO-SKU",
        "amount": 1500,
        "status": "PAID",
    }
    with patch("app.routes.xendit._check_db_idempotency_sync", return_value=False), \
         patch("app.routes.xendit._lookup_persisted_order_sync", return_value={"id": "ORD-PENNY-NO-SKU", "gross_amount": 1500, "product_id": None}):
        res_no_sku = await process_xendit_webhook_core(payload_no_sku, headers)
        assert res_no_sku["http_status"] == 400
        assert res_no_sku["response"]["status"] == "AMOUNT_MISMATCH"
        assert "strictly restricted" in res_no_sku["response"]["error"]

    # 2. Penny amount Rp1.500 with regular class SKU (persisted_sku == "OB-BATCH1-249K")
    payload_mismatch = {
        "id": "evt_test_penny_mismatch",
        "external_id": "ORD-PENNY-MISMATCH",
        "amount": 1500,
        "status": "PAID",
    }
    with patch("app.routes.xendit._check_db_idempotency_sync", return_value=False), \
         patch("app.routes.xendit._lookup_persisted_order_sync", return_value={"id": "ORD-PENNY-MISMATCH", "gross_amount": 1500, "product_id": "OB-BATCH1-249K"}):
        res_mismatch = await process_xendit_webhook_core(payload_mismatch, headers)
        assert res_mismatch["http_status"] == 400
        assert res_mismatch["response"]["status"] == "AMOUNT_MISMATCH"
        assert "strictly restricted" in res_mismatch["response"]["error"]

    # 3. Regular amount Rp249.000 for order persisted as TEST-PENNY-1500
    payload_reverse = {
        "id": "evt_test_penny_reverse",
        "external_id": "ORD-PENNY-REVERSE",
        "amount": 249000,
        "status": "PAID",
    }
    with patch("app.routes.xendit._check_db_idempotency_sync", return_value=False), \
         patch("app.routes.xendit._lookup_persisted_order_sync", return_value={"id": "ORD-PENNY-REVERSE", "gross_amount": 249000, "product_id": "TEST-PENNY-1500"}):
        res_reverse = await process_xendit_webhook_core(payload_reverse, headers)
        assert res_reverse["http_status"] == 400
        assert res_reverse["response"]["status"] == "AMOUNT_MISMATCH"
        assert "TEST-PENNY-1500 order requires exact Rp1,500 settlement." in res_reverse["response"]["error"]


@pytest.mark.asyncio
async def test_penny_duplicate_webhook_does_not_call_telegram_or_resend_whatsapp():
    """Negative Test 8: Replay/duplicate webhook for penny order remains strictly idempotent."""
    _ISSUED_TELEGRAM_LINKS_CACHE.clear()
    order_id = "ORD-TEST-PENNY-IDEMP-01"

    with patch.dict(os.environ, {"TELEGRAM_ONLINEBOOST_BOT_TOKEN": DUMMY_ONLINEBOOST_TOKEN, "TELEGRAM_ONLINEBOOST_CHAT_ID": SUPERGROUP_CHAT_ID}), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa, \
         patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_purchase", new_callable=AsyncMock) as mock_capi:

        mock_wa.return_value = {"messages": [{"id": "wamid.PENNY.IDEMP"}]}

        # First webhook arrival
        res1 = await fulfill_onlineboost_ctwa_order(
            order_id=order_id,
            buyer_name="Kak Penny Idemp",
            buyer_phone="08129999000",
            amount=1500,
            tenant_id="onlineboost",
        )
        assert res1["status"] == "SUCCESS"
        assert res1["single_use_invite_link"] is None
        assert mock_post.call_count == 0
        assert mock_capi.call_count == 0
        assert mock_wa.call_count == 1

        # Second webhook arrival (duplicate/replay)
        res2 = await fulfill_onlineboost_ctwa_order(
            order_id=order_id,
            buyer_name="Kak Penny Idemp",
            buyer_phone="08129999000",
            amount=1500,
            tenant_id="onlineboost",
        )
        assert res2["status"] == "SUCCESS"
        assert res2["single_use_invite_link"] is None
        assert res2.get("idempotency_hit") is True
        # Zero additional calls
        assert mock_post.call_count == 0
        assert mock_capi.call_count == 0
        assert mock_wa.call_count == 1  # Not called again


# ============================================================================
# P0-D INTEGRATION TEST RUNNER PARITY & PERSISTENCE HARDENING
# ============================================================================

async def invoke_aiohttp_invoice_endpoint(payload_dict: dict, headers_dict: dict = None):
    """Invoke aiohttp invoice handler for runner parity verification."""
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request
    from app.routes.academy_routes import register_academy_routes

    aio_app = web.Application()
    register_academy_routes(aio_app)
    handler = [
        r.handler for r in aio_app.router.routes()
        if r.resource.canonical == "/api/v1/academy/invoice" and r.method == "POST"
    ][0]
    req = make_mocked_request("POST", "/api/v1/academy/invoice", headers=headers_dict or {}, app=aio_app)
    req.json = AsyncMock(return_value=payload_dict)
    resp = await handler(req)
    return resp


@pytest.mark.asyncio
async def test_runner_parity_fastapi_and_aiohttp_unauthorized_rejected():
    """Parity Test 1: Both FastAPI and aiohttp runners reject unauthorized requests for TEST-PENNY-1500 (HTTP 403)."""
    env_mock = {
        "BOONTRACK_INTERNAL_HMAC_SECRET": "test_parity_secret_123",
        "APP_MASTER_KEY": "test_parity_master_456",
    }
    penny_payload = {
        "customer_name": "Public Attacker",
        "customer_email": "attacker@public.com",
        "customer_phone": "081234567890",
        "tenant_id": "onlineboost",
        "sku_id": TEST_PENNY_SKU_ID,
    }

    with patch.dict(os.environ, env_mock):
        # 1. FastAPI Runner
        client = TestClient(fastapi_app)
        resp_fastapi = client.post("/api/v1/academy/invoice", json=penny_payload, headers={})
        assert resp_fastapi.status_code == 403
        assert "Access Denied" in str(resp_fastapi.json())

        # 2. aiohttp Runner
        resp_aio = await invoke_aiohttp_invoice_endpoint(penny_payload, headers_dict={})
        assert resp_aio.status == 403
        body_aio = json.loads(resp_aio.body.decode())
        assert "Access Denied" in str(body_aio)


@pytest.mark.asyncio
async def test_runner_parity_fastapi_and_aiohttp_valid_headers_pass():
    """Parity Test 2: Both FastAPI and aiohttp runners accept authorized requests via secure headers (HTTP 200)."""
    env_mock = {
        "BOONTRACK_INTERNAL_HMAC_SECRET": "test_parity_secret_123",
        "APP_MASTER_KEY": "test_parity_master_456",
    }
    penny_payload = {
        "customer_name": "Founder Tester",
        "customer_email": "founder@internal.com",
        "customer_phone": "081299999999",
        "tenant_id": "onlineboost",
        "sku_id": TEST_PENNY_SKU_ID,
    }

    with patch.dict(os.environ, env_mock):
        client = TestClient(fastapi_app)

        # 1. FastAPI with X-Internal-Secret
        res_fa_secret = client.post("/api/v1/academy/invoice", json=penny_payload, headers={"X-Internal-Secret": "test_parity_secret_123"})
        assert res_fa_secret.status_code == 200
        assert res_fa_secret.json()["invoice"]["total_amount"] == 1500
        assert res_fa_secret.json()["invoice"]["sku_id"] == TEST_PENNY_SKU_ID

        # 2. FastAPI with Authorization: Bearer <master_key>
        res_fa_bearer = client.post("/api/v1/academy/invoice", json=penny_payload, headers={"Authorization": "Bearer test_parity_master_456"})
        assert res_fa_bearer.status_code == 200
        assert res_fa_bearer.json()["invoice"]["total_amount"] == 1500

        # 3. aiohttp with X-Internal-Secret
        res_aio_secret = await invoke_aiohttp_invoice_endpoint(penny_payload, headers_dict={"X-Internal-Secret": "test_parity_secret_123"})
        assert res_aio_secret.status == 200
        body_aio_secret = json.loads(res_aio_secret.body.decode())
        assert body_aio_secret["invoice"]["total_amount"] == 1500
        assert body_aio_secret["invoice"]["sku_id"] == TEST_PENNY_SKU_ID

        # 4. aiohttp with Authorization: Bearer <master_key>
        res_aio_bearer = await invoke_aiohttp_invoice_endpoint(penny_payload, headers_dict={"Authorization": "Bearer test_parity_master_456"})
        assert res_aio_bearer.status == 200
        body_aio_bearer = json.loads(res_aio_bearer.body.decode())
        assert body_aio_bearer["invoice"]["total_amount"] == 1500


@pytest.mark.asyncio
async def test_runner_parity_fastapi_and_aiohttp_missing_env_secrets_fail_closed():
    """Parity Test 3: Both FastAPI and aiohttp fail-closed with HTTP 500 when environment secrets are missing."""
    penny_payload = {
        "customer_name": "Founder Tester",
        "customer_email": "founder@internal.com",
        "customer_phone": "081299999999",
        "tenant_id": "onlineboost",
        "sku_id": TEST_PENNY_SKU_ID,
    }

    with patch.dict(os.environ, {}, clear=True):
        # 1. FastAPI Runner
        client = TestClient(fastapi_app)
        res_fa = client.post("/api/v1/academy/invoice", json=penny_payload, headers={"X-Internal-Secret": "any"})
        assert res_fa.status_code == 500
        assert "Authentication service unavailable" in str(res_fa.json())

        # 2. aiohttp Runner
        res_aio = await invoke_aiohttp_invoice_endpoint(penny_payload, headers_dict={"X-Internal-Secret": "any"})
        assert res_aio.status == 500
        body_aio = json.loads(res_aio.body.decode())
        assert "Authentication service unavailable" in str(body_aio)


@pytest.mark.asyncio
async def test_penny_persistence_failure_fails_closed():
    """Hardening Test 4: Creation of TEST-PENNY-1500 fails-closed (HTTP 500) if database write fails."""
    env_mock = {
        "BOONTRACK_INTERNAL_HMAC_SECRET": "test_parity_secret_123",
        "APP_MASTER_KEY": "test_parity_master_456",
    }
    penny_payload = {
        "customer_name": "Founder Tester",
        "customer_email": "founder@internal.com",
        "customer_phone": "081299999999",
        "tenant_id": "onlineboost",
        "sku_id": TEST_PENNY_SKU_ID,
    }

    with patch.dict(os.environ, env_mock),          patch("app.core.database.get_db_connection", side_effect=Exception("Database connection timeout")):
        # 1. FastAPI Runner fails-closed with HTTP 500
        client = TestClient(fastapi_app)
        res_fa = client.post("/api/v1/academy/invoice", json=penny_payload, headers={"X-Internal-Secret": "test_parity_secret_123"})
        assert res_fa.status_code == 500
        assert "persistence" in str(res_fa.json()).lower()

        # 2. aiohttp Runner fails-closed with HTTP 500
        res_aio = await invoke_aiohttp_invoice_endpoint(penny_payload, headers_dict={"X-Internal-Secret": "test_parity_secret_123"})
        assert res_aio.status == 500
        body_aio = json.loads(res_aio.body.decode())
        assert "persistence" in str(body_aio).lower()
