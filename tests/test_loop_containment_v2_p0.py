"""tests/test_loop_containment_v2_p0.py
Acceptance Test Suite V2 for Loop Containment, Ingress Pipeline & Pair Safety Budget.
Architectural Authority: CTO Office Mandate, ARCHITECTURE.md (§4.2, §8.4, §9.8).

CTO Office Architectural Doctrines:
1. "BoonTrack tidak berasumsi bahwa setiap inbound message berasal dari manusia.
    Setiap external conversational event diperlakukan sebagai untrusted input
    dan wajib melewati bounded safety, cost, and interaction controls sebelum
    dapat memicu AI inference atau outbound action."
2. "Loop protection is scoped from conversation/peer upward; global breakers
    are last-resort containment, not the first line of defense."

Tests Covered:
- Test A: Bot-to-Bot Rapid Ping-Pong (Pair Breaker trip ke PEER_QUARANTINED, LLM=0, tidak berulang).
- Test B: Scoped Isolation (Peer A di-quarantine karena loop, Peer B tetap bisa chat lancar).
- Test C: Pre-LLM Reservation Block (Budget habis -> LLM call = 0).
- Test D: Authorized Silent Pause (!pause owner -> is_paused=True, hening 200 OK).
- Test E: Unauthorized Customer Control (Pembeli ketik !pause -> perintah ditolak, bot tetap hidup).
- Test F: WABA Ceiling Protection (Burst > 30 msg/menit ke 085181830080 -> WABA Breaker OPEN).
- Test G: Circuit Recovery (HALF_OPEN -> sesi melewati cooldown, pulih ke ACTIVE aman).
"""

import os
import time
import pytest
from unittest.mock import patch

from app.services.ingress_pipeline import ingress_pipeline
from app.services.circuit_breaker_service import circuit_breaker_service
from app.services.challenge_service import challenge_service
from app.services.safety_budget_service import (
    safety_budget_service,
    STATE_ACTIVE,
    STATE_PEER_QUARANTINED,
    STATE_HALF_OPEN,
)


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Isolate tests by clearing in-memory caches and circuit breaker states."""
    circuit_breaker_service.clear()
    safety_budget_service.reset()
    challenge_service.clear_all()
    ingress_pipeline._session_paused_cache.clear()
    ingress_pipeline._admin_phones_cache.clear()
    ingress_pipeline._inbound_dedupe_cache.clear()
    yield
    circuit_breaker_service.clear()
    safety_budget_service.reset()
    challenge_service.clear_all()
    ingress_pipeline._session_paused_cache.clear()
    ingress_pipeline._admin_phones_cache.clear()
    ingress_pipeline._inbound_dedupe_cache.clear()


@pytest.mark.asyncio
async def test_a_bot_to_bot_rapid_ping_pong():
    """
    Test A: Bot-to-Bot Rapid Ping-Pong (Layer 4 — Loop Containment)
    Simulates rapid bot-to-bot loop burst. Gate C (Layer 3.5) is bypassed
    here because this scenario is specifically testing Layer 4 pair quarantine.
    Once threshold is breached, pair breaker trips to PEER_QUARANTINED.
    Subsequent messages are dropped immediately (200 OK, LLM=0, Outbound=0).
    """
    tenant_slug = "onlineboost"
    peer_phone = "6289998887771"
    loop_key = safety_budget_service.build_loop_key(tenant_slug, None, peer_phone)

    # Bypass Gate C (Layer 3.5) — this test targets Layer 4 Loop Containment
    with patch("app.services.ingress_pipeline.challenge_service.evaluate", return_value=("NORMAL", None)):
        # Send 4 messages normally (below default burst limit of 5)
        for i in range(4):
            decision = await ingress_pipeline.evaluate_ingress(
                tenant_slug=tenant_slug,
                sender_phone=peer_phone,
                incoming_text=f"Ping-pong payload {i}",
                wa_message_id=f"msg_ping_{i}",
            )
            assert decision.allowed is True
            assert decision.action == "PROCEED_TO_RUNTIME"

        # 5th rapid message within window breaches burst limit -> Trips to PEER_QUARANTINED
        decision_5th = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_phone,
            incoming_text="Ping-pong payload 5 (breach)",
            wa_message_id="msg_ping_5",
        )
        assert decision_5th.status_code == 200
        assert decision_5th.allowed is False
        assert decision_5th.action == "PEER_QUARANTINED"
        assert decision_5th.circuit_state == "OPEN"
        assert decision_5th.llm_calls == 0
        assert decision_5th.outbound_calls == 0
        assert "Burst rate threshold breached" in decision_5th.reason

        # Subsequent ping-pong attempt remains quarantined
        decision_followup = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_phone,
            incoming_text="Ping-pong loop echo",
            wa_message_id="msg_ping_followup",
        )
        assert decision_followup.allowed is False
        assert decision_followup.action == "PEER_QUARANTINED"
        assert decision_followup.llm_calls == 0
        assert decision_followup.outbound_calls == 0


@pytest.mark.asyncio
async def test_b_scoped_isolation():
    """
    Test B: Scoped Isolation (Layer 4 — Loop Containment)
    Peer A trips into PEER_QUARANTINED due to loop burst. Gate C bypassed here.
    Peer B messaging the same tenant is completely unaffected (allowed=True, LLM=1).
    Storefront catalog & transactional flows also stay 100% operational.
    """
    tenant_slug = "onlineboost"
    peer_a = "6289998881111"
    peer_b = "6289998882222"

    loop_key_a = safety_budget_service.build_loop_key(tenant_slug, None, peer_a)
    loop_key_b = safety_budget_service.build_loop_key(tenant_slug, None, peer_b)

    # Bypass Gate C (Layer 3.5) — this test targets Layer 4 Loop Containment scoped isolation
    with patch("app.services.ingress_pipeline.challenge_service.evaluate", return_value=("NORMAL", None)):
        # Force Peer A into PEER_QUARANTINED via burst breach
        for i in range(5):
            await ingress_pipeline.evaluate_ingress(
                tenant_slug=tenant_slug,
                sender_phone=peer_a,
                incoming_text=f"Spam message {i}",
                wa_message_id=f"msg_a_{i}",
            )

        # Assert Peer A is quarantined
        decision_a = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_a,
            incoming_text="Halo apakah bot masih aktif?",
            wa_message_id="msg_a_check",
        )
        assert decision_a.allowed is False
        assert decision_a.action == "PEER_QUARANTINED"
        assert decision_a.llm_calls == 0

        # Assert Peer B is NOT affected and can chat smoothly
        decision_b = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_b,
            incoming_text="Halo Kak, saya mau tanya harga baju batik",
            wa_message_id="msg_b_1",
        )
        assert decision_b.status_code == 200
        assert decision_b.allowed is True
        assert decision_b.action == "PROCEED_TO_RUNTIME"
        assert decision_b.llm_calls == 1

        # Assert transactional/catalog flows for this tenant stay 100% functional
        decision_tx = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_b,
            incoming_text="PAYMENT_CONFIRMATION_QRIS_12345",
            wa_message_id="msg_tx_1",
            is_transactional=True,
        )
        assert decision_tx.allowed is True
        assert decision_tx.action == "PROCEED_TO_RUNTIME"


@pytest.mark.asyncio
async def test_c_pre_llm_reservation_block():
    """
    Test C: Pre-LLM Reservation Block (§8.4 Layer 6)
    When peer's safety budget is exhausted:
    -> safety_budget_service.reserve() returns False.
    -> Ingress returns 200 OK fast drop (action: PRE_LLM_RESERVATION_BLOCKED, LLM=0, Outbound=0).
    Gate C (Layer 3.5) is bypassed here to isolate Layer 6 budget behavior.
    """
    tenant_slug = "onlineboost"
    peer_phone = "6289998883333"
    loop_key = safety_budget_service.build_loop_key(tenant_slug, None, peer_phone)

    # Set budget to 2 turns for this peer session
    safety_budget_service.set_budget(loop_key, turns=2)

    # Bypass Gate C (Layer 3.5) — this test targets Layer 6 Pre-LLM Budget
    with patch("app.services.ingress_pipeline.challenge_service.evaluate", return_value=("NORMAL", None)):
        # Turn 1: Allowed and reserved
        d1 = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_phone,
            incoming_text="Halo, mau beli barang A",
            wa_message_id="msg_budget_1",
        )
        assert d1.allowed is True
        assert d1.action == "PROCEED_TO_RUNTIME"
        assert d1.llm_calls == 1

        # Turn 2: Allowed and reserved
        d2 = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_phone,
            incoming_text="Bisa kirim ke Jakarta?",
            wa_message_id="msg_budget_2",
        )
        assert d2.allowed is True
        assert d2.action == "PROCEED_TO_RUNTIME"
        assert d2.llm_calls == 1

        # Turn 3: Budget exhausted (used 2/2) -> Pre-LLM reservation FAILS!
        d3 = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_phone,
            incoming_text="Metode pembayarannya apa saja?",
            wa_message_id="msg_budget_3",
        )
        assert d3.status_code == 200
        assert d3.allowed is False
        assert d3.action == "PRE_LLM_RESERVATION_BLOCKED"
        assert d3.llm_calls == 0
        assert d3.outbound_calls == 0
        assert "Pre-LLM safety turn budget exhausted" in d3.reason


@pytest.mark.asyncio
async def test_d_authorized_silent_pause():
    """
    Test D: Authorized Silent Pause (§8.4 Layer 3)
    When registered owner/admin sends '!pause':
    -> Session paused silently (is_paused=True, 200 OK, LLM=0, Outbound=0).
    """
    tenant_slug = "onlineboost"
    owner_phone = "6281237450222"
    ingress_pipeline.register_admin_phone(tenant_slug, owner_phone)

    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug=tenant_slug,
        sender_phone=owner_phone,
        incoming_text="!pause",
        from_me=False,
    )

    assert decision.status_code == 200
    assert decision.allowed is False
    assert decision.action == "SILENT_LOCK_PAUSED"
    assert decision.is_paused is True
    assert decision.llm_calls == 0
    assert decision.outbound_calls == 0
    assert ingress_pipeline.is_session_paused(tenant_slug, owner_phone) is True


@pytest.mark.asyncio
async def test_e_unauthorized_customer_control():
    """
    Test E: Unauthorized Customer Control (§8.4 Layer 3)
    When regular customer sends '!pause':
    -> Command is rejected/ignored, session is NOT paused, bot stays alive (allowed=True, LLM=1).
    """
    tenant_slug = "onlineboost"
    customer_phone = "6289991112223"
    ingress_pipeline.set_session_paused(tenant_slug, customer_phone, False)

    # Customer is not admin
    assert await ingress_pipeline.is_owner_or_admin(tenant_slug, customer_phone) is False

    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug=tenant_slug,
        sender_phone=customer_phone,
        incoming_text="!pause",
        from_me=False,
    )

    # Session MUST NOT be paused
    assert ingress_pipeline.is_session_paused(tenant_slug, customer_phone) is False
    assert decision.action != "SILENT_LOCK_PAUSED"
    assert decision.allowed is True
    assert decision.action == "PROCEED_TO_RUNTIME"
    assert decision.llm_calls == 1


@pytest.mark.asyncio
async def test_f_waba_ceiling_protection():
    """
    Test F: WABA Ceiling Protection (§9.8)
    Hard-cap of max 30 outbound messages/minute on official WABA (+62 851-8183-0080).
    When outbound burst exceeds 30 msg/min:
    -> WABA Breaker trips to OPEN.
    -> Subsequent WABA ingress is blocked (action: WABA_CIRCUIT_OPEN, circuit_state: OPEN, LLM=0).
    """
    waba_number = "085181830080"
    circuit_breaker_service.reset_waba_circuit()
    assert circuit_breaker_service.is_waba_circuit_open() is False

    # Simulate 30 outbound dispatches
    for _ in range(30):
        allowed, reason = circuit_breaker_service.record_waba_outbound()
        assert allowed is True
        assert reason == "OK"

    # Circuit is still closed at 30
    assert circuit_breaker_service.is_waba_circuit_open() is False

    # 31st outbound dispatch breaches the hard-cap
    allowed, reason = circuit_breaker_service.record_waba_outbound()
    assert allowed is False
    assert reason == "WABA_CIRCUIT_OPEN"
    assert circuit_breaker_service.is_waba_circuit_open() is True

    # Ingress to WABA is blocked by the open circuit
    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug="boontrack-platform",
        sender_phone=waba_number,
        incoming_text="Halo WABA",
        is_waba=True,
    )
    assert decision.allowed is False
    assert decision.action == "WABA_CIRCUIT_OPEN"
    assert decision.circuit_state == "OPEN"
    assert decision.llm_calls == 0


@pytest.mark.asyncio
async def test_g_circuit_recovery():
    """
    Test G: Circuit Recovery & State Machine (§9.8)
    State Lifecycle: ACTIVE -> PEER_QUARANTINED -> HALF_OPEN -> ACTIVE.
    Gate C (Layer 3.5) is bypassed here to isolate Layer 4 quarantine/recovery.
    """
    tenant_slug = "onlineboost"
    peer_phone = "6289998887777"
    loop_key = safety_budget_service.build_loop_key(tenant_slug, None, peer_phone)

    # Bypass Gate C (Layer 3.5) — this test targets Layer 4 circuit recovery state machine
    with patch("app.services.ingress_pipeline.challenge_service.evaluate", return_value=("NORMAL", None)):
        # 1. Breach burst limit to trip into PEER_QUARANTINED
        for i in range(5):
            await ingress_pipeline.evaluate_ingress(
                tenant_slug=tenant_slug,
                sender_phone=peer_phone,
                incoming_text=f"Rapid fire {i}",
                wa_message_id=f"msg_rf_{i}",
            )

        peer_record = safety_budget_service.get_or_create_peer(loop_key)
        assert peer_record.state == STATE_PEER_QUARANTINED
        assert peer_record.violation_count == 1
        assert peer_record.cooldown_until > time.time()

        # 2. Ingress during cooldown is blocked
        d_blocked = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_phone,
            incoming_text="Are we still blocked?",
            wa_message_id="msg_blocked_check",
        )
        assert d_blocked.allowed is False
        assert d_blocked.action == "PEER_QUARANTINED"

        # 3. Simulate cooldown expiration (set cooldown_until to the past)
        peer_record.cooldown_until = time.time() - 1.0

        # 4. Ingress after cooldown passes enters HALF_OPEN probe turn
        d_probe = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_phone,
            incoming_text="Halo, saya mau belanja normal sekarang",
            wa_message_id="msg_probe_turn",
        )
        # Probe turn must be allowed to verify recovery!
        assert d_probe.allowed is True
        assert d_probe.action == "PROCEED_TO_RUNTIME"
        assert d_probe.llm_calls == 1

        # 5. After successful turn execution, state is restored to ACTIVE
        assert peer_record.state == STATE_ACTIVE
        assert safety_budget_service.get_peer_state(loop_key) == STATE_ACTIVE

        # 6. Subsequent chat in ACTIVE continues normally
        d_active = await ingress_pipeline.evaluate_ingress(
            tenant_slug=tenant_slug,
            sender_phone=peer_phone,
            incoming_text="Bagus, saya mau pesan 2 pcs.",
            wa_message_id="msg_active_normal",
        )
    assert d_active.allowed is True
    assert d_active.action == "PROCEED_TO_RUNTIME"
