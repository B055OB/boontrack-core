"""
tests/test_owner_tester_self_loop.py
P0 Guardrail: Verification that Core Owner / Tester (+62 812-1556-7168)
chatting with Tenant Bot (+62 851-1363-6165, Solusi Ads) is treated as a regular
customer without being dropped by self-loop, Gate C friction, or rate limiter.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.challenge_service import challenge_service, STATE_NORMAL
from app.services.safety_budget_service import safety_budget_service, STATE_ACTIVE
from app.services.circuit_breaker_service import circuit_breaker_service
from app.services.ingress_pipeline import ingress_pipeline
from app.routes.whatsapp_gateway_routes import (
    get_connection_by_instance,
    check_and_handle_session_handover_and_toggle,
    process_evolution_webhook_payload,
)


@pytest.mark.asyncio
async def test_owner_tester_gate_c_exemption():
    """Gate C must never issue human-verification challenge or escalate to quarantine for tester."""
    owner_phone = "6281215567168"
    tenant_slug = "solusi-ads"

    # Rapid burst simulation (5 messages within 1 second)
    for i in range(5):
        state, reply = challenge_service.evaluate(tenant_slug, owner_phone, f"Pesan uji coba {i+1}")
        assert state == STATE_NORMAL
        assert reply is None


@pytest.mark.asyncio
async def test_owner_tester_loop_containment_exemption():
    """Loop containment must never quarantine or rate-limit the tester."""
    owner_phone = "6281215567168"
    tenant_slug = "solusi-ads"
    loop_key = safety_budget_service.build_loop_key(tenant_slug, None, owner_phone)

    # Burst simulation
    for _ in range(10):
        allowed, state, reason = safety_budget_service.check_loop_containment(loop_key)
        assert allowed is True
        assert state == STATE_ACTIVE

    # Pre-LLM reservation simulation (reserve 30 turns exceeding 20 default)
    for _ in range(30):
        assert safety_budget_service.reserve(loop_key, 1) is True


@pytest.mark.asyncio
async def test_owner_tester_active_pause_guard_exemption():
    """Tester chatting as customer on tenant bot must never be auto-muted."""
    owner_phone = "6281215567168"
    tenant_slug = "solusi-ads"

    res = await check_and_handle_session_handover_and_toggle(
        tenant_slug=tenant_slug,
        sender_phone=owner_phone,
        incoming_text="Halo kak, saya mau tanya paket jasa ads",
        sender_name="Rinaldi",
    )
    # Must return None (proceed to AI runtime)
    assert res is None


@pytest.mark.asyncio
async def test_owner_tester_inbound_processed_as_customer():
    """Full webhook flow: tester message is processed to AI runtime and dispatches outbound."""
    owner_phone = "6281215567168"
    bot_phone = "6285113636165"
    tenant_slug = "solusi-ads"

    payload = {
        "event": "messages.upsert",
        "instance": "solusi-ads",
        "data": {
            "key": {
                "remoteJid": f"{owner_phone}@s.whatsapp.net",
                "fromMe": False,
                "id": "TEST_OWNER_CHAT_P0"
            },
            "pushName": "Rinaldi Owner",
            "message": {
                "conversation": "Halo kak, ada promo Shopee Ads?"
            },
            "messageType": "conversation"
        }
    }

    mock_conn = {
        "id": "1bd7ec91-0e01-4654-b4e6-682fbed31a45",
        "tenant_id": tenant_slug,
        "tenant_slug": tenant_slug,
        "instance_name": tenant_slug,
        "phone_number": bot_phone,
        "status": "open",
        "metadata": {"mode": "DEDICATED"}
    }

    with patch("app.routes.whatsapp_gateway_routes.get_connection_by_instance", return_value=mock_conn),          patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock),          patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"key": {"id": "out_test_123"}})

        res = await process_evolution_webhook_payload(payload, tenant_slug=tenant_slug)

        assert res.get("status") == "success"
        assert res.get("tenant") == tenant_slug
        assert res.get("reply") or res.get("reply_text")
        # Ensure outbound message was dispatched via Evolution API to tester phone
        mock_post.assert_awaited()
