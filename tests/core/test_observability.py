"""tests/core/test_observability.py
Unit & Integration Test Suite for Phase D - Tenant Health Aggregator & Config Audit Trail.

Tests:
1. Tenant health metrics aggregation (status, whatsapp_gateway, ai_gateway, payment_webhook).
2. Dynamic configuration updates and automatic audit trail logging to tenant_config_history.
3. Sensitive data masking (tokens, phone numbers, passwords, card numbers) in error logs & incident summaries.
4. Non-existent tenant handling (404).
"""

import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.services.observability_service import (
    ObservabilityService,
    observability_service,
    mask_sensitive_data,
)
from app.core.tenant_loader import load_tenant_configs, LOADED_CONFIG_TENANTS


class TestTenantObservabilityAndAudit(unittest.TestCase):
    """Test suite for internal observability and configuration audit logging."""

    def setUp(self):
        self.client = TestClient(app)
        self.service = ObservabilityService(in_memory_mode=True)
        # Ensure default configs are loaded
        load_tenant_configs()
        self.tenant_id = "atmosfitnes"

    # =========================================================================
    # 1. Health Aggregation
    # =========================================================================

    def test_tenant_health_aggregation(self):
        """Memvalidasi endpoint GET /api/v1/internal/tenants/{tenant_id}/health mengagregasi status komponen."""
        resp = self.client.get(f"/api/v1/internal/tenants/{self.tenant_id}/health")
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data["tenant_id"], self.tenant_id)
        self.assertIn(data["status"], ("HEALTHY", "DEGRADED", "DOWN"))

        # WhatsApp Gateway check
        self.assertIn(data["whatsapp_gateway"], ("CONNECTED", "DISCONNECTED"))

        # AI Gateway check
        ai = data["ai_gateway"]
        self.assertIn(ai["status"], ("UP", "DEGRADED", "DOWN"))
        self.assertIn("latency_ms", ai)
        self.assertIn("primary_provider", ai)
        self.assertIsInstance(ai["fallback_active"], bool)

        # Payment Webhook check
        payment = data["payment_webhook"]
        self.assertIn(payment["status"], ("ACTIVE", "INACTIVE"))
        self.assertIn("success_rate", payment)

    def test_payment_webhook_ping_tracking(self):
        """Memvalidasi kalkulasi success rate dan last ping pada payment webhook."""
        self.service.record_payment_ping("atmosfitnes", success=True)
        self.service.record_payment_ping("atmosfitnes", success=True)
        self.service.record_payment_ping("atmosfitnes", success=False)

        health = self.service.get_tenant_health("atmosfitnes")
        payment_info = health["payment_webhook"]
        self.assertEqual(payment_info["status"], "ACTIVE")
        self.assertIsNotNone(payment_info["last_ping"])
        self.assertEqual(payment_info["success_rate"], 66.67)

    # =========================================================================
    # 2. Sensitive Data Masking
    # =========================================================================

    def test_sensitive_data_masking_tokens_and_phones(self):
        """Memvalidasi sanitasi log: token Meta, Bearer, nomor HP, password disamarkan."""
        # 1. Masking Nomor Telepon
        raw_phone_log = "User 081234567890 and +6281987654321 attempted check-in"
        masked_phone = mask_sensitive_data(raw_phone_log)
        self.assertNotIn("081234567890", masked_phone)
        self.assertNotIn("+6281987654321", masked_phone)
        self.assertIn("***", masked_phone)

        # 2. Masking Token Meta (EAAN...)
        raw_meta_token = "Failed to dispatch WA message: token EAANbiVgBfGQBSQkvsZBc8JmqdEZBJWSrZAWR1gnJep0lkyZAv4O02LKEwjoNAc8lNOvaEeKhtb6pcr45S8wtd5CrSKdoMwEq6A1eJV4Yb140DBOMbmj3wLzo0Y7fZBrus25EJ0xeqXlPbDisP6d4DmZAGkvbJ7hnKfFih3G7L7mn6g56OQVU42dZByNSHNEiwZDZD is invalid"
        masked_meta = mask_sensitive_data(raw_meta_token)
        self.assertNotIn("EAANbiVgBfGQBSQkvsZBc8JmqdEZBJWSrZAWR1gnJep0lkyZAv4O02LKEwjoNAc8lNOvaEeKhtb6pcr45S8wtd5CrSKdoMwEq6A1eJV4Yb140DBOMbmj3wLzo0Y7fZBrus25EJ0xeqXlPbDisP6d4DmZAGkvbJ7hnKfFih3G7L7mn6g56OQVU42dZByNSHNEiwZDZD", masked_meta)
        self.assertIn("EAAN", masked_meta)
        self.assertIn("***", masked_meta)

        # 3. Masking Bearer Token
        raw_bearer = "Authorization: Bearer sk-proj-1234567890abcdef1234567890"
        masked_bearer = mask_sensitive_data(raw_bearer)
        self.assertNotIn("sk-proj-1234567890abcdef1234567890", masked_bearer)
        self.assertIn("Bearer", masked_bearer)
        self.assertIn("***", masked_bearer)

        # 4. Masking Password / Secret
        raw_secret = '{"secret": "myUltraSecretPassword123", "status": "failed"}'
        masked_secret = mask_sensitive_data(raw_secret)
        self.assertNotIn("myUltraSecretPassword123", masked_secret)
        self.assertIn("***", masked_secret)

    def test_incident_recording_with_automatic_sanitization(self):
        """Memvalidasi record_incident secara otomatis menyamarkan data rahasia pada health last_incident."""
        raw_error = "Webhook timeout for customer 081234567890 with secret 'shh_super_secret_token'"
        incident = observability_service.record_incident(
            tenant_id=self.tenant_id,
            message=raw_error,
            level="ERROR",
        )

        self.assertNotIn("081234567890", incident["message"])
        self.assertNotIn("shh_super_secret_token", incident["message"])
        self.assertIn("***", incident["message"])

        # Periksa lewat API endpoint
        resp = self.client.get(f"/api/v1/internal/tenants/{self.tenant_id}/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data["last_incident"])
        self.assertNotIn("081234567890", data["last_incident"]["message"])

    # =========================================================================
    # 3. Dynamic Config Update & Audit Trail
    # =========================================================================

    def test_config_update_and_audit_trail_history(self):
        """Memvalidasi endpoint POST /api/v1/internal/tenants/{tenant_id}/config mencatat audit history."""
        update_payload = {
            "field_path": "payment_config.provider",
            "new_value": "DANA_DYNAMIC",
            "changed_by": "ALDO_ADMIN",
        }

        # 1. Jalankan update config via HTTP POST
        post_resp = self.client.post(
            f"/api/v1/internal/tenants/{self.tenant_id}/config",
            json=update_payload,
        )
        self.assertEqual(post_resp.status_code, 200)
        post_data = post_resp.json()
        self.assertEqual(post_data["status"], "success")
        self.assertEqual(post_data["total_changes"], 1)

        change_entry = post_data["changes_applied"][0]
        self.assertEqual(change_entry["tenant_id"], self.tenant_id)
        self.assertEqual(change_entry["field_path"], "payment_config.provider")
        self.assertEqual(change_entry["new_value"], "DANA_DYNAMIC")
        self.assertEqual(change_entry["changed_by"], "ALDO_ADMIN")

        # 2. Periksa audit trail via GET /api/v1/internal/tenants/{tenant_id}/history
        hist_resp = self.client.get(f"/api/v1/internal/tenants/{self.tenant_id}/history")
        self.assertEqual(hist_resp.status_code, 200)
        hist_data = hist_resp.json()
        self.assertEqual(hist_data["tenant_id"], self.tenant_id)
        self.assertGreaterEqual(hist_data["total"], 1)

        matched_history = [
            h for h in hist_data["history"]
            if h["field_path"] == "payment_config.provider" and h["new_value"] == "DANA_DYNAMIC"
        ]
        self.assertTrue(len(matched_history) > 0, "Audit trail harus mencatat perubahan payment_config.provider")

    # =========================================================================
    # 4. Error Handling: Non-Existent Tenant
    # =========================================================================

    def test_non_existent_tenant_health_returns_404(self):
        """Memvalidasi tenant yang sama sekali tidak terdaftar mengembalikan HTTP 404."""
        resp = self.client.get("/api/v1/internal/tenants/non_existent_ghost_tenant_999/health")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
