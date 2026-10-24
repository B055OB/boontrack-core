"""tests/test_health_and_readiness.py
Unit & Regression Test Suite for P1 Health & Readiness Probes.

Architectural Guarantees Tested:
1. HTTP Client Timeout Initialization:
   - Configured once during client initialization via ClientOptions(postgrest_client_timeout=SUPABASE_HTTP_TIMEOUT).
   - Never mutates shared session timeout per request.
2. Lightweight Liveness (/health):
   - Strictly zero network calls.
   - Accurately reports 'configured' (or 'unconfigured'), avoiding false 'connected' claims.
   - Always returns HTTP 200 as long as the process event loop is responsive.
3. Truthful & Sanitized Readiness (/ready):
   - Executes genuine dependency check against Supabase ('tenants' table).
   - Returns HTTP 200 only on real successful dependency response.
   - Returns HTTP 503 on connection failure, timeout, unconfigured client, or malformed response.
   - Employs sanitized categories (e.g. DEPENDENCY_UNREACHABLE, DEPENDENCY_TIMEOUT,
     DEPENDENCY_NOT_CONFIGURED, DEPENDENCY_MALFORMED_RESPONSE).
   - Never leaks internal IP addresses, stack traces, or raw exception strings into public JSON.
4. Concurrency & Thread-Pool Safety:
   - Concurrent probes execute safely without race conditions or shared state corruption.
   - NOTE ON THREAD TERMINATION: In Python, cancelling an asyncio task running in asyncio.to_thread()
     does NOT terminate or cancel the underlying OS/worker thread. Safety against thread pool
     exhaustion relies strictly on socket-level bounded HTTP client timeouts (connect=2.5s, read=5.0s),
     which cause the underlying blocking I/O call to raise and return the worker thread cleanly.
5. Zero Telegram Polling:
   - Neither probe triggers Telegram bot polling or getUpdates.
"""

import concurrent.futures
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

os.environ.setdefault("DATABASE_URL", "postgresql://mock_user:mock_pass@localhost:5432/mock_db")
os.environ.setdefault("SUPABASE_URL", "https://mock-supabase.boontrack.io")
os.environ.setdefault("SUPABASE_ANON_KEY", "mock-anon-key-boontrack-2026")
os.environ.setdefault("EVOLUTION_API_KEY", "mock-evolution-key")
os.environ.setdefault("XENDIT_SECRET_KEY", "mock-xendit-secret")
os.environ.setdefault("XENDIT_CALLBACK_TOKEN", "mock-callback-token")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:MOCK_TOKEN_FORMAT_ABCDEF")

from fastapi.testclient import TestClient
import app.main
from app.main import app, supabase_client, SUPABASE_HTTP_TIMEOUT


class TestHealthAndReadinessEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_client_timeout_configured_at_initialization(self):
        """Supabase HTTP client timeout must be configured once at startup using supported ClientOptions."""
        self.assertIsNotNone(supabase_client, "supabase_client should be initialized")
        postgrest_timeout = supabase_client.postgrest.session.timeout

        self.assertIsInstance(
            postgrest_timeout,
            httpx.Timeout,
            f"Expected httpx.Timeout instance, got {type(postgrest_timeout)}"
        )
        self.assertEqual(postgrest_timeout.connect, 2.5)
        self.assertEqual(postgrest_timeout.read, 5.0)
        self.assertEqual(postgrest_timeout.write, 5.0)
        self.assertEqual(postgrest_timeout.pool, 5.0)

        # Verify that querying /ready does NOT mutate or replace this shared session timeout
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-001"}]
        with patch.object(supabase_client, "table") as mock_table:
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            resp = self.client.get("/ready")
            self.assertEqual(resp.status_code, 200)

        self.assertIs(
            supabase_client.postgrest.session.timeout,
            postgrest_timeout,
            "Shared session timeout object was mutated across request execution!"
        )

    def test_health_liveness_strictly_zero_network_calls(self):
        """/health must be lightweight and perform 0 external network calls, returning 'configured'."""
        with patch.object(supabase_client, "table") as mock_table:
            response = self.client.get("/health")
            # Supabase table() should never be touched by /health
            mock_table.assert_not_called()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("service"), "boontrack-core")
        self.assertEqual(data.get("version"), "1.0.0")
        # Accurately reports configuration state without falsely claiming live connectivity
        self.assertEqual(data.get("database", {}).get("supabase"), "configured")

    def test_health_liveness_reports_unconfigured_when_client_missing(self):
        """/health returns HTTP 200 process liveness with 'unconfigured' when client is None."""
        with patch("app.main.supabase_client", None):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get("status"), "healthy")
            self.assertEqual(data.get("database", {}).get("supabase"), "unconfigured")

    def test_ready_returns_200_only_after_real_successful_query(self):
        """/ready returns 200 and 'active' only when dependency query genuinely succeeds."""
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-001"}]
        with patch.object(supabase_client, "table") as mock_table:
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            response = self.client.get("/ready")
            mock_table.assert_called_once_with("tenants")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "ready")
        self.assertEqual(data.get("database", {}).get("supabase"), "active")
        self.assertEqual(data.get("dependencies", {}).get("supabase", {}).get("status"), "active")
        self.assertNotIn("category", data.get("dependencies", {}).get("supabase", {}))

    def test_ready_returns_503_and_sanitized_category_on_connection_error(self):
        """/ready returns 503 and sanitized category without leaking raw internal exception strings."""
        sensitive_raw_error = "FATAL: connection to server at '10.244.15.8', port 5432 failed: Connection refused"
        with patch.object(supabase_client, "table") as mock_table:
            mock_table.return_value.select.return_value.limit.return_value.execute.side_effect = ConnectionError(sensitive_raw_error)
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("supabase"), "unreachable")
        
        dep_supa = data.get("dependencies", {}).get("supabase", {})
        self.assertEqual(dep_supa.get("status"), "unreachable")
        self.assertEqual(dep_supa.get("category"), "DEPENDENCY_UNREACHABLE")

        # Crucial: Raw internal diagnostics, IP addresses, and exceptions must NEVER leak in JSON response
        self.assertNotIn("error", dep_supa)
        self.assertNotIn("10.244.15.8", response.text)
        self.assertNotIn("Connection refused", response.text)
        self.assertNotIn("FATAL", response.text)

    def test_ready_returns_503_and_sanitized_category_on_timeout(self):
        """/ready returns 503 and DEPENDENCY_TIMEOUT on socket timeout without leaking exception info."""
        raw_timeout_msg = "Read socket timed out after 5.0 seconds from https://mock-supabase.boontrack.io"
        with patch.object(supabase_client, "table") as mock_table:
            mock_table.return_value.select.return_value.limit.return_value.execute.side_effect = httpx.ReadTimeout(raw_timeout_msg)
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("supabase"), "timeout")

        dep_supa = data.get("dependencies", {}).get("supabase", {})
        self.assertEqual(dep_supa.get("status"), "timeout")
        self.assertEqual(dep_supa.get("category"), "DEPENDENCY_TIMEOUT")

        # Verify no raw timeout details or URL leakage in response body
        self.assertNotIn("error", dep_supa)
        self.assertNotIn("https://mock-supabase.boontrack.io", response.text)
        self.assertNotIn("Read socket timed out", response.text)

    def test_ready_returns_503_when_client_unconfigured(self):
        """/ready returns 503 and DEPENDENCY_NOT_CONFIGURED when supabase_client is None."""
        with patch("app.main.supabase_client", None):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("supabase"), "unconfigured")
        self.assertEqual(
            data.get("dependencies", {}).get("supabase", {}).get("category"),
            "DEPENDENCY_NOT_CONFIGURED"
        )

    def test_ready_returns_503_on_malformed_response(self):
        """/ready returns 503 and DEPENDENCY_MALFORMED_RESPONSE if PostgREST returns unexpected None payload."""
        mock_res = MagicMock()
        mock_res.data = None
        with patch.object(supabase_client, "table") as mock_table:
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("supabase"), "degraded")
        self.assertEqual(
            data.get("dependencies", {}).get("supabase", {}).get("category"),
            "DEPENDENCY_MALFORMED_RESPONSE"
        )

    def test_concurrent_readiness_probes(self):
        """Verify that concurrent readiness probes execute cleanly without race conditions or shared state corruption."""
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-concurrency-test"}]

        def do_ready_probe():
            return self.client.get("/ready")

        with patch.object(supabase_client, "table") as mock_table:
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            
            # Execute 10 concurrent readiness probes
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(do_ready_probe) for _ in range(10)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]

            # All concurrent probes must succeed with 200 OK and ready status
            self.assertEqual(len(results), 10)
            for res in results:
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json().get("status"), "ready")

        # Now test concurrent failure handling
        with patch.object(supabase_client, "table") as mock_table:
            mock_table.return_value.select.return_value.limit.return_value.execute.side_effect = httpx.ConnectTimeout("connection timed out")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(do_ready_probe) for _ in range(10)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]

            self.assertEqual(len(results), 10)
            for res in results:
                self.assertEqual(res.status_code, 503)
                self.assertEqual(res.json().get("dependencies", {}).get("supabase", {}).get("category"), "DEPENDENCY_TIMEOUT")

    def test_zero_telegram_polling_during_health_and_readiness_probes(self):
        """Neither /health nor /ready probe should ever trigger Telegram bot polling or getUpdates."""
        from aiogram import Dispatcher
        from app.core import server as core_server

        with patch.object(Dispatcher, "start_polling", new_callable=AsyncMock) as mock_aiogram_polling, \
             patch.object(core_server, "start_telegram_polling", new_callable=AsyncMock) as mock_core_polling:

            resp_health = self.client.get("/health")
            resp_ready = self.client.get("/ready")

            self.assertEqual(resp_health.status_code, 200)
            self.assertEqual(mock_aiogram_polling.call_count, 0)
            self.assertEqual(mock_core_polling.call_count, 0)
            mock_aiogram_polling.assert_not_called()
            mock_core_polling.assert_not_called()
