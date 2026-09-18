"""
tests/test_webhook_hardening_and_isolation.py
---------------------------------------------
Comprehensive test suite verifying the 8 scenarios of the CTO Acceptance Matrix:
a. AKTIVASI BT-7170 via Platform WABA -> Enters Activation Handler & early return 200.
b. AKTIVASI BT-7170 via Tenant WABA -> Rejected as platform activation.
c. 'halo' via Platform WABA -> Displays platform menu (GLOBAL_FALLBACK_PLATFORM).
d. 'halo' via Tenant WABA -> Displays tenant conversation menu (GLOBAL_FALLBACK_TENANT).
e. Product inquiry via Tenant WABA -> Enters Catalog / CS routing.
f. Platform payment notification -> Enters Transactional Handler.
g. Unknown session / text -> Yields GLOBAL_FALLBACK (not silent).
h. Tenant A vs Tenant B isolation test (no cross-routing/leakage).
"""

import pytest
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.whatsapp.traffic_splitter import (
    TrafficSplitter,
    PlatformWebhookRouter,
    TenantWebhookRouter,
    PLATFORM_PHONE_NUMBER_ID,
    GLOBAL_FALLBACK_PLATFORM,
)
from app.services.tenant_context_resolver import TenantRuntimeContext


class TestWebhookHardeningAndIsolation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.platform_phone_id = str(PLATFORM_PHONE_NUMBER_ID) or "1268977686299719"
        self.tenant_a_phone_id = "888111222333"
        self.tenant_b_phone_id = "999444555666"

    # =========================================================================
    # a. AKTIVASI BT-7170 via Platform WABA -> Masuk Activation Handler & early return 200
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.services.onboarding_service.onboarding_service.get_tenant_details_by_slug")
    def test_scenario_a_activation_via_platform_waba(self, mock_details, mock_send_wa):
        mock_send_wa.return_value = True
        
        # Mocking tenant registration session
        from app.services.onboarding_service import onboarding_service
        onboarding_service._tenants_by_slug["test-store-7170"] = {
            "id": "t-7170-id",
            "slug": "test-store-7170",
            "name": "Toko Test 7170",
            "status": "pending_wa_verification",
            "is_active": False,
            "created_at": "2026-09-18T10:00:00+00:00",
            "metadata": {
                "wa_verification_token": "BT-7170",
                "phone": "6281234567170",
                "is_verified": False,
            }
        }

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.platform_phone_id,
                            "display_phone_number": "6285179555449"
                        },
                        "contacts": [{"profile": {"name": "Owner Toko"}, "wa_id": "6281234567170"}],
                        "messages": [{
                            "from": "6281234567170",
                            "id": "wamid.ACT7170",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "AKTIVASI BT-7170"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("action"), "store_activation")
        self.assertEqual(data.get("verified"), True)
        self.assertEqual(data.get("token"), "BT-7170")
        self.assertIn("berhasil diverifikasi", data.get("reply", ""))
        self.assertIn("Silakan lanjutkan pengaturan toko Anda di browser", data.get("reply", ""))
        
        # Verify dispatch sent confirmation message
        mock_send_wa.assert_called()

    # =========================================================================
    # b. AKTIVASI BT-7170 via Tenant WABA -> Ditolak / bukan aktivasi platform
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock)
    def test_scenario_b_activation_on_tenant_waba_rejected(self, mock_resolve_tenant, mock_send_wa):
        mock_send_wa.return_value = True
        mock_resolve_tenant.return_value = TenantRuntimeContext(
            tenant_id="tenant-alpha",
            slug="tenant-alpha",
            business_type="PHYSICAL",
            capabilities={"catalog": True, "order": True},
            metadata={"name": "Toko Alpha"}
        )

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "tenant_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.tenant_a_phone_id,
                            "display_phone_number": "628111222333"
                        },
                        "contacts": [{"profile": {"name": "User"}, "wa_id": "6281234567170"}],
                        "messages": [{
                            "from": "6281234567170",
                            "id": "wamid.REJ7170",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "AKTIVASI BT-7170"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data.get("status"), "rejected")
        self.assertEqual(data.get("purpose"), "TENANT_SALES")
        self.assertEqual(data.get("reason"), "PLATFORM_ACTIVATION_NOT_ALLOWED_ON_TENANT_WABA")
        self.assertIn("hanya dapat diverifikasi melalui nomor resmi platform", data.get("reply", ""))

    # =========================================================================
    # c. 'halo' via Platform WABA -> Menampilkan menu platform (GLOBAL_FALLBACK_PLATFORM)
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    def test_scenario_c_halo_via_platform_waba(self, mock_send_wa):
        mock_send_wa.return_value = True

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.platform_phone_id,
                            "display_phone_number": "6285179555449"
                        },
                        "contacts": [{"profile": {"name": "Calon Merchant"}, "wa_id": "6281999888777"}],
                        "messages": [{
                            "from": "6281999888777",
                            "id": "wamid.HALO_PLATFORM",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "halo"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("purpose"), "PLATFORM_TRANSACTIONAL")
        self.assertEqual(data.get("action"), "global_fallback_dispatched")
        self.assertIn("Aktivasi Toko", data.get("reply", ""))
        self.assertIn("shop.boontrack.com", data.get("reply", ""))

    # =========================================================================
    # d. 'halo' via Tenant WABA -> Menampilkan menu tenant conversation
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock)
    def test_scenario_d_halo_via_tenant_waba(self, mock_resolve_tenant, mock_send_wa):
        mock_send_wa.return_value = True
        mock_resolve_tenant.return_value = TenantRuntimeContext(
            tenant_id="tenant-alpha",
            slug="tenant-alpha",
            business_type="PHYSICAL",
            capabilities={"catalog": True, "order": True},
            metadata={"name": "Batik Cantik Alpha"}
        )

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "tenant_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.tenant_a_phone_id,
                            "display_phone_number": "628111222333"
                        },
                        "contacts": [{"profile": {"name": "Pelanggan"}, "wa_id": "628122334455"}],
                        "messages": [{
                            "from": "628122334455",
                            "id": "wamid.HALO_TENANT",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "halo"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("purpose"), "TENANT_SALES")
        self.assertEqual(data.get("tenant"), "tenant-alpha")
        self.assertIn("Batik Cantik Alpha", data.get("reply", ""))
        self.assertIn("shop.boontrack.com/tenant-alpha", data.get("reply", ""))

    # =========================================================================
    # e. Pertanyaan produk via Tenant WABA -> Masuk Catalog / CS
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.services.ai_engine.commerce_ai_engine.generate_commerce_response", new_callable=AsyncMock)
    @patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock)
    def test_scenario_e_product_inquiry_via_tenant_waba(self, mock_resolve_tenant, mock_ai, mock_send_wa):
        mock_send_wa.return_value = True
        mock_ai.return_value = "Kami memiliki Kemeja Batik Sutra seharga Rp250.000. Mau dibungkus Kak?"
        mock_resolve_tenant.return_value = TenantRuntimeContext(
            tenant_id="tenant-alpha",
            slug="tenant-alpha",
            business_type="PHYSICAL",
            capabilities={"catalog": True, "order": True},
            metadata={"name": "Batik Cantik Alpha"}
        )

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "tenant_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.tenant_a_phone_id,
                            "display_phone_number": "628111222333"
                        },
                        "contacts": [{"profile": {"name": "Pelanggan"}, "wa_id": "628122334455"}],
                        "messages": [{
                            "from": "628122334455",
                            "id": "wamid.PROD_INQUIRY",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "Ada promo harga batik sutra hari ini?"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("purpose"), "TENANT_SALES")
        mock_ai.assert_called_once()
        self.assertIn("Kemeja Batik Sutra", data.get("reply", ""))

    # =========================================================================
    # f. Notifikasi pembayaran platform -> Masuk Transactional Handler
    # =========================================================================
    def test_scenario_f_platform_payment_notification(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.platform_phone_id,
                            "display_phone_number": "6285179555449"
                        },
                        "contacts": [{"profile": {"name": "Payment Gateway"}, "wa_id": "6281999888000"}],
                        "messages": [{
                            "from": "6281999888000",
                            "id": "wamid.PAYMENT_ALERT",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "Pembayaran Berhasil untuk invoice #INV-2026-09-01 via Xendit Settlement"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("purpose"), "PLATFORM_TRANSACTIONAL")
        self.assertEqual(data.get("action"), "transactional_notification_logged")

    # =========================================================================
    # g. Unknown session / text -> Menghasilkan GLOBAL_FALLBACK (bukan silent)
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    def test_scenario_g_unknown_text_returns_global_fallback(self, mock_send_wa):
        mock_send_wa.return_value = True

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "platform_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": self.platform_phone_id,
                            "display_phone_number": "6285179555449"
                        },
                        "contacts": [{"profile": {"name": "Unknown"}, "wa_id": "628555444333"}],
                        "messages": [{
                            "from": "628555444333",
                            "id": "wamid.UNKNOWN_TEXT",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "xyz random gibberish 12345"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        # Must not be silent!
        self.assertEqual(data.get("status"), "success")
        self.assertIsNotNone(data.get("reply"))
        self.assertEqual(data.get("reply"), GLOBAL_FALLBACK_PLATFORM)

    # =========================================================================
    # h. Uji isolasi Tenant A vs Tenant B (tidak ada cross-route / leakage)
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    @patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock)
    def test_scenario_h_tenant_a_vs_tenant_b_isolation(self, mock_resolve_tenant, mock_send_wa):
        mock_send_wa.return_value = True
        
        # Call 1: Tenant A
        mock_resolve_tenant.return_value = TenantRuntimeContext(
            tenant_id="tenant-alpha",
            slug="tenant-alpha",
            business_type="PHYSICAL",
            capabilities={"catalog": True},
            metadata={"name": "Alpha Coffee", "secret_key": "ALPHA_SECRET"}
        )

        payload_a = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "tenant_a",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": self.tenant_a_phone_id},
                        "messages": [{"from": "6281001", "id": "m1", "type": "text", "text": {"body": "menu"}}]
                    }
                }]
            }]
        }

        resp_a = self.client.post("/api/v1/whatsapp/webhook", json=payload_a)
        data_a = resp_a.json()
        self.assertEqual(data_a.get("tenant"), "tenant-alpha")
        self.assertIn("Alpha Coffee", data_a.get("reply"))
        self.assertNotIn("Beta", data_a.get("reply"))

        # Call 2: Tenant B
        mock_resolve_tenant.return_value = TenantRuntimeContext(
            tenant_id="tenant-beta",
            slug="tenant-beta",
            business_type="PHYSICAL",
            capabilities={"catalog": True},
            metadata={"name": "Beta Sneaker", "secret_key": "BETA_SECRET"}
        )

        payload_b = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "tenant_b",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": self.tenant_b_phone_id},
                        "messages": [{"from": "6281002", "id": "m2", "type": "text", "text": {"body": "menu"}}]
                    }
                }]
            }]
        }

        resp_b = self.client.post("/api/v1/whatsapp/webhook", json=payload_b)
        data_b = resp_b.json()
        self.assertEqual(data_b.get("tenant"), "tenant-beta")
        self.assertIn("Beta Sneaker", data_b.get("reply"))
        self.assertNotIn("Alpha", data_b.get("reply"))

    # =========================================================================
    # i. Safe Webhook Acknowledgment untuk Unmapped Phone ID (Anti-Retry Storm)
    # =========================================================================
    @patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_by_phone_number_id", new_callable=AsyncMock)
    def test_unmapped_phone_id_safe_acknowledgment_prevents_retry_storm(self, mock_resolve_tenant):
        mock_resolve_tenant.return_value = None
        unmapped_phone_id = "777666555444"

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "unmapped_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "phone_number_id": unmapped_phone_id,
                            "display_phone_number": "628999999999"
                        },
                        "contacts": [{"profile": {"name": "Stranger"}, "wa_id": "628199999999"}],
                        "messages": [{
                            "from": "628199999999",
                            "id": "wamid.UNMAPPED_MSG",
                            "timestamp": "1741350000",
                            "type": "text",
                            "text": {"body": "halo"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        # Must return HTTP 200 OK with IGNORED_UNMAPPED (never 400/404)
        resp = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "IGNORED_UNMAPPED")
        self.assertEqual(data.get("phone_number_id"), unmapped_phone_id)

    # =========================================================================
    # j. Pemisahan Konseptual Messaging Window vs Token Expiry
    # =========================================================================
    @patch("app.whatsapp.traffic_splitter.send_whatsapp_text", new_callable=AsyncMock)
    def test_messaging_window_vs_token_expiry_separation(self, mock_send_wa):
        import asyncio
        from app.whatsapp.traffic_splitter import WebhookExecutionTrace, PlatformWebhookRouter
        from app.services.onboarding_service import onboarding_service

        mock_send_wa.return_value = True

        # Register pending tenant
        onboarding_service._tenants_by_slug["store-window-test"] = {
            "id": "t-window-id",
            "slug": "store-window-test",
            "status": "pending_wa_verification",
            "is_active": False,
            "created_at": "2026-09-18T10:00:00+00:00",
            "metadata": {
                "wa_verification_token": "BT-8899",
                "phone": "6281234568899",
                "is_verified": False,
            }
        }

        trace_non_user = WebhookExecutionTrace("msg_non_user", self.platform_phone_id, "6281234568899", "BT-8899")

        # Test Case 1: Non-user-initiated activation (e.g. backend sync / admin trigger)
        # Token valid & unexpired (< 48h), but NOT user-initiated: free-form message must be suppressed!
        res_non_user = asyncio.run(PlatformWebhookRouter._process_activation(
            token_suffix="8899",
            sender_phone="6281234568899",
            phone_number_id=self.platform_phone_id,
            raw_text="AKTIVASI BT-8899",
            trace=trace_non_user,
            is_user_initiated=False,
        ))

        self.assertEqual(res_non_user.get("status"), "success")
        self.assertEqual(res_non_user.get("verified"), True)
        self.assertEqual(res_non_user.get("free_form_dispatched"), False)
        self.assertEqual(res_non_user.get("messaging_window"), "NON_USER_INITIATED_SUPPRESSED")
        mock_send_wa.assert_not_called()

        # Reset tenant to pending for user-initiated test
        onboarding_service._tenants_by_slug["store-window-test"]["status"] = "pending_wa_verification"
        onboarding_service._tenants_by_slug["store-window-test"]["is_active"] = False

        # Test Case 2: User-initiated inbound message
        # Token valid & user initiated -> free-form message IS dispatched within 24h window
        trace_user = WebhookExecutionTrace("msg_user", self.platform_phone_id, "6281234568899", "BT-8899")
        res_user = asyncio.run(PlatformWebhookRouter._process_activation(
            token_suffix="8899",
            sender_phone="6281234568899",
            phone_number_id=self.platform_phone_id,
            raw_text="AKTIVASI BT-8899",
            trace=trace_user,
            is_user_initiated=True,
        ))

        self.assertEqual(res_user.get("status"), "success")
        self.assertEqual(res_user.get("verified"), True)
        self.assertEqual(res_user.get("free_form_dispatched"), True)
        self.assertEqual(res_user.get("messaging_window"), "USER_INITIATED_ACTIVE")
        mock_send_wa.assert_called_once()


if __name__ == "__main__":
    unittest.main()
