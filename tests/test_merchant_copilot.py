import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_merchant_copilot_endpoint_persona():
    # Mock boonpilot_service.chat agar mengembalikan jawaban Copilot Toko yang konsisten
    mock_copilot_response = {
        "reply": "Halo! Saya Copilot Toko Onlineboost siap membantu pantau omset dan kelola katalog produk Anda.",
        "description": "Halo! Saya Copilot Toko Onlineboost",
        "action_type": None,
        "status": "SUCCESS",
        "data": {"store": "Onlineboost", "active_orders": 12},
        "session_id": "copilot_sess_test_123"
    }

    with patch("app.services.boonpilot_service.boonpilot_service.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = mock_copilot_response

        response = client.post(
            "/api/v1/merchant/copilot",
            json={
                "tenant_slug": "onlineboost",
                "message": "Bagaimana omset toko saya hari ini?",
                "session_id": "test_sess_001"
            }
        )

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["status"] == "success"
        assert data["tenant_id"] == "onlineboost"
        assert "Onlineboost" in data["reply"]
        assert "Copilot" in data["reply"]
        # Pastikan BUKAN Persona Company Profile BoonTrack B2B
        assert "BoonTrack Group" not in data["reply"]
        assert "software kustom" not in data["reply"]
        assert "Holding" not in data["reply"]
        # DILARANG keras menyebut third-party engines
        assert "chatwoot" not in data["reply"].lower()
        assert len(data["quick_actions"]) > 0

@pytest.mark.asyncio
async def test_boonpilot_naming_convention_fallback():
    # Uji bahwa fallback tanpa mock menggunakan identitas resmi BoonPilot Copilot dan BoonTrack Inbox
    from app.services.boonpilot_service import boonpilot_service

    with patch("app.services.ai_gateway.ai_gateway.generate_for_agent", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = None  # Force fallback
        res = await boonpilot_service.chat(
            tenant_slug="onlineboost",
            message="apa yang bisa kamu lakukan?"
        )
        reply = res["reply"]
        assert "BoonPilot Copilot" in reply
        assert "BoonTrack Inbox" in reply
        assert "chatwoot" not in reply.lower()
