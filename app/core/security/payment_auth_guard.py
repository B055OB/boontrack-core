r"""Stage 1 Payment Security Foundation:
1. Canonical Tenant Identity Resolver (`CanonicalTenantResolver`)
2. PostgreSQL Authoritative Anti-Replay Store (`PostgresAuthoritativeReplayStore`)
3. Internal Payment Mutation HMAC Verification Foundation (`InternalPaymentHMACVerifier`)
4. Strict Canonical Request Target & Raw Body Bytes Contract (FastAPI & aiohttp parity)

Enforces all Phase 1 Stage 1 technical invariants:
- Authoritative tenant ownership resolved strictly via `INNER JOIN tenants t ON o.tenant_id = t.id::text`.
- Zero `OR o.tenant_slug = t.slug` fallback in authorization paths.
- Single authoritative replay store in PostgreSQL with atomic `UNIQUE (key_id, nonce)`.
- Redis strictly restricted to L1 fast-reject cache; PostgreSQL outage fails closed (`HTTP 503`).
- Full-context HMAC-SHA256 binding `v1|{key_id}|{timestamp}|{nonce}|{http_method}|{canonical_path}|{order_id}|{canonical_tenant_id}|{body_sha256}`.
- Non-canonical request paths (`//`, `/./`, `/../`, trailing `/`, `%` encoding, `\`) and query parameters on mutation routes are strictly rejected.
- `raw_body` must be exact wire `bytes`/`bytearray` (strings or pre-parsed objects rejected).
- Canonical environment variable `PAYMENT_INTERNAL_HMAC_KEYRING_JSON` with zero silent fallback aliases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple
import uuid

from app.services.payment.base import (
    PaymentAuthorizationError,
    PaymentConfigurationError,
    ReplayStoreUnavailableError,
)

logger = logging.getLogger(__name__)

# Canonical Environment Variable Names (Single Source of Truth — No Silent Fallbacks)
ENV_INTERNAL_HMAC_KEYRING: str = "PAYMENT_INTERNAL_HMAC_KEYRING_JSON"
ENV_APP_MASTER_KEY: str = "APP_MASTER_KEY"

FORBIDDEN_LEGACY_INTERNAL_HMAC_ENV_ALIASES: Tuple[str, ...] = (
    "PAYMENT_INTERNAL_HMAC_KEYS_JSON",
    "PAYMENT_INTERNAL_MUTATION_HMAC_SECRET",
)

# Header names for internal payment mutation authentication
HDR_KEY_ID: str = "x-payment-internal-key-id"
HDR_TIMESTAMP: str = "x-payment-internal-timestamp"
HDR_NONCE: str = "x-payment-internal-nonce"
HDR_SIGNATURE: str = "x-payment-internal-signature"
HDR_ACTOR: str = "x-payment-internal-actor"
HDR_TENANT_ID: str = "x-tenant-id"
HDR_AUTHORIZATION: str = "authorization"
HDR_API_KEY: str = "x-api-key"
HDR_MASTER_KEY: str = "x-master-key"

DEFAULT_TIMESTAMP_TOLERANCE_SECONDS: int = 300
DEFAULT_NONCE_TTL_SECONDS: int = 600

ALLOWED_INTERNAL_KEY_STATUSES: FrozenSet[str] = frozenset(
    {"ACTIVE", "PREVIOUS", "VERIFY_ONLY", "REVOKED"}
)


def _normalize_headers(headers: Mapping[str, Any]) -> Dict[str, str]:
    """Normalizes HTTP headers to lowercase keys with stripped string values."""
    normalized: Dict[str, str] = {}
    for k, v in (headers or {}).items():
        if k is not None and v is not None:
            normalized[str(k).strip().lower()] = str(v).strip()
    return normalized


def _validate_uuid_str(value: Any) -> Optional[str]:
    """Returns canonical lowercase UUID string if `value` is a valid UUID, else None."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except Exception:
        return None


# =============================================================================
# 0. Strict Canonical Request Target & Raw Body Bytes Validator
# =============================================================================

def validate_strict_canonical_path(raw_path: Any, *, raw_query_string: Optional[str] = None, allow_query_string: bool = False) -> str:
    """Validates that `raw_path` is already in strict canonical form without performing
    ambiguous normalization. Rejects non-canonical paths and unauthorized query strings.
    """
    if not isinstance(raw_path, str) or not raw_path:
        raise PaymentAuthorizationError(
            "Request path must be a non-empty string.",
            error_code="NON_CANONICAL_REQUEST_PATH",
            http_status=400,
        )

    # Check if raw_path contains a query delimiter directly
    if "?" in raw_path:
        path_part, _, inline_query = raw_path.partition("?")
        if not allow_query_string:
            raise PaymentAuthorizationError(
                "Query parameters are prohibited on internal payment mutation routes.",
                error_code="QUERY_PARAMETERS_FORBIDDEN",
                http_status=400,
            )
        raw_path = path_part
        raw_query_string = inline_query if raw_query_string is None else raw_query_string

    if raw_query_string is not None and raw_query_string != "" and not allow_query_string:
        raise PaymentAuthorizationError(
            f"Query parameters ('{raw_query_string}') are prohibited on internal payment mutation routes.",
            error_code="QUERY_PARAMETERS_FORBIDDEN",
            http_status=400,
        )

    if raw_path != raw_path.strip():
        raise PaymentAuthorizationError(
            "Request path must not contain leading or trailing whitespace.",
            error_code="NON_CANONICAL_REQUEST_PATH",
            http_status=400,
        )

    if not raw_path.startswith("/"):
        raise PaymentAuthorizationError(
            "Request path must start with '/'.",
            error_code="NON_CANONICAL_REQUEST_PATH",
            http_status=400,
        )

    for ch in raw_path:
        code = ord(ch)
        if code <= 0x20 or code >= 0x7F:
            raise PaymentAuthorizationError(
                "Request path contains whitespace, control, or non-ASCII characters.",
                error_code="NON_CANONICAL_REQUEST_PATH",
                http_status=400,
            )

    if "//" in raw_path:
        raise PaymentAuthorizationError(
            f"Non-canonical duplicate slash '//' in request path '{raw_path}'.",
            error_code="NON_CANONICAL_REQUEST_PATH",
            http_status=400,
        )

    if "\\" in raw_path or "%" in raw_path:
        raise PaymentAuthorizationError(
            f"Percent-encoding or backslash is prohibited in canonical mutation path '{raw_path}'.",
            error_code="NON_CANONICAL_REQUEST_PATH",
            http_status=400,
        )

    if "/./" in raw_path or "/../" in raw_path or raw_path.endswith("/.") or raw_path.endswith("/.."):
        raise PaymentAuthorizationError(
            f"Dot-segments are prohibited in canonical mutation path '{raw_path}'.",
            error_code="NON_CANONICAL_REQUEST_PATH",
            http_status=400,
        )

    if len(raw_path) > 1 and raw_path.endswith("/"):
        raise PaymentAuthorizationError(
            f"Trailing slash is prohibited in canonical mutation path '{raw_path}'.",
            error_code="NON_CANONICAL_REQUEST_PATH",
            http_status=400,
        )

    if allow_query_string and raw_query_string:
        for ch in raw_query_string:
            code = ord(ch)
            if code <= 0x20 or code >= 0x7F:
                raise PaymentAuthorizationError(
                    "Query string contains illegal whitespace or control characters.",
                    error_code="NON_CANONICAL_REQUEST_PATH",
                    http_status=400,
                )
        return f"{raw_path}?{raw_query_string}"

    return raw_path


def _require_raw_body_bytes(raw_body: Any) -> bytes:
    """Enforces that `raw_body` is exact wire bytes (`bytes` or `bytearray`), rejecting
    `str` or parsed objects so callers never hash re-serialized JSON models.
    """
    if isinstance(raw_body, bytes):
        return raw_body
    if isinstance(raw_body, bytearray):
        return bytes(raw_body)
    raise PaymentAuthorizationError(
        f"raw_body must be exact wire bytes (bytes or bytearray), got {type(raw_body).__name__}.",
        error_code="RAW_BODY_BYTES_REQUIRED",
        http_status=400,
    )


# =============================================================================
# 1. Canonical Tenant Identity Resolver
# =============================================================================

@dataclass(frozen=True)
class CanonicalOrderTenantContext:
    """Authoritative order-to-tenant relational context loaded from PostgreSQL."""

    order_id: str
    canonical_tenant_id: str
    canonical_tenant_slug: str
    gross_amount: int
    sku_id: str
    order_status: str

    @property
    def tenant_slug(self) -> str:
        return self.canonical_tenant_slug


class CanonicalTenantResolver:
    """Resolves and validates canonical tenant ownership (`tenants.id` UUID) from
    authoritative database relations (`orders` INNER JOIN `tenants`).

    Invariants:
    - Never uses `OR o.tenant_slug = t.slug` in any authorization or mutation path.
    - Rejects any order whose `orders.tenant_id` is null, non-UUID, or does not join
      to an existing `tenants.id` row (`HTTP 422 UNRESOLVED_CANONICAL_TENANT_ID`).
    - Rejects any mismatch between `orders.tenant_slug` (if present on the order row)
      and the joined `tenants.slug` (`HTTP 403 TENANT_IDENTITY_MISMATCH`).
    - Rejects any mismatch between the caller's verified tenant context and the
      order's `canonical_tenant_id` (`HTTP 403 ORDER_TENANT_MISMATCH`).
    """

    AUTHORITATIVE_JOIN_SQL: str = """
        SELECT
            o.id AS order_id,
            o.tenant_id::text AS order_tenant_id,
            o.tenant_slug AS recorded_order_tenant_slug,
            t.id::text AS canonical_tenant_id,
            t.slug AS canonical_tenant_slug,
            COALESCE(o.gross_amount, o.amount, 0) AS gross_amount,
            COALESCE(NULLIF(BTRIM(o.sku_id), ''), NULLIF(BTRIM(o.product_id), ''), '') AS sku_id,
            COALESCE(o.status, '') AS order_status
        FROM orders o
        INNER JOIN tenants t
            ON o.tenant_id::text = t.id::text
        WHERE o.id = %s
        LIMIT 1;
    """

    ORDER_DIAGNOSTIC_SQL: str = """
        SELECT
            o.id AS order_id,
            o.tenant_id::text AS order_tenant_id,
            o.tenant_slug AS recorded_order_tenant_slug
        FROM orders o
        WHERE o.id = %s
        LIMIT 1;
    """

    LEGACY_ISOLATED_LOOKUP_SQL: str = """
        SELECT
            t.id::text AS canonical_tenant_id,
            t.slug AS canonical_tenant_slug
        FROM tenants t
        WHERE t.slug = %s;
    """

    def __init__(self, db_connection_factory: Callable[[], Any]) -> None:
        if not callable(db_connection_factory):
            raise PaymentConfigurationError(
                "CanonicalTenantResolver requires a callable db_connection_factory."
            )
        self._db_conn_factory = db_connection_factory

    def resolve_order_tenant_strict(
        self,
        order_id: str,
        *,
        expected_actor_tenant_id: Optional[str] = None,
        untrusted_body_payload: Optional[Mapping[str, Any]] = None,
        untrusted_header_tenant_id: Optional[str] = None,
    ) -> CanonicalOrderTenantContext:
        """Resolves the authoritative `canonical_tenant_id` for `order_id` via
        `INNER JOIN tenants t ON o.tenant_id = t.id::text`.
        """
        clean_order_id = str(order_id or "").strip()
        if not clean_order_id:
            raise PaymentAuthorizationError(
                "order_id must be a non-empty string.",
                error_code="INVALID_ORDER_ID",
                http_status=400,
            )

        conn = None
        cur = None
        try:
            conn = self._db_conn_factory()
            cur = conn.cursor()
            cur.execute(self.AUTHORITATIVE_JOIN_SQL, (clean_order_id,))
            joined_row = cur.fetchone()

            if joined_row is None:
                cur.execute(self.ORDER_DIAGNOSTIC_SQL, (clean_order_id,))
                diag_row = cur.fetchone()
                if diag_row is None:
                    raise PaymentAuthorizationError(
                        f"Order '{clean_order_id}' does not exist.",
                        error_code="ORDER_NOT_FOUND",
                        http_status=404,
                    )
                raise PaymentAuthorizationError(
                    f"Order '{clean_order_id}' has unresolved or non-canonical tenant_id "
                    f"({diag_row[1]!r}); tenant_slug fallback is prohibited in authorization paths.",
                    error_code="UNRESOLVED_CANONICAL_TENANT_ID",
                    http_status=422,
                )

            (
                db_order_id,
                order_tenant_id,
                recorded_order_slug,
                canonical_tenant_id_raw,
                canonical_tenant_slug,
                gross_amount_raw,
                sku_id_raw,
                order_status_raw,
            ) = joined_row
        except PaymentAuthorizationError:
            raise
        except Exception as exc:
            raise ReplayStoreUnavailableError(
                f"Failed to query authoritative order-tenant relationship: {exc}",
                error_code="AUTHORITATIVE_TENANT_STORE_UNAVAILABLE",
                http_status=503,
            ) from exc
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        canonical_uuid = _validate_uuid_str(canonical_tenant_id_raw)
        order_tenant_uuid = _validate_uuid_str(order_tenant_id)
        if not canonical_uuid or not order_tenant_uuid or canonical_uuid != order_tenant_uuid:
            raise PaymentAuthorizationError(
                f"Order '{clean_order_id}' does not have a valid canonical UUID tenant_id.",
                error_code="UNRESOLVED_CANONICAL_TENANT_ID",
                http_status=422,
            )

        if recorded_order_slug is not None and str(recorded_order_slug).strip():
            rec_slug = str(recorded_order_slug).strip()
            can_slug = str(canonical_tenant_slug or "").strip()
            if rec_slug != can_slug:
                raise PaymentAuthorizationError(
                    f"Order '{clean_order_id}' has conflicting recorded tenant_slug '{rec_slug}' "
                    f"vs canonical tenant slug '{can_slug}'.",
                    error_code="TENANT_IDENTITY_MISMATCH",
                    http_status=403,
                )

        if expected_actor_tenant_id is not None:
            expected_uuid = _validate_uuid_str(expected_actor_tenant_id)
            if not expected_uuid or not hmac.compare_digest(expected_uuid, canonical_uuid):
                raise PaymentAuthorizationError(
                    f"Authenticated caller tenant '{expected_actor_tenant_id}' is not authorized "
                    f"for order '{clean_order_id}' (owned by '{canonical_uuid}').",
                    error_code="ORDER_TENANT_MISMATCH",
                    http_status=403,
                )

        if untrusted_header_tenant_id is not None and str(untrusted_header_tenant_id).strip():
            hdr_uuid = _validate_uuid_str(untrusted_header_tenant_id)
            if not hdr_uuid or not hmac.compare_digest(hdr_uuid, canonical_uuid):
                raise PaymentAuthorizationError(
                    f"Header X-Tenant-Id '{untrusted_header_tenant_id}' mismatches authoritative "
                    f"order canonical_tenant_id '{canonical_uuid}'.",
                    error_code="TENANT_SPOOFING_DETECTED",
                    http_status=403,
                )

        if isinstance(untrusted_body_payload, Mapping):
            for body_key in ("tenant_id", "canonical_tenant_id"):
                if body_key in untrusted_body_payload and untrusted_body_payload[body_key] is not None:
                    claimed_val = str(untrusted_body_payload[body_key]).strip()
                    claimed_uuid = _validate_uuid_str(claimed_val)
                    if not claimed_uuid or not hmac.compare_digest(claimed_uuid, canonical_uuid):
                        raise PaymentAuthorizationError(
                            f"Request body field '{body_key}' ('{claimed_val}') attempts to spoof "
                            f"or override authoritative order tenant '{canonical_uuid}'.",
                            error_code="TENANT_SPOOFING_DETECTED",
                            http_status=403,
                        )
            if "tenant_slug" in untrusted_body_payload and untrusted_body_payload["tenant_slug"] is not None:
                claimed_slug = str(untrusted_body_payload["tenant_slug"]).strip()
                if claimed_slug != str(canonical_tenant_slug or "").strip():
                    raise PaymentAuthorizationError(
                        f"Request body tenant_slug '{claimed_slug}' mismatches authoritative "
                        f"canonical tenant slug '{canonical_tenant_slug}'.",
                        error_code="TENANT_SPOOFING_DETECTED",
                        http_status=403,
                    )

        return CanonicalOrderTenantContext(
            order_id=str(db_order_id),
            canonical_tenant_id=canonical_uuid,
            canonical_tenant_slug=str(canonical_tenant_slug or "").strip(),
            gross_amount=int(gross_amount_raw or 0),
            sku_id=str(sku_id_raw or "").strip(),
            order_status=str(order_status_raw or "").strip(),
        )

    def resolve_legacy_slug_for_migration_only(
        self,
        legacy_tenant_slug: str,
        *,
        allow_migration_inspection: bool = False,
    ) -> str:
        """Isolated helper ONLY for offline migration/admin inspection."""
        if not allow_migration_inspection:
            raise PaymentAuthorizationError(
                "Legacy tenant_slug resolution is strictly forbidden in payment authorization paths.",
                error_code="LEGACY_SLUG_FALLBACK_FORBIDDEN",
                http_status=403,
            )

        slug = str(legacy_tenant_slug or "").strip()
        if not slug:
            raise PaymentAuthorizationError(
                "legacy_tenant_slug must be non-empty.",
                error_code="UNRESOLVED_CANONICAL_TENANT_ID",
                http_status=422,
            )

        conn = self._db_conn_factory()
        cur = conn.cursor()
        try:
            cur.execute(self.LEGACY_ISOLATED_LOOKUP_SQL, (slug,))
            rows = cur.fetchall()
        finally:
            cur.close()
            conn.close()

        if not rows or len(rows) != 1:
            raise PaymentAuthorizationError(
                f"Legacy tenant_slug '{slug}' does not map uniquely to a single canonical tenant UUID.",
                error_code="UNRESOLVED_CANONICAL_TENANT_ID",
                http_status=422,
            )

        canonical_uuid = _validate_uuid_str(rows[0][0])
        if not canonical_uuid:
            raise PaymentAuthorizationError(
                f"Resolved tenant id for slug '{slug}' is not a valid UUID.",
                error_code="UNRESOLVED_CANONICAL_TENANT_ID",
                http_status=422,
            )
        return canonical_uuid


# =============================================================================
# 2. PostgreSQL Authoritative Anti-Replay Store
# =============================================================================

class PostgresAuthoritativeReplayStore:
    """Single authoritative cross-worker anti-replay store backed by PostgreSQL.

    Invariants:
    - Executes atomic `INSERT INTO public.payment_hmac_replay_nonces ... ON CONFLICT (key_id, nonce) DO NOTHING RETURNING key_id, nonce`.
    - Redis is used strictly as an optional L1 fast-reject cache before hitting PostgreSQL
      and populated after PostgreSQL commit.
    - Redis is NEVER used as an authoritative fallback if PostgreSQL is down or unreachable.
    - Any PostgreSQL connection, query, or commit failure immediately raises
      `ReplayStoreUnavailableError` (`HTTP 503` fail-closed).
    """

    ATOMIC_CLAIM_SQL: str = """
        INSERT INTO public.payment_hmac_replay_nonces (
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
            expires_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (key_id, nonce) DO NOTHING
        RETURNING key_id, nonce;
    """

    def __init__(
        self,
        db_connection_factory: Optional[Callable[[], Any]],
        *,
        redis_client: Optional[Any] = None,
        ttl_seconds: int = DEFAULT_NONCE_TTL_SECONDS,
    ) -> None:
        self._db_conn_factory = db_connection_factory
        self._redis = redis_client
        self._ttl_seconds = max(int(ttl_seconds), 600)

    def claim_nonce_or_fail_closed(
        self,
        *,
        key_id: str,
        nonce: str,
        actor_principal: str,
        canonical_tenant_id: str,
        order_id: str,
        http_method: str,
        canonical_path: str,
        request_timestamp: int,
        body_sha256: str,
    ) -> None:
        """Atomically claims `(key_id, nonce)` in PostgreSQL."""
        clean_key_id = str(key_id or "").strip()
        clean_nonce = str(nonce or "").strip()
        if not clean_key_id or not clean_nonce:
            raise PaymentAuthorizationError(
                "Both key_id and nonce must be non-empty.",
                error_code="INVALID_NONCE_OR_KEY_ID",
                http_status=400,
            )

        redis_key = f"payment:hmac:replay_l1:{clean_key_id}:{clean_nonce}"

        # 1. Optional L1 Fast-Reject Check in Redis (Optimization ONLY)
        if self._redis is not None:
            try:
                if self._redis.get(redis_key):
                    raise PaymentAuthorizationError(
                        f"Replay detected via L1 cache for key_id='{clean_key_id}', nonce='{clean_nonce}'.",
                        error_code="DUPLICATE_NONCE_REPLAY",
                        http_status=403,
                    )
            except PaymentAuthorizationError:
                raise
            except Exception as redis_exc:
                logger.debug("Redis L1 replay cache read skipped (non-authoritative): %s", redis_exc)

        # 2. Authoritative Atomic Claim in PostgreSQL (Mandatory — Fail-Closed on Error)
        if self._db_conn_factory is None:
            raise ReplayStoreUnavailableError(
                "PostgreSQL authoritative replay store connection factory is not configured.",
                error_code="REPLAY_STORE_UNAVAILABLE",
                http_status=503,
            )

        now_utc = datetime.now(timezone.utc)
        expires_utc = now_utc + timedelta(seconds=self._ttl_seconds)

        conn = None
        cur = None
        try:
            conn = self._db_conn_factory()
            cur = conn.cursor()
            cur.execute(
                self.ATOMIC_CLAIM_SQL,
                (
                    clean_key_id,
                    clean_nonce,
                    str(actor_principal).strip(),
                    str(canonical_tenant_id).strip(),
                    str(order_id).strip(),
                    str(http_method).strip().upper(),
                    str(canonical_path).strip(),
                    int(request_timestamp),
                    str(body_sha256).strip().lower(),
                    now_utc,
                    expires_utc,
                ),
            )
            inserted_row = cur.fetchone()
            conn.commit()
        except Exception as db_exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise ReplayStoreUnavailableError(
                f"PostgreSQL authoritative replay store is unavailable or failed to commit nonce claim: {db_exc}",
                error_code="REPLAY_STORE_UNAVAILABLE",
                http_status=503,
            ) from db_exc
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        if inserted_row is None:
            raise PaymentAuthorizationError(
                f"Duplicate replay nonce rejected by PostgreSQL authoritative store: "
                f"key_id='{clean_key_id}', nonce='{clean_nonce}'.",
                error_code="DUPLICATE_NONCE_REPLAY",
                http_status=403,
            )

        # 3. Best-Effort Populate L1 Cache in Redis After Authoritative Commit
        if self._redis is not None:
            try:
                self._redis.set(redis_key, "1", ex=self._ttl_seconds)
            except Exception as redis_exc:
                logger.debug("Redis L1 replay cache write skipped: %s", redis_exc)


# =============================================================================
# 3. Internal Payment Mutation HMAC Verification Foundation
# =============================================================================

@dataclass(frozen=True)
class InternalHMACKeyEntry:
    """Represents a dedicated internal payment mutation HMAC key record."""

    key_id: str
    secret: str
    status: str  # "ACTIVE", "PREVIOUS", "VERIFY_ONLY", "REVOKED"
    bound_principal: str
    bound_tenant_id: Optional[str] = None
    not_after_epoch: Optional[int] = None


class InternalPaymentHMACKeyring:
    """Manages dedicated internal payment mutation HMAC keys (`PAYMENT_INTERNAL_HMAC_KEYRING_JSON`).

    Enforces:
    - Key separation from `APP_MASTER_KEY` (fails closed if any key reuses `APP_MASTER_KEY`).
    - Zero silent fallback to deprecated env var names (`PAYMENT_INTERNAL_HMAC_KEYS_JSON`, etc.).
    - Server-side binding between `key_id` and `bound_principal` (and optional `bound_tenant_id`).
    """

    def __init__(
        self,
        keys: Mapping[str, Mapping[str, Any]],
        *,
        app_master_key: Optional[str] = None,
    ) -> None:
        if not keys:
            raise PaymentConfigurationError(
                "InternalPaymentHMACKeyring requires at least one configured key."
            )

        master_secret = (app_master_key if app_master_key is not None else os.environ.get(ENV_APP_MASTER_KEY, "")).strip()
        self._keys: Dict[str, InternalHMACKeyEntry] = {}

        for key_id, meta in keys.items():
            kid = str(key_id).strip()
            if not kid:
                raise PaymentConfigurationError("Internal HMAC key_id must be non-empty.")
            secret = str(meta.get("secret") or "").strip()
            status = str(meta.get("status") or "").strip().upper()
            bound_principal = str(meta.get("bound_principal") or "").strip()
            bound_tenant_raw = meta.get("bound_tenant_id")
            not_after_raw = meta.get("not_after_epoch")

            if len(secret) < 32:
                raise PaymentConfigurationError(
                    f"Internal HMAC key '{kid}' secret must be at least 32 characters."
                )
            if master_secret and hmac.compare_digest(secret, master_secret):
                raise PaymentConfigurationError(
                    f"Internal HMAC key '{kid}' is forbidden from reusing APP_MASTER_KEY.",
                )
            if status not in ALLOWED_INTERNAL_KEY_STATUSES:
                raise PaymentConfigurationError(
                    f"Internal HMAC key '{kid}' has invalid status '{status}'."
                )
            if not bound_principal:
                raise PaymentConfigurationError(
                    f"Internal HMAC key '{kid}' must define a non-empty bound_principal."
                )

            bound_tenant_uuid: Optional[str] = None
            if bound_tenant_raw is not None and str(bound_tenant_raw).strip():
                bound_tenant_uuid = _validate_uuid_str(bound_tenant_raw)
                if not bound_tenant_uuid:
                    raise PaymentConfigurationError(
                        f"Internal HMAC key '{kid}' has non-UUID bound_tenant_id '{bound_tenant_raw}'."
                    )

            not_after_epoch = int(not_after_raw) if not_after_raw is not None else None
            self._keys[kid] = InternalHMACKeyEntry(
                key_id=kid,
                secret=secret,
                status=status,
                bound_principal=bound_principal,
                bound_tenant_id=bound_tenant_uuid,
                not_after_epoch=not_after_epoch,
            )

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "InternalPaymentHMACKeyring":
        env = environ if environ is not None else os.environ
        for legacy_var in FORBIDDEN_LEGACY_INTERNAL_HMAC_ENV_ALIASES:
            if env.get(legacy_var):
                raise PaymentConfigurationError(
                    f"Deprecated environment variable '{legacy_var}' detected. "
                    f"Use canonical '{ENV_INTERNAL_HMAC_KEYRING}' with no fallback aliases."
                )

        raw = env.get(ENV_INTERNAL_HMAC_KEYRING, "").strip()
        if not raw:
            raise PaymentConfigurationError(
                f"{ENV_INTERNAL_HMAC_KEYRING} is not configured."
            )
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            raise PaymentConfigurationError(
                f"Invalid JSON in {ENV_INTERNAL_HMAC_KEYRING}."
            ) from exc
        return cls(parsed, app_master_key=env.get(ENV_APP_MASTER_KEY, ""))

    def get_for_verification(
        self,
        key_id: str,
        *,
        now_epoch: Optional[int] = None,
    ) -> InternalHMACKeyEntry:
        kid = str(key_id or "").strip()
        if not kid or kid not in self._keys:
            raise PaymentAuthorizationError(
                f"Unknown internal payment HMAC key ID '{kid}'.",
                error_code="UNKNOWN_HMAC_KEY_ID",
                http_status=403,
            )
        entry = self._keys[kid]
        if entry.status == "REVOKED":
            raise PaymentAuthorizationError(
                f"Internal payment HMAC key '{kid}' has been REVOKED.",
                error_code="REVOKED_HMAC_KEY_ID",
                http_status=403,
            )
        if entry.status in ("PREVIOUS", "VERIFY_ONLY") and entry.not_after_epoch is not None:
            current_ts = int(now_epoch if now_epoch is not None else time.time())
            if current_ts > entry.not_after_epoch:
                raise PaymentAuthorizationError(
                    f"Rotated internal payment HMAC key '{kid}' grace window expired at {entry.not_after_epoch}.",
                    error_code="EXPIRED_ROTATED_HMAC_KEY",
                    http_status=403,
                )
        return entry


def build_internal_hmac_signing_string(
    *,
    key_id: str,
    timestamp: int,
    nonce: str,
    http_method: str,
    canonical_path: str,
    order_id: str,
    canonical_tenant_id: str,
    body_sha256: str,
    raw_query_string: Optional[str] = None,
    allow_query_string: bool = False,
) -> str:
    """Constructs the canonical internal payment mutation signing string:
    `v1|{key_id}|{timestamp}|{nonce}|{http_method_upper}|{canonical_path}|{order_id}|{canonical_tenant_id}|{body_sha256}`
    """
    validated_target = validate_strict_canonical_path(
        canonical_path,
        raw_query_string=raw_query_string,
        allow_query_string=allow_query_string,
    )
    return (
        f"v1|{key_id.strip()}|{int(timestamp)}|{nonce.strip()}|"
        f"{http_method.strip().upper()}|{validated_target}|"
        f"{order_id.strip()}|{canonical_tenant_id.strip()}|{body_sha256.strip().lower()}"
    )


def compute_internal_payment_hmac_signature(
    *,
    secret: str,
    key_id: str,
    timestamp: int,
    nonce: str,
    http_method: str,
    canonical_path: str,
    order_id: str,
    canonical_tenant_id: str,
    raw_body: bytes,
    raw_query_string: Optional[str] = None,
    allow_query_string: bool = False,
) -> str:
    """Computes the lowercase hex HMAC-SHA256 signature for an internal payment mutation request."""
    body_bytes = _require_raw_body_bytes(raw_body)
    body_sha256 = hashlib.sha256(body_bytes).hexdigest()
    signing_str = build_internal_hmac_signing_string(
        key_id=key_id,
        timestamp=timestamp,
        nonce=nonce,
        http_method=http_method,
        canonical_path=canonical_path,
        order_id=order_id,
        canonical_tenant_id=canonical_tenant_id,
        body_sha256=body_sha256,
        raw_query_string=raw_query_string,
        allow_query_string=allow_query_string,
    )
    return hmac.new(
        secret.encode("utf-8"),
        signing_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True)
class VerifiedPaymentMutationAuthContext:
    """Verified authentication, authorization, and tenant context returned on success."""

    key_id: str
    verified_actor_principal: str
    canonical_tenant_id: str
    canonical_tenant_slug: str
    order_id: str
    nonce: str
    timestamp: int
    body_sha256: str
    order_context: CanonicalOrderTenantContext

    @property
    def actor_id(self) -> str:
        return self.verified_actor_principal


PaymentAuthError = PaymentAuthorizationError


class InternalPaymentHMACVerifier:
    """Verifies internal payment mutation requests with full-context HMAC binding,
    strict canonical request target validation, verified actor identity binding,
    authoritative DB tenant resolution, and PostgreSQL atomic anti-replay enforcement.
    """

    def __init__(
        self,
        *,
        keyring: InternalPaymentHMACKeyring,
        tenant_resolver: CanonicalTenantResolver,
        replay_store: PostgresAuthoritativeReplayStore,
        app_master_key: Optional[str] = None,
        timestamp_tolerance_seconds: int = DEFAULT_TIMESTAMP_TOLERANCE_SECONDS,
    ) -> None:
        self._keyring = keyring
        self._tenant_resolver = tenant_resolver
        self._replay_store = replay_store
        self._app_master_key = (
            app_master_key if app_master_key is not None else os.environ.get(ENV_APP_MASTER_KEY, "")
        ).strip()
        self._timestamp_tolerance = int(timestamp_tolerance_seconds)

    def verify_mutation_request(
        self,
        *,
        headers: Mapping[str, Any],
        http_method: str,
        canonical_path: str,
        order_id: str,
        raw_body: bytes,
        raw_query_string: Optional[str] = None,
        allow_query_string: bool = False,
        parsed_body: Optional[Mapping[str, Any]] = None,
        actor_tenant_id_from_auth_context: Optional[str] = None,
        now_epoch: Optional[int] = None,
    ) -> VerifiedPaymentMutationAuthContext:
        """Executes end-to-end Stage 1 verification for a payment mutation request."""
        norm_headers = _normalize_headers(headers)

        # 0. Validate Strict Canonical Request Target & Raw Wire Bytes Upfront
        validated_target = validate_strict_canonical_path(
            canonical_path,
            raw_query_string=raw_query_string,
            allow_query_string=allow_query_string,
        )
        body_bytes = _require_raw_body_bytes(raw_body)
        body_sha256 = hashlib.sha256(body_bytes).hexdigest()

        # 1. Explicit Prohibition of APP_MASTER_KEY on Payment Mutation Endpoints
        for candidate_hdr in (HDR_AUTHORIZATION, HDR_API_KEY, HDR_MASTER_KEY, HDR_SIGNATURE):
            hdr_val = norm_headers.get(candidate_hdr, "")
            if not hdr_val:
                continue
            token_candidate = hdr_val
            if token_candidate.lower().startswith("bearer "):
                token_candidate = token_candidate[7:].strip()
            if self._app_master_key and hmac.compare_digest(token_candidate, self._app_master_key):
                raise PaymentAuthorizationError(
                    "APP_MASTER_KEY is strictly prohibited as a payment mutation credential.",
                    error_code="APP_MASTER_KEY_FORBIDDEN",
                    http_status=403,
                )

        if HDR_MASTER_KEY in norm_headers:
            raise PaymentAuthorizationError(
                "X-Master-Key header is strictly prohibited on payment mutation endpoints.",
                error_code="APP_MASTER_KEY_FORBIDDEN",
                http_status=403,
            )

        key_id = norm_headers.get(HDR_KEY_ID, "")
        ts_raw = norm_headers.get(HDR_TIMESTAMP, "")
        nonce = norm_headers.get(HDR_NONCE, "")
        signature = norm_headers.get(HDR_SIGNATURE, "")
        header_actor = norm_headers.get(HDR_ACTOR, "")
        header_tenant_id = norm_headers.get(HDR_TENANT_ID)

        if not key_id or not ts_raw or not nonce or not signature:
            raise PaymentAuthorizationError(
                "Missing required internal payment HMAC authentication headers.",
                error_code="MISSING_HMAC_HEADERS",
                http_status=401,
            )

        # 2. Validate Timestamp Format & Skew Window
        try:
            req_ts = int(ts_raw)
        except Exception as exc:
            raise PaymentAuthorizationError(
                f"Invalid X-Payment-Internal-Timestamp '{ts_raw}'.",
                error_code="INVALID_HMAC_TIMESTAMP",
                http_status=400,
            ) from exc

        current_ts = int(now_epoch if now_epoch is not None else time.time())
        if abs(current_ts - req_ts) > self._timestamp_tolerance:
            raise PaymentAuthorizationError(
                f"HMAC timestamp {req_ts} is outside the +/-{self._timestamp_tolerance}s window (now={current_ts}).",
                error_code="TIMESTAMP_OUT_OF_WINDOW",
                http_status=403,
            )

        # 3. Resolve Key Entry & Verified Actor Principal
        key_entry = self._keyring.get_for_verification(key_id, now_epoch=current_ts)
        verified_principal = key_entry.bound_principal

        if header_actor and not hmac.compare_digest(header_actor, verified_principal):
            raise PaymentAuthorizationError(
                f"Header X-Payment-Internal-Actor '{header_actor}' does not match bound principal '{verified_principal}'.",
                error_code="ACTOR_IDENTITY_SPOOFING_DETECTED",
                http_status=403,
            )

        body_map: Optional[Mapping[str, Any]] = parsed_body
        if body_map is None and body_bytes:
            try:
                decoded = json.loads(body_bytes.decode("utf-8"))
                if isinstance(decoded, Mapping):
                    body_map = decoded
            except Exception:
                body_map = None

        # Reject any body attempt to spoof actor identity
        if isinstance(body_map, Mapping):
            for actor_key in ("actor_id", "actor_principal", "agent_id", "verified_by"):
                if actor_key in body_map and body_map[actor_key] is not None:
                    claimed_actor = str(body_map[actor_key]).strip()
                    if claimed_actor and not hmac.compare_digest(claimed_actor, verified_principal):
                        raise PaymentAuthorizationError(
                            f"Request body field '{actor_key}' ('{claimed_actor}') attempts to spoof "
                            f"verified authentication context principal '{verified_principal}'.",
                            error_code="ACTOR_IDENTITY_SPOOFING_DETECTED",
                            http_status=403,
                        )

        # 4. Resolve Authoritative Order Canonical Tenant ID from PostgreSQL
        effective_expected_tenant = actor_tenant_id_from_auth_context or key_entry.bound_tenant_id
        order_ctx = self._tenant_resolver.resolve_order_tenant_strict(
            order_id=order_id,
            expected_actor_tenant_id=effective_expected_tenant,
            untrusted_body_payload=body_map,
            untrusted_header_tenant_id=header_tenant_id,
        )

        # 5. Compute and Verify Full-Context HMAC-SHA256 Signature
        expected_sig = compute_internal_payment_hmac_signature(
            secret=key_entry.secret,
            key_id=key_entry.key_id,
            timestamp=req_ts,
            nonce=nonce,
            http_method=http_method,
            canonical_path=validated_target,
            order_id=order_ctx.order_id,
            canonical_tenant_id=order_ctx.canonical_tenant_id,
            raw_body=body_bytes,
            allow_query_string=allow_query_string,
        )

        if not hmac.compare_digest(expected_sig, signature.strip().lower()):
            raise PaymentAuthorizationError(
                "Invalid internal payment mutation HMAC signature.",
                error_code="INVALID_HMAC_SIGNATURE",
                http_status=403,
            )

        # 6. Claim `(key_id, nonce)` in PostgreSQL Authoritative Anti-Replay Store (Fail-Closed)
        self._replay_store.claim_nonce_or_fail_closed(
            key_id=key_entry.key_id,
            nonce=nonce,
            actor_principal=verified_principal,
            canonical_tenant_id=order_ctx.canonical_tenant_id,
            order_id=order_ctx.order_id,
            http_method=http_method,
            canonical_path=validated_target,
            request_timestamp=req_ts,
            body_sha256=body_sha256,
        )

        return VerifiedPaymentMutationAuthContext(
            key_id=key_entry.key_id,
            verified_actor_principal=verified_principal,
            canonical_tenant_id=order_ctx.canonical_tenant_id,
            canonical_tenant_slug=order_ctx.canonical_tenant_slug,
            order_id=order_ctx.order_id,
            nonce=nonce,
            timestamp=req_ts,
            body_sha256=body_sha256,
            order_context=order_ctx,
        )


# =============================================================================
# 4. Stage 2 Unified Route Mutation Verification Helper & Environment Guard
# =============================================================================

FORBIDDEN_SETTLEMENT_STATUS_VALUES: FrozenSet[str] = frozenset(
    {"PAID", "LUNAS", "SETTLED", "SUCCESS", "SUCCEEDED", "COMPLETED", "APPROVED", "VERIFIED"}
)

TERMINAL_ORDER_STATUSES: FrozenSet[str] = frozenset(
    {"CANCELLED", "EXPIRED", "FAILED"}
)

ALLOWED_NON_SETTLEMENT_ADMIN_STATUSES: FrozenSet[str] = frozenset(
    {"PENDING", "WAITING_PAYMENT", "CANCELLED", "EXPIRED", "FAILED", "HOLD"}
)

VALID_ORDER_STATUS_TRANSITIONS: Mapping[str, FrozenSet[str]] = {
    "PENDING": frozenset({"WAITING_PAYMENT", "HOLD", "CANCELLED", "EXPIRED", "FAILED"}),
    "WAITING_PAYMENT": frozenset({"PENDING", "HOLD", "CANCELLED", "EXPIRED", "FAILED"}),
    "HOLD": frozenset({"PENDING", "WAITING_PAYMENT", "CANCELLED", "EXPIRED", "FAILED"}),
    "CANCELLED": frozenset(),
    "EXPIRED": frozenset(),
    "FAILED": frozenset(),
}


def validate_order_status_transition(
    *,
    current_status: Optional[str],
    target_status: str,
    order_id: str = "",
) -> str:
    """Validates an order status transition against the authoritative transition matrix (P0-C).

    Rules:
    1. Target status in FORBIDDEN_SETTLEMENT_STATUS_VALUES -> HTTP 403 SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN.
    2. Target status not in ALLOWED_NON_SETTLEMENT_ADMIN_STATUSES -> HTTP 422 INVALID_NON_SETTLEMENT_STATUS.
    3. Current status in FORBIDDEN_SETTLEMENT_STATUS_VALUES -> HTTP 409 INVALID_STATUS_TRANSITION.
    4. Current status in TERMINAL_ORDER_STATUSES:
       - If target_status == current_status: return normalized status (idempotent no-op).
       - If target_status != current_status: HTTP 409 INVALID_STATUS_TRANSITION.
    5. Active statuses (PENDING, WAITING_PAYMENT, HOLD):
       - If target_status == current_status: return normalized status (idempotent no-op).
       - If target_status in VALID_ORDER_STATUS_TRANSITIONS.get(current_status, ()): return normalized status.
       - Otherwise: HTTP 409 INVALID_STATUS_TRANSITION.
    """
    clean_target = str(target_status or "").strip().upper()
    clean_current = str(current_status or "").strip().upper() if current_status else ""

    # Rule 1: Settlement Target Forbidden via PATCH /status
    if clean_target in FORBIDDEN_SETTLEMENT_STATUS_VALUES:
        raise PaymentAuthorizationError(
            f"SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN: Transitioning order status to '{clean_target}' "
            "via PATCH /status is strictly prohibited. Orders may only settle via verified payment gateway webhooks.",
            error_code="SETTLEMENT_VIA_STATUS_PATCH_FORBIDDEN",
            http_status=403,
        )

    # Rule 2: Target must be in allowed non-settlement admin statuses
    if clean_target not in ALLOWED_NON_SETTLEMENT_ADMIN_STATUSES:
        raise PaymentAuthorizationError(
            f"INVALID_NON_SETTLEMENT_STATUS: Unsupported non-settlement status '{clean_target}'.",
            error_code="INVALID_NON_SETTLEMENT_STATUS",
            http_status=422,
        )

    # Rule 3: Settled Order is Immutable via status PATCH
    if clean_current in FORBIDDEN_SETTLEMENT_STATUS_VALUES:
        raise PaymentAuthorizationError(
            f"INVALID_STATUS_TRANSITION: Order '{order_id}' has already been settled ('{clean_current}') "
            "and cannot be mutated via administrative status PATCH.",
            error_code="INVALID_STATUS_TRANSITION",
            http_status=409,
        )

    # Idempotent no-op
    if clean_current and clean_target == clean_current:
        return clean_target

    # Rule 4: Terminal Status Cannot be Reactivated or Mutated
    if clean_current in TERMINAL_ORDER_STATUSES:
        raise PaymentAuthorizationError(
            f"INVALID_STATUS_TRANSITION: Terminal status '{clean_current}' cannot be transitioned to '{clean_target}'. "
            "Reopening or mutating terminal orders via status PATCH is strictly prohibited.",
            error_code="INVALID_STATUS_TRANSITION",
            http_status=409,
        )

    # Rule 5: Active Non-Settlement Status Transition Matrix
    allowed_targets = VALID_ORDER_STATUS_TRANSITIONS.get(clean_current)
    if allowed_targets is not None and clean_target not in allowed_targets:
        raise PaymentAuthorizationError(
            f"INVALID_STATUS_TRANSITION: Transition from '{clean_current}' to '{clean_target}' is not permitted.",
            error_code="INVALID_STATUS_TRANSITION",
            http_status=409,
        )

    return clean_target


def is_production_environment(environ: Optional[Mapping[str, str]] = None) -> bool:
    """Returns True if the runtime environment is configured as production."""
    env = environ if environ is not None else os.environ
    for key in ("APP_ENV", "ENVIRONMENT", "RAILWAY_ENVIRONMENT", "NODE_ENV"):
        val = str(env.get(key, "")).strip().lower()
        if val in ("production", "prod", "live"):
            return True
    return False


def verify_stage2_internal_mutation_request(
    *,
    headers: Mapping[str, Any],
    http_method: str,
    canonical_path: Optional[str] = None,
    raw_path: Optional[str] = None,
    order_id: str,
    raw_body: Optional[bytes] = None,
    raw_body_bytes: Optional[bytes] = None,
    raw_query_string: Optional[str] = None,
    allow_query_string: bool = False,
    parsed_body: Optional[Mapping[str, Any]] = None,
    db_connection_factory: Optional[Callable[[], Any]] = None,
    db_conn_factory: Optional[Callable[[], Any]] = None,
    redis_client: Optional[Any] = None,
    environ: Optional[Mapping[str, str]] = None,
    now_epoch: Optional[int] = None,
) -> VerifiedPaymentMutationAuthContext:
    """End-to-end Stage 2 route guard for administrative / internal mutation endpoints.

    Enforces:
    1. Strict canonical path & query string prohibition (`HTTP 400`).
    2. Raw request body `bytes` requirement (`HTTP 400`).
    3. `APP_MASTER_KEY` prohibition (`HTTP 403 APP_MASTER_KEY_FORBIDDEN`).
    4. Presence of required HMAC headers (`HTTP 401 MISSING_HMAC_HEADERS`).
    5. Keyring resolution from `PAYMENT_INTERNAL_HMAC_KEYRING_JSON`.
    6. Canonical tenant ownership resolution (`CanonicalTenantResolver`) + full-context HMAC
       verification + atomic PostgreSQL anti-replay (`HTTP 503` fail-closed on DB failure).
    """
    env = environ if environ is not None else os.environ
    norm_headers = _normalize_headers(headers)
    effective_path = canonical_path if canonical_path is not None else raw_path
    effective_body = raw_body if raw_body is not None else raw_body_bytes
    effective_db_factory = db_connection_factory if db_connection_factory is not None else db_conn_factory

    # 1. Validate canonical path and raw body bytes upfront
    validate_strict_canonical_path(
        effective_path,
        raw_query_string=raw_query_string,
        allow_query_string=allow_query_string,
    )
    _require_raw_body_bytes(effective_body)

    # 2. Enforce APP_MASTER_KEY prohibition before keyring load
    app_master_key = str(env.get(ENV_APP_MASTER_KEY, "")).strip()
    for candidate_hdr in (HDR_AUTHORIZATION, HDR_API_KEY, HDR_MASTER_KEY, HDR_SIGNATURE):
        hdr_val = norm_headers.get(candidate_hdr, "")
        if not hdr_val:
            continue
        token_candidate = hdr_val
        if token_candidate.lower().startswith("bearer "):
            token_candidate = token_candidate[7:].strip()
        if app_master_key and hmac.compare_digest(token_candidate, app_master_key):
            raise PaymentAuthorizationError(
                "APP_MASTER_KEY is strictly prohibited as a payment mutation credential.",
                error_code="APP_MASTER_KEY_FORBIDDEN",
                http_status=403,
            )

    if HDR_MASTER_KEY in norm_headers:
        raise PaymentAuthorizationError(
            "X-Master-Key header is strictly prohibited on payment mutation endpoints.",
            error_code="APP_MASTER_KEY_FORBIDDEN",
            http_status=403,
        )

    # 3. Check required HMAC headers before loading keyring
    key_id = norm_headers.get(HDR_KEY_ID, "")
    ts_raw = norm_headers.get(HDR_TIMESTAMP, "")
    nonce = norm_headers.get(HDR_NONCE, "")
    signature = norm_headers.get(HDR_SIGNATURE, "")
    if not key_id or not ts_raw or not nonce or not signature:
        raise PaymentAuthorizationError(
            "Missing required internal payment HMAC authentication headers.",
            error_code="MISSING_HMAC_HEADERS",
            http_status=401,
        )

    try:
        keyring = InternalPaymentHMACKeyring.from_env(env)
    except PaymentConfigurationError as cfg_err:
        raise PaymentAuthorizationError(
            f"Internal payment mutation HMAC keyring is not configured or invalid: {cfg_err}",
            error_code="INTERNAL_HMAC_NOT_CONFIGURED",
            http_status=403,
        ) from cfg_err

    if effective_db_factory is None:
        from app.core.database import get_db_connection
        effective_db_factory = get_db_connection

    tenant_resolver = CanonicalTenantResolver(effective_db_factory)
    replay_store = PostgresAuthoritativeReplayStore(
        effective_db_factory,
        redis_client=redis_client,
        ttl_seconds=DEFAULT_NONCE_TTL_SECONDS,
    )
    verifier = InternalPaymentHMACVerifier(
        keyring=keyring,
        tenant_resolver=tenant_resolver,
        replay_store=replay_store,
        app_master_key=app_master_key,
    )
    return verifier.verify_mutation_request(
        headers=norm_headers,
        http_method=http_method,
        canonical_path=effective_path,
        order_id=order_id,
        raw_body=effective_body,
        raw_query_string=raw_query_string,
        allow_query_string=allow_query_string,
        parsed_body=parsed_body,
        now_epoch=now_epoch,
    )


# =============================================================================
# 5. Stage 2 P0-D: Checkout Session Security, Anti-Enumeration & PII Masking
# =============================================================================

import secrets

ENV_CHECKOUT_SESSION_KEYRING: str = "CHECKOUT_SESSION_HMAC_KEYRING_JSON"
HDR_CHECKOUT_SESSION_TOKEN: str = "x-checkout-session-token"
COOKIE_CHECKOUT_SESSION_HOST: str = "__Host-bt_checkout_st"
COOKIE_CHECKOUT_SESSION_FALLBACK: str = "bt_checkout_st"

CHECKOUT_SECURITY_HEADERS: Dict[str, str] = {
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}

# Process-local ephemeral key used ONLY in non-production when CHECKOUT_SESSION_HMAC_KEYRING_JSON is unset
_EPHEMERAL_DEV_CS_KEY_ID: str = "cs_ephemeral_dev_k1"
_EPHEMERAL_DEV_CS_SECRET: str = secrets.token_hex(32)


def mask_pii_name(name: Optional[str]) -> str:
    """Masks customer name for public checkout status polling (e.g., 'Budi Santoso' -> 'B*** S***')."""
    raw = str(name or "").strip()
    if not raw:
        return "***"
    parts = [p for p in raw.split() if p]
    masked_parts = []
    for p in parts:
        if len(p) <= 1:
            masked_parts.append("*")
        else:
            masked_parts.append(p[0] + ("*" * min(len(p) - 1, 3)))
    return " ".join(masked_parts)


def mask_pii_phone(phone: Optional[str]) -> str:
    """Masks customer phone number (e.g., '6281234567890' -> '6281******890')."""
    raw = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(raw) <= 6:
        return "***"
    return f"{raw[:4]}{'*' * max(len(raw) - 7, 4)}{raw[-3:]}"


def mask_pii_email(email: Optional[str]) -> str:
    """Masks customer email address (e.g., 'budi.alumni@gmail.com' -> 'bu***@gmail.com')."""
    raw = str(email or "").strip()
    if "@" not in raw:
        return "***"
    local, _, domain = raw.partition("@")
    if not domain:
        return "***"
    prefix = local[:2] if len(local) >= 2 else (local[:1] or "*")
    return f"{prefix}***@{domain}"


def sanitize_public_invoice_dto(invoice: Mapping[str, Any]) -> Dict[str, Any]:
    """Produces a sanitized, PII-masked public invoice DTO with zero sensitive internal fields."""
    return {
        "order_id": str(invoice.get("order_id") or ""),
        "sku": invoice.get("sku"),
        "sku_id": invoice.get("sku_id"),
        "base_amount": invoice.get("base_amount"),
        "unique_code": invoice.get("unique_code"),
        "total_amount": invoice.get("total_amount"),
        "currency": invoice.get("currency", "IDR"),
        "qr_string": invoice.get("qr_string"),
        "qr_image_url": invoice.get("qr_image_url"),
        "customer_name": mask_pii_name(invoice.get("customer_name")),
        "customer_email": mask_pii_email(invoice.get("customer_email")),
        "customer_phone": mask_pii_phone(invoice.get("customer_phone")),
        "tenant_id": invoice.get("tenant_id"),
        "ttl_minutes": invoice.get("ttl_minutes"),
        "expires_at": invoice.get("expires_at"),
        "created_at": invoice.get("created_at"),
        "status": invoice.get("status", "PENDING"),
    }


def extract_cookie_token(headers: Mapping[str, str]) -> Optional[str]:
    """Extracts the checkout session token from the Cookie header if present."""
    cookie_hdr = headers.get("cookie", "")
    if not cookie_hdr:
        return None
    for chunk in cookie_hdr.split(";"):
        k, sep, v = chunk.strip().partition("=")
        if not sep:
            continue
        k_clean = k.strip()
        v_clean = v.strip()
        if k_clean in (COOKIE_CHECKOUT_SESSION_HOST, COOKIE_CHECKOUT_SESSION_FALLBACK) and v_clean:
            return v_clean
    return None


class CheckoutSessionTokenManager:
    """Issues and verifies ownership-bound, revocable checkout session tokens (`P0-D`).

    Token format: `v1.<cs_key_id>.<iat>.<exp>.<jti>.<hmac_sha256_hex>`
    Signing string: `cs:v1:{cs_key_id}:{iat}:{exp}:{jti}:{order_id}:{canonical_tenant_id}`
    """

    def __init__(
        self,
        keys: Optional[Mapping[str, Mapping[str, Any]]] = None,
        *,
        environ: Optional[Mapping[str, str]] = None,
    ) -> None:
        env = environ if environ is not None else os.environ
        master_key = str(env.get(ENV_APP_MASTER_KEY, "")).strip()

        if keys is None:
            raw_json = str(env.get(ENV_CHECKOUT_SESSION_KEYRING, "")).strip()
            if raw_json:
                try:
                    keys = json.loads(raw_json)
                except Exception as exc:
                    raise PaymentConfigurationError(
                        f"Invalid JSON in {ENV_CHECKOUT_SESSION_KEYRING}."
                    ) from exc
            elif is_production_environment(env):
                raise PaymentConfigurationError(
                    f"{ENV_CHECKOUT_SESSION_KEYRING} must be configured in production."
                )
            else:
                keys = {
                    _EPHEMERAL_DEV_CS_KEY_ID: {
                        "secret": _EPHEMERAL_DEV_CS_SECRET,
                        "status": "ACTIVE",
                    }
                }

        if not isinstance(keys, Mapping) or not keys:
            raise PaymentConfigurationError("CheckoutSessionTokenManager requires at least one key.")

        self._keys: Dict[str, Dict[str, str]] = {}
        self._active_key_id: Optional[str] = None

        for kid, meta in keys.items():
            clean_kid = str(kid).strip()
            if not clean_kid or "." in clean_kid or ":" in clean_kid:
                raise PaymentConfigurationError(f"Invalid checkout session key_id '{clean_kid}'.")
            secret = str(meta.get("secret") or "").strip()
            status = str(meta.get("status") or "").strip().upper()
            if len(secret) < 32:
                raise PaymentConfigurationError(
                    f"Checkout session key '{clean_kid}' secret must be at least 32 characters."
                )
            if master_key and hmac.compare_digest(secret, master_key):
                raise PaymentConfigurationError(
                    f"Checkout session key '{clean_kid}' is forbidden from reusing APP_MASTER_KEY."
                )
            if status not in ("ACTIVE", "VERIFY_ONLY", "REVOKED"):
                raise PaymentConfigurationError(
                    f"Checkout session key '{clean_kid}' has invalid status '{status}'."
                )
            self._keys[clean_kid] = {"secret": secret, "status": status}
            if status == "ACTIVE" and self._active_key_id is None:
                self._active_key_id = clean_kid

    def _compute_sig(
        self,
        *,
        secret: str,
        cs_key_id: str,
        iat: int,
        exp: int,
        jti: str,
        order_id: str,
        canonical_tenant_id: str,
    ) -> str:
        payload = f"cs:v1:{cs_key_id}:{int(iat)}:{int(exp)}:{jti}:{order_id}:{canonical_tenant_id}"
        return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def issue_token(
        self,
        *,
        order_id: str,
        canonical_tenant_id: str,
        ttl_seconds: int = 900,
        now_epoch: Optional[int] = None,
        key_id: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Issues a signed checkout session token and returns `(token, session_metadata_dict)`."""
        target_kid = key_id or self._active_key_id
        if not target_kid or target_kid not in self._keys:
            raise PaymentConfigurationError("No ACTIVE checkout session signing key available.")
        rec = self._keys[target_kid]
        if rec["status"] != "ACTIVE":
            raise PaymentConfigurationError(f"Checkout session key '{target_kid}' is not ACTIVE.")

        iat = int(now_epoch if now_epoch is not None else time.time())
        exp = iat + min(max(int(ttl_seconds), 60), 86400)
        jti = secrets.token_hex(16)
        clean_order = str(order_id).strip()
        clean_tenant = str(canonical_tenant_id).strip().lower()

        sig = self._compute_sig(
            secret=rec["secret"],
            cs_key_id=target_kid,
            iat=iat,
            exp=exp,
            jti=jti,
            order_id=clean_order,
            canonical_tenant_id=clean_tenant,
        )
        token = f"v1.{target_kid}.{iat}.{exp}.{jti}.{sig}"
        session_meta = {
            "jti": jti,
            "iat": iat,
            "exp": exp,
            "revoked": False,
            "order_id": clean_order,
            "canonical_tenant_id": clean_tenant,
            "cs_key_id": target_kid,
        }
        return token, session_meta

    def verify_request_and_authorize_invoice(
        self,
        *,
        requested_order_id: str,
        invoice_record: Optional[Mapping[str, Any]],
        headers: Mapping[str, Any],
        raw_query_string: Optional[str] = None,
        now_epoch: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Verifies the checkout session token and returns the sanitized invoice DTO.

        Enforces:
        - Constant-time dummy HMAC computation when order or token is missing (anti-enumeration).
        - Strict rejection if ANY query parameter is present in the URL (`?token=...`, `?st=...`).
        - Strict ownership binding (`order_id` and `canonical_tenant_id`).
        - Expiration (`now_epoch > exp`) and revocation (`revoked == True` or `status == 'CANCELLED'`).
        - Raises `PaymentAuthorizationError(..., http_status=404)` with uniform message on any failure.
        """
        norm_headers = _normalize_headers(headers)
        current_ts = int(now_epoch if now_epoch is not None else time.time())

        # Always obtain a secret for constant-time HMAC calculation to prevent timing enumeration
        fallback_secret = next(iter(self._keys.values()))["secret"]
        dummy_sig = self._compute_sig(
            secret=fallback_secret,
            cs_key_id="dummy",
            iat=current_ts,
            exp=current_ts + 900,
            jti="0" * 32,
            order_id=str(requested_order_id or "none"),
            canonical_tenant_id="none",
        )

        # 1. Zero Token in URL Rule: Reject if any query string parameter is present on GET /invoice/{id}
        if raw_query_string is not None and str(raw_query_string).strip() != "":
            hmac.compare_digest(dummy_sig, "0" * 64)
            raise PaymentAuthorizationError(
                "Invoice not found",
                error_code="CHECKOUT_SESSION_URL_TOKEN_FORBIDDEN",
                http_status=404,
            )

        # 2. Extract token ONLY from X-Checkout-Session-Token header or __Host-bt_checkout_st cookie
        token = norm_headers.get(HDR_CHECKOUT_SESSION_TOKEN, "").strip()
        if not token:
            token = extract_cookie_token(norm_headers) or ""

        if not token or invoice_record is None:
            hmac.compare_digest(dummy_sig, "0" * 64)
            raise PaymentAuthorizationError(
                "Invoice not found",
                error_code="CHECKOUT_SESSION_UNAUTHORIZED",
                http_status=404,
            )

        parts = token.split(".")
        if len(parts) != 6 or parts[0] != "v1":
            hmac.compare_digest(dummy_sig, "0" * 64)
            raise PaymentAuthorizationError(
                "Invoice not found",
                error_code="CHECKOUT_SESSION_MALFORMED",
                http_status=404,
            )

        _, cs_key_id, iat_str, exp_str, jti, provided_sig = parts
        try:
            iat = int(iat_str)
            exp = int(exp_str)
        except Exception as exc:
            hmac.compare_digest(dummy_sig, "0" * 64)
            raise PaymentAuthorizationError(
                "Invoice not found",
                error_code="CHECKOUT_SESSION_MALFORMED",
                http_status=404,
            ) from exc

        key_rec = self._keys.get(cs_key_id)
        if not key_rec or key_rec["status"] == "REVOKED":
            hmac.compare_digest(dummy_sig, "0" * 64)
            raise PaymentAuthorizationError(
                "Invoice not found",
                error_code="CHECKOUT_SESSION_KEY_INVALID",
                http_status=404,
            )

        inv_order_id = str(invoice_record.get("order_id") or "").strip()
        session_meta = invoice_record.get("checkout_session") or {}
        inv_tenant = str(
            session_meta.get("canonical_tenant_id")
            or invoice_record.get("canonical_tenant_id")
            or invoice_record.get("tenant_id")
            or ""
        ).strip().lower()

        expected_sig = self._compute_sig(
            secret=key_rec["secret"],
            cs_key_id=cs_key_id,
            iat=iat,
            exp=exp,
            jti=jti,
            order_id= str(requested_order_id).strip(),
            canonical_tenant_id=inv_tenant,
        )

        sig_ok = hmac.compare_digest(expected_sig.lower(), provided_sig.strip().lower())
        order_ok = hmac.compare_digest(str(requested_order_id).strip(), inv_order_id)
        try:
            recorded_exp = int(session_meta.get("exp", exp))
        except Exception:
            recorded_exp = exp
        effective_exp = min(exp, recorded_exp)
        not_expired = (current_ts <= effective_exp) and (iat <= effective_exp)

        inv_status = str(invoice_record.get("status") or "").strip().upper()
        not_revoked = (
            not bool(session_meta.get("revoked", False))
            and inv_status not in ("CANCELLED", "REVOKED", "EXPIRED")
        )
        recorded_jti = str(session_meta.get("jti") or "")
        jti_ok = bool(recorded_jti) and hmac.compare_digest(jti, recorded_jti)

        if not (sig_ok and order_ok and not_expired and not_revoked and jti_ok):
            raise PaymentAuthorizationError(
                "Invoice not found",
                error_code="CHECKOUT_SESSION_INVALID_OR_EXPIRED",
                http_status=404,
            )

        return sanitize_public_invoice_dto(invoice_record)


# =============================================================================
# 7. Stage 3 Step 2A: Credential Profile Data Model & Mapper (Multi-Tenant)
# =============================================================================

ALLOWED_CREDENTIAL_PROVIDERS: FrozenSet[str] = frozenset({"XENDIT", "MIDTRANS", "DUITKU"})
ALLOWED_PROFILE_STATUSES: FrozenSet[str] = frozenset({"ACTIVE", "SUSPENDED", "REVOKED"})
ALLOWED_SECRET_STATUSES: FrozenSet[str] = frozenset({"ACTIVE", "VERIFY_ONLY", "REVOKED"})
ALLOWED_ENVIRONMENTS: FrozenSet[str] = frozenset({"production", "sandbox"})


@dataclass(frozen=True)
class CredentialSecretVersion:
    """One verification secret version (callback_token / server_key / api_key)
    within the Credential Profile rotation lifecycle.
    Stores secret_ref (pointer to Secret Manager / Encrypted Vault / Resolver), NEVER plaintext.
    """
    secret_version_id: str
    secret_ref: str
    status: str  # "ACTIVE" | "VERIFY_ONLY" | "REVOKED"
    created_at_utc: str
    rotated_at_utc: Optional[str] = None
    not_after_epoch: Optional[int] = None  # Mandatory if status == "VERIFY_ONLY"

    def __post_init__(self) -> None:
        if not self.secret_version_id or not isinstance(self.secret_version_id, str):
            raise PaymentConfigurationError(
                "secret_version_id must be a non-empty string.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )
        if not self.secret_ref or not isinstance(self.secret_ref, str):
            raise PaymentConfigurationError(
                "secret_ref must be a non-empty pointer string URI.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )
        norm_status = str(self.status or "").strip().upper()
        if norm_status not in ALLOWED_SECRET_STATUSES:
            raise PaymentConfigurationError(
                f"Invalid secret status '{self.status}'. Must be one of {sorted(ALLOWED_SECRET_STATUSES)}.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )
        object.__setattr__(self, "status", norm_status)
        if norm_status == "VERIFY_ONLY" and self.not_after_epoch is None:
            raise PaymentConfigurationError(
                f"Secret version '{self.secret_version_id}' with status 'VERIFY_ONLY' mandates 'not_after_epoch'.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )


@dataclass(frozen=True)
class TenantCredentialProfile:
    """Internal Payment Gateway credential profile bound strictly 1-to-1 with canonical_tenant_id."""
    credential_profile_id: str
    canonical_tenant_id: str  # Canonical lowercase UUID from tenants.id
    provider: str  # "XENDIT" | "MIDTRANS" | "DUITKU"
    verification_method: str  # e.g. "XENDIT_CALLBACK_TOKEN", "MIDTRANS_SHA512", "DUITKU_CALLBACK_HMAC_SHA256"
    expected_provider_account_id: str  # Xendit business_id / Midtrans merchant_id / Duitku merchantCode
    environment: str  # "production" | "sandbox"
    profile_status: str  # "ACTIVE" | "SUSPENDED" | "REVOKED"
    verification_secrets: Tuple[CredentialSecretVersion, ...]
    updated_at_utc: str
    rotated_by_principal: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.credential_profile_id or not isinstance(self.credential_profile_id, str):
            raise PaymentConfigurationError(
                "credential_profile_id must be a non-empty string.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )
        val_uuid = _validate_uuid_str(self.canonical_tenant_id)
        if not val_uuid:
            raise PaymentAuthorizationError(
                f"canonical_tenant_id '{self.canonical_tenant_id}' is not a valid canonical UUID.",
                error_code="INVALID_CANONICAL_TENANT_ID",
                http_status=422,
            )
        object.__setattr__(self, "canonical_tenant_id", val_uuid)

        norm_prov = str(self.provider or "").strip().upper()
        if norm_prov not in ALLOWED_CREDENTIAL_PROVIDERS:
            raise PaymentConfigurationError(
                f"Unsupported provider '{self.provider}'. Must be one of {sorted(ALLOWED_CREDENTIAL_PROVIDERS)}.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )
        object.__setattr__(self, "provider", norm_prov)

        norm_status = str(self.profile_status or "").strip().upper()
        if norm_status not in ALLOWED_PROFILE_STATUSES:
            raise PaymentConfigurationError(
                f"Invalid profile_status '{self.profile_status}'. Must be one of {sorted(ALLOWED_PROFILE_STATUSES)}.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )
        object.__setattr__(self, "profile_status", norm_status)

        norm_env = str(self.environment or "").strip().lower()
        if norm_env not in ALLOWED_ENVIRONMENTS:
            raise PaymentConfigurationError(
                f"Invalid environment '{self.environment}'. Must be one of {sorted(ALLOWED_ENVIRONMENTS)}.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )
        object.__setattr__(self, "environment", norm_env)

        if not self.expected_provider_account_id or not isinstance(self.expected_provider_account_id, str):
            raise PaymentConfigurationError(
                "expected_provider_account_id must be a non-empty string.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )

        if not self.verification_secrets:
            raise PaymentConfigurationError(
                f"Credential profile '{self.credential_profile_id}' must contain at least one verification secret.",
                error_code="INVALID_CREDENTIAL_PROFILE",
                http_status=422,
            )


@dataclass(frozen=True)
class CredentialVerificationResult:
    """Proof of credential profile resolution and secret verification.
    SECURITY NOTICE: matched_secret_value is NEVER stored or returned.
    Verification secrets are consumed strictly in-memory within the verifier boundary.
    """
    credential_profile_id: str
    canonical_tenant_id: str
    provider: str
    verification_method: str
    expected_provider_account_id: str
    matched_secret_version_id: str
    matched_secret_status: str
    environment: str
    audit_entry: Dict[str, Any]


class CredentialProfileMapper:
    """Stage 3 Step 2A: Multi-Tenant Credential Profile Mapper.

    Invariants:
    1. Strict 1-to-1 canonical lowercase UUID tenant binding.
    2. Multiple credential profiles per tenant.
    3. Multiple profiles per provider supported.
    4. `active_provider` is only a checkout default; never an exclusivity mechanism.
    5. Explicit order-level `credential_profile_id` takes precedence during callback resolution.
    6. Legacy fallback only if exactly one ACTIVE profile matches canonical tenant and trusted callback provider.
    7. Zero matches -> NOT_FOUND; multiple matches -> AMBIGUOUS; inactive -> INACTIVE; tenant mismatch -> TENANT_MISMATCH.
    8. Environment mismatch (sandbox under production) fails closed.
    9. Secrets resolved exclusively via pointer URIs (secret_ref); plaintext secrets in metadata rejected.
    10. Constant-time verification across ACTIVE and non-expired grace VERIFY_ONLY secrets.
    11. REVOKED and expired secrets rejected fail-closed.
    12. Zero plaintext secret returned in results or audit trail.
    """

    def __init__(
        self,
        *,
        secret_resolver: Optional[Callable[[str], str]] = None,
        runtime_environment: Optional[str] = None,
        clock_fn: Optional[Callable[[], datetime]] = None,
        vault_store: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._secret_resolver = secret_resolver
        raw_env = (
            runtime_environment
            or os.getenv("APP_ENV", "development")
        ).strip().lower()
        if raw_env in ("prod", "production"):
            self._runtime_environment = "production"
        else:
            self._runtime_environment = "sandbox"
        self._clock_fn = clock_fn or (lambda: datetime.now(timezone.utc))
        self._vault_store: Dict[str, str] = dict(vault_store or {})

    @property
    def runtime_environment(self) -> str:
        return self._runtime_environment

    def _resolve_secret_ref(self, secret_ref: str) -> str:
        """Resolves secret_ref pointer string to raw secret.
        Rejects plaintext, arbitrary unvalidated schemes, or missing secrets.
        """
        if not isinstance(secret_ref, str) or not secret_ref.strip():
            raise PaymentAuthorizationError(
                "Invalid secret_ref: pointer must be a non-empty string URI.",
                error_code="CREDENTIAL_SECRET_UNAVAILABLE",
                http_status=503,
            )
        ref = secret_ref.strip()

        if self._secret_resolver is not None:
            val = self._secret_resolver(ref)
            if not val or not isinstance(val, str):
                raise PaymentAuthorizationError(
                    f"Custom secret resolver failed to resolve non-empty secret for pointer '{ref}'.",
                    error_code="CREDENTIAL_SECRET_UNAVAILABLE",
                    http_status=503,
                )
            return val

        if ref.startswith("env://"):
            var_name = ref[len("env://"):].strip()
            if not var_name or var_name not in os.environ:
                raise PaymentAuthorizationError(
                    f"Secret environment variable '{var_name}' is not set.",
                    error_code="CREDENTIAL_SECRET_UNAVAILABLE",
                    http_status=503,
                )
            val = os.environ[var_name]
            if not val:
                raise PaymentAuthorizationError(
                    f"Secret environment variable '{var_name}' is empty.",
                    error_code="CREDENTIAL_SECRET_UNAVAILABLE",
                    http_status=503,
                )
            return val
        elif ref.startswith("vault://"):
            if ref in self._vault_store:
                val = self._vault_store[ref]
                if not val:
                    raise PaymentAuthorizationError(
                        f"Vault secret at '{ref}' is empty.",
                        error_code="CREDENTIAL_SECRET_UNAVAILABLE",
                        http_status=503,
                    )
                return val
            raise PaymentAuthorizationError(
                f"Vault secret provider unavailable for '{ref}'.",
                error_code="CREDENTIAL_SECRET_UNAVAILABLE",
                http_status=503,
            )
        else:
            raise PaymentAuthorizationError(
                f"Unsupported secret_ref pointer scheme '{ref}'. Only explicit pointer schemes (env://, vault://) are allowed.",
                error_code="CREDENTIAL_SECRET_UNAVAILABLE",
                http_status=503,
            )

    def parse_profiles_from_metadata(
        self,
        tenant_metadata: Mapping[str, Any],
        expected_canonical_tenant_id: Optional[str] = None,
    ) -> List[TenantCredentialProfile]:
        """Parses and validates all TenantCredentialProfile objects from tenant_metadata['payment_config']['credential_profiles'].
        Enforces:
        - If expected_canonical_tenant_id is provided, every profile must match that UUID exactly.
        - Profiles must have valid canonical lowercase UUIDs.
        - Plaintext secrets directly inside metadata are rejected.
        """
        if not isinstance(tenant_metadata, Mapping):
            return []

        pay_cfg = tenant_metadata.get("payment_config")
        if not isinstance(pay_cfg, Mapping):
            pay_cfg = tenant_metadata if "credential_profiles" in tenant_metadata else {}

        raw_profiles = pay_cfg.get("credential_profiles")
        if not raw_profiles:
            return []

        profile_dicts: List[Dict[str, Any]] = []
        if isinstance(raw_profiles, list):
            for item in raw_profiles:
                if isinstance(item, dict):
                    profile_dicts.append(item)
        elif isinstance(raw_profiles, dict):
            for k, item in raw_profiles.items():
                if isinstance(item, dict):
                    # Ensure credential_profile_id is populated if key is profile id
                    p_dict = dict(item)
                    if "credential_profile_id" not in p_dict and k.startswith("cred_"):
                        p_dict["credential_profile_id"] = k
                    profile_dicts.append(p_dict)

        expected_uuid = None
        if expected_canonical_tenant_id is not None:
            expected_uuid = _validate_uuid_str(expected_canonical_tenant_id)
            if not expected_uuid:
                raise PaymentAuthorizationError(
                    f"Invalid expected_canonical_tenant_id '{expected_canonical_tenant_id}'. Must be a valid canonical UUID.",
                    error_code="INVALID_CANONICAL_TENANT_ID",
                    http_status=422,
                )

        parsed_profiles: List[TenantCredentialProfile] = []
        seen_profile_ids: set[str] = set()

        for raw_p in profile_dicts:
            # Security guard: reject plaintext secrets stored directly in metadata
            for forbidden_raw_field in ("secret_key", "api_key", "server_key", "callback_token", "secret_value"):
                if forbidden_raw_field in raw_p and not str(raw_p[forbidden_raw_field]).startswith(("env://", "vault://")):
                    raise PaymentAuthorizationError(
                        f"Plaintext secret in '{forbidden_raw_field}' is prohibited in credential metadata. "
                        "Must use secret_ref pointer architecture.",
                        error_code="INVALID_CREDENTIAL_PROFILE",
                        http_status=422,
                    )

            p_id = str(raw_p.get("credential_profile_id") or "").strip()
            if not p_id:
                raise PaymentConfigurationError(
                    "Credential profile missing required 'credential_profile_id'.",
                    error_code="INVALID_CREDENTIAL_PROFILE",
                    http_status=422,
                )
            if p_id in seen_profile_ids:
                raise PaymentAuthorizationError(
                    f"Duplicate credential_profile_id '{p_id}' detected.",
                    error_code="AMBIGUOUS_CREDENTIAL_PROFILE_BINDING",
                    http_status=403,
                )
            seen_profile_ids.add(p_id)

            t_uuid = _validate_uuid_str(raw_p.get("canonical_tenant_id"))
            if not t_uuid:
                raise PaymentAuthorizationError(
                    f"Profile '{p_id}' possesses invalid or non-UUID canonical_tenant_id '{raw_p.get('canonical_tenant_id')}'.",
                    error_code="INVALID_CANONICAL_TENANT_ID",
                    http_status=422,
                )

            if expected_uuid is not None and t_uuid != expected_uuid:
                raise PaymentAuthorizationError(
                    f"Credential profile tenant mismatch: profile '{p_id}' belongs to tenant '{t_uuid}', "
                    f"not expected tenant '{expected_uuid}'.",
                    error_code="CREDENTIAL_PROFILE_TENANT_MISMATCH",
                    http_status=403,
                )

            raw_secrets = raw_p.get("verification_secrets") or []
            if not isinstance(raw_secrets, list) or len(raw_secrets) == 0:
                raise PaymentConfigurationError(
                    f"Credential profile '{p_id}' must define non-empty 'verification_secrets'.",
                    error_code="INVALID_CREDENTIAL_PROFILE",
                    http_status=422,
                )

            parsed_secrets: List[CredentialSecretVersion] = []
            active_secret_count = 0
            for s_item in raw_secrets:
                if not isinstance(s_item, dict):
                    raise PaymentConfigurationError(
                        f"Secret version in profile '{p_id}' must be a dictionary.",
                        error_code="INVALID_CREDENTIAL_PROFILE",
                        http_status=422,
                    )
                s_ver = CredentialSecretVersion(
                    secret_version_id=str(s_item.get("secret_version_id") or "").strip(),
                    secret_ref=str(s_item.get("secret_ref") or "").strip(),
                    status=str(s_item.get("status") or "").strip().upper(),
                    created_at_utc=str(s_item.get("created_at_utc") or "").strip(),
                    rotated_at_utc=s_item.get("rotated_at_utc"),
                    not_after_epoch=s_item.get("not_after_epoch"),
                )
                if s_ver.status == "ACTIVE":
                    active_secret_count += 1
                parsed_secrets.append(s_ver)

            profile = TenantCredentialProfile(
                credential_profile_id=p_id,
                canonical_tenant_id=t_uuid,
                provider=str(raw_p.get("provider") or "").strip().upper(),
                verification_method=str(raw_p.get("verification_method") or "").strip().upper(),
                expected_provider_account_id=str(raw_p.get("expected_provider_account_id") or "").strip(),
                environment=str(raw_p.get("environment") or "").strip().lower(),
                profile_status=str(raw_p.get("profile_status") or "").strip().upper(),
                verification_secrets=tuple(parsed_secrets),
                updated_at_utc=str(raw_p.get("updated_at_utc") or "").strip(),
                rotated_by_principal=raw_p.get("rotated_by_principal"),
            )
            parsed_profiles.append(profile)

        return parsed_profiles

    def resolve_checkout_profile(
        self,
        tenant_metadata: Mapping[str, Any],
        requested_provider: Optional[str] = None,
    ) -> TenantCredentialProfile:
        """Resolves the active TenantCredentialProfile for checkout.
        - If requested_provider is provided, uses it.
        - Otherwise defaults to payment_config['active_provider'].
        - Mandates that the candidate profile is ACTIVE and matches the runtime environment.
        - Fails closed on missing provider, missing profile, or ambiguous active profiles.
        """
        if not isinstance(tenant_metadata, Mapping):
            raise PaymentConfigurationError(
                "tenant_metadata must be a mapping.",
                error_code="MISSING_PAYMENT_CONFIG",
                http_status=422,
            )

        pay_cfg = tenant_metadata.get("payment_config")
        if not isinstance(pay_cfg, Mapping):
            pay_cfg = tenant_metadata if "credential_profiles" in tenant_metadata else {}

        target_provider: Optional[str] = None
        if requested_provider is not None and str(requested_provider).strip():
            target_provider = str(requested_provider).strip().upper()
        else:
            active_prov = pay_cfg.get("active_provider")
            if active_prov and str(active_prov).strip():
                target_provider = str(active_prov).strip().upper()

        if not target_provider:
            raise PaymentConfigurationError(
                "No payment provider specified and no active_provider configured for checkout.",
                error_code="MISSING_PAYMENT_PROVIDER",
                http_status=422,
            )

        if target_provider not in ALLOWED_CREDENTIAL_PROVIDERS:
            raise PaymentConfigurationError(
                f"Unsupported payment provider '{target_provider}'. Must be one of {sorted(ALLOWED_CREDENTIAL_PROVIDERS)}.",
                error_code="UNSUPPORTED_PAYMENT_PROVIDER",
                http_status=422,
            )

        profiles = self.parse_profiles_from_metadata(tenant_metadata)
        matching_profiles = [
            p for p in profiles
            if p.provider == target_provider and p.profile_status == "ACTIVE"
        ]

        if not matching_profiles:
            raise PaymentAuthorizationError(
                f"No active credential profile found for provider '{target_provider}'.",
                error_code="CREDENTIAL_PROFILE_NOT_FOUND",
                http_status=404,
            )

        # Environment check
        if self._runtime_environment == "production":
            prod_candidates = [p for p in matching_profiles if p.environment == "production"]
            if not prod_candidates:
                raise PaymentAuthorizationError(
                    f"Active credential profile for provider '{target_provider}' is configured for sandbox, "
                    "but runtime environment is production.",
                    error_code="CREDENTIAL_PROFILE_ENVIRONMENT_MISMATCH",
                    http_status=403,
                )
            matching_profiles = prod_candidates
        else:
            # In sandbox / dev runtime, prefer sandbox profiles, but allow production if explicitly configured
            sandbox_candidates = [p for p in matching_profiles if p.environment == "sandbox"]
            if sandbox_candidates:
                matching_profiles = sandbox_candidates

        if len(matching_profiles) == 1:
            return matching_profiles[0]

        # Disambiguate if multiple active profiles match
        default_id = str(
            pay_cfg.get("default_credential_profile_id")
            or pay_cfg.get("default_profile_id")
            or ""
        ).strip()
        if default_id:
            specific = [p for p in matching_profiles if p.credential_profile_id == default_id]
            if len(specific) == 1:
                return specific[0]

        raise PaymentAuthorizationError(
            f"Ambiguous active credential profiles for provider '{target_provider}'. Multiple profiles exist without an explicit default.",
            error_code="AMBIGUOUS_CREDENTIAL_PROFILE_BINDING",
            http_status=403,
        )

    def resolve_and_verify_callback_secret(
        self,
        canonical_tenant_id: str,
        tenant_metadata: Mapping[str, Any],
        order_metadata: Optional[Mapping[str, Any]],
        provider: str,
        inbound_account_id: str,
        candidate_secret: str,
    ) -> CredentialVerificationResult:
        """Resolves the authoritative TenantCredentialProfile for an inbound callback and
        cryptographically verifies candidate_secret (constant-time) against ACTIVE or grace VERIFY_ONLY secrets.

        Invariants enforced:
        - Strict canonical lowercase UUID validation.
        - Explicit order_metadata['credential_profile_id'] takes precedence.
        - Legacy fallback applies only when exactly one ACTIVE profile matches canonical_tenant_id and provider.
        - Inactive profiles, tenant mismatches, and environment mismatches rejected fail-closed.
        - REVOKED and expired VERIFY_ONLY secrets rejected fail-closed.
        - Zero plaintext secret returned in result or audit trail.
        """
        norm_tenant_uuid = _validate_uuid_str(canonical_tenant_id)
        if not norm_tenant_uuid:
            raise PaymentAuthorizationError(
                f"canonical_tenant_id '{canonical_tenant_id}' is not a valid canonical UUID.",
                error_code="INVALID_CANONICAL_TENANT_ID",
                http_status=422,
            )

        norm_prov = str(provider or "").strip().upper()
        if norm_prov not in ALLOWED_CREDENTIAL_PROVIDERS:
            raise PaymentConfigurationError(
                f"Unsupported payment provider '{provider}'. Must be one of {sorted(ALLOWED_CREDENTIAL_PROVIDERS)}.",
                error_code="UNSUPPORTED_PAYMENT_PROVIDER",
                http_status=422,
            )

        profiles = self.parse_profiles_from_metadata(
            tenant_metadata,
            expected_canonical_tenant_id=norm_tenant_uuid,
        )

        order_meta = order_metadata if isinstance(order_metadata, Mapping) else {}
        bound_profile_id = str(order_meta.get("credential_profile_id") or "").strip()
        bound_provider = str(order_meta.get("provider") or "").strip().upper()

        selected_profile: TenantCredentialProfile

        if bound_profile_id:
            matching = [p for p in profiles if p.credential_profile_id == bound_profile_id]
            if not matching:
                raise PaymentAuthorizationError(
                    f"Credential profile '{bound_profile_id}' bound to order was not found for tenant '{norm_tenant_uuid}'.",
                    error_code="CREDENTIAL_PROFILE_NOT_FOUND",
                    http_status=404,
                )
            selected_profile = matching[0]

            if selected_profile.profile_status != "ACTIVE":
                raise PaymentAuthorizationError(
                    f"Credential profile '{bound_profile_id}' is inactive ({selected_profile.profile_status}).",
                    error_code="CREDENTIAL_PROFILE_INACTIVE",
                    http_status=403,
                )

            if selected_profile.canonical_tenant_id != norm_tenant_uuid:
                raise PaymentAuthorizationError(
                    f"Credential profile '{bound_profile_id}' does not belong to tenant '{norm_tenant_uuid}'.",
                    error_code="CREDENTIAL_PROFILE_TENANT_MISMATCH",
                    http_status=403,
                )

            if selected_profile.provider != norm_prov:
                raise PaymentAuthorizationError(
                    f"Provider mismatch: order profile '{bound_profile_id}' is for '{selected_profile.provider}', "
                    f"but callback received for '{norm_prov}'.",
                    error_code="CREDENTIAL_PROFILE_PROVIDER_MISMATCH",
                    http_status=403,
                )

            if bound_provider and bound_provider != selected_profile.provider:
                raise PaymentAuthorizationError(
                    f"Provider mismatch: order bound provider '{bound_provider}' does not match profile provider '{selected_profile.provider}'.",
                    error_code="CREDENTIAL_PROFILE_PROVIDER_MISMATCH",
                    http_status=403,
                )
        else:
            # Legacy fallback: order lacks credential_profile_id
            # Resolve only if exactly one ACTIVE profile matches canonical_tenant_id and trusted callback provider
            matching = [
                p for p in profiles
                if p.canonical_tenant_id == norm_tenant_uuid
                and p.provider == norm_prov
                and p.profile_status == "ACTIVE"
            ]
            if len(matching) == 0:
                raise PaymentAuthorizationError(
                    f"No active credential profile found for tenant '{norm_tenant_uuid}' and provider '{norm_prov}'.",
                    error_code="CREDENTIAL_PROFILE_NOT_FOUND",
                    http_status=404,
                )
            if len(matching) > 1:
                raise PaymentAuthorizationError(
                    f"Ambiguous credential profile resolution: multiple active profiles ({[p.credential_profile_id for p in matching]}) "
                    f"match provider '{norm_prov}' without explicit order-level binding.",
                    error_code="AMBIGUOUS_CREDENTIAL_PROFILE_BINDING",
                    http_status=403,
                )
            selected_profile = matching[0]

        # Environment enforcement
        if self._runtime_environment == "production" and selected_profile.environment != "production":
            raise PaymentAuthorizationError(
                f"Credential profile '{selected_profile.credential_profile_id}' is in sandbox environment, "
                "but application is in production mode.",
                error_code="CREDENTIAL_PROFILE_ENVIRONMENT_MISMATCH",
                http_status=403,
            )

        # Inbound provider account ID check (constant-time)
        inbound_acct_str = str(inbound_account_id or "").strip()
        if not inbound_acct_str or not hmac.compare_digest(selected_profile.expected_provider_account_id, inbound_acct_str):
            raise PaymentAuthorizationError(
                f"Inbound provider account ID '{inbound_acct_str}' does not match expected account "
                f"'{selected_profile.expected_provider_account_id}' for profile '{selected_profile.credential_profile_id}'.",
                error_code="PROVIDER_ACCOUNT_MISMATCH",
                http_status=403,
            )

        # Candidate secret verification (constant-time)
        cand_secret_str = str(candidate_secret or "")
        if not cand_secret_str:
            raise PaymentAuthorizationError(
                "Webhook verification failed: empty candidate secret.",
                error_code="PG_WEBHOOK_SIGNATURE_INVALID",
                http_status=403,
            )

        current_epoch = int(self._clock_fn().timestamp())
        matched_version: Optional[CredentialSecretVersion] = None
        matched_expired: bool = False
        matched_revoked: bool = False

        for secret_ver in selected_profile.verification_secrets:
            raw_secret = self._resolve_secret_ref(secret_ver.secret_ref)
            is_match = hmac.compare_digest(raw_secret, cand_secret_str)
            if is_match:
                if secret_ver.status == "ACTIVE":
                    matched_version = secret_ver
                    break
                elif secret_ver.status == "VERIFY_ONLY":
                    if secret_ver.not_after_epoch is not None and current_epoch > secret_ver.not_after_epoch:
                        matched_expired = True
                    else:
                        matched_version = secret_ver
                        break
                elif secret_ver.status == "REVOKED":
                    matched_revoked = True

        if matched_version is not None:
            audit_entry = {
                "credential_profile_id": selected_profile.credential_profile_id,
                "canonical_tenant_id": selected_profile.canonical_tenant_id,
                "provider": selected_profile.provider,
                "verification_method": selected_profile.verification_method,
                "matched_secret_version_id": matched_version.secret_version_id,
                "matched_secret_status": matched_version.status,
                "environment": selected_profile.environment,
                "verified_at_utc": self._clock_fn().isoformat(),
                "outcome": "AUTHENTICATED",
            }
            return CredentialVerificationResult(
                credential_profile_id=selected_profile.credential_profile_id,
                canonical_tenant_id=selected_profile.canonical_tenant_id,
                provider=selected_profile.provider,
                verification_method=selected_profile.verification_method,
                expected_provider_account_id=selected_profile.expected_provider_account_id,
                matched_secret_version_id=matched_version.secret_version_id,
                matched_secret_status=matched_version.status,
                environment=selected_profile.environment,
                audit_entry=audit_entry,
            )

        if matched_revoked:
            raise PaymentAuthorizationError(
                f"Candidate secret matches revoked secret version in profile '{selected_profile.credential_profile_id}'.",
                error_code="REVOKED_CREDENTIAL_SECRET_VERSION",
                http_status=403,
            )

        if matched_expired:
            raise PaymentAuthorizationError(
                f"Candidate secret matches expired VERIFY_ONLY secret version in profile '{selected_profile.credential_profile_id}'.",
                error_code="EXPIRED_CREDENTIAL_SECRET_VERSION",
                http_status=403,
            )

        raise PaymentAuthorizationError(
            f"Webhook cryptographic verification failed for profile '{selected_profile.credential_profile_id}'.",
            error_code="PG_WEBHOOK_SIGNATURE_INVALID",
            http_status=403,
        )


