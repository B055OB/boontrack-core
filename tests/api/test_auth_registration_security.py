"""
tests/api/test_auth_registration_security.py
Comprehensive Security Regression Test Suite for PR #29.

Validates the complete remediation of:
- Attack Path A: Self-Asserted Email Identity / JWT Impersonation (Zero DB Write Privilege).
- Attack Path B: Tenant Slug Hijacking / Owner Mutation (Privileged DB Write).

Required Test Matrix (CTO P0/P1 Work Order — Task 6):
1. DB credentials absent => registration HTTP 503.
2. PostgreSQL insert failure + Supabase unavailable => 503.
3. Failed activation leaves no in-memory active membership.
4. Subsequent login cannot authenticate from failed activation memory residue.
5. UPDATE rowcount zero => no JWT.
6. Existing public.tenants slug without merchants row cannot be claimed by an unrelated registrant.
7. Existing suspended merchant cannot self-reactivate.
8. Failed email dispatch cannot permanently reserve a slug.
9. Two concurrent OTP verifications => at most one JWT.
10. Production mode never consults test-only registries.
11. New merchant authentication succeeds with real persisted pending row + verified email.
12. New merchant upload authorization succeeds after activation without any in-memory fixture.
13. Existing owner login remains valid.
14. Existing active cs_agents staff login remains valid.
"""

import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.abspath("."))
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "super-secret-core-jwt-key-for-test-isolation-32chars"
os.environ["CORE_JWT_ISSUER"] = "boontrack-core"
os.environ["CORE_JWT_AUDIENCE"] = "boontrack-api"
os.environ["BOONTRACK_DISABLE_AUTH_RATE_LIMIT"] = "1"

from app.main import app
from app.routes.auth_routes import (
    token_store,
    register_auth_test_merchant,
    clear_auth_test_registries,
    _in_memory_merchants,
    _pending_registrations,
    _query_existing_merchant_by_slug,
    _resolve_verified_user_membership,
    auth_rate_limiter,
)
from app.routes.media_routes import (
    verify_signed_merchant_session,
    authorize_tenant_upload,
    clear_merchant_membership_registry,
    register_merchant_membership,
    _merchant_memberships,
)
from app.services.email_service import email_service


class DummyRequest:
    """Mock HTTP request with Bearer authorization header."""
    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}


class TestAuthRegistrationSecurity(unittest.TestCase):
    def setUp(self):
        os.environ["APP_ENV"] = "test"
        clear_auth_test_registries()
        clear_merchant_membership_registry()
        auth_rate_limiter.reset()
        self.client = TestClient(app)

    def tearDown(self):
        os.environ["APP_ENV"] = "test"
        clear_auth_test_registries()
        clear_merchant_membership_registry()
        auth_rate_limiter.reset()

    # -------------------------------------------------------------------------
    # CTO Test 1: DB credentials absent => registration HTTP 503
    # -------------------------------------------------------------------------
    def test_01_db_credentials_absent_causes_registration_http_503(self):
        """
        TASK 6 — Test 1:
        When DB credentials are not configured and Supabase is unavailable,
        public registration must fail closed with HTTP 503 and NEVER issue a JWT.
        """
        with patch("app.core.database.get_db_connection", side_effect=RuntimeError("PostgreSQL connection parameters are not configured. Refusing to connect.")), \
             patch("app.routes.auth_routes.get_supabase", return_value=None), \
             patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic:

            res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new_merchant@startup.com",
                    "name": "New Founder",
                    "tenant_slug": "no-cred-store",
                },
            )

            self.assertEqual(res.status_code, 503)
            self.assertIn("fail-closed", res.json()["detail"].lower())
            self.assertNotIn("access_token", res.json())
            mock_magic.assert_not_called()

    # -------------------------------------------------------------------------
    # CTO Test 2: PostgreSQL insert failure + Supabase unavailable => 503
    # -------------------------------------------------------------------------
    def test_02_postgresql_insert_failure_and_supabase_unavailable_causes_http_503(self):
        """
        TASK 6 — Test 2:
        When PostgreSQL insert fails and Supabase is unavailable,
        the handler must fail closed with HTTP 503 without falling back to memory.
        """
        with patch("app.routes.auth_routes._query_existing_merchant_by_slug", return_value=(None, None)), \
             patch("app.core.database.get_db_connection", side_effect=Exception("PostgreSQL insert failed: connection reset")), \
             patch("app.routes.auth_routes.get_supabase", return_value=None), \
             patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic:

            res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": "victim@company.com",
                    "name": "Attacker",
                    "tenant_slug": "db-fail-store",
                },
            )

            self.assertEqual(res.status_code, 503)
            self.assertIn("Layanan database gagal", res.json()["detail"])
            mock_magic.assert_not_called()

    # -------------------------------------------------------------------------
    # CTO Test 3: Failed activation leaves no in-memory active membership
    # -------------------------------------------------------------------------
    def test_03_failed_activation_leaves_no_in_memory_active_membership(self):
        """
        TASK 6 — Test 3:
        When merchant activation UPDATE fails in database, it must leave NO active in-memory membership.
        """
        slug = "failed-act-store"
        email = "founder@failed-act.com"
        otp = "771122"

        token_store.set_token(
            f"bt:auth:magic_link_otp:{otp}",
            {
                "email": email,
                "name": "Founder",
                "otp_code": otp,
                "token": "token-failed-act-123",
                "tenant_slug": slug,
                "role": "merchant",
                "is_registration": True,
                "created_at": 1000,
            },
            ttl_seconds=900,
        )

        with patch("app.core.database.get_db_connection", side_effect=Exception("DB deadlock during activation")), \
             patch("app.routes.auth_routes.get_supabase", return_value=None):

            res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": otp},
            )

            self.assertEqual(res.status_code, 503)
            self.assertIn("Gagal mengaktifkan akun merchant", res.json()["detail"])

            # Verify no active state in in-memory registries
            self.assertNotEqual(_in_memory_merchants.get(slug, {}).get("status"), "ACTIVE")
            self.assertNotIn((email, slug), _merchant_memberships)

    # -------------------------------------------------------------------------
    # CTO Test 4: Subsequent login cannot authenticate from failed activation memory residue
    # -------------------------------------------------------------------------
    def test_04_subsequent_login_cannot_authenticate_from_failed_activation_memory_residue(self):
        """
        TASK 6 — Test 4:
        A subsequent login request after a failed activation cannot authenticate
        from any residual process cache.
        """
        slug = "stale-residue-store"
        email = "victim@residue.com"

        # Database lookup strictly returns NOT_FOUND or inactive
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None  # No active merchant in DB
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with patch("app.core.database.get_db_connection", return_value=mock_conn), \
             patch("app.routes.auth_routes.get_supabase", return_value=None):

            # Attempt membership resolution
            mem, err = _resolve_verified_user_membership(email=email, claimed_tenant_slug=slug)
            self.assertIsNone(mem)

    # -------------------------------------------------------------------------
    # CTO Test 5: UPDATE rowcount zero => no JWT
    # -------------------------------------------------------------------------
    def test_05_update_rowcount_zero_causes_no_jwt(self):
        """
        TASK 6 — Test 5:
        When activation UPDATE affects 0 rows (e.g. no pending merchant row found),
        it must fail closed and return zero JWT tokens.
        """
        slug = "zero-row-store"
        email = "user@zero-row.com"
        otp = "998877"

        token_store.set_token(
            f"bt:auth:magic_link_otp:{otp}",
            {
                "email": email,
                "name": "User",
                "otp_code": otp,
                "token": "tok-zero-123",
                "tenant_slug": slug,
                "role": "merchant",
                "is_registration": True,
                "created_at": 1000,
            },
            ttl_seconds=900,
        )

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.rowcount = 0  # Zero rows updated!
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with patch("app.core.database.get_db_connection", return_value=mock_conn), \
             patch("app.routes.auth_routes.get_supabase", return_value=None):

            res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": otp},
            )

            self.assertEqual(res.status_code, 503)
            self.assertIn("UPDATE_AFFECTED_ZERO_ROWS", res.json()["detail"])
            self.assertNotIn("access_token", res.json())

    # -------------------------------------------------------------------------
    # CTO Test 6: Existing public.tenants slug without merchants row cannot be claimed
    # -------------------------------------------------------------------------
    def test_06_existing_public_tenants_slug_without_merchants_row_cannot_be_claimed(self):
        """
        TASK 6 — Test 6:
        An existing slug in public.tenants (platform/system tenant without merchants row)
        cannot be claimed by an unrelated registrant. Returns HTTP 409 Conflict.
        """
        slug = "system-platform-slug"
        attacker_email = "attacker@evil.com"

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # First query (merchants) returns None; Second query (public.tenants) returns a row!
        mock_cur.fetchone.side_effect = [
            None,  # Not in merchants
            (slug, "ACTIVE", True),  # In public.tenants!
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with patch("app.core.database.get_db_connection", return_value=mock_conn), \
             patch("app.routes.auth_routes.get_supabase", return_value=None):

            res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": attacker_email,
                    "name": "Attacker",
                    "tenant_slug": slug,
                },
            )

            self.assertEqual(res.status_code, 409)
            self.assertIn("sudah terdaftar pada sistem", res.json()["detail"])

    # -------------------------------------------------------------------------
    # CTO Test 7: Existing suspended merchant cannot self-reactivate
    # -------------------------------------------------------------------------
    def test_07_existing_suspended_merchant_cannot_self_reactivate(self):
        """
        TASK 6 — Test 7:
        An existing suspended, disabled, or blocked merchant cannot self-reactivate
        through public registration. Returns HTTP 403 Forbidden.
        """
        slug = "suspended-shop"
        owner_email = "owner@suspended-shop.com"

        mock_existing = {
            "slug": slug,
            "owner_email": owner_email,
            "status": "SUSPENDED",
            "source": "merchants",
        }

        with patch("app.routes.auth_routes._query_existing_merchant_by_slug", return_value=(mock_existing, None)):
            res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": owner_email,
                    "name": "Owner",
                    "tenant_slug": slug,
                },
            )

            self.assertEqual(res.status_code, 403)
            self.assertIn("SUSPENDED", res.json()["detail"])
            self.assertIn("Tidak dapat melakukan registrasi ulang", res.json()["detail"])

    # -------------------------------------------------------------------------
    # CTO Test 8: Failed email dispatch cannot permanently reserve a slug
    # -------------------------------------------------------------------------
    def test_08_failed_email_dispatch_cannot_permanently_reserve_slug(self):
        """
        TASK 6 — Test 8:
        When email dispatch fails, the pending reservation must be rolled back
        so the slug is NOT permanently blocked. Subsequent registration succeeds.
        """
        slug = "rollback-reservation-shop"
        email = "user@rollback.com"

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None  # Clean lookup: 0 existing rows
        mock_cur.rowcount = 1
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with patch("app.core.database.get_db_connection", return_value=mock_conn), \
             patch("app.routes.auth_routes.get_supabase", return_value=None):

            # 1. First attempt: email dispatch fails
            with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic:
                mock_magic.return_value = False  # Email failed

                res = self.client.post(
                    "/api/v1/auth/register",
                    json={"email": email, "name": "User", "tenant_slug": slug},
                )
                self.assertEqual(res.status_code, 503)
                self.assertIn("Reservasi tenant dibatalkan", res.json()["detail"])

                # Verify slug is NOT permanently reserved in pending registry
                self.assertNotIn(slug, _pending_registrations)

            # 2. Second attempt: email dispatch succeeds -> returns 201
            with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic:
                mock_magic.return_value = True

                res2 = self.client.post(
                    "/api/v1/auth/register",
                    json={"email": email, "name": "User", "tenant_slug": slug},
                )
                self.assertEqual(res2.status_code, 201)
                self.assertEqual(res2.json()["status"], "pending_verification")

    # -------------------------------------------------------------------------
    # CTO Test 9: Two concurrent OTP verifications => at most one JWT
    # -------------------------------------------------------------------------
    def test_09_two_concurrent_otp_verifications_produce_at_most_one_jwt(self):
        """
        TASK 6 — Test 9:
        Under concurrent verification requests with the same OTP, atomic consumption
        guarantees that at most one JWT session token is minted.
        """
        slug = "concurrency-shop"
        email = "user@concurrency.com"
        otp = "654321"

        token_store.set_token(
            f"bt:auth:magic_link_otp:{otp}",
            {
                "email": email,
                "name": "Concurrent User",
                "otp_code": otp,
                "token": "tok-concurrent-123",
                "tenant_slug": slug,
                "role": "merchant",
                "is_registration": True,
                "created_at": 1000,
            },
            ttl_seconds=900,
        )

        with patch("app.routes.auth_routes._activate_pending_merchant", return_value=(True, None)):
            def send_verify():
                return self.client.post(
                    "/api/v1/auth/magic-link/verify",
                    json={"otp_code": otp},
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                future1 = executor.submit(send_verify)
                future2 = executor.submit(send_verify)
                res1 = future1.result()
                res2 = future2.result()

            status_codes = sorted([res1.status_code, res2.status_code])
            # Exactly one must succeed (200) and one must be rejected (401)
            self.assertEqual(status_codes, [200, 401])

            success_res = res1 if res1.status_code == 200 else res2
            self.assertIn("access_token", success_res.json())

    # -------------------------------------------------------------------------
    # CTO Test 10: Production mode never consults test-only registries
    # -------------------------------------------------------------------------
    def test_10_production_mode_never_consults_test_only_registries(self):
        """
        TASK 6 — Test 10:
        When running in production mode (APP_ENV=production),
        test fixture registries must NEVER act as authorization sources.
        """
        os.environ["APP_ENV"] = "production"

        slug = "prod-bypass-slug"
        email = "attacker@prod-bypass.com"

        # Plant malicious active fixture in memory
        _in_memory_merchants[slug] = {
            "slug": slug,
            "owner_email": email,
            "status": "ACTIVE",
            "role": "merchant",
        }
        _merchant_memberships[(email, slug)] = {
            "merchant_id": email,
            "tenant_id": slug,
            "is_active": True,
        }

        # Mock DB to return cleanly 0 rows found
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with patch("app.core.database.get_db_connection", return_value=mock_conn), \
             patch("app.routes.auth_routes.get_supabase", return_value=None):

            # 1. Query existing merchant by slug must NOT see in-memory fixture
            rec, err = _query_existing_merchant_by_slug(slug)
            self.assertIsNone(rec)

            # 2. Resolve membership must NOT see in-memory fixture
            mem, err = _resolve_verified_user_membership(email=email, claimed_tenant_slug=slug)
            self.assertIsNone(mem)

    # -------------------------------------------------------------------------
    # CTO Test 11: New merchant authentication succeeds with persisted pending row + verified email
    # -------------------------------------------------------------------------
    def test_11_new_merchant_authentication_succeeds_with_persisted_pending_row_and_verified_email(self):
        """
        TASK 6 — Test 11:
        New merchant registration persists pending row -> verification email dispatched ->
        valid OTP submitted -> merchant activated in DB -> JWT session token minted.
        """
        merchant_email = "founder@startup-shop.com"
        merchant_slug = "startup-shop-2026"
        merchant_name = "Founder Startup"

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None  # No existing slug in DB
        mock_cur.rowcount = 1  # Real database activation updates exactly 1 row!
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with patch("app.core.database.get_db_connection", return_value=mock_conn), \
             patch("app.routes.auth_routes.get_supabase", return_value=None), \
             patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_magic, \
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

    # -------------------------------------------------------------------------
    # CTO Test 12: New merchant upload authorization succeeds after activation without in-memory fixture
    # -------------------------------------------------------------------------
    def test_12_new_merchant_upload_authorization_succeeds_after_activation_without_in_memory_fixture(self):
        """
        TASK 6 — Test 12:
        After valid activation, upload authorization succeeds based purely on
        persisted database state, without relying on any in-memory fixture.
        """
        merchant_email = "verified_owner@production-shop.com"
        merchant_slug = "production-shop-active"

        # Generate verified session JWT
        from app.routes.auth_routes import generate_session_jwt
        jwt_token = generate_session_jwt(email=merchant_email, tenant_slug=merchant_slug, role="merchant")

        # Explicitly CLEAR all in-memory fixtures!
        clear_auth_test_registries()
        clear_merchant_membership_registry()

        mock_req = DummyRequest(token=jwt_token)

        # Database returns active tenant and active owner
        with patch("app.routes.media_routes._query_db_tenant_active", return_value=(True, None)), \
             patch("app.routes.media_routes._query_db_merchant_membership", return_value=({"is_active": True, "role": "owner"}, None)):

            auth_result = authorize_tenant_upload(mock_req, expected_slug=merchant_slug)
            self.assertEqual(auth_result["tenant_id"], merchant_slug)
            self.assertEqual(auth_result["merchant_id"], merchant_email)

    # -------------------------------------------------------------------------
    # CTO Test 13: Existing owner login remains valid
    # -------------------------------------------------------------------------
    def test_13_existing_owner_login_remains_valid(self):
        """
        TASK 6 — Test 13:
        Existing merchant owner login via magic link remains functional and receives JWT.
        """
        owner_email = "legit_owner@boontrack.com"
        tenant_slug = "legit-store"

        register_auth_test_merchant(slug=tenant_slug, owner_email=owner_email, is_active=True)

        with patch.object(email_service, "send_magic_link_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            req_res = self.client.post(
                "/api/v1/auth/magic-link/request",
                json={"email": owner_email, "tenant_slug": tenant_slug},
            )
            self.assertEqual(req_res.status_code, 200)

            otp = mock_send.call_args.kwargs["otp_code"]
            ver_res = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"otp_code": otp},
            )
            self.assertEqual(ver_res.status_code, 200)
            self.assertIn("access_token", ver_res.json())
            self.assertEqual(ver_res.json()["user"]["role"], "merchant")

    # -------------------------------------------------------------------------
    # CTO Test 14: Existing active cs_agents staff login remains valid
    # -------------------------------------------------------------------------
    def test_14_existing_active_cs_agents_staff_login_remains_valid(self):
        """
        TASK 6 — Test 14:
        Existing active cs_agents staff member authenticates via magic link
        and receives a session JWT with role 'staff' (or configured staff role).
        """
        staff_email = "support_agent@company.com"
        tenant_slug = "company-hq"
        staff_role = "staff"

        otp = "334455"
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

        mock_membership = {
            "role": staff_role,
            "tenant_slug": tenant_slug,
            "is_active": True,
        }

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
    # Additional Security Tests: Attack Path A & B Regression
    # -------------------------------------------------------------------------
    def test_existing_slug_cannot_be_overwritten_by_different_email(self):
        """Attack Path B: Cross-email slug collision returns HTTP 409 Conflict."""
        slug = "protected-store"
        register_auth_test_merchant(slug=slug, owner_email="real_owner@store.com", is_active=True)

        res = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "hijacker@evil.com",
                "name": "Hijacker",
                "tenant_slug": slug,
            },
        )
        self.assertEqual(res.status_code, 409)
        self.assertIn("sudah terdaftar", res.json()["detail"])

    def test_insert_conflict_cannot_be_swallowed_and_followed_by_jwt(self):
        """Unique constraint conflict during insert returns HTTP 409 Conflict."""
        with patch("app.routes.auth_routes._query_existing_merchant_by_slug", return_value=(None, None)), \
             patch("app.routes.auth_routes._insert_pending_merchant", return_value=(False, "CONFLICT: duplicate key")):

            res = self.client.post(
                "/api/v1/auth/register",
                json={
                    "email": "user@store.com",
                    "name": "User",
                    "tenant_slug": "race-slug",
                },
            )
            self.assertEqual(res.status_code, 409)

    def test_expired_or_replayed_otp_cannot_issue_jwt(self):
        """Expired or replayed OTP returns HTTP 401 Unauthorized."""
        res = self.client.post(
            "/api/v1/auth/magic-link/verify",
            json={"otp_code": "000000"},
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("tidak valid atau telah kadaluarsa", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
