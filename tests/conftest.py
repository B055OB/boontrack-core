"""tests/conftest.py
Global isolated test configuration and fail-fast safety enforcement for BoonTrack Core.

CRITICAL:
- NEVER loads root `.env`.
- Calls `bootstrap_isolated_test_env()` BEFORE importing any `app.*` module.
- Validates disposable PostgreSQL, Redis, and non-production Supabase targets at collection
  and verifies live disposable service availability at `pytest_sessionstart` when required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.core.security.test_isolation_guard import (  # noqa: E402
    assert_disposable_postgres_target,
    assert_disposable_redis_target,
    bootstrap_isolated_test_env,
    is_disposable_services_required,
    validate_isolated_test_environment,
    verify_connected_postgres_is_disposable,
)

# Enforce isolated `.env.test` + driver backstop hooks BEFORE any `app.*` import
bootstrap_isolated_test_env(repo_root=_REPO_ROOT)

# Ensure app.core.config.settings (once imported) matches validated env
try:
    from app.core.config import settings

    settings.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
    settings.POSTGRES_USER = os.getenv("POSTGRES_USER")
    settings.POSTGRES_DB = os.getenv("POSTGRES_DB")
    settings.POSTGRES_PORT = os.getenv("POSTGRES_PORT")
    settings.POSTGRES_HOST = os.getenv("POSTGRES_HOST")
except Exception:
    pass


def pytest_configure(config: pytest.Config) -> None:
    """Re-validate strict isolation targets before collecting any test modules."""
    try:
        validate_isolated_test_environment()
    except Exception as exc:
        pytest.exit(f"[TEST ISOLATION ABORT] {exc}", returncode=2)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Verify disposable PostgreSQL & Redis services are reachable & initialized when mandatory."""
    validate_isolated_test_environment()

    if not is_disposable_services_required():
        return

    # 1. Probe disposable PostgreSQL and verify required schema tables
    try:
        import psycopg2
        from app.core.database import get_db_connection

        assert_disposable_postgres_target(dsn=os.getenv("DATABASE_URL"), allow_if_unconfigured=False)
        conn = get_db_connection()
        try:
            verify_connected_postgres_is_disposable(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name IN ('tenants', 'merchants', 'inbound_webhook_events', 'phone_suppressions');
                    """
                )
                present = {row[0] for row in cur.fetchall()}
                missing = {"tenants", "merchants", "inbound_webhook_events", "phone_suppressions"} - present
                if missing:
                    pytest.exit(
                        "[TEST ISOLATION ABORT] Disposable PostgreSQL missing initialized schema tables: "
                        f"{sorted(missing)}. Run `python scripts/init_test_postgres_schema.py` first.",
                        returncode=2,
                    )
        finally:
            if not conn.closed:
                conn.close()
    except pytest.exit.Exception:
        raise
    except Exception as exc:
        pytest.exit(
            f"[TEST ISOLATION ABORT] Disposable PostgreSQL unavailable under strict service requirement: {exc}",
            returncode=2,
        )

    # 2. Probe disposable Redis
    try:
        import redis as _redis_mod

        redis_url = os.getenv("REDIS_URL") or (
            f"redis://{os.getenv('REDIS_HOST', '127.0.0.1')}:{os.getenv('REDIS_PORT', '56379')}/0"
        )
        assert_disposable_redis_target(redis_url=redis_url, allow_if_unconfigured=False)
        r_client = _redis_mod.Redis.from_url(redis_url, socket_timeout=2.0, socket_connect_timeout=2.0)
        if not r_client.ping():
            pytest.exit("[TEST ISOLATION ABORT] Disposable Redis ping returned False.", returncode=2)
    except pytest.exit.Exception:
        raise
    except Exception as exc:
        pytest.exit(
            f"[TEST ISOLATION ABORT] Disposable Redis unavailable under strict service requirement: {exc}",
            returncode=2,
        )
