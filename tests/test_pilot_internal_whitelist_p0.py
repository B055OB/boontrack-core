"""tests/test_pilot_internal_whitelist_p0.py
Preflight Regression Test Suite for P0-A Pilot Isolation & Server-Side Allowlist.

Security Invariants Verified:
1. Global Strict Hold Precedence: When ONLINEBOOST_PAYMENT_STRICT_HOLD is active (default),
   ALL payment creation is blocked fail-closed, even for whitelisted numbers.
2. Missing or Invalid Allowlist Fails Closed: When hold is false but PILOT_INTERNAL_WHITELIST
   is missing, empty, or unparseable, payment creation remains blocked.
3. Unauthorized Customer Isolation: In pilot mode, only numbers explicitly in PILOT_INTERNAL_WHITELIST
   can reach live payment creation. Unauthorized callers remain strictly held.
4. Robust Digit Normalization: Formats (+62, 08xx, dashes, spaces) match correctly against allowlist.
5. Privacy Compliance: Customer phone numbers are masked in audit logs (never plaintext).
6. Gateway Integration Guards: CTWA Gatekeeper, Node 2 Fast-Path, and Academy Bot (State 1 & Route C)
   all enforce the server-side allowlist before invoking payment gateways or DB order mutations.
"""

import os
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.academy_service import (
    is_onlineboost_payment_held,
    mask_phone_for_log,
    generate_fast_path_xendit_qris_batch1,
    academy_bot,
)
from app.services.ctwa_state_engine import ctwa_state_engine


def test_phone_masking_for_audit_logs():
    """Verify customer phone numbers are properly masked for audit logs."""
    assert mask_phone_for_log("6288226098088") == "6288****088"
    assert mask_phone_for_log("+62 812-3456-7890") == "6281****890"
    assert mask_phone_for_log("088226098088") == "6288****088"
    assert mask_phone_for_log(None) == "[EMPTY]"
    assert mask_phone_for_log("") == "[EMPTY]"
    assert mask_phone_for_log("123") == "***"


def test_global_strict_hold_blocks_all_even_if_whitelisted():
    """Invariant 1: When global strict hold is active, 100% of callers are held."""
    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "true",
        "PILOT_INTERNAL_WHITELIST": "6288226098088,6281234567890",
    }):
        # Whitelisted number is STILL blocked under global strict hold
        assert is_onlineboost_payment_held("6288226098088") is True
        assert is_onlineboost_payment_held("088226098088") is True
        # Non-whitelisted number is blocked
        assert is_onlineboost_payment_held("6289999999999") is True
        # Missing number is blocked
        assert is_onlineboost_payment_held(None) is True
        assert is_onlineboost_payment_held() is True


def test_pilot_mode_missing_or_empty_whitelist_fails_closed():
    """Invariant 2: When hold is false but allowlist is missing or empty, fail closed."""
    # Subcase A: Empty string
    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": "",
    }):
        assert is_onlineboost_payment_held("6288226098088") is True
        assert is_onlineboost_payment_held(None) is True

    # Subcase B: Only whitespace / commas
    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": "  , ,  ",
    }):
        assert is_onlineboost_payment_held("6288226098088") is True

    # Subcase C: Variable absent
    env_clean = {k: v for k, v in os.environ.items() if k != "PILOT_INTERNAL_WHITELIST"}
    env_clean["ONLINEBOOST_PAYMENT_STRICT_HOLD"] = "false"
    with patch.dict(os.environ, env_clean, clear=True):
        assert is_onlineboost_payment_held("6288226098088") is True


def test_pilot_mode_unauthorized_number_blocked():
    """Invariant 3: Non-whitelisted customers remain held even when pilot is live."""
    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": "6288226098088,6281234567890",
    }):
        # Random customer is blocked
        assert is_onlineboost_payment_held("6281112223334") is True
        assert is_onlineboost_payment_held("081112223334") is True
        assert is_onlineboost_payment_held("+6285556667778") is True
        # Empty/None customer is blocked
        assert is_onlineboost_payment_held("") is True
        assert is_onlineboost_payment_held(None) is True


def test_pilot_mode_authorized_number_permitted():
    """Invariant 4: Only explicitly whitelisted numbers can proceed to live payment."""
    with patch.dict(os.environ, {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": "6288226098088,6281234567890",
    }):
        # Number 1: 6288226098088 (exact, leading 0, formatted with + and dashes)
        assert is_onlineboost_payment_held("6288226098088") is False
        assert is_onlineboost_payment_held("088226098088") is False
        assert is_onlineboost_payment_held("+62 882-2609-8088") is False

        # Number 2: 6281234567890
        assert is_onlineboost_payment_held("6281234567890") is False
        assert is_onlineboost_payment_held("081234567890") is False


@pytest.mark.asyncio
async def test_ctwa_gatekeeper_blocks_unauthorized_customer_in_pilot():
    """CTWA State Engine Gatekeeper blocks non-whitelisted customer when pilot is live."""
    pilot_env = {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": "6288226098088",
    }
    with patch.dict(os.environ, pilot_env):
        unauthorized_phone = "6281112223334"
        raw_msg = {
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "response_json": json.dumps({
                        "name": "Bukan Pilot",
                        "email": "bukan.pilot@gmail.com"
                    })
                }
            }
        }

        with patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit, \
             patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock):

            res = await ctwa_state_engine.process_turn(
                phone=unauthorized_phone,
                incoming_text="",
                raw_msg=raw_msg,
                phone_number_id="1419090974617162",
            )

            # Blocked: Xendit must NEVER be called, order must remain None
            assert not mock_xendit.called
            assert res["order_id"] is None
            assert res["qris_payload"] == ""
            assert "strict hold" in res["reply"].lower()


@pytest.mark.asyncio
async def test_ctwa_gatekeeper_allows_whitelisted_customer_in_pilot():
    """CTWA State Engine Gatekeeper permits whitelisted pilot customer when pilot is live."""
    pilot_env = {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": "6288226098088",
    }
    with patch.dict(os.environ, pilot_env):
        authorized_phone = "6288226098088"
        raw_msg = {
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "response_json": json.dumps({
                        "name": "Pilot Tester",
                        "email": "pilot.tester@boontrack.com"
                    })
                }
            }
        }

        mock_qr_res = {
            "qr_string": "00020101021254062490005802ID5909BoonTrack6012Kab. Bandung6105402866304ABCD",
            "qr_code_url": "https://api.xendit.co/qr/image.png",
            "id": "qr_pilot_test_123",
        }

        with patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock, return_value=mock_qr_res) as mock_xendit, \
             patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock):

            res = await ctwa_state_engine.process_turn(
                phone=authorized_phone,
                incoming_text="",
                raw_msg=raw_msg,
                phone_number_id="1419090974617162",
            )

            # Permitted: Xendit called, order issued
            assert mock_xendit.called
            assert res["order_id"] is not None
            assert res["order_id"].startswith("ORD-OB-")
            assert res["qris_payload"].startswith("000201")


@pytest.mark.asyncio
async def test_fast_path_xendit_qris_blocks_unauthorized_customer_in_pilot():
    """Fast-Path QRIS blocks unauthorized customer in pilot mode."""
    pilot_env = {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": "6288226098088",
    }
    with patch.dict(os.environ, pilot_env):
        with patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit:
            res = await generate_fast_path_xendit_qris_batch1(
                customer_phone="6281112223334",
                customer_name="Unauthorized User",
                customer_email="unauth@gmail.com",
            )
            assert res["status"] == "STRICT_HOLD"
            assert res["strict_hold"] is True
            assert res["order_id"] is None
            assert not mock_xendit.called


@pytest.mark.asyncio
async def test_academy_bot_route_c_blocks_unauthorized_customer_in_pilot():
    """Academy Bot Route C blocks unauthorized customer when pilot is live."""
    pilot_env = {
        "ONLINEBOOST_PAYMENT_STRICT_HOLD": "false",
        "PILOT_INTERNAL_WHITELIST": "6288226098088",
    }
    with patch.dict(os.environ, pilot_env):
        with patch("app.services.academy_service.send_whatsapp_text", new_callable=AsyncMock):
            res = await academy_bot.process_inbound(
                sender_phone="6289999999999",
                incoming_text="Halo kak, saya mau konfirmasi pemesanan Inkubasi CTWA Batch 1.",
                contact_name="Storefront Buyer",
                phone_number_id="1419090974617162",
                tenant_id="onlineboost",
                raw_msg={"trigger_campaign": "storefront_direct"},
            )
            assert res["action"] == "PAYMENT_STRICT_HOLD"
            assert res["strict_hold"] is True
            assert res["order_id"] is None
