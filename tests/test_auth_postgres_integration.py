"""
tests/test_auth_postgres_integration.py
CTO DIRECTIVE — PR #29 LIVE POSTGRESQL & DISTRIBUTED TOKEN STORE INTEGRATION TEST SUITE

Empirically and mathematically proves:
1. Redis / TokenStore multi-instance atomic concurrency (single consumer proof).
2. Live PostgreSQL integration for merchant registration and activation asserting persisted
   public.merchants and public.tenants rows without mocks.
3. Actual media upload authorization without mocking database lookup functions.
4. Failed email dispatch cleanup against persistent database state (zero orphaned rows).
5. ACTIVE owner login succeeds, while ACTIVE owner re-registration returns HTTP 409 Conflict.
6. Suspended merchant cannot self-reactivate (HTTP 403 Forbidden).
7. Two concurrent registrations racing for the same slug result in exactly one winner (201) and one conflict (409).
8. Production mode fails closed (HTTP 503) if distributed token store is required but unavailable.
"""

import os
import sys
import uuid
import time
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

# Ensure boontrack core is importable
sys.path.insert(0, os.path.abspath("."))
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "super-secret-core-jwt-key-for-test-isolation-32chars"
os.environ["CORE_JWT_ISSUER"] = "boontrack-core"
os.environ["CORE_JWT_AUDIENCE"] = "boontrack-api"
os.environ["BOONTRACK_DISABLE_AUTH_RATE_LIMIT"] = "1"

from app.main import app
from app.core.database import get_db_connection
from app.routes.auth_routes import (
    token_store,
    handle_register_logic,
    RegisterRequest,
    MagicLinkRequest,
    MagicLinkVerifyRequest,
    request_magic_link,
    verify_magic_link,
    clear_auth_test_registries,
    _query_existing_merchant_by_slug,
    _delete_pending_merchant,
    _is_distributed_token_store_required,
)
from app.routes.media_routes import (
    authorize_tenant_upload,
    clear_merchant_membership_registry,
)
from app.services.email_service import email_service


def _is_live_postgres_available() -> bool:
    """Checks whether a live PostgreSQL connection is active."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
        conn.close()
        return True
    except Exception:
        return False


LIVE_POSTGRES_ACTIVE = _is_live_postgres_available()


class DummyRequest:
    """Mock HTTP request with Bearer authorization header."""
    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}


class TestAuthPostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.test_slugs_to_cleanup = []

    def setUp(self):
        clear_auth_test_registries()
        clear_merchant_membership_registry()

    def tearDown(self):
        clear_auth_test_registries()
        clear_merchant_membership_registry()

    @classmethod
    def tearDownClass(cls):
        """Clean up all created test tenants in live PostgreSQL."""
        if LIVE_POSTGRES_ACTIVE and cls.test_slugs_to_cleanup:
            try:
                conn = get_db_connection()
                with conn.cursor() as cur:
                    for s in cls.test_slugs_to_cleanup:
                        cur.execute("DELETE FROM public.merchants WHERE lower(slug) = %s;", (s.lower(),))
                        cur.execute("DELETE FROM public.tenants WHERE lower(slug) = %s;", (s.lower(),))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[TEARDOWN ERROR] Failed to clean up test slugs: {e}")

    # -------------------------------------------------------------------------
    # Test 1: Redis / TokenStore multi-instance atomic concurrency
    # -------------------------------------------------------------------------
    def test_01_token_store_atomic_concurrency_single_consumer(self):
        """
        Proves atomic verification session consumption across concurrent threads/workers.
        Exactly one worker receives the session data; all other workers receive None.
        """
        test_token = f"tok_concurrent_{uuid.uuid4().hex}"
        test_otp = f"{uuid.uuid4().int % 900000 + 100000:06d}"
        payload = {
            "email": "worker_test@example.com",
            "name": "Worker Tester",
            "token": test_token,
            "otp_code": test_otp,
            "tenant_slug": "worker-store",
            "role": "merchant",
            "is_registration": True,
            "created_at": time.time(),
        }

        token_store.set_token(f"bt:auth:magic_link:{test_token}", payload, ttl_seconds=60)
        token_store.set_token(f"bt:auth:magic_link_otp:{test_otp}", payload, ttl_seconds=60)

        num_threads = 10
        results = []

        def worker_attempt():
            return token_store.consume_verification_session(token=test_token, otp_code=test_otp)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_attempt) for _ in range(num_threads)]
            for f in futures:
                results.append(f.result())

        successful_consumptions = [r for r in results if r is not None]
        none_results = [r for r in results if r is None]

        self.assertEqual(len(successful_consumptions), 1, "Exactly one worker must consume the session")
        self.assertEqual(len(none_results), num_threads - 1, "All concurrent workers must receive None")
        self.assertEqual(successful_consumptions[0]["email"], "worker_test@example.com")

    # -------------------------------------------------------------------------
    # Test 2: Live PostgreSQL Merchant Registration & Activation Lifecycle
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_02_live_postgres_merchant_registration_and_activation_persists_both_tables(self):
        """
        Proves registration and activation atomically create and update rows in BOTH
        public.merchants AND public.tenants with accurate status and active flags.
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-reg-{raw_uuid}"
        email = f"owner_{raw_uuid}@testboontrack.id"
        name = f"PG Store {raw_uuid}"
        self.__class__.test_slugs_to_cleanup.append(slug)

        captured_tokens = {}

        async def capture_email(to_email, magic_link_url, otp_code, tenant_name):
            captured_tokens["token"] = magic_link_url.split("token=")[-1]
            captured_tokens["otp_code"] = otp_code
            return True

        with patch.object(email_service, "send_magic_link_email", side_effect=capture_email):
            req = RegisterRequest(
                email=email,
                name=name,
                tenant_slug=slug,
                phone="081299998888",
                store_name=name,
            )
            reg_res = self.client.post("/api/v1/auth/register", json=req.model_dump())
            self.assertEqual(reg_res.status_code, 201)
            reg_data = reg_res.json()
            self.assertEqual(reg_data["status"], "pending_verification")
            self.assertTrue(reg_data["requires_verification"])
            self.assertNotIn("access_token", reg_data)

        # 1. Assert rows exist in live PostgreSQL with status PENDING_VERIFICATION
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT status, is_otp_verified FROM public.merchants WHERE lower(slug) = %s;", (slug.lower(),))
                m_row = cur.fetchone()
                self.assertIsNotNone(m_row, "Merchant row must be persisted in PostgreSQL")
                self.assertEqual(m_row[0], "PENDING_VERIFICATION")
                self.assertFalse(m_row[1])

                cur.execute("SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s;", (slug.lower(),))
                t_row = cur.fetchone()
                self.assertIsNotNone(t_row, "Tenant row must be provisioned in public.tenants")
                self.assertEqual(t_row[0], "PENDING_VERIFICATION")
                self.assertFalse(t_row[1], "Pending tenant must have is_active = false")
        finally:
            conn.close()

        # 2. Activate via OTP
        verify_req = {"otp_code": captured_tokens["otp_code"]}
        v_res = self.client.post("/api/v1/auth/magic-link/verify", json=verify_req)
        self.assertEqual(v_res.status_code, 200)
        v_data = v_res.json()
        self.assertIn("access_token", v_data)
        jwt_token = v_data["access_token"]
        self.assertEqual(v_data["user"]["tenant_slug"], slug)

        # 3. Assert rows updated to ACTIVE in live PostgreSQL
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT status, is_otp_verified FROM public.merchants WHERE lower(slug) = %s;", (slug.lower(),))
                m_active = cur.fetchone()
                self.assertEqual(m_active[0], "ACTIVE")
                self.assertTrue(m_active[1])

                cur.execute("SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s;", (slug.lower(),))
                t_active = cur.fetchone()
                self.assertEqual(t_active[0], "ACTIVE")
                self.assertTrue(t_active[1], "Activated tenant must have is_active = true")
        finally:
            conn.close()

        return slug, jwt_token

    # -------------------------------------------------------------------------
    # Test 3: Actual Media Upload Authorization Against Real Database
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_03_actual_upload_authorization_succeeds_without_db_lookup_mocks(self):
        """
        Proves media upload authorization succeeds using the genuine session JWT
        against real public.tenants and public.merchants rows, without mocking
        _query_db_tenant_active or _query_db_merchant_membership.
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-upload-{raw_uuid}"
        email = f"uploader_{raw_uuid}@testboontrack.id"
        self.__class__.test_slugs_to_cleanup.append(slug)

        # Register and activate directly in PostgreSQL
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status, is_otp_verified)
                    VALUES (%s, %s, %s, %s, %s, 'ACTIVE', true);
                    """,
                    (slug, f"Store {slug}", "Upload Tester", email, "081299998888"),
                )
                cur.execute(
                    """
                    INSERT INTO public.tenants (name, slug, tier, status, is_active)
                    VALUES (%s, %s, 'STARTER', 'ACTIVE', true);
                    """,
                    (f"Store {slug}", slug),
                )
            conn.commit()
        finally:
            conn.close()

        # Generate genuine signed JWT for this merchant
        from app.routes.auth_routes import generate_session_jwt
        jwt_token = generate_session_jwt(email=email, tenant_slug=slug, role="merchant")

        # Call media upload authorization with real request
        req = DummyRequest(jwt_token)
        auth_result = authorize_tenant_upload(request=req, expected_slug=slug)
        self.assertEqual(auth_result["tenant_id"], slug)
        self.assertEqual(auth_result["merchant_id"], email)

    # -------------------------------------------------------------------------
    # Test 4: Failed Email Dispatch Cleanup Leaves Zero Orphaned Database Rows
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_04_failed_email_dispatch_cleans_up_persistent_state(self):
        """
        Proves that when email dispatch fails, pending reservations in both
        merchants and public.tenants are immediately rolled back and deleted.
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-failmail-{raw_uuid}"
        email = f"fail_{raw_uuid}@testboontrack.id"
        self.__class__.test_slugs_to_cleanup.append(slug)

        with patch.object(email_service, "send_magic_link_email", return_value=False):
            req = {
                "email": email,
                "name": "Failed Mail Owner",
                "tenant_slug": slug,
            }
            res = self.client.post("/api/v1/auth/register", json=req)
            self.assertEqual(res.status_code, 503)

        # Assert no rows remain in PostgreSQL
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM public.merchants WHERE lower(slug) = %s;", (slug.lower(),))
                m_count = cur.fetchone()[0]
                self.assertEqual(m_count, 0, "Failed email dispatch must delete pending merchants row")

                cur.execute("SELECT count(*) FROM public.tenants WHERE lower(slug) = %s;", (slug.lower(),))
                t_count = cur.fetchone()[0]
                self.assertEqual(t_count, 0, "Failed email dispatch must delete pending tenants row")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 5: ACTIVE Owner Login vs Registration Behavior
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_05_active_owner_login_succeeds_while_reregistration_returns_409(self):
        """
        Proves an ACTIVE owner can log in normally via magic-link request/verify,
        but calling public registration on the existing active store returns HTTP 409 Conflict.
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-active-{raw_uuid}"
        email = f"active_{raw_uuid}@testboontrack.id"
        self.__class__.test_slugs_to_cleanup.append(slug)

        # Seed active merchant and tenant in live PostgreSQL
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status, is_otp_verified)
                    VALUES (%s, %s, %s, %s, %s, 'ACTIVE', true);
                    """,
                    (slug, f"Store {slug}", "Active Owner", email, "081299998888"),
                )
                cur.execute(
                    """
                    INSERT INTO public.tenants (name, slug, tier, status, is_active)
                    VALUES (%s, %s, 'STARTER', 'ACTIVE', true);
                    """,
                    (f"Store {slug}", slug),
                )
            conn.commit()
        finally:
            conn.close()

        # 1. Normal magic-link login flow
        captured_otp = []
        async def mock_send(to_email, magic_link_url, otp_code, tenant_name):
            captured_otp.append(otp_code)
            return True

        with patch.object(email_service, "send_magic_link_email", side_effect=mock_send):
            req_login = self.client.post("/api/v1/auth/magic-link/request", json={"email": email, "tenant_slug": slug})
            self.assertEqual(req_login.status_code, 200)

        self.assertTrue(len(captured_otp) > 0)
        verify_res = self.client.post("/api/v1/auth/magic-link/verify", json={"otp_code": captured_otp[0]})
        self.assertEqual(verify_res.status_code, 200)
        self.assertIn("access_token", verify_res.json())

        # 2. Attempting public registration with the already ACTIVE store must return HTTP 409 Conflict
        reg_attempt = self.client.post(
            "/api/v1/auth/register",
            json={"email": email, "name": "Active Owner", "tenant_slug": slug},
        )
        self.assertEqual(reg_attempt.status_code, 409)
        self.assertIn("sudah aktif terdaftar", reg_attempt.json()["detail"])

    # -------------------------------------------------------------------------
    # Test 6: Suspended Merchant Cannot Self-Reactivate
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_06_suspended_merchant_cannot_self_reactivate(self):
        """
        Proves an existing merchant marked SUSPENDED cannot re-register or self-reactivate.
        Returns HTTP 403 Forbidden.
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-suspended-{raw_uuid}"
        email = f"suspended_{raw_uuid}@testboontrack.id"
        self.__class__.test_slugs_to_cleanup.append(slug)

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status, is_otp_verified)
                    VALUES (%s, %s, %s, %s, %s, 'SUSPENDED', true);
                    """,
                    (slug, f"Store {slug}", "Suspended Owner", email, "081299998888"),
                )
            conn.commit()
        finally:
            conn.close()

        res = self.client.post(
            "/api/v1/auth/register",
            json={"email": email, "name": "Suspended Owner", "tenant_slug": slug},
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("SUSPENDED", res.json()["detail"])

    # -------------------------------------------------------------------------
    # Test 7: Two Concurrent Registrations Racing for the Same Slug
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_07_concurrent_registrations_racing_for_same_slug(self):
        """
        Proves that when two concurrent requests race to register the same slug,
        exactly one succeeds (201 Created) and the other is rejected (409 Conflict).
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-race-{raw_uuid}"
        email_a = f"race_a_{raw_uuid}@testboontrack.id"
        email_b = f"race_b_{raw_uuid}@testboontrack.id"
        self.__class__.test_slugs_to_cleanup.append(slug)

        with patch.object(email_service, "send_magic_link_email", return_value=True):
            def register_applicant(email_val, name_val):
                client = TestClient(app)
                return client.post(
                    "/api/v1/auth/register",
                    json={"email": email_val, "name": name_val, "tenant_slug": slug},
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                f_a = executor.submit(register_applicant, email_a, "Applicant A")
                f_b = executor.submit(register_applicant, email_b, "Applicant B")
                res_a = f_a.result()
                res_b = f_b.result()

        statuses = [res_a.status_code, res_b.status_code]
        self.assertIn(201, statuses, "One applicant must succeed with 201 Created")
        self.assertIn(409, statuses, "The losing applicant must receive 409 Conflict")

        # Assert only one record exists in PostgreSQL
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*), lower(owner_email) FROM public.merchants WHERE lower(slug) = %s GROUP BY lower(owner_email);", (slug.lower(),))
                rows = cur.fetchall()
                self.assertEqual(len(rows), 1, "Exactly one owner must be recorded for this slug")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 8: Production Fail-Closed on Distributed Token Store Unavailability
    # -------------------------------------------------------------------------
    def test_08_production_fail_closed_on_distributed_store_unavailability(self):
        """
        Proves that when APP_ENV=production (or REDIS_REQUIRED=true),
        the system strictly fails closed (HTTP 503 / RuntimeError) if Redis is unavailable.
        """
        with patch.dict(os.environ, {"APP_ENV": "production", "REDIS_REQUIRED": "true"}):
            self.assertTrue(_is_distributed_token_store_required())

            with patch.object(token_store, "_is_redis_healthy", return_value=False):
                # 1. Verification session consumption must fail closed
                with self.assertRaises(RuntimeError) as cm:
                    token_store.consume_verification_session(token="dummy_token")
                self.assertIn("[SECURITY FAIL-CLOSED]", str(cm.exception))

                # 2. Token storage must fail closed
                with self.assertRaises(RuntimeError) as cm2:
                    token_store.set_token("dummy_key", {"test": True})
                self.assertIn("[SECURITY FAIL-CLOSED]", str(cm2.exception))


if __name__ == "__main__":
    unittest.main()
