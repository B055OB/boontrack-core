"""tests/test_allowed_pg_cidrs.py
Unit test suite verifying fail-closed TEST_ALLOWED_PG_CIDRS parsing, prefix enforcement,
RFC 1918 boundary validation, and server-side disposable PostgreSQL IP verification.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Tuple

import psycopg2.extensions as pg_ext
import pytest

from app.core.security.test_isolation_guard import (
    TestIsolationViolation,
    _get_allowed_pg_cidrs,
    validate_isolated_test_environment,
    verify_connected_postgres_is_disposable,
)


class _FakeCursor:
    def __init__(self, conn: "_FakePgConnection") -> None:
        self._conn = conn

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        return None

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        return self._conn.identity_row


class _FakePgConnection:
    """Lightweight test double for psycopg2 connection in disposable PG verification."""

    def __init__(
        self,
        *,
        autocommit: bool = False,
        tx_status: int = pg_ext.TRANSACTION_STATUS_IDLE,
        identity_row: Optional[Tuple[Any, ...]] = ("test_boontrack", "127.0.0.1"),
    ) -> None:
        self.autocommit = autocommit
        self._tx_status = tx_status
        self.identity_row = identity_row
        self.closed = 0
        self.rollback_calls = 0
        self.close_calls = 0

    def get_transaction_status(self) -> int:
        return self._tx_status

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._tx_status = pg_ext.TRANSACTION_STATUS_IDLE

    def close(self) -> None:
        self.close_calls += 1
        self.closed = 1


# ============================================================================
# AC-1.4: 8 Mandatory Unit Tests (Positive & Negative)
# ============================================================================


def test_allowed_pg_cidrs_unset_or_empty_allows_only_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that unset or empty TEST_ALLOWED_PG_CIDRS permits loopback and blocks private IPs."""
    for empty_val in (None, "", "   "):
        if empty_val is None:
            monkeypatch.delenv("TEST_ALLOWED_PG_CIDRS", raising=False)
        else:
            monkeypatch.setenv("TEST_ALLOWED_PG_CIDRS", empty_val)

        assert _get_allowed_pg_cidrs() == ()
        validate_isolated_test_environment()

        conn_lo = _FakePgConnection(identity_row=("test_boontrack", "127.0.0.1"))
        verify_connected_postgres_is_disposable(conn_lo)

        conn_v6_lo = _FakePgConnection(identity_row=("test_boontrack", "::1"))
        verify_connected_postgres_is_disposable(conn_v6_lo)

        conn_priv = _FakePgConnection(identity_row=("test_boontrack", "172.18.0.2"))
        with pytest.raises(TestIsolationViolation, match="Refusing connection to non-local PostgreSQL server IP '172.18.0.2'"):
            verify_connected_postgres_is_disposable(conn_priv)
        assert conn_priv.close_calls == 1

        conn_priv2 = _FakePgConnection(identity_row=("test_boontrack", "10.0.0.5"))
        with pytest.raises(TestIsolationViolation, match="Refusing connection to non-local PostgreSQL server IP '10.0.0.5'"):
            verify_connected_postgres_is_disposable(conn_priv2)
        assert conn_priv2.close_calls == 1


def test_allowed_pg_cidrs_exact_slash32_allows_matching_container_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that an exact /32 CIDR allows the matching container IP and preserves loopback."""
    monkeypatch.setenv("TEST_ALLOWED_PG_CIDRS", "172.18.0.2/32")
    cidrs = _get_allowed_pg_cidrs()
    assert len(cidrs) == 1
    assert str(cidrs[0]) == "172.18.0.2/32"

    validate_isolated_test_environment()

    conn_match = _FakePgConnection(identity_row=("test_boontrack", "172.18.0.2"))
    verify_connected_postgres_is_disposable(conn_match)
    assert conn_match.close_calls == 0

    # Loopback continues to be allowed
    conn_lo = _FakePgConnection(identity_row=("test_boontrack", "127.0.0.1"))
    verify_connected_postgres_is_disposable(conn_lo)
    assert conn_lo.close_calls == 0


def test_allowed_pg_cidrs_multiple_valid_cidrs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that comma-separated valid CIDRs (/24 to /32) all match correctly."""
    monkeypatch.setenv("TEST_ALLOWED_PG_CIDRS", "172.18.0.2/32, 10.0.0.5/32, 192.168.1.0/24")
    cidrs = _get_allowed_pg_cidrs()
    assert len(cidrs) == 3

    validate_isolated_test_environment()

    for allowed_ip in ("172.18.0.2", "10.0.0.5", "192.168.1.42", "127.0.0.1"):
        conn = _FakePgConnection(identity_row=("test_boontrack", allowed_ip))
        verify_connected_postgres_is_disposable(conn)
        assert conn.close_calls == 0


def test_in_docker_internal_net_alone_does_not_allow_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1.1: TEST_IN_DOCKER_INTERNAL_NET='1' alone MUST NOT allow private IPs without TEST_ALLOWED_PG_CIDRS."""
    monkeypatch.setenv("TEST_IN_DOCKER_INTERNAL_NET", "1")
    monkeypatch.setenv("TEST_ALLOWED_PG_CIDRS", "")

    assert _get_allowed_pg_cidrs() == ()

    conn_docker_pg = _FakePgConnection(identity_row=("test_boontrack", "172.18.0.2"))
    with pytest.raises(TestIsolationViolation, match="Refusing connection to non-local PostgreSQL server IP '172.18.0.2'"):
        verify_connected_postgres_is_disposable(conn_docker_pg)
    assert conn_docker_pg.close_calls == 1

    conn_docker_other = _FakePgConnection(identity_row=("test_boontrack", "10.0.0.5"))
    with pytest.raises(TestIsolationViolation, match="Refusing connection to non-local PostgreSQL server IP '10.0.0.5'"):
        verify_connected_postgres_is_disposable(conn_docker_other)
    assert conn_docker_other.close_calls == 1

    # Loopback still succeeds under TEST_IN_DOCKER_INTERNAL_NET
    conn_lo = _FakePgConnection(identity_row=("test_boontrack", "127.0.0.1"))
    verify_connected_postgres_is_disposable(conn_lo)


def test_allowed_pg_cidrs_rejects_non_matching_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that private IPs not matching configured CIDRs are rejected fail-closed."""
    monkeypatch.setenv("TEST_ALLOWED_PG_CIDRS", "172.18.0.2/32")

    conn_subnet_sibling = _FakePgConnection(identity_row=("test_boontrack", "172.18.0.3"))
    with pytest.raises(TestIsolationViolation, match="Refusing connection to non-local PostgreSQL server IP '172.18.0.3'"):
        verify_connected_postgres_is_disposable(conn_subnet_sibling)
    assert conn_subnet_sibling.close_calls == 1

    conn_other_net = _FakePgConnection(identity_row=("test_boontrack", "10.0.0.2"))
    with pytest.raises(TestIsolationViolation, match="Refusing connection to non-local PostgreSQL server IP '10.0.0.2'"):
        verify_connected_postgres_is_disposable(conn_other_net)
    assert conn_other_net.close_calls == 1


def test_allowed_pg_cidrs_rejects_overly_broad_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that prefixes broader than /24 (e.g. /0, /8, /12, /16) are rejected."""
    broad_prefixes = ("0.0.0.0/0", "10.0.0.0/8", "172.16.0.0/12", "172.18.0.0/16", "192.168.0.0/16")
    for broad in broad_prefixes:
        monkeypatch.setenv("TEST_ALLOWED_PG_CIDRS", broad)
        with pytest.raises(TestIsolationViolation):
            _get_allowed_pg_cidrs()
        with pytest.raises(TestIsolationViolation):
            validate_isolated_test_environment()


def test_allowed_pg_cidrs_rejects_public_and_sinkhole_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that non-RFC 1918 public, documentation/sinkhole IPs, and markers are rejected."""
    prohibited_targets = (
        "8.8.8.8/32",
        "1.1.1.1/32",
        "192.0.2.1/32",
        "192.0.2.0/24",
        "198.51.100.1/32",
        "203.0.113.1/32",
        "mpluzajlzpregmjwpjqr/32",
    )
    for target in prohibited_targets:
        monkeypatch.setenv("TEST_ALLOWED_PG_CIDRS", target)
        with pytest.raises(TestIsolationViolation):
            _get_allowed_pg_cidrs()
        with pytest.raises(TestIsolationViolation):
            validate_isolated_test_environment()


def test_allowed_pg_cidrs_rejects_malformed_and_non_strict_cidrs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that non-strict CIDRs, bare IPs without mask, and trailing commas fail closed."""
    malformed_tokens = (
        "invalid",
        "172.18.0.2",
        "172.18.0.2/24",   # Non-strict: host bits set on /24
        "172.18.0.2/32,",  # Trailing comma
        ",172.18.0.2/32",  # Leading comma
        "172.18.0.2/32,,172.18.0.3/32",  # Double comma / empty token
        "172.18.0.2/33",   # Invalid prefixlen
        "172.18.0.2/abc",  # Non-numeric prefix
    )
    for token in malformed_tokens:
        monkeypatch.setenv("TEST_ALLOWED_PG_CIDRS", token)
        with pytest.raises(TestIsolationViolation):
            _get_allowed_pg_cidrs()
        with pytest.raises(TestIsolationViolation):
            validate_isolated_test_environment()
