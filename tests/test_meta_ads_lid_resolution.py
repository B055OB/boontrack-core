import pytest
from unittest.mock import patch, AsyncMock
from app.routes.whatsapp_gateway_routes import process_evolution_webhook_payload

@pytest.mark.asyncio
async def test_meta_ads_lid_resolution():
    """
    Verifies that when an inbound message arrives with remoteJid ending with @lid
    and remoteJidAlt containing @s.whatsapp.net, remoteJidAlt is prioritized
    so the customer phone is accurately resolved.
    """
    lid_payload = {
        "event": "messages.upsert",
        "instance": "tumbuh-kembang-anak",
        "data": {
            "key": {
                "id": "ACB5AC5FACBF782AED3AE91B1F7A790C",
                "fromMe": False,
                "remoteJid": "4501142540386@lid",
                "remoteJidAlt": "6289501265422@s.whatsapp.net",
                "addressingMode": "lid",
            },
            "pushName": "Sayyidatul Fitri",
            "messageType": "conversation",
            "message": {
                "conversation": "Halo, saya ingin konsultasi",
            },
        },
    }

    captured_phone = {}

    async def mock_ingress(tenant_slug, sender_phone, **kwargs):
        captured_phone["ingress_phone"] = sender_phone
        from app.services.ingress_pipeline import IngressPipelineResult
        return IngressPipelineResult(status_code=200, allowed=True)

    async def mock_process_inbound(payload):
        captured_phone["inbound_phone"] = payload.sender_phone
        return {"status": "success", "reply_text": "Halo!"}

    mock_conn = {
        "tenant_id": "tumbuh-kembang-anak",
        "tenant_slug": "tumbuh-kembang-anak",
        "instance_name": "tumbuh-kembang-anak",
        "mode": "DEDICATED",
        "phone_number": "6285129992305",
    }

    with patch("app.routes.whatsapp_gateway_routes.get_connection_by_instance", return_value=mock_conn), \
         patch("app.services.ingress_pipeline.ingress_pipeline.evaluate_ingress", side_effect=mock_ingress), \
         patch("app.routes.whatsapp_gateway_routes.process_inbound_message", side_effect=mock_process_inbound), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http_post, \
         patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as mock_resolve:

        from unittest.mock import MagicMock
        mock_ctx = MagicMock()
        mock_ctx.slug = "tumbuh-kembang-anak"
        mock_ctx.metadata = {"is_bot_active": True, "bot_paused": False}
        mock_resolve.return_value = mock_ctx

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = {"key": {"id": "out_123"}}
        mock_http_post.return_value = mock_http_response

        res = await process_evolution_webhook_payload(lid_payload, tenant_slug="tumbuh-kembang-anak")

        assert captured_phone.get("ingress_phone") == "6289501265422"
        assert captured_phone.get("inbound_phone") == "6289501265422"

        # Verify outbound call used the real phone number, not LID
        outbound_call = mock_http_post.call_args_list[-1]
        outbound_payload = outbound_call.kwargs.get("json", {})
        assert outbound_payload.get("number") == "6289501265422"
