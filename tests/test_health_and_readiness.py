"""tests/test_health_and_readiness.py
Unit & Regression Test Suite for P1 Health & Readiness Probes (Track A.3.2).

Architectural Guarantees Tested:
1. HTTP Client Timeout Initialization:
   - Configured once during client initialization via ClientOptions(postgrest_client_timeout=SUPABASE_HTTP_TIMEOUT).
   - Never mutates shared session timeout per request.
2. Lightweight Liveness (/health):
   - Strictly zero network / database calls (neither Supabase REST nor PostgreSQL).
   - Accurately reports 'configured' (or 'unconfigured'), avoiding false 'connected' claims.
   - Always returns HTTP 200 as long as the process event loop is responsive.
3. Truthful & Sanitized Dual-Dependency Readiness (/ready):
   - Executes genuine dependency checks against BOTH Supabase REST ('tenants' table)
     AND PostgreSQL (`SET LOCAL statement_timeout = '2500ms'; SELECT 1;` wrapped in
     `asyncio.wait_for(..., timeout=3.0)` with read-only transaction and finally cleanup).
   - Returns HTTP 200 ONLY when BOTH Supabase (`active`) and PostgreSQL (`active`) succeed.
   - Returns HTTP 503 if EITHER Supabase or PostgreSQL fails, times out, is unconfigured,
     or returns a malformed response.
   - Employs sanitized statuses/categories (`unavailable`, `timeout`, `unreachable`, `degraded`,
     `DEPENDENCY_UNAVAILABLE`, `DEPENDENCY_TIMEOUT`, `DEPENDENCY_UNREACHABLE`,
     `DEPENDENCY_NOT_CONFIGURED`, `DEPENDENCY_MALFORMED_RESPONSE`).
   - Never leaks DATABASE_URL, passwords, hostnames, internal IPs, stack traces, or raw
     exception strings into public JSON responses.
4. Concurrency & Resource Hygiene:
   - Cursor and connection are unconditionally closed in finally blocks.
   - Concurrent probes execute safely without race conditions or shared state corruption.
5. Zero Telegram Polling:
   - Neither probe triggers Telegram bot polling or getUpdates.
"""

import concurrent.futures
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

os.environ.setdefault("DATABASE_URL", "postgresql://test_user:test_password@127.0.0.1:5432/test_boontrack")
os.environ.setdefault("SUPABASE_URL", "https://mock.supabase.invalid")
os.environ.setdefault("SUPABASE_ANON_KEY", "mock-anon-key-boontrack-2026")
os.environ.setdefault("EVOLUTION_API_KEY", "mock-evolution-key")
os.environ.setdefault("XENDIT_SECRET_KEY", "mock-xendit-secret")
os.environ.setdefault("XENDIT_CALLBACK_TOKEN", "mock-callback-token")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:MOCK_TOKEN_FORMAT_ABCDEF")

from fastapi.testclient import TestClient
import app.main
from app.main import app, supabase_client, SUPABASE_HTTP_TIMEOUT


def _make_mock_pg_conn(fetchone_value=(1,)):
    """Builds a mock psycopg2 connection + cursor for PostgreSQL readiness probe tests."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_value
    mock_conn = MagicMock()
    mock_conn.closed = 0
    mock_conn.cursor.return_value = mock_cur
    return mock_conn, mock_cur


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
        mock_conn, _ = _make_mock_pg_conn((1,))
        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", return_value=mock_conn):
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            resp = self.client.get("/ready")
            self.assertEqual(resp.status_code, 200)

        self.assertIs(
            supabase_client.postgrest.session.timeout,
            postgrest_timeout,
            "Shared session timeout object was mutated across request execution!"
        )

    def test_health_liveness_strictly_zero_network_and_db_calls(self):
        """/health must be pure liveness HTTP 200 with zero Supabase or PostgreSQL calls."""
        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection") as mock_pg:
            response = self.client.get("/health")
            mock_table.assert_not_called()
            mock_pg.assert_not_called()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("service"), "boontrack-core")
        self.assertEqual(data.get("version"), "1.0.0")
        self.assertEqual(data.get("database", {}).get("supabase"), "configured")

    def test_health_liveness_reports_unconfigured_when_client_missing(self):
        """/health returns HTTP 200 process liveness with 'unconfigured' when client is None."""
        with patch("app.main.supabase_client", None), \
             patch("app.main.get_db_connection") as mock_pg:
            response = self.client.get("/health")
            mock_pg.assert_not_called()
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get("status"), "healthy")
            self.assertEqual(data.get("database", {}).get("supabase"), "unconfigured")

    def test_ready_returns_200_only_when_both_supabase_and_postgres_active(self):
        """/ready returns HTTP 200 only when BOTH Supabase and bounded read-only PG SELECT 1 succeed."""
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-001"}]
        mock_conn, mock_cur = _make_mock_pg_conn((1,))

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", return_value=mock_conn) as mock_get_conn:
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            response = self.client.get("/ready")
            mock_table.assert_called_once_with("tenants")
            mock_get_conn.assert_called_once()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "ready")
        self.assertEqual(data.get("database", {}).get("supabase"), "active")
        self.assertEqual(data.get("database", {}).get("postgres"), "active")
        self.assertEqual(data.get("dependencies", {}).get("supabase", {}).get("status"), "active")
        self.assertEqual(data.get("dependencies", {}).get("postgres", {}).get("status"), "active")
        self.assertNotIn("category", data.get("dependencies", {}).get("supabase", {}))
        self.assertNotIn("category", data.get("dependencies", {}).get("postgres", {}))

        # Verify bounded read-only SQL execution & unconditional cleanup
        mock_conn.set_session.assert_called_once_with(readonly=True, autocommit=False)
        executed_sql = [call.args[0] for call in mock_cur.execute.call_args_list]
        self.assertEqual(executed_sql[0], "SET LOCAL statement_timeout = '2500ms';")
        self.assertEqual(executed_sql[1], "SELECT 1;")
        mock_cur.close.assert_called_once()
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_ready_returns_503_on_postgres_connection_error_without_secret_leakage(self):
        """/ready returns 503 with sanitized status on PG connection error and never leaks DSN/secrets."""
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-001"}]
        secret_dsn_error = (
            "FATAL: password authentication failed for user 'postgres' at "
            "postgresql://postgres:SuperSecretProdPass99!@db.mpluzajlzpregmjwpjqr.supabase.co:5432/postgres"
        )

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", side_effect=RuntimeError(secret_dsn_error)):
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("supabase"), "active")
        self.assertEqual(data.get("database", {}).get("postgres"), "unavailable")

        dep_pg = data.get("dependencies", {}).get("postgres", {})
        self.assertEqual(dep_pg.get("status"), "unavailable")
        self.assertEqual(dep_pg.get("category"), "DEPENDENCY_UNAVAILABLE")

        # Strict zero secret / DSN / hostname leakage assertions
        self.assertNotIn("error", dep_pg)
        self.assertNotIn("SuperSecretProdPass99!", response.text)
        self.assertNotIn("mpluzajlzpregmjwpjqr", response.text)
        self.assertNotIn("postgresql://", response.text)
        self.assertNotIn("password authentication failed", response.text)
        self.assertNotIn("FATAL", response.text)

    def test_ready_returns_503_on_postgres_statement_timeout_and_closes_resources(self):
        """/ready returns 503 and sanitized timeout status when PG statement_timeout triggers."""
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-001"}]
        mock_conn, mock_cur = _make_mock_pg_conn((1,))

        class QueryCanceled(Exception):
            pass

        def exec_side_effect(sql):
            if sql == "SELECT 1;":
                raise QueryCanceled("canceling statement due to statement timeout on host pg-internal.local")

        mock_cur.execute.side_effect = exec_side_effect

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", return_value=mock_conn):
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("postgres"), "timeout")
        self.assertEqual(data.get("dependencies", {}).get("postgres", {}).get("category"), "DEPENDENCY_TIMEOUT")
        self.assertNotIn("pg-internal.local", response.text)
        self.assertNotIn("canceling statement", response.text)
        mock_cur.close.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_ready_returns_503_on_postgres_asyncio_wait_for_timeout(self):
        """/ready enforces asyncio.wait_for timeout bound and returns HTTP 503 'timeout'."""
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-001"}]

        def slow_pg_probe():
            time.sleep(0.25)
            return True

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main._probe_postgres_readiness_sync", side_effect=slow_pg_probe), \
             patch("app.main.POSTGRES_READINESS_TIMEOUT_SECONDS", 0.05):
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("postgres"), "timeout")
        self.assertEqual(data.get("dependencies", {}).get("postgres", {}).get("category"), "DEPENDENCY_TIMEOUT")

    def test_ready_returns_503_on_postgres_malformed_response(self):
        """/ready returns 503 when PostgreSQL SELECT 1 returns unexpected payload."""
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-001"}]
        mock_conn, mock_cur = _make_mock_pg_conn(None)

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", return_value=mock_conn):
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("postgres"), "degraded")
        self.assertEqual(
            data.get("dependencies", {}).get("postgres", {}).get("category"),
            "DEPENDENCY_MALFORMED_RESPONSE"
        )
        mock_cur.close.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_ready_returns_503_and_sanitized_category_on_supabase_connection_error(self):
        """/ready returns 503 when Supabase fails even if PostgreSQL is active, with zero error leakage."""
        sensitive_raw_error = "FATAL: connection to server at '10.244.15.8', port 5432 failed: Connection refused"
        mock_conn, _ = _make_mock_pg_conn((1,))

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", return_value=mock_conn):
            mock_table.return_value.select.return_value.limit.return_value.execute.side_effect = ConnectionError(sensitive_raw_error)
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("supabase"), "unreachable")
        self.assertEqual(data.get("database", {}).get("postgres"), "active")

        dep_supa = data.get("dependencies", {}).get("supabase", {})
        self.assertEqual(dep_supa.get("status"), "unreachable")
        self.assertEqual(dep_supa.get("category"), "DEPENDENCY_UNREACHABLE")

        # Crucial: Raw internal diagnostics, IP addresses, and exceptions must NEVER leak in JSON response
        self.assertNotIn("error", dep_supa)
        self.assertNotIn("10.244.15.8", response.text)
        self.assertNotIn("Connection refused", response.text)
        self.assertNotIn("FATAL", response.text)

    def test_ready_returns_503_and_sanitized_category_on_supabase_timeout(self):
        """/ready returns 503 and DEPENDENCY_TIMEOUT on Supabase socket timeout without leaking info."""
        raw_timeout_msg = "Read socket timed out after 5.0 seconds from https://mock.supabase.invalid"
        mock_conn, _ = _make_mock_pg_conn((1,))

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", return_value=mock_conn):
            mock_table.return_value.select.return_value.limit.return_value.execute.side_effect = httpx.ReadTimeout(raw_timeout_msg)
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("supabase"), "timeout")

        dep_supa = data.get("dependencies", {}).get("supabase", {})
        self.assertEqual(dep_supa.get("status"), "timeout")
        self.assertEqual(dep_supa.get("category"), "DEPENDENCY_TIMEOUT")

        self.assertNotIn("error", dep_supa)
        self.assertNotIn("https://mock.supabase.invalid", response.text)
        self.assertNotIn("Read socket timed out", response.text)

    def test_ready_returns_503_when_supabase_client_unconfigured(self):
        """/ready returns 503 and DEPENDENCY_NOT_CONFIGURED when supabase_client is None."""
        mock_conn, _ = _make_mock_pg_conn((1,))
        with patch("app.main.supabase_client", None), \
             patch("app.main.get_db_connection", return_value=mock_conn):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data.get("status"), "unhealthy")
        self.assertEqual(data.get("database", {}).get("supabase"), "unconfigured")
        self.assertEqual(
            data.get("dependencies", {}).get("supabase", {}).get("category"),
            "DEPENDENCY_NOT_CONFIGURED"
        )

    def test_ready_returns_503_on_supabase_malformed_response(self):
        """/ready returns 503 and DEPENDENCY_MALFORMED_RESPONSE if PostgREST returns unexpected None payload."""
        mock_res = MagicMock()
        mock_res.data = None
        mock_conn, _ = _make_mock_pg_conn((1,))

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", return_value=mock_conn):
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
        """Verify concurrent readiness probes execute cleanly without race conditions or state corruption."""
        mock_res = MagicMock()
        mock_res.data = [{"id": "tenant-concurrency-test"}]

        def do_ready_probe():
            return self.client.get("/ready")

        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", side_effect=lambda: _make_mock_pg_conn((1,))[0]):
            mock_table.return_value.select.return_value.limit.return_value.execute.return_value = mock_res

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(do_ready_probe) for _ in range(10)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]

            self.assertEqual(len(results), 10)
            for res in results:
                self.assertEqual(res.status_code, 200)
                body = res.json()
                self.assertEqual(body.get("status"), "ready")
                self.assertEqual(body.get("database", {}).get("postgres"), "active")
                self.assertEqual(body.get("database", {}).get("supabase"), "active")

        # Concurrent failure handling (Supabase timeout)
        with patch.object(supabase_client, "table") as mock_table, \
             patch("app.main.get_db_connection", side_effect=lambda: _make_mock_pg_conn((1,))[0]):
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
             patch.object(core_server, "start_telegram_polling", new_callable=AsyncMock) as mock_core_polling, \
             patch("app.main.get_db_connection", side_effect=RuntimeError("mock pg offline")):

            resp_health = self.client.get("/health")
            resp_ready = self.client.get("/ready")

            self.assertEqual(resp_health.status_code, 200)
            self.assertEqual(resp_ready.status_code, 503)
            self.assertEqual(mock_aiogram_polling.call_count, 0)
            self.assertEqual(mock_core_polling.call_count, 0)
            mock_aiogram_polling.assert_not_called()
            mock_core_polling.assert_not_called()
