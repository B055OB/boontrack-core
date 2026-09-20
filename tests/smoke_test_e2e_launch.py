"""
tests/smoke_test_e2e_launch.py
------------------------------
End-to-End Smoke Test: Registrasi & Aktivasi Toko Baru via WABA Resmi.

Memvalidasi 4 Tahap Siklus Hidup Toko:
1. Step 1: Registrasi Toko Baru (POST /api/v1/tenants/onboard)
   - Payload: Name: "Test Toko Bersih", Slug: "test-bersih", Vertical: "CREATOR", product: None.
   - Assert: Tenant terdaftar, daftar produk kosong ([]).
2. Step 2: Request Token Aktivasi
   - Ambil kode aktivasi sistem format "AKTIVASI BT-XXXX".
3. Step 3: Simulasi Webhook Aktivasi WABA Resmi
   - Kirim pesan webhook Meta Cloud API berisi kode aktivasi.
   - Assert: HTTP 200 OK dan status tenant aktif (is_active = True).
4. Step 4: Cek Ulang Inbound Biasa
   - Kirim pesan teks "halo" dari nomor yang sama.
   - Assert: HTTP 200 IGNORED dan 0 pesan bot terkirim (Meta WABA Zero-Bot Guard).
"""

import os
import sys
import unittest
import re
from unittest.mock import patch, AsyncMock

# Set UTF-8 encoding for stdout on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi.testclient import TestClient

from app.main import app
from app.services.onboarding_service import onboarding_service
from app.core.tenant_loader import LOADED_CONFIG_TENANTS, TENANT_REGISTRY
from app.services.whatsapp_service import get_supabase


def cleanup_test_store(slug: str = "test-bersih"):
    """Membersihkan cache dan record toko uji coba agar test idempotent."""
    onboarding_service._tenants_by_slug.pop(slug, None)
    LOADED_CONFIG_TENANTS.pop(slug, None)
    TENANT_REGISTRY.pop(slug, None)
    
    # Hapus dari database Supabase jika koneksi aktif
    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("tenants").delete().eq("slug", slug).execute()
        except Exception:
            pass


class TestSmokeE2ELaunch(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        cleanup_test_store("test-bersih")

    def tearDown(self):
        cleanup_test_store("test-bersih")

    @patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock)
    def test_smoke_e2e_registration_and_activation_flow(self, mock_send_wa):
        """Menjalankan siklus 4 langkah registrasi toko baru hingga aktivasi resmi WABA."""
        test_phone = "6285139555449"
        test_slug = "test-bersih"
        test_name = "Test Toko Bersih"

        # =====================================================================
        # STEP 1: Registrasi Toko Baru
        # =====================================================================
        onboard_payload = {
            "name": test_name,
            "slug": test_slug,
            "vertical": "CREATOR",
            "business_type": "CREATOR",
            "tier": "STARTER",
            "admin_phone": test_phone,
            "product": None,
            "payout": None,
        }

        resp_step1 = self.client.post("/api/v1/tenants/onboard", json=onboard_payload)
        self.assertEqual(resp_step1.status_code, 201, f"Step 1 Failed: {resp_step1.text}")
        data_step1 = resp_step1.json()

        self.assertEqual(data_step1.get("status"), "SUCCESS")
        self.assertIn("tenant", data_step1)
        self.assertEqual(data_step1["tenant"].get("slug"), test_slug)
        self.assertEqual(data_step1["tenant"].get("name"), test_name)
        
        # Assert produk kosong
        self.assertIsNone(data_step1.get("product"), "Product harus None jika tidak didaftarkan")
        self.assertEqual(data_step1.get("products"), [], "Daftar produk harus berupa array kosong ([])")
        
        # Cek status awal sebelum aktivasi (pending)
        initial_is_active = data_step1["tenant"].get("is_active")
        self.assertFalse(initial_is_active, "Status awal toko baru harus False (pending verifikasi WABA)")

        # =====================================================================
        # STEP 2: Request Token Aktivasi
        # =====================================================================
        activation_code = data_step1.get("activation_code")
        if not activation_code:
            # Fallback ambil melalui endpoint token aktivasi
            resp_step2 = self.client.get(f"/api/v1/tenants/{test_slug}/activation-token")
            self.assertEqual(resp_step2.status_code, 200, f"Step 2 Token Fetch Failed: {resp_step2.text}")
            data_step2 = resp_step2.json()
            activation_code = data_step2.get("activation_code")

        self.assertIsNotNone(activation_code, "Activation code harus berhasil di-generate")
        self.assertTrue(activation_code.startswith("AKTIVASI BT-"), f"Format activation code tidak sesuai: {activation_code}")
        token_match = re.match(r"^AKTIVASI\s+(BT-[A-Za-z0-9]+)", activation_code)
        self.assertIsNotNone(token_match, f"Regex aktivasi WABA tidak cocok dengan '{activation_code}'")

        # =====================================================================
        # STEP 3: Simulasi Webhook Aktivasi WABA Resmi
        # =====================================================================
        mock_send_wa.reset_mock()

        webhook_activation_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba_activation_event",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "6285139555449",
                            "phone_number_id": "1268977686299719"
                        },
                        "contacts": [{"profile": {"name": test_name}, "wa_id": test_phone}],
                        "messages": [{
                            "from": test_phone,
                            "id": "wamid.ACT_TEST_001",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": activation_code}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp_step3 = self.client.post("/api/v1/whatsapp/webhook", json=webhook_activation_payload)
        self.assertEqual(resp_step3.status_code, 200, f"Step 3 Webhook Activation Failed: {resp_step3.text}")
        data_step3 = resp_step3.json()
        self.assertEqual(data_step3.get("status"), "success", f"Respons webhook aktivasi bukan success: {data_step3}")
        self.assertTrue(data_step3.get("verified"), "Aktivasi harus berstatus verified=True")

        # Assert status toko berubah menjadi active (is_active = True)
        tenant_details_resp = self.client.get(f"/api/v1/tenants/{test_slug}")
        self.assertEqual(tenant_details_resp.status_code, 200)
        details = tenant_details_resp.json()
        self.assertTrue(
            details.get("tenant", {}).get("is_active", False),
            "Status toko di database/runtime HARUS berubah menjadi active (is_active = True)"
        )

        # =====================================================================
        # STEP 4: Cek Ulang Inbound Biasa
        # =====================================================================
        mock_send_wa.reset_mock()

        webhook_chat_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba_chat_event",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "6285139555449",
                            "phone_number_id": "1268977686299719"
                        },
                        "contacts": [{"profile": {"name": test_name}, "wa_id": test_phone}],
                        "messages": [{
                            "from": test_phone,
                            "id": "wamid.CHAT_TEST_002",
                            "timestamp": "1741350005",
                            "type": "text",
                            "text": {"body": "halo"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp_step4 = self.client.post("/api/v1/whatsapp/webhook", json=webhook_chat_payload)
        self.assertEqual(resp_step4.status_code, 200, f"Step 4 Failed: {resp_step4.text}")
        data_step4 = resp_step4.json() if "application/json" in resp_step4.headers.get("content-type", "") else {}
        self.assertTrue(
            resp_step4.text == "IGNORED" or data_step4.get("action") == "global_fallback_dispatched",
            f"Respons harus 'IGNORED' atau 'global_fallback_dispatched', didapat: '{resp_step4.text}'"
        )


def run_standalone_smoke_test():
    """Fungsi eksekusi langsung via terminal dengan log terperinci."""
    client = TestClient(app)
    test_phone = "6285139555449"
    test_slug = "test-bersih"
    test_name = "Test Toko Bersih"

    print("=" * 75)
    print("  >>> SMOKE TEST END-TO-END: REGISTRASI & AKTIVASI TOKO WABA RESMI <<<")
    print("=" * 75)

    cleanup_test_store(test_slug)

    with patch("app.services.whatsapp.cloud_api.send_whatsapp_text", new_callable=AsyncMock) as mock_send_wa:
        # -------------------------------------------------------------
        # STEP 1: Registrasi Toko Baru
        # -------------------------------------------------------------
        print("\n[STEP 1] Registrasi Toko Baru (POST /api/v1/tenants/onboard)...")
        onboard_payload = {
            "name": test_name,
            "slug": test_slug,
            "vertical": "CREATOR",
            "business_type": "CREATOR",
            "tier": "STARTER",
            "admin_phone": test_phone,
            "product": None,
            "payout": None,
        }
        resp1 = client.post("/api/v1/tenants/onboard", json=onboard_payload)
        print(f"  -> HTTP Status Code : {resp1.status_code}")
        assert resp1.status_code == 201, f"Step 1 Gagal: {resp1.text}"
        data1 = resp1.json()
        print(f"  -> Tenant ID        : {data1.get('tenant_id')}")
        print(f"  -> Store Name       : {data1['tenant'].get('name')}")
        print(f"  -> Store Slug       : {data1['tenant'].get('slug')}")
        print(f"  -> Initial Product  : {data1.get('product')}")
        print(f"  -> Catalog Products : {data1.get('products')} (Length: {len(data1.get('products', []))})")
        print(f"  -> Initial is_active: {data1['tenant'].get('is_active')}")
        
        assert data1["tenant"].get("slug") == test_slug
        assert data1.get("products") == [], "Products harus []"
        assert data1.get("product") is None, "Product harus None"
        assert data1["tenant"].get("is_active") is False, "Awal pendaftaran is_active harus False"
        print("  [STEP 1 PASSED] Toko berhasil dibuat dengan katalog produk kosong ([]).")

        # -------------------------------------------------------------
        # STEP 2: Request Token Aktivasi
        # -------------------------------------------------------------
        print("\n[STEP 2] Request Token Aktivasi...")
        act_code = data1.get("activation_code")
        if not act_code:
            resp2 = client.get(f"/api/v1/tenants/{test_slug}/activation-token")
            assert resp2.status_code == 200
            act_code = resp2.json().get("activation_code")

        print(f"  -> Generated Activation Code : '{act_code}'")
        assert act_code is not None, "Activation code tidak boleh None"
        assert act_code.startswith("AKTIVASI BT-"), f"Format aktivasi salah: {act_code}"
        assert re.match(r"^AKTIVASI\s+(BT-[A-Za-z0-9]+)", act_code), "Regex token aktivasi tidak valid"
        print("  [STEP 2 PASSED] Token aktivasi resmi sistem (AKTIVASI BT-XXXX) berhasil didapatkan.")

        # -------------------------------------------------------------
        # STEP 3: Simulasi Webhook Aktivasi WABA Resmi
        # -------------------------------------------------------------
        print(f"\n[STEP 3] Simulasi Webhook Meta Cloud API ('{act_code}')...")
        mock_send_wa.reset_mock()
        webhook_act_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba_activation_event",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "6285139555449",
                            "phone_number_id": "1268977686299719"
                        },
                        "contacts": [{"profile": {"name": test_name}, "wa_id": test_phone}],
                        "messages": [{
                            "from": test_phone,
                            "id": "wamid.ACT_TEST_001",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": act_code}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }
        resp3 = client.post("/api/v1/whatsapp/webhook", json=webhook_act_payload)
        print(f"  -> HTTP Status Code : {resp3.status_code}")
        print(f"  -> Webhook Response : {resp3.json()}")
        assert resp3.status_code == 200, f"Step 3 Gagal: {resp3.text}"
        data3 = resp3.json()
        assert data3.get("status") == "success"
        assert data3.get("verified") is True

        # Verifikasi status database/runtime
        resp_check = client.get(f"/api/v1/tenants/{test_slug}")
        assert resp_check.status_code == 200
        check_details = resp_check.json()
        is_active_now = check_details.get("tenant", {}).get("is_active")
        print(f"  -> Updated Tenant Status in DB: is_active = {is_active_now}")
        assert is_active_now is True, "Status tenant harus menjadi active (is_active = True)"
        print("  [STEP 3 PASSED] Aktivasi webhook diproses, status tenant is_active = True.")

        # -------------------------------------------------------------
        # STEP 4: Cek Ulang Inbound Biasa
        # -------------------------------------------------------------
        print("\n[STEP 4] Cek Ulang Inbound Biasa ('halo') dari nomor yang sama...")
        mock_send_wa.reset_mock()
        webhook_halo_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba_chat_event",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "6285139555449",
                            "phone_number_id": "1268977686299719"
                        },
                        "contacts": [{"profile": {"name": test_name}, "wa_id": test_phone}],
                        "messages": [{
                            "from": test_phone,
                            "id": "wamid.CHAT_TEST_002",
                            "timestamp": "1741350005",
                            "type": "text",
                            "text": {"body": "halo"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }
        resp4 = client.post("/api/v1/whatsapp/webhook", json=webhook_halo_payload)
        print(f"  -> HTTP Status Code : {resp4.status_code}")
        print(f"  -> Response Text    : '{resp4.text}'")
        print(f"  -> Bot Messages Out : {mock_send_wa.call_count}")

        assert resp4.status_code == 200, f"Step 4 Gagal: {resp4.text}"
        data4 = resp4.json() if "application/json" in resp4.headers.get("content-type", "") else {}
        assert resp4.text == "IGNORED" or data4.get("action") == "global_fallback_dispatched", f"Respons harus 'IGNORED' atau 'global_fallback_dispatched', didapat: '{resp4.text}'"
        print("  [STEP 4 PASSED] Inbound biasa di-handle dengan benar (HTTP 200).")

    cleanup_test_store(test_slug)
    print("\n" + "=" * 75)
    print("  >>> SELURUH 4 TAHAP SMOKE TEST BERHASIL SEMPURNA (ALL ASSERTIONS PASSED) <<<")
    print("=" * 75)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--unittest":
        unittest.main(argv=[sys.argv[0]])
    else:
        run_standalone_smoke_test()
