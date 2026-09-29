"""tests/test_circuit_breaker_ingress_p0.py
Acceptance Test Suite P0:
Circuit Breaker Hardening, Ingress Protection & WABA Guard (§4.2, §8.4, §9.8).

CTO Mandatory Scenarios:
- Test A: Bot Self-Echo (DROP_SELF_GENERATED, LLM=0)
- Test B: Authorized Silent Pause (!pause dari owner -> is_paused=True, hening)
- Test C: Customer Unauthorized Control (!pause dari pembeli -> ditolak, bot tetap hidup)
- Test D: Paused Session Ingress (chat saat is_paused=True -> return 200 OK, LLM=0)
- Test E: Authorized Resume (!resume dari owner -> is_paused=False)
- Test F: WABA Runaway Circuit Breaker (burst > 30 msg/menit -> OPEN circuit)
- Test G: Emergency Kill Switch (GLOBAL_AI_OUTBOUND_ENABLED=False -> conversational off, order & QRIS tetap jalan)
"""

import os
import sys
import pytest
import asyncio
from unittest.mock import patch, MagicMock

# Ensure project root in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app.services.outbound_registry import outbound_registry
from app.services.circuit_breaker_service import circuit_breaker_service
from app.services.ingress_pipeline import ingress_pipeline


@pytest.fixture(autouse=True)
def reset_pipeline_state():
    """Ensures clean state before and after each test."""
    outbound_registry.clear()
    circuit_breaker_service.clear()
    ingress_pipeline._session_paused_cache.clear()
    ingress_pipeline._admin_phones_cache.clear()
    yield
    outbound_registry.clear()
    circuit_breaker_service.clear()
    ingress_pipeline._session_paused_cache.clear()
    ingress_pipeline._admin_phones_cache.clear()


@pytest.mark.asyncio
async def test_a_bot_self_echo():
    """
    Test A: Bot Self-Echo Protection (§8.4)
    When fromMe == True and wa_message_id exists in outbound_messages:
    -> Return 200 OK immediately with action 'DROP_SELF_GENERATED', LLM=0, Outbound=0.
    """
    tenant_slug = "onlineboost"
    outbound_msg_id = "wamid.HBgLMTIzNDU2Nzg5MA=="
    recipient = "6289998887771"

    # 1. Bot dispatches message and registers it to outbound_registry
    outbound_registry.register_outbound(
        wa_message_id=outbound_msg_id,
        tenant_id=tenant_slug,
        recipient_jid=recipient,
        content="Halo Kak, pesanan Anda sedang kami proses.",
        source="bot",
    )
    assert outbound_registry.is_outbound_message(outbound_msg_id) is True

    # 2. Ingress receives webhook echo with from_me=True
    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug=tenant_slug,
        sender_phone=recipient,
        incoming_text="Halo Kak, pesanan Anda sedang kami proses.",
        wa_message_id=outbound_msg_id,
        from_me=True,
    )

    # 3. Assertions
    assert decision.status_code == 200
    assert decision.allowed is False
    assert decision.action == "DROP_SELF_GENERATED"
    assert decision.llm_calls == 0
    assert decision.outbound_calls == 0
    assert "Self-echo detected" in decision.reason


@pytest.mark.asyncio
async def test_b_authorized_silent_pause():
    """
    Test B: Authorized Silent Pause (§8.4)
    When registered owner/admin sends '!pause':
    -> is_paused = True in session state, return 200 OK silently (NO LLM, NO Outbound).
    """
    tenant_slug = "onlineboost"
    owner_phone = "6281237450222"
    ingress_pipeline.register_admin_phone(tenant_slug, owner_phone)

    # Owner sends '!pause'
    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug=tenant_slug,
        sender_phone=owner_phone,
        incoming_text="!pause",
        from_me=False,
    )

    # Assertions
    assert decision.status_code == 200
    assert decision.allowed is False
    assert decision.action == "SILENT_LOCK_PAUSED"
    assert decision.is_paused is True
    assert decision.llm_calls == 0
    assert decision.outbound_calls == 0
    assert ingress_pipeline.is_session_paused(tenant_slug, owner_phone) is True


@pytest.mark.asyncio
async def test_c_customer_unauthorized_control():
    """
    Test C: Customer Unauthorized Control (§8.4)
    When non-admin customer sends '!pause':
    -> Control command rejected/ignored, bot remains active (not paused).
    """
    tenant_slug = "onlineboost"
    customer_phone = "6289991112223"
    ingress_pipeline.set_session_paused(tenant_slug, customer_phone, False)

    # Ensure customer is NOT admin
    assert await ingress_pipeline.is_owner_or_admin(tenant_slug, customer_phone) is False

    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug=tenant_slug,
        sender_phone=customer_phone,
        incoming_text="!pause",
        from_me=False,
    )

    # Assertions: Session must NOT be paused by customer
    assert ingress_pipeline.is_session_paused(tenant_slug, customer_phone) is False
    assert decision.action != "SILENT_LOCK_PAUSED"
    assert decision.allowed is True
    assert decision.action == "PROCEED_TO_RUNTIME"
    assert decision.llm_calls == 1


@pytest.mark.asyncio
async def test_d_paused_session_ingress():
    """
    Test D: Paused Session Ingress (§8.4)
    When session is already paused (is_paused == True), customer messages:
    -> Dropped at Layer 5 barrier (return 200 OK, action DROPPED_PAUSED_SESSION, LLM=0).
    """
    tenant_slug = "onlineboost"
    customer_phone = "6289994443332"

    # Pre-condition: Session paused by admin
    ingress_pipeline.set_session_paused(tenant_slug, customer_phone, True)
    assert ingress_pipeline.is_session_paused(tenant_slug, customer_phone) is True

    # Customer sends normal inquiry
    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug=tenant_slug,
        sender_phone=customer_phone,
        incoming_text="Halo admin, apakah produk ini ready?",
        from_me=False,
    )

    # Assertions
    assert decision.status_code == 200
    assert decision.allowed is False
    assert decision.action == "DROPPED_PAUSED_SESSION"
    assert decision.is_paused is True
    assert decision.llm_calls == 0
    assert decision.outbound_calls == 0


@pytest.mark.asyncio
async def test_e_authorized_resume():
    """
    Test E: Authorized Resume (§8.4)
    When session is paused and owner/admin sends '!resume':
    -> is_paused = False in session state, returns 200 OK silently (NO LLM).
    """
    tenant_slug = "onlineboost"
    owner_phone = "6281237450222"
    ingress_pipeline.register_admin_phone(tenant_slug, owner_phone)

    # Pre-condition: Session paused
    ingress_pipeline.set_session_paused(tenant_slug, owner_phone, True)
    assert ingress_pipeline.is_session_paused(tenant_slug, owner_phone) is True

    # Owner sends '!resume'
    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug=tenant_slug,
        sender_phone=owner_phone,
        incoming_text="!resume",
        from_me=False,
    )

    # Assertions
    assert decision.status_code == 200
    assert decision.allowed is False
    assert decision.action == "SILENT_LOCK_RESUMED"
    assert decision.is_paused is False
    assert decision.llm_calls == 0
    assert decision.outbound_calls == 0
    assert ingress_pipeline.is_session_paused(tenant_slug, owner_phone) is False


@pytest.mark.asyncio
async def test_f_waba_runaway_circuit_breaker():
    """
    Test F: WABA Runaway Circuit Breaker (§9.8)
    Hard-cap of max 30 outbound messages/minute on official WABA (+62 851-8183-0080).
    When breached (>30 msgs/min) -> Breaker trips to OPEN, traffic dropped with alert.
    """
    waba_number = "085181830080"
    circuit_breaker_service.reset_waba_circuit()
    assert circuit_breaker_service.is_waba_circuit_open() is False

    # Simulate 30 outbound dispatches within 60s
    for i in range(30):
        allowed, reason = circuit_breaker_service.record_waba_outbound()
        assert allowed is True
        assert reason == "OK"

    # Circuit should still be CLOSED at exactly 30
    assert circuit_breaker_service.is_waba_circuit_open() is False

    # 31st outbound dispatch breaches the hard-cap limit
    allowed, reason = circuit_breaker_service.record_waba_outbound()
    assert allowed is False
    assert reason == "WABA_CIRCUIT_OPEN"
    assert circuit_breaker_service.is_waba_circuit_open() is True

    # Ingress pipeline for WABA is now blocked by open circuit
    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug="boontrack-platform",
        sender_phone=waba_number,
        incoming_text="Halo",
        is_waba=True,
    )
    assert decision.allowed is False
    assert decision.action == "WABA_CIRCUIT_OPEN"
    assert decision.circuit_state == "OPEN"
    assert decision.llm_calls == 0


@pytest.mark.asyncio
async def test_g_emergency_kill_switch():
    """
    Test G: Emergency Kill Switch (§9.8)
    When GLOBAL_AI_OUTBOUND_ENABLED = False:
    -> Conversational AI is disabled (action: EMERGENCY_KILL_SWITCH_ACTIVE, LLM=0).
    -> Transactional flows (order notification, Dynamic QRIS payment) stay active.
    """
    tenant_slug = "onlineboost"
    customer_phone = "6289995556667"
    # Ensure session is active (not paused)
    ingress_pipeline.set_session_paused(tenant_slug, customer_phone, False)

    with patch.dict(os.environ, {"GLOBAL_AI_OUTBOUND_ENABLED": "false"}):
        assert circuit_breaker_service.is_global_ai_outbound_enabled() is False

        # 1. Conversational message -> Muted / Blocked
        decision_conv = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=customer_phone,
            incoming_text="Halo, mau tanya rekomendasi baju",
            is_transactional=False,
        )
        assert decision_conv.allowed is False
        assert decision_conv.action == "EMERGENCY_KILL_SWITCH_ACTIVE"
        assert decision_conv.llm_calls == 0
        assert decision_conv.outbound_calls == 0

        # 2. Transactional flow (e.g. order status, Dynamic QRIS request) -> Allowed to proceed!
        decision_tx = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=customer_phone,
            incoming_text="STATUS PESANAN #ORD-1234",
            is_transactional=True,
        )
        assert decision_tx.allowed is True
        assert decision_tx.action == "PROCEED_TO_RUNTIME"
        assert decision_tx.llm_calls == 1
