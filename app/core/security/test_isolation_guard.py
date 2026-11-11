"""app/core/security/test_isolation_guard.py
Fail-closed test isolation guards preventing test suites or scripts from ever loading
production `.env` or connecting to production/staging PostgreSQL, Redis, or Supabase targets.

Design Principles:
- Uses stdlib only at module level (safe before any `app.*` import).
- Keyed on explicit test-guard signals (`TEST_STRICT_DB_GUARD=1`, `TEST_REQUIRE_DISPOSABLE_SERVICES=1`,
  `pytest` in `sys.modules`, or direct `test_*.py` script execution), NEVER disabled when a test
  temporarily patches `APP_ENV="production"` for fail-closed behavioral checks.
- Preserves missing-credential fail-closed `RuntimeError` ordering for config-entrypoint tests.
"""

from __future__ import annotations

import functools
import ipaddress
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, NoReturn, Optional, Tuple
from urllib.parse import parse_qs, urlparse

_FORBIDDEN_TARGET_MARKERS = (
    "mpluzajlzpregmjwpjqr",
    "xkhqirhurnjqglmajghn",
    "pooler.supabase.com",
    ".supabase.co",
    ".supabase.com",
    "railway.app",
    "rlwy.net",
    "rds.amazonaws.com",
    "neon.tech",
)

_ALLOWLIST_PG_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_ALLOWLIST_REDIS_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_docker_internal_net() -> bool:
    return os.getenv("TEST_IN_DOCKER_INTERNAL_NET", "").strip() == "1"


def _allowed_pg_hosts() -> frozenset[str]:
    if _is_docker_internal_net():
        return _ALLOWLIST_PG_HOSTS | {"test-postgres"}
    return _ALLOWLIST_PG_HOSTS


def _allowed_redis_hosts() -> frozenset[str]:
    if _is_docker_internal_net():
        return _ALLOWLIST_REDIS_HOSTS | {"test-redis"}
    return _ALLOWLIST_REDIS_HOSTS


_ALLOWLIST_SUPABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_DISPOSABLE_DB_NAME_RE = re.compile(r"^(test_boontrack|bt_.*_test_[a-z0-9_]+)$")
_DISPOSABLE_SUPABASE_INVALID_HOST_RE = re.compile(r"^[a-z0-9-]+\.supabase\.invalid$")

_HOOKS_INSTALLED = False
_BOOTSTRAPPED = False
_ORIGINAL_DOTENV_LOAD: Any = None


class TestIsolationViolation(RuntimeError):
    """Raised when test isolation, target allowlist, or disposable-DB invariants are violated."""


def is_strict_test_guard_active() -> bool:
    """Returns True whenever strict disposable-target test isolation must be enforced."""
    if os.getenv("TEST_STRICT_DB_GUARD", "").strip() == "1":
        return True
    if os.getenv("TEST_REQUIRE_DISPOSABLE_SERVICES", "").strip() == "1":
        return True
    if "pytest" in sys.modules:
        return True
    if sys.argv and sys.argv[0]:
        script_name = os.path.basename(sys.argv[0])
        if script_name.startswith("test_") and script_name.endswith(".py"):
            return True
    return False


def is_disposable_services_required() -> bool:
    """Returns True when live disposable PG & Redis services are mandatory (no silent skip)."""
    if os.getenv("CI", "").strip().lower() in ("1", "true", "yes"):
        return True
    return os.getenv("TEST_REQUIRE_DISPOSABLE_SERVICES", "").strip() == "1"


def safe_load_dotenv(*args: Any, **kwargs: Any) -> bool:
    """Wrapper replacing bare `dotenv.load_dotenv()` across app and scripts.

    Under active test isolation, refuses to load root `.env` (only `.env.test` may be loaded),
    while preserving dynamic `dotenv.load_dotenv` resolution outside strict test guard.
    """
    import dotenv  # Dynamic lookup preserves subprocess monkeypatching (e.g. test_fail_closed_config_entrypoints)

    if is_strict_test_guard_active():
        candidate_path = args[0] if args else kwargs.get("dotenv_path")
        if candidate_path and os.path.basename(str(candidate_path)) == ".env.test":
            fn = _ORIGINAL_DOTENV_LOAD or dotenv.load_dotenv
            return bool(fn(*args, **kwargs))
        return False

    fn = _ORIGINAL_DOTENV_LOAD or dotenv.load_dotenv
    return bool(fn(*args, **kwargs))


def _contains_forbidden_marker(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    lower = str(value).strip().lower()
    for marker in _FORBIDDEN_TARGET_MARKERS:
        if marker in lower:
            return marker
    return None


def _parse_libpq_dsn(raw: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for token in re.findall(r"(\w+)\s*=\s*(?:'([^']*)'|(\S+))", raw):
        k, v1, v2 = token
        parsed[k.lower()] = v1 if v1 != "" else v2
    return parsed


def assert_disposable_postgres_target(
    dsn: Optional[str] = None,
    *,
    host: Optional[str] = None,
    port: Optional[Any] = None,
    dbname: Optional[str] = None,
    user: Optional[str] = None,
    allow_if_unconfigured: bool = True,
) -> None:
    """Validates that a PostgreSQL connection target points strictly to a disposable test DB.

    When `allow_if_unconfigured=True` and credentials are completely absent, returns cleanly so
    standard `[SECURITY FAIL-CLOSED]` missing-credential RuntimeError checks execute as expected.
    """
    if not is_strict_test_guard_active():
        return

    raw_dsn = str(dsn).strip() if dsn is not None else ""
    if raw_dsn.startswith("sqlite:"):
        return

    if allow_if_unconfigured and not raw_dsn and not (host or dbname or user):
        return

    resolved_host = (host or "").strip()
    resolved_db = (dbname or "").strip()
    resolved_user = (user or "").strip()

    if raw_dsn:
        marker = _contains_forbidden_marker(raw_dsn)
        if marker:
            raise TestIsolationViolation(
                f"[TEST ISOLATION GUARD] Forbidden non-disposable PostgreSQL target marker '{marker}' in DSN."
            )
        if "://" in raw_dsn:
            u = urlparse(raw_dsn)
            scheme = (u.scheme or "").lower()
            if not (scheme == "postgres" or scheme.startswith("postgresql")):
                raise TestIsolationViolation(f"[TEST ISOLATION GUARD] Invalid PostgreSQL DSN scheme: '{scheme}'.")
            qs = parse_qs(u.query or "")
            for qk in ("hostaddr", "host"):
                for qv in qs.get(qk, ()):
                    qv_clean = qv.strip()
                    if not qv_clean:
                        continue
                    q_marker = _contains_forbidden_marker(qv_clean)
                    if q_marker:
                        raise TestIsolationViolation(
                            f"[TEST ISOLATION GUARD] Forbidden non-disposable PostgreSQL query {qk} marker '{q_marker}'."
                        )
                    if qv_clean.lower() not in _allowed_pg_hosts():
                        raise TestIsolationViolation(
                            f"[TEST ISOLATION GUARD] Non-allowlisted PostgreSQL query {qk} '{qv_clean}'."
                        )
            for qdb in qs.get("dbname", ()):
                qdb_clean = qdb.strip()
                if qdb_clean and not _DISPOSABLE_DB_NAME_RE.match(qdb_clean):
                    raise TestIsolationViolation(
                        f"[TEST ISOLATION GUARD] Non-disposable PostgreSQL query dbname '{qdb_clean}'."
                    )
            for quser in qs.get("user", ()):
                quser_marker = _contains_forbidden_marker(quser.strip())
                if quser_marker:
                    raise TestIsolationViolation(
                        f"[TEST ISOLATION GUARD] Forbidden PostgreSQL query user marker '{quser_marker}'."
                    )
            q_host = (qs.get("host") or qs.get("hostaddr") or [""])[0].strip()
            q_db = (qs.get("dbname") or [""])[0].strip()
            q_user = (qs.get("user") or [""])[0].strip()
            resolved_host = (u.hostname or q_host or resolved_host).strip()
            resolved_db = (u.path or "").lstrip("/").strip() or q_db or resolved_db
            resolved_user = (u.username or q_user or resolved_user).strip()
        else:
            kw = _parse_libpq_dsn(raw_dsn)
            resolved_host = (kw.get("host") or kw.get("hostaddr") or resolved_host).strip()
            resolved_db = (kw.get("dbname") or resolved_db).strip()
            resolved_user = (kw.get("user") or resolved_user).strip()

    for field_name, field_val in (("host", resolved_host), ("dbname", resolved_db), ("user", resolved_user)):
        marker = _contains_forbidden_marker(field_val)
        if marker:
            raise TestIsolationViolation(
                f"[TEST ISOLATION GUARD] Forbidden non-disposable PostgreSQL {field_name} ('{marker}')."
            )

    if allow_if_unconfigured and (not resolved_host or not resolved_db):
        return

    clean_host = resolved_host.lower()
    if clean_host not in _allowed_pg_hosts():
        raise TestIsolationViolation(
            f"[TEST ISOLATION GUARD] Non-allowlisted PostgreSQL host '{resolved_host}'. "
            f"Allowed disposable hosts: {sorted(_ALLOWLIST_PG_HOSTS)}."
        )

    if not _DISPOSABLE_DB_NAME_RE.match(resolved_db):
        raise TestIsolationViolation(
            f"[TEST ISOLATION GUARD] Non-disposable PostgreSQL database name '{resolved_db}'. "
            f"Database must match '{_DISPOSABLE_DB_NAME_RE.pattern}' (bare 'postgres' is prohibited)."
        )


def assert_disposable_redis_target(
    redis_url: Optional[str] = None,
    *,
    host: Optional[str] = None,
    allow_if_unconfigured: bool = True,
) -> None:
    """Validates that a Redis target points strictly to loopback or disposable test-redis container."""
    if not is_strict_test_guard_active():
        return

    raw_url = str(redis_url).strip() if redis_url is not None else ""
    clean_host = (host or "").strip()

    if raw_url:
        marker = _contains_forbidden_marker(raw_url)
        if marker:
            raise TestIsolationViolation(
                f"[TEST ISOLATION GUARD] Forbidden Redis URL marker '{marker}'."
            )
        u = urlparse(raw_url)
        clean_host = (u.hostname or clean_host).strip()

    if allow_if_unconfigured and not raw_url and not clean_host:
        return

    if clean_host.lower() not in _allowed_redis_hosts():
        raise TestIsolationViolation(
            f"[TEST ISOLATION GUARD] Non-allowlisted Redis host '{clean_host}'. "
            f"Allowed hosts: {sorted(_ALLOWLIST_REDIS_HOSTS)}."
        )


def assert_disposable_supabase_url(url: Optional[str], *, allow_empty: bool = True) -> None:
    """Validates that Supabase HTTP URL never points to production/staging cloud endpoints."""
    if not is_strict_test_guard_active():
        return

    raw = str(url or "").strip()
    if not raw:
        if allow_empty:
            return
        raise TestIsolationViolation("[TEST ISOLATION GUARD] Empty SUPABASE_URL.")

    marker = _contains_forbidden_marker(raw)
    if marker:
        raise TestIsolationViolation(
            f"[TEST ISOLATION GUARD] Forbidden production/staging Supabase marker '{marker}' in SUPABASE_URL."
        )

    u = urlparse(raw)
    hostname = (u.hostname or "").strip().lower()
    if hostname in _ALLOWLIST_SUPABASE_HOSTS or _DISPOSABLE_SUPABASE_INVALID_HOST_RE.match(hostname):
        return

    raise TestIsolationViolation(
        f"[TEST ISOLATION GUARD] Non-allowlisted Supabase host '{hostname}'. "
        "Allowed targets: 127.0.0.1, localhost, or *.supabase.invalid."
    )


_PG_TX_IDLE = 0
_PG_TX_ACTIVE = 1
_PG_TX_INTRANS = 2
_PG_TX_INERROR = 3
_PG_TX_UNKNOWN = 4
_PG_TX_STATUS_NAMES = {
    _PG_TX_IDLE: "IDLE",
    _PG_TX_ACTIVE: "ACTIVE",
    _PG_TX_INTRANS: "INTRANS",
    _PG_TX_INERROR: "INERROR",
    _PG_TX_UNKNOWN: "UNKNOWN",
}


def _close_unverified_connection(conn: Any) -> Optional[Exception]:
    """Closes a PostgreSQL connection fail-closed, returning any close error instead of swallowing it."""
    try:
        if conn is not None and not bool(getattr(conn, "closed", False)):
            conn.close()
    except Exception as close_exc:
        return close_exc
    return None


def _fail_closed_pg_verification(
    conn: Any,
    message: str,
    *,
    cause: Optional[Exception] = None,
) -> NoReturn:
    """Closes an unverified or unsafe connection and raises TestIsolationViolation."""
    close_exc = _close_unverified_connection(conn)
    if close_exc is None and isinstance(cause, TestIsolationViolation):
        raise cause
    full_message = message if close_exc is None else f"{message} (close failed: {close_exc})"
    if cause is not None:
        raise TestIsolationViolation(full_message) from cause
    raise TestIsolationViolation(full_message)


def _inspect_pg_connection_state(conn: Any) -> Tuple[bool, int]:
    """Reads `(autocommit, libpq_transaction_status)` without mutating connection state."""
    if conn is None or bool(getattr(conn, "closed", True)):
        raise TestIsolationViolation(
            "[TEST ISOLATION GUARD] Refusing verification on null or closed PostgreSQL connection."
        )

    autocommit = getattr(conn, "autocommit", None)
    if not isinstance(autocommit, bool):
        _fail_closed_pg_verification(
            conn,
            f"[TEST ISOLATION GUARD] Refusing verification on connection with non-boolean autocommit ({autocommit!r}).",
        )

    raw_status: Any = None
    get_tx_status = getattr(conn, "get_transaction_status", None)
    if callable(get_tx_status):
        try:
            raw_status = get_tx_status()
        except Exception as exc:
            _fail_closed_pg_verification(
                conn,
                f"[TEST ISOLATION GUARD] Failed inspecting PostgreSQL transaction status: {exc}",
                cause=exc,
            )
    else:
        info = getattr(conn, "info", None)
        if info is not None:
            try:
                raw_status = getattr(info, "transaction_status", None)
            except Exception as exc:
                _fail_closed_pg_verification(
                    conn,
                    f"[TEST ISOLATION GUARD] Failed inspecting PostgreSQL connection info status: {exc}",
                    cause=exc,
                )

    if isinstance(raw_status, bool) or not isinstance(raw_status, int):
        _fail_closed_pg_verification(
            conn,
            f"[TEST ISOLATION GUARD] Unable to inspect PostgreSQL transaction status ({raw_status!r}).",
        )

    tx_status = int(raw_status)
    if tx_status not in _PG_TX_STATUS_NAMES:
        _fail_closed_pg_verification(
            conn,
            f"[TEST ISOLATION GUARD] Unexpected PostgreSQL transaction status code ({tx_status}).",
        )

    return autocommit, tx_status


def verify_connected_postgres_is_disposable(conn: Any) -> None:
    """Server-side guard verifying an open psycopg2 connection targets a disposable DB.

    Inspects initial transaction state and preserves caller-owned transactions:
    - Starts IDLE + autocommit=False: closes only the verification transaction via rollback()
      and verifies return to IDLE.
    - Starts IDLE + autocommit=True: leaves connection in IDLE without rollback().
    - Starts INTRANS (caller-owned transaction): leaves transaction intact without rollback()
      or autocommit mutation.
    - Fails closed on ACTIVE, INERROR, UNKNOWN, or unreadable connection states.
    """
    if not is_strict_test_guard_active():
        return

    initial_autocommit, initial_status = _inspect_pg_connection_state(conn)
    if initial_status not in (_PG_TX_IDLE, _PG_TX_INTRANS):
        status_label = _PG_TX_STATUS_NAMES[initial_status]
        _fail_closed_pg_verification(
            conn,
            f"[TEST ISOLATION GUARD] Refusing verification in unsafe initial PostgreSQL transaction state '{status_label}'.",
        )

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), coalesce(inet_server_addr()::text, 'local-socket');")
            row = cur.fetchone()
    except TestIsolationViolation as exc:
        _fail_closed_pg_verification(conn, str(exc), cause=exc)
    except Exception as exc:
        _fail_closed_pg_verification(
            conn,
            f"[TEST ISOLATION GUARD] Failed server-side disposable DB verification: {exc}",
            cause=exc,
        )

    if not row or len(row) < 2:
        _fail_closed_pg_verification(
            conn,
            "[TEST ISOLATION GUARD] Server-side disposable DB verification returned empty identity row.",
        )

    actual_db = str(row[0] if row[0] is not None else "").strip()
    server_addr = str(row[1] if row[1] is not None else "").strip()

    if not _DISPOSABLE_DB_NAME_RE.match(actual_db):
        _fail_closed_pg_verification(
            conn,
            f"[TEST ISOLATION GUARD] Refusing operation on non-disposable server database '{actual_db}'.",
        )

    if server_addr and server_addr != "local-socket":
        ip_str = server_addr.split("/", 1)[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            ip_obj = None

        in_docker_net = _is_docker_internal_net()
        allowed_ip = bool(
            ip_obj is not None
            and (ip_obj.is_loopback or (in_docker_net and ip_obj.is_private))
        )
        if not allowed_ip:
            _fail_closed_pg_verification(
                conn,
                f"[TEST ISOLATION GUARD] Refusing connection to non-local PostgreSQL server IP '{server_addr}'.",
            )

    post_autocommit, post_status = _inspect_pg_connection_state(conn)
    if post_autocommit != initial_autocommit:
        _fail_closed_pg_verification(
            conn,
            f"[TEST ISOLATION GUARD] Unexpected autocommit mutation during verification: {initial_autocommit} -> {post_autocommit}.",
        )

    if initial_status == _PG_TX_IDLE and not initial_autocommit:
        if post_status == _PG_TX_INTRANS:
            try:
                conn.rollback()
            except Exception as rb_exc:
                _fail_closed_pg_verification(
                    conn,
                    f"[TEST ISOLATION GUARD] Failed to restore IDLE transaction state after verification: {rb_exc}",
                    cause=rb_exc,
                )
        elif post_status != _PG_TX_IDLE:
            status_label = _PG_TX_STATUS_NAMES[post_status]
            _fail_closed_pg_verification(
                conn,
                f"[TEST ISOLATION GUARD] Unexpected post-SELECT PostgreSQL transaction state '{status_label}'.",
            )

        restored_autocommit, restored_status = _inspect_pg_connection_state(conn)
        if restored_autocommit is not False or restored_status != _PG_TX_IDLE:
            status_label = _PG_TX_STATUS_NAMES[restored_status]
            _fail_closed_pg_verification(
                conn,
                f"[TEST ISOLATION GUARD] Connection did not return to IDLE cleanly (state='{status_label}', autocommit={restored_autocommit}).",
            )
    elif initial_status == _PG_TX_IDLE and initial_autocommit:
        if post_status != _PG_TX_IDLE:
            status_label = _PG_TX_STATUS_NAMES[post_status]
            _fail_closed_pg_verification(
                conn,
                f"[TEST ISOLATION GUARD] Unexpected active transaction '{status_label}' after SELECT under autocommit=True.",
            )
    elif initial_status == _PG_TX_INTRANS:
        if post_status != _PG_TX_INTRANS:
            status_label = _PG_TX_STATUS_NAMES[post_status]
            _fail_closed_pg_verification(
                conn,
                f"[TEST ISOLATION GUARD] Caller-owned INTRANS transaction transitioned unexpectedly to '{status_label}'.",
            )


def validate_isolated_test_environment() -> None:
    """Fail-fast validation of all database, cache, Supabase, and disallowed backup/staging env vars."""
    if not is_strict_test_guard_active():
        return

    for forbidden_var in ("STAGING_DATABASE_URL", "SUPABASE_DB_URL"):
        if os.getenv(forbidden_var, "").strip():
            raise TestIsolationViolation(
                f"[TEST ISOLATION GUARD] Forbidden environment variable '{forbidden_var}' must be empty in test mode."
            )

    db_url = os.getenv("DATABASE_URL", "").strip()
    if db_url:
        assert_disposable_postgres_target(dsn=db_url, allow_if_unconfigured=False)

    pg_host = os.getenv("POSTGRES_HOST", "").strip()
    pg_db = os.getenv("POSTGRES_DB", "").strip()
    pg_user = os.getenv("POSTGRES_USER", "").strip()
    if pg_host or pg_db or pg_user:
        assert_disposable_postgres_target(
            host=pg_host,
            dbname=pg_db,
            user=pg_user,
            allow_if_unconfigured=False,
        )

    for extra_dsn_var in (
        "STAGE1_TEST_DISPOSABLE_PG_DSN",
        "STAGE3_STEP0_DISPOSABLE_PG_DSN",
        "STAGE3_STEP1_DISPOSABLE_PG_DSN",
    ):
        val = os.getenv(extra_dsn_var, "").strip()
        if val:
            assert_disposable_postgres_target(dsn=val, allow_if_unconfigured=False)

    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        assert_disposable_redis_target(redis_url=redis_url, allow_if_unconfigured=False)
    for r_host_var in ("REDIS_HOST", "REDISHOST"):
        r_host = os.getenv(r_host_var, "").strip()
        if r_host:
            assert_disposable_redis_target(host=r_host, allow_if_unconfigured=False)

    for sb_var in ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL", "EXPECTED_SUPABASE_URL"):
        sb_val = os.getenv(sb_var, "").strip()
        if sb_val:
            assert_disposable_supabase_url(sb_val, allow_empty=False)


def _extract_pg_args(args: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    dsn = args[0] if args else kwargs.get("dsn")
    return {
        "dsn": dsn,
        "host": kwargs.get("host") or kwargs.get("hostaddr"),
        "dbname": kwargs.get("dbname") or kwargs.get("database"),
        "user": kwargs.get("user"),
    }


def install_driver_isolation_hooks() -> None:
    """Idempotently installs socket-level backstop hooks on DB/Redis/Supabase constructors."""
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    _HOOKS_INSTALLED = True

    # 1. psycopg2 & pools
    try:
        import psycopg2
        import psycopg2.pool

        orig_pg2_connect = psycopg2.connect
        if not getattr(orig_pg2_connect, "_bt_guarded", False):

            @functools.wraps(orig_pg2_connect)
            def guarded_pg2_connect(*args: Any, **kwargs: Any) -> Any:
                if is_strict_test_guard_active():
                    info = _extract_pg_args(args, kwargs)
                    assert_disposable_postgres_target(
                        dsn=info["dsn"],
                        host=info["host"],
                        dbname=info["dbname"],
                        user=info["user"],
                        allow_if_unconfigured=False,
                    )
                return orig_pg2_connect(*args, **kwargs)

            guarded_pg2_connect._bt_guarded = True  # type: ignore[attr-defined]
            psycopg2.connect = guarded_pg2_connect

        for pool_cls in (psycopg2.pool.SimpleConnectionPool, psycopg2.pool.ThreadedConnectionPool):
            orig_pool_init = pool_cls.__init__
            if not getattr(orig_pool_init, "_bt_guarded", False):

                @functools.wraps(orig_pool_init)
                def _make_pool_init(orig_fn: Any) -> Any:
                    @functools.wraps(orig_fn)
                    def guarded_pool_init(self: Any, minconn: Any, maxconn: Any, *args: Any, **kwargs: Any) -> None:
                        if is_strict_test_guard_active():
                            info = _extract_pg_args(args, kwargs)
                            assert_disposable_postgres_target(
                                dsn=info["dsn"],
                                host=info["host"],
                                dbname=info["dbname"],
                                user=info["user"],
                                allow_if_unconfigured=False,
                            )
                        return orig_fn(self, minconn, maxconn, *args, **kwargs)

                    guarded_pool_init._bt_guarded = True  # type: ignore[attr-defined]
                    return guarded_pool_init

                pool_cls.__init__ = _make_pool_init(orig_pool_init)  # type: ignore[method-assign]
    except Exception:
        pass

    # 2. psycopg (v3)
    try:
        import psycopg

        orig_pg3_connect = psycopg.connect
        if not getattr(orig_pg3_connect, "_bt_guarded", False):

            @functools.wraps(orig_pg3_connect)
            def guarded_pg3_connect(*args: Any, **kwargs: Any) -> Any:
                if is_strict_test_guard_active():
                    conninfo = args[0] if args else kwargs.get("conninfo")
                    assert_disposable_postgres_target(
                        dsn=conninfo,
                        host=kwargs.get("host"),
                        dbname=kwargs.get("dbname"),
                        user=kwargs.get("user"),
                        allow_if_unconfigured=False,
                    )
                return orig_pg3_connect(*args, **kwargs)

            guarded_pg3_connect._bt_guarded = True  # type: ignore[attr-defined]
            psycopg.connect = guarded_pg3_connect  # type: ignore[assignment]

        orig_pg3_async = psycopg.AsyncConnection.connect
        if not getattr(orig_pg3_async, "_bt_guarded", False):

            @functools.wraps(orig_pg3_async)
            async def guarded_pg3_async(*args: Any, **kwargs: Any) -> Any:
                if is_strict_test_guard_active():
                    conninfo = args[0] if args else kwargs.get("conninfo")
                    assert_disposable_postgres_target(
                        dsn=conninfo,
                        host=kwargs.get("host"),
                        dbname=kwargs.get("dbname"),
                        user=kwargs.get("user"),
                        allow_if_unconfigured=False,
                    )
                return await orig_pg3_async(*args, **kwargs)

            guarded_pg3_async._bt_guarded = True  # type: ignore[attr-defined]
            psycopg.AsyncConnection.connect = guarded_pg3_async  # type: ignore[assignment]
    except Exception:
        pass

    # 3. asyncpg
    try:
        import asyncpg

        orig_apg_connect = asyncpg.connect
        if not getattr(orig_apg_connect, "_bt_guarded", False):

            @functools.wraps(orig_apg_connect)
            async def guarded_apg_connect(*args: Any, **kwargs: Any) -> Any:
                if is_strict_test_guard_active():
                    dsn = args[0] if args else kwargs.get("dsn")
                    assert_disposable_postgres_target(
                        dsn=dsn,
                        host=kwargs.get("host"),
                        dbname=kwargs.get("database"),
                        user=kwargs.get("user"),
                        allow_if_unconfigured=False,
                    )
                return await orig_apg_connect(*args, **kwargs)

            guarded_apg_connect._bt_guarded = True  # type: ignore[attr-defined]
            asyncpg.connect = guarded_apg_connect

        orig_apg_pool = asyncpg.create_pool
        if not getattr(orig_apg_pool, "_bt_guarded", False):

            @functools.wraps(orig_apg_pool)
            async def guarded_apg_pool(*args: Any, **kwargs: Any) -> Any:
                if is_strict_test_guard_active():
                    dsn = args[0] if args else kwargs.get("dsn")
                    assert_disposable_postgres_target(
                        dsn=dsn,
                        host=kwargs.get("host"),
                        dbname=kwargs.get("database"),
                        user=kwargs.get("user"),
                        allow_if_unconfigured=False,
                    )
                return await orig_apg_pool(*args, **kwargs)

            guarded_apg_pool._bt_guarded = True  # type: ignore[attr-defined]
            asyncpg.create_pool = guarded_apg_pool
    except Exception:
        pass

    # 4. SQLAlchemy create_engine & create_async_engine (permits sqlite:///:memory:)
    try:
        import sqlalchemy
        import sqlalchemy.ext.asyncio

        orig_create_engine = sqlalchemy.create_engine
        if not getattr(orig_create_engine, "_bt_guarded", False):

            @functools.wraps(orig_create_engine)
            def guarded_create_engine(url: Any, *args: Any, **kwargs: Any) -> Any:
                if is_strict_test_guard_active():
                    assert_disposable_postgres_target(dsn=str(url), allow_if_unconfigured=False)
                return orig_create_engine(url, *args, **kwargs)

            guarded_create_engine._bt_guarded = True  # type: ignore[attr-defined]
            sqlalchemy.create_engine = guarded_create_engine

        orig_create_async = sqlalchemy.ext.asyncio.create_async_engine
        if not getattr(orig_create_async, "_bt_guarded", False):

            @functools.wraps(orig_create_async)
            def guarded_create_async(url: Any, *args: Any, **kwargs: Any) -> Any:
                if is_strict_test_guard_active():
                    assert_disposable_postgres_target(dsn=str(url), allow_if_unconfigured=False)
                return orig_create_async(url, *args, **kwargs)

            guarded_create_async._bt_guarded = True  # type: ignore[attr-defined]
            sqlalchemy.ext.asyncio.create_async_engine = guarded_create_async
    except Exception:
        pass

    # 5. Redis sync & async
    try:
        import redis
        import redis.asyncio as aioredis

        for r_cls in (redis.Redis, redis.StrictRedis, aioredis.Redis, redis.ConnectionPool, aioredis.ConnectionPool):
            orig_from_url = r_cls.from_url.__func__ if hasattr(r_cls.from_url, "__func__") else r_cls.from_url
            if not getattr(orig_from_url, "_bt_guarded", False):

                @classmethod  # type: ignore[misc]
                def _guarded_from_url(cls: Any, url: str, *args: Any, _orig: Any = orig_from_url, **kwargs: Any) -> Any:
                    if is_strict_test_guard_active():
                        assert_disposable_redis_target(redis_url=url, allow_if_unconfigured=False)
                    return _orig(cls, url, *args, **kwargs)

                _guarded_from_url.__func__._bt_guarded = True  # type: ignore[attr-defined]
                r_cls.from_url = _guarded_from_url  # type: ignore[method-assign]

            if r_cls in (redis.ConnectionPool, aioredis.ConnectionPool):
                continue

            orig_init = r_cls.__init__
            if not getattr(orig_init, "_bt_guarded", False):

                def _make_redis_init(orig_fn: Any) -> Any:
                    @functools.wraps(orig_fn)
                    def guarded_redis_init(self: Any, *args: Any, **kwargs: Any) -> None:
                        if is_strict_test_guard_active():
                            pool = kwargs.get("connection_pool")
                            if pool is not None and hasattr(pool, "connection_kwargs"):
                                host_val = pool.connection_kwargs.get("host", "localhost")
                            else:
                                host_val = kwargs.get("host") or (args[0] if args and isinstance(args[0], str) else "localhost")
                            assert_disposable_redis_target(host=str(host_val), allow_if_unconfigured=False)
                        return orig_fn(self, *args, **kwargs)

                    guarded_redis_init._bt_guarded = True  # type: ignore[attr-defined]
                    return guarded_redis_init

                r_cls.__init__ = _make_redis_init(orig_init)  # type: ignore[method-assign]
    except Exception:
        pass

    # 6. Supabase client factories
    try:
        import supabase

        orig_sb = supabase.create_client
        if not getattr(orig_sb, "_bt_guarded", False):

            @functools.wraps(orig_sb)
            def guarded_create_client(supabase_url: str, supabase_key: str, *args: Any, **kwargs: Any) -> Any:
                if is_strict_test_guard_active():
                    assert_disposable_supabase_url(supabase_url, allow_empty=False)
                return orig_sb(supabase_url, supabase_key, *args, **kwargs)

            guarded_create_client._bt_guarded = True  # type: ignore[attr-defined]
            supabase.create_client = guarded_create_client

        if hasattr(supabase, "acreate_client"):
            orig_asb = supabase.acreate_client
            if not getattr(orig_asb, "_bt_guarded", False):

                @functools.wraps(orig_asb)
                async def guarded_acreate_client(supabase_url: str, supabase_key: str, *args: Any, **kwargs: Any) -> Any:
                    if is_strict_test_guard_active():
                        assert_disposable_supabase_url(supabase_url, allow_empty=False)
                    return await orig_asb(supabase_url, supabase_key, *args, **kwargs)

                guarded_acreate_client._bt_guarded = True  # type: ignore[attr-defined]
                supabase.acreate_client = guarded_acreate_client
    except Exception:
        pass


def bootstrap_isolated_test_env(repo_root: Optional[Path] = None) -> None:
    """Enforces isolated synthetic test environment BEFORE any `app.*` module imports.

    - Never reads root `.env`.
    - Reads `.env.test` (in CI honors already-configured disposable CI env vars; locally overrides
      any inherited shell / `.env` values cleanly).
    - Wraps `dotenv.load_dotenv` inside the current process so module-level `load_dotenv()` calls
      never leak `.env`.
    - Installs socket/constructor hooks on DB/Redis/Supabase drivers.
    """
    global _BOOTSTRAPPED, _ORIGINAL_DOTENV_LOAD
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True

    root = repo_root or Path(__file__).resolve().parents[3]
    env_test_path = root / ".env.test"

    import dotenv

    if _ORIGINAL_DOTENV_LOAD is None:
        _ORIGINAL_DOTENV_LOAD = dotenv.load_dotenv

    test_profile: Dict[str, str] = {}
    if env_test_path.is_file():
        raw_vals = dotenv.dotenv_values(str(env_test_path))
        test_profile = {k: (v if v is not None else "") for k, v in raw_vals.items()}

    # Always force strict test environment & clear disallowed backup/staging vars
    os.environ["APP_ENV"] = "test"
    os.environ["ENV"] = "test"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["BOONTRACK_ENV"] = "test"
    os.environ["TEST_STRICT_DB_GUARD"] = "1"
    os.environ.pop("STAGING_DATABASE_URL", None)
    os.environ.pop("SUPABASE_DB_URL", None)
    os.environ.pop("REVOKED_STAGING_DB_PASSWORD", None)

    is_ci = os.getenv("CI", "").strip().lower() in ("1", "true", "yes")
    ci_keep_vars = frozenset({
        "DATABASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "REDIS_URL",
        "REDIS_HOST",
        "REDIS_PORT",
        "STAGE1_TEST_DISPOSABLE_PG_DSN",
        "STAGE3_STEP0_DISPOSABLE_PG_DSN",
        "STAGE3_STEP1_DISPOSABLE_PG_DSN",
        "TEST_REQUIRE_DISPOSABLE_SERVICES",
        "TEST_IN_DOCKER_INTERNAL_NET",
    })

    for k, v in test_profile.items():
        if k in ("STAGING_DATABASE_URL", "SUPABASE_DB_URL", "REVOKED_STAGING_DB_PASSWORD"):
            os.environ.pop(k, None)
            continue
        if (is_ci or _is_docker_internal_net()) and k in ci_keep_vars and os.getenv(k, "").strip():
            continue
        os.environ[k] = v

    # Neutralize module-level dotenv.load_dotenv() calls for `.env` inside this test process
    def _guarded_process_load_dotenv(*args: Any, **kwargs: Any) -> bool:
        candidate = args[0] if args else kwargs.get("dotenv_path")
        if candidate and os.path.basename(str(candidate)) == ".env.test":
            return bool(_ORIGINAL_DOTENV_LOAD(*args, **kwargs))
        return False

    dotenv.load_dotenv = _guarded_process_load_dotenv  # type: ignore[assignment]

    validate_isolated_test_environment()
    install_driver_isolation_hooks()
