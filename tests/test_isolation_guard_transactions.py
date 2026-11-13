"""tests/test_isolation_guard_transactions.py
Targeted verification of psycopg2 transaction-state semantics in
`app.core.security.test_isolation_guard.verify_connected_postgres_is_disposable`.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, List, Optional, Tuple

import psycopg2
import psycopg2.extensions as pg_ext
import pytest

from app.core.database import get_db_connection
from app.core.security.test_isolation_guard import (
    TestIsolationViolation as _IsolationViolation,
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
        self._conn.executed_sql.append(sql)
        if self._conn.query_error is not None:
            self._conn._tx_status = self._conn.post_error_tx_status
            raise self._conn.query_error

        if not self._conn._autocommit and self._conn._tx_status == pg_ext.TRANSACTION_STATUS_IDLE:
            self._conn._tx_status = pg_ext.TRANSACTION_STATUS_INTRANS

        if self._conn.post_select_hook is not None:
            self._conn.post_select_hook(self._conn)

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        return self._conn.identity_row


class _FakePgConnection:
    """Faithful psycopg2 transaction-state test double with controlled failure hooks."""

    def __init__(
        self,
        *,
        autocommit: bool = False,
        tx_status: int = pg_ext.TRANSACTION_STATUS_IDLE,
        identity_row: Optional[Tuple[Any, ...]] = ("test_boontrack", "127.0.0.1"),
        query_error: Optional[Exception] = None,
        post_error_tx_status: int = pg_ext.TRANSACTION_STATUS_INERROR,
        rollback_error: Optional[Exception] = None,
        rollback_preserves_intrans: bool = False,
        close_error: Optional[Exception] = None,
        post_select_hook: Optional[Callable[["_FakePgConnection"], None]] = None,
    ) -> None:
        self._autocommit = autocommit
        self._tx_status = tx_status
        self.identity_row = identity_row
        self.query_error = query_error
        self.post_error_tx_status = post_error_tx_status
        self.rollback_error = rollback_error
        self.rollback_preserves_intrans = rollback_preserves_intrans
        self.close_error = close_error
        self.post_select_hook = post_select_hook

        self.closed = 0
        self.rollback_calls = 0
        self.commit_calls = 0
        self.close_calls = 0
        self.executed_sql: List[str] = []
        self.uncommitted_work: List[str] = []

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        if self._tx_status in (pg_ext.TRANSACTION_STATUS_INTRANS, pg_ext.TRANSACTION_STATUS_INERROR):
            raise psycopg2.ProgrammingError("set_session cannot be used inside a transaction")
        self._autocommit = bool(value)

    def set_session(self, *, readonly: Optional[bool] = None, autocommit: Optional[bool] = None) -> None:
        if self._tx_status in (pg_ext.TRANSACTION_STATUS_INTRANS, pg_ext.TRANSACTION_STATUS_INERROR):
            raise psycopg2.ProgrammingError("set_session cannot be used inside a transaction")
        if autocommit is not None:
            self._autocommit = bool(autocommit)

    def get_transaction_status(self) -> int:
        return self._tx_status

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def begin_caller_work(self, item: str) -> None:
        self._tx_status = pg_ext.TRANSACTION_STATUS_INTRANS
        self.uncommitted_work.append(item)

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self.rollback_error is not None:
            raise self.rollback_error
        if not self.rollback_preserves_intrans:
            self._tx_status = pg_ext.TRANSACTION_STATUS_IDLE
            self.uncommitted_work.clear()

    def commit(self) -> None:
        self.commit_calls += 1
        self._tx_status = pg_ext.TRANSACTION_STATUS_IDLE

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error
        self.closed = 1


# ============================================================================
# 1. Unit double tests covering all transaction & fail-closed state paths
# ============================================================================


def test_guard_idle_non_autocommit_rolls_back_only_verification_tx() -> None:
    conn = _FakePgConnection(autocommit=False, tx_status=pg_ext.TRANSACTION_STATUS_IDLE)

    verify_connected_postgres_is_disposable(conn)

    assert len(conn.executed_sql) == 1
    assert conn.rollback_calls == 1
    assert conn.commit_calls == 0
    assert conn.close_calls == 0
    assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_IDLE
    assert conn.autocommit is False

    # Call sites like init_test_postgres_schema.py & audit_production_catalog_rls.py
    # must be able to change autocommit/session immediately without ProgrammingError.
    conn.autocommit = True
    assert conn.autocommit is True


def test_guard_idle_autocommit_true_preserves_idle_without_rollback() -> None:
    conn = _FakePgConnection(autocommit=True, tx_status=pg_ext.TRANSACTION_STATUS_IDLE)

    verify_connected_postgres_is_disposable(conn)

    assert len(conn.executed_sql) == 1
    assert conn.rollback_calls == 0
    assert conn.commit_calls == 0
    assert conn.close_calls == 0
    assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_IDLE
    assert conn.autocommit is True


def test_guard_preserves_existing_caller_owned_transaction_and_work() -> None:
    conn = _FakePgConnection(autocommit=False, tx_status=pg_ext.TRANSACTION_STATUS_IDLE)
    conn.begin_caller_work("pending-tenant-insert")

    verify_connected_postgres_is_disposable(conn)

    assert len(conn.executed_sql) == 1
    assert conn.rollback_calls == 0
    assert conn.commit_calls == 0
    assert conn.close_calls == 0
    assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_INTRANS
    assert conn.autocommit is False
    assert conn.uncommitted_work == ["pending-tenant-insert"]


@pytest.mark.parametrize(
    "bad_row,expected_msg",
    [
        (("postgres", "127.0.0.1"), "non-disposable server database 'postgres'"),
        (("boontrack_prod", "127.0.0.1"), "non-disposable server database 'boontrack_prod'"),
        (("test_boontrack", "93.184.216.34"), "non-local PostgreSQL server IP '93.184.216.34'"),
        ((), "returned empty identity row"),
        (None, "returned empty identity row"),
    ],
)
def test_guard_identity_mismatch_fails_closed_and_closes_connection(
    bad_row: Optional[Tuple[Any, ...]],
    expected_msg: str,
) -> None:
    conn = _FakePgConnection(
        autocommit=False,
        tx_status=pg_ext.TRANSACTION_STATUS_IDLE,
        identity_row=bad_row,
    )

    with pytest.raises(_IsolationViolation, match=expected_msg):
        verify_connected_postgres_is_disposable(conn)

    assert conn.closed == 1
    assert conn.close_calls == 1
    assert conn.commit_calls == 0


def test_guard_database_query_failure_propagates_and_does_not_rollback_caller_work() -> None:
    root_err = psycopg2.OperationalError("simulated SELECT failure")
    conn = _FakePgConnection(
        autocommit=False,
        tx_status=pg_ext.TRANSACTION_STATUS_IDLE,
        query_error=root_err,
    )
    conn.begin_caller_work("caller-mutation")

    with pytest.raises(_IsolationViolation, match="Failed server-side disposable DB verification") as exc_info:
        verify_connected_postgres_is_disposable(conn)

    assert exc_info.value.__cause__ is root_err
    assert conn.rollback_calls == 0
    assert conn.closed == 1
    assert conn.uncommitted_work == ["caller-mutation"]


@pytest.mark.parametrize(
    "bad_status",
    [
        pg_ext.TRANSACTION_STATUS_ACTIVE,
        pg_ext.TRANSACTION_STATUS_INERROR,
        pg_ext.TRANSACTION_STATUS_UNKNOWN,
        99,
    ],
)
def test_guard_unexpected_initial_tx_status_fails_closed_before_select(bad_status: int) -> None:
    conn = _FakePgConnection(autocommit=False, tx_status=bad_status)
    conn.uncommitted_work.append("caller-state")

    with pytest.raises(_IsolationViolation):
        verify_connected_postgres_is_disposable(conn)

    assert conn.executed_sql == []
    assert conn.rollback_calls == 0
    assert conn.closed == 1
    assert conn.uncommitted_work == ["caller-state"]


def test_guard_missing_status_or_closed_conn_fails_closed() -> None:
    class _NoStatusConn:
        closed = 0
        autocommit = False
        close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            self.closed = 1

    no_status = _NoStatusConn()
    with pytest.raises(_IsolationViolation, match="Unable to inspect PostgreSQL transaction status"):
        verify_connected_postgres_is_disposable(no_status)
    assert no_status.closed == 1

    already_closed = _FakePgConnection()
    already_closed.closed = 1
    with pytest.raises(_IsolationViolation, match="null or closed"):
        verify_connected_postgres_is_disposable(already_closed)


def test_guard_rollback_failure_or_unrestored_state_fails_closed() -> None:
    rb_err = RuntimeError("rollback boom")
    conn_rb_fail = _FakePgConnection(
        autocommit=False,
        tx_status=pg_ext.TRANSACTION_STATUS_IDLE,
        rollback_error=rb_err,
    )
    with pytest.raises(_IsolationViolation, match="Failed to restore IDLE transaction state") as exc_info:
        verify_connected_postgres_is_disposable(conn_rb_fail)
    assert exc_info.value.__cause__ is rb_err
    assert conn_rb_fail.closed == 1

    conn_stuck_intrans = _FakePgConnection(
        autocommit=False,
        tx_status=pg_ext.TRANSACTION_STATUS_IDLE,
        rollback_preserves_intrans=True,
    )
    with pytest.raises(_IsolationViolation, match="did not return to IDLE cleanly"):
        verify_connected_postgres_is_disposable(conn_stuck_intrans)
    assert conn_stuck_intrans.closed == 1


def test_guard_unexpected_post_select_transitions_fail_closed() -> None:
    # Case A: IDLE + autocommit=True unexpectedly becomes INTRANS
    conn_ac_intrans = _FakePgConnection(
        autocommit=True,
        tx_status=pg_ext.TRANSACTION_STATUS_IDLE,
        post_select_hook=lambda c: setattr(c, "_tx_status", pg_ext.TRANSACTION_STATUS_INTRANS),
    )
    with pytest.raises(_IsolationViolation, match="Unexpected active transaction"):
        verify_connected_postgres_is_disposable(conn_ac_intrans)
    assert conn_ac_intrans.rollback_calls == 0
    assert conn_ac_intrans.closed == 1

    # Case B: Caller INTRANS unexpectedly drops to IDLE during SELECT
    conn_dropped = _FakePgConnection(
        autocommit=False,
        tx_status=pg_ext.TRANSACTION_STATUS_INTRANS,
        post_select_hook=lambda c: setattr(c, "_tx_status", pg_ext.TRANSACTION_STATUS_IDLE),
    )
    with pytest.raises(_IsolationViolation, match="Caller-owned INTRANS transaction transitioned unexpectedly"):
        verify_connected_postgres_is_disposable(conn_dropped)
    assert conn_dropped.closed == 1

    # Case C: autocommit silently mutated during SELECT
    conn_ac_mutated = _FakePgConnection(
        autocommit=False,
        tx_status=pg_ext.TRANSACTION_STATUS_IDLE,
        post_select_hook=lambda c: setattr(c, "_autocommit", True),
    )
    with pytest.raises(_IsolationViolation, match="Unexpected autocommit mutation"):
        verify_connected_postgres_is_disposable(conn_ac_mutated)
    assert conn_ac_mutated.closed == 1


def test_guard_info_transaction_status_fallback_and_close_error_not_swallowed() -> None:
    from types import SimpleNamespace

    class _InfoOnlyConn:
        closed = 0
        autocommit = False
        rollback_calls = 0
        close_calls = 0

        def __init__(self) -> None:
            self.info = SimpleNamespace(transaction_status=pg_ext.TRANSACTION_STATUS_IDLE)

        def cursor(self) -> Any:
            conn_ref = self

            class _Cur:
                def __enter__(self) -> "_Cur":
                    return self

                def __exit__(self, *args: Any) -> None:
                    return None

                def execute(self, sql: str, params: Any = None) -> None:
                    conn_ref.info.transaction_status = pg_ext.TRANSACTION_STATUS_INTRANS

                def fetchone(self) -> Tuple[str, str]:
                    return ("test_boontrack", "127.0.0.1")

            return _Cur()

        def rollback(self) -> None:
            self.rollback_calls += 1
            self.info.transaction_status = pg_ext.TRANSACTION_STATUS_IDLE

        def close(self) -> None:
            self.close_calls += 1
            self.closed = 1

    info_conn = _InfoOnlyConn()
    verify_connected_postgres_is_disposable(info_conn)
    assert info_conn.rollback_calls == 1
    assert info_conn.info.transaction_status == pg_ext.TRANSACTION_STATUS_IDLE
    assert info_conn.close_calls == 0

    bad_conn = _FakePgConnection(
        identity_row=("prod_db", "127.0.0.1"),
        close_error=OSError("socket close failed"),
    )
    with pytest.raises(_IsolationViolation, match="close failed: socket close failed"):
        verify_connected_postgres_is_disposable(bad_conn)
    assert bad_conn.close_calls == 1


# ============================================================================
# 2. Live disposable PostgreSQL integration tests (psycopg2 inside test_internal_net)
# ============================================================================


def test_live_psycopg2_idle_non_autocommit_and_sibling_transitions() -> None:
    conn = get_db_connection()
    try:
        assert conn.autocommit is False
        assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_IDLE

        verify_connected_postgres_is_disposable(conn)
        assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_IDLE
        assert conn.autocommit is False

        # Replicate scripts/init_test_postgres_schema.py#L87
        conn.autocommit = True
        assert conn.autocommit is True

        # Replicate scripts/enable_rls_security.py#L56 & #L58
        conn.set_session(readonly=True, autocommit=False)
        assert conn.autocommit is False
        assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_IDLE
        conn.autocommit = False

        # Replicate scripts/audit_production_catalog_rls.py#L125 & #L324
        conn.set_session(readonly=True, autocommit=True)
        assert conn.autocommit is True
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            assert cur.fetchone() == (1,)
        verify_connected_postgres_is_disposable(conn)
        assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_IDLE
        assert conn.autocommit is True
        conn.set_session(readonly=False)
    finally:
        if not conn.closed:
            conn.close()


def test_live_psycopg2_caller_transaction_preserved_without_rollback() -> None:
    conn = get_db_connection()
    marker = f"tx-preserve-{uuid.uuid4().hex}"
    try:
        assert conn.autocommit is False
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE _guard_tx_test (token text NOT NULL);")
            cur.execute("INSERT INTO _guard_tx_test (token) VALUES (%s);", (marker,))

        assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_INTRANS

        # Guard runs SELECT inside the caller transaction and must NOT roll back
        verify_connected_postgres_is_disposable(conn)

        assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_INTRANS
        assert conn.autocommit is False
        with conn.cursor() as cur:
            cur.execute("SELECT token FROM _guard_tx_test;")
            rows = cur.fetchall()
        assert rows == [(marker,)]

        conn.rollback()
        assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_IDLE
    finally:
        if not conn.closed:
            conn.rollback()
            conn.close()


def test_live_psycopg2_inerror_transaction_fails_closed() -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error):
                cur.execute("SELECT * FROM public.nonexistent_table_for_inerror_probe;")

        assert conn.get_transaction_status() == pg_ext.TRANSACTION_STATUS_INERROR
        with pytest.raises(_IsolationViolation, match="unsafe initial PostgreSQL transaction state 'INERROR'"):
            verify_connected_postgres_is_disposable(conn)
        assert conn.closed != 0
    finally:
        if not conn.closed:
            conn.close()
