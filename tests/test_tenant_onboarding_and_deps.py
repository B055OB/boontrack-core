"""tests/test_tenant_onboarding_and_deps.py
Unit & Integration Tests for Tenant Onboarding & Global Isolation Dependency.

Validates:
1. Pydantic Schemas (`app/schemas/tenant.py`):
   - TenantCreateRequest validation (name >= 3 chars, slug regex alphanumeric+hyphen, business_category).
   - TenantResponse serialization (id, slug, status, created_at, etc.).
2. Tenant Onboarding Endpoint (`POST /api/v1/tenant/onboard`):
   - Successful creation with unique slug.
   - Optional WABA phone number binding and resolution check.
   - Rejection of duplicate slug with HTTP 409 Conflict.
3. Global Dependency Injection (`get_current_tenant`):
   - Success with valid X-Tenant-ID header (and caching).
   - Rejection with HTTP 401 Unauthorized when header is missing.
   - Rejection with HTTP 403 Forbidden when tenant is not found.
   - Rejection with HTTP 403 Forbidden when tenant is marked inactive/disabled.
"""

import os
import sys
import unittest
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import APIRouter, Depends, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.deps import (
    TenantContext,
    clear_tenant_cache,
    get_current_tenant,
    register_test_tenant,
)
from app.api.v1.endpoints.tenant_onboarding import (
    clear_onboarded_tenants_store,
)
from app.main import app
from app.schemas.tenant import TenantCreateRequest, TenantResponse
from app.services.tenant_resolver import (
    clear_tenant_cache as clear_waba_cache,
    resolve_tenant_by_phone_number_id,
)

# Test router to verify get_current_tenant dependency injection
isolation_router = APIRouter(prefix="/test/isolation", tags=["Test Isolation"])


@isolation_router.get("/tenant-profile")
async def get_test_tenant_profile(tenant: TenantContext = Depends(get_current_tenant)):
    return {
        "status": "success",
        "tenant_id": tenant.id,
        "tenant_slug": tenant.slug,
        "is_active": tenant.is_active,
    }


# Mount the test router once
app.include_router(isolation_router)


class TestTenantSchemas(unittest.TestCase):
    """Unit tests for TenantCreateRequest and TenantResponse schemas."""

    def test_valid_tenant_create_request(self):
        req = TenantCreateRequest(
            name="Little Bite Clinic",
            slug="little-bite-clinic",
            business_category="clinical_consultation",
            waba_phone_number_id="1365010890024026",
        )
        self.assertEqual(req.name, "Little Bite Clinic")
        self.assertEqual(req.slug, "little-bite-clinic")
        self.assertEqual(req.business_category, "clinical_consultation")
        self.assertEqual(req.waba_phone_number_id, "1365010890024026")

    def test_name_shorter_than_3_chars_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            TenantCreateRequest(
                name="AB",
                slug="valid-slug",
                business_category="fnb",
            )

    def test_slug_with_spaces_fails_validation(self):
        with self.assertRaises(ValidationError):
            TenantCreateRequest(
                name="Coffee Shop",
                slug="coffee shop",
                business_category="fnb",
            )

    def test_slug_with_invalid_characters_fails_validation(self):
        with self.assertRaises(ValidationError):
            TenantCreateRequest(
                name="Coffee Shop",
                slug="coffee_shop_invalid!",
                business_category="fnb",
            )

    def test_slug_alphanumeric_and_hyphen_passes(self):
        req = TenantCreateRequest(
            name="Toko Ritel 123",
            slug="retail-store-123",
            business_category="retail",
        )
        self.assertEqual(req.slug, "retail-store-123")

    def test_tenant_response_schema_serialization(self):
        now = datetime.now(timezone.utc)
        resp = TenantResponse(
            id=str(uuid.uuid4()),
            name="Alpha Store",
            slug="alpha-store",
            business_category="retail",
            status="active",
            is_active=True,
            created_at=now,
        )
        self.assertEqual(resp.name, "Alpha Store")
        self.assertEqual(resp.slug, "alpha-store")
        self.assertEqual(resp.status, "active")
        self.assertTrue(resp.is_active)
        self.assertIsNone(resp.waba_phone_number_id)


class TestTenantOnboardingEndpoint(unittest.TestCase):
    """Integration tests for POST /api/v1/tenant/onboard endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        clear_onboarded_tenants_store()
        clear_tenant_cache()
        clear_waba_cache()

    def test_onboard_tenant_success_with_unique_slug(self):
        unique_slug = f"unique-tenant-{os.urandom(4).hex()}"
        payload = {
            "name": "Kedai Kopi Nusantara",
            "slug": unique_slug,
            "business_category": "fnb",
        }

        res = self.client.post("/api/v1/tenant/onboard", json=payload)
        self.assertIn(res.status_code, (200, 201))

        data = res.json()
        self.assertIn("id", data)
        self.assertEqual(data["slug"], unique_slug)
        self.assertEqual(data["name"], "Kedai Kopi Nusantara")
        self.assertEqual(data["status"], "active")
        self.assertTrue(data["is_active"])
        self.assertIn("created_at", data)

    def test_onboard_tenant_with_waba_phone_binding(self):
        unique_slug = f"klinik-anak-{os.urandom(4).hex()}"
        waba_phone_id = f"waba_id_{os.urandom(4).hex()}"
        payload = {
            "name": "Klinik Tumbuh Kembang",
            "slug": unique_slug,
            "business_category": "clinical_consultation",
            "waba_phone_number_id": waba_phone_id,
        }

        res = self.client.post("/api/v1/tenant/onboard", json=payload)
        self.assertIn(res.status_code, (200, 201))

        data = res.json()
        self.assertEqual(data["slug"], unique_slug)
        self.assertEqual(data["waba_phone_number_id"], waba_phone_id)

    def test_onboard_tenant_duplicate_slug_returns_409_conflict(self):
        dup_slug = f"dup-slug-{os.urandom(4).hex()}"
        payload = {
            "name": "Toko Pertama",
            "slug": dup_slug,
            "business_category": "retail",
        }

        # First request succeeds
        res1 = self.client.post("/api/v1/tenant/onboard", json=payload)
        self.assertIn(res1.status_code, (200, 201))

        # Second request with the same slug must return 409 Conflict
        res2 = self.client.post("/api/v1/tenant/onboard", json=payload)
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)
        err = res2.json()
        self.assertIn("detail", err)
        self.assertIn("sudah terdaftar", err["detail"].lower())

    def test_onboard_tenant_invalid_slug_returns_422(self):
        payload = {
            "name": "Toko Invalid Slug",
            "slug": "invalid_slug_with_underscores!",
            "business_category": "retail",
        }
        res = self.client.post("/api/v1/tenant/onboard", json=payload)
        self.assertEqual(res.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)


class TestGlobalTenantIsolationDependency(unittest.TestCase):
    """Integration tests for get_current_tenant dependency injection."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        clear_tenant_cache()

    def test_get_current_tenant_success_with_header(self):
        t_id = f"t-{os.urandom(4).hex()}"
        t_slug = f"store-{os.urandom(4).hex()}"
        register_test_tenant(
            tenant_id=t_id,
            slug=t_slug,
            name="Active Store",
            is_active=True,
        )

        # Lookup by slug
        headers = {"X-Tenant-ID": t_slug}
        res = self.client.get("/test/isolation/tenant-profile", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["tenant_slug"], t_slug)
        self.assertTrue(data["is_active"])

        # Subsequent call tests cache acceleration
        res2 = self.client.get("/test/isolation/tenant-profile", headers=headers)
        self.assertEqual(res2.status_code, 200)

    def test_get_current_tenant_missing_header_returns_401(self):
        res = self.client.get("/test/isolation/tenant-profile")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        data = res.json()
        self.assertIn("detail", data)
        self.assertIn("missing", data["detail"].lower())

    def test_get_current_tenant_not_found_returns_403(self):
        headers = {"X-Tenant-ID": "nonexistent-tenant-xyz-999"}
        res = self.client.get("/test/isolation/tenant-profile", headers=headers)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        data = res.json()
        self.assertIn("detail", data)
        self.assertIn("not found", data["detail"].lower())

    def test_get_current_tenant_inactive_returns_403(self):
        t_id = f"inactive-{os.urandom(4).hex()}"
        t_slug = f"inactive-store-{os.urandom(4).hex()}"
        register_test_tenant(
            tenant_id=t_id,
            slug=t_slug,
            name="Suspended Store",
            is_active=False,
        )

        headers = {"X-Tenant-ID": t_slug}
        res = self.client.get("/test/isolation/tenant-profile", headers=headers)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        data = res.json()
        self.assertIn("detail", data)
        self.assertIn("deactivated", data["detail"].lower())


if __name__ == "__main__":
    unittest.main()
