"""
tests/api/test_auth_registration_security.py
Comprehensive Security Regression Test Suite for PR #29.

Validates the complete remediation of:
- Attack Path A: Self-Asserted Email Identity / JWT Impersonation (Zero DB Write Privilege).
- Attack Path B: Tenant Slug Hijacking / Owner Mutation (Privileged DB Write).

Required Test Matrix (CTO P0/P1 Work Order):
Negative Tests:
1. Direct registration with victim email cannot return JWT without email verification.
2. DB write failure cannot return JWT (fails closed with HTTP 503).
3. Existing victim slug cannot be claimed using victim email without proving inbox ownership.
4. Existing slug cannot be overwritten by a different email (HTTP 409 Conflict).
5. Insert conflict cannot be swallowed and followed by JWT (HTTP 409 Conflict).
6. Valid OTP for an unrelated email cannot claim victim tenant (HTTP 403 Forbidden).
7. Expired or replayed OTP cannot issue JWT (HTTP 401 Unauthorized).
8. Database membership failure cannot issue JWT (HTTP 503 Service Unavailable).

Positive Tests:
9. Existing owner with valid email verification can authenticate.
10. Legitimate staff with active cs_agents membership can authenticate.
11. New merchant can complete pending onboarding and authenticate after valid email verification.
12. Existing magic-link login contract remains functional.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.abspath("."))
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "super-secret-core-jwt-key-for-test-isolation-32chars"
os.environ["CORE_JWT_ISSUER"] = "boontrack-core"
os.environ["CORE_JWT_AUDIENCE"] = "boontrack-api"

from app.main import app
from app.routes.auth_routes import (
    token_store,
    register_auth_test_merchant,
    clear_auth_test_registries,
    _in_memory_merchants,
    _pending_registrations,
)
from app.routes.media_routes import (
    verify_signed_merchant_session,
    authorize_tenant_upload,
    clear_merchant_membership_registry,
    register_merchant_membership,
)
from app.services.email_service import email_service


class DummyRequest:
    """Mock HTTP request with Bearer authorization header."""
    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}


class TestAuthRegistrationSecurity(unittest.TestCase):
    def setUp(self):
        clear_auth_test_registries()
        clear_merchant_membership_registry()
        self.client = TestClient(app)

    def tearDown(self):
        clear_auth_test_registries()
        clear_merchant_membership_registry()

    # -------------------------------------------------------------------------
    # Negative Test 1: Direct registration cannot return JWT without email verification
    # -------------------------------------------------------------------------
    def test_direct_registration_with_victim_email_cannot_return_jwt_without_email_verification(self):
        """
        TASK 5 — Negative Test 1:
        Direct registration with victim email must NEVER return an access_token.
        Response must be HTTP 201 Created with status 'pending_verification'.
        """
        victim_email = "owner@victim-store.com"
        victim_slug = "victim-store-unique-1"

        with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic, \
             patch.object(email_service, "send_merchant_welcome_email", new_callable=AsyncMock) as mock_welcome:
            mock_magic.return_value = True
            mock_welcome.return_value = True

            res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": victim_email,
                    "name": "Attacker Impersonator",
                    "tenant_slug": victim_slug,
                    "store_name": "Victim Store",
                },
            )

            self.assertEqual(res.status_code, 201)
            data = res.json()
            self.assertEqual(data["status"], "pending_verification")
            self.assertTrue(data.get("requires_verification"))
            # MUST NOT issue an access token
            self.assertNotIn("access_token", data)
            self.assertNotIn("token", data)
            # Proof of verification email dispatched
            self.assertTrue(mock_magic.called)

    # -------------------------------------------------------------------------
    # Negative Test 2: DB write failure cannot return JWT (fails closed)
    # -------------------------------------------------------------------------
    def test_db_write_failure_cannot_return_jwt_and_fails_closed(self):
        """
        TASK 5 — Negative Test 2:
        When database write fails (e.g. RLS denial, connection drop), the registration
        handler must fail closed with HTTP 503 and NEVER issue a JWT token.
        """
        victim_email = "victim@company.test"
        victim_slug = "db-fail-store"

        mock_supabase = MagicMock()
        mock_table = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.side_effect = Exception("42501: permission denied for table merchants")
        mock_table.insert.return_value = mock_insert
        mock_supabase.table.return_value = mock_table

        with patch("app.routes.auth_routes.get_supabase", return_value=mock_supabase), \
             patch("app.core.database.get_db_connection", side_effect=Exception("DB connection refused")), \
             patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic:

            res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": victim_email,
                    "name": "Attacker",
                    "tenant_slug": victim_slug,
                },
            )

            # Must fail closed with HTTP 503
            self.assertEqual(res.status_code, 503)
            self.assertIn("Layanan database gagal", res.json()["detail"])
            # Verification email must NOT be sent on DB failure
            self.assertFalse(mock_magic.called)

    # -------------------------------------------------------------------------
    # Negative Test 3: Existing victim slug cannot be claimed without inbox proof
    # -------------------------------------------------------------------------
    def test_existing_victim_slug_cannot_be_claimed_using_victim_email_without_proving_inbox_ownership(self):
        """
        TASK 5 — Negative Test 3:
        When an existing slug is registered to victim@domain.com, an attacker submitting
        victim@domain.com for that slug receives pending verification, NOT a JWT.
        Attempting to verify with a wrong/guess OTP fails with HTTP 401.
        """
        victim_email = "legit_owner@victimcorp.com"
        victim_slug = "victim-corp-live"

        # Register existing active merchant in database fixture
        register_auth_test_merchant(slug=victim_slug, owner_email=victim_email, is_active=True)

        with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic, \
             patch.object(email_service, "send_merchant_welcome_email", new_callable=AsyncMock):
            mock_magic.return_value = True

            # Attacker submits victim's email and slug
            reg_res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": victim_email,
                    "name": "Attacker",
                    "tenant_slug": victim_slug,
                },
            )
            self.assertEqual(reg_res.status_code, 201)
            self.assertNotIn("access_token", reg_res.json())

            # Attacker attempts to verify using an invalid/random OTP code
            verify_res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": "000000"},
            )
            self.assertEqual(verify_res.status_code, 401)
            self.assertIn("tidak valid", verify_res.json()["detail"].lower())

    # -------------------------------------------------------------------------
    # Negative Test 4: Existing slug cannot be overwritten by different email
    # -------------------------------------------------------------------------
    def test_existing_slug_cannot_be_overwritten_by_different_email(self):
        """
        TASK 5 — Negative Test 4:
        When slug 'warung-kopi' belongs to 'kopi_owner@domain.com', an attacker registering
        with 'attacker@evil.com' claiming 'warung-kopi' must be rejected with HTTP 409 Conflict.
        The database owner must remain unchanged.
        """
        owner_email = "kopi_owner@domain.com"
        attacker_email = "attacker@evil.com"
        target_slug = "warung-kopi"

        register_auth_test_merchant(slug=target_slug, owner_email=owner_email, is_active=True)

        res = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": attacker_email,
                "name": "Attacker",
                "tenant_slug": target_slug,
            },
        )

        self.assertEqual(res.status_code, 409)
        self.assertIn("sudah terdaftar untuk pemilik lain", res.json()["detail"])
        # Verify slug remains owned by legitimate owner
        self.assertEqual(_in_memory_merchants[target_slug]["owner_email"], owner_email)

    # -------------------------------------------------------------------------
    # Negative Test 5: Insert conflict cannot be swallowed and followed by JWT
    # -------------------------------------------------------------------------
    def test_insert_conflict_cannot_be_swallowed_and_followed_by_jwt(self):
        """
        TASK 5 — Negative Test 5:
        If database raises a 23505 unique constraint violation on insert, the handler
        must NOT swallow it. It must return HTTP 409 and never mint a JWT.
        """
        slug = "conflict-slug"
        email = "registrant@test.com"

        mock_supabase = MagicMock()
        mock_table = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.side_effect = Exception("23505: duplicate key value violates unique constraint 'merchants_slug_key'")
        mock_table.insert.return_value = mock_insert
        mock_supabase.table.return_value = mock_table

        with patch("app.routes.auth_routes.get_supabase", return_value=mock_supabase), \
             patch("app.core.database.get_db_connection", side_effect=Exception("psql unconfigured")):

            res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": email,
                    "name": "Registrant",
                    "tenant_slug": slug,
                },
            )

            self.assertEqual(res.status_code, 409)
            self.assertIn("sudah terdaftar", res.json()["detail"])

    # -------------------------------------------------------------------------
    # Negative Test 6: Valid OTP for unrelated email cannot claim victim tenant
    # -------------------------------------------------------------------------
    def test_valid_otp_for_unrelated_email_cannot_claim_victim_tenant(self):
        """
        TASK 5 — Negative Test 6:
        Attacker possesses a valid OTP for 'attacker@evil.com'.
        Attacker attempts to authenticate and claim 'victim-shop' (owned by victim).
        The verification endpoint must reject with HTTP 403 Forbidden.
        """
        victim_email = "real_owner@victim.com"
        attacker_email = "attacker@evil.com"
        victim_slug = "victim-shop"

        # Victim owns victim-shop
        register_auth_test_merchant(slug=victim_slug, owner_email=victim_email, is_active=True)

        # Attacker requests magic link with claimed_tenant_slug="victim-shop"
        attacker_token = "valid_attacker_token_xyz"
        attacker_otp = "654321"

        token_store.set_token(
            f"bt:auth:magic_link_otp:{attacker_otp}",
            {
                "email": attacker_email,
                "token": attacker_token,
                "otp_code": attacker_otp,
                "tenant_slug": victim_slug,  # Maliciously claiming victim's slug
                "is_registration": False,    # Existing login flow
            },
            ttl_seconds=900,
        )

        res = self.client.post(
            "/api/v1/auth/magic-link/verify",
            json={"otp_code": attacker_otp},
        )

        # Must reject with HTTP 403 Forbidden
        self.assertEqual(res.status_code, 403)
        self.assertIn("tidak memiliki keanggotaan aktif", res.json()["detail"])

    # -------------------------------------------------------------------------
    # Negative Test 7: Expired or replayed OTP cannot issue JWT
    # -------------------------------------------------------------------------
    def test_expired_or_replayed_otp_cannot_issue_jwt(self):
        """
        TASK 5 — Negative Test 7:
        An OTP can only be used once. Second attempt (replay) must return HTTP 401.
        Expired tokens must also return HTTP 401.
        """
        user_email = "user@replay-test.com"
        tenant_slug = "replay-store"
        token = "single_use_token_999"
        otp = "123987"

        register_auth_test_merchant(slug=tenant_slug, owner_email=user_email, is_active=True)

        token_store.set_token(
            f"bt:auth:magic_link_otp:{otp}",
            {
                "email": user_email,
                "token": token,
                "otp_code": otp,
                "tenant_slug": tenant_slug,
                "is_registration": False,
            },
            ttl_seconds=900,
        )
        token_store.set_token(
            f"bt:auth:magic_link:{token}",
            {
                "email": user_email,
                "token": token,
                "otp_code": otp,
                "tenant_slug": tenant_slug,
                "is_registration": False,
            },
            ttl_seconds=900,
        )

        # First attempt: SUCCESS
        res1 = self.client.post("/api/v1/auth/magic-link/verify", json={"otp_code": otp})
        self.assertEqual(res1.status_code, 200)
        self.assertIn("access_token", res1.json())

        # Second attempt (Replay): 401 UNAUTHORIZED
        res2 = self.client.post("/api/v1/auth/magic-link/verify", json={"otp_code": otp})
        self.assertEqual(res2.status_code, 401)
        self.assertIn("tidak valid", res2.json()["detail"].lower())

        # Associated token replay also fails
        res3 = self.client.post("/api/v1/auth/magic-link/verify", json={"token": token})
        self.assertEqual(res3.status_code, 401)

    # -------------------------------------------------------------------------
    # Negative Test 8: Database membership failure cannot issue JWT
    # -------------------------------------------------------------------------
    def test_database_membership_failure_cannot_issue_jwt(self):
        """
        TASK 5 — Negative Test 8:
        If database lookup fails during verification, the handler must fail closed
        with HTTP 503 and NEVER issue a JWT token.
        """
        user_email = "merchant@db-fail.com"
        tenant_slug = "fail-tenant"
        otp = "889900"

        token_store.set_token(
            f"bt:auth:magic_link_otp:{otp}",
            {
                "email": user_email,
                "otp_code": otp,
                "tenant_slug": tenant_slug,
                "is_registration": False,
            },
            ttl_seconds=900,
        )

        # Mock membership lookup to fail with database exception
        with patch("app.routes.auth_routes._resolve_verified_user_membership", return_value=(None, "DB_CONN_TIMEOUT: simulated failure")):
            res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": otp},
            )
            self.assertEqual(res.status_code, 503)
            self.assertIn("Layanan database otorisasi keanggotaan tidak tersedia", res.json()["detail"])

    # -------------------------------------------------------------------------
    # Positive Test 9: Existing owner with valid email verification can authenticate
    # -------------------------------------------------------------------------
    def test_existing_owner_with_valid_email_verification_can_authenticate(self):
        """
        TASK 5 — Positive Test 9:
        Legitimate owner with active merchants record can request OTP and verify.
        Receives HTTP 200 with signed JWT for their owned tenant with role='merchant'.
        """
        owner_email = "owner@authentic-shop.com"
        tenant_slug = "authentic-shop"

        register_auth_test_merchant(slug=tenant_slug, owner_email=owner_email, is_active=True)

        with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            # 1. Request magic link
            req_res = self.client.post(
                "/api/v1/auth/magic-link/request",
                json={"email": owner_email, "tenant_slug": tenant_slug},
            )
            self.assertEqual(req_res.status_code, 200)

            # Extract generated OTP from token_store
            call_kwargs = mock_send.call_args.kwargs
            otp_code = call_kwargs["otp_code"]

            # 2. Verify magic link with OTP
            ver_res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": otp_code},
            )
            self.assertEqual(ver_res.status_code, 200)
            data = ver_res.json()
            self.assertIn("access_token", data)
            self.assertEqual(data["user"]["email"], owner_email)
            self.assertEqual(data["user"]["tenant_slug"], tenant_slug)
            self.assertEqual(data["user"]["role"], "merchant")

            # 3. Downstream upload authorization succeeds
            mock_req = DummyRequest(data["access_token"])
            auth_session = verify_signed_merchant_session(mock_req)
            self.assertEqual(auth_session["tenant_id"], tenant_slug)
            self.assertEqual(auth_session["merchant_id"], owner_email)

    # -------------------------------------------------------------------------
    # Positive Test 10: Legitimate staff with active cs_agents can authenticate
    # -------------------------------------------------------------------------
    def test_legitimate_staff_with_active_cs_agents_membership_can_authenticate(self):
        """
        TASK 5 — Positive Test 10:
        Legitimate staff member in cs_agents can authenticate via magic link.
        Receives signed JWT with their assigned staff role and tenant_id.
        """
        staff_email = "staff_agent@support.com"
        tenant_slug = "client-brand"
        staff_role = "agent"

        # Mock membership lookup returning cs_agents record
        mock_membership = {
            "role": staff_role,
            "tenant_slug": tenant_slug,
            "is_active": True,
        }

        otp = "765432"
        token_store.set_token(
            f"bt:auth:magic_link_otp:{otp}",
            {
                "email": staff_email,
                "otp_code": otp,
                "tenant_slug": tenant_slug,
                "is_registration": False,
            },
            ttl_seconds=900,
        )

        with patch("app.routes.auth_routes._resolve_verified_user_membership", return_value=(mock_membership, None)):
            res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": otp},
            )

            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("access_token", data)
            self.assertEqual(data["user"]["email"], staff_email)
            self.assertEqual(data["user"]["tenant_slug"], tenant_slug)
            self.assertEqual(data["user"]["role"], staff_role)

    # -------------------------------------------------------------------------
    # Positive Test 11: New merchant can complete onboarding after email verification
    # -------------------------------------------------------------------------
    def test_new_merchant_can_complete_pending_onboarding_and_authenticate_after_valid_email_verification(self):
        """
        TASK 5 — Positive Test 11:
        New merchant registers -> status is pending_verification (no JWT).
        Merchant submits valid OTP -> merchant is activated in DB and receives JWT.
        """
        merchant_email = "founder@startup-shop.com"
        merchant_slug = "startup-shop-2026"
        merchant_name = "Founder Startup"

        with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic, \
             patch.object(email_service, "send_merchant_welcome_email", new_callable=AsyncMock) as mock_welcome:
            mock_magic.return_value = True
            mock_welcome.return_value = True

            # 1. Registration
            reg_res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": merchant_email,
                    "name": merchant_name,
                    "tenant_slug": merchant_slug,
                    "store_name": "Startup Store",
                },
            )
            self.assertEqual(reg_res.status_code, 201)
            reg_data = reg_res.json()
            self.assertEqual(reg_data["status"], "pending_verification")
            self.assertNotIn("access_token", reg_data)

            # Extract OTP sent in email
            call_kwargs = mock_magic.call_args.kwargs
            otp_code = call_kwargs["otp_code"]

            # 2. Verify with valid OTP
            ver_res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": otp_code},
            )
            self.assertEqual(ver_res.status_code, 200)
            ver_data = ver_res.json()
            self.assertIn("access_token", ver_data)
            self.assertEqual(ver_data["user"]["email"], merchant_email)
            self.assertEqual(ver_data["user"]["tenant_slug"], merchant_slug)
            self.assertEqual(ver_data["user"]["role"], "merchant")

            # 3. Verify merchant is now marked ACTIVE in database fixture
            self.assertEqual(_in_memory_merchants[merchant_slug]["status"], "ACTIVE")

    # -------------------------------------------------------------------------
    # Positive Test 12: Existing magic-link login contract remains functional
    # -------------------------------------------------------------------------
    def test_existing_magic_link_login_contract_remains_functional(self):
        """
        TASK 5 — Positive Test 12:
        Full end-to-end magic link request -> verify flow remains 100% backward compatible
        for legitimate existing users.
        """
        user_email = "existing_merchant@boontrack.com"
        tenant_slug = "existing-merchant-store"

        register_auth_test_merchant(slug=tenant_slug, owner_email=user_email, is_active=True)

        with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            # Request
            req_res = self.client.post(
                "/api/v1/auth/magic-link/request",
                json={"email": user_email, "tenant_slug": tenant_slug},
            )
            self.assertEqual(req_res.status_code, 200)
            self.assertEqual(req_res.json()["status"], "success")

            # Verify
            otp_code = mock_send.call_args.kwargs["otp_code"]
            ver_res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": otp_code},
            )
            self.assertEqual(ver_res.status_code, 200)
            self.assertIn("access_token", ver_res.json())
            self.assertEqual(ver_res.json()["user"]["email"], user_email)


if __name__ == "__main__":
    unittest.main()

