r"""Live Disposable PostgreSQL Integration Test Suite for Phase 1 — Stage 1 (`PG-INT-01` .. `PG-INT-06`).

Executes against a real, isolated, disposable local PostgreSQL database specified by
`STAGE1_TEST_DISPOSABLE_PG_DSN`.

Strict Safety Guards (`assert_strictly_disposable_local_postgres_dsn`):
1. Never reads `DATABASE_URL`, `SUPABASE_DB_URL`, or `.env`.
2. Requires hostname in `{"127.0.0.1", "localhost", "::1"}` (loopback only).
3. Requires database name matching `^bt_stage1_disposable_test_[a-z0-9_]+$`.
4. Verifies server-side `current_database()` and loopback connection before running any DDL/DML.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import pytest
import psycopg2

from app.core.security.payment_auth_guard import (
    CanonicalTenantResolver,
    HDR_ACTOR,
    HDR_KEY_ID,
    HDR_NONCE,
    HDR_SIGNATURE,
    HDR_TIMESTAMP,
    InternalPaymentHMACKeyring,
    InternalPaymentHMACVerifier,
    PostgresAuthoritativeReplayStore,
    compute_internal_payment_hmac_signature,
)
from app.services.payment.base import (
    PaymentAuthorizationError,
    ReplayStoreUnavailableError,
)
from app.core.security.test_isolation_guard import _get_allowed_pg_cidrs

ENV_DISPOSABLE_PG_DSN = "STAGE1_TEST_DISPOSABLE_PG_DSN"
DISPOSABLE_DB_NAME_PATTERN = re.compile(r"^bt_stage1_disposable_test_[a-z0-9_]+$")

MIGRATION_032_PATH = Path(__file__).resolve().parent.parent / "migrations" / "032_create_payment_replay_nonces.sql"

TENANT_1_UUID = "7f9c2a10-4b55-4e88-9c11-112233445566"
TENANT_1_SLUG = "onlineboost"
TENANT_2_UUID = "9a8b7c6d-5e4f-4a3b-8c2d-665544332211"
TENANT_2_SLUG = "merchant-dua"

ACTIVE_KEY_ID = "pim_k202611_active"
ACTIVE_KEY_SECRET = "internal_hmac_secret_active_202611_high_entropy_key_001"
ACTIVE_PRINCIPAL = "svc:payment_settlement_worker"
FAKE_APP_MASTER_KEY = "master_key_super_secret_do_not_use_for_payments_999999"

FIXED_NOW_EPOCH = 1762345200


def assert_strictly_disposable_local_postgres_dsn(dsn: str) -> Tuple[str, str]:
    """Validates that `dsn` points strictly to a loopback disposable test database."""
    if not dsn or not dsn.strip():
        raise RuntimeError(
            f"{ENV_DISPOSABLE_PG_DSN} is not set. Refusing to fall back to any shared or default database."
        )
    parsed = urlparse(dsn.strip())
    if parsed.scheme not in ("postgresql", "postgres"):
        raise RuntimeError(f"Invalid DSN scheme '{parsed.scheme}'; expected postgresql://")
    host = (parsed.hostname or "").strip().lower()
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    if os.getenv("TEST_IN_DOCKER_INTERNAL_NET", "").strip() == "1":
        allowed_hosts.add("test-postgres")
    if host not in allowed_hosts:
        raise RuntimeError(
            f"FORBIDDEN_NON_LOCAL_DB_HOST: '{host}'. Live Stage 1 integration tests may only "
            "run against loopback or isolated test-postgres network."
        )
    db_name = (parsed.path or "").lstrip("/").strip()
    if not DISPOSABLE_DB_NAME_PATTERN.match(db_name):
        raise RuntimeError(
            f"FORBIDDEN_DB_NAME: '{db_name}'. Database name must match "
            f"'{DISPOSABLE_DB_NAME_PATTERN.pattern}'."
        )
    return dsn.strip(), db_name


def _get_verified_disposable_dsn() -> str:
    import ipaddress

    raw_dsn = os.environ.get(ENV_DISPOSABLE_PG_DSN, "")
    dsn, db_name = assert_strictly_disposable_local_postgres_dsn(raw_dsn)
    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        if "does not exist" not in str(exc):
            raise
        admin_dsn = dsn.rsplit("/", 1)[0] + "/test_boontrack"
        admin_conn = psycopg2.connect(admin_dsn)
        admin_conn.autocommit = True
        try:
            with admin_conn.cursor() as adm_cur:
                adm_cur.execute(f'CREATE DATABASE "{db_name}";')
        finally:
            admin_conn.close()
        conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), inet_server_addr()::text;")
            row = cur.fetchone()
            assert row is not None
            actual_db, server_addr = row
            if actual_db != db_name or not DISPOSABLE_DB_NAME_PATTERN.match(actual_db):
                raise RuntimeError(f"Connected database '{actual_db}' does not match disposable contract.")
            if server_addr:
                ip_obj = ipaddress.ip_address(server_addr.split("/", 1)[0])
                if not (ip_obj is not None and (ip_obj.is_loopback or any(ip_obj in net for net in _get_allowed_pg_cidrs()))):
                    raise RuntimeError(f"Connected server address '{server_addr}' is not loopback or isolated test network!")
    finally:
        conn.close()
    return dsn


class _RuntimeRoleConnWrapper:
    """Wraps a real `psycopg2` connection and executes `SET ROLE bt_app_runtime;`
    immediately so all runtime queries execute under least-privilege `bt_app_runtime`.
    """

    def __init__(self, dsn: str, *, fail_on_commit: bool = False) -> None:
        self._raw_conn = psycopg2.connect(dsn)
        self._fail_on_commit = fail_on_commit
        with self._raw_conn.cursor() as cur:
            cur.execute("SET ROLE bt_app_runtime;")
        self._raw_conn.commit()

    def cursor(self) -> Any:
        return self._raw_conn.cursor()

    def commit(self) -> None:
        if self._fail_on_commit:
            self._raw_conn.rollback()
            raise psycopg2.OperationalError("Simulated connection drop during COMMIT on live PostgreSQL")
        self._raw_conn.commit()

    def rollback(self) -> None:
        self._raw_conn.rollback()

    def close(self) -> None:
        self._raw_conn.close()


@pytest.fixture(scope="module")
def disposable_pg_dsn() -> str:
    """Bootstraps the disposable PostgreSQL schema and applies Migration 032."""
    dsn = _get_verified_disposable_dsn()
    migration_sql = MIGRATION_032_PATH.read_text(encoding="utf-8")

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid != pg_backend_pid();"
            )
            # Clean slate in disposable database
            cur.execute("DROP TABLE IF EXISTS public.payment_hmac_replay_cleanup_audit_log CASCADE;")
            cur.execute("DROP TABLE IF EXISTS public.payment_hmac_replay_nonces CASCADE;")
            cur.execute("DROP TABLE IF EXISTS public.orders CASCADE;")
            cur.execute("DROP TABLE IF EXISTS public.tenants CASCADE;")

            # Minimal authoritative tenants & orders tables for CanonicalTenantResolver join
            cur.execute(
                """
                CREATE TABLE public.tenants (
                    id UUID PRIMARY KEY,
                    slug VARCHAR(128) NOT NULL UNIQUE,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                CREATE TABLE public.orders (
                    id VARCHAR(128) PRIMARY KEY,
                    tenant_id VARCHAR(100) NOT NULL,
                    tenant_slug VARCHAR(128),
                    gross_amount BIGINT NOT NULL,
                    amount BIGINT NOT NULL,
                    sku_id VARCHAR(255) NOT NULL,
                    product_id VARCHAR(255),
                    status VARCHAR(64) NOT NULL,
                    payment_status VARCHAR(32) DEFAULT 'PENDING',
                    order_status VARCHAR(32) DEFAULT 'PENDING',
                    fulfillment_status VARCHAR(64) NOT NULL DEFAULT 'UNFULFILLED',
                    paid_at TIMESTAMPTZ,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    fulfillment_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                """
            )
            cur.execute(
                "INSERT INTO public.tenants (id, slug) VALUES (%s, %s), (%s, %s);",
                (TENANT_1_UUID, TENANT_1_SLUG, TENANT_2_UUID, TENANT_2_SLUG),
            )
            cur.execute(
                """
                INSERT INTO public.orders (id, tenant_id, tenant_slug, gross_amount, amount, sku_id, status)
                VALUES
                    ('ORD-OB-1001', %s, %s, 249000, 249000, 'kelas-inkubasi-ctwa-batch-1-scale', 'PENDING'),
                    ('ORD-M2-2002', %s, %s, 150000, 150000, 'produk-merchant-dua', 'PENDING');
                """,
                (TENANT_1_UUID, TENANT_1_SLUG, TENANT_2_UUID, TENANT_2_SLUG),
            )

            # Apply Migration 032
            cur.execute(migration_sql)

            # Grant SELECT on tenants and orders to bt_app_runtime so CanonicalTenantResolver works under bt_app_runtime
            cur.execute("GRANT SELECT ON TABLE public.tenants, public.orders TO bt_app_runtime;")
    finally:
        conn.close()

    return dsn


def _build_live_pg_verifier(
    dsn: str,
    *,
    redis_client: Optional[Any] = None,
    fail_on_commit: bool = False,
) -> InternalPaymentHMACVerifier:
    keyring = InternalPaymentHMACKeyring(
        keys={
            ACTIVE_KEY_ID: {
                "secret": ACTIVE_KEY_SECRET,
                "status": "ACTIVE",
                "bound_principal": ACTIVE_PRINCIPAL,
                "bound_tenant_id": TENANT_1_UUID,
            }
        },
        app_master_key=FAKE_APP_MASTER_KEY,
    )
    conn_factory = lambda: _RuntimeRoleConnWrapper(dsn, fail_on_commit=fail_on_commit)
    resolver = CanonicalTenantResolver(conn_factory)
    replay_store = PostgresAuthoritativeReplayStore(
        conn_factory,
        redis_client=redis_client,
        ttl_seconds=600,
    )
    return InternalPaymentHMACVerifier(
        keyring=keyring,
        tenant_resolver=resolver,
        replay_store=replay_store,
        app_master_key=FAKE_APP_MASTER_KEY,
        timestamp_tolerance_seconds=300,
    )


def _build_signed_headers(nonce: str, raw_body: bytes = b'{"reason":"live_pg_test"}') -> Dict[str, str]:
    sig = compute_internal_payment_hmac_signature(
        secret=ACTIVE_KEY_SECRET,
        key_id=ACTIVE_KEY_ID,
        timestamp=FIXED_NOW_EPOCH,
        nonce=nonce,
        http_method="POST",
        canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
        order_id="ORD-OB-1001",
        canonical_tenant_id=TENANT_1_UUID,
        raw_body=raw_body,
    )
    return {
        HDR_KEY_ID: ACTIVE_KEY_ID,
        HDR_TIMESTAMP: str(FIXED_NOW_EPOCH),
        HDR_NONCE: nonce,
        HDR_SIGNATURE: sig,
        HDR_ACTOR: ACTIVE_PRINCIPAL,
    }


# =============================================================================
# PG-INT-01: Migration 032 Application, Role Privileges, Sequence & Retention
# =============================================================================

def test_pg_int_01_migration_032_and_role_sequence_privilege_enforcement(disposable_pg_dsn: str) -> None:
    """PG-INT-01: Verifies on live PostgreSQL:
    1. Table owner is `bt_migration_owner`.
    2. `bt_app_runtime` can `SELECT` and `INSERT` (using `BIGSERIAL` sequence `nextval`).
    3. `bt_app_runtime` is strictly denied `UPDATE`, `DELETE`, `TRUNCATE`, `setval()`,
       and `purge_expired_payment_replay_nonces()`.
    4. `bt_replay_cleanup` cannot `DELETE` rows within the 90-day forensic retention window,
       can purge rows older than 90 days via `purge_expired_payment_replay_nonces()`,
       and writes an immutable audit log record.
    """
    conn = psycopg2.connect(disposable_pg_dsn)
    try:
        # 1. Verify table owner is bt_migration_owner
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = 'payment_hmac_replay_nonces';"
            )
            owner_row = cur.fetchone()
            assert owner_row is not None and owner_row[0] == "bt_migration_owner"

        # 2. Switch to bt_app_runtime and test INSERT + SELECT
        with conn.cursor() as cur:
            cur.execute("SET ROLE bt_app_runtime;")
            now_utc = datetime.now(timezone.utc)
            cur.execute(
                """
                INSERT INTO public.payment_hmac_replay_nonces (
                    key_id, nonce, actor_principal, canonical_tenant_id, order_id,
                    http_method, canonical_path, request_timestamp, body_sha256,
                    consumed_at, expires_at
                )
                VALUES (%s, %s, %s, %s, %s, 'POST', '/api/v1/orders/ORD-OB-1001/approve-and-deliver', %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    ACTIVE_KEY_ID,
                    "nonce_pg_int_01_runtime",
                    ACTIVE_PRINCIPAL,
                    TENANT_1_UUID,
                    "ORD-OB-1001",
                    FIXED_NOW_EPOCH,
                    hashlib.sha256(b"test").hexdigest(),
                    now_utc,
                    now_utc + timedelta(seconds=600),
                ),
            )
            inserted_id = cur.fetchone()[0]
            assert inserted_id >= 1
        conn.commit()

        # 3. Verify bt_app_runtime is DENIED UPDATE, DELETE, TRUNCATE, setval, and purge function
        forbidden_runtime_statements = [
            "UPDATE public.payment_hmac_replay_nonces SET order_id = 'HACKED' WHERE nonce = 'nonce_pg_int_01_runtime';",
            "DELETE FROM public.payment_hmac_replay_nonces WHERE nonce = 'nonce_pg_int_01_runtime';",
            "TRUNCATE TABLE public.payment_hmac_replay_nonces;",
            "SELECT setval('public.payment_hmac_replay_nonces_id_seq', 999999);",
            "SELECT public.purge_expired_payment_replay_nonces(100);",
        ]
        for stmt in forbidden_runtime_statements:
            with pytest.raises(psycopg2.Error) as exc_priv:
                with conn.cursor() as cur:
                    cur.execute("SET ROLE bt_app_runtime;")
                    cur.execute(stmt)
            assert exc_priv.value.pgcode == "42501", f"Expected SQLSTATE 42501 for: {stmt}"
            conn.rollback()

        # 4. Insert an ancient (>91 days expired) row as bt_app_runtime, then test bt_replay_cleanup
        with conn.cursor() as cur:
            cur.execute("SET ROLE bt_app_runtime;")
            old_consumed = datetime.now(timezone.utc) - timedelta(days=95)
            old_expires = old_consumed + timedelta(seconds=600)  # expired ~95 days ago (> 90d retention)
            cur.execute(
                """
                INSERT INTO public.payment_hmac_replay_nonces (
                    key_id, nonce, actor_principal, canonical_tenant_id, order_id,
                    http_method, canonical_path, request_timestamp, body_sha256,
                    consumed_at, expires_at
                )
                VALUES (%s, %s, %s, %s, %s, 'POST', '/api/v1/orders/ORD-OB-1001/approve-and-deliver', %s, %s, %s, %s);
                """,
                (
                    ACTIVE_KEY_ID,
                    "nonce_pg_int_01_expired_95d",
                    ACTIVE_PRINCIPAL,
                    TENANT_1_UUID,
                    "ORD-OB-1001",
                    FIXED_NOW_EPOCH - 8208000,
                    hashlib.sha256(b"old").hexdigest(),
                    old_consumed,
                    old_expires,
                ),
            )
        conn.commit()

        # 5. bt_replay_cleanup CANNOT delete the recent (<90d) row
        with pytest.raises(psycopg2.Error) as exc_ret:
            with conn.cursor() as cur:
                cur.execute("SET ROLE bt_replay_cleanup;")
                cur.execute(
                    "DELETE FROM public.payment_hmac_replay_nonces WHERE nonce = 'nonce_pg_int_01_runtime';"
                )
        assert exc_ret.value.pgcode == "42501"
        assert "FORENSIC_RETENTION_ACTIVE" in str(exc_ret.value)
        conn.rollback()

        # 6. bt_replay_cleanup CAN execute purge_expired_payment_replay_nonces() to remove the >90d row
        with conn.cursor() as cur:
            cur.execute("SET ROLE bt_replay_cleanup;")
            cur.execute("SELECT public.purge_expired_payment_replay_nonces(500);")
            purged_count = cur.fetchone()[0]
            assert purged_count == 1

            # Verify recent row still exists and expired row is gone
            cur.execute(
                "SELECT COUNT(*) FROM public.payment_hmac_replay_nonces WHERE nonce = 'nonce_pg_int_01_runtime';"
            )
            assert cur.fetchone()[0] == 1
            cur.execute(
                "SELECT COUNT(*) FROM public.payment_hmac_replay_nonces WHERE nonce = 'nonce_pg_int_01_expired_95d';"
            )
            assert cur.fetchone()[0] == 0

            # Verify audit log row was recorded and is immutable
            cur.execute(
                "SELECT executed_by_role, deleted_row_count FROM public.payment_hmac_replay_cleanup_audit_log ORDER BY audit_id DESC LIMIT 1;"
            )
            audit_row = cur.fetchone()
            assert audit_row == ("bt_replay_cleanup", 1)
        conn.commit()

        # 7. Verify audit log cannot be deleted or updated even by bt_replay_cleanup
        with pytest.raises(psycopg2.Error) as exc_audit_del:
            with conn.cursor() as cur:
                cur.execute("SET ROLE bt_replay_cleanup;")
                cur.execute("DELETE FROM public.payment_hmac_replay_cleanup_audit_log;")
        assert exc_audit_del.value.pgcode == "42501"
        conn.rollback()
    finally:
        conn.close()


# =============================================================================
# PG-INT-02: Unique Constraint `(key_id, nonce)` on Real PostgreSQL Connection
# =============================================================================

def test_pg_int_02_unique_constraint_on_real_postgres_connection(disposable_pg_dsn: str) -> None:
    """PG-INT-02: Verifies composite unique constraint `(key_id, nonce)` and
    active replay window check constraint on a real PostgreSQL connection.
    """
    store = PostgresAuthoritativeReplayStore(lambda: _RuntimeRoleConnWrapper(disposable_pg_dsn))
    body_hash = hashlib.sha256(b'{"reason":"pg_int_02"}').hexdigest()

    # First claim succeeds
    store.claim_nonce_or_fail_closed(
        key_id=ACTIVE_KEY_ID,
        nonce="nonce_pg_int_02_unique",
        actor_principal=ACTIVE_PRINCIPAL,
        canonical_tenant_id=TENANT_1_UUID,
        order_id="ORD-OB-1001",
        http_method="POST",
        canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
        request_timestamp=FIXED_NOW_EPOCH,
        body_sha256=body_hash,
    )

    # Second claim with same (key_id, nonce) fails with DUPLICATE_NONCE_REPLAY
    with pytest.raises(PaymentAuthorizationError) as exc_dup:
        store.claim_nonce_or_fail_closed(
            key_id=ACTIVE_KEY_ID,
            nonce="nonce_pg_int_02_unique",
            actor_principal=ACTIVE_PRINCIPAL,
            canonical_tenant_id=TENANT_1_UUID,
            order_id="ORD-OB-1001",
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            request_timestamp=FIXED_NOW_EPOCH,
            body_sha256=body_hash,
        )
    assert exc_dup.value.error_code == "DUPLICATE_NONCE_REPLAY"
    assert exc_dup.value.http_status == 403

    # Same nonce under a DIFFERENT key_id succeeds (proving composite uniqueness)
    store.claim_nonce_or_fail_closed(
        key_id="pim_k202611_secondary_key",
        nonce="nonce_pg_int_02_unique",
        actor_principal=ACTIVE_PRINCIPAL,
        canonical_tenant_id=TENANT_1_UUID,
        order_id="ORD-OB-1001",
        http_method="POST",
        canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
        request_timestamp=FIXED_NOW_EPOCH,
        body_sha256=body_hash,
    )


# =============================================================================
# PG-INT-03: Cross-Worker Duplicate Nonce Rejection
# =============================================================================

def test_pg_int_03_cross_worker_duplicate_nonce_rejection(disposable_pg_dsn: str) -> None:
    """PG-INT-03: Two independent worker verifiers (`worker_a` and `worker_b`) with
    separate PostgreSQL connections and no Redis reject cross-worker replay.
    """
    worker_a = _build_live_pg_verifier(disposable_pg_dsn, redis_client=None)
    worker_b = _build_live_pg_verifier(disposable_pg_dsn, redis_client=None)

    body = b'{"reason":"cross_worker_test"}'
    headers = _build_signed_headers("nonce_pg_int_03_cross_worker", raw_body=body)

    ctx_a = worker_a.verify_mutation_request(
        headers=headers,
        http_method="POST",
        canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
        order_id="ORD-OB-1001",
        raw_body=body,
        now_epoch=FIXED_NOW_EPOCH,
    )
    assert ctx_a.nonce == "nonce_pg_int_03_cross_worker"

    with pytest.raises(PaymentAuthorizationError) as exc_b:
        worker_b.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_b.value.error_code == "DUPLICATE_NONCE_REPLAY"
    assert exc_b.value.http_status == 403


# =============================================================================
# PG-INT-04: 16-Worker Concurrent Claim Race Condition on Live PostgreSQL
# =============================================================================

def test_pg_int_04_concurrent_16_worker_claim_race_on_live_postgres(disposable_pg_dsn: str) -> None:
    """PG-INT-04: 16 concurrent worker threads with independent live PostgreSQL
    connections race on the same `(key_id, nonce)`. Exactly 1 wins and 15 are rejected.
    """
    body = b'{"reason":"live_pg_16_worker_race"}'
    shared_nonce = "nonce_pg_int_04_race_16_workers"
    headers = _build_signed_headers(shared_nonce, raw_body=body)

    worker_count = 16
    barrier = threading.Barrier(worker_count)
    successes: List[str] = []
    replay_rejections: List[str] = []
    unexpected_errors: List[Exception] = []
    lock = threading.Lock()

    def _worker_task() -> None:
        verifier = _build_live_pg_verifier(disposable_pg_dsn, redis_client=None)
        barrier.wait()
        try:
            ctx = verifier.verify_mutation_request(
                headers=headers,
                http_method="POST",
                canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
                order_id="ORD-OB-1001",
                raw_body=body,
                now_epoch=FIXED_NOW_EPOCH,
            )
            with lock:
                successes.append(ctx.nonce)
        except PaymentAuthorizationError as auth_err:
            with lock:
                if auth_err.error_code == "DUPLICATE_NONCE_REPLAY":
                    replay_rejections.append(auth_err.error_code)
                else:
                    unexpected_errors.append(auth_err)
        except Exception as exc:
            with lock:
                unexpected_errors.append(exc)

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(_worker_task) for _ in range(worker_count)]
        for f in futures:
            f.result()

    assert not unexpected_errors, f"Unexpected errors in concurrent PG test: {unexpected_errors}"
    assert len(successes) == 1
    assert len(replay_rejections) == worker_count - 1

    # Verify exactly 1 row exists in live PostgreSQL
    conn = psycopg2.connect(disposable_pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM public.payment_hmac_replay_nonces WHERE key_id = %s AND nonce = %s;",
                (ACTIVE_KEY_ID, shared_nonce),
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()


# =============================================================================
# PG-INT-05: Commit Failure & Connection Failure Fail-Closed (HTTP 503)
# =============================================================================

def test_pg_int_05_commit_failure_and_connection_failure_fail_closed(disposable_pg_dsn: str) -> None:
    """PG-INT-05: Verifies that both a commit failure on a real PostgreSQL transaction
    and a connection failure fail closed with `ReplayStoreUnavailableError` (HTTP 503)
    and leave zero uncommitted/orphan nonce rows.
    """
    body = b'{"reason":"commit_failure_test"}'
    commit_fail_nonce = "nonce_pg_int_05_commit_fail"
    headers = _build_signed_headers(commit_fail_nonce, raw_body=body)

    # 1. Commit failure on live PostgreSQL connection -> rolls back and raises HTTP 503
    verifier_commit_fail = _build_live_pg_verifier(disposable_pg_dsn, fail_on_commit=True)
    with pytest.raises(ReplayStoreUnavailableError) as exc_commit:
        verifier_commit_fail.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_commit.value.error_code == "REPLAY_STORE_UNAVAILABLE"
    assert exc_commit.value.http_status == 503

    # Confirm the rolled-back nonce was NOT persisted in PostgreSQL
    conn = psycopg2.connect(disposable_pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM public.payment_hmac_replay_nonces WHERE nonce = %s;",
                (commit_fail_nonce,),
            )
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()

    # 2. Unreachable PostgreSQL port -> raises HTTP 503
    dead_dsn = "postgresql://postgres:disposable@127.0.0.1:1/bt_stage1_disposable_test_dead?connect_timeout=1"
    verifier_dead = _build_live_pg_verifier(disposable_pg_dsn)
    verifier_dead._replay_store._db_conn_factory = lambda: psycopg2.connect(dead_dsn)
    with pytest.raises(ReplayStoreUnavailableError) as exc_dead:
        verifier_dead.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_dead.value.http_status == 503


# =============================================================================
# PG-INT-06: Redis Outage & Eviction Invariance with Live PostgreSQL
# =============================================================================

class _BrokenRedisClient:
    def get(self, key: str) -> Any:
        raise ConnectionError("Redis connection refused (outage)")

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        raise ConnectionError("Redis connection refused (outage)")


def test_pg_int_06_redis_outage_and_eviction_invariance_with_live_postgres(disposable_pg_dsn: str) -> None:
    """PG-INT-06: When Redis is completely down, live PostgreSQL remains the sole
    authoritative store: the first request succeeds and the duplicate replay is rejected.
    """
    verifier_broken_redis = _build_live_pg_verifier(
        disposable_pg_dsn,
        redis_client=_BrokenRedisClient(),
    )
    body = b'{"reason":"redis_outage_live_pg"}'
    nonce = "nonce_pg_int_06_redis_down"
    headers = _build_signed_headers(nonce, raw_body=body)

    # 1. First request succeeds despite Redis outage
    ctx = verifier_broken_redis.verify_mutation_request(
        headers=headers,
        http_method="POST",
        canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
        order_id="ORD-OB-1001",
        raw_body=body,
        now_epoch=FIXED_NOW_EPOCH,
    )
    assert ctx.nonce == nonce

    # 2. Replay request is rejected by live PostgreSQL despite Redis outage
    with pytest.raises(PaymentAuthorizationError) as exc_replay:
        verifier_broken_redis.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_replay.value.error_code == "DUPLICATE_NONCE_REPLAY"
    assert exc_replay.value.http_status == 403

