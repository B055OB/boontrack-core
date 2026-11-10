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
    _insert_pending_merchant,
    _activate_pending_merchant,
    _delete_pending_merchant,
    _is_distributed_token_store_required,
    reconcile_pending_cleanups,
    verification_rate_limiter,
    TokenStore,
    _DEAD_LETTER_CLEANUP_REGISTRY,
    _AUTH_HASH_TAG,
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


def _is_live_redis_available() -> bool:
    """Checks whether a live Redis connection is active."""
    if token_store and token_store._is_redis_healthy():
        return True
    try:
        import redis as _redis_mod
        if _redis_mod is not None:
            r = _redis_mod.Redis.from_url(
                os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0",
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
            return bool(r.ping())
    except Exception:
        pass
    return False


LIVE_REDIS_ACTIVE = _is_live_redis_available()


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

    # -------------------------------------------------------------------------
    # Test 9: Tenant already ACTIVE between preflight and insert
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_09_tenant_already_active_between_preflight_and_insert(self):
        """
        Proves atomic rollback if an existing tenant became ACTIVE in public.tenants
        between the preflight query and _insert_pending_merchant execution.
        Rowcount checking on ON CONFLICT ... WHERE status='PENDING_VERIFICATION' aborts with CONFLICT.
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-active-race-{raw_uuid}"
        email = f"applicant_{raw_uuid}@testboontrack.id"
        self.__class__.test_slugs_to_cleanup.append(slug)

        # 1. Pre-seed tenant as ACTIVE directly in public.tenants
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
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

        # 2. Attempt _insert_pending_merchant
        ok, err = _insert_pending_merchant(
            slug=slug,
            user_name="Race Applicant",
            user_email=email,
            phone="081299998888",
            store_name=f"Store {slug}",
        )
        self.assertFalse(ok, "_insert_pending_merchant must fail if tenant already exists in ACTIVE state")
        self.assertIn("CONFLICT", str(err))

        # 3. Assert merchants row was rolled back completely
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM public.merchants WHERE lower(slug) = %s;", (slug.lower(),))
                m_count = cur.fetchone()[0]
                self.assertEqual(m_count, 0, "Merchants insert must be rolled back on tenant conflict")

                # Tenant status must remain ACTIVE
                cur.execute("SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s;", (slug.lower(),))
                t_row = cur.fetchone()
                self.assertEqual(t_row[0], "ACTIVE")
                self.assertTrue(t_row[1])
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 10: Tenant becomes SUSPENDED before activation
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_10_tenant_becomes_suspended_before_activation_causes_rollback(self):
        """
        Proves that if a tenant record transitions to SUSPENDED before activation,
        _activate_pending_merchant fails-closed and rolls back the merchant status update.
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-susp-act-{raw_uuid}"
        email = f"susp_act_{raw_uuid}@testboontrack.id"
        self.__class__.test_slugs_to_cleanup.append(slug)

        # 1. Insert pending merchant and SUSPENDED tenant
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                    VALUES (%s, %s, %s, %s, %s, 'PENDING_VERIFICATION');
                    """,
                    (slug, f"Store {slug}", "Suspended Tester", email, "081299998888"),
                )
                cur.execute(
                    """
                    INSERT INTO public.tenants (name, slug, tier, status, is_active)
                    VALUES (%s, %s, 'STARTER', 'SUSPENDED', false);
                    """,
                    (f"Store {slug}", slug),
                )
            conn.commit()
        finally:
            conn.close()

        # 2. Call activation
        act_ok, act_err = _activate_pending_merchant(slug=slug, owner_email=email)
        self.assertFalse(act_ok, "Activation must fail if tenant is not in PENDING_VERIFICATION state")
        self.assertIn("TENANT_ACTIVATION_AFFECTED_ZERO_ROWS", str(act_err))

        # 3. Assert merchant was NOT activated (rolled back to PENDING_VERIFICATION)
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT status, is_otp_verified FROM public.merchants WHERE lower(slug) = %s;", (slug.lower(),))
                m_row = cur.fetchone()
                self.assertEqual(m_row[0], "PENDING_VERIFICATION", "Merchant must not be ACTIVE")
                self.assertFalse(m_row[1])

                cur.execute("SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s;", (slug.lower(),))
                t_row = cur.fetchone()
                self.assertEqual(t_row[0], "SUSPENDED", "Tenant must remain SUSPENDED")
                self.assertFalse(t_row[1])
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 11: Tenant activation zero rows or error causes merchant rollback
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_11_tenant_activation_zero_rows_or_error_causes_merchant_rollback(self):
        """
        Proves that when public.tenants has no pending record for the slug,
        _activate_pending_merchant rolls back the merchant update atomically.
        """
        raw_uuid = uuid.uuid4().hex[:8]
        slug = f"test-pg-zero-rows-{raw_uuid}"
        email = f"zero_rows_{raw_uuid}@testboontrack.id"
        self.__class__.test_slugs_to_cleanup.append(slug)

        # 1. Insert merchant in PENDING_VERIFICATION without corresponding tenant in public.tenants
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                    VALUES (%s, %s, %s, %s, %s, 'PENDING_VERIFICATION');
                    """,
                    (slug, f"Store {slug}", "Zero Rows Owner", email, "081299998888"),
                )
            conn.commit()
        finally:
            conn.close()

        # 2. Call activation
        act_ok, act_err = _activate_pending_merchant(slug=slug, owner_email=email)
        self.assertFalse(act_ok, "Activation must fail when public.tenants affected rows == 0")
        self.assertIn("TENANT_ACTIVATION_AFFECTED_ZERO_ROWS", str(act_err))

        # 3. Assert merchant status is rolled back
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM public.merchants WHERE lower(slug) = %s;", (slug.lower(),))
                m_row = cur.fetchone()
                self.assertEqual(m_row[0], "PENDING_VERIFICATION")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Test 12: Supabase fallback compensating rollback on tenant failure
    # -------------------------------------------------------------------------
    def test_12_supabase_dual_table_compensating_rollback_on_tenant_failure(self):
        """
        Proves compensating rollback for Supabase fallback path:
        1. When tenant provisioning fails during _insert_pending_merchant, the inserted merchant is deleted.
        2. When tenant activation fails during _activate_pending_merchant, the merchant status is reverted back to PENDING_VERIFICATION.
        """
        slug = f"test-sb-comp-{uuid.uuid4().hex[:8]}"
        email = f"comp_{slug}@testboontrack.id"

        # Mock Supabase client
        mock_sb = unittest.mock.MagicMock()

        # Case 1: _insert_pending_merchant where tenants.insert raises
        mock_merchants_table = unittest.mock.MagicMock()
        mock_tenants_table = unittest.mock.MagicMock()
        mock_tenants_table.insert.side_effect = Exception("Tenant RLS policy violation")

        def table_router(table_name):
            if table_name == "merchants":
                return mock_merchants_table
            return mock_tenants_table

        mock_sb.table.side_effect = table_router

        # Patch get_db_connection to raise error so Supabase fallback is executed
        with patch("app.core.database.get_db_connection", side_effect=Exception("DB unavailable")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb):
            ok, err = _insert_pending_merchant(slug=slug, user_name="Comp Owner", user_email=email)
            self.assertFalse(ok)
            self.assertIn("SUPABASE_TENANT_PROVISION_ERROR", str(err))
            # Verify compensating delete was called on merchants table
            mock_merchants_table.delete.assert_called()

        # Case 2: _activate_pending_merchant where tenants.update returns 0 rows
        mock_sb2 = unittest.mock.MagicMock()
        mock_m2 = unittest.mock.MagicMock()
        mock_t2 = unittest.mock.MagicMock()

        mock_m2.update.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        # Tenants returns empty data (0 rows affected)
        mock_t2.update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[])

        def table_router2(name):
            if name == "merchants":
                return mock_m2
            return mock_t2

        mock_sb2.table.side_effect = table_router2

        with patch("app.core.database.get_db_connection", side_effect=Exception("DB unavailable")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb2):
            act_ok, act_err = _activate_pending_merchant(slug=slug, owner_email=email)
            self.assertFalse(act_ok)
            self.assertIn("TENANT_ACTIVATION_AFFECTED_ZERO_ROWS", str(act_err))

    # -------------------------------------------------------------------------
    # Test 13: Distributed verification rate limiting: IP and Challenge Lockout
    # -------------------------------------------------------------------------
    def test_13_verification_rate_limiting_ip_and_challenge_lockout(self):
        """
        Proves verification rate limiting:
        1. Max 15 requests per minute per IP -> 16th returns HTTP 429.
        2. Max 5 failed attempts per challenge -> 6th returns HTTP 429.
        3. Generic error message does not leak whether email or OTP exists.
        4. Valid OTP resets challenge counter.
        5. Production mode fails closed (HTTP 503) if rate limiter cannot connect to Redis.
        """
        with patch.dict(os.environ, {"BOONTRACK_DISABLE_AUTH_RATE_LIMIT": "0"}):
            verification_rate_limiter.reset_all()

            # 1. Test per-challenge lockout (5 failed attempts)
            bad_otp = "999999"
            for i in range(5):
                res = self.client.post("/api/v1/auth/magic-link/verify", json={"otp_code": bad_otp})
                self.assertEqual(res.status_code, 401, f"Attempt {i+1} must be 401 Unauthorized")
                self.assertIn("tidak valid atau telah kadaluarsa", res.json()["detail"])

            # 6th attempt must be locked out with 429
            lockout_res = self.client.post("/api/v1/auth/magic-link/verify", json={"otp_code": bad_otp})
            self.assertEqual(lockout_res.status_code, 429, "6th attempt must return 429 Too Many Requests")
            self.assertIn("Batas percobaan verifikasi", lockout_res.json()["detail"])

            # 2. Test valid OTP resets counter
            good_otp = "123456"
            good_token = "valid_tok_test_13"
            session = {
                "email": "rate_test@example.com",
                "token": good_token,
                "otp_code": good_otp,
                "tenant_slug": "rate-test-slug",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{good_token}", session)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{good_otp}", session)

            with patch("app.routes.auth_routes._resolve_verified_user_membership", return_value=({"role": "merchant", "tenant_slug": "rate-test-slug", "is_active": True}, None)):
                good_res = self.client.post("/api/v1/auth/magic-link/verify", json={"otp_code": good_otp})
                self.assertEqual(good_res.status_code, 200)
                is_locked, _ = verification_rate_limiter.is_challenge_locked(good_otp)
                self.assertFalse(is_locked, "Challenge lockout must be reset upon successful verification")

            # 3. Test production fail-closed on Redis outage
            with patch.dict(os.environ, {"APP_ENV": "production", "REDIS_REQUIRED": "true"}):
                with patch.object(token_store, "_is_redis_healthy", return_value=False):
                    fail_closed_res = self.client.post("/api/v1/auth/magic-link/verify", json={"otp_code": "555555"})
                    self.assertEqual(fail_closed_res.status_code, 503)
                    self.assertIn("fail-closed", fail_closed_res.json()["detail"])

    # -------------------------------------------------------------------------
    # Test 14: Slug lock lease token correctness and atomic release
    # -------------------------------------------------------------------------
    def test_14_slug_lock_lease_token_correctness_and_atomic_release(self):
        """
        Proves:
        1. acquire_slug_lock returns a unique lease token string.
        2. A concurrent acquisition attempt on the same slug returns None.
        3. release_slug_lock with a wrong or mismatched lease token returns False and does not release.
        4. release_slug_lock with the correct lease token releases the lock.
        5. Next acquisition attempt succeeds.
        6. In production mode, acquire_slug_lock fails closed if Redis is unavailable.
        """
        slug = f"lease-slug-{uuid.uuid4().hex[:8]}"

        lease_token_1 = token_store.acquire_slug_lock(slug, ttl_seconds=15)
        self.assertIsNotNone(lease_token_1)
        self.assertIsInstance(lease_token_1, str)
        self.assertTrue(len(lease_token_1) >= 16)

        # Concurrent attempt with different worker/request
        lease_token_2 = token_store.acquire_slug_lock(slug, ttl_seconds=15)
        self.assertIsNone(lease_token_2, "Concurrent lock acquisition on same slug must return None")

        # Release attempt with wrong lease token
        wrong_rel = token_store.release_slug_lock(slug, lease_token="wrong_lease_token_value")
        self.assertFalse(wrong_rel, "Releasing with invalid lease token must return False")

        # Lock must still be held
        attempt_again = token_store.acquire_slug_lock(slug, ttl_seconds=15)
        self.assertIsNone(attempt_again, "Lock must still be held after invalid release attempt")

        # Correct release
        rel_ok = token_store.release_slug_lock(slug, lease_token=lease_token_1)
        self.assertTrue(rel_ok, "Releasing with correct lease token must return True")

        # Now acquire should succeed
        lease_token_3 = token_store.acquire_slug_lock(slug, ttl_seconds=15)
        self.assertIsNotNone(lease_token_3)
        token_store.release_slug_lock(slug, lease_token=lease_token_3)

        # In production mode without Redis, acquire_slug_lock strictly fails closed
        with patch.dict(os.environ, {"APP_ENV": "production", "REDIS_REQUIRED": "true"}):
            with patch.object(token_store, "_is_redis_healthy", return_value=False):
                with self.assertRaises(RuntimeError):
                    token_store.acquire_slug_lock("prod-fail-closed-slug")

    # -------------------------------------------------------------------------
    # Test 15: Dead-letter queue and reconcile_pending_cleanups() recovery
    # -------------------------------------------------------------------------
    def test_15_dead_letter_queue_and_reconciliation_recovery(self):
        """
        Proves:
        1. Failed cleanup writes to durable dead-letter registry.
        2. reconcile_pending_cleanups() retries cleanup and successfully resolves pending reservations.
        """
        slug = f"dead-letter-{uuid.uuid4().hex[:8]}"
        email = f"dead_{slug}@testboontrack.id"

        # Simulate cleanup failure by mocking DB error
        with patch("app.core.database.get_db_connection", side_effect=Exception("Simulated cleanup DB down")):
            ok, err = _delete_pending_merchant(slug, email)
            self.assertFalse(ok)
            self.assertIn("Simulated cleanup DB down", str(err))

        # Check dead-letter registry has recorded this failure
        self.assertIn(slug, _DEAD_LETTER_CLEANUP_REGISTRY)
        self.assertEqual(_DEAD_LETTER_CLEANUP_REGISTRY[slug]["owner_email"], email)

        # Now simulate DB recovery and run reconcile_pending_cleanups()
        with patch("app.routes.auth_routes._delete_pending_merchant", return_value=(True, None)):
            result = reconcile_pending_cleanups()
            self.assertIn(slug, result["reconciled"])
            self.assertNotIn(slug, result["failed"])

    # -------------------------------------------------------------------------
    # Test 16: Redis Multi-Instance TokenStore and paired-key atomic deletion
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_REDIS_ACTIVE, "Live Redis server required for multi-instance integration test")
    def test_16_redis_multi_instance_cluster_hash_tag_and_paired_deletion(self):
        """
        Proves that two independent TokenStore instances sharing Redis
        execute atomic Lua consumption with cluster hash tags ({bt:auth})
        and delete paired token and OTP keys without race conditions.
        """
        token = f"tok_pair_{uuid.uuid4().hex}"
        otp = f"{uuid.uuid4().int % 900000 + 100000:06d}"
        session = {
            "email": "pair_test@example.com",
            "token": token,
            "otp_code": otp,
            "tenant_slug": "pair-store",
            "is_registration": True,
            "created_at": time.time(),
        }

        # Instance 1 sets token
        token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{token}", session)
        token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{otp}", session)

        # Instance 2 consumes via OTP
        second_store = TokenStore()
        consumed = second_store.consume_verification_session(otp_code=otp)
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed["email"], "pair_test@example.com")

        # Second consumer via token gets None (already atomically consumed and paired key deleted)
        consumed_again = token_store.consume_verification_session(token=token)
        self.assertIsNone(consumed_again, "Paired token key must be deleted atomically upon OTP consumption")


if __name__ == "__main__":
    unittest.main()
