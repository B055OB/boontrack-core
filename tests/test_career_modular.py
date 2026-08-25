import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

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
            params={"hub.mode": "subscribe", "hub.verify_token": "boontrack_career_token", "hub.challenge": "123456"}
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

    def test_legacy_wrapper_exports(self):
        self.assertEqual(handle_incoming_whatsapp, legacy_handle_incoming)
        self.assertEqual(verify_webhook, legacy_verify_webhook)


if __name__ == "__main__":
    unittest.main()

