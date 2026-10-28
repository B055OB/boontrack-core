"""tests/test_onlineboost_flows_orchestration_phase5.py
Comprehensive Phase 5 Test Suite for OnlineBoost WhatsApp Flows Orchestration.

Covers all 13 scenarios specified in CTO Directive Phase 5:
1. The correct OnlineBoost inquiry launches the intended Flow.
2. The Flow response payload is parsed correctly from the real WhatsApp webhook contract.
3. Valid name/email values are persisted through the authoritative service.
4. Invalid or missing fields are rejected without invoice side effects.
5. Spoofed tenant, Flow ID, session, or product data cannot cross tenant boundaries.
6. Duplicate delivery/submission does not duplicate an invoice or order.
7. A held payment request never invokes real Xendit QRIS creation.
8. Registration-interest responses do not create a circular CTA loop.
9. Asking a product question does not automatically transfer the conversation to a human.
10. Opt-out messages take priority and trigger no promotional response or Flow.
11. No placeholder Telegram link or duplicate fulfillment message is produced.
12. Missing QRIS payload does not crash the state engine.
13. Existing alumni and unrelated tenant behavior remains compatible.
"""

import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.waba_adapter import WabaProviderAdapter
from app.services.academy_service import (
    ALUMNI_MAU_GREETING,
    BOT_LED_ASSISTANT_RESPONSE,
    CANONICAL_BATCH1_SKU,
    LEGACY_ACADEMY_SKU_ID,
    SITUATION_C_PRICE_BENEFITS_SCRIPT,
    academy_bot,
    is_onlineboost_payment_held,
)
from app.services.ctwa_fulfillment_service import fulfill_onlineboost_ctwa_order
from app.services.ctwa_state_engine import (
    SINGLE_OFFER_PRICE,
    SINGLE_OFFER_SLUG,
    ctwa_state_engine,
    is_valid_email_format,
    is_valid_name,
    mask_email,
)
from app.whatsapp.traffic_splitter import TrafficSplitter


@pytest.fixture(autouse=True)
def clean_test_sessions():
    """Ensure in-memory sessions are cleared before each test."""
    ctwa_state_engine.sessions.clear()
    from app.services.academy_service import _ACADEMY_SESSIONS
    _ACADEMY_SESSIONS.clear()
    yield
    ctwa_state_engine.sessions.clear()
    _ACADEMY_SESSIONS.clear()


# ============================================================================
# 1. Inquiry launches the intended Flow
# ============================================================================
@pytest.mark.asyncio
async def test_01_inquiry_launches_intended_flow():
    """
    Scenario 1:
    Inbound landing page CTA 'Saya tertarik ikut kelas nya Kang'
    recognizes registration entrypoint and launches native WhatsApp Flow.
    """
    test_phone = "6288226098088"
    inbound_text = "Saya tertarik ikut kelas nya Kang"

    with patch("app.services.whatsapp.cloud_api.send_whatsapp_flow", new_callable=AsyncMock) as mock_flow:
        mock_flow.return_value = {"messages": [{"id": "wamid.HBgFLOW123"}]}

        res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text=inbound_text,
            sender_name="Budi",
            phone_number_id="1419090974617162",
        )

        assert res["success"] is True
        assert res["action"] == "SEND_REGISTRATION_FLOW"
        assert res["current_state"] == "STATE_FLOW_SENT"
        assert mock_flow.called

        flow_call = mock_flow.call_args[1]
        assert flow_call["to_phone"] == test_phone
        assert flow_call["tenant_id"] == "onlineboost"
        assert flow_call["phone_number_id"] == "1419090974617162"
        assert flow_call["flow_cta"] == "Daftar & Amankan Slot"
        assert flow_call["flow_id"] == "1663739061907747"
        assert flow_call["flow_token"] == "onlineboost_batch1_reg"
        assert flow_call["flow_action"] == "navigate"
        assert flow_call["flow_action_payload"] == {"screen": "REGISTRATION"}
        assert flow_call["header_text"] == "OnlineBoost Batch 1"
        assert "Halo Kak! Klik tombol di bawah" in flow_call["body_text"]
        assert "https://shop.boontrack.com" not in flow_call["body_text"]


# ============================================================================
# 2. Flow response payload is parsed correctly from real WhatsApp webhook
# ============================================================================
@pytest.mark.asyncio
async def test_02_flow_response_payload_parsed_correctly():
    """
    Scenario 2:
    Real WhatsApp nfm_reply payload is safely parsed and extracted.
    Supports both {"name": ...} (published Meta form) and legacy {"full_name": ...}.
    """
    # Test case A: published Meta form payload {"name": ..., "email": ...}
    raw_webhook_msg_published = {
        "from": "6281234567890",
        "id": "wamid.HBgREALFLOW001",
        "timestamp": "1710000000",
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({
                    "name": "Ahmad Fauzi",
                    "email": "ahmad.fauzi@example.com",
                    "flow_token": "onlineboost_batch1_reg"
                }),
                "body": "Sent",
                "name": "flow"
            }
        }
    }

    parsed_published = ctwa_state_engine.parse_inbound_lead(raw_msg=raw_webhook_msg_published)
    assert parsed_published is not None
    assert parsed_published[0] == "Ahmad Fauzi"
    assert parsed_published[1] == "ahmad.fauzi@example.com"

    # Test case B: fallback {"full_name": ..., "email": ...}
    raw_webhook_msg_legacy = {
        "from": "6281234567890",
        "id": "wamid.HBgREALFLOW002",
        "timestamp": "1710000000",
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({
                    "full_name": "Ahmad Fauzi",
                    "email": "ahmad.fauzi@example.com",
                    "flow_token": "onlineboost_batch1_reg"
                }),
                "body": "Sent",
                "name": "flow"
            }
        }
    }

    parsed_legacy = ctwa_state_engine.parse_inbound_lead(raw_msg=raw_webhook_msg_legacy)
    assert parsed_legacy is not None
    assert parsed_legacy[0] == "Ahmad Fauzi"
    assert parsed_legacy[1] == "ahmad.fauzi@example.com"


# ============================================================================
# 3. Valid name/email values are persisted through authoritative service
# ============================================================================
@pytest.mark.asyncio
async def test_03_valid_name_email_persisted():
    """
    Scenario 3:
    Valid registration data is persisted to session and database before returning.
    """
    test_phone = "6281298765432"
    raw_webhook_msg = {
        "from": test_phone,
        "id": "wamid.HBgPERSIST001",
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({
                    "full_name": "Dewi Sartika",
                    "email": "dewi.sartika@gmail.com"
                }),
                "body": "Sent",
                "name": "flow"
            }
        }
    }

    with patch.object(ctwa_state_engine, "_save_session_to_db") as mock_save_db, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock):

        res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="",
            raw_msg=raw_webhook_msg,
            phone_number_id="1419090974617162",
        )

        assert res["success"] is True
        assert res["action"] == "GATEKEEPER_STRICT_HOLD"

        session = ctwa_state_engine.get_session(test_phone)
        assert session["lead_name"] == "Dewi Sartika"
        assert session["lead_email"] == "dewi.sartika@gmail.com"
        assert session["current_state"] == "STATE_LEAD_QUEUED"
        assert mock_save_db.called


# ============================================================================
# 4. Invalid or missing fields are rejected without invoice side effects
# ============================================================================
@pytest.mark.asyncio
async def test_04_invalid_missing_fields_rejected_safely():
    """
    Scenario 4:
    Submissions with missing/invalid names or email formats are rejected
    with actionable recovery, without invoking Xendit or order creation.
    """
    test_phone = "6281311223344"

    # Case A: Name too short (< 2 chars)
    short_name_msg = {
        "from": test_phone,
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({"full_name": "X", "email": "valid@email.com"})
            }
        }
    }

    with patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_text:

        res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="",
            raw_msg=short_name_msg,
            phone_number_id="1419090974617162",
        )

        assert res["success"] is False
        assert res["action"] == "REGISTRATION_VALIDATION_FAILED"
        assert res["order_id"] is None
        assert not mock_xendit.called
        assert "Mohon maaf Kak, data pendaftaran belum valid" in res["reply"]
        assert mock_send_text.called

    # Case B: Invalid email format
    invalid_email_msg = {
        "from": test_phone,
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({"full_name": "Rian Kusuma", "email": "not-an-email"})
            }
        }
    }

    with patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit:
        res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="",
            raw_msg=invalid_email_msg,
            phone_number_id="1419090974617162",
        )

        assert res["success"] is False
        assert res["action"] == "REGISTRATION_VALIDATION_FAILED"
        assert not mock_xendit.called


# ============================================================================
# 5. Spoofed tenant or product data cannot cross tenant boundaries
# ============================================================================
@pytest.mark.asyncio
async def test_05_spoofed_tenant_data_rejected():
    """
    Scenario 5:
    Client injecting 'tenant', 'price', or other properties in response_json
    cannot override authoritative tenant or product price.
    """
    test_phone = "6281455667788"
    spoofed_msg = {
        "from": test_phone,
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({
                    "full_name": "Hacker Spoof",
                    "email": "hacker@evil.com",
                    "tenant": "malicious_tenant",
                    "tenant_id": "malicious_tenant",
                    "price": 1000,
                    "amount": 1000,
                })
            }
        }
    }

    with patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock):
        res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="",
            raw_msg=spoofed_msg,
            phone_number_id="1419090974617162",
        )

        session = ctwa_state_engine.get_session(test_phone)
        assert session["tenant_slug"] == "onlineboost"
        assert res["total_amount"] == SINGLE_OFFER_PRICE  # Still 249000
        assert res["total_amount"] != 1000


# ============================================================================
# 6. Duplicate delivery/submission does not duplicate an invoice or order
# ============================================================================
@pytest.mark.asyncio
async def test_06_duplicate_submission_idempotency():
    """
    Scenario 6:
    Duplicate Flow submission from the same customer returns idempotent
    queued status without generating secondary side effects.
    """
    test_phone = "6281566778899"
    msg = {
        "from": test_phone,
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({
                    "full_name": "Siti Nurhaliza",
                    "email": "siti.nurhaliza@gmail.com"
                })
            }
        }
    }

    with patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock):
        # First submission
        res1 = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="",
            raw_msg=msg,
            phone_number_id="1419090974617162",
        )
        assert res1["action"] == "GATEKEEPER_STRICT_HOLD"

        # Second identical submission
        res2 = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="",
            raw_msg=msg,
            phone_number_id="1419090974617162",
        )
        assert res2["action"] == "GATEKEEPER_STRICT_HOLD"
        assert res2["order_id"] is None
        assert "sudah tersimpan sebelumnya" in res2["reply"]


# ============================================================================
# 7. A held payment request never invokes real Xendit QRIS creation
# ============================================================================
@pytest.mark.asyncio
async def test_07_held_payment_request_never_calls_xendit():
    """
    Scenario 7:
    Under strict hold, Xendit dynamic QRIS is strictly forbidden from being called.
    """
    test_phone = "6281677889900"
    msg = {
        "from": test_phone,
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "response_json": json.dumps({
                    "full_name": "Eko Prasetyo",
                    "email": "eko.prasetyo@gmail.com"
                })
            }
        }
    }

    assert is_onlineboost_payment_held() is True

    with patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock):

        res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="",
            raw_msg=msg,
            phone_number_id="1419090974617162",
        )

        assert not mock_xendit.called
        assert res["order_id"] is None
        assert res["qris_payload"] == ""
        assert "strict hold" in res["reply"].lower()


# ============================================================================
# 8. Registration-interest responses do not create a circular CTA loop
# ============================================================================
@pytest.mark.asyncio
async def test_08_no_circular_landing_page_loop():
    """
    Scenario 8:
    Responding to 'Saya tertarik ikut kelas nya Kang' does not send back
    the landing page URL (https://shop.boontrack.com/...).
    """
    test_phone = "6281788990011"
    inbound_text = "Saya tertarik ikut kelas nya Kang"

    with patch("app.services.whatsapp.cloud_api.send_whatsapp_flow", new_callable=AsyncMock) as mock_flow:
        res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text=inbound_text,
            phone_number_id="1419090974617162",
        )

        assert "https://shop.boontrack.com" not in res["reply"]
        assert "kelas-inkubasi-ctwa-batch-1-scale" not in res["reply"]
        if mock_flow.called:
            body = mock_flow.call_args[1].get("body_text", "")
            assert "https://shop.boontrack.com" not in body


# ============================================================================
# 9. Asking a product question does not automatically transfer to human
# ============================================================================
@pytest.mark.asyncio
async def test_09_product_question_does_not_transfer_to_human():
    """
    Scenario 9:
    Questions about admin, price, or benefits are answered by virtual assistant
    without triggering human CS handoff or RotaryRouting transfer.
    """
    test_phone = "6281899001122"

    # Query 1: Admin inquiry
    res_admin = await ctwa_state_engine.process_turn(
        phone=test_phone,
        incoming_text="Halo admin, saya mau tanya dulu dong",
        phone_number_id="1419090974617162",
    )
    assert res_admin["action"] == "BOT_LED_ASSISTANT_REPLY"
    assert "asisten virtual resmi OnlineBoost" in res_admin["reply"]
    assert res_admin.get("handover_ready") is not True

    # Query 2: Price and benefits inquiry
    res_price = await ctwa_state_engine.process_turn(
        phone=test_phone,
        incoming_text="OnlineBoost itu apa dan fasilitas apa yang didapat?",
        phone_number_id="1419090974617162",
    )
    assert res_price["action"] == "EXPLAIN_PRICE_AND_BENEFITS"
    assert "Rp249.000" in res_price["reply"]
    assert "Bimbingan 10 Langkah Intensif" in res_price["reply"]


# ============================================================================
# 10. Opt-out messages take priority and trigger no promotional response or Flow
# ============================================================================
@pytest.mark.asyncio
async def test_10_opt_out_priority_guard():
    """
    Scenario 10:
    STOP, BERHENTI, UNSUBSCRIBE trigger durable suppression and opt-out acknowledgment
    before any flow or sales response.
    """
    test_phone = "6281900112233"

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "10001",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "+6288226098088",
                        "phone_number_id": "1419090974617162"
                    },
                    "contacts": [{"profile": {"name": "OptOut User"}, "wa_id": test_phone}],
                    "messages": [{
                        "from": test_phone,
                        "id": "wamid.HBgOPTOUT001",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": "BERHENTI"}
                    }]
                }
            }]
        }]
    }

    mock_tenant_ctx = MagicMock()
    mock_tenant_ctx.slug = "onlineboost"
    mock_tenant_ctx.name = "OnlineBoost"
    mock_tenant_ctx.tenant_id = "onlineboost"

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock) as mock_resolve, \
         patch("app.services.phone_suppression_service.record_durable_suppression", return_value=(True, "memory")), \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_flow", new_callable=AsyncMock) as mock_flow:

        mock_resolve.return_value = mock_tenant_ctx
        status_code, res, trace = await TrafficSplitter.split_and_dispatch(payload)

        assert status_code == 200
        assert res.get("purpose") == "COMPLIANCE_OPT_OUT"
        assert res.get("suppressed") is True
        assert not mock_flow.called
        assert "berhasil berhenti berlangganan" in mock_send_wa.call_args[1]["text"]


# ============================================================================
# 11. No placeholder Telegram link or duplicate fulfillment message
# ============================================================================
@pytest.mark.asyncio
async def test_11_no_placeholder_telegram_link():
    """
    Scenario 11:
    Fulfillment requires verified single-use link creation. Never generate
    fake or placeholder links like 'https://t.me/+BTA_...'.
    """
    from app.services.ctwa_fulfillment_service import create_telegram_single_use_invite_link
    test_order_id = "ORD-OB-TEST-FULFILL"
    test_phone = "6282112233445"

    with patch("httpx.AsyncClient.post") as mock_tg_post, \
         patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa:
        # Simulate Telegram API error
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"ok": False, "description": "Telegram API Internal Error"}
        mock_tg_post.return_value = mock_resp

        # 1. Direct call to create_telegram_single_use_invite_link must raise RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            await create_telegram_single_use_invite_link(
                order_id=test_order_id,
                buyer_name="Test Buyer",
            )
        assert "Telegram Bot API failed to generate verified invite link" in str(exc_info.value)

        # 2. Call to fulfill_onlineboost_ctwa_order must return PENDING_TELEGRAM_LINK and never send fake link
        res_ful = await fulfill_onlineboost_ctwa_order(
            order_id=test_order_id,
            buyer_name="Test Buyer",
            buyer_phone=test_phone,
            amount=248850,
            tenant_id="onlineboost",
        )
        assert res_ful["status"] in ("PENDING_TELEGRAM_LINK", "TELEGRAM_PENDING_RETRY")
        assert res_ful.get("single_use_invite_link") is None
        assert mock_wa.called
        sent_wa_text = mock_wa.call_args[1].get("text", "")
        assert "https://t.me/+" not in sent_wa_text
        assert "+BTA_" not in sent_wa_text


# ============================================================================
# 12. Missing QRIS payload does not crash the state engine
# ============================================================================
@pytest.mark.asyncio
async def test_12_missing_qris_payload_handled_safely():
    """
    Scenario 12:
    Missing or empty qris_payload is handled safely without KeyError: 'qris_payload'.
    """
    test_phone = "6282233445566"

    with patch.object(ctwa_state_engine, "execute_deterministic_gatekeeper", new_callable=AsyncMock) as mock_gk:
        # Mock gatekeeper returning empty payload
        mock_gk.return_value = {
            "status": "GATEKEEPER_PENDING",
            "order_id": None,
            "total_amount": 249000,
            "qris_payload": None,  # Explicitly None
            "caption": "Pendaftaran dicatat.",
        }

        res = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="Halo Admin, saya atas nama Joko Susilo (joko@gmail.com) sudah daftar kelas",
        )

        assert res is not None
        assert res["action"] == "GATEKEEPER_PENDING"
        assert res["qris_payload"] == ""
        assert res["media_url"] == ""


# ============================================================================
# 13. Existing alumni and unrelated tenant behavior remains compatible
# ============================================================================
@pytest.mark.asyncio
async def test_13_existing_alumni_and_tenant_compatibility():
    """
    Scenario 13:
    Legacy MAU alumni entrypoint and SKU mappings remain compatible.
    """
    # 1. SKU Mappings
    assert CANONICAL_BATCH1_SKU == "OB-BATCH1-249K"
    assert LEGACY_ACADEMY_SKU_ID == "OB-BATCH1-249K"

    # 2. Legacy 'MAU' trigger
    phone = "6282344556677"
    with patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_wa:
        res_mau = await academy_bot.process_inbound(
            sender_phone=phone,
            incoming_text="MAU",
            contact_name="Alumni Joko",
            tenant_id="onlineboost",
        )

        assert res_mau is not None
        assert res_mau["handled"] is True
        assert res_mau["action"] == "ALUMNI_MAU_QUALIFY"
        assert "Di Batch 1 ini, gue lagi siapkan metode baru yang fokus praktik" in res_mau["reply"]

    # 3. Privacy Masking helper validation
    masked = mask_email("budi.santoso@gmail.com")
    assert masked.startswith("bu")
    assert masked.endswith("@gmail.com")
    assert "santoso" not in masked
    assert mask_email("al@yahoo.com") == "a*@yahoo.com"
    assert mask_email("invalid") == "***"

    # 4. Email and Name Validators
    assert is_valid_name("Ahmad") is True
    assert is_valid_name("A") is False
    assert is_valid_name("12345") is False
    assert is_valid_email_format("valid@test.com") is True
    assert is_valid_email_format("invalid-email") is False


# ============================================================================
# 14. Outbound Flow Dispatch Idempotency (Prevent Duplicate Flow Send)
# ============================================================================
@pytest.mark.asyncio
async def test_14_outbound_flow_dispatch_idempotency():
    """
    Scenario 14:
    Calling process_turn or process_inbound twice with landing page trigger
    dispatches send_whatsapp_flow exactly once to prevent duplicate flow messages.
    """
    test_phone = "6289900112233"
    ctwa_state_engine.reset_session(test_phone)
    academy_bot.reset_session(test_phone)

    raw_msg_1 = {"id": "wamid.IDEMPOTENT_001", "from": test_phone}

    with patch("app.services.whatsapp.cloud_api.send_whatsapp_flow", new_callable=AsyncMock) as mock_flow:
        mock_flow.return_value = {"messages": [{"id": "wamid.HBgFLOW_IDEMP"}]}

        # Call 1: First inquiry -> flow dispatched
        res1 = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="Saya tertarik ikut kelas nya Kang",
            raw_msg=raw_msg_1,
            phone_number_id="1419090974617162",
        )
        assert res1["success"] is True
        assert res1["action"] == "SEND_REGISTRATION_FLOW"
        assert mock_flow.call_count == 1

        # Call 2: Duplicate delivery of same message -> flow NOT dispatched again
        res2 = await ctwa_state_engine.process_turn(
            phone=test_phone,
            incoming_text="Saya tertarik ikut kelas nya Kang",
            raw_msg=raw_msg_1,
            phone_number_id="1419090974617162",
        )
        assert res2["success"] is True
        assert mock_flow.call_count == 1  # Still 1, not duplicated!
