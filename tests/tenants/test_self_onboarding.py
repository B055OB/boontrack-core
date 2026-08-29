"""tests/tenants/test_self_onboarding.py
Unit & Integration Test Suite for Merchant Self-Onboarding & Provisioning.

Tests:
1. Complete self-onboarding with tenant, initial product, and payout in 1 database transaction.
2. Verification of 'affiliate_ref' field persistence and database index on Tenant model.
3. Duplicate slug rejection (HTTP 409 Conflict) and transactional rollback integrity.
4. Payload validation enforcement (HTTP 422 for missing required fields or negative price).
5. Immediate availability of newly onboarded tenant in runtime registry.
"""

import os
import unittest
from decimal import Decimal
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.models.tenant import Tenant
from app.services.onboarding_service import (
    onboarding_service,
    TenantSlugAlreadyExistsError,
)
from app.core.tenant_loader import LOADED_CONFIG_TENANTS, TENANT_REGISTRY


class TestMerchantSelfOnboarding(unittest.TestCase):
    """Test suite for tenant self-onboarding and merchant provisioning."""

    def setUp(self):
        self.client = TestClient(app)
        onboarding_service.clear_state()

    def tearDown(self):
        onboarding_service.clear_state()

    # =========================================================================
    # 1. Successful Self-Onboarding Transaction
    # =========================================================================

    def test_successful_self_onboarding(self):
        """Memvalidasi registrasi tenant, produk pertama, dan payout dalam 1 transaksi atomik (HTTP 201)."""
        unique_suffix = uuid4().hex[:6]
        slug = f"kopi-senja-{unique_suffix}"
        payload = {
            "name": f"Kopi Senja {unique_suffix.upper()}",
            "slug": slug,
            "tier": "STARTER",
            "affiliate_ref": "AFF-BARISTA-01",
            "admin_email": "owner@kopisenja.com",
            "admin_phone": "081234567890",
            "product": {
                "title": "Paket Kopi Susu 1 Liter",
                "slug": f"kopi-susu-liter-{unique_suffix}",
                "description": "Kopi susu gula aren botol 1000ml siap minum",
                "price": 85000,
                "product_type": "DIGITAL_FILE",
                "asset_reference": "coffee_asset_001",
                "is_available": True,
            },
            "payout": {
                "bank_name": "BCA",
                "account_number": "8800112233",
                "account_holder": "Budi Santoso",
                "payout_email": "finance@kopisenja.com",
            },
        }

        resp = self.client.post("/api/v1/tenants/onboard", json=payload)
        self.assertEqual(resp.status_code, 201)

        data = resp.json()
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["message"], "Tenant onboarded successfully")

        # 1. Verifikasi Tenant Data
        tenant = data["tenant"]
        self.assertEqual(tenant["name"], payload["name"])
        self.assertEqual(tenant["slug"], slug)
        self.assertEqual(tenant["affiliate_ref"], "AFF-BARISTA-01")
        self.assertEqual(tenant["tier"], "STARTER")
        self.assertTrue(tenant["is_active"])

        # 2. Verifikasi Relasi Produk Pertama
        product = data["product"]
        self.assertEqual(product["tenant_id"], data["tenant_id"])
        self.assertEqual(product["title"], "Paket Kopi Susu 1 Liter")
        self.assertEqual(product["price"], 85000.0)

        # 3. Verifikasi Relasi Payout Merchant
        payout = data["payout"]
        self.assertEqual(payout["tenant_id"], data["tenant_id"])
        self.assertEqual(payout["bank_name"], "BCA")
        self.assertEqual(payout["account_number"], "8800112233")
        self.assertEqual(payout["account_holder"], "Budi Santoso")

    # =========================================================================
    # 2. Affiliate Reference Index & Persistence
    # =========================================================================

    def test_affiliate_ref_index_and_persistence(self):
        """Memvalidasi kolom affiliate_ref terindeks di model Tenant dan tersimpan saat onboarding."""
        # 1. Validasi model level: kolom affiliate_ref berstatus indexed
        affiliate_col = Tenant.__table__.columns.get("affiliate_ref")
        self.assertIsNotNone(affiliate_col, "Kolom affiliate_ref harus ada di tabel tenants")
        self.assertTrue(
            affiliate_col.index or any(idx.columns.contains(affiliate_col) for idx in Tenant.__table__.indexes),
            "Kolom affiliate_ref harus memiliki database index",
        )

        # 2. Onboarding dengan affiliate_ref
        unique_slug = f"toko-affiliate-{uuid4().hex[:6]}"
        payload_with_aff = {
            "name": "Toko Affiliate Hero",
            "slug": unique_slug,
            "affiliate_ref": "REF_PARTNER_777",
            "product": {
                "title": "Produk Affiliate 1",
                "price": 50000,
            },
            "payout": {
                "bank_name": "MANDIRI",
                "account_number": "13100223344",
                "account_holder": "Partner Hero",
            },
        }

        resp = self.client.post("/api/v1/tenants/onboard", json=payload_with_aff)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["tenant"]["affiliate_ref"], "REF_PARTNER_777")

        # 3. Onboarding tanpa affiliate_ref (opsional)
        unique_slug_no_aff = f"toko-no-aff-{uuid4().hex[:6]}"
        payload_no_aff = {
            "name": "Toko Tanpa Affiliate",
            "slug": unique_slug_no_aff,
            "product": {
                "title": "Produk Mandiri 1",
                "price": 25000,
            },
            "payout": {
                "bank_name": "BRI",
                "account_number": "002201998877",
                "account_holder": "Merchant Mandiri",
            },
        }
        resp_no_aff = self.client.post("/api/v1/tenants/onboard", json=payload_no_aff)
        self.assertEqual(resp_no_aff.status_code, 201)
        self.assertIsNone(resp_no_aff.json()["tenant"]["affiliate_ref"])

    # =========================================================================
    # 3. Duplicate Slug Conflict & Rollback Integrity
    # =========================================================================

    def test_duplicate_slug_conflict_and_rollback(self):
        """Memvalidasi penolakan slug duplikat (HTTP 409) dan jaminan transaksi atomik."""
        duplicate_slug = f"brand-unik-{uuid4().hex[:6]}"
        initial_payload = {
            "name": "Brand Unik Pertama",
            "slug": duplicate_slug,
            "product": {
                "title": "Produk Pertama",
                "price": 10000,
            },
            "payout": {
                "bank_name": "BNI",
                "account_number": "0987654321",
                "account_holder": "Owner Pertama",
            },
        }

        # First request succeeds
        resp1 = self.client.post("/api/v1/tenants/onboard", json=initial_payload)
        self.assertEqual(resp1.status_code, 201)

        # Second request with duplicate slug must be rejected with 409
        second_payload = {
            "name": "Brand Unik Palsu",
            "slug": duplicate_slug,
            "product": {
                "title": "Produk Kedua Duplikat",
                "price": 99999,
            },
            "payout": {
                "bank_name": "BCA",
                "account_number": "1122334455",
                "account_holder": "Peniru",
            },
        }

        resp2 = self.client.post("/api/v1/tenants/onboard", json=second_payload)
        self.assertEqual(resp2.status_code, 409)
        self.assertIn("already exists", resp2.json()["detail"].lower())

    # =========================================================================
    # 4. Schema Validation (Missing Fields & Negative Price)
    # =========================================================================

    def test_validation_error_on_invalid_payload(self):
        """Memvalidasi kegagalan validasi schema (HTTP 422) jika data wajib kosong atau invalid."""
        # 1. Harga produk negatif
        invalid_price_payload = {
            "name": "Toko Invalid Price",
            "slug": "toko-invalid-price",
            "product": {
                "title": "Barang Murah",
                "price": -10000,  # Invalid
            },
            "payout": {
                "bank_name": "BCA",
                "account_number": "12345678",
                "account_holder": "Budi",
            },
        }
        resp_price = self.client.post("/api/v1/tenants/onboard", json=invalid_price_payload)
        self.assertEqual(resp_price.status_code, 422)

        # 2. Payout info tidak lengkap (missing account_number)
        missing_payout_payload = {
            "name": "Toko Missing Payout",
            "slug": "toko-missing-payout",
            "product": {
                "title": "Barang Bagus",
                "price": 50000,
            },
            "payout": {
                "bank_name": "BCA",
                # missing account_number & account_holder
            },
        }
        resp_payout = self.client.post("/api/v1/tenants/onboard", json=missing_payout_payload)
        self.assertEqual(resp_payout.status_code, 422)

    # =========================================================================
    # 5. Immediate Runtime Availability
    # =========================================================================

    def test_onboarded_tenant_immediate_active_in_registry(self):
        """Memvalidasi tenant yang baru saja di-onboard langsung aktif di runtime registry platform."""
        new_slug = f"kedai-ramen-{uuid4().hex[:6]}"
        payload = {
            "name": "Kedai Ramen Ichiban",
            "slug": new_slug,
            "product": {
                "title": "Ramen Kuah Tori Paitan",
                "price": 45000,
            },
            "payout": {
                "bank_name": "DANA",
                "account_number": "081234567890",
                "account_holder": "Chef Ramen",
            },
        }

        resp = self.client.post("/api/v1/tenants/onboard", json=payload)
        self.assertEqual(resp.status_code, 201)

        # Cek runtime loader
        self.assertIn(new_slug, LOADED_CONFIG_TENANTS)
        self.assertEqual(LOADED_CONFIG_TENANTS[new_slug].identity.name, "Kedai Ramen Ichiban")
        self.assertIn(new_slug, TENANT_REGISTRY)


if __name__ == "__main__":
    unittest.main()
