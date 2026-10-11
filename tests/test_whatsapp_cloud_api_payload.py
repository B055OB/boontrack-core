"""
tests/test_whatsapp_cloud_api_payload.py
----------------------------------------
Test suite validating:
1. Meta Cloud API Graph v20.0 payload builder compliance for /messages
2. send_text and send_whatsapp_text parameter normalization & error resilience
3. Immediate inbound message persistence to Supabase conversations/messages
   even when outbound bot response fails with HTTP 400.
4. app.services.whatsapp_cloud_api module exports.
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.whatsapp_cloud_api import (
    build_whatsapp_text_payload,
    send_text,
    send_whatsapp_text,
    log_to_supabase_messages,
)
from app.whatsapp.traffic_splitter import (
    TenantWebhookRouter,
    PlatformWebhookRouter,
    WebhookExecutionTrace,
)
from app.schemas.context import TenantRuntimeContext


class TestWhatsAppCloudApiPayload:
    def test_build_whatsapp_text_payload_standard_v20(self):
        """Validasi format standar Meta Cloud API Graph v20.0."""
        payload = build_whatsapp_text_payload(
            to="+6288226098088",
            text="Halo Kak, terima kasih sudah menghubungi kami!",
        )

        assert payload["messaging_product"] == "whatsapp"
        assert payload["recipient_type"] == "individual"
        assert payload["to"] == "6288226098088"  # stripped +
        assert payload["type"] == "text"
        assert payload["text"] == {
            "body": "Halo Kak, terima kasih sudah menghubungi kami!"
        }
        assert "preview_url" not in payload["text"]

    def test_build_whatsapp_text_payload_with_preview_url(self):
        """Validasi opsi preview_url."""
        payload = build_whatsapp_text_payload(
            to="081234567890",
            text="Kunjungi kami di https://shop.boontrack.com",
            preview_url=True,
        )

        assert payload["to"] == "6281234567890"  # 08 converted to 62
        assert payload["text"]["preview_url"] is True
        assert payload["text"]["body"] == "Kunjungi kami di https://shop.boontrack.com"

    def test_build_whatsapp_text_payload_raises_on_empty_to(self):
        """Memastikan 'to' tidak boleh kosong/null."""
        with pytest.raises(ValueError, match="Recipient phone number"):
            build_whatsapp_text_payload(to="", text="Test message")

        with pytest.raises(ValueError, match="Recipient phone number"):
            build_whatsapp_text_payload(to=None, text="Test message")


class TestSendTextDispatch:
    @pytest.mark.asyncio
    async def test_send_text_alias_and_flexible_kwargs(self):
        """send_text menerima keyword fleksibel 'to', 'recipient', 'to_phone'."""
        with patch("app.services.whatsapp.cloud_api.get_wa_credentials") as mock_cred, \
             patch("httpx.AsyncClient.post") as mock_post, \
             patch("app.services.whatsapp.cloud_api.log_to_supabase_messages", new_callable=AsyncMock) as mock_log:

            mock_cred.return_value = ("test-token", "1419090974617162", "v20.0")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"messages": [{"id": "wamid.test123"}]}
            mock_post.return_value = mock_resp

            # Panggil dengan kwarg 'recipient'
            res = await send_text(recipient="6288226098088", text="Halo dari OnlineBoost")
            assert res is not None

            # Verifikasi payload yang dikirim ke httpx.post
            call_kwargs = mock_post.call_args[1]
            sent_json = call_kwargs["json"]
            assert sent_json["messaging_product"] == "whatsapp"
            assert sent_json["recipient_type"] == "individual"
            assert sent_json["to"] == "6288226098088"
            assert sent_json["type"] == "text"
            assert sent_json["text"]["body"] == "Halo dari OnlineBoost"

    @pytest.mark.asyncio
    async def test_send_text_handles_meta_400_and_logs_failure(self):
        """Jika Meta Cloud API merespons 400 Bad Request, log kegagalan tetap tercatat di Supabase."""
        with patch("app.services.whatsapp.cloud_api.get_wa_credentials") as mock_cred, \
             patch("httpx.AsyncClient.post") as mock_post, \
             patch("app.services.whatsapp.cloud_api.log_to_supabase_messages", new_callable=AsyncMock) as mock_log:

            mock_cred.return_value = ("test-token", "1419090974617162", "v20.0")
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.text = '{"error":{"message":"(#100) The parameter recipient is required."}}'
            mock_post.return_value = mock_resp

            res = await send_whatsapp_text(
                to_phone="6288226098088",
                text="Tes balasan",
                tenant_id="onlineboost",
            )
            assert res is None

            # Pastikan log_to_supabase_messages dipanggil dengan metadata failed
            assert mock_log.called
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs["sender"] == "bot"
            assert call_kwargs["metadata"]["status"] == "failed"
            assert call_kwargs["metadata"]["status_code"] == 400


class TestInboundMessagePersistence:
    @pytest.mark.asyncio
    async def test_tenant_webhook_router_persists_inbound_on_outbound_failure(self):
        """
        Pesan masuk dari user HARUS tersimpan di tabel conversations/messages Supabase
        meskipun balasan bot outbound mengalami kegagalan 400.
        """
        tenant_context = TenantRuntimeContext(
            tenant_id="onlineboost",
            slug="onlineboost",
            name="OnlineBoost ID",
            is_active=True,
            metadata={"waba_phone_number_id": "1419090974617162"}
        )

        trace = WebhookExecutionTrace(
            message_id="wamid.inbound_999",
            phone_number_id="1419090974617162",
            sender_phone="628123456789",
            raw_text="Halo apa ini OnlineBoost?",
        )

        with patch("app.services.whatsapp.cloud_api.log_to_supabase_messages", new_callable=AsyncMock) as mock_log, \
             patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send:

            # Simulasikan send_whatsapp_text gagal (None) karena 400
            mock_send.return_value = None

            raw_msg = {
                "id": "wamid.inbound_999",
                "from": "628123456789",
                "text": {"body": "Halo apa ini OnlineBoost?"},
                "type": "text",
                "timestamp": "1728615000",
            }

            result = await TenantWebhookRouter.handle(
                tenant_context=tenant_context,
                sender_phone="628123456789",
                incoming_text="Halo apa ini OnlineBoost?",
                phone_number_id="1419090974617162",
                contact_name="Budi",
                raw_msg=raw_msg,
                trace=trace,
            )

            # Inbound message HARUS tercatat
            mock_log.assert_called()
            # Cek panggilan pertama adalah logging pesan masuk dari user
            first_log_call = mock_log.call_args_list[0][1]
            assert first_log_call["sender"] == "user"
            assert first_log_call["text"] == "Halo apa ini OnlineBoost?"
            assert first_log_call["tenant_id"] == "onlineboost"
            assert first_log_call["user_phone"] == "628123456789"
            assert first_log_call["user_name"] == "Budi"
            assert first_log_call["metadata"]["direction"] == "inbound"
            assert first_log_call["metadata"]["wamid"] == "wamid.inbound_999"

    @pytest.mark.asyncio
    async def test_platform_webhook_router_persists_inbound_user_message(self):
        """PlatformWebhookRouter juga mencatat pesan masuk user ke Supabase."""
        trace = WebhookExecutionTrace(
            message_id="wamid.platform_inbound",
            phone_number_id="1365010890024026",
            sender_phone="628123456789",
            raw_text="AKTIVASI BT-XYZ123",
        )

        with patch("app.services.whatsapp.cloud_api.log_to_supabase_messages", new_callable=AsyncMock) as mock_log, \
             patch("app.whatsapp.traffic_splitter.PlatformWebhookRouter._process_activation", new_callable=AsyncMock) as mock_proc:

            mock_proc.return_value = {"status": "ok"}
            raw_msg = {"id": "wamid.platform_inbound", "from": "628123456789"}

            await PlatformWebhookRouter.handle(
                sender_phone="628123456789",
                incoming_text="AKTIVASI BT-XYZ123",
                phone_number_id="1365010890024026",
                raw_msg=raw_msg,
                trace=trace,
            )

            mock_log.assert_called()
            user_calls = [c[1] for c in mock_log.call_args_list if c[1].get("sender") == "user"]
            assert len(user_calls) >= 1
            user_call = user_calls[0]
            assert user_call["text"] == "AKTIVASI BT-XYZ123"
            assert user_call["user_phone"] == "628123456789"
