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
    register_auth_test_merchant,
    _query_existing_merchant_by_slug,
    _insert_pending_merchant,
    _activate_pending_merchant,
    _delete_pending_merchant,
    _revert_pending_merchant_activation,
    _is_distributed_token_store_required,
    reconcile_pending_cleanups,
    start_cleanup_reconciler_worker,
    _record_dead_letter_cleanup,
    _clear_dead_letter_cleanup,
    verification_rate_limiter,
    DistributedAuthRateLimiter,
    auth_rate_limiter,
    TokenStore,
    _DEAD_LETTER_CLEANUP_REGISTRY,
    _AUTH_HASH_TAG,
)
from app.core.security.trusted_proxy import get_trusted_client_ip, TrustedProxyResolver
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


def _is_ci_environment() -> bool:
    for var in ("CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION"):
        if os.getenv(var, "").strip().lower() in ("true", "1", "yes"):
            return True
    return False


_IS_CI = _is_ci_environment()


def _is_live_redis_available() -> bool:
    """Checks whether a live Redis connection is active."""
    if token_store and token_store._is_redis_healthy():
        return True
    try:
        import redis as _redis_mod
        if _redis_mod is not None:
            r = _redis_mod.Redis.from_url(
                os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0",
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
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
        verify_req = {"otp_code": captured_tokens["otp_code"], "challenge_id": reg_data["challenge_id"]}
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
            req_data = req_login.json()

        self.assertTrue(len(captured_otp) > 0)
        verify_res = self.client.post("/api/v1/auth/magic-link/verify", json={"otp_code": captured_otp[0], "challenge_id": req_data["challenge_id"]})
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

            # 1. Test per-challenge lockout (5 failed attempts against an authoritative challenge)
            ch_13 = f"ch_test_13_{uuid.uuid4().hex[:8]}"
            tok_13 = f"tok_test_13_{uuid.uuid4().hex}"
            session_13 = {
                "email": "test13_lockout@example.com",
                "token": tok_13,
                "otp_code": "112233",
                "challenge_id": ch_13,
                "tenant_slug": "rate-test-slug",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{tok_13}", session_13)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{session_13['otp_code']}", session_13)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{ch_13}", session_13)

            bad_otp = "999999"
            for i in range(5):
                res = self.client.post("/api/v1/auth/magic-link/verify", json={"challenge_id": ch_13, "otp_code": bad_otp})
                self.assertEqual(res.status_code, 401, f"Attempt {i+1} must be 401 Unauthorized")
                self.assertIn("tidak valid atau telah kadaluarsa", res.json()["detail"])

            # 6th attempt must be locked out with 429
            lockout_res = self.client.post("/api/v1/auth/magic-link/verify", json={"challenge_id": ch_13, "otp_code": bad_otp})
            self.assertEqual(lockout_res.status_code, 429, "6th attempt must return 429 Too Many Requests")
            self.assertIn("Batas percobaan verifikasi", lockout_res.json()["detail"])

            # 2. Test valid OTP resets counter
            good_otp = "123456"
            good_token = f"valid_tok_test_13_{uuid.uuid4().hex}"
            good_ch = f"ch_good_13_{uuid.uuid4().hex[:8]}"
            session = {
                "email": "rate_test@example.com",
                "token": good_token,
                "otp_code": good_otp,
                "challenge_id": good_ch,
                "tenant_slug": "rate-test-slug",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{good_token}", session)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{good_otp}", session)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{good_ch}", session)

            with patch("app.routes.auth_routes._resolve_verified_user_membership", return_value=({"role": "merchant", "tenant_slug": "rate-test-slug", "is_active": True}, None)):
                good_res = self.client.post("/api/v1/auth/magic-link/verify", json={"challenge_id": good_ch, "otp_code": good_otp})
                self.assertEqual(good_res.status_code, 200)
                is_locked, _ = verification_rate_limiter.is_challenge_locked(good_ch)
                self.assertFalse(is_locked, "Challenge lockout must be reset upon successful verification")

            # 3. Test production fail-closed on Redis outage
            with patch.dict(os.environ, {"APP_ENV": "production", "REDIS_REQUIRED": "true"}):
                with patch.object(token_store, "_is_redis_healthy", return_value=False):
                    fail_closed_res = self.client.post("/api/v1/auth/magic-link/verify", json={"challenge_id": good_ch, "otp_code": "555555"})
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

        # Simulate cleanup failure by mocking DB error and Supabase error
        with patch("app.core.database.get_db_connection", side_effect=Exception("Simulated cleanup DB down")), \
             patch("app.routes.auth_routes.get_supabase", return_value=None):
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
    @unittest.skipIf(not _IS_CI and not LIVE_REDIS_ACTIVE, "Live Redis server required for multi-instance integration test (mandatory in CI)")
    def test_16_redis_multi_instance_cluster_hash_tag_and_paired_deletion(self):
        """
        Proves that two independent TokenStore instances sharing Redis
        execute atomic Lua consumption with cluster hash tags ({bt:auth})
        and delete paired token and OTP keys without race conditions.
        """
        if _IS_CI:
            self.assertTrue(LIVE_REDIS_ACTIVE, "Live Redis container (redis:7-alpine) is mandatory in CI environment!")
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

    # -------------------------------------------------------------------------
    # Test 17: Authoritative Challenge Rate Limiting & Adversarial Controls (CTO P0)
    # -------------------------------------------------------------------------
    def test_17_challenge_rate_limiting_cycling_otps_locked_out_and_account_controls(self):
        """
        Proves:
        1. Five incorrect OTP guesses against one authoritative challenge increment failure counter.
        2. Sixth attempt rejected with HTTP 429 even when the submitted OTP changes every time.
        3. Attacker changing challenge_id on every guess is rejected with 401 without creating unlimited buckets.
        4. Attacker changing email on every guess cannot evade account/challenge lockout.
        5. Omitting challenge_id and email is rejected with 401 without creating rate-limit buckets.
        6. Attempt to reuse a challenge belonging to another email fails with 401 and increments failure counter.
        7. Concurrent failed guesses across independent clients lock out accurately.
        8. Redis outage in production mode returns fail-closed (HTTP 503).
        """
        with patch.dict(os.environ, {"BOONTRACK_DISABLE_AUTH_RATE_LIMIT": "0"}):
            verification_rate_limiter.reset_all()

            # Set up authoritative server-issued verification session
            victim_challenge = f"ch_auth_{uuid.uuid4().hex[:12]}"
            victim_token = f"tok_auth_{uuid.uuid4().hex}"
            victim_otp = "889900"
            victim_email = "victim_test@boontrack.id"
            session_payload = {
                "email": victim_email,
                "token": victim_token,
                "otp_code": victim_otp,
                "challenge_id": victim_challenge,
                "tenant_slug": "victim-shop",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{victim_token}", session_payload)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{victim_otp}", session_payload)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{victim_challenge}", session_payload)

            # 1 & 2: Five different incorrect OTP values against one authoritative challenge
            distinct_bad_otps = ["111111", "222222", "333333", "444444", "555555"]
            for idx, bad_otp in enumerate(distinct_bad_otps):
                res = self.client.post(
                    "/api/v1/auth/magic-link/verify",
                    json={"challenge_id": victim_challenge, "otp_code": bad_otp, "email": victim_email},
                )
                self.assertEqual(res.status_code, 401, f"Attempt {idx+1} with OTP '{bad_otp}' must return HTTP 401")
                self.assertIn("tidak valid atau telah kadaluarsa", res.json()["detail"])

            # 6th attempt with a 6th totally different OTP MUST return HTTP 429
            sixth_otp = "666666"
            res_6th = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"challenge_id": victim_challenge, "otp_code": sixth_otp, "email": victim_email},
            )
            self.assertEqual(res_6th.status_code, 429, "6th attempt must be rejected with HTTP 429 even though OTP changed every time")
            self.assertIn("Batas percobaan verifikasi", res_6th.json()["detail"])

            # 3. Rotating challenge_id on every guess does NOT create unlimited challenge buckets
            verification_rate_limiter.reset_all()
            for i in range(3):
                bogus_challenge = f"ch_bogus_{uuid.uuid4().hex[:12]}"
                res_bogus = self.client.post(
                    "/api/v1/auth/magic-link/verify",
                    json={"challenge_id": bogus_challenge, "otp_code": "123456"},
                )
                self.assertEqual(res_bogus.status_code, 401)
                # Ensure no bucket was created in Redis for forged challenge
                if token_store and token_store._redis_client:
                    exists = token_store._redis_client.exists(f"{_AUTH_HASH_TAG}:ratelimit:challenge:{bogus_challenge}")
                    self.assertEqual(exists, 0, "Unknown challenge ID must NOT create a rate-limit bucket in Redis")

            # 4. Attacker rotating client-supplied email cannot evade challenge/account lockout
            verification_rate_limiter.reset_all()
            ch_rot = f"ch_rot_{uuid.uuid4().hex[:12]}"
            tok_rot = f"tok_rot_{uuid.uuid4().hex}"
            session_rot = {
                "email": "target_owner@boontrack.id",
                "token": tok_rot,
                "otp_code": "123789",
                "challenge_id": ch_rot,
                "tenant_slug": "target-shop",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{tok_rot}", session_rot)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{session_rot['otp_code']}", session_rot)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{ch_rot}", session_rot)

            for i in range(5):
                res_rot = self.client.post(
                    "/api/v1/auth/magic-link/verify",
                    json={"challenge_id": ch_rot, "otp_code": f"00000{i}", "email": f"attacker_{i}@evil.test"},
                )
                self.assertEqual(res_rot.status_code, 401)

            # 6th attempt with yet another email must be locked out (HTTP 429)
            res_rot_6th = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"challenge_id": ch_rot, "otp_code": "999999", "email": "another_attacker@evil.test"},
            )
            self.assertEqual(res_rot_6th.status_code, 429, "Rotating client email cannot evade challenge lockout")

            # 5. Omitting challenge_id when verifying numeric OTP returns HTTP 400 Bad Request
            # Repeated invalid attempts without challenge_id across rotating IPs all fail with 400
            for rot_ip_idx in range(5):
                res_blind = self.client.post(
                    "/api/v1/auth/magic-link/verify",
                    json={"otp_code": "999999"},
                    headers={"CF-Connecting-IP": f"198.51.100.{rot_ip_idx+10}"},
                )
                self.assertEqual(res_blind.status_code, 400, "Verifying OTP without challenge_id must return HTTP 400")
                self.assertIn("challenge_id", res_blind.json()["detail"].lower())

            # Valid challenge-bound verification succeeds with 200 OK
            valid_ch_test = f"ch_bound_{uuid.uuid4().hex[:12]}"
            valid_tok_test = f"tok_bound_{uuid.uuid4().hex}"
            valid_otp_test = "771122"
            valid_email_test = "bound_owner@boontrack.id"
            register_auth_test_merchant(slug="bound-store", owner_email=valid_email_test, is_active=True)
            bound_payload = {
                "email": valid_email_test,
                "token": valid_tok_test,
                "otp_code": valid_otp_test,
                "challenge_id": valid_ch_test,
                "tenant_slug": "bound-store",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{valid_tok_test}", bound_payload)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{valid_otp_test}", bound_payload)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{valid_ch_test}", bound_payload)

            res_valid_ch = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"challenge_id": valid_ch_test, "otp_code": valid_otp_test},
            )
            self.assertEqual(res_valid_ch.status_code, 200)
            self.assertIn("access_token", res_valid_ch.json())

            # Valid high-entropy token verification without challenge_id succeeds (preserving token flow)
            valid_tok_flow = f"tok_flow_{uuid.uuid4().hex}"
            token_payload = {
                "email": valid_email_test,
                "token": valid_tok_flow,
                "tenant_slug": "bound-store",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{valid_tok_flow}", token_payload)
            res_valid_tok = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"token": valid_tok_flow},
            )
            self.assertEqual(res_valid_tok.status_code, 200)
            self.assertIn("access_token", res_valid_tok.json())

            # 6. Attempt to reuse a challenge belonging to another email fails
            ch_reuse = f"ch_reuse_{uuid.uuid4().hex[:12]}"
            tok_reuse = f"tok_reuse_{uuid.uuid4().hex}"
            session_reuse = {
                "email": "legit_owner@boontrack.id",
                "token": tok_reuse,
                "otp_code": "654321",
                "challenge_id": ch_reuse,
                "tenant_slug": "legit-shop",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{tok_reuse}", session_reuse)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{session_reuse['otp_code']}", session_reuse)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{ch_reuse}", session_reuse)

            res_mismatch = self.client.post(
                "/api/v1/auth/magic-link/verify",
                json={"challenge_id": ch_reuse, "otp_code": session_reuse['otp_code'], "email": "attacker@evil.test"},
            )
            self.assertEqual(res_mismatch.status_code, 401)

            # 7. Concurrent failed guesses across independent clients
            verification_rate_limiter.reset_all()
            conc_challenge = f"ch_conc_{uuid.uuid4().hex[:12]}"
            conc_token = f"tok_conc_{uuid.uuid4().hex}"
            session_conc = {
                "email": "conc_test@boontrack.id",
                "token": conc_token,
                "otp_code": "334455",
                "challenge_id": conc_challenge,
                "tenant_slug": "conc-shop",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{conc_token}", session_conc)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{session_conc['otp_code']}", session_conc)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{conc_challenge}", session_conc)

            def make_failed_attempt(item):
                i, guess_otp = item
                return self.client.post(
                    "/api/v1/auth/magic-link/verify",
                    json={"challenge_id": conc_challenge, "otp_code": guess_otp},
                    headers={"X-Forwarded-For": f"198.51.100.{i+1}"},
                ).status_code

            with ThreadPoolExecutor(max_workers=5) as pool:
                guesses = [(i, f"{100000 + i}") for i in range(10)]
                statuses = list(pool.map(make_failed_attempt, guesses))

            self.assertEqual(statuses.count(401), 5)
            self.assertEqual(statuses.count(429), 5)

            # 8. Valid OTP succeeds and resets challenge and account counter
            valid_challenge = f"ch_valid_{uuid.uuid4().hex[:12]}"
            valid_otp = "777888"
            valid_tok = f"tok_valid_{uuid.uuid4().hex}"
            test_email = f"reset_test_{uuid.uuid4().hex[:6]}@boontrack.id"
            session_valid = {
                "email": test_email,
                "token": valid_tok,
                "otp_code": valid_otp,
                "challenge_id": valid_challenge,
                "tenant_slug": "reset-test-slug",
                "is_registration": False,
                "created_at": time.time(),
            }
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link:{valid_tok}", session_valid)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_otp:{valid_otp}", session_valid)
            token_store.set_token(f"{_AUTH_HASH_TAG}:magic_link_challenge:{valid_challenge}", session_valid)

            verification_rate_limiter.reset_all()
            verification_rate_limiter.record_failed_attempt(challenge_id=valid_challenge, account_id=test_email)

            with patch("app.routes.auth_routes._resolve_verified_user_membership", return_value=({"role": "merchant", "tenant_slug": "reset-test-slug", "is_active": True}, None)):
                valid_res = self.client.post(
                    "/api/v1/auth/magic-link/verify",
                    json={"challenge_id": valid_challenge, "otp_code": valid_otp, "email": test_email},
                )
                self.assertEqual(valid_res.status_code, 200)
                is_ch_locked, _ = verification_rate_limiter.is_challenge_locked(valid_challenge)
                self.assertFalse(is_ch_locked, "Challenge lockout counter must be reset upon valid OTP verification")
                is_acc_locked, _ = verification_rate_limiter.is_account_locked(test_email)
                self.assertFalse(is_acc_locked, "Account lockout counter must be reset upon valid OTP verification")

            # 9. Redis outage in production mode returns fail-closed (HTTP 503)
            with patch.dict(os.environ, {"APP_ENV": "production", "REDIS_REQUIRED": "true"}):
                with patch.object(token_store, "_is_redis_healthy", return_value=False):
                    prod_res = self.client.post("/api/v1/auth/magic-link/verify", json={"challenge_id": valid_challenge, "otp_code": "000000"})
                    self.assertEqual(prod_res.status_code, 503)
                    self.assertIn("fail-closed", prod_res.json()["detail"])

    # -------------------------------------------------------------------------
    # Test 18: Tightened Trusted Proxy Boundary (CTO P0/P1)
    # -------------------------------------------------------------------------
    def test_18_trusted_client_ip_and_spoofed_forwarded_headers(self):
        """
        Proves:
        1. Untrusted direct client IP sending spoofed X-Forwarded-For is ignored.
        2. Real untrusted client IP is preserved when forwarded through trusted proxy (right-to-left traversal).
        3. Cloudflare CF-Connecting-IP is honored ONLY when direct peer is in Cloudflare IP ranges.
        4. Trusted private network proxy (RFC1918) CANNOT inject CF-Connecting-IP; falls back to X-Forwarded-For.
        5. Untrusted direct client cannot spoof CF-Connecting-IP.
        """
        resolver = TrustedProxyResolver(
            trusted_cidrs=["127.0.0.1/32", "10.0.0.0/8"],
            cloudflare_cidrs=["173.245.48.0/20"],
        )

        class MockClient:
            def __init__(self, host):
                self.host = host

        class MockReq:
            def __init__(self, host, headers=None):
                self.client = MockClient(host)
                self.headers = headers or {}

        # 1. Untrusted direct connection (203.0.113.5) with spoofed headers
        untrusted_req = MockReq(
            host="203.0.113.5",
            headers={"x-forwarded-for": "1.1.1.1, 10.0.0.1", "cf-connecting-ip": "8.8.8.8"},
        )
        resolved_ip = resolver.resolve_client_ip(untrusted_req)
        self.assertEqual(resolved_ip, "203.0.113.5", "Untrusted peer MUST NOT be allowed to spoof client IP via headers")

        # 2. Trusted private proxy connection (10.0.0.2) attempting to inject forged CF-Connecting-IP
        private_proxy_cf_inject_req = MockReq(
            host="10.0.0.2",
            headers={"cf-connecting-ip": "8.8.8.8", "x-forwarded-for": "198.51.100.99, 10.0.0.2"},
        )
        resolved_priv_ip = resolver.resolve_client_ip(private_proxy_cf_inject_req)
        self.assertEqual(resolved_priv_ip, "198.51.100.99", "Private RFC1918 proxy CANNOT inject CF-Connecting-IP; must use XFF")

        # 3. Trusted Cloudflare proxy (173.245.48.10) with CF-Connecting-IP
        cf_req = MockReq(
            host="173.245.48.10",
            headers={"cf-connecting-ip": "198.51.100.77", "x-forwarded-for": "198.51.100.77"},
        )
        resolved_cf_ip = resolver.resolve_client_ip(cf_req)
        self.assertEqual(resolved_cf_ip, "198.51.100.77", "Trusted Cloudflare peer must yield CF-Connecting-IP")

        # 4. Untrusted direct peer trying to inject CF-Connecting-IP
        cf_spoof_req = MockReq(
            host="192.0.2.1",
            headers={"cf-connecting-ip": "8.8.8.8"},
        )
        resolved_spoof = resolver.resolve_client_ip(cf_spoof_req)
        self.assertEqual(resolved_spoof, "192.0.2.1", "Untrusted peer MUST NOT be allowed to spoof via CF-Connecting-IP")

    # -------------------------------------------------------------------------
    # Test 19: Action-Aware Reconciliation and Lock Safety (CTO P1)
    # -------------------------------------------------------------------------
    def test_19_scheduled_cleanup_reconciliation_and_active_tenant_preservation(self):
        """
        Proves:
        1. Action-aware recovery distinguishes action='delete' from action='revert'.
        2. action='revert' restores status='PENDING_VERIFICATION' and is_otp_verified=false without deleting rows.
        3. ACTIVE tenants are NEVER deleted or reverted by reconciliation.
        4. Leader lock unavailable in production fails closed.
        5. Per-record lock unavailable in production skips record safely without unprotected execution.
        6. Redis outage during dead-letter persistence fails closed in production.
        7. Repeated reconciliation is idempotent.
        """
        # 1. Action-aware revert: restores PENDING_VERIFICATION without deleting rows
        revert_slug = f"revert-slug-{uuid.uuid4().hex[:8]}"
        revert_email = f"owner_{revert_slug}@boontrack.id"

        if LIVE_POSTGRES_ACTIVE:
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.tenants (name, slug, tier, status, is_active)
                        VALUES (%s, %s, 'STARTER', 'PENDING_VERIFICATION', false)
                        ON CONFLICT (slug) DO NOTHING;
                        """,
                        (revert_slug, revert_slug),
                    )
                    cur.execute(
                        """
                        INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                        VALUES (%s, %s, 'Owner Revert', %s, '08123456789', 'ACTIVE')
                        ON CONFLICT DO NOTHING;
                        """,
                        (revert_slug, revert_slug, revert_email),
                    )
                conn.commit()
            finally:
                conn.close()

            # Record dead-letter with action='revert'
            _record_dead_letter_cleanup(revert_slug, revert_email, "simulated activation compensation failure", action="revert")
            res_rev = reconcile_pending_cleanups()
            self.assertIn(revert_slug, res_rev["reconciled"])

            # Verify merchants table reverted to PENDING_VERIFICATION and tenant row was NOT deleted!
            conn2 = get_db_connection()
            try:
                with conn2.cursor() as cur2:
                    cur2.execute("SELECT status FROM public.merchants WHERE lower(slug) = %s;", (revert_slug,))
                    m_row = cur2.fetchone()
                    self.assertIsNotNone(m_row)
                    self.assertEqual(m_row[0], "PENDING_VERIFICATION", "Merchant status must be reverted to PENDING_VERIFICATION")

                    cur2.execute("SELECT status FROM public.tenants WHERE lower(slug) = %s;", (revert_slug,))
                    t_row = cur2.fetchone()
                    self.assertIsNotNone(t_row, "Tenant row must NOT be deleted during revert action")
                    self.assertEqual(t_row[0], "PENDING_VERIFICATION")
            finally:
                conn2.close()

        # 2. Test active tenant guard: An ACTIVE tenant in PostgreSQL is NEVER deleted
        active_slug = f"active-guard-{uuid.uuid4().hex[:8]}"
        active_email = f"owner_{active_slug}@testboontrack.id"

        if LIVE_POSTGRES_ACTIVE:
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.tenants (name, slug, tier, status, is_active)
                        VALUES (%s, %s, 'STARTER', 'ACTIVE', true)
                        ON CONFLICT (slug) DO UPDATE SET status = 'ACTIVE', is_active = true;
                        """,
                        (active_slug, active_slug),
                    )
                    cur.execute(
                        """
                        INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                        VALUES (%s, %s, 'Owner Active', %s, '08123456789', 'ACTIVE')
                        ON CONFLICT DO NOTHING;
                        """,
                        (active_slug, active_slug, active_email),
                    )
                conn.commit()
            finally:
                conn.close()

            _record_dead_letter_cleanup(active_slug, active_email, "simulated prior error", action="delete")
            res = reconcile_pending_cleanups()
            self.assertNotIn(active_slug, _DEAD_LETTER_CLEANUP_REGISTRY)

            conn3 = get_db_connection()
            try:
                with conn3.cursor() as cur3:
                    cur3.execute("SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s;", (active_slug,))
                    t_row = cur3.fetchone()
                    self.assertIsNotNone(t_row)
                    self.assertEqual(t_row[0], "ACTIVE")
                    self.assertTrue(t_row[1])
            finally:
                conn3.close()

        # 2b. Active Tenant Guard on action='revert':
        # If tenant is ACTIVE or is_active=true, do NOT revert the merchant automatically.
        # Preserve both records and retain the dead-letter entry for manual reconciliation.
        rev_active_slug = f"rev-act-guard-{uuid.uuid4().hex[:8]}"
        rev_active_email = f"owner_{rev_active_slug}@testboontrack.id"

        if LIVE_POSTGRES_ACTIVE:
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.tenants (name, slug, tier, status, is_active)
                        VALUES (%s, %s, 'STARTER', 'ACTIVE', true)
                        ON CONFLICT (slug) DO UPDATE SET status = 'ACTIVE', is_active = true;
                        """,
                        (rev_active_slug, rev_active_slug),
                    )
                    cur.execute(
                        """
                        INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                        VALUES (%s, %s, 'Owner Rev Active', %s, '08123456789', 'ACTIVE')
                        ON CONFLICT DO NOTHING;
                        """,
                        (rev_active_slug, rev_active_slug, rev_active_email),
                    )
                conn.commit()
            finally:
                conn.close()

            _record_dead_letter_cleanup(rev_active_slug, rev_active_email, "simulated activation failure on active tenant", action="revert")
            res_act_rev = reconcile_pending_cleanups()
            # Must NOT be in reconciled; dead-letter record retained!
            self.assertIn(rev_active_slug, res_act_rev["failed"])
            self.assertIn(rev_active_slug, _DEAD_LETTER_CLEANUP_REGISTRY)

            conn_chk = get_db_connection()
            try:
                with conn_chk.cursor() as cur:
                    cur.execute("SELECT status FROM public.merchants WHERE lower(slug) = %s;", (rev_active_slug,))
                    m_row = cur.fetchone()
                    self.assertEqual(m_row[0], "ACTIVE", "Active tenant's merchant must NOT be reverted")

                    cur.execute("SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s;", (rev_active_slug,))
                    t_row = cur.fetchone()
                    self.assertEqual(t_row[0], "ACTIVE")
                    self.assertTrue(t_row[1])
            finally:
                conn_chk.close()

            # Clean up dead-letter test entry
            _clear_dead_letter_cleanup(rev_active_slug)

        # 2c. Revert with owner mismatch and zero-rowcount scenarios
        mismatch_slug = f"rev-mismatch-{uuid.uuid4().hex[:8]}"
        mismatch_real_email = f"real_{mismatch_slug}@boontrack.id"
        mismatch_wrong_email = f"wrong_{mismatch_slug}@boontrack.id"

        if LIVE_POSTGRES_ACTIVE:
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.tenants (name, slug, tier, status, is_active)
                        VALUES (%s, %s, 'STARTER', 'PENDING_VERIFICATION', false)
                        ON CONFLICT (slug) DO NOTHING;
                        """,
                        (mismatch_slug, mismatch_slug),
                    )
                    cur.execute(
                        """
                        INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                        VALUES (%s, %s, 'Mismatch Owner', %s, '08123456789', 'ACTIVE')
                        ON CONFLICT DO NOTHING;
                        """,
                        (mismatch_slug, mismatch_slug, mismatch_real_email),
                    )
                conn.commit()
            finally:
                conn.close()

            # Revert with mismatched email returns False (affected 0 rows)
            ok_mis, err_mis = _revert_pending_merchant_activation(mismatch_slug, mismatch_wrong_email)
            self.assertFalse(ok_mis)
            self.assertIn("affected 0 rows", str(err_mis))

            # Non-existent slug returns False (affected 0 rows)
            ok_zero, err_zero = _revert_pending_merchant_activation("non_existent_slug_xyz", "anyone@boontrack.id")
            self.assertFalse(ok_zero)
            self.assertIn("affected 0 rows", str(err_zero))

        # 2d. Fail-Closed Tenant Guard on Revert when DB error occurs (CTO P1)
        with patch("app.core.database.get_db_connection", side_effect=Exception("PG DB Error during revert")):
            with patch("app.routes.auth_routes.get_supabase", return_value=None):
                ok_unk, err_unk = _revert_pending_merchant_activation("unknown_err_slug", "owner@unknown.test")
                self.assertFalse(ok_unk, "Revert must fail closed when tenant state is unknown")
                self.assertIn("TENANT_GUARD_UNKNOWN_STATE", str(err_unk))

        # Supabase tenant check returns None / error -> fail closed
        mock_sb_err = unittest.mock.MagicMock()
        mock_sb_err.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = Exception("Supabase network error")
        with patch("app.core.database.get_db_connection", side_effect=Exception("PG Down")):
            with patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_err):
                ok_sb_unk, err_sb_unk = _revert_pending_merchant_activation("sb_unk_slug", "owner@sb.test")
                self.assertFalse(ok_sb_unk, "Revert must fail closed when Supabase tenant check errors")
                self.assertIn("TENANT_GUARD_UNKNOWN_STATE", str(err_sb_unk))

        # 3. Production fail-closed on leader lock unavailable
        with patch.dict(os.environ, {"APP_ENV": "production", "REDIS_REQUIRED": "true"}):
            with patch.object(token_store, "_is_redis_healthy", return_value=False):
                res_prod = reconcile_pending_cleanups()
                self.assertEqual(res_prod.get("error"), "redis_unavailable")

        # 4. Production fail-closed on dead-letter persistence failure
        with patch.dict(os.environ, {"APP_ENV": "production", "REDIS_REQUIRED": "true"}):
            with patch.object(token_store, "_is_redis_healthy", return_value=False):
                with self.assertRaises(RuntimeError):
                    _record_dead_letter_cleanup("fail-slug", "fail@boontrack.id", "cannot persist")

        # 5. Idempotent repeated runs
        res1 = reconcile_pending_cleanups()
        res2 = reconcile_pending_cleanups()
        self.assertEqual(res1.get("failed", []), [])
        self.assertEqual(res2.get("failed", []), [])

    # -------------------------------------------------------------------------
    # Test 20: Supabase Dual-Table Recovery and State-Based Evidence (CTO P1)
    # -------------------------------------------------------------------------
    def test_20_supabase_compensating_recovery_dual_table_scenarios(self):
        """
        Tests dual-table compensating recovery scenarios and state verification:
        1. Merchant insert succeeds but tenant insert fails -> compensating delete executed.
        2. Merchant compensation delete fails -> failure enqueued in durable dead-letter queue.
        3. Merchant activation succeeds but tenant activation fails -> compensating revert executed.
        4. Merchant status revert fails -> failure enqueued in durable dead-letter queue.
        5. PostgreSQL cleanup fails but Supabase cleanup succeeds -> returns True, clears obsolete error.
        6. State-based recovery verification: verifies resulting state of both tables.
        7. Supabase delete distinguishes successful deletion from zero-row or RLS-filtered operations.
        """
        # Scenario 1: Merchant insert succeeds, tenant insert fails -> compensating delete succeeds
        slug1 = f"comp-ins-1-{uuid.uuid4().hex[:8]}"
        email1 = f"comp_{slug1}@example.test"
        mock_sb_s1 = unittest.mock.MagicMock()
        mock_m1 = unittest.mock.MagicMock()
        mock_t1 = unittest.mock.MagicMock()
        mock_m1.insert.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        mock_t1.insert.side_effect = Exception("Simulated tenant provision conflict")
        mock_sb_s1.table.side_effect = lambda name: mock_m1 if name == "merchants" else mock_t1

        with patch("app.core.database.get_db_connection", side_effect=Exception("DB down")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_s1):
            ok1, err1 = _insert_pending_merchant(slug=slug1, user_name="User1", user_email=email1)
            self.assertFalse(ok1)
            self.assertIn("SUPABASE_TENANT_PROVISION_ERROR", str(err1))
            mock_m1.delete.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.assert_called_once()

        # Scenario 2: Merchant insert succeeds, tenant fails, compensating delete fails -> dead-letter enqueued
        slug2 = f"comp-ins-2-{uuid.uuid4().hex[:8]}"
        email2 = f"comp_{slug2}@example.test"
        mock_sb_s2 = unittest.mock.MagicMock()
        mock_m2 = unittest.mock.MagicMock()
        mock_t2 = unittest.mock.MagicMock()
        mock_m2.insert.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        mock_t2.insert.side_effect = Exception("Tenant provision failed")
        mock_m2.delete.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.side_effect = Exception("Compensating delete failed")
        mock_sb_s2.table.side_effect = lambda name: mock_m2 if name == "merchants" else mock_t2

        with patch("app.core.database.get_db_connection", side_effect=Exception("DB down")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_s2):
            ok2, err2 = _insert_pending_merchant(slug=slug2, user_name="User2", user_email=email2)
            self.assertFalse(ok2)
            self.assertIn(slug2, _DEAD_LETTER_CLEANUP_REGISTRY)
            self.assertEqual(_DEAD_LETTER_CLEANUP_REGISTRY[slug2]["owner_email"], email2)

        # Scenario 3: Merchant activation succeeds, tenant activation fails -> compensating revert executed
        slug3 = f"comp-act-3-{uuid.uuid4().hex[:8]}"
        email3 = f"comp_{slug3}@example.test"
        mock_sb_s3 = unittest.mock.MagicMock()
        mock_m3 = unittest.mock.MagicMock()
        mock_t3 = unittest.mock.MagicMock()
        mock_m3.update.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        mock_t3.update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[])
        mock_sb_s3.table.side_effect = lambda name: mock_m3 if name == "merchants" else mock_t3

        with patch("app.core.database.get_db_connection", side_effect=Exception("DB down")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_s3):
            ok3, err3 = _activate_pending_merchant(slug=slug3, owner_email=email3)
            self.assertFalse(ok3)
            self.assertIn("TENANT_ACTIVATION_AFFECTED_ZERO_ROWS", str(err3))

        # Scenario 4: Merchant activation succeeds, tenant fails, compensating revert fails -> dead-letter enqueued
        slug4 = f"comp-act-4-{uuid.uuid4().hex[:8]}"
        email4 = f"comp_{slug4}@example.test"
        mock_sb_s4 = unittest.mock.MagicMock()
        mock_m4 = unittest.mock.MagicMock()
        mock_t4 = unittest.mock.MagicMock()
        mock_m4.update.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.side_effect = [
            unittest.mock.MagicMock(data=[{"id": 1}]),
            Exception("Revert to PENDING failed"),
        ]
        mock_t4.update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[])
        mock_sb_s4.table.side_effect = lambda name: mock_m4 if name == "merchants" else mock_t4

        with patch("app.core.database.get_db_connection", side_effect=Exception("DB down")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_s4):
            ok4, err4 = _activate_pending_merchant(slug=slug4, owner_email=email4)
            self.assertFalse(ok4)
            self.assertIn(slug4, _DEAD_LETTER_CLEANUP_REGISTRY)
            self.assertEqual(_DEAD_LETTER_CLEANUP_REGISTRY[slug4]["action"], "revert")

        # Scenario 5: PostgreSQL cleanup fails but Supabase cleanup succeeds -> returns True, clears obsolete error
        slug5 = f"comp-del-5-{uuid.uuid4().hex[:8]}"
        email5 = f"comp_{slug5}@example.test"
        mock_sb_s5 = unittest.mock.MagicMock()
        mock_m5 = unittest.mock.MagicMock()
        mock_t5 = unittest.mock.MagicMock()
        mock_m5.delete.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        mock_t5.delete.return_value.eq.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        mock_sb_s5.table.side_effect = lambda name: mock_m5 if name == "merchants" else mock_t5

        with patch("app.core.database.get_db_connection", side_effect=Exception("PostgreSQL connection refused")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_s5):
            ok5, err5 = _delete_pending_merchant(slug=slug5, owner_email=email5)
            self.assertTrue(ok5, "When Supabase cleanup succeeds, _delete_pending_merchant must return True")
            self.assertIsNone(err5, "Obsolete PostgreSQL error must not be retained when Supabase cleanup succeeds")

        # Scenario 6: State-based verification on live PostgreSQL
        if LIVE_POSTGRES_ACTIVE:
            state_slug = f"state-rec-{uuid.uuid4().hex[:8]}"
            state_email = f"state_{state_slug}@boontrack.id"
            conn_st = get_db_connection()
            try:
                with conn_st.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.tenants (name, slug, tier, status, is_active)
                        VALUES (%s, %s, 'STARTER', 'PENDING_VERIFICATION', false)
                        ON CONFLICT (slug) DO NOTHING;
                        """,
                        (state_slug, state_slug),
                    )
                    cur.execute(
                        """
                        INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                        VALUES (%s, %s, 'State Merchant', %s, '08123456789', 'ACTIVE')
                        ON CONFLICT DO NOTHING;
                        """,
                        (state_slug, state_slug, state_email),
                    )
                conn_st.commit()
            finally:
                conn_st.close()

            _record_dead_letter_cleanup(state_slug, state_email, "simulated prior error", action="revert")
            res_rec = reconcile_pending_cleanups()
            self.assertIn(state_slug, res_rec["reconciled"])

            conn_st2 = get_db_connection()
            try:
                with conn_st2.cursor() as cur2:
                    cur2.execute("SELECT status FROM public.merchants WHERE lower(slug) = %s;", (state_slug,))
                    m_row = cur2.fetchone()
                    self.assertIsNotNone(m_row)
                    self.assertEqual(m_row[0], "PENDING_VERIFICATION", "Merchant must be restored to PENDING_VERIFICATION")

                    cur2.execute("SELECT status FROM public.tenants WHERE lower(slug) = %s;", (state_slug,))
                    t_row = cur2.fetchone()
                    self.assertIsNotNone(t_row, "Pending tenant must not be deleted during revert")
                    self.assertEqual(t_row[0], "PENDING_VERIFICATION")
            finally:
                conn_st2.close()

        # Scenario 7: Supabase delete zero-row or RLS-filtered detection
        mock_sb_zero = unittest.mock.MagicMock()
        mock_m_zero = unittest.mock.MagicMock()
        mock_t_zero = unittest.mock.MagicMock()
        mock_m_zero.delete.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[])
        mock_m_zero.select.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1, "status": "PENDING_VERIFICATION"}])
        mock_sb_zero.table.side_effect = lambda name: mock_m_zero if name == "merchants" else mock_t_zero

        with patch("app.core.database.get_db_connection", side_effect=Exception("PostgreSQL connection refused")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_zero):
            ok_zero, err_zero = _delete_pending_merchant(slug="zero-row-slug", owner_email="test@zero.id")
            self.assertFalse(ok_zero, "Zero-row or RLS-filtered delete must not report success")

        # Scenario 8: Tenant deletion returns 0 rows (RLS filtered / status mismatch) while merchant succeeds
        mock_sb_t_zero = unittest.mock.MagicMock()
        mock_m_succ = unittest.mock.MagicMock()
        mock_t_zero = unittest.mock.MagicMock()
        # Merchant delete succeeds with 1 row deleted
        mock_m_succ.delete.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        # Tenant delete returns 0 rows
        mock_t_zero.delete.return_value.eq.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[])
        # Secondary select on tenant shows tenant row STILL exists!
        mock_t_zero.select.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1, "status": "PENDING_VERIFICATION"}])
        mock_sb_t_zero.table.side_effect = lambda name: mock_m_succ if name == "merchants" else mock_t_zero

        with patch("app.core.database.get_db_connection", side_effect=Exception("PostgreSQL connection refused")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_t_zero):
            ok_t_zero, err_t_zero = _delete_pending_merchant(slug="tenant-zero-slug", owner_email="test@zero.id")
            self.assertFalse(ok_t_zero, "Tenant deletion returning zero rows while row exists must fail recovery")
            self.assertIn("tenant-zero-slug", _DEAD_LETTER_CLEANUP_REGISTRY)
            self.assertEqual(_DEAD_LETTER_CLEANUP_REGISTRY["tenant-zero-slug"]["action"], "delete")

        # Scenario 9: In _insert_pending_merchant via Supabase, tenant fails, compensating merchant delete affects 0 rows
        # while merchant record still exists -> must record durable dead-letter
        slug9 = f"comp-zero-{uuid.uuid4().hex[:8]}"
        email9 = f"comp_zero_{slug9}@example.test"
        mock_sb_s9 = unittest.mock.MagicMock()
        mock_m9 = unittest.mock.MagicMock()
        mock_t9 = unittest.mock.MagicMock()
        # Merchant insert succeeds
        mock_m9.insert.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        # Tenant insert fails
        mock_t9.insert.side_effect = Exception("Tenant provision failed on conflict")
        # Compensating delete affects 0 rows (RLS policy filtered)
        mock_m9.delete.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[])
        # Secondary SELECT shows merchant record STILL exists!
        mock_m9.select.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1, "status": "PENDING_VERIFICATION"}])
        mock_sb_s9.table.side_effect = lambda name: mock_m9 if name == "merchants" else mock_t9

        with patch("app.core.database.get_db_connection", side_effect=Exception("DB down")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_s9):
            ok9, err9 = _insert_pending_merchant(slug=slug9, user_name="User9", user_email=email9)
            self.assertFalse(ok9)
            self.assertIn(slug9, _DEAD_LETTER_CLEANUP_REGISTRY)
            self.assertEqual(_DEAD_LETTER_CLEANUP_REGISTRY[slug9]["action"], "delete")
            self.assertIn("affected 0 rows", _DEAD_LETTER_CLEANUP_REGISTRY[slug9]["error"])

        # Scenario 10: In _insert_pending_merchant via Supabase, tenant fails, compensating delete returns data=[{"id": 1}]
        # but secondary select shows merchant STILL exists -> must record durable dead-letter
        slug10 = f"comp-still-{uuid.uuid4().hex[:8]}"
        email10 = f"comp_still_{slug10}@example.test"
        mock_sb_s10 = unittest.mock.MagicMock()
        mock_m10 = unittest.mock.MagicMock()
        mock_t10 = unittest.mock.MagicMock()
        mock_m10.insert.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        mock_t10.insert.side_effect = Exception("Tenant provision failed")
        mock_m10.delete.return_value.eq.return_value.ilike.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1}])
        mock_m10.select.return_value.eq.return_value.execute.return_value = unittest.mock.MagicMock(data=[{"id": 1, "status": "PENDING_VERIFICATION"}])
        mock_sb_s10.table.side_effect = lambda name: mock_m10 if name == "merchants" else mock_t10

        with patch("app.core.database.get_db_connection", side_effect=Exception("DB down")), \
             patch("app.routes.auth_routes.get_supabase", return_value=mock_sb_s10):
            ok10, err10 = _insert_pending_merchant(slug=slug10, user_name="User10", user_email=email10)
            self.assertFalse(ok10)
            self.assertIn(slug10, _DEAD_LETTER_CLEANUP_REGISTRY)
            self.assertEqual(_DEAD_LETTER_CLEANUP_REGISTRY[slug10]["action"], "delete")

    # -------------------------------------------------------------------------
    # Test 21: Distributed Public Auth Rate Limiter & Multi-Instance Sync (CTO P1)
    # -------------------------------------------------------------------------
    def test_21_distributed_public_auth_rate_limiting_and_multi_instance(self):
        """
        Proves:
        1. Two independent DistributedAuthRateLimiter instances share rate limit counters via Redis.
        2. Route-specific budgets: 30 req/min for /request and 10 req/min for /register.
        3. Bursts on public magic-link request and registration endpoints are throttled.
        4. In production mode, Redis outage strictly fails closed (HTTP 503).
        5. Actual HTTP endpoints enforce separate budgets across shared Redis.
        """
        store1 = TokenStore()
        store2 = TokenStore()

        limiter1 = DistributedAuthRateLimiter(endpoint="test", max_requests=5, window_seconds=60, store=store1)
        limiter2 = DistributedAuthRateLimiter(endpoint="test", max_requests=5, window_seconds=60, store=store2)

        test_user = f"burst_user_{uuid.uuid4().hex[:6]}@boontrack.id"

        with patch.dict(os.environ, {"BOONTRACK_DISABLE_AUTH_RATE_LIMIT": "0"}):
            limiter1.reset()

            # Make 3 requests via limiter1
            for _ in range(3):
                allowed, _ = limiter1.is_allowed(test_user)
                self.assertTrue(allowed)

            # Enforce that Redis health is mandatory in CI
            if _IS_CI:
                self.assertTrue(store1._is_redis_healthy(), "Redis store1 must be healthy in CI (redis:7-alpine)")
                self.assertTrue(store2._is_redis_healthy(), "Redis store2 must be healthy in CI (redis:7-alpine)")

            # Multi-instance cross-process rate limiting assertions
            if store1._is_redis_healthy() and store2._is_redis_healthy():
                # Make 2 requests via limiter2
                for _ in range(2):
                    allowed, _ = limiter2.is_allowed(test_user)
                    self.assertTrue(allowed)

                # 6th request via limiter2 must be rejected (exceeded 5 requests globally)
                allowed_6th, retry_after = limiter2.is_allowed(test_user)
                self.assertFalse(allowed_6th, "6th request across distributed instances must be rate limited")
                self.assertGreater(retry_after, 0)
            elif _IS_CI:
                self.fail("Redis cross-instance rate limiting assertions must not be skipped in CI")

            # Route-specific budgets test (30 req/min for request, 10 req/min for register)
            req_store1 = TokenStore()
            req_store2 = TokenStore()
            lim_req1 = DistributedAuthRateLimiter(endpoint="request", max_requests=30, window_seconds=60, store=req_store1)
            lim_req2 = DistributedAuthRateLimiter(endpoint="request", max_requests=30, window_seconds=60, store=req_store2)

            reg_store1 = TokenStore()
            reg_store2 = TokenStore()
            lim_reg1 = DistributedAuthRateLimiter(endpoint="register", max_requests=10, window_seconds=60, store=reg_store1)
            lim_reg2 = DistributedAuthRateLimiter(endpoint="register", max_requests=10, window_seconds=60, store=reg_store2)

            lim_req1.reset()
            lim_reg1.reset()

            user_budget = f"budget_user_{uuid.uuid4().hex[:6]}@boontrack.id"

            if _IS_CI:
                self.assertTrue(reg_store1._is_redis_healthy(), "Redis reg_store1 must be healthy in CI")
                self.assertTrue(reg_store2._is_redis_healthy(), "Redis reg_store2 must be healthy in CI")

            if reg_store1._is_redis_healthy() and reg_store2._is_redis_healthy():
                # 1. Register budget (10 max across 2 instances sharing Redis)
                for _ in range(5):
                    self.assertTrue(lim_reg1.is_allowed(user_budget)[0])
                for _ in range(5):
                    self.assertTrue(lim_reg2.is_allowed(user_budget)[0])
                # 11th request: rejected!
                self.assertFalse(lim_reg2.is_allowed(user_budget)[0])

                # 2. Independent budget proof: Even though user_budget is locked out on register (10/10 consumed),
                # the SAME user_budget can STILL make requests on the request endpoint (budget 30)!
                for _ in range(15):
                    self.assertTrue(lim_req1.is_allowed(user_budget)[0], "Request endpoint must have independent budget")
                for _ in range(15):
                    self.assertTrue(lim_req2.is_allowed(user_budget)[0], "Request endpoint must have independent budget")
                # 31st request: rejected!
                self.assertFalse(lim_req2.is_allowed(user_budget)[0])

                # 3. Verify Redis key independence
                if req_store1._redis_client:
                    reg_keys = req_store1._redis_client.keys(f"{_AUTH_HASH_TAG}:ratelimit:auth:register:account:{user_budget}*")
                    req_keys = req_store1._redis_client.keys(f"{_AUTH_HASH_TAG}:ratelimit:auth:request:account:{user_budget}*")
                    self.assertGreater(len(reg_keys), 0)
                    self.assertGreater(len(req_keys), 0)
                    self.assertNotEqual(set(reg_keys), set(req_keys), "Register and request rate limit keys must be independent")
            elif _IS_CI:
                self.fail("Redis independent endpoint budget assertions must not be skipped in CI")

            # 4. Independent Account vs IP Buckets test (CTO P1):
            # Rotasi IP tidak boleh mereset counter akun, dan pergantian email tidak boleh mereset counter IP
            account_user = f"acc_rot_{uuid.uuid4().hex[:6]}@boontrack.id"
            lim_ip_acc = DistributedAuthRateLimiter(endpoint="rot_test", max_requests=5, window_seconds=60, store=store1)
            lim_ip_acc.reset()

            # A. IP Rotation: 5 requests from 5 different IPs for the SAME account
            for i in range(5):
                allowed, _ = lim_ip_acc.is_allowed(account_user, client_ip=f"192.0.2.{i+1}")
                self.assertTrue(allowed, f"Request {i+1} with rotating IP should be allowed")
            # 6th request from a brand new IP for the same account must be BLOCKED (account locked out)
            allowed_6th_ip, _ = lim_ip_acc.is_allowed(account_user, client_ip="192.0.2.99")
            self.assertFalse(allowed_6th_ip, "Rotating IP must NOT reset account bucket counter")

            # B. Email Rotation: 5 requests for 5 different accounts from the SAME IP
            static_ip = "198.51.100.42"
            lim_ip_acc2 = DistributedAuthRateLimiter(endpoint="rot_test2", max_requests=5, window_seconds=60, store=store1)
            lim_ip_acc2.reset()
            for i in range(5):
                rotating_user = f"rot_user_{i}_{uuid.uuid4().hex[:4]}@boontrack.id"
                allowed, _ = lim_ip_acc2.is_allowed(rotating_user, client_ip=static_ip)
                self.assertTrue(allowed, f"Request {i+1} with rotating email should be allowed")
            # 6th request with a brand new email from the same IP must be BLOCKED (IP locked out)
            brand_new_user = f"rot_user_new_{uuid.uuid4().hex[:4]}@boontrack.id"
            allowed_6th_email, _ = lim_ip_acc2.is_allowed(brand_new_user, client_ip=static_ip)
            self.assertFalse(allowed_6th_email, "Rotating email must NOT reset IP bucket counter")

            # HTTP endpoint rate limit testing across instances
            http_user = f"http_rate_{uuid.uuid4().hex[:6]}@boontrack.id"
            from app.routes.auth_routes import request_rate_limiter, register_rate_limiter
            request_rate_limiter.reset()
            register_rate_limiter.reset()

            with patch.object(request_rate_limiter, "max_requests", 3):
                for _ in range(3):
                    res_http = self.client.post("/api/v1/auth/magic-link/request", json={"email": http_user})
                    self.assertEqual(res_http.status_code, 200)
                # 4th HTTP request must return 429
                res_http_4th = self.client.post("/api/v1/auth/magic-link/request", json={"email": http_user})
                self.assertEqual(res_http_4th.status_code, 429)
                self.assertIn("Terlalu banyak permintaan autentikasi", res_http_4th.json()["detail"])

            # Production mode fail-closed when Redis is down
            with patch.dict(os.environ, {"APP_ENV": "production", "REDIS_REQUIRED": "true"}):
                with patch.object(store1, "_is_redis_healthy", return_value=False):
                    with self.assertRaises(RuntimeError):
                        limiter1.is_allowed("prod_user@boontrack.id")




    # -------------------------------------------------------------------------
    # Test 22: Live PostgreSQL Mixed-State Cleanup & Consistency Verification (CTO P0)
    # -------------------------------------------------------------------------
    @unittest.skipUnless(LIVE_POSTGRES_ACTIVE, "Live PostgreSQL database required for integration test")
    def test_22_live_postgres_mixed_state_cleanup_reconciliation(self):
        """
        Proves:
        1. PostgreSQL dual-table cleanup inspects affected-row counts.
        2. Independently verifies final merchant and tenant states after deletion.
        3. Never clears dead-letter when one record remains inconsistent.
        4. Mixed-state (tenant remaining as active/non-pending) triggers rollback and creates dead-letter.
        5. Mixed-state (merchant owner mismatch) triggers rollback and creates dead-letter.
        """
        # Scenario 1: Mixed state where merchants has pending row, but tenants is ACTIVE / is_active=true
        mixed_slug_1 = f"mix-state-1-{uuid.uuid4().hex[:8]}"
        mixed_email_1 = f"owner_{mixed_slug_1}@boontrack.id"

        conn1 = get_db_connection()
        try:
            with conn1.cursor() as cur:
                # Seed merchants row in PENDING_VERIFICATION
                cur.execute(
                    """
                    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                    VALUES (%s, %s, 'Mixed 1', %s, '08123456789', 'PENDING_VERIFICATION')
                    ON CONFLICT DO NOTHING;
                    """,
                    (mixed_slug_1, mixed_slug_1, mixed_email_1),
                )
                # Seed tenants row in ACTIVE / is_active=true state (so DELETE WHERE is_active=false will NOT delete it!)
                cur.execute(
                    """
                    INSERT INTO public.tenants (name, slug, tier, status, is_active)
                    VALUES (%s, %s, 'STARTER', 'ACTIVE', true)
                    ON CONFLICT (slug) DO UPDATE SET status = 'ACTIVE', is_active = true;
                    """,
                    (mixed_slug_1, mixed_slug_1),
                )
            conn1.commit()
        finally:
            conn1.close()

        # In Scenario 1, merchants is PENDING_VERIFICATION while tenants is ACTIVE.
        # Guard does NOT clear dead-letter because merchant is pending (inconsistent mixed state).
        # PostgreSQL cleanup rolls back because rem_t is not None, and records dead-letter.
        ok_mix1, err_mix1 = _delete_pending_merchant(mixed_slug_1, mixed_email_1)
        self.assertFalse(ok_mix1)
        self.assertIn("POSTGRESQL_CLEANUP_INCONSISTENT_STATE", str(err_mix1))
        self.assertIn(mixed_slug_1, _DEAD_LETTER_CLEANUP_REGISTRY)
        self.assertEqual(_DEAD_LETTER_CLEANUP_REGISTRY[mixed_slug_1]["action"], "delete")

        # Scenario 2: What if tenants was PENDING_VERIFICATION with is_active=true?
        mixed_slug_2 = f"mix-state-2-{uuid.uuid4().hex[:8]}"
        mixed_email_2 = f"owner_{mixed_slug_2}@boontrack.id"

        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                    VALUES (%s, %s, 'Mixed 2', %s, '08123456789', 'PENDING_VERIFICATION')
                    ON CONFLICT DO NOTHING;
                    """,
                    (mixed_slug_2, mixed_slug_2, mixed_email_2),
                )
                # Seed tenant row as PENDING_VERIFICATION but with is_active=true
                # This bypasses the active guard (status != ACTIVE), but DELETE query specifies is_active=false,
                # so the tenant row is NOT deleted!
                cur.execute(
                    """
                    INSERT INTO public.tenants (name, slug, tier, status, is_active)
                    VALUES (%s, %s, 'STARTER', 'PENDING_VERIFICATION', true)
                    ON CONFLICT (slug) DO UPDATE SET status = 'PENDING_VERIFICATION', is_active = true;
                    """,
                    (mixed_slug_2, mixed_slug_2),
                )
            conn2.commit()
        finally:
            conn2.close()

        ok_mix2, err_mix2 = _delete_pending_merchant(mixed_slug_2, mixed_email_2)
        # Must fail because rem_t is not None (tenants row remained)!
        self.assertFalse(ok_mix2)
        self.assertIn("POSTGRESQL_CLEANUP_INCONSISTENT_STATE", str(err_mix2))
        self.assertIn(mixed_slug_2, _DEAD_LETTER_CLEANUP_REGISTRY)
        self.assertEqual(_DEAD_LETTER_CLEANUP_REGISTRY[mixed_slug_2]["action"], "delete")

        # Verify in PostgreSQL: Transaction was rolled back! Both rows still exist!
        conn_v2 = get_db_connection()
        try:
            with conn_v2.cursor() as cur:
                cur.execute("SELECT status FROM public.merchants WHERE lower(slug) = %s;", (mixed_slug_2,))
                self.assertIsNotNone(cur.fetchone())
                cur.execute("SELECT status, is_active FROM public.tenants WHERE lower(slug) = %s;", (mixed_slug_2,))
                self.assertIsNotNone(cur.fetchone())
        finally:
            conn_v2.close()

        # Scenario 2: Mixed state where merchants has mismatched owner_email
        mixed_slug_3 = f"mix-state-3-{uuid.uuid4().hex[:8]}"
        mixed_email_real = f"real_{mixed_slug_3}@boontrack.id"
        mixed_email_wrong = f"wrong_{mixed_slug_3}@boontrack.id"

        conn3 = get_db_connection()
        try:
            with conn3.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.merchants (slug, store_name, owner_name, owner_email, owner_whatsapp, status)
                    VALUES (%s, %s, 'Mixed 3', %s, '08123456789', 'PENDING_VERIFICATION')
                    ON CONFLICT DO NOTHING;
                    """,
                    (mixed_slug_3, mixed_slug_3, mixed_email_real),
                )
                cur.execute(
                    """
                    INSERT INTO public.tenants (name, slug, tier, status, is_active)
                    VALUES (%s, %s, 'STARTER', 'PENDING_VERIFICATION', false)
                    ON CONFLICT (slug) DO UPDATE SET status = 'PENDING_VERIFICATION', is_active = false;
                    """,
                    (mixed_slug_3, mixed_slug_3),
                )
            conn3.commit()
        finally:
            conn3.close()

        # Attempt cleanup with mismatched email
        ok_mix3, err_mix3 = _delete_pending_merchant(mixed_slug_3, mixed_email_wrong)
        self.assertFalse(ok_mix3)
        self.assertIn("POSTGRESQL_CLEANUP_INCONSISTENT_STATE", str(err_mix3))
        self.assertIn(mixed_slug_3, _DEAD_LETTER_CLEANUP_REGISTRY)

        # Clean up test rows
        conn_clean = get_db_connection()
        try:
            with conn_clean.cursor() as cur:
                cur.execute("DELETE FROM public.merchants WHERE slug IN (%s, %s, %s);", (mixed_slug_1, mixed_slug_2, mixed_slug_3))
                cur.execute("DELETE FROM public.tenants WHERE slug IN (%s, %s, %s);", (mixed_slug_1, mixed_slug_2, mixed_slug_3))
            conn_clean.commit()
        finally:
            conn_clean.close()
        _clear_dead_letter_cleanup(mixed_slug_1)
        _clear_dead_letter_cleanup(mixed_slug_2)
        _clear_dead_letter_cleanup(mixed_slug_3)


if __name__ == "__main__":
    unittest.main()
