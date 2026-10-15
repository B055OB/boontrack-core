"""tests/test_fail_closed_config_entrypoints.py
Negative Tests for Configuration Entry Points (CTO Audit Compliance).

Verifies fail-closed behavior across:
1. app.core.config.Settings (No default fallback credentials)
2. app.core.database.get_db_connection (Fail-closed on missing credentials or DATABASE_URL)
3. app.core.database.get_tenant_db_connection & tenant_transaction (Fail-closed on missing/empty tenant_id or DB credentials)
4. app.core.server (Fail-closed on missing DATABASE_URL)
5. app.main (Fail-closed on missing Supabase configuration)
6. app.api.webhook_payment (Fail-closed on missing Supabase configuration)
"""

import os
import sys
import subprocess
import pytest

from app.core.config import settings
from app.core.database import (
    get_db_connection,
    get_tenant_db_connection,
    tenant_transaction,
    get_worker_db_connection,
    worker_elevated_transaction,
)


# ============================================================================
# 1. Negative Tests: Database Core In-Process Helpers
# ============================================================================

def test_get_db_connection_fail_closed_when_missing_password(monkeypatch):
    """Verifies get_db_connection raises RuntimeError when POSTGRES_PASSWORD is unset."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", None)

    with pytest.raises(RuntimeError) as exc_info:
        get_db_connection()

    assert "[SECURITY FAIL-CLOSED]" in str(exc_info.value)
    assert "POSTGRES_PASSWORD" in str(exc_info.value)


def test_get_db_connection_fail_closed_when_missing_host(monkeypatch):
    """Verifies get_db_connection raises RuntimeError when POSTGRES_HOST is unset."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.setattr(settings, "POSTGRES_HOST", None)

    with pytest.raises(RuntimeError) as exc_info:
        get_db_connection()

    assert "[SECURITY FAIL-CLOSED]" in str(exc_info.value)
    assert "POSTGRES_HOST" in str(exc_info.value)


def test_get_db_connection_fail_closed_when_missing_user(monkeypatch):
    """Verifies get_db_connection raises RuntimeError when POSTGRES_USER is unset."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.setattr(settings, "POSTGRES_USER", None)

    with pytest.raises(RuntimeError) as exc_info:
        get_db_connection()

    assert "[SECURITY FAIL-CLOSED]" in str(exc_info.value)
    assert "POSTGRES_USER" in str(exc_info.value)


def test_get_db_connection_fail_closed_when_missing_db(monkeypatch):
    """Verifies get_db_connection raises RuntimeError when POSTGRES_DB is unset."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.setattr(settings, "POSTGRES_DB", None)

    with pytest.raises(RuntimeError) as exc_info:
        get_db_connection()

    assert "[SECURITY FAIL-CLOSED]" in str(exc_info.value)
    assert "POSTGRES_DB" in str(exc_info.value)


def test_get_tenant_db_connection_fail_closed_empty_tenant():
    """Verifies get_tenant_db_connection raises ValueError on empty or whitespace tenant_id."""
    with pytest.raises(ValueError) as exc_info_empty:
        get_tenant_db_connection("")
    assert "mandatory" in str(exc_info_empty.value)

    with pytest.raises(ValueError) as exc_info_spaces:
        get_tenant_db_connection("    ")
    assert "mandatory" in str(exc_info_spaces.value)

    with pytest.raises(ValueError) as exc_info_none:
        get_tenant_db_connection(None)
    assert "mandatory" in str(exc_info_none.value)


def test_tenant_transaction_fail_closed_empty_tenant():
    """Verifies tenant_transaction raises ValueError on missing tenant_id."""
    with pytest.raises(ValueError) as exc_info:
        with tenant_transaction(""):
            pass
    assert "mandatory" in str(exc_info.value)


def test_worker_db_connection_fail_closed_missing_credentials(monkeypatch):
    """Verifies worker connection helpers fail closed when DB credentials are unconfigured."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", None)

    with pytest.raises(RuntimeError) as exc_info:
        get_worker_db_connection("test_worker", elevated=False)
    assert "[SECURITY FAIL-CLOSED]" in str(exc_info.value)

    with pytest.raises(RuntimeError) as exc_elevated:
        with worker_elevated_transaction("test_worker"):
            pass
    assert "[SECURITY FAIL-CLOSED]" in str(exc_elevated.value)


# ============================================================================
# 2. Negative Tests: Subprocess Clean-Environment Entrypoints
# ============================================================================

def _run_isolated_code(code_snippet: str, extra_vars=None):
    """Executes python code in an isolated subprocess with stripped env and disabled dotenv."""
    clean_env = os.environ.copy()
    keys_to_remove = [
        "DATABASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    ]
    for key in keys_to_remove:
        clean_env.pop(key, None)
    if extra_vars:
        clean_env.update(extra_vars)

    full_code = "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n" + code_snippet
    return subprocess.run([sys.executable, "-c", full_code], env=clean_env, capture_output=True, text=True)


def test_settings_no_default_credentials_in_clean_env():
    """Verifies that in a clean environment, Settings defaults POSTGRES credentials to None."""
    code = (
        "from app.core.config import settings\n"
        "assert settings.POSTGRES_PASSWORD is None, f'Expected None, got {settings.POSTGRES_PASSWORD}'\n"
        "assert settings.POSTGRES_USER is None, f'Expected None, got {settings.POSTGRES_USER}'\n"
        "assert settings.POSTGRES_DB is None, f'Expected None, got {settings.POSTGRES_DB}'\n"
        "assert settings.POSTGRES_HOST is None, f'Expected None, got {settings.POSTGRES_HOST}'\n"
        "print('CONFIG_DEFAULTS_CLEAN_SUCCESS')\n"
    )
    proc = _run_isolated_code(code)
    assert proc.returncode == 0, f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "CONFIG_DEFAULTS_CLEAN_SUCCESS" in proc.stdout


def test_database_connection_fail_closed_in_clean_env():
    """Verifies that get_db_connection() in a clean environment raises RuntimeError."""
    code = (
        "from app.core.database import get_db_connection\n"
        "get_db_connection()\n"
    )
    proc = _run_isolated_code(code)
    assert proc.returncode != 0
    assert "[SECURITY FAIL-CLOSED]" in proc.stderr
    assert "RuntimeError" in proc.stderr


def test_app_core_server_fail_closed_without_database_url():
    """Verifies that app.core.server fails closed when DATABASE_URL is missing."""
    code = "import app.core.server"
    proc = _run_isolated_code(code)
    assert proc.returncode != 0
    assert "[SECURITY FAIL-CLOSED]" in proc.stderr
    assert "DATABASE_URL is mandatory" in proc.stderr


def test_app_main_fail_closed_without_supabase_url():
    """Verifies that app.main fails closed when SUPABASE_URL is missing."""
    code = "import app.main"
    proc = _run_isolated_code(code, extra_vars={
        "DATABASE_URL": "postgresql://test_user:test_password@127.0.0.1:5432/test_boontrack",
        "SUPABASE_KEY": "some-test-key",
    })
    assert proc.returncode != 0
    assert "[SECURITY FAIL-CLOSED]" in proc.stderr
    assert "SUPABASE_URL" in proc.stderr


def test_app_main_fail_closed_without_supabase_key():
    """Verifies that app.main fails closed when SUPABASE_KEY is missing."""
    code = "import app.main"
    proc = _run_isolated_code(code, extra_vars={
        "DATABASE_URL": "postgresql://test_user:test_password@127.0.0.1:5432/test_boontrack",
        "SUPABASE_URL": "https://valid-supabase-url.supabase.co",
    })
    assert proc.returncode != 0
    assert "[SECURITY FAIL-CLOSED]" in proc.stderr
    assert "SUPABASE_KEY" in proc.stderr


def test_webhook_payment_fail_closed_without_supabase_url():
    """Verifies that app.api.webhook_payment fails closed when SUPABASE_URL is missing."""
    code = "import app.api.webhook_payment"
    proc = _run_isolated_code(code, extra_vars={
        "DATABASE_URL": "postgresql://test_user:test_password@127.0.0.1:5432/test_boontrack",
        "SUPABASE_KEY": "some-test-key",
    })
    assert proc.returncode != 0
    assert "[SECURITY FAIL-CLOSED]" in proc.stderr
    assert "SUPABASE_URL" in proc.stderr


def test_webhook_payment_fail_closed_without_supabase_key():
    """Verifies that app.api.webhook_payment fails closed when SUPABASE_KEY is missing."""
    code = "import app.api.webhook_payment"
    proc = _run_isolated_code(code, extra_vars={
        "DATABASE_URL": "postgresql://test_user:test_password@127.0.0.1:5432/test_boontrack",
        "SUPABASE_URL": "https://valid-supabase-url.supabase.co",
    })
    assert proc.returncode != 0
    assert "[SECURITY FAIL-CLOSED]" in proc.stderr
    assert "SUPABASE_KEY" in proc.stderr
