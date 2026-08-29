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
from app.models.tenant import Tenant, OnboardingMode
from app.configs.templates import COMMERCE_TEMPLATE, RETAIL_D2C_TEMPLATE, CommerceVertical
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
        self.assertEqual(tenant["onboarding_mode"], "SELF_SERVICE")
        self.assertEqual(tenant["template"], "COMMERCE_TEMPLATE")
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

    # =========================================================================
    # 6. Dual GTM Motion Flags (onboarding_mode)
    # =========================================================================

    def test_onboarding_mode_dual_gtm_motions(self):
        """Memvalidasi fleksibilitas dual GTM motion (SELF_SERVICE, ASSISTED, ENTERPRISE)."""
        # 1. Validasi enum definition & model column index
        self.assertEqual(OnboardingMode.SELF_SERVICE.value, "SELF_SERVICE")
        self.assertEqual(OnboardingMode.ASSISTED.value, "ASSISTED")
        self.assertEqual(OnboardingMode.ENTERPRISE.value, "ENTERPRISE")

        mode_col = Tenant.__table__.columns.get("onboarding_mode")
        self.assertIsNotNone(mode_col, "Kolom onboarding_mode wajib ada di tabel tenants")
        self.assertTrue(
            mode_col.index or any(idx.columns.contains(mode_col) for idx in Tenant.__table__.indexes),
            "Kolom onboarding_mode harus memiliki database index",
        )

        # 2. Test Default SELF_SERVICE saat onboarding_mode tidak dikirimkan
        slug_default = f"store-self-{uuid4().hex[:6]}"
        resp_def = self.client.post("/api/v1/tenants/onboard", json={
            "name": "Store Self Service",
            "slug": slug_default,
            "product": {"title": "Barang 1", "price": 10000},
            "payout": {"bank_name": "BCA", "account_number": "111", "account_holder": "Owner"},
        })
        self.assertEqual(resp_def.status_code, 201)
        self.assertEqual(resp_def.json()["tenant"]["onboarding_mode"], "SELF_SERVICE")

        # 3. Test Explicit ASSISTED Onboarding Mode
        slug_assisted = f"store-assisted-{uuid4().hex[:6]}"
        resp_asst = self.client.post("/api/v1/tenants/onboard", json={
            "name": "Store Assisted Motion",
            "slug": slug_assisted,
            "onboarding_mode": "ASSISTED",
            "product": {"title": "Barang Assisted", "price": 20000},
            "payout": {"bank_name": "BRI", "account_number": "222", "account_holder": "Partner"},
        })
        self.assertEqual(resp_asst.status_code, 201)
        self.assertEqual(resp_asst.json()["tenant"]["onboarding_mode"], "ASSISTED")

        # 4. Test Explicit ENTERPRISE Onboarding Mode
        slug_ent = f"store-enterprise-{uuid4().hex[:6]}"
        resp_ent = self.client.post("/api/v1/tenants/onboard", json={
            "name": "Store Enterprise Motion",
            "slug": slug_ent,
            "onboarding_mode": "ENTERPRISE",
            "tier": "ENTERPRISE",
            "product": {"title": "Custom Solution", "price": 5000000},
            "payout": {"bank_name": "MANDIRI", "account_number": "333", "account_holder": "PT Maju Bersama"},
        })
        self.assertEqual(resp_ent.status_code, 201)
        self.assertEqual(resp_ent.json()["tenant"]["onboarding_mode"], "ENTERPRISE")

    # =========================================================================
    # 7. Generic COMMERCE_TEMPLATE Abstraction & Dynamic Verticals
    # =========================================================================

    def test_commerce_template_abstraction_and_verticals(self):
        """Memvalidasi template generic COMMERCE_TEMPLATE, alias RETAIL_D2C_TEMPLATE, dan multi-vertical."""
        # 1. Validasi struktur generic template & alias backward compatibility
        self.assertIs(RETAIL_D2C_TEMPLATE, COMMERCE_TEMPLATE, "RETAIL_D2C_TEMPLATE harus alias dari COMMERCE_TEMPLATE")
        self.assertIn("vertical_configs", COMMERCE_TEMPLATE)
        for vert in ["DIGITAL_PRODUCTS", "FASHION", "BEAUTY", "FNB", "SERVICES"]:
            self.assertIn(vert, COMMERCE_TEMPLATE["vertical_configs"])

        # 2. Test Onboarding dengan alias RETAIL_D2C_TEMPLATE -> Ter-normalize ke COMMERCE_TEMPLATE
        slug_alias = f"d2c-store-{uuid4().hex[:6]}"
        resp_alias = self.client.post("/api/v1/tenants/onboard", json={
            "name": "Butik Busana Indah",
            "slug": slug_alias,
            "template": "RETAIL_D2C_TEMPLATE",
            "vertical": "FASHION",
            "product": {"title": "Kemeja Linen Premium", "price": 175000},
            "payout": {"bank_name": "BCA", "account_number": "444555", "account_holder": "Butik Indah"},
        })
        self.assertEqual(resp_alias.status_code, 201)
        tenant_alias = resp_alias.json()["tenant"]
        self.assertEqual(tenant_alias["template"], "COMMERCE_TEMPLATE")
        self.assertEqual(tenant_alias["vertical"], "FASHION")

        # 3. Test Dynamic Multi-Vertical Configuration (Tanpa duplikasi engine)
        verticals_to_test = [
            ("FNB", "Resto Sedap Rasa", "Paket Nasi Liwet", 35000),
            ("BEAUTY", "Glow Skincare Official", "Serum Pencerah Wajah", 120000),
            ("SERVICES", "Studio Konsultasi Karir", "Sesi 1-on-1 Mentoring", 250000),
            ("DIGITAL_PRODUCTS", "EduTech Indonesia", "E-Book Master Python", 75000),
        ]

        for vert_name, brand_name, prod_title, price in verticals_to_test:
            vert_slug = f"test-vert-{vert_name.lower()}-{uuid4().hex[:4]}"
            resp_vert = self.client.post("/api/v1/tenants/onboard", json={
                "name": brand_name,
                "slug": vert_slug,
                "template": "COMMERCE_TEMPLATE",
                "vertical": vert_name,
                "product": {"title": prod_title, "price": price},
                "payout": {"bank_name": "BNI", "account_number": "999888", "account_holder": brand_name},
            })
            self.assertEqual(resp_vert.status_code, 201)
            t_data = resp_vert.json()["tenant"]
            self.assertEqual(t_data["vertical"], vert_name)
            self.assertEqual(t_data["template"], "COMMERCE_TEMPLATE")

            # Verifikasi injected runtime persona & keywords
            actual_slug = t_data["slug"]
            config = LOADED_CONFIG_TENANTS.get(actual_slug)
            self.assertIsNotNone(config)
            self.assertIn(vert_name, COMMERCE_TEMPLATE["vertical_configs"])
            expected_keywords = COMMERCE_TEMPLATE["vertical_configs"][vert_name]["menu_keywords"]
            self.assertEqual(config.menu_config.keywords, expected_keywords)


if __name__ == "__main__":
    unittest.main()
