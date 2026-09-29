import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from app.services.unified_conversation_service import unified_conversation_engine
from app.services.rotary_routing_service import rotary_routing_service

@pytest.mark.asyncio
async def test_handover_option_2_detection_and_pause():
    tenant = "buzzerukm"
    phone = "6281111222333"

    with patch("app.services.whatsapp_service.get_supabase") as mock_sb:
        mock_client = MagicMock()
        mock_sb.return_value = mock_client
        mock_client.from_().select().eq().eq().maybe_single().execute.return_value = MagicMock(data=None)

        res = await unified_conversation_engine.process_chat(
            tenant_slug=tenant,
            message="2",
            sender_id=phone,
            channel="whatsapp"
        )

        assert res.get("action") == "HANDOVER_TO_HUMAN"
        assert res.get("bot_paused") is True
        assert res.get("current_state") == "HANDOVER_TO_HUMAN"
        assert "Admin" in res.get("reply", "")

@pytest.mark.asyncio
async def test_handover_kang_sakti_phrase_detection():
    tenant = "buzzerukm"
    phone = "6281111222333"

    with patch("app.services.whatsapp_service.get_supabase") as mock_sb:
        mock_client = MagicMock()
        mock_sb.return_value = mock_client
        mock_client.from_().select().eq().eq().maybe_single().execute.return_value = MagicMock(data=None)

        res = await unified_conversation_engine.process_chat(
            tenant_slug=tenant,
            message="sudah itu saja saya mau ngobrol dengan kang sakti ya makasih",
            sender_id=phone,
            channel="whatsapp"
        )

        assert res.get("action") == "HANDOVER_TO_HUMAN"
        assert res.get("bot_paused") is True
        assert "Admin" in res.get("reply", "")

@pytest.mark.asyncio
async def test_inbound_message_drop_when_paused():
    tenant = "buzzerukm"
    phone = "6281111222333"

    paused_session_data = {
        "id": "mock-sess-paused",
        "current_state": "HANDOVER_TO_HUMAN",
        "is_paused": True,
        "paused_until": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    }

    with patch("app.services.whatsapp_service.get_supabase") as mock_sb:
        mock_client = MagicMock()
        mock_sb.return_value = mock_client
        mock_client.from_().select().eq().eq().maybe_single().execute.return_value = MagicMock(data=paused_session_data)

        res = await unified_conversation_engine.process_chat(
            tenant_slug=tenant,
            message="apakah ada update?",
            sender_id=phone,
            channel="whatsapp"
        )

        assert res.get("action") == "DROP_PAUSED"
        assert res.get("reply") is None
        assert res.get("bot_paused") is True

def test_rotary_service_checks_supabase_pause():
    tenant = "buzzerukm"
    phone = "6281111222333"

    active_pause_data = {
        "current_state": "HANDOVER_TO_HUMAN",
        "is_paused": True,
        "paused_until": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    }

    with patch("app.services.whatsapp_service.get_supabase") as mock_sb:
        mock_client = MagicMock()
        mock_sb.return_value = mock_client
        mock_client.from_().select().eq().eq().maybe_single().execute.return_value = MagicMock(data=active_pause_data)

        is_paused = rotary_routing_service.is_bot_paused_for_phone(tenant, phone)
        assert is_paused is True
