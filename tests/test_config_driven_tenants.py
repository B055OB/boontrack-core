import os
import json
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
import pydantic

from app.schemas.tenant_config import (
    TenantConfig,
    TenantIdentity,
    TenantPersona,
    TenantStatus,
    TenantMenuConfig,
    MenuItem,
    TenantChannelConfig,
    TenantPaymentConfig,
    TenantFeatureFlags,
)
from app.engines.generic_tenant_engine import GenericTenantEngine
from app.core.tenant_loader import (
    load_tenant_configs,
    register_config_driven_tenant_routes,
    load_dynamic_tenants,
    TENANT_STATUS,
)


class TestConfigDrivenTenants(unittest.IsolatedAsyncioTestCase):
    """Sprint B: Unit & Integration Tests for Config-Driven Architecture."""

    def setUp(self):
        self._status_backup = dict(TENANT_STATUS)
        self.sample_valid_config = TenantConfig(
            identity=TenantIdentity(
                tenant_id="test_edu_pilot",
                name="Pilot Edu Assistant",
                slug="edu-pilot",
                status=TenantStatus.ACTIVE,
                description="Asisten edukasi & bimbingan belajar digital."
            ),
            persona=TenantPersona(
                system_prompt="Kamu adalah EduBot, asisten belajar yang cerdas dan sabar.",
                tone="ramah, edukatif",
                language="id",
                default_fallback_message="Maaf, server edukasi sedang sibuk. Coba lagi sebentar.",
                welcome_message="Selamat datang di EduBot!"
            ),
            menu_config=TenantMenuConfig(
                main_menu_text="📚 Menu EduBot:\n1. Modul Matematika (Rp15.000)\n2. Bantuan Tutor (Admin)\nKetik nomor menu.",
                keywords={"menu": "MAIN_MENU", "batal": "RESET", "reset": "RESET", "start": "MAIN_MENU"},
                options=[
                    MenuItem(
                        id="1",
                        title="Modul Matematika",
                        description="Modul latihan soal & pembahasan.",
                        action="ORDER_QRIS",
                        price_amount=15000
                    ),
                    MenuItem(
                        id="2",
                        title="Bantuan Tutor",
                        description="Konsultasi langsung dengan tutor.",
                        action="ESCALATE"
                    )
                ],
                escalation_keywords=["admin", "tutor", "cs", "guru", "bantuan manusia"],
                escalation_message="Permintaan Anda diteruskan ke Tutor piket. Mohon tunggu sejenak."
            ),
            channel_config=TenantChannelConfig(
                whatsapp_phone_number_id="9988776655",
                webhook_verify_token="edu_secret_token_2026",
                credentials={}
            ),
            payment_config=TenantPaymentConfig(
                provider="DANA_DYNAMIC",
                static_qris_payload="00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI5204737253033605802ID5909BoonTrack6012Kab. Bandung61054028663048DC1",
                use_unique_code=True,
                unique_code_digits=3,
                min_amount=10000
            ),
            feature_flags=TenantFeatureFlags(
                enable_cv_ats=False,
                enable_document_analysis=False,
                enable_qris=True,
                enable_ai_completion=True
            )
        )

    def tearDown(self):
        TENANT_STATUS.clear()
        TENANT_STATUS.update(self._status_backup)

    def test_tenant_config_schema_validation(self):
        """Validasi kepatuhan schema Pydantic v2 terhadap data konfigurasi tenant."""
        # 1. Objek valid
        self.assertTrue(self.sample_valid_config.is_active())
        self.assertEqual(self.sample_valid_config.get_verify_token(), "edu_secret_token_2026")
        self.assertEqual(self.sample_valid_config.get_phone_number_id(), "9988776655")
        self.assertTrue(self.sample_valid_config.get_static_qris().startswith("00020101"))

        # 2. Objek invalid (field wajib tidak ada)
        with self.assertRaises(pydantic.ValidationError):
            TenantConfig.model_validate({"identity": {"tenant_id": "incomplete"}})

    def test_load_tenant_configs_with_fault_isolation(self):
        """Memverifikasi bahwa load_tenant_configs memuat file valid dan mengisolasi file corrupt tanpa crash."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # File 1: Valid JSON
            valid_path = os.path.join(tmp_dir, "pilot_valid.json")
            with open(valid_path, "w", encoding="utf-8") as f:
                json.dump(self.sample_valid_config.model_dump(), f)

            # File 2: Syntax Error / Broken JSON
            corrupted_path = os.path.join(tmp_dir, "broken_syntax.json")
            with open(corrupted_path, "w", encoding="utf-8") as f:
                f.write("{ invalid json content: [not closed")

            # File 3: Schema Validation Error
            invalid_schema_path = os.path.join(tmp_dir, "invalid_schema.json")
            with open(invalid_schema_path, "w", encoding="utf-8") as f:
                json.dump({"identity": {"tenant_id": "bad_tenant"}}, f)

            # Eksekusi pemuatan direktori
            loaded_configs = load_tenant_configs(config_dir=tmp_dir)

            # File valid berhasil dimuat
            self.assertIn("test_edu_pilot", loaded_configs)
            self.assertEqual(loaded_configs["test_edu_pilot"].identity.name, "Pilot Edu Assistant")

            # File corrupt tidak melempar uncaught exception, melainkan dicatat sebagai degraded
            self.assertIn("broken_syntax", TENANT_STATUS)
            self.assertEqual(TENANT_STATUS["broken_syntax"]["status"], "degraded")
            self.assertIn("invalid_schema", TENANT_STATUS)
            self.assertEqual(TENANT_STATUS["invalid_schema"]["status"], "degraded")

    async def test_generic_engine_navigation_reset(self):
        """Memverifikasi bahwa kata kunci navigasi 'menu', 'batal', 'reset' mereset state dan menampilkan main menu."""
        engine = GenericTenantEngine()
        user_ctx = {"state": "WAITING_PAYMENT", "pending_order": {"id": "123"}}

        # Trigger reset dengan 'menu'
        res = await engine.handle_message(
            tenant_config=self.sample_valid_config,
            incoming_message="menu",
            user_context=user_ctx,
            user_id="628111222333"
        )
        self.assertEqual(res["action"], "SEND_TEXT")
        self.assertIn("Menu EduBot:", res["text"])
        self.assertEqual(user_ctx["state"], "IDLE")
        self.assertIsNone(user_ctx["pending_order"])

        # Trigger reset dengan 'batal'
        res_batal = await engine.handle_message(
            tenant_config=self.sample_valid_config,
            incoming_message="batal",
            user_context=user_ctx,
            user_id="628111222333"
        )
        self.assertEqual(res_batal["action"], "SEND_TEXT")
        self.assertEqual(res_batal["state"], "IDLE")

    async def test_generic_engine_escalation_detection(self):
        """Memverifikasi bahwa pesan mengandung kata kunci eskalasi mengarahkan ke CS/Admin."""
        engine = GenericTenantEngine()
        user_ctx = {"state": "IDLE"}

        res = await engine.handle_message(
            tenant_config=self.sample_valid_config,
            incoming_message="Halo, saya ingin bicara dengan tutor piket admin",
            user_context=user_ctx,
            user_id="628111222333"
        )
        self.assertEqual(res["action"], "ESCALATE")
        self.assertEqual(res["state"], "ESCALATED")
        self.assertIn("Tutor piket", res["text"])

    async def test_generic_engine_qris_order_generation(self):
        """Memverifikasi bahwa pemilihan opsi menu berbayar menghasilkan dynamic QRIS EMVCo dan QuickChart URL."""
        engine = GenericTenantEngine()
        user_ctx = {}

        # User memilih menu '1' (Modul Matematika Rp15.000)
        res = await engine.handle_message(
            tenant_config=self.sample_valid_config,
            incoming_message="1",
            user_context=user_ctx,
            user_id="628111222333"
        )
        self.assertEqual(res["action"], "SEND_QRIS")
        self.assertEqual(res["state"], "WAITING_PAYMENT")
        self.assertIsNotNone(res["image_url"])
        self.assertTrue(res["image_url"].startswith("https://quickchart.io/qr?text="))
        self.assertTrue(res["qris_string"].startswith("000201010212"))
        
        # Nominal harus mencakup harga dasar (15.000) + 3-digit kode unik (100 - 999)
        self.assertGreaterEqual(res["amount"], 15100)
        self.assertLessEqual(res["amount"], 15999)
        formatted_expected = f"{res['amount']:,}".replace(",", ".")
        self.assertIn(formatted_expected, res["text"])

    async def test_generic_engine_ai_completion_and_fallback(self):
        """Memverifikasi bahwa pertanyaan bebas memanggil AI Gateway dengan persona system_prompt tenant."""
        mock_ai = AsyncMock()
        mock_ai.generate.return_value = "Ini jawaban materi Matematika dasar."

        engine = GenericTenantEngine(ai_service=mock_ai)
        res = await engine.handle_message(
            tenant_config=self.sample_valid_config,
            incoming_message="Jelaskan rumus phytagoras dong",
            user_context={},
            user_id="628111222333"
        )
        self.assertEqual(res["action"], "SEND_TEXT")
        self.assertEqual(res["text"], "Ini jawaban materi Matematika dasar.")
        
        # Pastikan system_prompt yang diteruskan ke AI sesuai dengan persona tenant
        mock_ai.generate.assert_called_once()
        _, kwargs = mock_ai.generate.call_args
        self.assertEqual(kwargs.get("system_prompt"), self.sample_valid_config.persona.system_prompt)

        # Uji fallback jika AI melempar error
        mock_ai.generate.side_effect = RuntimeError("OpenAI rate limit exceeded")
        res_fallback = await engine.handle_message(
            tenant_config=self.sample_valid_config,
            incoming_message="Pertanyaan lain",
            user_context={},
            user_id="628111222333"
        )
        self.assertEqual(res_fallback["action"], "SEND_TEXT")
        self.assertEqual(res_fallback["text"], self.sample_valid_config.persona.default_fallback_message)

    async def test_dynamic_webhook_routing_for_config_tenants(self):
        """Menguji registrasi dynamic webhook WhatsApp Meta API untuk tenant berbasis konfigurasi."""
        app = web.Application()
        mock_engine = GenericTenantEngine()
        
        # Daftarkan route untuk config tenant
        registered = register_config_driven_tenant_routes(app, self.sample_valid_config, engine=mock_engine)
        self.assertTrue(registered)

        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            # 1. Meta Webhook Verification GET: Token Cocok -> 200 OK
            resp_verify_ok = await client.get(
                "/webhook/test_edu_pilot/whatsapp?hub.mode=subscribe&hub.verify_token=edu_secret_token_2026&hub.challenge=EDU_OK"
            )
            self.assertEqual(resp_verify_ok.status, 200)
            self.assertEqual(await resp_verify_ok.text(), "EDU_OK")

            # 2. Meta Webhook Verification GET: Token Salah -> 403 Forbidden
            resp_verify_fail = await client.get(
                "/webhook/test_edu_pilot/whatsapp?hub.mode=subscribe&hub.verify_token=SALAH_TOKEN&hub.challenge=EDU_OK"
            )
            self.assertEqual(resp_verify_fail.status, 403)

            # 3. Meta Inbound Event POST: Pesan Masuk -> 200 OK
            incoming_payload = {
                "object": "whatsapp_business_account",
                "entry": [{
                    "changes": [{
                        "value": {
                            "messages": [{
                                "from": "6281234567890",
                                "id": "wamid.edu_test_1",
                                "timestamp": "1700000000",
                                "type": "text",
                                "text": {"body": "menu"}
                            }]
                        }
                    }]
                }]
            }
            with patch("app.core.tenant_loader.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
                resp_post = await client.post("/webhook/test_edu_pilot/whatsapp", json=incoming_payload)
                self.assertEqual(resp_post.status, 200)
                data = await resp_post.json()
                self.assertEqual(data.get("status"), "processed")
                mock_send_wa.assert_called_once()
                self.assertIn("Menu EduBot:", mock_send_wa.call_args[1].get("text"))

            # 4. Meta Inbound Event POST: Status Update (Delivered/Read) -> 200 OK
            status_payload = {
                "object": "whatsapp_business_account",
                "entry": [{
                    "changes": [{
                        "value": {
                            "statuses": [{"id": "wamid.123", "status": "delivered"}]
                        }
                    }]
                }]
            }
            resp_status = await client.post("/webhook/test_edu_pilot/whatsapp", json=status_payload)
            self.assertEqual(resp_status.status, 200)

        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
