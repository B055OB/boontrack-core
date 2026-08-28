import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from app.tenants.career.config import VERIFY_TOKEN
from app.tenants.career.service import career_service, GLOBAL_USER_STATES
from app.tenants.career.router import verify_webhook, handle_incoming_whatsapp, register_career_routes
from app.routes.whatsapp_career import (
    handle_incoming_whatsapp as legacy_handle_incoming,
    verify_webhook as legacy_verify_webhook
)


class TestCareerModular(AioHTTPTestCase):

    async def get_application(self):
        app = web.Application()
        register_career_routes(app)
        return app

    def setUp(self):
        super().setUp()
        GLOBAL_USER_STATES.clear()

    @unittest_run_loop
    async def test_verify_webhook_success(self):
        resp = await self.client.get(
            "/api/v1/tenants/boontrack-career/webhook/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "123456"}
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.text(), "123456")

    @unittest_run_loop
    async def test_verify_webhook_failure(self):
        resp = await self.client.get(
            "/api/v1/tenants/boontrack-career/webhook/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong_token", "hub.challenge": "123456"}
        )
        self.assertEqual(resp.status, 403)

    @unittest_run_loop
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_handle_incoming_freemium_menu(self, mock_log, mock_send_buttons):
        mock_send_buttons.return_value = {"status": "success"}

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "interactive",
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {
                                    "id": "btn_menu",
                                    "title": "🏠 Menu Utama"
                                }
                            }
                        }]
                    }
                }]
            }]
        }

        resp = await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status, 200)
        mock_send_buttons.assert_called_once()
        self.assertEqual(mock_send_buttons.call_args[1]["header_text"], "BOONTRACK CAREER")

    @unittest_run_loop
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_handle_incoming_premium_unlocked_menu(self, mock_log, mock_send_buttons):
        mock_send_buttons.return_value = {"status": "success"}

        # Set user as paid premium
        GLOBAL_USER_STATES["62899998888"] = {"is_premium_paid": True, "data": {"nama_panggilan": "Budi"}}

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "text",
                            "text": {"body": "menu"}
                        }]
                    }
                }]
            }]
        }

        resp = await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status, 200)
        mock_send_buttons.assert_called_once()
        self.assertIn("BOONTRACK CAREER PRO", mock_send_buttons.call_args[1]["header_text"])

    @unittest_run_loop
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_developer_whitelist_bypass(self, mock_log, mock_send_buttons):
        mock_send_buttons.return_value = {"status": "success"}

        # Whitelisted developer number (fresh state without prior payment)
        dev_phone = "6281237450222"
        self.assertNotIn(dev_phone, GLOBAL_USER_STATES)

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Developer Alldy"}, "wa_id": dev_phone}],
                        "messages": [{
                            "from": dev_phone,
                            "type": "text",
                            "text": {"body": "menu"}
                        }]
                    }
                }]
            }]
        }

        resp = await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status, 200)
        mock_send_buttons.assert_called_once()
        
        # Verify whitelist auto-upgraded session
        self.assertTrue(GLOBAL_USER_STATES[dev_phone]["is_premium_paid"])
        self.assertEqual(GLOBAL_USER_STATES[dev_phone]["tier"], "premium_unlocked")
        self.assertIn("BOONTRACK CAREER PRO", mock_send_buttons.call_args[1]["header_text"])

    @unittest_run_loop
    @patch("app.tenants.career.service.ai_gateway.generate")
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.send_whatsapp_text")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_job_matcher_ai_workflow(self, mock_log, mock_send_text, mock_send_buttons, mock_ai_generate):
        mock_ai_generate.return_value = "🎯 *HASIL ANALISIS KECOCOKAN LOKER*\nSkor: 90%"

        # 1. User clicks btn_job_match
        payload_1 = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "interactive",
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {"id": "btn_job_match", "title": "🎯 Job Matcher AI"}
                            }
                        }]
                    }
                }]
            }]
        }
        await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload_1)
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["mode"], "job_match")

        # 2. User inputs job description text
        payload_2 = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "text",
                            "text": {"body": "Dibutuhkan Senior Backend Engineer mahir Python FastAPI PostgreSQL Docker dan Microservices"}
                        }]
                    }
                }]
            }]
        }
        await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload_2)
        mock_ai_generate.assert_called_once()
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["mode"], "menu")

    @unittest_run_loop
    @patch("app.tenants.career.service.ai_gateway.generate")
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.send_whatsapp_text")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_mock_interview_multi_turn_flow(self, mock_log, mock_send_text, mock_send_buttons, mock_ai_generate):
        mock_ai_generate.side_effect = [
            "Evaluasi Ronda 1: Bagus",
            "Evaluasi Ronda 2: Runtut",
            "🏆 Rapor Akhir Kesiapan: 92/100"
        ]

        # 1. Start Mock Interview
        payload_start = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "interactive",
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {"id": "btn_mock_interview", "title": "🎙️ Simulasi HR"}
                            }
                        }]
                    }
                }]
            }]
        }
        await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload_start)
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["mode"], "mock_interview")
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["interview_step"], 1)

        # 2. Answer Ronda 1
        payload_ans1 = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "text",
                            "text": {"body": "Saya berpengalaman 4 tahun membangun sistem payment gateway dan meningkatkan reliabilitas 99.9%"}
                        }]
                    }
                }]
            }]
        }
        await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload_ans1)
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["interview_step"], 2)

        # 3. Answer Ronda 2
        payload_ans2 = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "text",
                            "text": {"body": "Saat server crash di tengah flash sale, saya membagi tim dalam triage bug dan rollback hotfix dalam 10 menit."}
                        }]
                    }
                }]
            }]
        }
        await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload_ans2)
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["interview_step"], 3)

        # 4. Answer Ronda 3 (Final)
        payload_ans3 = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "text",
                            "text": {"body": "Dalam 90 hari pertama saya akan memetakan arsitektur bot dan memangkas latency response di bawah 1 detik."}
                        }]
                    }
                }]
            }]
        }
        await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload_ans3)
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["mode"], "menu")

    @unittest_run_loop
    @patch("app.tenants.career.service.ai_gateway.generate")
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.send_whatsapp_text")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_salary_coach_workflow(self, mock_log, mock_send_text, mock_send_buttons, mock_ai_generate):
        mock_ai_generate.return_value = "💰 *PANDUAN BENCHMARK & STRATEGI NEGOSIASI GAJI*\nMedian: 15jt"

        # 1. User clicks btn_salary_coach
        payload_start = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "interactive",
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {"id": "btn_salary_coach", "title": "💰 Negosiasi Gaji"}
                            }
                        }]
                    }
                }]
            }]
        }
        await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload_start)
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["mode"], "salary_coach")

        # 2. User sends offer info
        payload_input = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Budi Santoso"}, "wa_id": "62899998888"}],
                        "messages": [{
                            "from": "62899998888",
                            "type": "text",
                            "text": {"body": "Senior Backend Engineer dapat tawaran 18 juta di Jakarta"}
                        }]
                    }
                }]
            }]
        }
        await self.client.post("/api/v1/tenants/boontrack-career/webhook/whatsapp", json=payload_input)
        mock_ai_generate.assert_called_once()
        self.assertEqual(GLOBAL_USER_STATES["62899998888"]["mode"], "menu")

    @unittest_run_loop
    @patch("app.tenants.career.service.analytics_service.log_funnel_event")
    @patch("app.tenants.career.service.send_whatsapp_text")
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.track_event")
    async def test_funnel_event_career_cv_review_submitted(self, mock_track, mock_send_btns, mock_send_text, mock_log_funnel):
        """Memvalidasi logging funnel event: career_cv_review_submitted saat hasil review CV selesai."""
        mock_log_funnel.return_value = True
        mock_send_text.return_value = {"status": "success"}
        mock_send_btns.return_value = {"status": "success"}

        review_data = {
            "overall_score": 88,
            "breakdown_scores": {"ats": 90, "formatting": 85},
            "findings": ["Pengalaman kerja sangat solid"]
        }

        await career_service.deliver_review_and_trigger_upsell(
            sender_wa_id="62811122233",
            filtered_data=review_data,
            filename="curriculum_vitae.pdf"
        )

        mock_log_funnel.assert_called_once()
        call_kwargs = mock_log_funnel.call_args[1]
        self.assertEqual(call_kwargs["event_name"], "career_cv_review_submitted")
        self.assertEqual(call_kwargs["user_id"], "62811122233")
        self.assertEqual(call_kwargs["tenant_id"], "boontrack-career")
        self.assertEqual(call_kwargs["metadata"]["score"], 88)
        self.assertEqual(call_kwargs["metadata"]["filename"], "curriculum_vitae.pdf")

    @unittest_run_loop
    @patch("app.tenants.career.service.analytics_service.log_funnel_event")
    @patch("app.tenants.career.service.parse_receipt_image")
    @patch("app.tenants.career.service.download_whatsapp_media")
    @patch("app.tenants.career.service.send_whatsapp_text")
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_funnel_event_career_premium_hr_converted(self, mock_log_msg, mock_send_btns, mock_send_text, mock_download, mock_ocr, mock_log_funnel):
        """Memvalidasi logging funnel event: career_premium_hr_converted saat struk terverifikasi via OCR."""
        mock_log_funnel.return_value = True
        mock_download.return_value = b"fake_image_bytes"
        mock_ocr.return_value = {
            "is_valid_receipt": True,
            "is_transfer_receipt": True,
            "amount": 25350,
            "nominal": 25350
        }

        GLOBAL_USER_STATES["62877788899"] = {
            "mode": "awaiting_rewrite_payment",
            "active_invoice": "BT-9901-350"
        }

        await career_service.handle_image(
            sender_wa_id="62877788899",
            display_name="Kandidat Pro",
            media_id="media_struk_999"
        )

        mock_log_funnel.assert_called_once()
        call_kwargs = mock_log_funnel.call_args[1]
        self.assertEqual(call_kwargs["event_name"], "career_premium_hr_converted")
        self.assertEqual(call_kwargs["user_id"], "62877788899")
        self.assertEqual(call_kwargs["tenant_id"], "boontrack-career")
        self.assertEqual(call_kwargs["metadata"]["amount"], 25350)
        self.assertEqual(call_kwargs["metadata"]["invoice_id"], "BT-9901-350")
        self.assertTrue(GLOBAL_USER_STATES["62877788899"]["is_premium_paid"])

    @unittest_run_loop
    @patch("app.tenants.career.service.analytics_service.log_funnel_event")
    @patch("app.tenants.career.service.process_unified_cv_step")
    @patch("app.tenants.career.service.send_whatsapp_text")
    @patch("app.tenants.career.service.send_whatsapp_document")
    @patch("app.tenants.career.service.safe_log_to_supabase_messages")
    async def test_funnel_event_career_cv_build_completed(self, mock_log_msg, mock_send_doc, mock_send_text, mock_cv_step, mock_log_funnel):
        """Memvalidasi logging funnel event: career_cv_build_completed saat wizard CV selesai."""
        mock_log_funnel.return_value = True
        mock_cv_step.return_value = {
            "reply_text": "CV Dasar Anda selesai!",
            "messages": ["CV Dasar Anda selesai!"],
            "file_path": None,
            "is_completed": True
        }

        GLOBAL_USER_STATES["62833344455"] = {
            "mode": "builder",
            "step": 8,
            "data": {}
        }

        await career_service.handle_text_or_button(
            sender_wa_id="62833344455",
            display_name="User Builder",
            user_text="Selesai",
            button_id=""
        )

        mock_log_funnel.assert_called_once()
        call_kwargs = mock_log_funnel.call_args[1]
        self.assertEqual(call_kwargs["event_name"], "career_cv_build_completed")
        self.assertEqual(call_kwargs["user_id"], "62833344455")
        self.assertEqual(call_kwargs["tenant_id"], "boontrack-career")
    @patch("app.tenants.career.service.send_whatsapp_image_link", new_callable=AsyncMock)
    @patch("app.tenants.career.service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.tenants.career.service.track_event", new_callable=AsyncMock)
    async def test_rewrite_button_sends_dynamic_qris_bytes_buffer(
        self,
        mock_track,
        mock_send_text,
        mock_send_image_link
    ):
        """Memvalidasi bahwa saat user memilih paket rewrite (10k), bot mengirim Pesan 1 (Rincian) dan Pesan 2 (Dynamic QRIS via URL)."""
        user_id = "628999888777"
        GLOBAL_USER_STATES[user_id] = {
            "mode": "menu",
            "step": 0,
            "data": {}
        }

        await career_service.handle_text_or_button(
            sender_wa_id=user_id,
            display_name="User Dynamic QRIS",
            user_text="",
            button_id="btn_rewrite_single"
        )

        # 1. Pesan 1: Teks Rincian Paket Terkirim
        mock_send_text.assert_called()
        text_calls = [call[0][1] for call in mock_send_text.call_args_list]
        self.assertTrue(any("INVOICE PAKET LAYANAN" in t for t in text_calls))
        self.assertTrue(any("Single CV Polish & ATS Rewrite" in t for t in text_calls))
        self.assertTrue(any("15 Menit" in t for t in text_calls))

        # 2. Pesan 2: Gambar QRIS Dinamis via URL terkirim
        mock_send_image_link.assert_called_once()
        args, kwargs = mock_send_image_link.call_args
        to_phone = (args[0] if args else None) or kwargs.get("to")
        self.assertEqual(to_phone, user_id)

        # Validasi image_url berupa QuickChart URL
        image_url = kwargs.get("image_url") or (args[1] if len(args) > 1 else None)
        self.assertIsInstance(image_url, str)
        self.assertIn("quickchart.io", image_url)

        # Validasi caption memuat instruksi scan dan nominal
        caption = kwargs.get("caption", "")
        self.assertIn("Silakan scan QRIS di atas untuk menyelesaikan pembayaran", caption)

        # Validasi state tersimpan sebagai awaiting_rewrite_payment
        self.assertEqual(GLOBAL_USER_STATES[user_id]["mode"], "awaiting_rewrite_payment")
        self.assertIsNotNone(GLOBAL_USER_STATES[user_id].get("active_invoice"))

    @patch("app.tenants.career.service.send_whatsapp_image_link", new_callable=AsyncMock)
    @patch("app.tenants.career.service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.tenants.career.service.track_event", new_callable=AsyncMock)
    async def test_pro_bundle_button_sends_dynamic_qris_and_invoice_details(
        self,
        mock_track,
        mock_send_text,
        mock_send_image_link
    ):
        """Memvalidasi bahwa saat user klik tombol Pro Bundle (25k), bot mengirim rincian paket 25k & Dynamic QRIS via URL."""
        user_id = "628999111222"
        GLOBAL_USER_STATES[user_id] = {
            "mode": "menu",
            "step": 0,
            "data": {}
        }

        await career_service.handle_text_or_button(
            sender_wa_id=user_id,
            display_name="User Pro Bundle",
            user_text="",
            button_id="btn_bundle_pro"
        )

        # 1. Pesan 1: Teks Rincian Paket Pro Bundle Terkirim
        mock_send_text.assert_called()
        text_calls = [call[0][1] for call in mock_send_text.call_args_list]
        self.assertTrue(any("Career Pro Bundle" in t for t in text_calls))
        self.assertTrue(any("25,000" in t or "25.000" in t for t in text_calls))

        # 2. Pesan 2: Gambar QRIS Dinamis via URL terkirim
        mock_send_image_link.assert_called_once()
        args, kwargs = mock_send_image_link.call_args
        image_url = kwargs.get("image_url") or (args[1] if len(args) > 1 else None)
        self.assertIsInstance(image_url, str)
        self.assertIn("quickchart.io", image_url)

        self.assertEqual(GLOBAL_USER_STATES[user_id]["mode"], "awaiting_rewrite_payment")

    @patch("app.tenants.career.service.download_whatsapp_media", new_callable=AsyncMock)
    @patch("app.tenants.career.service.extract_text_from_bytes")
    @patch("app.tenants.career.service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.tenants.career.service.send_whatsapp_image_link", new_callable=AsyncMock)
    async def test_handle_document_paraphrase_sends_two_message_sequence(
        self,
        mock_send_image_link,
        mock_send_text,
        mock_extract_text,
        mock_download_media
    ):
        """Memvalidasi urutan pengiriman dokumen intake: Pesan 1 (Teks Analisis), Pesan 2 (Dynamic QRIS via URL)."""
        user_id = "6281237450222"
        GLOBAL_USER_STATES[user_id] = {
            "mode": "paraphrase",
            "step": 0,
            "data": {}
        }
        mock_download_media.return_value = b"fake_pdf_bytes"
        mock_extract_text.return_value = "Bab 3 Metode Penelitian ini menguji pengaruh likuiditas terhadap profitabilitas perbankan nasional. " * 50

        await career_service.handle_document(
            sender_wa_id=user_id,
            display_name="User Skripsi",
            media_id="media_skripsi_123",
            filename="BAB III WORD.pdf"
        )

        # 1. Pesan 1: Teks Analisis Dokumen terkirim
        mock_send_text.assert_called()
        text_calls = [call[0][1] for call in mock_send_text.call_args_list]
        self.assertTrue(any("DOKUMEN BERHASIL DIANALISIS" in t for t in text_calls))

        # 2. Pesan 2: Dynamic QRIS via URL terkirim
        mock_send_image_link.assert_called_once()
        args, kwargs = mock_send_image_link.call_args
        target_phone = (args[0] if args else None) or kwargs.get("to")
        self.assertEqual(target_phone, user_id)

        image_url = kwargs.get("image_url") or (args[1] if len(args) > 1 else None)
        self.assertIsInstance(image_url, str)
        self.assertIn("quickchart.io", image_url)

        caption = kwargs.get("caption", "")
        self.assertIn("Silakan scan QRIS di atas untuk menyelesaikan pembayaran", caption)
        self.assertEqual(GLOBAL_USER_STATES[user_id]["mode"], "awaiting_rewrite_payment")

    @patch("app.tenants.career.service.download_whatsapp_media", new_callable=AsyncMock)
    @patch("app.tenants.career.service.extract_text_from_bytes")
    @patch("app.tenants.career.service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.tenants.career.service.send_whatsapp_buttons", new_callable=AsyncMock)
    @patch("app.tenants.career.service.send_whatsapp_image_link", new_callable=AsyncMock)
    async def test_cv_review_pay_per_job_upload_new_draft_resets_single_payment(
        self,
        mock_send_image_link,
        mock_send_buttons,
        mock_send_text,
        mock_extract_text,
        mock_download_media
    ):
        """Memvalidasi bahwa upload draft CV baru mereset status bayar single sebelumnya (Pay-Per-Job strict)."""
        user_id = "628555666777"
        
        # User sebelumnya sudah pernah bayar single draft
        GLOBAL_USER_STATES[user_id] = {
            "mode": "menu",
            "step": 0,
            "is_premium_paid": True,
            "tier": "single_draft_paid",
            "single_paid_draft": "INV-OLD-123",
            "data": {}
        }

        mock_download_media.return_value = b"fake_docx_bytes"
        mock_extract_text.return_value = "Nama: Budi Santoso. Pengalaman: Software Engineer di Startup selama 3 tahun."

        # User mengunggah dokumen CV baru
        await career_service.handle_document(
            sender_wa_id=user_id,
            display_name="Budi Payer",
            media_id="media_new_cv_doc",
            filename="CV_Baru_Draft_2.docx"
        )

        # 1. Status bayar single sebelumnya HARUS di-reset (bukan gratis selamanya)
        self.assertFalse(GLOBAL_USER_STATES[user_id].get("is_premium_paid"))
        self.assertEqual(GLOBAL_USER_STATES[user_id].get("tier"), "free")
        self.assertIsNone(GLOBAL_USER_STATES[user_id].get("single_paid_draft"))

        # 2. Saat user meminta rewrite untuk draft baru ini, wajib buat invoice baru
        await career_service.handle_text_or_button(
            sender_wa_id=user_id,
            display_name="Budi Payer",
            user_text="",
            button_id="btn_rewrite_single"
        )

        mock_send_image_link.assert_called_once()
        self.assertEqual(GLOBAL_USER_STATES[user_id]["mode"], "awaiting_rewrite_payment")
        new_inv = GLOBAL_USER_STATES[user_id].get("active_invoice")
        self.assertIsNotNone(new_inv)
        self.assertNotEqual(new_inv, "INV-OLD-123")

    @patch("app.tenants.career.service.download_whatsapp_media", new_callable=AsyncMock)
    @patch("app.tenants.career.service.extract_text_from_bytes")
    @patch("app.tenants.career.service.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.tenants.career.service.send_whatsapp_buttons", new_callable=AsyncMock)
    @patch("app.tenants.career.service.send_whatsapp_image", new_callable=AsyncMock)
    async def test_cv_review_active_unexpired_bundle_quota_persists_across_uploads(
        self,
        mock_send_image,
        mock_send_buttons,
        mock_send_text,
        mock_extract_text,
        mock_download_media
    ):
        """Memvalidasi bahwa kuota bundle aktif yang belum expired dapat digunakan untuk rewrite tanpa bayar ulang."""
        user_id = "628777888999"
        
        # User memiliki bundle aktif dengan kuota 3x (expired 30 hari ke depan)
        from datetime import datetime, timedelta
        exp_time = (datetime.now() + timedelta(days=30)).isoformat()
        GLOBAL_USER_STATES[user_id] = {
            "mode": "menu",
            "step": 0,
            "is_premium_paid": True,
            "tier": "bundle_active",
            "bundle_quota": 3,
            "bundle_expires_at": exp_time,
            "data": {}
        }

        mock_download_media.return_value = b"fake_docx_bytes"
        mock_extract_text.return_value = "Nama: Siti Aminah. Pengalaman: Product Manager di Fintech."

        # User unggah CV baru
        await career_service.handle_document(
            sender_wa_id=user_id,
            display_name="Siti Bundle",
            media_id="media_bundle_cv",
            filename="CV_Siti_Draft.pdf"
        )

        # Status bundle tetap aktif
        self.assertTrue(career_service.is_user_premium(user_id))
        self.assertEqual(GLOBAL_USER_STATES[user_id].get("bundle_quota"), 3)

        # Saat klik single rewrite, kuota dipotong 1 dan TIDAK membuat invoice QRIS baru
        await career_service.handle_text_or_button(
            sender_wa_id=user_id,
            display_name="Siti Bundle",
            user_text="",
            button_id="btn_rewrite_single"
        )

        mock_send_image.assert_not_called()
        self.assertEqual(GLOBAL_USER_STATES[user_id].get("bundle_quota"), 2)
        mock_send_text.assert_called()

    @patch("app.tenants.career.service.send_whatsapp_image_link", new_callable=AsyncMock)
    @patch("app.tenants.career.service.send_whatsapp_text", new_callable=AsyncMock)
    async def test_polish_rephrase_is_pure_pay_per_use_every_submission_generates_invoice(
        self,
        mock_send_text,
        mock_send_image_link
    ):
        """Memvalidasi bahwa Polish & Rephrase 100% pay-per-use dan selalu generate invoice baru berstatus WAITING_PAYMENT."""
        user_id = "628111222999"
        GLOBAL_USER_STATES[user_id] = {
            "mode": "paraphrase",
            "step": 0,
            "data": {}
        }

        raw_script = "Latar belakang penelitian ini bertujuan untuk menguji hipotesis kinerja keuangan terhadap kepuasan investor." * 5

        # Submisi naskah
        await career_service.handle_text_or_button(
            sender_wa_id=user_id,
            display_name="Penulis Jurnal",
            user_text=raw_script,
            button_id=""
        )

        # Harus membuat invoice QRIS baru via URL
        mock_send_image_link.assert_called_once()
        self.assertEqual(GLOBAL_USER_STATES[user_id]["mode"], "awaiting_rewrite_payment")
        active_inv = GLOBAL_USER_STATES[user_id].get("active_invoice")
        self.assertIsNotNone(active_inv)

    @unittest_run_loop
    @patch("app.tenants.career.service.get_supabase")
    @patch("app.tenants.career.service.send_whatsapp_buttons")
    async def test_navigation_keyword_cancels_unpaid_invoice_and_resets_to_menu(
        self, mock_send_buttons, mock_get_supabase
    ):
        """Validasi bahwa keyword navigasi ('menu', 'batal', 'reset', 'ulang', 'start')
        di state WAITING_PAYMENT otomatis membatalkan invoice UNPAID dan kembali ke menu utama."""
        from app.services.reconciliation_service import PAYMENT_INTENTS
        from datetime import datetime

        user_id = "628129990001"
        invoice_id = "INV-TEST-CANCEL-001"

        # Mock Supabase
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=[{"id": "job-1"}])
        mock_get_supabase.return_value = mock_client

        # Setup state sedang menunggu pembayaran
        GLOBAL_USER_STATES[user_id] = {
            "mode": "awaiting_rewrite_payment",
            "step": 0,
            "active_invoice": invoice_id,
            "awaiting_payment_at": datetime.now().isoformat(),
            "data": {}
        }
        PAYMENT_INTENTS[invoice_id] = {
            "invoice_id": invoice_id,
            "user_id": user_id,
            "status": "PENDING",
            "total_amount": 25300
        }

        # Test dengan keyword 'batal'
        await career_service.handle_text_or_button(
            sender_wa_id=user_id,
            display_name="User Batal",
            user_text="batal",
            button_id=""
        )

        # Verifikasi intent di memori dibatalkan
        self.assertEqual(PAYMENT_INTENTS[invoice_id]["status"], "CANCELLED")
        # Verifikasi state user kembali ke menu
        self.assertEqual(GLOBAL_USER_STATES[user_id]["mode"], "menu")
        self.assertIsNone(GLOBAL_USER_STATES[user_id]["active_invoice"])
        # Verifikasi menu utama dikirimkan
        mock_send_buttons.assert_called_once()

    @unittest_run_loop
    @patch("app.tenants.career.service.get_supabase")
    @patch("app.tenants.career.service.send_whatsapp_text")
    async def test_ttl_expiry_auto_cancels_unpaid_order(
        self, mock_send_text, mock_get_supabase
    ):
        """Validasi bahwa order UNPAID yang telah melewati TTL (> 30 menit)
        otomatis di-reset ke menu saat pesan baru masuk."""
        from app.services.reconciliation_service import PAYMENT_INTENTS
        from datetime import datetime, timedelta

        user_id = "628129990002"
        invoice_id = "INV-EXPIRED-30MIN"

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=[])
        mock_get_supabase.return_value = mock_client

        # Waktu dibuat 35 menit yang lalu (sudah expired)
        created_35m_ago = datetime.now() - timedelta(minutes=35)
        GLOBAL_USER_STATES[user_id] = {
            "mode": "awaiting_rewrite_payment",
            "step": 0,
            "active_invoice": invoice_id,
            "awaiting_payment_at": created_35m_ago.isoformat(),
            "data": {}
        }
        PAYMENT_INTENTS[invoice_id] = {
            "invoice_id": invoice_id,
            "user_id": user_id,
            "status": "PENDING",
            "created_at": created_35m_ago,
            "total_amount": 10450
        }

        # User mengirim pesan baru setelah sekian lama
        await career_service.handle_text_or_button(
            sender_wa_id=user_id,
            display_name="User Lama",
            user_text="halo bot",
            button_id=""
        )

        # Verifikasi auto-cancelled karena expired
        self.assertEqual(PAYMENT_INTENTS[invoice_id]["status"], "CANCELLED")
        self.assertEqual(GLOBAL_USER_STATES[user_id]["mode"], "menu")

    @unittest_run_loop
    @patch("app.tenants.career.service.send_whatsapp_text")
    async def test_awaiting_payment_non_nav_text_sends_polite_reminder(
        self, mock_send_text
    ):
        """Validasi bahwa jika user mengirim pesan teks sembarang saat WAITING_PAYMENT,
        bot tidak freeze/diam, melainkan mengirimkan reminder tagihan & opsi batal."""
        from app.services.reconciliation_service import PAYMENT_INTENTS
        from datetime import datetime

        user_id = "628129990003"
        invoice_id = "INV-REMINDER-001"

        GLOBAL_USER_STATES[user_id] = {
            "mode": "awaiting_rewrite_payment",
            "step": 0,
            "active_invoice": invoice_id,
            "awaiting_payment_at": datetime.now().isoformat(),
            "data": {}
        }
        PAYMENT_INTENTS[invoice_id] = {
            "invoice_id": invoice_id,
            "user_id": user_id,
            "status": "PENDING",
            "total_amount": 25300
        }

        # User kirim pesan teks bukan tombol dan bukan keyword reset
        await career_service.handle_text_or_button(
            sender_wa_id=user_id,
            display_name="User Bingung",
            user_text="sudah saya transfer ya kak",
            button_id=""
        )

        mock_send_text.assert_called_once()
        call_msg = mock_send_text.call_args[0][1]
        self.assertIn("MENUNGGU PEMBAYARAN", call_msg)
        self.assertIn("Rp25,300", call_msg)
        self.assertIn("struk", call_msg)
        self.assertIn("batal", call_msg)

    @unittest_run_loop
    @patch("scripts.reset_user_state.get_supabase")
    async def test_reset_user_state_script(self, mock_get_supabase):
        """Memvalidasi script utility scripts/reset_user_state.py dapat mereset user state secara tepat."""
        from scripts.reset_user_state import run_reset
        from app.services.reconciliation_service import PAYMENT_INTENTS
        from datetime import datetime

        user_id = "628129990004"
        invoice_id = "INV-SCRIPT-001"

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=[{"id": "job-1"}])
        mock_get_supabase.return_value = mock_client

        GLOBAL_USER_STATES[user_id] = {
            "mode": "awaiting_rewrite_payment",
            "step": 2,
            "active_invoice": invoice_id,
            "awaiting_payment_at": datetime.now().isoformat(),
            "data": {"position": "Engineer"}
        }
        PAYMENT_INTENTS[invoice_id] = {
            "invoice_id": invoice_id,
            "user_id": user_id,
            "status": "PENDING",
            "total_amount": 10000
        }

        res = await run_reset(user_id)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(GLOBAL_USER_STATES[user_id]["mode"], "menu")
        self.assertEqual(GLOBAL_USER_STATES[user_id]["step"], 0)
        self.assertIsNone(GLOBAL_USER_STATES[user_id]["active_invoice"])
        self.assertEqual(PAYMENT_INTENTS[invoice_id]["status"], "CANCELLED")

    def test_legacy_wrapper_exports(self):
        self.assertEqual(handle_incoming_whatsapp, legacy_handle_incoming)
        self.assertEqual(verify_webhook, legacy_verify_webhook)


if __name__ == "__main__":
    unittest.main()




