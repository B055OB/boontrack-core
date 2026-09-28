"""tests/test_whatsapp_inbound_media_gemini.py
Comprehensive Verification for WhatsApp Inbound Media (Evolution API)
connected to Gemini Multimodal Pipeline.
"""

import base64
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.whatsapp.evolution import get_base64_from_media_message
from app.services.whatsapp_service import get_base64_from_media_message as reexported_get_b64
from app.services.ai_gateway.providers import GeminiProvider
from app.services.ai_engine import commerce_ai_engine
from app.services.unified_conversation_service import unified_conversation_engine

client = TestClient(app)


# ============================================================================
# 1. Evolution API getBase64FromMediaMessage Helper Tests
# ============================================================================

@pytest.mark.asyncio
async def test_get_base64_from_media_message_success():
    """Memverifikasi pemanggilan POST /chat/getBase64FromMediaMessage/{instance} berhasil."""
    fake_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"base64": fake_b64}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        msg_payload = {
            "key": {"id": "MSG_123", "remoteJid": "628123456789@s.whatsapp.net"},
            "message": {
                "imageMessage": {
                    "mimetype": "image/jpeg",
                    "caption": "Tanya produk ini"
                }
            }
        }

        res = await get_base64_from_media_message("test-instance", msg_payload)
        assert res == fake_b64

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "/chat/getBase64FromMediaMessage/test-instance" in call_url
        call_body = mock_post.call_args[1]["json"]
        assert call_body["message"]["key"]["id"] == "MSG_123"
        assert call_body["convertToMp4"] is False


@pytest.mark.asyncio
async def test_get_base64_from_media_message_formats_raw_base64():
    """Memverifikasi penambahan prefix data URL jika Evolution mengembalikan base64 polos."""
    raw_b64 = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"base64": raw_b64}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        msg_payload = {
            "key": {"id": "MSG_456"},
            "message": {
                "imageMessage": {
                    "mimetype": "image/png"
                }
            }
        }

        res = await get_base64_from_media_message("instance_png", msg_payload)
        assert res == f"data:image/png;base64,{raw_b64}"


@pytest.mark.asyncio
async def test_get_base64_from_media_message_failure_handles_gracefully():
    """Memverifikasi jika Evolution API error, helper mengembalikan None tanpa melempar exception."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = '{"error": "Message not found"}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await get_base64_from_media_message("test_inst", {"key": {"id": "NON_EXISTENT"}})
        assert res is None


def test_reexported_helper():
    """Memverifikasi helper diexport di app.services.whatsapp_service."""
    assert reexported_get_b64 is get_base64_from_media_message


# ============================================================================
# 2. Webhook Ingress WhatsApp Inbound Media Tests
# ============================================================================

@pytest.mark.asyncio
async def test_evolution_webhook_downloads_base64_and_forwards_to_pipeline():
    """
    Ketika user mengirim gambar (imageMessage) tanpa base64 di payload webhook:
    1. Webhook otomatis memanggil getBase64FromMediaMessage ke Evolution API.
    2. Payload base64 & mimetype diteruskan ke InboundPayload untuk AI pipeline.
    """
    dummy_b64_content = base64.b64encode(b"gambar_produk_baju").decode("utf-8")
    full_data_url = f"data:image/jpeg;base64,{dummy_b64_content}"

    with patch("app.routes.whatsapp_gateway_routes.get_base64_from_media_message", new_callable=AsyncMock) as mock_get_b64, \
         patch("app.routes.whatsapp_gateway_routes.upload_media_to_r2") as mock_r2, \
         patch("app.routes.whatsapp_gateway_routes.process_inbound_message", new_callable=AsyncMock) as mock_process, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_get_b64.return_value = full_data_url
        mock_r2.return_value = "https://r2.boontrack.com/img_test.jpg"
        mock_process.return_value = {"reply_text": "Produk ini adalah Kemeja Flannel seharga Rp 150.000."}
        mock_post.return_value.status_code = 200

        webhook_payload = {
            "event": "messages.upsert",
            "instance": "onlineboost",
            "data": {
                "key": {
                    "remoteJid": "628123456789@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG_PROD_999"
                },
                "pushName": "Budi",
                "message": {
                    "imageMessage": {
                        "caption": "Kak ini barangnya masih ada?",
                        "mimetype": "image/jpeg"
                        # base64 sengaja TIDAK dikirimkan di payload webhook
                    }
                }
            }
        }

        res = client.post("/api/v1/whatsapp/webhook/evolution/onlineboost", json=webhook_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["image_received"] is True

        # Verifikasi get_base64_from_media_message dipanggil
        mock_get_b64.assert_called_once()

        # Verifikasi process_inbound_message menerima image_base64 dan mime_type
        mock_process.assert_called_once()
        inbound_payload = mock_process.call_args[0][0]
        assert inbound_payload.image_base64 == full_data_url
        assert inbound_payload.mime_type == "image/jpeg"
        assert inbound_payload.message_body == "Kak ini barangnya masih ada?"


@pytest.mark.asyncio
async def test_evolution_webhook_image_without_caption_uses_default_prompt():
    """
    Ketika user mengirim gambar tanpa caption:
    Pesan otomatis diset: 'Tolong analisa gambar ini sesuai konteks toko.'
    """
    dummy_b64 = "data:image/jpeg;base64,QUJD"

    with patch("app.routes.whatsapp_gateway_routes.get_base64_from_media_message", new_callable=AsyncMock) as mock_get_b64, \
         patch("app.routes.whatsapp_gateway_routes.upload_media_to_r2") as mock_r2, \
         patch("app.routes.whatsapp_gateway_routes.process_inbound_message", new_callable=AsyncMock) as mock_process, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_get_b64.return_value = dummy_b64
        mock_r2.return_value = "https://r2.boontrack.com/img_test.jpg"
        mock_process.return_value = {"reply_text": "Gambar bukti transfer telah kami terima."}
        mock_post.return_value.status_code = 200

        webhook_payload = {
            "event": "messages.upsert",
            "instance": "onlineboost",
            "data": {
                "key": {
                    "remoteJid": "628123456789@s.whatsapp.net",
                    "fromMe": False,
                    "id": "MSG_IMG_NO_CAPTION"
                },
                "message": {
                    "imageMessage": {
                        "mimetype": "image/jpeg"
                        # Caption kosong
                    }
                }
            }
        }

        res = client.post("/api/v1/whatsapp/webhook/evolution/onlineboost", json=webhook_payload)
        assert res.status_code == 200

        mock_process.assert_called_once()
        inbound_payload = mock_process.call_args[0][0]
        assert inbound_payload.message_body == "Tolong analisa gambar ini sesuai konteks toko."
        assert inbound_payload.image_base64 == dummy_b64


# ============================================================================
# 3. Gemini Multimodal Pipeline (GeminiProvider with inlineData)
# ============================================================================

@pytest.mark.asyncio
async def test_gemini_provider_sends_inlinedata_when_image_base64_present():
    """
    Memverifikasi bahwa GeminiProvider menyertakan objek inlineData
    pada payload REST API Gemini saat context memuat image_base64.
    """
    provider = GeminiProvider()
    provider.api_key = "test_gemini_api_key_123"

    mock_session = MagicMock()
    mock_cm = AsyncMock()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value='{"candidates": [{"content": {"parts": [{"text": "{\\"reply\\": \\"Bukti transfer Rp 100.000 valid.\\"}"}]}}], "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 20}}')
    mock_cm.__aenter__.return_value = mock_response
    mock_session.post.return_value = mock_cm

    test_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    context = {
        "image_base64": test_b64,
        "mime_type": "image/jpeg",
        "temperature": 0.0,
    }

    res_text, p_tok, c_tok = await provider.call(
        session=mock_session,
        user_message="Tolong cek bukti transfer ini",
        context=context,
        system_prompt="Anda asisten toko resmi.",
        model_name="gemini-3.8-flash",
    )

    assert "Bukti transfer Rp 100.000 valid." in res_text

    # Verifikasi payload POST yang dikirim ke generativelanguage.googleapis.com
    mock_session.post.assert_called_once()
    called_url = mock_session.post.call_args[0][0]
    assert "gemini-3.8-flash:generateContent" in called_url

    called_json = mock_session.post.call_args[1]["json"]
    parts = called_json["contents"][0]["parts"]
    assert len(parts) == 2
    assert parts[0]["text"] == "Tolong cek bukti transfer ini"
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert parts[1]["inlineData"]["data"] == "/9j/4AAQSkZJRg=="


# ============================================================================
# 4. Unified Conversation Engine Multimodal Routing
# ============================================================================

@pytest.mark.asyncio
async def test_unified_conversation_engine_routes_image_directly_to_commerce_ai():
    """
    Memverifikasi bahwa pesan yang memuat gambar tidak dicegat oleh
    menu sapaan statis atau guardrail produk tak dikenal, melainkan langsung
    diteruskan ke Commerce AI Engine dengan membawa image_base64.
    """
    test_img = "data:image/jpeg;base64,QUJDREVGR0g="

    with patch.object(commerce_ai_engine, "generate_commerce_response", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "Gambar produk tersebut adalah Paket Pro Scale seharga Rp 299.000."

        res = await unified_conversation_engine.process_chat(
            tenant_slug="onlineboost",
            message="",
            sender_id="628123456789",
            sender_name="Budi",
            channel="whatsapp",
            image_base64=test_img,
            mime_type="image/jpeg",
        )

        assert res["success"] is True
        assert "Paket Pro Scale" in res["reply"]

        mock_gen.assert_called_once()
        gen_kwargs = mock_gen.call_args[1]
        assert gen_kwargs["image_base64"] == test_img
        assert gen_kwargs["mime_type"] == "image/jpeg"
        assert gen_kwargs["user_message"] == "Tolong analisa gambar ini sesuai konteks toko."
