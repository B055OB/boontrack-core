import pytest
import asyncio
import uuid
from unittest.mock import patch, AsyncMock
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web

from app.core.server import create_web_app
from app.services.ctwa_state_engine import ctwa_state_engine, SINGLE_OFFER_PRICE
from app.services.whatsapp_service import normalize_phone_number


class TestCtwaWhatsAppWebhookFlow(AioHTTPTestCase):

    async def get_application(self):
        return create_web_app()

    @unittest_run_loop
    async def test_health_shows_whatsapp_central_active(self):
        """Verifikasi bahwa /health melaporkan whatsapp_central berstatus active."""
        resp = await self.client.get("/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("tenants", {}).get("whatsapp_central"), "active")
        self.assertEqual(data.get("tenants", {}).get("whatsapp_gateway"), "active")

    @unittest_run_loop
    async def test_fresh_lead_reset_state(self):
        """Verifikasi bahwa tester numbers berada dalam kondisi fresh lead tanpa session lock."""
        for num in ["081237450222", "6281237450222", "081977655099", "6281977655099"]:
            clean = normalize_phone_number(num) or num
            ctwa_state_engine.reset_session(clean)
            sess = ctwa_state_engine.get_session(clean)
            self.assertIn(sess.get("current_state"), ("STATE_0", "STATE_OFFER_PITCHED"))
            self.assertFalse(sess.get("is_settled"))

    @unittest_run_loop
    async def test_qris_intent_auto_response_and_qris_generation(self):
        """
        Verifikasi bahwa kata kunci 'saya mau bayar via qris' dari nomor penguji
        langsung menghasilkan QRIS Rp249.000 (downward unique code) dan teks instruksi bayar presisi.
        """
        tester_phone = "6281237450222"
        ctwa_state_engine.reset_session(tester_phone)

        with patch("app.services.ctwa_state_engine.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit, \
             patch("app.services.whatsapp.cloud_api.send_whatsapp_image", new_callable=AsyncMock) as mock_img, \
             patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_txt, \
             patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_initiate_checkout", new_callable=AsyncMock):

            mock_xendit.return_value = {
                "qr_string": "00020101021226600016ID.CO.XENDIT.WWW01189360099900000000005204581253033605802ID5911Test Store6007Jakarta6304ABCD",
                "qr_id": "qr_mock_123",
                "invoice_url": "https://checkout.xendit.co/web/INV-MOCK-123",
            }
            mock_img.return_value = {"messages": [{"id": "wamid.mock"}]}
            mock_txt.return_value = {"messages": [{"id": "wamid.mock"}]}

            res = await ctwa_state_engine.process_turn(
                phone=tester_phone,
                incoming_text="saya mau bayar via qris",
                sender_name="Alldy Tester",
            )

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "GATEKEEPER_QRIS_ISSUED")
            self.assertEqual(res.get("current_state"), "STATE_PAYMENT_PENDING")
            
            # Cek nominal Rp 249.000 minus kode unik 3 digit downward (248.001 - 248.900)
            total_amt = res.get("total_amount")
            self.assertGreaterEqual(total_amt, 248000)
            self.assertLessEqual(total_amt, SINGLE_OFFER_PRICE)
            self.assertIn("TAGIHAN RESMI PENDAFTARAN BATCH 1", res.get("reply"))
            self.assertIn("TOTAL TAGIHAN PRESISI", res.get("reply"))
            self.assertIsNotNone(res.get("media_url"))

    @unittest_run_loop
    async def test_evolution_webhook_inbound_onlineboost_triggers_qris(self):
        """
        Verifikasi webhook masuk via Evolution API untuk instance onlineboost:
        Menerima kata kunci 'saya mau bayar via qris' -> Membalas teks instruksi + QRIS.
        """
        tester_phone = "6281977655099"
        ctwa_state_engine.reset_session(tester_phone)

        payload = {
            "event": "messages.upsert",
            "instance": "onlineboost",
            "data": {
                "key": {
                    "remoteJid": f"{tester_phone}@s.whatsapp.net",
                    "fromMe": False,
                    "id": f"MSG_EVO_TEST_{uuid.uuid4().hex[:6]}"
                },
                "pushName": "Alldy Tester",
                "message": {
                    "conversation": "Halo min, saya mau bayar via qris"
                }
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_evo_send, \
             patch("app.services.ctwa_state_engine.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as mock_xendit, \
             patch("app.services.ctwa_state_engine.cloud_api.send_whatsapp_image", new_callable=AsyncMock) as mock_waba_img, \
             patch("app.services.ctwa_state_engine.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_waba_text, \
             patch("app.modules.tracking.capi_dispatcher.capi_dispatcher.dispatch_initiate_checkout", new_callable=AsyncMock):

            mock_xendit.return_value = {
                "qr_string": "00020101021226600016ID.CO.XENDIT.WWW01189360099900000000005204581253033605802ID5911Test Store6007Jakarta6304ABCD",
                "qr_id": "qr_mock_123",
                "invoice_url": "https://checkout.xendit.co/web/INV-MOCK-123",
            }

            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "SUCCESS"}
            mock_resp.text = '{"status":"SUCCESS"}'
            mock_evo_send.return_value = mock_resp

            resp = await self.client.post("/api/v1/whatsapp/webhook/evolution/onlineboost", json=payload)
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            print("\nDEBUG EVOLUTION WEBHOOK DATA:", data)
            
            # Memastikan tidak di-drop karena tenant mismatch atau unmapped instance
            self.assertNotEqual(data.get("reason"), "SECURITY_UNMAPPED_WHATSAPP_INSTANCE")
            self.assertNotEqual(data.get("reason"), "tenant_mismatch")
            self.assertEqual(data.get("status"), "success")

            # Memverifikasi bahwa outbound dispatch mengirim media/caption ke nomor penguji via WABA Meta API atau Baileys
            self.assertTrue(mock_waba_img.called or mock_evo_send.called)
            if mock_waba_img.called:
                call_kwargs = mock_waba_img.call_args.kwargs
                self.assertEqual(call_kwargs.get("to_phone"), tester_phone)
                self.assertIn("TAGIHAN RESMI PENDAFTARAN BATCH 1", call_kwargs.get("caption", ""))
            else:
                send_call_args = mock_evo_send.call_args[1].get("json") or {}
                self.assertEqual(send_call_args.get("number"), tester_phone)
                caption = send_call_args.get("caption") or send_call_args.get("text") or ""
                self.assertIn("TAGIHAN RESMI PENDAFTARAN BATCH 1", caption)
