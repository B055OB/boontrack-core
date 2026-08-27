import sys
import types
import unittest
from unittest.mock import patch, AsyncMock
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

from app.core.tenant_loader import (
    load_dynamic_tenants,
    get_tenant_statuses,
    get_tenant_details,
    sanitize_error_summary,
    TENANT_REGISTRY,
    TENANT_STATUS,
)
from app.api.endpoints import register_api_routes
from app.tenants.career.config import VERIFY_TOKEN as CAREER_VERIFY_TOKEN


class TestReliabilityAndTenantIsolation(unittest.IsolatedAsyncioTestCase):
    """Sprint A: Tenant Error Isolation, Safe Dynamic Loader, and Webhook Fault Tolerance Tests."""

    def setUp(self):
        self._status_backup = dict(TENANT_STATUS)

    def tearDown(self):
        TENANT_STATUS.clear()
        TENANT_STATUS.update(self._status_backup)

    async def test_dod_simulation_dummy_tenant_startup_crash_isolation(self):
        """DoD Simulation:
        1. Simulasikan skenario di mana 1 tenant dummy gagal inisialisasi / error saat startup (ImportError / RuntimeError).
        2. Pastikan boontrack-core tetap berjalan normal (Graceful Degradation, Zero Cascade Failure).
        3. Tenant lain (Om Budi, BoonTrack Career, Holding/Commerce) tetap melayani traffic secara normal.
        4. Webhook Meta WhatsApp API tetap merespons 200 OK.
        """
        app = web.Application()
        register_api_routes(app)

        # Buat dummy mock module yang sengaja error saat registrasi
        broken_mod = types.ModuleType("app.tenants.broken_dummy_tenant")
        def broken_register(app_instance):
            raise RuntimeError("Database connection timed out during tenant initialization in C:\\internal\\secret\\path.py")
        broken_mod.register_broken_routes = broken_register
        sys.modules["app.tenants.broken_dummy_tenant"] = broken_mod

        # Skenario registry: tenant nyata + 2 dummy tenant bermasalah
        test_registry = {
            "career": {
                "name": "BoonTrack Career",
                "module": "app.tenants.career.router",
                "register_func": "register_career_routes",
                "enabled": True,
            },
            "om_budi": {
                "name": "Om Budi Bot",
                "module": "app.tenants.om_budi.router",
                "register_func": "register_om_budi_routes",
                "enabled": True,
            },
            "holding": {
                "name": "Holding Commerce",
                "module": "app.modules.commerce.router",
                "routes_attr": "commerce_routes",
                "enabled": True,
            },
            "dummy_missing_module_tenant": {
                "name": "Dummy Missing Module Tenant",
                "module": "app.tenants.non_existent_dummy_tenant_xyz",
                "register_func": "register_dummy_routes",
                "enabled": True,
            },
            "dummy_startup_crash_tenant": {
                "name": "Dummy Startup Crash Tenant",
                "module": "app.tenants.broken_dummy_tenant",
                "register_func": "register_broken_routes",
                "enabled": True,
            }
        }

        # 1. Pastikan load_dynamic_tenants berhasil tanpa melempar fatal exception
        try:
            statuses = load_dynamic_tenants(app, registry=test_registry)
        except Exception as e:
            self.fail(f"load_dynamic_tenants threw an uncaught exception: {e}")

        # Verifikasi status isolasi
        self.assertEqual(statuses["career"], "active")
        self.assertEqual(statuses["om_budi"], "active")
        self.assertEqual(statuses["holding"], "active")
        self.assertEqual(statuses["dummy_missing_module_tenant"], "degraded")
        self.assertEqual(statuses["dummy_startup_crash_tenant"], "degraded")

        # 2. Boot server dengan test client
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            # 3. Verifikasi GET /api/v1/system/tenants
            resp_tenants = await client.get("/api/v1/system/tenants")
            self.assertEqual(resp_tenants.status, 200)
            tenants_payload = await resp_tenants.json()

            self.assertEqual(tenants_payload.get("status"), "degraded")
            self.assertEqual(tenants_payload.get("active"), 3)
            self.assertEqual(tenants_payload.get("degraded"), 2)

            tenants_data = tenants_payload.get("tenants", {})
            self.assertEqual(tenants_data["om_budi"]["health"], "healthy")
            self.assertEqual(tenants_data["career"]["health"], "healthy")
            self.assertEqual(tenants_data["holding"]["health"], "healthy")
            self.assertEqual(tenants_data["dummy_missing_module_tenant"]["health"], "degraded")
            self.assertEqual(tenants_data["dummy_startup_crash_tenant"]["health"], "degraded")

            # Verifikasi tidak ada kebocoran stack trace atau full internal path ke publik
            for t_key, t_info in tenants_data.items():
                err_msg = t_info.get("error")
                if err_msg:
                    self.assertNotIn("Traceback (most recent call last)", err_msg)
                    self.assertNotIn("C:\\internal\\secret\\path.py", err_msg)

            # 4. Verifikasi Tenant Om Budi tetap melayani traffic webhook normal (200 OK)
            resp_om_budi = await client.get(
                "/webhook/om_budi/whatsapp?hub.mode=subscribe&hub.verify_token=om_budi_secure_token_2026&hub.challenge=OM_BUDI_ALIVE"
            )
            self.assertEqual(resp_om_budi.status, 200)
            self.assertEqual(await resp_om_budi.text(), "OM_BUDI_ALIVE")

            # 5. Verifikasi Tenant Career tetap melayani traffic webhook normal (200 OK)
            resp_career = await client.get(
                f"/webhook/boontrack-career/whatsapp?hub.mode=subscribe&hub.verify_token={CAREER_VERIFY_TOKEN}&hub.challenge=CAREER_ALIVE"
            )
            self.assertEqual(resp_career.status, 200)
            self.assertEqual(await resp_career.text(), "CAREER_ALIVE")

            # 6. Verifikasi Tenant Holding/Commerce tetap melayani traffic (200 OK)
            resp_holding = await client.get("/api/v1/commerce/digicorn/search?q=ebook")
            self.assertEqual(resp_holding.status, 200)
            holding_data = await resp_holding.json()
            self.assertEqual(holding_data.get("status"), "success")
            self.assertEqual(holding_data.get("tenant_id"), "digicorn")

            # 7. Verifikasi Webhook Meta API POST ke Career mengembalikan 200 OK
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
            resp_wa_status = await client.post("/webhook/boontrack-career/whatsapp", json=status_payload)
            self.assertEqual(resp_wa_status.status, 200)

        finally:
            await client.close()
            sys.modules.pop("app.tenants.broken_dummy_tenant", None)

    async def test_tenant_health_check_endpoint_public_safety(self):
        """Memverifikasi bahwa GET /api/v1/system/tenants mengembalikan status kesehatan detail
        (healthy, degraded, atau down) dan log error terisolasi tanpa membocorkan stack trace.
        """
        raw_error_with_traceback = (
            "Traceback (most recent call last):\n"
            '  File "C:\\Users\\Alldy\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\foo.py", line 12, in <module>\n'
            "    import secret_dependency\n"
            "ModuleNotFoundError: No module named 'secret_dependency'"
        )

        sanitized = sanitize_error_summary(raw_error_with_traceback)
        self.assertNotIn("Traceback", sanitized)
        self.assertNotIn("C:\\Users\\Alldy", sanitized)
        self.assertIn("ModuleNotFoundError: No module named 'secret_dependency'", sanitized)

    async def test_meta_webhook_runtime_error_isolation_returns_200(self):
        """Memverifikasi bahwa error tak terduga saat runtime memproses webhook WhatsApp
        TIDAK melempar uncaught 500 fatal ke server utama, melainkan terisolasi dan tetap mengembalikan HTTP 200 OK.
        """
        from app.core.server import create_web_app

        app = create_web_app()
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            # Simulasi payload pesan WhatsApp masuk ke Career Assistant
            incoming_message_payload = {
                "object": "whatsapp_business_account",
                "entry": [{
                    "changes": [{
                        "value": {
                            "messages": [{
                                "from": "628999888777",
                                "id": "wamid.simulated_crash_1",
                                "timestamp": "1700000000",
                                "type": "text",
                                "text": {"body": "halo crash"}
                            }],
                            "contacts": [{"wa_id": "628999888777", "profile": {"name": "Tester"}}]
                        }
                    }]
                }]
            }

            # Mock career_service.handle_text_or_button agar melempar unexpected Exception
            with patch("app.tenants.career.service.career_service.handle_text_or_button", side_effect=RuntimeError("AI Engine unexpected failure")):
                resp = await client.post("/webhook/boontrack-career/whatsapp", json=incoming_message_payload)
                # Harus berstatus HTTP 200 agar Meta API tidak retrying / disable webhook
                self.assertEqual(resp.status, 200)
                text = await resp.text()
                self.assertEqual(text, "EVENT_ERROR_ISOLATED")

            # Simulasi error tak terduga pada webhook Om Budi
            with patch("app.tenants.om_budi.service.om_budi_service.handle_incoming_message", side_effect=Exception("Database lock error")):
                resp_om_budi = await client.post("/webhook/om_budi/whatsapp", json=incoming_message_payload)
                # Harus berstatus HTTP 200 dengan status error_isolated
                self.assertEqual(resp_om_budi.status, 200)
                json_res = await resp_om_budi.json()
                self.assertEqual(json_res.get("status"), "error_isolated")

        finally:
            await client.close()

    def test_strict_code_freeze_qris_and_payment_verification_service(self):
        """Memvalidasi Strict Code Freeze pada modul app/services/payment_verification_service.py."""
        import os
        payment_service_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "services", "payment_verification_service.py"
        )
        self.assertTrue(os.path.exists(payment_service_path), "File payment_verification_service.py wajib ada.")

        from app.services.payment_verification_service import PaymentVerificationService, payment_verification_service
        self.assertIsNotNone(payment_verification_service)
        self.assertTrue(hasattr(payment_verification_service, "verify_payment_params"))
        self.assertTrue(hasattr(payment_verification_service, "verify_receipt_ocr_data"))
        self.assertTrue(hasattr(payment_verification_service, "is_valid_receiver"))


if __name__ == "__main__":
    unittest.main()
