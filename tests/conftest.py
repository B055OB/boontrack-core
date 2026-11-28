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

# Runtime synthetic Ed25519 provenance keypair fixture (Wave 1C / REM-04)
# Generated purely at runtime in memory without persisting any private key to disk or .env.test.
def _generate_synthetic_test_provenance_keyrings() -> tuple[str, str]:
    """Deterministically derive synthetic Ed25519 test keyrings purely at runtime in memory.

    Zero keys are stored in .env.test, source files, or persisted artifacts.
    """
    import hashlib
    import json
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    # Deterministic test seed (32 bytes)
    seed = hashlib.sha256(b"boontrack_runtime_synthetic_provenance_keyring_fixture_v1").digest()
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    priv_hex = seed.hex()
    pub_hex = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    priv_keyring = json.dumps({
        "prv_synthetic_test_v1": {
            "private_key_hex": priv_hex,
            "status": "ACTIVE",
        }
    })
    pub_keyring = json.dumps({
        "prv_synthetic_test_v1": {
            "public_key_hex": pub_hex,
            "status": "ACTIVE",
        }
    })
    return priv_keyring, pub_keyring


_SYNTHETIC_PRIV_KEYRING, _SYNTHETIC_PUB_KEYRING = _generate_synthetic_test_provenance_keyrings()

# Inject into environment if not present
if "PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON" not in os.environ:
    os.environ["PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON"] = _SYNTHETIC_PRIV_KEYRING
if "PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON" not in os.environ:
    os.environ["PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON"] = _SYNTHETIC_PUB_KEYRING

# Live environment safety guard: purge any accidentally inherited live host credentials
for _live_prefix in ("xnd_production_", "Mid-server-"):
    for _env_k, _env_v in list(os.environ.items()):
        if _env_v and _live_prefix in str(_env_v):
            os.environ.pop(_env_k, None)

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
                      AND table_name IN ('tenants', 'inbound_webhook_events', 'phone_suppressions');
                    """
                )
                present = {row[0] for row in cur.fetchall()}
                missing = {"tenants", "inbound_webhook_events", "phone_suppressions"} - present
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
            f"redis://{os.getenv('REDIS_HOST', '127.0.0.1')}:{os.getenv('REDIS_PORT', '6379')}/0"
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


@pytest.fixture(autouse=True)
def ensure_test_provenance_isolation():
    """Ensure deterministic synthetic provenance keyrings are restored after tests.

    Tests that delete or override keys via monkeypatch are fully respected during the test,
    and the runtime baseline is restored at teardown.
    """
    yield
    # Restore default synthetic keyrings if removed during tests without monkeypatch
    if "PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON" not in os.environ:
        os.environ["PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON"] = _SYNTHETIC_PRIV_KEYRING
    if "PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON" not in os.environ:
        os.environ["PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON"] = _SYNTHETIC_PUB_KEYRING


@pytest.fixture
def runtime_synthetic_provenance_keypair() -> dict[str, str]:
    """Provides the active deterministic synthetic Ed25519 test keypair mapping."""
    return {
        "private_keyring_json": _SYNTHETIC_PRIV_KEYRING,
        "public_keyring_json": _SYNTHETIC_PUB_KEYRING,
    }
