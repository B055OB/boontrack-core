r"""Unit, Cryptographic, RFC 8785 Conformance & Negative Security Tests for Phase 1 — Stage 1.

Covers 24 deterministic in-memory test scenarios:
1. Valid HMAC signature passes.
2. Invalid HMAC signature rejected.
3. Tampered body, method, path, or order ID rejected.
4. Expired and future timestamp rejected.
5. Duplicate nonce replay rejected.
6. Concurrent duplicate nonce race condition (16 threads).
7. PostgreSQL replay store outage fails closed (`HTTP 503`) even when Redis is healthy.
8. Unknown and revoked HMAC key ID rejected; expired rotated key rejected.
9. `APP_MASTER_KEY` rejected for payment mutation.
10. Spoofed `actor_id` and `tenant_id` in request body rejected.
11. Canonical tenant resolution success (`orders.tenant_id == tenants.id::text`).
12. `tenant_slug` fallback prohibited (`OR o.tenant_slug = t.slug` absent) & unresolved legacy order fails closed (`HTTP 422`).
13. Tenant mismatch against order (`ORDER_TENANT_MISMATCH` `HTTP 403`).
14. RFC 8785 official Appendix B test vectors, numeric exponent boundaries (`1e-6` vs `1e-7`, `1e-5`, `1e20` vs `1e21`), binary64 edge cases, and cross-implementation SHA-256 digest consistency.
15. RFC 8785 Unicode UTF-16 sorting, invalid lone/reversed surrogate rejection, and unsupported type rejection.
16. Provenance 17-field contract, single-field tampering detection, and integer-only amount enforcement.
17. Ed25519 asymmetric provenance signing, public-key-only verifier isolation, key rotation (`ACTIVE`, `VERIFY_ONLY`, `REVOKED`), key mismatch, and key separation.
18. Forged proof rejection: application callers cannot instantiate `CryptographicVerificationProof` / `VerifiedSettlementCapability` directly even with allowlisted `proof_source` strings.
19. `TrustedSettlementVerificationBoundary` cryptographic webhook verification (Xendit & Midtrans) and deterministic verifier identity binding.
20. Direct Tenant Rail lock: `MANUAL_DIRECT_TENANT` is blocked in boundary minting, signer, and verifier.
21. Non-canonical request path rejection (`//`, `/./`, `/../`, trailing `/`, `%` encoding, `\`).
22. Query parameter tampering rejection on mutation routes (`QUERY_PARAMETERS_FORBIDDEN`).
23. Raw request body `bytes` enforcement (`RAW_BODY_BYTES_REQUIRED` on `str`/`dict`) & byte-level whitespace sensitivity.
24. Canonical environment variable contract & fail-closed rejection of deprecated env var aliases.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import threading
from typing import Any, Dict, List, Optional, Tuple
import pytest

from app.core.security.payment_auth_guard import (
    CanonicalTenantResolver,
    ENV_APP_MASTER_KEY,
    ENV_INTERNAL_HMAC_KEYRING,
    HDR_ACTOR,
    HDR_API_KEY,
    HDR_AUTHORIZATION,
    HDR_KEY_ID,
    HDR_MASTER_KEY,
    HDR_NONCE,
    HDR_SIGNATURE,
    HDR_TENANT_ID,
    HDR_TIMESTAMP,
    InternalPaymentHMACKeyring,
    InternalPaymentHMACVerifier,
    PostgresAuthoritativeReplayStore,
    compute_internal_payment_hmac_signature,
    validate_strict_canonical_path,
)
from app.core.security.provenance_authority import (
    CryptographicVerificationProof,
    ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
    ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
    PROVENANCE_CONTRACT_FIELDS,
    PROVENANCE_SCHEMA_VERSION,
    ProvenanceSigningKeyring,
    ProvenanceSigner,
    ProvenanceVerificationKeyring,
    ProvenanceVerifier,
    TrustedSettlementVerificationBoundary,
    VerifiedSettlementCapability,
    canonicalize_rfc8785,
    canonicalize_rfc8785_str,
    validate_provenance_17_field_contract,
)
from app.services.payment.base import (
    PaymentAuthorizationError,
    PaymentConfigurationError,
    ReplayStoreUnavailableError,
    SettlementProvenanceError,
)


# =============================================================================
# Test Constants & Fixtures
# =============================================================================

TENANT_1_UUID = "7f9c2a10-4b55-4e88-9c11-112233445566"
TENANT_1_SLUG = "onlineboost"

TENANT_2_UUID = "9a8b7c6d-5e4f-4a3b-8c2d-665544332211"
TENANT_2_SLUG = "merchant-dua"

FAKE_APP_MASTER_KEY = "master_key_super_secret_do_not_use_for_payments_999999"

ACTIVE_KEY_ID = "pim_k202611_active"
ACTIVE_KEY_SECRET = "internal_hmac_secret_active_202611_high_entropy_key_001"
ACTIVE_PRINCIPAL = "svc:payment_settlement_worker"

PREV_KEY_ID = "pim_k202610_prev"
PREV_KEY_SECRET = "internal_hmac_secret_previous_202610_high_entropy_002"
PREV_PRINCIPAL = "svc:payment_settlement_worker"

REVOKED_KEY_ID = "pim_k202609_revoked"
REVOKED_KEY_SECRET = "internal_hmac_secret_revoked_202609_compromised_003"
REVOKED_PRINCIPAL = "svc:payment_settlement_worker"

# 32-byte Ed25519 private seeds (64 hex chars each)
PROV_ACTIVE_KEY_ID = "prv_k202611_v1"
PROV_ACTIVE_PRIV_HEX = "11" * 32

PROV_PREV_KEY_ID = "prv_k202610_v0"
PROV_PREV_PRIV_HEX = "22" * 32

PROV_REVOKED_KEY_ID = "prv_k202608_revoked"
PROV_REVOKED_PRIV_HEX = "33" * 32

PROV_OTHER_PRIV_HEX = "44" * 32

XENDIT_TEST_CALLBACK_SECRET = "xnd_cb_token_onlineboost_verified_secret_2026"
XENDIT_TEST_BUSINESS_ID = "5f4e3d2c1b0a998877665544"

FIXED_NOW_EPOCH = 1762345200  # 2025-11-05T12:20:00Z


class _FakePostgresState:
    """Thread-safe in-memory mock emulating PostgreSQL `orders`, `tenants`, and
    `public.payment_hmac_replay_nonces` for unit tests (`test_01`..`test_13`).
    (Note: Real PostgreSQL integration tests are in `test_phase1_stage1_pg_disposable_integration.py`).
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.available: bool = True
        self.tenants: Dict[str, Dict[str, Any]] = {
            TENANT_1_UUID: {"id": TENANT_1_UUID, "slug": TENANT_1_SLUG},
            TENANT_2_UUID: {"id": TENANT_2_UUID, "slug": TENANT_2_SLUG},
        }
        self.orders: Dict[str, Dict[str, Any]] = {
            "ORD-OB-1001": {
                "id": "ORD-OB-1001",
                "tenant_id": TENANT_1_UUID,
                "tenant_slug": TENANT_1_SLUG,
                "gross_amount": 249000,
                "sku_id": "kelas-inkubasi-ctwa-batch-1-scale",
                "status": "PENDING",
            },
            "ORD-M2-2002": {
                "id": "ORD-M2-2002",
                "tenant_id": TENANT_2_UUID,
                "tenant_slug": TENANT_2_SLUG,
                "gross_amount": 150000,
                "sku_id": "produk-merchant-dua",
                "status": "PENDING",
            },
            "ORD-LEGACY-NO-UUID": {
                "id": "ORD-LEGACY-NO-UUID",
                "tenant_id": "",
                "tenant_slug": TENANT_1_SLUG,
                "gross_amount": 99000,
                "sku_id": "legacy-sku",
                "status": "PENDING",
            },
            "ORD-CONFLICT-SLUG": {
                "id": "ORD-CONFLICT-SLUG",
                "tenant_id": TENANT_1_UUID,
                "tenant_slug": "wrong-spoofed-slug",
                "gross_amount": 249000,
                "sku_id": "kelas-inkubasi-ctwa-batch-1-scale",
                "status": "PENDING",
            },
        }
        self.replay_nonces: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def connect(self) -> "_FakePgConnection":
        if not self.available:
            raise RuntimeError("FATAL: terminating connection due to administrator command (PostgreSQL down)")
        return _FakePgConnection(self)


class _FakePgCursor:
    def __init__(self, state: _FakePostgresState) -> None:
        self._state = state
        self._rows: List[Tuple[Any, ...]] = []
        self._idx: int = 0

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        if not self._state.available:
            raise RuntimeError("PostgreSQL connection lost during query execution")

        normalized_sql = " ".join(sql.split()).upper()

        if (
            "FROM ORDERS O INNER JOIN TENANTS T ON O.TENANT_ID = T.ID::TEXT" in normalized_sql
            or "FROM ORDERS O INNER JOIN TENANTS T ON O.TENANT_ID::TEXT = T.ID::TEXT" in normalized_sql
        ):
            assert "OR O.TENANT_SLUG" not in normalized_sql
            order_id = params[0]
            with self._state.lock:
                order = self._state.orders.get(order_id)
                if not order:
                    self._rows = []
                    return
                t_id = str(order.get("tenant_id") or "")
                tenant = self._state.tenants.get(t_id)
                if not tenant:
                    self._rows = []
                    return
                self._rows = [
                    (
                        order["id"],
                        order["tenant_id"],
                        order["tenant_slug"],
                        tenant["id"],
                        tenant["slug"],
                        order["gross_amount"],
                        order["sku_id"],
                        order["status"],
                    )
                ]
            self._idx = 0
            return

        if "FROM ORDERS O WHERE O.ID = %S" in normalized_sql:
            order_id = params[0]
            with self._state.lock:
                order = self._state.orders.get(order_id)
                if not order:
                    self._rows = []
                else:
                    self._rows = [(order["id"], order["tenant_id"], order["tenant_slug"])]
            self._idx = 0
            return

        if "FROM TENANTS T WHERE T.SLUG = %S" in normalized_sql:
            slug = params[0]
            with self._state.lock:
                matches = [
                    (t["id"], t["slug"])
                    for t in self._state.tenants.values()
                    if t["slug"] == slug
                ]
                self._rows = matches
            self._idx = 0
            return

        if "INSERT INTO PUBLIC.PAYMENT_HMAC_REPLAY_NONCES" in normalized_sql:
            (
                key_id,
                nonce,
                actor_principal,
                canonical_tenant_id,
                order_id,
                http_method,
                canonical_path,
                request_timestamp,
                body_sha256,
                consumed_at,
                expires_at,
            ) = params
            composite_key = (key_id, nonce)
            with self._state.lock:
                if composite_key in self._state.replay_nonces:
                    self._rows = []
                else:
                    self._state.replay_nonces[composite_key] = {
                        "key_id": key_id,
                        "nonce": nonce,
                        "actor_principal": actor_principal,
                        "canonical_tenant_id": canonical_tenant_id,
                        "order_id": order_id,
                        "http_method": http_method,
                        "canonical_path": canonical_path,
                        "request_timestamp": request_timestamp,
                        "body_sha256": body_sha256,
                        "consumed_at": consumed_at,
                        "expires_at": expires_at,
                    }
                    self._rows = [(key_id, nonce)]
            self._idx = 0
            return

        raise NotImplementedError(f"Unhandled SQL in _FakePgCursor: {sql}")

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if self._idx >= len(self._rows):
            return None
        row = self._rows[self._idx]
        self._idx += 1
        return row

    def fetchall(self) -> List[Tuple[Any, ...]]:
        rem = self._rows[self._idx :]
        self._idx = len(self._rows)
        return rem

    def close(self) -> None:
        pass


class _FakePgConnection:
    def __init__(self, state: _FakePostgresState) -> None:
        self._state = state

    def cursor(self) -> _FakePgCursor:
        return _FakePgCursor(self._state)

    def commit(self) -> None:
        if not self._state.available:
            raise RuntimeError("Commit failed: PostgreSQL connection terminated")

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeRedisClient:
    def __init__(self) -> None:
        self.store: Dict[str, str] = {}
        self.get_calls: int = 0
        self.set_calls: int = 0

    def get(self, key: str) -> Optional[str]:
        self.get_calls += 1
        return self.store.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        self.set_calls += 1
        self.store[key] = value


def _build_stage1_verifier(
    pg_state: Optional[_FakePostgresState] = None,
    redis_client: Optional[_FakeRedisClient] = None,
) -> Tuple[InternalPaymentHMACVerifier, _FakePostgresState]:
    state = pg_state or _FakePostgresState()
    keyring = InternalPaymentHMACKeyring(
        keys={
            ACTIVE_KEY_ID: {
                "secret": ACTIVE_KEY_SECRET,
                "status": "ACTIVE",
                "bound_principal": ACTIVE_PRINCIPAL,
                "bound_tenant_id": TENANT_1_UUID,
            },
            PREV_KEY_ID: {
                "secret": PREV_KEY_SECRET,
                "status": "VERIFY_ONLY",
                "bound_principal": PREV_PRINCIPAL,
                "bound_tenant_id": TENANT_1_UUID,
                "not_after_epoch": FIXED_NOW_EPOCH + 3600,
            },
            REVOKED_KEY_ID: {
                "secret": REVOKED_KEY_SECRET,
                "status": "REVOKED",
                "bound_principal": REVOKED_PRINCIPAL,
                "bound_tenant_id": TENANT_1_UUID,
            },
        },
        app_master_key=FAKE_APP_MASTER_KEY,
    )
    resolver = CanonicalTenantResolver(state.connect)
    replay_store = PostgresAuthoritativeReplayStore(
        state.connect,
        redis_client=redis_client,
        ttl_seconds=600,
    )
    verifier = InternalPaymentHMACVerifier(
        keyring=keyring,
        tenant_resolver=resolver,
        replay_store=replay_store,
        app_master_key=FAKE_APP_MASTER_KEY,
        timestamp_tolerance_seconds=300,
    )
    return verifier, state


def _build_signed_headers(
    *,
    key_id: str = ACTIVE_KEY_ID,
    secret: str = ACTIVE_KEY_SECRET,
    timestamp: int = FIXED_NOW_EPOCH,
    nonce: str = "nonce_stage1_0001",
    http_method: str = "POST",
    canonical_path: str = "/api/v1/orders/ORD-OB-1001/approve-and-deliver",
    order_id: str = "ORD-OB-1001",
    canonical_tenant_id: str = TENANT_1_UUID,
    raw_body: bytes = b'{"reason":"verified_delivery"}',
    actor_header: Optional[str] = ACTIVE_PRINCIPAL,
) -> Dict[str, str]:
    sig = compute_internal_payment_hmac_signature(
        secret=secret,
        key_id=key_id,
        timestamp=timestamp,
        nonce=nonce,
        http_method=http_method,
        canonical_path=canonical_path,
        order_id=order_id,
        canonical_tenant_id=canonical_tenant_id,
        raw_body=raw_body,
    )
    headers = {
        HDR_KEY_ID: key_id,
        HDR_TIMESTAMP: str(timestamp),
        HDR_NONCE: nonce,
        HDR_SIGNATURE: sig,
    }
    if actor_header is not None:
        headers[HDR_ACTOR] = actor_header
    return headers


def _mint_valid_xendit_capability(
    *,
    order_id: str = "ORD-OB-1001",
    canonical_tenant_id: str = TENANT_1_UUID,
    amount: int = 249000,
    sku_id: str = "kelas-inkubasi-ctwa-batch-1-scale",
) -> VerifiedSettlementCapability:
    return TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="XENDIT",
        verification_method="XENDIT_CALLBACK_TOKEN",
        credential_profile_id="cred_xendit_onlineboost_prod",
        expected_provider_account_id=XENDIT_TEST_BUSINESS_ID,
        provider_verification_secret=XENDIT_TEST_CALLBACK_SECRET,
        webhook_headers={"x-callback-token": XENDIT_TEST_CALLBACK_SECRET},
        webhook_payload={
            "id": "evt_xnd_99887766",
            "event_id": "evt_xnd_99887766",
            "payment_id": "qrpy_99887766",
            "business_id": XENDIT_TEST_BUSINESS_ID,
            "status": "SUCCEEDED",
            "amount": amount,
        },
        authoritative_order_id=order_id,
        authoritative_canonical_tenant_id=canonical_tenant_id,
        authoritative_order_amount=amount,
        authoritative_sku_id=sku_id,
        verified_at_utc="2026-11-05T13:00:00Z",
    )


# =============================================================================
# Test Cases 1 - 10: Internal Payment Mutation HMAC & Anti-Replay Store
# =============================================================================

def test_01_valid_hmac_signature_passes() -> None:
    redis_l1 = _FakeRedisClient()
    verifier, pg_state = _build_stage1_verifier(redis_client=redis_l1)
    body = b'{"reason":"verified_delivery"}'
    headers = _build_signed_headers(nonce="nonce_valid_001", raw_body=body)

    ctx = verifier.verify_mutation_request(
        headers=headers,
        http_method="POST",
        canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
        order_id="ORD-OB-1001",
        raw_body=body,
        now_epoch=FIXED_NOW_EPOCH,
    )

    assert ctx.key_id == ACTIVE_KEY_ID
    assert ctx.verified_actor_principal == ACTIVE_PRINCIPAL
    assert ctx.canonical_tenant_id == TENANT_1_UUID
    assert ctx.order_id == "ORD-OB-1001"
    assert (ACTIVE_KEY_ID, "nonce_valid_001") in pg_state.replay_nonces
    assert redis_l1.set_calls == 1


def test_02_invalid_hmac_signature_rejected() -> None:
    verifier, pg_state = _build_stage1_verifier()
    body = b'{"reason":"verified_delivery"}'
    headers = _build_signed_headers(nonce="nonce_invalid_sig_002", raw_body=body)
    headers[HDR_SIGNATURE] = "0" * 64

    with pytest.raises(PaymentAuthorizationError) as exc_info:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_info.value.error_code == "INVALID_HMAC_SIGNATURE"
    assert (ACTIVE_KEY_ID, "nonce_invalid_sig_002") not in pg_state.replay_nonces


def test_03_tampered_body_method_path_order_id_rejected() -> None:
    verifier, pg_state = _build_stage1_verifier()
    original_body = b'{"reason":"verified_delivery"}'
    headers = _build_signed_headers(nonce="nonce_tamper_003", raw_body=original_body)

    with pytest.raises(PaymentAuthorizationError) as exc_body:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=b'{"reason":"tampered_body"}',
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_body.value.error_code == "INVALID_HMAC_SIGNATURE"

    with pytest.raises(PaymentAuthorizationError) as exc_method:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="PATCH",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=original_body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_method.value.error_code == "INVALID_HMAC_SIGNATURE"

    with pytest.raises(PaymentAuthorizationError) as exc_path:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/status",
            order_id="ORD-OB-1001",
            raw_body=original_body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_path.value.error_code == "INVALID_HMAC_SIGNATURE"
    assert (ACTIVE_KEY_ID, "nonce_tamper_003") not in pg_state.replay_nonces


def test_04_expired_and_future_timestamp_rejected() -> None:
    verifier, _ = _build_stage1_verifier()
    body = b'{"reason":"verified_delivery"}'

    expired_headers = _build_signed_headers(
        timestamp=FIXED_NOW_EPOCH - 301,
        nonce="nonce_expired_ts",
        raw_body=body,
    )
    with pytest.raises(PaymentAuthorizationError) as exc_exp:
        verifier.verify_mutation_request(
            headers=expired_headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_exp.value.error_code == "TIMESTAMP_OUT_OF_WINDOW"

    future_headers = _build_signed_headers(
        timestamp=FIXED_NOW_EPOCH + 301,
        nonce="nonce_future_ts",
        raw_body=body,
    )
    with pytest.raises(PaymentAuthorizationError) as exc_fut:
        verifier.verify_mutation_request(
            headers=future_headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_fut.value.error_code == "TIMESTAMP_OUT_OF_WINDOW"


def test_05_duplicate_nonce_replay_rejected() -> None:
    verifier, _ = _build_stage1_verifier(redis_client=None)
    body = b'{"reason":"verified_delivery"}'
    headers = _build_signed_headers(nonce="nonce_replay_005", raw_body=body)

    verifier.verify_mutation_request(
        headers=headers,
        http_method="POST",
        canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
        order_id="ORD-OB-1001",
        raw_body=body,
        now_epoch=FIXED_NOW_EPOCH,
    )

    with pytest.raises(PaymentAuthorizationError) as exc_replay:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_replay.value.error_code == "DUPLICATE_NONCE_REPLAY"


def test_06_concurrent_duplicate_nonce_race_condition() -> None:
    verifier, pg_state = _build_stage1_verifier(redis_client=None)
    body = b'{"reason":"concurrent_race_test"}'
    shared_nonce = "nonce_race_condition_shared_999"
    headers = _build_signed_headers(nonce=shared_nonce, raw_body=body)

    worker_count = 16
    barrier = threading.Barrier(worker_count)
    successes: List[str] = []
    replay_rejections: List[str] = []
    unexpected_errors: List[Exception] = []
    result_lock = threading.Lock()

    def _worker() -> None:
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
            with result_lock:
                successes.append(ctx.nonce)
        except PaymentAuthorizationError as auth_err:
            with result_lock:
                if auth_err.error_code == "DUPLICATE_NONCE_REPLAY":
                    replay_rejections.append(auth_err.error_code)
                else:
                    unexpected_errors.append(auth_err)
        except Exception as err:
            with result_lock:
                unexpected_errors.append(err)

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(_worker) for _ in range(worker_count)]
        for f in futures:
            f.result()

    assert not unexpected_errors
    assert len(successes) == 1
    assert len(replay_rejections) == worker_count - 1
    assert len(pg_state.replay_nonces) == 1


def test_07_postgresql_replay_store_outage_fails_closed_even_when_redis_healthy() -> None:
    healthy_redis = _FakeRedisClient()
    pg_state = _FakePostgresState()
    verifier, _ = _build_stage1_verifier(pg_state=pg_state, redis_client=healthy_redis)

    body = b'{"reason":"verified_delivery"}'
    headers = _build_signed_headers(nonce="nonce_pg_outage_007", raw_body=body)

    def _broken_pg_connect() -> Any:
        raise RuntimeError("psycopg2.OperationalError: FATAL: remaining connection slots are reserved")

    verifier._replay_store._db_conn_factory = _broken_pg_connect

    with pytest.raises(ReplayStoreUnavailableError) as exc_info:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )

    assert exc_info.value.error_code == "REPLAY_STORE_UNAVAILABLE"
    assert exc_info.value.http_status == 503
    assert healthy_redis.set_calls == 0


def test_08_unknown_and_revoked_hmac_key_id_rejected() -> None:
    verifier, _ = _build_stage1_verifier()
    body = b'{"reason":"verified_delivery"}'

    unknown_headers = _build_signed_headers(
        key_id="pim_unknown_key_999",
        secret=ACTIVE_KEY_SECRET,
        nonce="nonce_unk_key",
        raw_body=body,
    )
    with pytest.raises(PaymentAuthorizationError) as exc_unk:
        verifier.verify_mutation_request(
            headers=unknown_headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_unk.value.error_code == "UNKNOWN_HMAC_KEY_ID"

    revoked_headers = _build_signed_headers(
        key_id=REVOKED_KEY_ID,
        secret=REVOKED_KEY_SECRET,
        nonce="nonce_rev_key",
        raw_body=body,
    )
    with pytest.raises(PaymentAuthorizationError) as exc_rev:
        verifier.verify_mutation_request(
            headers=revoked_headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_rev.value.error_code == "REVOKED_HMAC_KEY_ID"


def test_09_app_master_key_rejected_for_payment_mutation() -> None:
    verifier, _ = _build_stage1_verifier()
    body = b'{"reason":"verified_delivery"}'
    headers = _build_signed_headers(nonce="nonce_master_009", raw_body=body)
    headers[HDR_AUTHORIZATION] = f"Bearer {FAKE_APP_MASTER_KEY}"

    with pytest.raises(PaymentAuthorizationError) as exc_master:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_master.value.error_code == "APP_MASTER_KEY_FORBIDDEN"

    with pytest.raises(PaymentConfigurationError):
        InternalPaymentHMACKeyring(
            keys={
                "pim_bad_master": {
                    "secret": FAKE_APP_MASTER_KEY,
                    "status": "ACTIVE",
                    "bound_principal": "svc:bad",
                }
            },
            app_master_key=FAKE_APP_MASTER_KEY,
        )


def test_10_spoofed_actor_id_and_tenant_id_in_request_body_rejected() -> None:
    verifier, _ = _build_stage1_verifier()

    spoofed_actor_body = b'{"actor_id":"admin:super_spoof","reason":"verified_delivery"}'
    headers_actor = _build_signed_headers(nonce="nonce_spoof_actor", raw_body=spoofed_actor_body)
    with pytest.raises(PaymentAuthorizationError) as exc_actor:
        verifier.verify_mutation_request(
            headers=headers_actor,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=spoofed_actor_body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_actor.value.error_code == "ACTOR_IDENTITY_SPOOFING_DETECTED"

    spoofed_tenant_body = json.dumps({"tenant_id": TENANT_2_UUID, "reason": "verified_delivery"}).encode("utf-8")
    headers_tenant = _build_signed_headers(nonce="nonce_spoof_tenant", raw_body=spoofed_tenant_body)
    with pytest.raises(PaymentAuthorizationError) as exc_tenant:
        verifier.verify_mutation_request(
            headers=headers_tenant,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=spoofed_tenant_body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_tenant.value.error_code == "TENANT_SPOOFING_DETECTED"


# =============================================================================
# Test Cases 11 - 13: Canonical Tenant Identity Resolution
# =============================================================================

def test_11_canonical_tenant_resolution_success() -> None:
    state = _FakePostgresState()
    resolver = CanonicalTenantResolver(state.connect)

    ctx = resolver.resolve_order_tenant_strict(
        "ORD-OB-1001",
        expected_actor_tenant_id=TENANT_1_UUID,
    )
    assert ctx.order_id == "ORD-OB-1001"
    assert ctx.canonical_tenant_id == TENANT_1_UUID
    assert ctx.canonical_tenant_slug == TENANT_1_SLUG
    assert ctx.gross_amount == 249000


def test_12_tenant_slug_fallback_prohibited_and_unresolved_legacy_order_fails_closed() -> None:
    verifier, state = _build_stage1_verifier()
    resolver = CanonicalTenantResolver(state.connect)

    with pytest.raises(PaymentAuthorizationError) as exc_slug:
        resolver.resolve_legacy_slug_for_migration_only(TENANT_1_SLUG, allow_migration_inspection=False)
    assert exc_slug.value.error_code == "LEGACY_SLUG_FALLBACK_FORBIDDEN"

    headers = _build_signed_headers(
        nonce="nonce_legacy_unresolved",
        order_id="ORD-LEGACY-NO-UUID",
        canonical_path="/api/v1/orders/ORD-LEGACY-NO-UUID/approve-and-deliver",
    )
    with pytest.raises(PaymentAuthorizationError) as exc_legacy:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-LEGACY-NO-UUID/approve-and-deliver",
            order_id="ORD-LEGACY-NO-UUID",
            raw_body=b'{"reason":"verified_delivery"}',
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_legacy.value.error_code == "UNRESOLVED_CANONICAL_TENANT_ID"
    assert exc_legacy.value.http_status == 422


def test_13_tenant_mismatch_against_order() -> None:
    verifier, _ = _build_stage1_verifier()
    headers_cross_tenant = _build_signed_headers(
        nonce="nonce_cross_tenant_0013",
        order_id="ORD-M2-2002",
        canonical_tenant_id=TENANT_2_UUID,
        canonical_path="/api/v1/orders/ORD-M2-2002/approve-and-deliver",
    )

    with pytest.raises(PaymentAuthorizationError) as exc_info:
        verifier.verify_mutation_request(
            headers=headers_cross_tenant,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-M2-2002/approve-and-deliver",
            order_id="ORD-M2-2002",
            raw_body=b'{"reason":"verified_delivery"}',
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_info.value.error_code == "ORDER_TENANT_MISMATCH"
    assert exc_info.value.http_status == 403


# =============================================================================
# Test Cases 14 - 15: RFC 8785 (JCS) Full Conformance & Exponent Boundaries
# =============================================================================

def test_14_rfc8785_official_appendix_b_and_exponent_boundaries() -> None:
    """Requirement 14: Verifies official RFC 8785 Appendix B vectors, ECMAScript
    Number::toString exponent boundary cases (10^-6 fixed vs 10^-7 exponential,
    10^20 fixed vs 10^21 exponential, 1e-5 fixed), binary64 edge cases, and
    cross-implementation SHA-256 digest consistency.
    """
    # 1. Official RFC 8785 §3.2.3 UTF-16 Key Sorting Vector
    sorting_input = {
        "\ue000": "bmp_after_surrogate",
        "😀": "grinning_face_u1f600",
        "\u0080": "latin1_ctrl",
        "a": "lower_a",
        "2": "two",
        "10": "ten",
        "1": "one",
        "\r": "carriage_return",
    }
    assert canonicalize_rfc8785_str(sorting_input) == (
        '{"\\r":"carriage_return","1":"one","10":"ten","2":"two",'
        '"a":"lower_a","\u0080":"latin1_ctrl","😀":"grinning_face_u1f600","\ue000":"bmp_after_surrogate"}'
    )

    # 2. Numeric Exponent Boundary Vectors (RFC 8785 §3.2.2.3 / ECMA-262 §7.1.12.1)
    exponent_vectors = [
        (0.0, "0"),
        (-0.0, "0"),
        (-0, "0"),
        (1.0, "1"),
        (4.50, "4.5"),
        (2e-3, "0.002"),
        (1e-5, "0.00001"),        # Crucial: Python repr(1e-5) is '1e-05', RFC 8785 requires '0.00001'
        (-2.5e-5, "-0.000025"),
        (1e-6, "0.000001"),       # Exact lower fixed-point boundary (10^-6)
        (-1e-6, "-0.000001"),
        (1e-7, "1e-7"),           # Exact lower exponential boundary (10^-7)
        (-1e-7, "-1e-7"),
        (333333333.33333329, "333333333.3333333"),  # RFC 8785 Appendix B precision vector
        (1e16, "10000000000000000"),
        (1.5e16, "15000000000000000"),
        (1e20, "100000000000000000000"),            # Exact upper fixed-point boundary (< 10^21)
        (1e21, "1e+21"),                            # Exact upper exponential boundary (>= 10^21)
        (-1e21, "-1e+21"),
        (1e30, "1e+30"),
        (1.7976931348623157e+308, "1.7976931348623157e+308"),
        (5e-324, "5e-324"),
    ]
    for num_val, expected_json in exponent_vectors:
        assert canonicalize_rfc8785_str(num_val) == expected_json, f"Mismatch for {num_val!r}"

    # 3. Official RFC 8785 Appendix B "numbers" structure cross-implementation test vector
    rfc8785_numbers_doc = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001]
    }
    expected_numbers_canonical = '{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'
    assert canonicalize_rfc8785_str(rfc8785_numbers_doc) == expected_numbers_canonical
    assert (
        hashlib.sha256(canonicalize_rfc8785(rfc8785_numbers_doc)).hexdigest()
        == hashlib.sha256(expected_numbers_canonical.encode("utf-8")).hexdigest()
    )

    # 4. NaN, +Infinity, -Infinity must be rejected
    for non_finite in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            canonicalize_rfc8785({"bad": non_finite})


def test_15_rfc8785_unicode_and_invalid_surrogate_rejection() -> None:
    """Requirement 15: Tests lone high surrogate, lone low surrogate, reversed surrogate pair,
    and non-canonical input types (Decimal, set, bytes, non-str dict keys).
    """
    for bad_surrogate in ("\ud800", "\udfff", "prefix\ud83dsuffix", "\ude00\ud83d"):
        with pytest.raises(ValueError):
            canonicalize_rfc8785({"text": bad_surrogate})
        with pytest.raises(ValueError):
            canonicalize_rfc8785({bad_surrogate: "val"})

    for unsupported_obj in (Decimal("249000.00"), {"a", "b"}, b"raw_bytes", {123: "int_key"}):
        with pytest.raises(ValueError):
            canonicalize_rfc8785(unsupported_obj)


# =============================================================================
# Test Cases 16 - 20: Ed25519 Provenance Authority, Boundary Capability & Rail Lock
# =============================================================================

def test_16_provenance_17_field_contract_and_integer_amount_enforcement() -> None:
    assert len(PROVENANCE_CONTRACT_FIELDS) == 17

    signing_keyring = ProvenanceSigningKeyring(
        keys={PROV_ACTIVE_KEY_ID: {"private_key_hex": PROV_ACTIVE_PRIV_HEX, "status": "ACTIVE"}},
        forbidden_secrets=frozenset({ACTIVE_KEY_SECRET, FAKE_APP_MASTER_KEY}),
    )
    verify_keyring = signing_keyring.export_public_verification_keyring()
    signer = ProvenanceSigner(signing_keyring)
    verifier = ProvenanceVerifier(verify_keyring)

    capability = _mint_valid_xendit_capability()
    envelope = signer.sign_verified_settlement(capability)

    assert set(envelope["fields"].keys()) == set(PROVENANCE_CONTRACT_FIELDS)
    assert len(envelope["fields"]) == 17
    assert envelope["algorithm"] == "Ed25519"
    assert len(envelope["signature"]) == 128

    verified = verifier.verify_provenance_envelope(
        envelope,
        expected_order_id="ORD-OB-1001",
        expected_canonical_tenant_id=TENANT_1_UUID,
        expected_amount=249000,
        expected_sku_id="kelas-inkubasi-ctwa-batch-1-scale",
        required_rail_type="NATIVE_PG",
    )
    assert verified["verified_amount"] == 249000

    # Tamper with each mutable field and prove Ed25519 verification fails closed
    tamper_mutations: Dict[str, Any] = {
        "actor_principal": "pg_webhook:xendit:spoofed",
        "canonical_tenant_id": TENANT_2_UUID,
        "credential_profile_id": "cred_tampered",
        "event_id": "evt_xnd_tampered",
        "order_id": "ORD-OB-9999",
        "provider": "MIDTRANS",
        "provider_account_id": "acct_tampered",
        "provider_event_id": "qrpy_tampered",
        "sku_id": "tampered-sku",
        "verification_method": "MIDTRANS_SHA512",
        "verified_amount": 1500,
        "verified_at_utc": "2026-11-05T13:00:01Z",
    }
    for field_name, new_val in tamper_mutations.items():
        tampered_fields = dict(envelope["fields"])
        tampered_fields[field_name] = new_val
        with pytest.raises(SettlementProvenanceError) as exc_tamper:
            verifier.verify_provenance_envelope({"fields": tampered_fields, "signature": envelope["signature"]})
        assert exc_tamper.value.error_code == "PROVENANCE_SIGNATURE_MISMATCH"

    # Floating-point or boolean amount must be rejected
    for bad_amount in (249000.0, 249000.5, True, False, 0, -100):
        bad_amt_fields = dict(envelope["fields"])
        bad_amt_fields["verified_amount"] = bad_amount
        with pytest.raises(SettlementProvenanceError) as exc_amt:
            validate_provenance_17_field_contract(bad_amt_fields)
        assert exc_amt.value.error_code == "PROVENANCE_INVALID_AMOUNT"


def test_17_provenance_ed25519_public_key_only_verifier_and_key_rotation() -> None:
    """Requirement 17: Verifies Ed25519 asymmetric separation (verifier keyring rejects private keys),
    key separation from internal HMAC, key rotation (`ACTIVE`, `VERIFY_ONLY`, `REVOKED`), and key mismatch.
    """
    # Case A: Verifier keyring rejects any entry containing a private key or secret
    with pytest.raises(SettlementProvenanceError) as exc_priv_in_ver:
        ProvenanceVerificationKeyring(
            {
                PROV_ACTIVE_KEY_ID: {
                    "public_key_hex": "aa" * 32,
                    "private_key_hex": PROV_ACTIVE_PRIV_HEX,
                    "status": "ACTIVE",
                }
            }
        )
    assert exc_priv_in_ver.value.error_code == "PROVENANCE_VERIFIER_PRIVATE_KEY_FORBIDDEN"

    # Case B: Key separation violation (reusing ACTIVE_KEY_SECRET in ProvenanceSigningKeyring)
    with pytest.raises(SettlementProvenanceError) as exc_sep:
        ProvenanceSigningKeyring(
            keys={"prv_bad": {"private_key_hex": ACTIVE_KEY_SECRET, "status": "ACTIVE"}},
            forbidden_secrets=frozenset({ACTIVE_KEY_SECRET}),
        )
    assert exc_sep.value.error_code == "PROVENANCE_KEY_SEPARATION_VIOLATION"

    signing_keyring = ProvenanceSigningKeyring(
        keys={
            PROV_ACTIVE_KEY_ID: {"private_key_hex": PROV_ACTIVE_PRIV_HEX, "status": "ACTIVE"},
            PROV_PREV_KEY_ID: {"private_key_hex": PROV_PREV_PRIV_HEX, "status": "VERIFY_ONLY"},
            PROV_REVOKED_KEY_ID: {"private_key_hex": PROV_REVOKED_PRIV_HEX, "status": "REVOKED"},
        }
    )
    public_verify_keyring = signing_keyring.export_public_verification_keyring()
    signer = ProvenanceSigner(signing_keyring)
    verifier = ProvenanceVerifier(public_verify_keyring)
    capability = _mint_valid_xendit_capability()

    # Case C: Attempting to sign with VERIFY_ONLY or REVOKED key -> rejected
    with pytest.raises(SettlementProvenanceError) as exc_vo:
        signer.sign_verified_settlement(capability, key_id=PROV_PREV_KEY_ID)
    assert exc_vo.value.error_code == "PROVENANCE_KEY_NOT_ACTIVE"

    with pytest.raises(SettlementProvenanceError) as exc_rev_sign:
        signer.sign_verified_settlement(capability, key_id=PROV_REVOKED_KEY_ID)
    assert exc_rev_sign.value.error_code == "PROVENANCE_KEY_REVOKED"

    # Case D: Unknown or REVOKED key during verification -> rejected
    valid_env = signer.sign_verified_settlement(capability, key_id=PROV_ACTIVE_KEY_ID)
    unk_fields = dict(valid_env["fields"])
    unk_fields["prov_key_id"] = "prv_unknown_9999"
    with pytest.raises(SettlementProvenanceError) as exc_unk:
        verifier.verify_provenance_envelope({"fields": unk_fields, "signature": valid_env["signature"]})
    assert exc_unk.value.error_code == "UNKNOWN_PROVENANCE_KEY_ID"

    rev_fields = dict(valid_env["fields"])
    rev_fields["prov_key_id"] = PROV_REVOKED_KEY_ID
    with pytest.raises(SettlementProvenanceError) as exc_rev_ver:
        verifier.verify_provenance_envelope({"fields": rev_fields, "signature": valid_env["signature"]})
    assert exc_rev_ver.value.error_code == "PROVENANCE_KEY_REVOKED"

    # Case E: Key mismatch (signed with a different Ed25519 private key claiming PROV_ACTIVE_KEY_ID) -> rejected
    rogue_keyring = ProvenanceSigningKeyring(
        keys={PROV_ACTIVE_KEY_ID: {"private_key_hex": PROV_OTHER_PRIV_HEX, "status": "ACTIVE"}}
    )
    rogue_env = ProvenanceSigner(rogue_keyring).sign_verified_settlement(capability, key_id=PROV_ACTIVE_KEY_ID)
    with pytest.raises(SettlementProvenanceError) as exc_mismatch:
        verifier.verify_provenance_envelope(rogue_env)
    assert exc_mismatch.value.error_code == "PROVENANCE_SIGNATURE_MISMATCH"

    # Case F: Historical envelope signed before key rotation (when PROV_PREV_KEY_ID was ACTIVE)
    # verifies cleanly when PROV_PREV_KEY_ID is in VERIFY_ONLY state on the public keyring
    hist_keyring = ProvenanceSigningKeyring(
        keys={PROV_PREV_KEY_ID: {"private_key_hex": PROV_PREV_PRIV_HEX, "status": "ACTIVE"}}
    )
    hist_env = ProvenanceSigner(hist_keyring).sign_verified_settlement(capability, key_id=PROV_PREV_KEY_ID)
    verified_hist = verifier.verify_provenance_envelope(hist_env)
    assert verified_hist["prov_key_id"] == PROV_PREV_KEY_ID


def test_18_caller_cannot_instantiate_proof_directly_with_allowlisted_string() -> None:
    """Requirement 18: Proves that an application caller cannot forge a settlement proof
    simply by instantiating `CryptographicVerificationProof` / `VerifiedSettlementCapability`
    and choosing an allowlisted `proof_source` string (`"VERIFIED_PG_WEBHOOK_ADAPTER"`).
    """
    # 1. Attempting direct dataclass instantiation with allowlisted string -> UNTRUSTED_PROVENANCE_CALLER
    with pytest.raises(SettlementProvenanceError) as exc_direct:
        CryptographicVerificationProof(
            proof_source="VERIFIED_PG_WEBHOOK_ADAPTER",
            actor_principal="pg_webhook:xendit:forged",
            canonical_tenant_id=TENANT_1_UUID,
            credential_profile_id="cred_xendit_onlineboost_prod",
            event_id="evt_forged",
            order_id="ORD-OB-1001",
            provider="XENDIT",
            provider_account_id=XENDIT_TEST_BUSINESS_ID,
            provider_event_id="qrpy_forged",
            rail_type="NATIVE_PG",
            sku_id="kelas-inkubasi-ctwa-batch-1-scale",
            verification_method="XENDIT_CALLBACK_TOKEN",
            verified_amount=249000,
            verified_at_utc="2026-11-05T13:00:00Z",
        )
    assert exc_direct.value.error_code == "UNTRUSTED_PROVENANCE_CALLER"

    # 2. Attempting direct instantiation with untrusted sources -> UNTRUSTED_PROVENANCE_SOURCE
    for forbidden_source in ("ORDER_STATUS_PAID_COLUMN", "APPLICATION_REQUEST_CLAIM", "PUBLIC_MARK_PAID"):
        with pytest.raises(SettlementProvenanceError) as exc_src:
            CryptographicVerificationProof(
                proof_source=forbidden_source,
                actor_principal="app:untrusted_caller",
                canonical_tenant_id=TENANT_1_UUID,
                credential_profile_id="cred_none",
                event_id="evt_fake",
                order_id="ORD-OB-1001",
                provider="XENDIT",
                provider_account_id="acct",
                provider_event_id="evt",
                rail_type="NATIVE_PG",
                sku_id="kelas-inkubasi-ctwa-batch-1-scale",
                verification_method="XENDIT_CALLBACK_TOKEN",
                verified_amount=249000,
                verified_at_utc="2026-11-05T13:00:00Z",
            )
        assert exc_src.value.error_code == "UNTRUSTED_PROVENANCE_SOURCE"


def test_19_verified_pg_webhook_gate_mints_and_binds_verifier_identity() -> None:
    """Requirement 19: Verifies that `TrustedSettlementVerificationBoundary` validates
    Xendit callback tokens and Midtrans SHA-512 signatures, enforces account binding,
    and deterministically binds `actor_principal`.
    """
    # 1. Wrong Xendit callback token -> PG_WEBHOOK_SIGNATURE_INVALID
    with pytest.raises(SettlementProvenanceError) as exc_bad_tok:
        TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
            provider="XENDIT",
            verification_method="XENDIT_CALLBACK_TOKEN",
            credential_profile_id="cred_xendit_onlineboost_prod",
            expected_provider_account_id=XENDIT_TEST_BUSINESS_ID,
            provider_verification_secret=XENDIT_TEST_CALLBACK_SECRET,
            webhook_headers={"x-callback-token": "wrong_forged_token"},
            webhook_payload={
                "id": "evt_1",
                "business_id": XENDIT_TEST_BUSINESS_ID,
                "status": "SUCCEEDED",
                "amount": 249000,
            },
            authoritative_order_id="ORD-OB-1001",
            authoritative_canonical_tenant_id=TENANT_1_UUID,
            authoritative_order_amount=249000,
            authoritative_sku_id="kelas-inkubasi-ctwa-batch-1-scale",
            verified_at_utc="2026-11-05T13:00:00Z",
        )
    assert exc_bad_tok.value.error_code == "PG_WEBHOOK_SIGNATURE_INVALID"

    # 2. Wrong business_id (cross-merchant webhook replay) -> PROVIDER_ACCOUNT_BINDING_MISMATCH
    with pytest.raises(SettlementProvenanceError) as exc_bad_acct:
        TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
            provider="XENDIT",
            verification_method="XENDIT_CALLBACK_TOKEN",
            credential_profile_id="cred_xendit_onlineboost_prod",
            expected_provider_account_id=XENDIT_TEST_BUSINESS_ID,
            provider_verification_secret=XENDIT_TEST_CALLBACK_SECRET,
            webhook_headers={"x-callback-token": XENDIT_TEST_CALLBACK_SECRET},
            webhook_payload={
                "id": "evt_1",
                "business_id": "other_merchant_business_id_999",
                "status": "SUCCEEDED",
                "amount": 249000,
            },
            authoritative_order_id="ORD-OB-1001",
            authoritative_canonical_tenant_id=TENANT_1_UUID,
            authoritative_order_amount=249000,
            authoritative_sku_id="kelas-inkubasi-ctwa-batch-1-scale",
            verified_at_utc="2026-11-05T13:00:00Z",
        )
    assert exc_bad_acct.value.error_code == "PROVIDER_ACCOUNT_BINDING_MISMATCH"

    # 3. Valid Midtrans SHA-512 verification succeeds and binds deterministic actor_principal
    midtrans_server_key = "SB-Mid-server-verified_secret_key_2026"
    midtrans_sig = hashlib.sha512(
        f"ORD-OB-1001200249000.00{midtrans_server_key}".encode("utf-8")
    ).hexdigest()
    mid_cap = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="MIDTRANS",
        verification_method="MIDTRANS_SHA512",
        credential_profile_id="cred_midtrans_onlineboost",
        expected_provider_account_id="G123456789",
        provider_verification_secret=midtrans_server_key,
        webhook_headers={},
        webhook_payload={
            "order_id": "ORD-OB-1001",
            "status_code": "200",
            "gross_amount": "249000.00",
            "signature_key": midtrans_sig,
            "merchant_id": "G123456789",
            "transaction_status": "settlement",
            "transaction_id": "mid_tx_889900",
        },
        authoritative_order_id="ORD-OB-1001",
        authoritative_canonical_tenant_id=TENANT_1_UUID,
        authoritative_order_amount=249000,
        authoritative_sku_id="kelas-inkubasi-ctwa-batch-1-scale",
        verified_at_utc="2026-11-05T13:00:00Z",
    )
    assert mid_cap.actor_principal == "pg_webhook:midtrans:cred_midtrans_onlineboost"


def test_20_direct_tenant_rail_signing_and_verification_locked() -> None:
    """Requirement 20: While Direct Tenant Rail is disabled, neither the boundary,
    the signer, nor the verifier permits `MANUAL_DIRECT_TENANT`.
    """
    with pytest.raises(SettlementProvenanceError) as exc_boundary:
        TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
            provider="XENDIT",
            verification_method="XENDIT_CALLBACK_TOKEN",
            credential_profile_id="cred_xendit_onlineboost_prod",
            expected_provider_account_id=XENDIT_TEST_BUSINESS_ID,
            provider_verification_secret=XENDIT_TEST_CALLBACK_SECRET,
            webhook_headers={"x-callback-token": XENDIT_TEST_CALLBACK_SECRET},
            webhook_payload={
                "id": "evt_1",
                "business_id": XENDIT_TEST_BUSINESS_ID,
                "status": "SUCCEEDED",
                "amount": 249000,
            },
            authoritative_order_id="ORD-OB-1001",
            authoritative_canonical_tenant_id=TENANT_1_UUID,
            authoritative_order_amount=249000,
            authoritative_sku_id="kelas-inkubasi-ctwa-batch-1-scale",
            verified_at_utc="2026-11-05T13:00:00Z",
            rail_type="MANUAL_DIRECT_TENANT",
        )
    assert exc_boundary.value.error_code == "DIRECT_TENANT_RAIL_SIGNING_LOCKED"
    assert exc_boundary.value.http_status == 403

    # Also verify that validate_provenance_17_field_contract rejects MANUAL_DIRECT_TENANT
    cap = _mint_valid_xendit_capability()
    fields = cap.to_unsigned_17_field_dict(prov_key_id=PROV_ACTIVE_KEY_ID)
    fields["rail_type"] = "MANUAL_DIRECT_TENANT"
    with pytest.raises(SettlementProvenanceError) as exc_ver:
        validate_provenance_17_field_contract(fields)
    assert exc_ver.value.error_code == "DIRECT_TENANT_RAIL_LOCKED"


# =============================================================================
# Test Cases 21 - 24: Canonical Request Target, Raw Body Bytes, & Config Contract
# =============================================================================

def test_21_non_canonical_request_path_rejected() -> None:
    r"""Requirement 21: Non-canonical paths (`//`, `/./`, `/../`, trailing `/`,
    percent-encoding `%2F`, backslash `\`, leading/trailing whitespace) are rejected.
    """
    non_canonical_paths = [
        "/api/v1//orders/ORD-OB-1001/approve-and-deliver",
        "/api/v1/./orders/ORD-OB-1001/approve-and-deliver",
        "/api/v1/orders/../orders/ORD-OB-1001/approve-and-deliver",
        "/api/v1/orders/ORD-OB-1001/approve-and-deliver/",
        "/api/v1/orders/ORD-OB-1001/approve%2Dand%2Ddeliver",
        "/api/v1/orders/ORD-OB-1001\\approve-and-deliver",
        " /api/v1/orders/ORD-OB-1001/approve-and-deliver",
        "/api/v1/orders/ORD-OB-1001/approve-and-deliver ",
        "api/v1/orders/ORD-OB-1001/approve-and-deliver",
    ]
    for bad_path in non_canonical_paths:
        with pytest.raises(PaymentAuthorizationError) as exc_path:
            validate_strict_canonical_path(bad_path)
        assert exc_path.value.error_code == "NON_CANONICAL_REQUEST_PATH"
        assert exc_path.value.http_status == 400


def test_22_query_parameters_on_mutation_route_rejected() -> None:
    """Requirement 22: Query parameters on internal payment mutation routes are rejected."""
    verifier, _ = _build_stage1_verifier()
    body = b'{"reason":"verified_delivery"}'
    headers = _build_signed_headers(nonce="nonce_query_022", raw_body=body)

    with pytest.raises(PaymentAuthorizationError) as exc_inline_q:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver?tenant_id=" + TENANT_2_UUID,
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_inline_q.value.error_code == "QUERY_PARAMETERS_FORBIDDEN"

    with pytest.raises(PaymentAuthorizationError) as exc_param_q:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            raw_query_string="debug=1",
            order_id="ORD-OB-1001",
            raw_body=body,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_param_q.value.error_code == "QUERY_PARAMETERS_FORBIDDEN"


def test_23_raw_body_bytes_enforced_and_whitespace_mutation_rejected() -> None:
    """Requirement 23: Passing `str` instead of `bytes` for `raw_body` is rejected with
    `RAW_BODY_BYTES_REQUIRED`, and single-byte whitespace mutation in wire bytes is rejected.
    """
    verifier, _ = _build_stage1_verifier()
    compact_bytes = b'{"reason":"verified_delivery"}'
    spaced_bytes = b'{"reason": "verified_delivery"}'
    headers = _build_signed_headers(nonce="nonce_raw_bytes_023", raw_body=compact_bytes)

    # 1. Passing str instead of bytes -> RAW_BODY_BYTES_REQUIRED
    with pytest.raises(PaymentAuthorizationError) as exc_str:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body='{"reason":"verified_delivery"}',  # type: ignore[arg-type]
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_str.value.error_code == "RAW_BODY_BYTES_REQUIRED"

    # 2. Semantically identical JSON with 1 extra space byte -> INVALID_HMAC_SIGNATURE
    with pytest.raises(PaymentAuthorizationError) as exc_space:
        verifier.verify_mutation_request(
            headers=headers,
            http_method="POST",
            canonical_path="/api/v1/orders/ORD-OB-1001/approve-and-deliver",
            order_id="ORD-OB-1001",
            raw_body=spaced_bytes,
            now_epoch=FIXED_NOW_EPOCH,
        )
    assert exc_space.value.error_code == "INVALID_HMAC_SIGNATURE"


def test_24_environment_variable_contract_rejects_legacy_aliases() -> None:
    """Requirement 24: Verifies that canonical environment variables load cleanly
    and deprecated legacy aliases fail closed with `PaymentConfigurationError`.
    """
    # 1. Legacy internal HMAC alias rejected
    with pytest.raises(PaymentConfigurationError):
        InternalPaymentHMACKeyring.from_env(
            {
                "PAYMENT_INTERNAL_HMAC_KEYS_JSON": json.dumps(
                    {
                        ACTIVE_KEY_ID: {
                            "secret": ACTIVE_KEY_SECRET,
                            "status": "ACTIVE",
                            "bound_principal": ACTIVE_PRINCIPAL,
                        }
                    }
                )
            }
        )

    # 2. Legacy provenance alias rejected
    with pytest.raises(PaymentConfigurationError):
        ProvenanceSigningKeyring.from_env(
            {
                "PAYMENT_PROVENANCE_HMAC_KEYS_JSON": json.dumps(
                    {PROV_ACTIVE_KEY_ID: {"private_key_hex": PROV_ACTIVE_PRIV_HEX, "status": "ACTIVE"}}
                )
            }
        )

    # 3. Canonical environment variable names succeed
    env = {
        ENV_INTERNAL_HMAC_KEYRING: json.dumps(
            {
                ACTIVE_KEY_ID: {
                    "secret": ACTIVE_KEY_SECRET,
                    "status": "ACTIVE",
                    "bound_principal": ACTIVE_PRINCIPAL,
                }
            }
        ),
        ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING: json.dumps(
            {PROV_ACTIVE_KEY_ID: {"private_key_hex": PROV_ACTIVE_PRIV_HEX, "status": "ACTIVE"}}
        ),
        ENV_APP_MASTER_KEY: FAKE_APP_MASTER_KEY,
    }
    internal_kr = InternalPaymentHMACKeyring.from_env(env)
    prov_sign_kr = ProvenanceSigningKeyring.from_env(env)
    pub_rec = prov_sign_kr.get_for_signing(PROV_ACTIVE_KEY_ID)

    env[ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING] = json.dumps(
        {PROV_ACTIVE_KEY_ID: {"public_key_hex": pub_rec.public_key_hex, "status": "ACTIVE"}}
    )
    prov_ver_kr = ProvenanceVerificationKeyring.from_env(env)
    assert internal_kr.get_for_verification(ACTIVE_KEY_ID).bound_principal == ACTIVE_PRINCIPAL
    assert prov_ver_kr.get_for_verification(PROV_ACTIVE_KEY_ID).public_key_hex == pub_rec.public_key_hex
