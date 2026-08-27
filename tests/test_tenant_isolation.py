import unittest
from app.core.security.encryption import encrypt_pii, decrypt_pii, generate_blind_index
from app.core.security.masking import mask_pii_string


class TestTenantIsolationAndPII(unittest.TestCase):

    def test_encryption_and_blind_index(self):
        tenant_a = "diskominfo-bdg"
        tenant_b = "om_budi"
        raw_nik = "1268977686299719"

        # 1. Enkripsi per-tenant harus menghasilkan ciphertext berbeda
        enc_a = encrypt_pii(tenant_a, raw_nik)
        enc_b = encrypt_pii(tenant_b, raw_nik)
        self.assertNotEqual(enc_a, enc_b, "Ciphertext antar-tenant tidak boleh sama.")

        # 2. Dekripsi berhasil mengembalikan NIK asli
        dec_a = decrypt_pii(tenant_a, enc_a)
        self.assertEqual(dec_a, raw_nik)

        # 3. Blind index HMAC hash konsisten untuk lookup
        hash_1 = generate_blind_index(raw_nik)
        hash_2 = generate_blind_index(raw_nik)
        self.assertEqual(hash_1, hash_2)

    def test_zero_pii_masking(self):
        raw_nik = "3273012345670001"
        sample_log = f"Aduan warga dengan NIK {raw_nik} berhasil diverifikasi."

        masked = mask_pii_string(sample_log)
        self.assertNotIn(raw_nik, masked, "Ditemukan kebocoran plaintext NIK!")
        self.assertIn("3273**********01", masked)


class TestDynamicTenantLoaderAndIsolation(unittest.IsolatedAsyncioTestCase):
    """Pengujian Unit untuk Arsitektur Isolasi Tenant Penuh & Safe Dynamic Loader."""

    def setUp(self):
        from app.core.tenant_loader import TENANT_STATUS
        self._status_backup = dict(TENANT_STATUS)

    def tearDown(self):
        from app.core.tenant_loader import TENANT_STATUS
        TENANT_STATUS.clear()
        TENANT_STATUS.update(self._status_backup)

    async def test_dynamic_loader_status_reporting(self):
        """Verifikasi bahwa seluruh tenant utama dimuat secara dinamis dan dilaporkan pada /health serta /api/v1/system/tenants."""
        from app.core.server import create_web_app
        from app.core.tenant_loader import get_tenant_statuses, get_tenant_details
        from aiohttp.test_utils import TestServer, TestClient

        app = create_web_app()
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            # 1. Test GET /health returns tenant status summary
            resp = await client.get("/health")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data.get("status"), "healthy")
            self.assertIn("tenants", data)
            self.assertIn("career", data["tenants"])
            self.assertIn("om_budi", data["tenants"])
            self.assertEqual(data["tenants"]["career"], "active")
            self.assertEqual(data["tenants"]["om_budi"], "active")

            # 2. Test GET /api/v1/system/tenants returns detailed reporting
            resp_sys = await client.get("/api/v1/system/tenants")
            self.assertEqual(resp_sys.status, 200)
            sys_data = await resp_sys.json()
            self.assertIn(sys_data.get("status"), ("ok", "degraded"))
            self.assertIn("career", sys_data["tenants"])
            self.assertEqual(sys_data["tenants"]["career"]["status"], "active")
            self.assertIsNone(sys_data["tenants"]["career"]["error"])
        finally:
            await client.close()

    async def test_broken_tenant_does_not_crash_server_and_isolates_error(self):
        """Simulasikan tenant rusak (ImportError & runtime exception) dan buktikan:
        1. Server TIDAK PERNAH crash saat startup (Zero Cascade Failure).
        2. Tenant rusak ditandai DEGRADED beserta rincian error-nya.
        3. Tenant yang sehat tetap aktif dan melayani HTTP 200 OK.
        """
        from aiohttp import web
        from aiohttp.test_utils import TestServer, TestClient
        from app.core.tenant_loader import load_dynamic_tenants, TENANT_STATUS

        mock_test_routes = web.RouteTableDef()

        @mock_test_routes.get("/api/v1/healthy-mock/test")
        async def healthy_handler(request):
            return web.json_response({"status": "mock_healthy_ok"}, status=200)

        # Buat modul mock runtime untuk registrasi router
        import types
        healthy_mod = types.ModuleType("mock_healthy_module")
        def register_healthy(app):
            app.add_routes(mock_test_routes)
        healthy_mod.register_healthy = register_healthy
        import sys
        sys.modules["mock_healthy_module"] = healthy_mod

        # Registry simulasi dengan: 1 healthy, 1 missing module (ImportError), 1 error function
        faulty_registry = {
            "healthy_tenant": {
                "name": "Healthy Mock Tenant",
                "module": "mock_healthy_module",
                "register_func": "register_healthy",
                "enabled": True,
            },
            "broken_import_tenant": {
                "name": "Crashing Import Tenant",
                "module": "app.tenants.non_existent_crash_tenant",
                "register_func": "register_crash",
                "enabled": True,
            },
            "broken_registration_tenant": {
                "name": "Crashing Registration Tenant",
                "module": "mock_healthy_module",
                "register_func": "non_existent_register_func",
                "enabled": True,
            }
        }

        test_app = web.Application()

        # Eksekusi dynamic loader dengan faulty registry
        # Wajib SUKSES tanpa melempar uncaught exception ke caller
        statuses = load_dynamic_tenants(test_app, registry=faulty_registry)

        self.assertEqual(statuses["healthy_tenant"], "active")
        self.assertEqual(statuses["broken_import_tenant"], "degraded")
        self.assertEqual(statuses["broken_registration_tenant"], "degraded")

        self.assertEqual(TENANT_STATUS["healthy_tenant"]["status"], "active")
        self.assertEqual(TENANT_STATUS["broken_import_tenant"]["status"], "degraded")
        self.assertIn("No module named", TENANT_STATUS["broken_import_tenant"]["error"])
        self.assertEqual(TENANT_STATUS["broken_registration_tenant"]["status"], "degraded")

        # Buktikan bahwa app tetap dapat berjalan di web server dan melayani tenant sehat
        server = TestServer(test_app)
        client = TestClient(server)
        await client.start_server()

        try:
            resp = await client.get("/api/v1/healthy-mock/test")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data.get("status"), "mock_healthy_ok")
        finally:
            await client.close()
            # Cleanup sys.modules
            sys.modules.pop("mock_healthy_module", None)


if __name__ == "__main__":
    unittest.main()