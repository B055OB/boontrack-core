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


@pytest.mark.asyncio
async def test_evolution_webhook_image_message_upload_r2():
    """Memverifikasi bahwa webhook Evolution API dengan imageMessage mengupload media ke R2 dan menyertakan media_url."""
    import base64
    dummy_bytes = b"fake_image_binary_content"
    dummy_b64 = base64.b64encode(dummy_bytes).decode("utf-8")
    expected_r2_url = "https://pub-cdf9b905df884053a60ef8bdb777d463.r2.dev/media/test12345.jpg"

    with patch("app.routes.whatsapp_gateway_routes.upload_media_to_r2") as mock_r2, \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock) as mock_log, \
         patch("app.routes.whatsapp_gateway_routes.process_inbound_message", new_callable=AsyncMock) as mock_process:

        mock_r2.return_value = expected_r2_url
        mock_process.return_value = {"reply_text": "Terima kasih atas kiriman gambarnya!"}

        payload = {
            "event": "messages.upsert",
            "instance": "onlineboost",
            "data": {
                "key": {
                    "remoteJid": "628987654321@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG_IMG_001"
                },
                "message": {
                    "imageMessage": {
                        "caption": "Bukti transfer",
                        "mimetype": "image/jpeg",
                        "base64": dummy_b64
                    }
                }
            }
        }

        res = client.post("/api/v1/whatsapp/webhook/evolution/onlineboost", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["media_url"] == expected_r2_url

        # Pastikan upload_media_to_r2 dipanggil dengan bytes yang di-decode
        mock_r2.assert_called_once()
        call_kwargs = mock_r2.call_args[1]
        assert call_kwargs["file_bytes"] == dummy_bytes
        assert "MSG_IMG_001" in call_kwargs["file_name"]

        # Pastikan log_to_supabase_messages dipanggil dengan parameter media_url
        mock_log.assert_called_once()
        log_kwargs = mock_log.call_args[1]
        assert log_kwargs["media_url"] == expected_r2_url
        assert log_kwargs["text"] == "Bukti transfer"
        assert log_kwargs["user_phone"] == "628987654321"

