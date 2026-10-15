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


# ============================================================================
# 3. Privilege Separation Tests: Supabase Client Least Privilege & RLS
# ============================================================================

def test_main_rejects_service_role_key_as_standard_client():
    """Verifies that app.main refuses to use SUPABASE_SERVICE_ROLE_KEY for the standard client."""
    code = "import app.main"
    proc = _run_isolated_code(code, extra_vars={
        "DATABASE_URL": "postgresql://test_user:test_password@127.0.0.1:5432/test_boontrack",
        "SUPABASE_URL": "https://valid-supabase-url.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "secret-service-role-key-that-must-not-be-default",
    })
    assert proc.returncode != 0
    assert "[SECURITY FAIL-CLOSED]" in proc.stderr
    assert "SUPABASE_SERVICE_ROLE_KEY is strictly prohibited for standard application client" in proc.stderr


def test_main_get_admin_supabase_client_isolation(monkeypatch):
    """Verifies get_admin_supabase_client() raises RuntimeError when SUPABASE_SERVICE_ROLE_KEY is absent."""
    import app.main as main_mod

    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        main_mod.get_admin_supabase_client()
    assert "SUPABASE_SERVICE_ROLE_KEY is required" in str(exc_info.value)


def test_webhook_payment_verified_admin_client_boundary(monkeypatch):
    """Verifies that get_verified_webhook_supabase_client strictly gates admin client acquisition."""
    from app.api.webhook_payment import get_verified_webhook_supabase_client

    monkeypatch.setenv("XENDIT_CALLBACK_TOKEN", "verified_token_12345")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "admin_service_role_key_xyz")
    monkeypatch.setenv("SUPABASE_URL", "https://valid-supabase-url.supabase.co")

    # 1. Missing header -> PermissionError
    with pytest.raises(PermissionError) as exc_missing:
        get_verified_webhook_supabase_client({})
    assert "Invalid or missing x-callback-token" in str(exc_missing.value)

    # 2. Invalid token -> PermissionError
    with pytest.raises(PermissionError) as exc_invalid:
        get_verified_webhook_supabase_client({"x-callback-token": "attacker_fake_token"})
    assert "Invalid or missing x-callback-token" in str(exc_invalid.value)

    # 3. Valid token -> Success (admin client granted)
    admin_client = get_verified_webhook_supabase_client({"x-callback-token": "verified_token_12345"})
    assert admin_client is not None
    assert admin_client.supabase_key == "admin_service_role_key_xyz"


def test_tenant_client_cannot_read_protected_tables_without_valid_session():
    """
    Verifies that a tenant or public client under 'authenticated' role
    cannot read protected tenant-scoped records without an active app.current_tenant_id session.
    """
    admin_conn = get_db_connection()
    try:
        # 1. Seed confidential record under tenant_alpha
        with admin_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO public.staging_alumni_cpm (tenant_id, lead_phone, alumni_name, status)
                VALUES ('tenant_alpha', '62811119999', 'Protected Tenant Record', 'STAGED')
                ON CONFLICT DO NOTHING;
            """)
        admin_conn.commit()

        # 2. Query as non-superuser role 'authenticated' with NO tenant context set
        with admin_conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE authenticated;")
            # Ensure app.current_tenant_id is unconfigured/empty
            cur.execute("SELECT set_config('app.current_tenant_id', '', true);")
            cur.execute("SELECT COUNT(*) FROM public.staging_alumni_cpm WHERE tenant_id = 'tenant_alpha';")
            count = cur.fetchone()[0]

            # RLS MUST enforce zero visibility
            assert count == 0, f"SECURITY AUDIT FAILURE: Anonymous/unset tenant session leaked {count} rows!"
    finally:
        admin_conn.rollback()
        admin_conn.close()

