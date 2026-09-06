"""tests/test_whatsapp_gateway_routes.py
Integration & Whitelabel Branding Tests for BoonTrack WhatsApp Engine routes.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.main import app

client = TestClient(app)


def test_growth_session_connect_whitelabel_message():
    """Memverifikasi bahwa endpoint connect mengembalikan pesan resmi BoonTrack WhatsApp Engine tanpa menyebut pihak ketiga."""
    res = client.post("/api/v1/whatsapp/sessions/onlineboost/connect")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "BoonTrack WhatsApp Engine" in data["message"]
    assert "baileys" not in data["message"].lower()


@pytest.mark.asyncio
async def test_inbound_process_whitelabel_channel():
    """Memverifikasi inbound process berhasil dan mencatat channel 'boontrack_whatsapp_engine'."""
    with patch("app.routes.whatsapp_gateway_routes.commerce_ai_engine.generate_commerce_response", new_callable=AsyncMock) as mock_ai, \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock) as mock_log:
        
        mock_ai.return_value = "Halo dari toko! Ada yang bisa kami bantu?"
        
        payload = {
            "tenant_slug": "onlineboost",
            "sender_phone": "628123456789",
            "message_body": "Halo mau tanya produk",
            "sender_name": "Budi"
        }
        res = client.post("/api/v1/whatsapp/inbound-process", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert len(data["reply_text"]) > 0
        
        # Periksa channel logging yang dipanggil
        calls = mock_log.call_args_list
        assert len(calls) >= 1
        for call in calls:
            assert call.kwargs.get("channel") == "boontrack_whatsapp_engine"
            assert "baileys" not in call.kwargs.get("channel", "").lower()
