"""tests/test_personal_dm_auto_reply.py
Tests ensuring AI Auto-Reply is 100% active on all personal chats (including Hendra Balah)
and only skipped for groups unless mentioned.
"""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app
from app.services.ingress_pipeline import ingress_pipeline
from app.services.rotary_routing_service import rotary_routing_service

client = TestClient(app)


@pytest.mark.asyncio
async def test_ingress_pipeline_personal_dm_never_paused():
    """Verify that personal DMs proceed even if session is in paused cache."""
    # Simulate a paused session in memory
    ingress_pipeline.set_session_paused("boon", "6282130580323", True)

    decision = await ingress_pipeline.evaluate_ingress(
        tenant_slug="boon",
        sender_phone="6282130580323",
        incoming_text="Halo apa kabar",
        from_me=False,
        raw_payload={"key": {"remoteJid": "6282130580323@s.whatsapp.net"}},
    )
    assert decision.allowed is True
    assert decision.action == "PROCEED_TO_RUNTIME"


def test_rotary_routing_hendra_never_paused():
    """Verify Hendra Balah phone numbers are exempted from rotary pause."""
    for p in ["6282130580323", "082130580323", "6282113914613", "082113914613"]:
        assert rotary_routing_service.is_bot_paused_for_phone("boon", p) is False


@pytest.mark.asyncio
async def test_inbound_process_hendra_balah_success():
    """Verify inbound-process endpoint for Hendra Balah executes successfully."""
    payload = {
        "tenant_slug": "boon",
        "sender_phone": "6282130580323",
        "message_body": "Klo ga ada kabar kumaha sy nyaa",
        "sender_name": "Kak Hendra",
        "conversation_scope": "DIRECT",
    }
    res = client.post("/api/v1/whatsapp/inbound-process", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data.get("bot_paused") is not True
    assert len(data.get("reply_text") or "") > 0
