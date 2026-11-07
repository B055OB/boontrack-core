"""Dedicated Ed25519 Payment Provenance Authority & RFC 8785 Canonical JSON Serializer.

Phase 1 — Stage 1: Security Foundation (Corrective Implementation)

Enforces the following technical invariants:
1. RFC 8785 (JCS) deterministic canonical JSON serialization (full ECMA-262 §7.1.12.1
   binary64 number formatting, UTF-16 code unit key ordering, strict surrogate rejection).
2. Exact 17-field provenance contract (`PROVENANCE_CONTRACT_FIELDS`) with integer-only
   payment amounts (`verified_amount` must be `int`, never `float` or `bool`).
3. Asymmetric Ed25519 (RFC 8032) cryptographic signing & verification:
   - `ProvenanceSigningKeyring` (`PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON`):
     holds Ed25519 private keys (`ACTIVE`, `VERIFY_ONLY`, `REVOKED`) for `ProvenanceSigner`.
   - `ProvenanceVerificationKeyring` (`PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON`):
     holds Ed25519 public keys ONLY (`ACTIVE`, `VERIFY_ONLY`, `REVOKED`) for `ProvenanceVerifier`.
     `ProvenanceVerifier` possesses zero private keys and zero signing capability.
4. Replacement of caller-instantiable proof dataclasses with `VerifiedSettlementCapability`,
   which can ONLY be minted by `TrustedSettlementVerificationBoundary` after cryptographic
   provider callback verification (`XENDIT_CALLBACK_TOKEN` / `MIDTRANS_SHA512`) or verified
   Maker-Checker validation.
5. Direct Tenant Rail Hard-Lock: While Direct Tenant Rail is disabled (`EXPERIMENTAL /
   PENDING_REVIEW`), neither `TrustedSettlementVerificationBoundary`, `ProvenanceSigner`,
   nor `ProvenanceVerifier` permits `MANUAL_DIRECT_TENANT` proofs on the normal path.

TRUST BOUNDARY & THREAT MODEL DISCLOSURE:
- `ProvenanceVerifier` (public-key-only) is cryptographically isolated from `ProvenanceSigner`
  (private-key holder): compromising a verifier-only worker or inspecting its memory cannot
  yield signing keys or forge settlement proofs.
- However, within the OS process that loads `ProvenanceSigningKeyring`, the private signing
  authority shares the process trust boundary with all code running in that same process.
  Module-private tokens (`_BoundaryMintToken`) enforce software call-graph discipline against
  accidental or unauthorized internal caller misuse; they are NOT claimed as absolute protection
  against arbitrary in-process code execution (RCE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import math
import os
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.services.payment.base import PaymentConfigurationError, SettlementProvenanceError

PROVENANCE_SCHEMA_VERSION: str = "1.1"
PROVENANCE_SIGNATURE_ALGORITHM: str = "Ed25519"

# Canonical Environment Variable Names (Single Source of Truth — No Silent Fallbacks)
ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING: str = "PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON"
ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING: str = "PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON"
ENV_INTERNAL_HMAC_KEYRING: str = "PAYMENT_INTERNAL_HMAC_KEYRING_JSON"
ENV_APP_MASTER_KEY: str = "APP_MASTER_KEY"

# Deprecated / Legacy Environment Variable Aliases (Must Fail-Closed if Present)
FORBIDDEN_LEGACY_PROVENANCE_ENV_ALIASES: Tuple[str, ...] = (
    "PAYMENT_PROVENANCE_HMAC_KEYS_JSON",
    "PAYMENT_PROVENANCE_SIGNING_KEYRING",
    "PAYMENT_PROVENANCE_SIGNING_KEYRING_JSON",
)

# Pre-Implementation Contract: Exact 17 approved fields in canonical lexicographical order.
PROVENANCE_CONTRACT_FIELDS: Tuple[str, ...] = (
    "actor_principal",
    "canonical_tenant_id",
    "credential_profile_id",
    "currency",
    "event_id",
    "order_id",
    "prov_key_id",
    "provider",
    "provider_account_id",
    "provider_event_id",
    "rail_type",
    "schema_version",
    "settlement_status",
    "sku_id",
    "verification_method",
    "verified_amount",
    "verified_at_utc",
)

PROVENANCE_CONTRACT_FIELD_SET: FrozenSet[str] = frozenset(PROVENANCE_CONTRACT_FIELDS)

ALLOWED_RAIL_TYPES: FrozenSet[str] = frozenset({"NATIVE_PG", "MANUAL_DIRECT_TENANT"})
LOCKED_RAIL_TYPES: FrozenSet[str] = frozenset({"MANUAL_DIRECT_TENANT"})

# Stage 3 Native Payment Gateway Rail Policy (Strictly XENDIT, MIDTRANS, DUITKU)
STAGE3_NATIVE_PG_ALLOWED_PROVIDERS: FrozenSet[str] = frozenset(
    {"XENDIT", "MIDTRANS", "DUITKU"}
)
STAGE3_NATIVE_PG_ALLOWED_VERIFICATION_METHODS: FrozenSet[str] = frozenset(
    {
        "XENDIT_CALLBACK_TOKEN",
        "MIDTRANS_SHA512",
        "DUITKU_CALLBACK_HMAC_SHA256",
    }
)
STAGE3_NATIVE_PG_PROVIDER_METHOD_MAP: Mapping[str, FrozenSet[str]] = {
    "XENDIT": frozenset({"XENDIT_CALLBACK_TOKEN"}),
    "MIDTRANS": frozenset({"MIDTRANS_SHA512"}),
    "DUITKU": frozenset({"DUITKU_CALLBACK_HMAC_SHA256"}),
}
LOCKED_UNAUTHORIZED_PROVIDERS: FrozenSet[str] = frozenset(
    {"DOKU", "STRIPE", "MANUAL_BANK_MUTATION", "DODO", "DODO_MOR"}
)
LOCKED_UNAUTHORIZED_VERIFICATION_METHODS: FrozenSet[str] = frozenset(
    {
        "DOKU_HMAC_SHA256",
        "MAKER_CHECKER_BANK_MUTATION",
        "XENDIT_WEBHOOK_SIGNATURE",
        "DUITKU_CALLBACK_MD5",
    }
)

# Global Provenance Contract Allowlists:
# Distinct from Stage 3 Native PG policy constants so future authorized rails can be
# governed independently without mutating Native PG rules. While Direct Tenant Rail and
# non-Stage-3 providers remain locked/unapproved, the global allowlist equals Stage 3 Native PG.
ALLOWED_PROVIDERS: FrozenSet[str] = STAGE3_NATIVE_PG_ALLOWED_PROVIDERS
ALLOWED_VERIFICATION_METHODS: FrozenSet[str] = STAGE3_NATIVE_PG_ALLOWED_VERIFICATION_METHODS
ALLOWED_PROOF_SOURCES: FrozenSet[str] = frozenset(
    {
        "VERIFIED_PG_WEBHOOK_ADAPTER",
        "VERIFIED_MAKER_CHECKER_AUTHORITY",
    }
)
FORBIDDEN_UNTRUSTED_PROOF_SOURCES: FrozenSet[str] = frozenset(
    {
        "ORDER_STATUS_PAID_COLUMN",
        "APPLICATION_REQUEST_CLAIM",
        "PUBLIC_MARK_PAID",
        "UNVERIFIED_WEBHOOK",
        "DIRECT_DATACLASS_INSTANTIATION",
    }
)
ALLOWED_KEY_STATUSES: FrozenSet[str] = frozenset({"ACTIVE", "VERIFY_ONLY", "REVOKED"})


# =============================================================================
# 1. RFC 8785 (JCS) Canonical JSON Serialization Implementation
# =============================================================================

def _utf16_code_units_sort_key(key: str) -> Tuple[int, ...]:
    """Computes the RFC 8785 §3.2.3 sorting key based on UTF-16 code units.

    Strings are compared as sequences of 16-bit unsigned integers (UTF-16BE code units),
    ensuring accurate ordering across BMP characters (including U+E000..U+FFFF) and
    supplementary plane characters (U+10000..U+10FFFF encoded as surrogate pairs).
    """
    if not isinstance(key, str):
        raise ValueError("RFC 8785 object keys must be strings.")
    try:
        raw = key.encode("utf-16-be")
    except UnicodeEncodeError as exc:
        raise ValueError("Invalid UTF-16 surrogate in RFC 8785 object key.") from exc
    return tuple((raw[i] << 8) | raw[i + 1] for i in range(0, len(raw), 2))


def _escape_rfc8785_string(value: str) -> str:
    """Formats a string according to RFC 8785 §3.2.2.2."""
    if not isinstance(value, str):
        raise ValueError("Expected str for RFC 8785 string serialization.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Invalid UTF-8 surrogate in RFC 8785 string.") from exc

    out: List[str] = ['"']
    for ch in value:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError("Lone UTF-16 surrogate is illegal in RFC 8785 JSON.")
        if code == 0x08:
            out.append("\\b")
        elif code == 0x09:
            out.append("\\t")
        elif code == 0x0A:
            out.append("\\n")
        elif code == 0x0C:
            out.append("\\f")
        elif code == 0x0D:
            out.append("\\r")
        elif code == 0x22:
            out.append('\\"')
        elif code == 0x5C:
            out.append("\\\\")
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _format_rfc8785_number(value: Any) -> str:
    """Formats an integer or IEEE-754 binary64 float per RFC 8785 §3.2.2.3
    (ECMA-262 §7.1.12.1 `Number::toString`).

    Fixed-point notation is used for 10^-6 <= |x| < 10^21 (-6 <= exp < 21).
    Exponential notation (`e+` / `e-`) is used for |x| < 10^-6 or |x| >= 10^21.
    """
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid numeric value in _format_rfc8785_number.")

    if isinstance(value, int):
        if value == 0:
            return "0"
        return str(value)

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and Infinity are not permitted in RFC 8785 Canonical JSON.")
        if value == 0.0:
            return "0"

        sign = "-" if value < 0.0 else ""
        # Python's repr(float) produces the shortest IEEE-754 round-trip decimal significand.
        d = Decimal(repr(abs(value)))
        sign_d, digits_tuple, dec_exp = d.as_tuple()
        digits_str = "".join(str(x) for x in digits_tuple).rstrip("0")
        if not digits_str:
            return "0"

        # Total value is digits_str * 10^(n - k), where 10^(n-1) <= |value| < 10^n
        k = len(digits_str)
        n = d.adjusted() + 1

        if k <= n <= 21:
            return f"{sign}{digits_str}{'0' * (n - k)}"
        if 0 < n < k:
            return f"{sign}{digits_str[:n]}.{digits_str[n:]}"
        if -5 <= n <= 0:
            return f"{sign}0.{'0' * (-n)}{digits_str}"

        exp_val = n - 1
        exp_sign = "+" if exp_val >= 0 else "-"
        exp_str = f"{exp_sign}{abs(exp_val)}"
        if k == 1:
            return f"{sign}{digits_str}e{exp_str}"
        return f"{sign}{digits_str[0]}.{digits_str[1:]}e{exp_str}"

    raise ValueError(f"Unsupported numeric type for RFC 8785: {type(value).__name__}")


def _serialize_rfc8785_node(node: Any) -> str:
    """Recursively serializes a JSON value according to RFC 8785 (JCS).

    Note: Only pure `dict`, `list`, `tuple`, `str`, `int`, `float`, `bool`, and `None`
    are accepted. Custom mappings, sets, Decimals, or subclasses that introduce ambiguity
    are rejected.
    """
    if node is None:
        return "null"
    if node is True:
        return "true"
    if node is False:
        return "false"
    if isinstance(node, str):
        return _escape_rfc8785_string(node)
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return _format_rfc8785_number(node)
    if type(node) in (list, tuple):
        return "[" + ",".join(_serialize_rfc8785_node(item) for item in node) + "]"
    if type(node) is dict:
        for k in node.keys():
            if type(k) is not str:
                raise ValueError("RFC 8785 object keys must be exact str instances.")
        sorted_items = sorted(node.items(), key=lambda kv: _utf16_code_units_sort_key(kv[0]))
        serialized_members = [
            f"{_escape_rfc8785_string(k)}:{_serialize_rfc8785_node(v)}"
            for k, v in sorted_items
        ]
        return "{" + ",".join(serialized_members) + "}"

    raise ValueError(f"Unsupported type for RFC 8785 canonicalization: {type(node).__name__}")


def canonicalize_rfc8785(data: Any) -> bytes:
    """Serializes `data` into UTF-8 encoded RFC 8785 Canonical JSON bytes."""
    return _serialize_rfc8785_node(data).encode("utf-8")


def canonicalize_rfc8785_str(data: Any) -> str:
    """Serializes `data` into an RFC 8785 Canonical JSON string."""
    return _serialize_rfc8785_node(data)


# =============================================================================
# 2. Trusted Verification Boundary & Capability Minting
# =============================================================================

class _BoundaryMintToken:
    """Module-private capability token used to prevent accidental or unauthorized
    direct construction of `VerifiedSettlementCapability` by application callers.

    NOTE: As documented in the module header, this token enforces software call-graph
    discipline against internal API misuse; it is not a defense against arbitrary
    in-process code execution (RCE) within the signer's OS process.
    """
    __slots__ = ()


_BOUNDARY_MINT_TOKEN = _BoundaryMintToken()


def _compute_capability_seal(fields_without_key: Mapping[str, Any], proof_source: str) -> str:
    """Computes an internal structural integrity seal over the verified fields."""
    payload = dict(fields_without_key)
    payload["_proof_source"] = proof_source
    return hashlib.sha256(canonicalize_rfc8785(payload)).hexdigest()


@dataclass(frozen=True)
class VerifiedSettlementCapability:
    """Unforgeable capability object issued exclusively by `TrustedSettlementVerificationBoundary`
    after cryptographic verification of a payment gateway callback or Maker-Checker approval.

    Application callers cannot instantiate this class directly without `_BOUNDARY_MINT_TOKEN`.
    """

    proof_source: str
    actor_principal: str
    canonical_tenant_id: str
    credential_profile_id: str
    event_id: str
    order_id: str
    provider: str
    provider_account_id: str
    provider_event_id: str
    rail_type: str
    sku_id: str
    verification_method: str
    verified_amount: int
    verified_at_utc: str
    currency: str = "IDR"
    settlement_status: str = "SETTLED"
    schema_version: str = PROVENANCE_SCHEMA_VERSION
    _mint_token: Optional[_BoundaryMintToken] = field(default=None, repr=False, compare=False)
    _capability_seal: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.proof_source in FORBIDDEN_UNTRUSTED_PROOF_SOURCES or (
            self.proof_source not in ALLOWED_PROOF_SOURCES
        ):
            raise SettlementProvenanceError(
                f"Untrusted proof_source '{self.proof_source}'. Provenance can only be minted "
                f"from {sorted(ALLOWED_PROOF_SOURCES)}.",
                error_code="UNTRUSTED_PROVENANCE_SOURCE",
            )
        if self.rail_type in LOCKED_RAIL_TYPES:
            raise SettlementProvenanceError(
                f"Rail type '{self.rail_type}' is locked while Direct Tenant Rail is "
                "DISABLED (EXPERIMENTAL / PENDING_REVIEW).",
                error_code="DIRECT_TENANT_RAIL_SIGNING_LOCKED",
                http_status=403,
            )
        if self._mint_token is not _BOUNDARY_MINT_TOKEN or not self._capability_seal:
            raise SettlementProvenanceError(
                "Direct instantiation of VerifiedSettlementCapability / CryptographicVerificationProof "
                "by application callers is prohibited. Use TrustedSettlementVerificationBoundary.",
                error_code="UNTRUSTED_PROVENANCE_CALLER",
                http_status=403,
            )

    def to_unsigned_17_field_dict(self, prov_key_id: str) -> Dict[str, Any]:
        """Builds the exact 17-field provenance dictionary prior to Ed25519 signing."""
        raw = {
            "actor_principal": self.actor_principal,
            "canonical_tenant_id": self.canonical_tenant_id,
            "credential_profile_id": self.credential_profile_id,
            "currency": self.currency,
            "event_id": self.event_id,
            "order_id": self.order_id,
            "prov_key_id": prov_key_id,
            "provider": self.provider,
            "provider_account_id": self.provider_account_id,
            "provider_event_id": self.provider_event_id,
            "rail_type": self.rail_type,
            "schema_version": self.schema_version,
            "settlement_status": self.settlement_status,
            "sku_id": self.sku_id,
            "verification_method": self.verification_method,
            "verified_amount": self.verified_amount,
            "verified_at_utc": self.verified_at_utc,
        }
        expected_seal = _compute_capability_seal(
            {k: v for k, v in raw.items() if k != "prov_key_id"},
            self.proof_source,
        )
        if not hmac.compare_digest(self._capability_seal, expected_seal):
            raise SettlementProvenanceError(
                "VerifiedSettlementCapability integrity seal mismatch.",
                error_code="UNTRUSTED_PROVENANCE_CALLER",
            )
        return validate_provenance_17_field_contract(raw)


# Compatibility alias that strictly rejects direct caller instantiation:
CryptographicVerificationProof = VerifiedSettlementCapability


class TrustedSettlementVerificationBoundary:
    """Trusted verification gatekeeper that validates raw payment gateway cryptographic
    callbacks (or verified Maker-Checker approvals) and issues a `VerifiedSettlementCapability`.

    Callers cannot choose an arbitrary `actor_principal` or `proof_source`; the boundary
    verifies the cryptographic proof and binds the verifier identity deterministically.
    """

    @staticmethod
    def verify_pg_webhook_and_issue_capability(
        *,
        provider: str,
        verification_method: str,
        credential_profile_id: str,
        expected_provider_account_id: str,
        provider_verification_secret: str,
        webhook_headers: Mapping[str, str],
        webhook_payload: Mapping[str, Any],
        authoritative_order_id: str,
        authoritative_canonical_tenant_id: str,
        authoritative_order_amount: int,
        authoritative_sku_id: str,
        verified_at_utc: str,
        rail_type: str = "NATIVE_PG",
        duitku_s2s_verifier: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
        db_conn_factory: Optional[Any] = None,
        expected_provider_reference: Optional[str] = None,
        s2s_worker_id: Optional[str] = None,
        s2s_lease_seconds: int = 15,
    ) -> VerifiedSettlementCapability:
        """Verifies a native Payment Gateway webhook callback against the tenant's internal
        credential profile and authoritative order record before issuing a capability.
        """
        if rail_type in LOCKED_RAIL_TYPES:
            raise SettlementProvenanceError(
                f"Direct Tenant Rail ('{rail_type}') is DISABLED (EXPERIMENTAL / PENDING_REVIEW).",
                error_code="DIRECT_TENANT_RAIL_SIGNING_LOCKED",
                http_status=403,
            )
        if rail_type != "NATIVE_PG":
            raise SettlementProvenanceError(
                f"Invalid rail_type '{rail_type}' for PG webhook verification.",
                error_code="PROVENANCE_INVALID_RAIL_TYPE",
            )

        norm_provider = str(provider or "").strip().upper()
        norm_method = str(verification_method or "").strip().upper()
        if norm_provider not in STAGE3_NATIVE_PG_ALLOWED_PROVIDERS or norm_provider not in ALLOWED_PROVIDERS:
            raise SettlementProvenanceError(
                f"Unsupported provider '{norm_provider}'; allowed={sorted(STAGE3_NATIVE_PG_ALLOWED_PROVIDERS)}.",
                error_code="PROVENANCE_INVALID_PROVIDER",
                http_status=403,
            )
        if (
            norm_method not in STAGE3_NATIVE_PG_ALLOWED_VERIFICATION_METHODS
            or norm_method not in ALLOWED_VERIFICATION_METHODS
            or norm_method not in STAGE3_NATIVE_PG_PROVIDER_METHOD_MAP.get(norm_provider, frozenset())
        ):
            raise SettlementProvenanceError(
                f"Unsupported verification_method '{norm_method}' for provider '{norm_provider}'.",
                error_code="PROVENANCE_INVALID_VERIFICATION_METHOD",
                http_status=403,
            )

        profile_id = str(credential_profile_id or "").strip()
        expected_acct = str(expected_provider_account_id or "").strip()
        secret = str(provider_verification_secret or "")

        if not profile_id or not expected_acct or len(secret) < 16:
            raise SettlementProvenanceError(
                "Incomplete or weak tenant credential profile for webhook verification.",
                error_code="INVALID_CREDENTIAL_PROFILE",
            )

        if isinstance(authoritative_order_amount, bool) or not isinstance(authoritative_order_amount, int) or authoritative_order_amount <= 0:
            raise SettlementProvenanceError(
                "Authoritative order amount must be a positive integer.",
                error_code="PROVENANCE_INVALID_AMOUNT",
            )

        normalized_headers = {str(k).strip().lower(): str(v).strip() for k, v in (webhook_headers or {}).items()}
        auth_order_id_str = str(authoritative_order_id or "").strip()

        if norm_provider == "XENDIT" and norm_method == "XENDIT_CALLBACK_TOKEN":
            callback_token = normalized_headers.get("x-callback-token", "")
            if not callback_token or not hmac.compare_digest(callback_token, secret):
                raise SettlementProvenanceError(
                    "Xendit x-callback-token cryptographic verification failed.",
                    error_code="PG_WEBHOOK_SIGNATURE_INVALID",
                )
            data_obj = webhook_payload.get("data") if isinstance(webhook_payload.get("data"), Mapping) else {}
            top_biz = str(webhook_payload.get("business_id") or "").strip()
            data_biz = str(data_obj.get("business_id") or "").strip()
            if top_biz and data_biz and not hmac.compare_digest(top_biz, data_biz):
                raise SettlementProvenanceError(
                    "Xendit top-level business_id conflicts with data.business_id.",
                    error_code="PROVIDER_ACCOUNT_BINDING_MISMATCH",
                )
            payload_acct = top_biz or data_biz or str(webhook_payload.get("user_id") or "").strip()
            if not payload_acct or not hmac.compare_digest(payload_acct, expected_acct):
                raise SettlementProvenanceError(
                    f"Xendit business_id '{payload_acct}' does not match credential profile '{expected_acct}'.",
                    error_code="PROVIDER_ACCOUNT_BINDING_MISMATCH",
                )
            ext_id = str(data_obj.get("external_id") or data_obj.get("reference_id") or webhook_payload.get("external_id") or "").strip()
            if ext_id and not hmac.compare_digest(ext_id, auth_order_id_str):
                raise SettlementProvenanceError(
                    f"Xendit external_id '{ext_id}' does not match authoritative order '{auth_order_id_str}'.",
                    error_code="PROVENANCE_ORDER_MISMATCH",
                )
            raw_currency = data_obj.get("currency") if "currency" in data_obj else webhook_payload.get("currency")
            if raw_currency is not None and str(raw_currency).strip().upper() != "IDR":
                raise SettlementProvenanceError(
                    f"Unsupported Xendit currency '{raw_currency}'; expected 'IDR'.",
                    error_code="PROVENANCE_INVALID_CURRENCY",
                )
            payload_status = str(data_obj.get("status") or webhook_payload.get("status") or "").strip().upper()
            if payload_status not in ("PAID", "SETTLED", "SUCCEEDED", "COMPLETED"):
                raise SettlementProvenanceError(
                    f"Xendit webhook status '{payload_status}' is not a settled state.",
                    error_code="PG_WEBHOOK_NOT_SETTLED",
                )
            payload_amount = data_obj.get("amount") if "amount" in data_obj else webhook_payload.get("amount")
            if isinstance(payload_amount, bool) or not isinstance(payload_amount, int) or payload_amount <= 0:
                raise SettlementProvenanceError(
                    f"Xendit webhook amount must be a positive integer IDR amount, got {payload_amount!r}.",
                    error_code="PROVENANCE_INVALID_AMOUNT",
                )
            paid_amt = data_obj.get("paid_amount") if "paid_amount" in data_obj else webhook_payload.get("paid_amount")
            if paid_amt is not None and (isinstance(paid_amt, bool) or not isinstance(paid_amt, int) or paid_amt != payload_amount):
                raise SettlementProvenanceError(
                    "Xendit paid_amount conflicts with webhook amount.",
                    error_code="PROVENANCE_AMOUNT_MISMATCH",
                )
            if payload_amount != authoritative_order_amount:
                raise SettlementProvenanceError(
                    f"Xendit webhook amount '{payload_amount}' does not match authoritative order amount {authoritative_order_amount}.",
                    error_code="PROVENANCE_AMOUNT_MISMATCH",
                )
            event_id = str(
                normalized_headers.get("webhook-id")
                or normalized_headers.get("x-webhook-id")
                or webhook_payload.get("event_id")
                or webhook_payload.get("id")
                or data_obj.get("id")
                or ""
            ).strip()
            provider_event_id = str(
                data_obj.get("payment_id")
                or data_obj.get("qr_id")
                or data_obj.get("id")
                or webhook_payload.get("payment_id")
                or webhook_payload.get("qr_id")
                or webhook_payload.get("id")
                or ""
            ).strip()
            if not event_id or not provider_event_id or provider_event_id == auth_order_id_str:
                raise SettlementProvenanceError(
                    "Xendit webhook requires non-empty event_id and provider_event_id distinct from order_id.",
                    error_code="PROVENANCE_EMPTY_EVENT_ID",
                )

        elif norm_provider == "MIDTRANS" and norm_method == "MIDTRANS_SHA512":
            sig_key = str(webhook_payload.get("signature_key") or "").strip().lower()
            status_code = str(webhook_payload.get("status_code") or "").strip()
            gross_amount_raw = str(webhook_payload.get("gross_amount") or "").strip()
            payload_order_id = str(webhook_payload.get("order_id") or "").strip()
            expected_sig = hashlib.sha512(
                f"{payload_order_id}{status_code}{gross_amount_raw}{secret}".encode("utf-8")
            ).hexdigest().lower()
            if not sig_key or not hmac.compare_digest(sig_key, expected_sig):
                raise SettlementProvenanceError(
                    "Midtrans SHA-512 signature_key verification failed.",
                    error_code="PG_WEBHOOK_SIGNATURE_INVALID",
                )
            if not payload_order_id or not hmac.compare_digest(payload_order_id, auth_order_id_str):
                raise SettlementProvenanceError(
                    f"Midtrans order_id '{payload_order_id}' does not match authoritative order '{auth_order_id_str}'.",
                    error_code="PROVENANCE_ORDER_MISMATCH",
                )
            payload_acct = str(webhook_payload.get("merchant_id") or "").strip()
            if not payload_acct or not hmac.compare_digest(payload_acct, expected_acct):
                raise SettlementProvenanceError(
                    f"Midtrans merchant_id '{payload_acct}' does not match credential profile '{expected_acct}'.",
                    error_code="PROVIDER_ACCOUNT_BINDING_MISMATCH",
                )
            raw_currency = webhook_payload.get("currency")
            if raw_currency is not None and str(raw_currency).strip().upper() != "IDR":
                raise SettlementProvenanceError(
                    f"Unsupported Midtrans currency '{raw_currency}'; expected 'IDR'.",
                    error_code="PROVENANCE_INVALID_CURRENCY",
                )
            tx_status = str(webhook_payload.get("transaction_status") or "").strip().lower()
            fraud_status = str(webhook_payload.get("fraud_status") or "").strip().lower()
            is_settled_midtrans = status_code == "200" and (
                (tx_status == "settlement" and fraud_status in ("accept", ""))
                or (tx_status == "capture" and fraud_status == "accept")
            )
            if not is_settled_midtrans:
                raise SettlementProvenanceError(
                    f"Midtrans status (status_code='{status_code}', transaction_status='{tx_status}', "
                    f"fraud_status='{fraud_status}') is not an accepted settled state.",
                    error_code="PG_WEBHOOK_NOT_SETTLED",
                )
            try:
                dec_amt = Decimal(gross_amount_raw)
            except Exception as exc:
                raise SettlementProvenanceError("Invalid Midtrans gross_amount.", error_code="PROVENANCE_INVALID_AMOUNT") from exc
            if not dec_amt.is_finite() or dec_amt <= 0 or dec_amt != int(dec_amt):
                raise SettlementProvenanceError(
                    f"Midtrans gross_amount '{gross_amount_raw}' must be a positive whole integer IDR amount.",
                    error_code="PROVENANCE_INVALID_AMOUNT",
                )
            parsed_amt = int(dec_amt)
            if parsed_amt != authoritative_order_amount:
                raise SettlementProvenanceError(
                    f"Midtrans gross_amount '{parsed_amt}' does not match authoritative order amount {authoritative_order_amount}.",
                    error_code="PROVENANCE_AMOUNT_MISMATCH",
                )
            event_id = str(webhook_payload.get("transaction_id") or "").strip()
            if not event_id or event_id == auth_order_id_str:
                raise SettlementProvenanceError(
                    "Midtrans transaction_id must be a non-empty provider transaction identifier distinct from order_id.",
                    error_code="PROVENANCE_EMPTY_EVENT_ID",
                )
            provider_event_id = event_id

        elif norm_provider == "DUITKU" and norm_method == "DUITKU_CALLBACK_HMAC_SHA256":
            merchant_code = str(webhook_payload.get("merchantCode") or "").strip()
            amount_raw = webhook_payload.get("amount")
            merchant_order_id = str(webhook_payload.get("merchantOrderId") or "").strip()
            provided_sig = str(webhook_payload.get("signature") or "").strip().lower()
            result_code = str(webhook_payload.get("resultCode") or "").strip()
            reference = str(webhook_payload.get("reference") or "").strip()

            amount_sig_str = "" if isinstance(amount_raw, bool) or amount_raw is None else str(amount_raw).strip()
            expected_cb_sig = hmac.new(
                secret.encode("utf-8"),
                f"{merchant_code}{amount_sig_str}{merchant_order_id}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest().lower()
            if not provided_sig or len(provided_sig) != 64 or not hmac.compare_digest(provided_sig, expected_cb_sig):
                raise SettlementProvenanceError(
                    "Duitku callback HMAC-SHA256 signature verification failed.",
                    error_code="PG_WEBHOOK_SIGNATURE_INVALID",
                    http_status=403,
                )
            if not merchant_code or not hmac.compare_digest(merchant_code, expected_acct):
                raise SettlementProvenanceError(
                    f"Duitku merchantCode '{merchant_code}' does not match credential profile '{expected_acct}'.",
                    error_code="PROVIDER_ACCOUNT_BINDING_MISMATCH",
                    http_status=403,
                )
            if not merchant_order_id or not hmac.compare_digest(merchant_order_id, auth_order_id_str):
                raise SettlementProvenanceError(
                    f"Duitku merchantOrderId '{merchant_order_id}' does not match authoritative order '{auth_order_id_str}'.",
                    error_code="PROVENANCE_ORDER_MISMATCH",
                    http_status=422,
                )
            raw_currency = webhook_payload.get("currency")
            if raw_currency is not None and str(raw_currency).strip().upper() != "IDR":
                raise SettlementProvenanceError(
                    f"Unsupported Duitku currency '{raw_currency}'; expected 'IDR'.",
                    error_code="PROVENANCE_INVALID_CURRENCY",
                    http_status=422,
                )
            if isinstance(amount_raw, bool):
                raise SettlementProvenanceError(
                    "Duitku amount cannot be boolean.",
                    error_code="PROVENANCE_INVALID_AMOUNT",
                    http_status=422,
                )
            if isinstance(amount_raw, int):
                parsed_amt = amount_raw
            elif isinstance(amount_raw, str) and amount_raw.strip().isdigit():
                parsed_amt = int(amount_raw.strip())
            else:
                raise SettlementProvenanceError(
                    f"Duitku amount '{amount_raw!r}' must be a positive integer IDR amount.",
                    error_code="PROVENANCE_INVALID_AMOUNT",
                    http_status=422,
                )
            if parsed_amt <= 0:
                raise SettlementProvenanceError(
                    f"Duitku amount '{parsed_amt}' must be > 0.",
                    error_code="PROVENANCE_INVALID_AMOUNT",
                    http_status=422,
                )
            if parsed_amt != authoritative_order_amount:
                raise SettlementProvenanceError(
                    f"Duitku amount '{parsed_amt}' does not match authoritative order amount {authoritative_order_amount}.",
                    error_code="PROVENANCE_AMOUNT_MISMATCH",
                    http_status=422,
                )
            if result_code != "00":
                raise SettlementProvenanceError(
                    f"Duitku resultCode '{result_code}' is not a settled state ('00').",
                    error_code="PG_WEBHOOK_NOT_SETTLED",
                    http_status=200,
                )
            if (
                not reference
                or reference == auth_order_id_str
                or reference.lower().startswith(("ord-", "ref-", "merchant_ref"))
            ):
                raise SettlementProvenanceError(
                    "Duitku reference must be a non-empty provider reference distinct from order_id.",
                    error_code="PROVENANCE_EMPTY_EVENT_ID",
                    http_status=422,
                )
            if expected_provider_reference and not hmac.compare_digest(
                reference, str(expected_provider_reference).strip()
            ):
                raise SettlementProvenanceError(
                    "Duitku reference does not match pre-registered order provider_reference.",
                    error_code="PROVIDER_REFERENCE_MISMATCH",
                    http_status=422,
                )
            provider_event_id = reference
            event_id = str(webhook_payload.get("event_id") or f"duitku:{merchant_code}:{reference}").strip()
            canonical_tenant_uuid_str = str(uuid.UUID(str(authoritative_canonical_tenant_id).strip()))

            TrustedSettlementVerificationBoundary._verify_duitku_s2s_once_with_idempotency(
                merchant_code=merchant_code,
                merchant_order_id=auth_order_id_str,
                canonical_tenant_id=canonical_tenant_uuid_str,
                api_key=secret,
                event_id=event_id,
                provider_event_id=provider_event_id,
                expected_amount=authoritative_order_amount,
                duitku_s2s_verifier=duitku_s2s_verifier,
                db_conn_factory=db_conn_factory,
                s2s_worker_id=s2s_worker_id,
                s2s_lease_seconds=s2s_lease_seconds,
            )
        else:
            raise SettlementProvenanceError(
                f"Unsupported provider/verification_method combination: {norm_provider}/{norm_method}.",
                error_code="PROVENANCE_INVALID_VERIFICATION_METHOD",
            )

        # Deterministic verifier identity bound by the authority (never caller-supplied)
        bound_actor_principal = f"pg_webhook:{norm_provider.lower()}:{profile_id}"

        base_fields = {
            "actor_principal": bound_actor_principal,
            "canonical_tenant_id": str(uuid.UUID(str(authoritative_canonical_tenant_id).strip())),
            "credential_profile_id": profile_id,
            "currency": "IDR",
            "event_id": event_id,
            "order_id": str(authoritative_order_id).strip(),
            "provider": norm_provider,
            "provider_account_id": expected_acct,
            "provider_event_id": provider_event_id,
            "rail_type": rail_type,
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "settlement_status": "SETTLED",
            "sku_id": str(authoritative_sku_id).strip(),
            "verification_method": norm_method,
            "verified_amount": authoritative_order_amount,
            "verified_at_utc": str(verified_at_utc).strip(),
        }
        seal = _compute_capability_seal(base_fields, "VERIFIED_PG_WEBHOOK_ADAPTER")

        return VerifiedSettlementCapability(
            proof_source="VERIFIED_PG_WEBHOOK_ADAPTER",
            actor_principal=bound_actor_principal,
            canonical_tenant_id=base_fields["canonical_tenant_id"],
            credential_profile_id=profile_id,
            event_id=event_id,
            order_id=base_fields["order_id"],
            provider=norm_provider,
            provider_account_id=expected_acct,
            provider_event_id=provider_event_id,
            rail_type=rail_type,
            sku_id=base_fields["sku_id"],
            verification_method=norm_method,
            verified_amount=authoritative_order_amount,
            verified_at_utc=base_fields["verified_at_utc"],
            _mint_token=_BOUNDARY_MINT_TOKEN,
            _capability_seal=seal,
        )

    @staticmethod
    def _parse_utc_timestamp(val: Any) -> Optional[datetime]:
        if val is None:
            return None
        if isinstance(val, datetime):
            return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
        val_str = str(val).strip()
        if not val_str:
            return None
        try:
            dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    @staticmethod
    def _verify_duitku_s2s_once_with_idempotency(
        *,
        merchant_code: str,
        merchant_order_id: str,
        canonical_tenant_id: str,
        api_key: str,
        event_id: str,
        provider_event_id: str,
        expected_amount: int,
        duitku_s2s_verifier: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]],
        db_conn_factory: Optional[Any],
        s2s_worker_id: Optional[str] = None,
        s2s_lease_seconds: int = 15,
    ) -> None:
        """Enforces durable database-backed atomic claim/lease (`public.payment_events`)
        BEFORE invoking Duitku `transactionStatus` server-to-server verification.
        """
        if db_conn_factory is None:
            raise SettlementProvenanceError(
                "Durable database connection factory (db_conn_factory) is required for Duitku S2S claim/lease idempotency.",
                error_code="DATABASE_UNAVAILABLE",
                http_status=503,
            )
        if not callable(duitku_s2s_verifier):
            raise SettlementProvenanceError(
                "Duitku server-to-server transactionStatus verifier is required (live network calls disabled).",
                error_code="DUITKU_S2S_VERIFICATION_FAILED",
                http_status=503,
            )

        worker_id = str(s2s_worker_id or f"s2s_worker:{uuid.uuid4()}")
        now_utc = datetime.now(timezone.utc)
        lease_expires_utc = now_utc + timedelta(seconds=int(s2s_lease_seconds))
        claimed_attempt: int = 1
        was_factory = callable(db_conn_factory)
        conn: Any = None
        try:
            conn = db_conn_factory() if was_factory else db_conn_factory
            if hasattr(conn, "autocommit"):
                conn.autocommit = False
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO payment_events (
                    provider, event_id, provider_event_id, reference_id, order_id, tenant_id,
                    event_type, amount, status, record_classification,
                    s2s_verification_status, s2s_claimed_at, s2s_lease_expires_at,
                    s2s_claimed_by, s2s_attempt_count, created_at, updated_at
                ) VALUES (
                    'DUITKU', %s, %s, %s, %s, %s,
                    'PAYMENT_PENDING', %s, 'PROCESSING', 'STAGE3_SETTLEMENT',
                    'S2S_IN_FLIGHT', %s, %s,
                    %s, 1, %s, %s
                )
                ON CONFLICT DO NOTHING
                RETURNING event_id, s2s_attempt_count;
                """,
                (
                    event_id,
                    provider_event_id,
                    merchant_order_id,
                    merchant_order_id,
                    canonical_tenant_id,
                    expected_amount,
                    now_utc,
                    lease_expires_utc,
                    worker_id,
                    now_utc,
                    now_utc,
                ),
            )
            claimed_row = cur.fetchone()
            if claimed_row is not None:
                claimed_attempt = int(_extract_row_field(claimed_row, 1, "s2s_attempt_count") or 1)
                conn.commit()
            else:
                cur.execute(
                    """
                    SELECT
                        event_id, provider_event_id, order_id, tenant_id, amount,
                        status, s2s_verification_status, s2s_lease_expires_at,
                        s2s_claimed_by, s2s_attempt_count
                    FROM payment_events
                    WHERE provider = %s AND (event_id = %s OR provider_event_id = %s)
                    FOR UPDATE;
                    """,
                    ("DUITKU", event_id, provider_event_id),
                )
                rows = cur.fetchall() or []
                if not rows:
                    _safe_rollback_conn(conn)
                    raise SettlementProvenanceError(
                        "Failed to acquire or inspect Duitku S2S claim row.",
                        error_code="DATABASE_UNAVAILABLE",
                        http_status=503,
                    )
                for row in rows:
                    r_evt = str(_extract_row_field(row, 0, "event_id") or "").strip()
                    r_prov_evt = str(_extract_row_field(row, 1, "provider_event_id") or "").strip()
                    r_ord = str(_extract_row_field(row, 2, "order_id") or "").strip()
                    r_tenant = str(_extract_row_field(row, 3, "tenant_id") or "").strip()
                    r_amt_raw = _extract_row_field(row, 4, "amount")
                    r_status = str(_extract_row_field(row, 5, "status") or "").strip().upper()
                    r_s2s = str(_extract_row_field(row, 6, "s2s_verification_status") or "").strip().upper()
                    r_lease_exp = TrustedSettlementVerificationBoundary._parse_utc_timestamp(
                        _extract_row_field(row, 7, "s2s_lease_expires_at")
                    )
                    r_amt = int(Decimal(str(r_amt_raw))) if r_amt_raw is not None else expected_amount
                    if (
                        r_evt != event_id
                        or (r_prov_evt and r_prov_evt != provider_event_id)
                        or (r_ord and r_ord != merchant_order_id)
                        or (r_tenant and r_tenant != canonical_tenant_id)
                        or r_amt != expected_amount
                    ):
                        _safe_rollback_conn(conn)
                        raise SettlementProvenanceError(
                            "Conflicting Duitku payment event replay detected prior to S2S verification.",
                            error_code="CONFLICTING_PAYMENT_EVENT_REPLAY",
                            http_status=409,
                        )
                    if r_status in ("PROCESSED", "QUARANTINED_LATE_SETTLEMENT") or r_s2s == "S2S_VERIFIED":
                        _safe_rollback_conn(conn)
                        return
                    if (
                        r_status == "PROCESSING"
                        and r_s2s == "S2S_IN_FLIGHT"
                        and r_lease_exp is not None
                        and r_lease_exp > now_utc
                    ):
                        _safe_rollback_conn(conn)
                        raise SettlementProvenanceError(
                            "Duitku S2S verification is already in flight under an active worker lease.",
                            error_code="DUITKU_S2S_VERIFICATION_IN_FLIGHT",
                            http_status=409,
                        )
                cur.execute(
                    """
                    UPDATE payment_events
                    SET s2s_verification_status = 'S2S_IN_FLIGHT',
                        s2s_claimed_at = %s,
                        s2s_lease_expires_at = %s,
                        s2s_claimed_by = %s,
                        s2s_attempt_count = s2s_attempt_count + 1,
                        updated_at = %s
                    WHERE provider = 'DUITKU' AND event_id = %s AND status = 'PROCESSING'
                    RETURNING s2s_attempt_count;
                    """,
                    (now_utc, lease_expires_utc, worker_id, now_utc, event_id),
                )
                reclaimed = cur.fetchone()
                if reclaimed is None:
                    _safe_rollback_conn(conn)
                    raise SettlementProvenanceError(
                        "Failed to reclaim expired or retryable Duitku S2S lease.",
                        error_code="DUITKU_S2S_VERIFICATION_IN_FLIGHT",
                        http_status=409,
                    )
                claimed_attempt = int(_extract_row_field(reclaimed, 0, "s2s_attempt_count"))
                conn.commit()
        except SettlementProvenanceError:
            _safe_rollback_conn(conn)
            raise
        except Exception as exc:
            _safe_rollback_conn(conn)
            raise SettlementProvenanceError(
                f"Database unavailable during Duitku pre-S2S claim/lease: {exc}",
                error_code="DATABASE_UNAVAILABLE",
                http_status=503,
            ) from exc
        finally:
            _safe_close_conn(conn, was_factory)

        s2s_request_sig = hmac.new(
            api_key.encode("utf-8"),
            f"{merchant_code}{merchant_order_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().lower()
        s2s_request = {
            "merchantCode": merchant_code,
            "merchantOrderId": merchant_order_id,
            "signature": s2s_request_sig,
        }
        try:
            s2s_response = duitku_s2s_verifier(s2s_request)
            if not isinstance(s2s_response, Mapping):
                raise SettlementProvenanceError(
                    "Duitku S2S transactionStatus response must be a mapping.",
                    error_code="DUITKU_S2S_VERIFICATION_FAILED",
                    http_status=503,
                )
            s2s_status_code = str(s2s_response.get("statusCode") or "").strip()
            s2s_order_id = str(s2s_response.get("merchantOrderId") or "").strip()
            s2s_reference = str(s2s_response.get("reference") or "").strip()
            s2s_amt_raw = s2s_response.get("amount")
            if isinstance(s2s_amt_raw, bool):
                s2s_amt = -1
            elif isinstance(s2s_amt_raw, int):
                s2s_amt = s2s_amt_raw
            elif isinstance(s2s_amt_raw, str) and s2s_amt_raw.strip().isdigit():
                s2s_amt = int(s2s_amt_raw.strip())
            else:
                s2s_amt = -1

            if (
                s2s_status_code != "00"
                or not hmac.compare_digest(s2s_order_id, merchant_order_id)
                or not hmac.compare_digest(s2s_reference, provider_event_id)
                or s2s_amt != expected_amount
            ):
                raise SettlementProvenanceError(
                    f"Duitku S2S transactionStatus mismatch or non-settled status "
                    f"(statusCode='{s2s_status_code}', merchantOrderId='{s2s_order_id}', "
                    f"reference='{s2s_reference}', amount={s2s_amt_raw!r}).",
                    error_code="DUITKU_S2S_VERIFICATION_FAILED",
                    http_status=503,
                )
        except Exception as exc:
            err_conn: Any = None
            try:
                err_conn = db_conn_factory() if was_factory else db_conn_factory
                if hasattr(err_conn, "autocommit"):
                    err_conn.autocommit = False
                err_cur = err_conn.cursor()
                err_cur.execute(
                    """
                    UPDATE payment_events
                    SET s2s_verification_status = 'S2S_RETRYABLE_FAILURE',
                        s2s_last_error = %s,
                        updated_at = %s
                    WHERE provider = 'DUITKU'
                      AND event_id = %s
                      AND status = 'PROCESSING'
                      AND s2s_claimed_by = %s
                      AND s2s_attempt_count = %s;
                    """,
                    (str(exc), datetime.now(timezone.utc), event_id, worker_id, claimed_attempt),
                )
                err_conn.commit()
            except Exception:
                _safe_rollback_conn(err_conn)
            finally:
                _safe_close_conn(err_conn, was_factory)

            if isinstance(exc, SettlementProvenanceError):
                raise
            raise SettlementProvenanceError(
                f"Duitku transactionStatus S2S verification call failed: {exc}",
                error_code="DUITKU_S2S_VERIFICATION_FAILED",
                http_status=503,
            ) from exc

        # Phase 3: Fenced lease completion to S2S_VERIFIED
        fin_conn: Any = None
        try:
            fin_conn = db_conn_factory() if was_factory else db_conn_factory
            if hasattr(fin_conn, "autocommit"):
                fin_conn.autocommit = False
            fin_cur = fin_conn.cursor()
            finish_utc = datetime.now(timezone.utc)
            s2s_resp_json = json.dumps(dict(s2s_response), sort_keys=True, separators=(",", ":"))
            fin_cur.execute(
                """
                UPDATE payment_events
                SET s2s_verification_status = 'S2S_VERIFIED',
                    s2s_last_error = NULL,
                    s2s_verified_at = %s,
                    s2s_status_code = %s,
                    s2s_reference = %s,
                    s2s_response_payload = %s::jsonb,
                    updated_at = %s
                WHERE provider = 'DUITKU'
                  AND event_id = %s
                  AND status = 'PROCESSING'
                  AND s2s_verification_status = 'S2S_IN_FLIGHT'
                  AND s2s_claimed_by = %s
                  AND s2s_attempt_count = %s
                  AND s2s_lease_expires_at >= %s
                RETURNING event_id;
                """,
                (
                    finish_utc,
                    s2s_status_code,
                    s2s_reference,
                    s2s_resp_json,
                    finish_utc,
                    event_id,
                    worker_id,
                    claimed_attempt,
                    finish_utc,
                ),
            )
            if fin_cur.fetchone() is None:
                _safe_rollback_conn(fin_conn)
                raise SettlementProvenanceError(
                    "Stale Duitku S2S worker lease expired or was superseded by a newer worker claim.",
                    error_code="DUITKU_S2S_STALE_WORKER_FENCED",
                    http_status=409,
                )
            fin_conn.commit()
        except SettlementProvenanceError:
            _safe_rollback_conn(fin_conn)
            raise
        except Exception as exc:
            _safe_rollback_conn(fin_conn)
            raise SettlementProvenanceError(
                f"Database unavailable while finalizing Duitku S2S lease: {exc}",
                error_code="DATABASE_UNAVAILABLE",
                http_status=503,
            ) from exc
        finally:
            _safe_close_conn(fin_conn, was_factory)


# =============================================================================
# 3. Dedicated Ed25519 Provenance Keyrings (Private Signer vs Public Verifier)
# =============================================================================

@dataclass(frozen=True)
class ProvenanceSigningKeyRecord:
    """Ed25519 private signing key entry held ONLY by `ProvenanceSigningKeyring`."""

    key_id: str
    private_key_hex: str
    public_key_hex: str
    status: str  # "ACTIVE", "VERIFY_ONLY", "REVOKED"


@dataclass(frozen=True)
class ProvenancePublicKeyRecord:
    """Ed25519 public verification key entry held by `ProvenanceVerificationKeyring`.
    Contains ZERO private key material.
    """

    key_id: str
    public_key_hex: str
    status: str  # "ACTIVE", "VERIFY_ONLY", "REVOKED"


def _assert_no_legacy_provenance_env_aliases(environ: Mapping[str, str]) -> None:
    """Fails closed if any deprecated provenance environment variable alias is present."""
    for legacy_var in FORBIDDEN_LEGACY_PROVENANCE_ENV_ALIASES:
        if environ.get(legacy_var):
            raise PaymentConfigurationError(
                f"Deprecated environment variable '{legacy_var}' detected. "
                f"Use canonical '{ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING}' and "
                f"'{ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING}' with no fallback aliases."
            )


def _derive_ed25519_keypair_from_hex(seed_or_secret: str) -> Tuple[str, str]:
    """Parses a 64-character hex seed (32 bytes) or derives a deterministic 32-byte
    Ed25519 seed from high-entropy key material, returning `(private_key_hex, public_key_hex)`.
    """
    cleaned = seed_or_secret.strip()
    if len(cleaned) == 64:
        try:
            seed_bytes = bytes.fromhex(cleaned)
        except ValueError:
            seed_bytes = hashlib.sha256(cleaned.encode("utf-8")).digest()
    else:
        seed_bytes = hashlib.sha256(cleaned.encode("utf-8")).digest()

    priv = Ed25519PrivateKey.from_private_bytes(seed_bytes)
    pub = priv.public_key()
    priv_hex = seed_bytes.hex()
    pub_hex = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return priv_hex, pub_hex


class ProvenanceSigningKeyring:
    """Dedicated Ed25519 private signing keyring (`PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON`).

    Strictly isolated from `APP_MASTER_KEY` and `PAYMENT_INTERNAL_HMAC_KEYRING_JSON`.
    """

    def __init__(
        self,
        keys: Mapping[str, Mapping[str, Any]],
        forbidden_secrets: Optional[FrozenSet[str]] = None,
    ) -> None:
        if not keys:
            raise SettlementProvenanceError(
                "ProvenanceSigningKeyring requires at least one configured Ed25519 key.",
                error_code="EMPTY_PROVENANCE_KEYRING",
            )

        forbidden = forbidden_secrets or frozenset()
        self._keys: Dict[str, ProvenanceSigningKeyRecord] = {}
        self._active_key_id: Optional[str] = None

        for key_id, meta in keys.items():
            kid = str(key_id).strip()
            if not kid:
                raise SettlementProvenanceError(
                    "Provenance key_id must be non-empty.",
                    error_code="INVALID_PROVENANCE_KEY_ID",
                )
            raw_priv = str(meta.get("private_key_hex") or meta.get("secret") or "").strip()
            status = str(meta.get("status") or "").strip().upper()

            if len(raw_priv) < 32:
                raise SettlementProvenanceError(
                    f"Provenance private key '{kid}' must be at least 32 characters (32 bytes / 64 hex).",
                    error_code="WEAK_PROVENANCE_KEY_SECRET",
                )
            if status not in ALLOWED_KEY_STATUSES:
                raise SettlementProvenanceError(
                    f"Provenance key '{kid}' has invalid status '{status}'.",
                    error_code="INVALID_PROVENANCE_KEY_STATUS",
                )

            priv_hex, pub_hex = _derive_ed25519_keypair_from_hex(raw_priv)

            for bad_secret in forbidden:
                if bad_secret:
                    bad_priv_hex, _ = _derive_ed25519_keypair_from_hex(bad_secret)
                    if hmac.compare_digest(raw_priv, bad_secret) or hmac.compare_digest(priv_hex, bad_priv_hex):
                        raise SettlementProvenanceError(
                            f"Provenance key '{kid}' reuses a forbidden secret (APP_MASTER_KEY or internal HMAC key).",
                            error_code="PROVENANCE_KEY_SEPARATION_VIOLATION",
                        )

            self._keys[kid] = ProvenanceSigningKeyRecord(
                key_id=kid,
                private_key_hex=priv_hex,
                public_key_hex=pub_hex,
                status=status,
            )
            if status == "ACTIVE" and self._active_key_id is None:
                self._active_key_id = kid

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "ProvenanceSigningKeyring":
        env = environ if environ is not None else os.environ
        _assert_no_legacy_provenance_env_aliases(env)

        raw_json = env.get(ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING, "").strip()
        if not raw_json:
            raise SettlementProvenanceError(
                f"{ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING} is not configured.",
                error_code="MISSING_PROVENANCE_SIGNING_KEYRING",
            )
        try:
            parsed = json.loads(raw_json)
        except Exception as exc:
            raise SettlementProvenanceError(
                f"Invalid JSON in {ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING}.",
                error_code="INVALID_PROVENANCE_KEYRING_JSON",
            ) from exc

        forbidden: List[str] = []
        master_key = env.get(ENV_APP_MASTER_KEY, "").strip()
        if master_key:
            forbidden.append(master_key)
        internal_json = env.get(ENV_INTERNAL_HMAC_KEYRING, "").strip()
        if internal_json:
            try:
                internal_map = json.loads(internal_json)
                if isinstance(internal_map, Mapping):
                    for v in internal_map.values():
                        if isinstance(v, Mapping) and v.get("secret"):
                            forbidden.append(str(v["secret"]))
            except Exception:
                pass

        return cls(parsed, forbidden_secrets=frozenset(forbidden))

    def get_for_signing(self, key_id: Optional[str] = None) -> ProvenanceSigningKeyRecord:
        target_id = key_id or self._active_key_id
        if not target_id or target_id not in self._keys:
            raise SettlementProvenanceError(
                f"Unknown provenance signing key ID '{target_id}'.",
                error_code="UNKNOWN_PROVENANCE_KEY_ID",
            )
        record = self._keys[target_id]
        if record.status == "REVOKED":
            raise SettlementProvenanceError(
                f"Provenance key '{target_id}' is REVOKED and cannot sign.",
                error_code="PROVENANCE_KEY_REVOKED",
            )
        if record.status != "ACTIVE":
            raise SettlementProvenanceError(
                f"Provenance key '{target_id}' has status '{record.status}'; only ACTIVE keys can sign new provenance.",
                error_code="PROVENANCE_KEY_NOT_ACTIVE",
            )
        return record

    def export_public_verification_keyring(self) -> "ProvenanceVerificationKeyring":
        """Exports a public-key-only `ProvenanceVerificationKeyring` containing zero private keys."""
        pub_map = {
            kid: {"public_key_hex": rec.public_key_hex, "status": rec.status}
            for kid, rec in self._keys.items()
        }
        return ProvenanceVerificationKeyring(pub_map)


class ProvenanceVerificationKeyring:
    """Public-key-only Ed25519 verification keyring (`PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON`).

    Rejects any configuration containing private keys or symmetric secrets so that
    verifier processes never hold signing material.
    """

    def __init__(self, public_keys: Mapping[str, Mapping[str, Any]]) -> None:
        if not public_keys:
            raise SettlementProvenanceError(
                "ProvenanceVerificationKeyring requires at least one configured Ed25519 public key.",
                error_code="EMPTY_PROVENANCE_KEYRING",
            )
        self._keys: Dict[str, ProvenancePublicKeyRecord] = {}

        for key_id, meta in public_keys.items():
            kid = str(key_id).strip()
            if not kid:
                raise SettlementProvenanceError(
                    "Provenance public key_id must be non-empty.",
                    error_code="INVALID_PROVENANCE_KEY_ID",
                )
            if "private_key_hex" in meta or "secret" in meta or "private_key" in meta:
                raise SettlementProvenanceError(
                    f"ProvenanceVerificationKeyring key '{kid}' must contain ONLY public_key_hex; "
                    "private keys and symmetric secrets are forbidden in the verifier keyring.",
                    error_code="PROVENANCE_VERIFIER_PRIVATE_KEY_FORBIDDEN",
                )
            pub_hex = str(meta.get("public_key_hex") or "").strip().lower()
            status = str(meta.get("status") or "").strip().upper()
            if len(pub_hex) != 64:
                raise SettlementProvenanceError(
                    f"Provenance Ed25519 public_key_hex for '{kid}' must be 64 hex chars (32 bytes).",
                    error_code="INVALID_PROVENANCE_PUBLIC_KEY",
                )
            try:
                pub_bytes = bytes.fromhex(pub_hex)
                Ed25519PublicKey.from_public_bytes(pub_bytes)
            except Exception as exc:
                raise SettlementProvenanceError(
                    f"Invalid Ed25519 public key bytes for '{kid}'.",
                    error_code="INVALID_PROVENANCE_PUBLIC_KEY",
                ) from exc

            if status not in ALLOWED_KEY_STATUSES:
                raise SettlementProvenanceError(
                    f"Provenance public key '{kid}' has invalid status '{status}'.",
                    error_code="INVALID_PROVENANCE_KEY_STATUS",
                )
            self._keys[kid] = ProvenancePublicKeyRecord(
                key_id=kid,
                public_key_hex=pub_hex,
                status=status,
            )

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "ProvenanceVerificationKeyring":
        env = environ if environ is not None else os.environ
        _assert_no_legacy_provenance_env_aliases(env)

        raw_json = env.get(ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING, "").strip()
        if not raw_json:
            raise SettlementProvenanceError(
                f"{ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING} is not configured.",
                error_code="MISSING_PROVENANCE_VERIFY_KEYRING",
            )
        try:
            parsed = json.loads(raw_json)
        except Exception as exc:
            raise SettlementProvenanceError(
                f"Invalid JSON in {ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING}.",
                error_code="INVALID_PROVENANCE_KEYRING_JSON",
            ) from exc
        return cls(parsed)

    def get_for_verification(self, key_id: str) -> ProvenancePublicKeyRecord:
        kid = str(key_id or "").strip()
        if not kid or kid not in self._keys:
            raise SettlementProvenanceError(
                f"Unknown provenance verification key ID '{kid}'.",
                error_code="UNKNOWN_PROVENANCE_KEY_ID",
            )
        record = self._keys[kid]
        if record.status == "REVOKED":
            raise SettlementProvenanceError(
                f"Provenance key '{kid}' is REVOKED and cannot verify provenance.",
                error_code="PROVENANCE_KEY_REVOKED",
            )
        return record


# Compatibility alias for tests initializing ProvenanceSigningKeyring
ProvenanceKeyring = ProvenanceSigningKeyring


# =============================================================================
# 4. 17-Field Contract Validator
# =============================================================================

def validate_provenance_17_field_contract(fields: Mapping[str, Any]) -> Dict[str, Any]:
    """Validates that `fields` contains the exact 17 approved provenance fields
    and that every field satisfies its type and domain invariants.
    """
    if not isinstance(fields, Mapping):
        raise SettlementProvenanceError(
            "Provenance fields payload must be a mapping.",
            error_code="PROVENANCE_INVALID_PAYLOAD",
        )

    actual_keys = frozenset(fields.keys())
    if actual_keys != PROVENANCE_CONTRACT_FIELD_SET or len(fields) != 17:
        missing = sorted(PROVENANCE_CONTRACT_FIELD_SET - actual_keys)
        extra = sorted(actual_keys - PROVENANCE_CONTRACT_FIELD_SET)
        raise SettlementProvenanceError(
            f"Provenance 17-field contract violation: expected exact 17 fields, "
            f"got {len(fields)} (missing={missing}, extra={extra}).",
            error_code="PROVENANCE_FIELD_CONTRACT_VIOLATION",
        )

    schema_version = fields.get("schema_version")
    if schema_version != PROVENANCE_SCHEMA_VERSION:
        raise SettlementProvenanceError(
            f"Unsupported provenance schema_version '{schema_version}'; expected '{PROVENANCE_SCHEMA_VERSION}'.",
            error_code="PROVENANCE_SCHEMA_VERSION_MISMATCH",
        )

    currency = fields.get("currency")
    if currency != "IDR":
        raise SettlementProvenanceError(
            f"Unsupported provenance currency '{currency}'; expected 'IDR'.",
            error_code="PROVENANCE_INVALID_CURRENCY",
        )

    settlement_status = fields.get("settlement_status")
    if settlement_status != "SETTLED":
        raise SettlementProvenanceError(
            f"Invalid provenance settlement_status '{settlement_status}'; expected 'SETTLED'.",
            error_code="PROVENANCE_INVALID_SETTLEMENT_STATUS",
        )

    raw_amount = fields.get("verified_amount")
    if isinstance(raw_amount, bool) or not isinstance(raw_amount, int) or raw_amount <= 0:
        raise SettlementProvenanceError(
            f"verified_amount must be a positive integer IDR amount, got {raw_amount!r}.",
            error_code="PROVENANCE_INVALID_AMOUNT",
        )

    canonical_tenant_id = str(fields.get("canonical_tenant_id") or "").strip()
    try:
        parsed_uuid = uuid.UUID(canonical_tenant_id)
        canonical_tenant_id = str(parsed_uuid)
    except Exception as exc:
        raise SettlementProvenanceError(
            f"canonical_tenant_id must be a valid canonical UUID, got '{canonical_tenant_id}'.",
            error_code="PROVENANCE_INVALID_CANONICAL_TENANT_ID",
        ) from exc

    rail_type = str(fields.get("rail_type") or "").strip()
    if rail_type in LOCKED_RAIL_TYPES:
        raise SettlementProvenanceError(
            f"Direct Tenant Rail ('{rail_type}') is DISABLED (EXPERIMENTAL / PENDING_REVIEW).",
            error_code="DIRECT_TENANT_RAIL_LOCKED",
            http_status=403,
        )
    if rail_type not in ALLOWED_RAIL_TYPES:
        raise SettlementProvenanceError(
            f"Invalid rail_type '{rail_type}'; allowed={sorted(ALLOWED_RAIL_TYPES)}.",
            error_code="PROVENANCE_INVALID_RAIL_TYPE",
        )

    provider = str(fields.get("provider") or "").strip().upper()
    if provider in LOCKED_UNAUTHORIZED_PROVIDERS or provider not in ALLOWED_PROVIDERS:
        raise SettlementProvenanceError(
            f"Invalid provider '{provider}'; allowed={sorted(ALLOWED_PROVIDERS)}.",
            error_code="PROVENANCE_INVALID_PROVIDER",
        )
    if rail_type == "NATIVE_PG" and provider not in STAGE3_NATIVE_PG_ALLOWED_PROVIDERS:
        raise SettlementProvenanceError(
            f"Provider '{provider}' is not permitted on Stage 3 NATIVE_PG rail; "
            f"allowed={sorted(STAGE3_NATIVE_PG_ALLOWED_PROVIDERS)}.",
            error_code="PROVENANCE_INVALID_PROVIDER",
        )

    verification_method = str(fields.get("verification_method") or "").strip()
    if (
        verification_method in LOCKED_UNAUTHORIZED_VERIFICATION_METHODS
        or verification_method not in ALLOWED_VERIFICATION_METHODS
    ):
        raise SettlementProvenanceError(
            f"Invalid verification_method '{verification_method}'.",
            error_code="PROVENANCE_INVALID_VERIFICATION_METHOD",
        )
    if rail_type == "NATIVE_PG" and verification_method not in STAGE3_NATIVE_PG_ALLOWED_VERIFICATION_METHODS:
        raise SettlementProvenanceError(
            f"Verification method '{verification_method}' is not permitted on Stage 3 NATIVE_PG rail.",
            error_code="PROVENANCE_INVALID_VERIFICATION_METHOD",
        )

    for str_field in (
        "actor_principal",
        "credential_profile_id",
        "event_id",
        "order_id",
        "prov_key_id",
        "provider_account_id",
        "provider_event_id",
        "sku_id",
        "verified_at_utc",
    ):
        val = fields.get(str_field)
        if not isinstance(val, str) or not val.strip():
            raise SettlementProvenanceError(
                f"Provenance field '{str_field}' must be a non-empty string.",
                error_code=f"PROVENANCE_EMPTY_{str_field.upper()}",
            )

    verified_at_utc = str(fields["verified_at_utc"]).strip()
    if not verified_at_utc.endswith("Z") and "+00:00" not in verified_at_utc:
        raise SettlementProvenanceError(
            f"verified_at_utc must be an ISO-8601 UTC timestamp, got '{verified_at_utc}'.",
            error_code="PROVENANCE_INVALID_TIMESTAMP",
        )
    try:
        datetime.fromisoformat(verified_at_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception as exc:
        raise SettlementProvenanceError(
            f"Malformed verified_at_utc ISO-8601 timestamp '{verified_at_utc}'.",
            error_code="PROVENANCE_INVALID_TIMESTAMP",
        ) from exc

    return {
        "actor_principal": str(fields["actor_principal"]).strip(),
        "canonical_tenant_id": canonical_tenant_id,
        "credential_profile_id": str(fields["credential_profile_id"]).strip(),
        "currency": "IDR",
        "event_id": str(fields["event_id"]).strip(),
        "order_id": str(fields["order_id"]).strip(),
        "prov_key_id": str(fields["prov_key_id"]).strip(),
        "provider": provider,
        "provider_account_id": str(fields["provider_account_id"]).strip(),
        "provider_event_id": str(fields["provider_event_id"]).strip(),
        "rail_type": rail_type,
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "settlement_status": "SETTLED",
        "sku_id": str(fields["sku_id"]).strip(),
        "verification_method": verification_method,
        "verified_amount": int(raw_amount),
        "verified_at_utc": verified_at_utc,
    }


# =============================================================================
# 5. Ed25519 Provenance Signer & Public-Key-Only Verifier
# =============================================================================

class ProvenanceSigner:
    """Dedicated Ed25519 signing authority.

    Only accepts a `VerifiedSettlementCapability` issued by `TrustedSettlementVerificationBoundary`.
    """

    def __init__(self, keyring: ProvenanceSigningKeyring) -> None:
        if not isinstance(keyring, ProvenanceSigningKeyring):
            raise SettlementProvenanceError(
                "ProvenanceSigner requires a ProvenanceSigningKeyring instance.",
                error_code="INVALID_PROVENANCE_SIGNER_KEYRING",
            )
        self._keyring = keyring

    def sign_verified_settlement(
        self,
        capability: VerifiedSettlementCapability,
        *,
        key_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Signs the 17-field RFC 8785 canonical JSON payload with an ACTIVE Ed25519 private key."""
        if not isinstance(capability, VerifiedSettlementCapability):
            raise SettlementProvenanceError(
                "ProvenanceSigner.sign_verified_settlement requires a VerifiedSettlementCapability "
                "minted by TrustedSettlementVerificationBoundary.",
                error_code="UNTRUSTED_PROVENANCE_CALLER",
            )
        if capability.rail_type in LOCKED_RAIL_TYPES:
            raise SettlementProvenanceError(
                f"Direct Tenant Rail ('{capability.rail_type}') signing is locked.",
                error_code="DIRECT_TENANT_RAIL_SIGNING_LOCKED",
                http_status=403,
            )

        key_record = self._keyring.get_for_signing(key_id)
        fields_17 = capability.to_unsigned_17_field_dict(prov_key_id=key_record.key_id)
        canonical_bytes = canonicalize_rfc8785(fields_17)

        priv_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_record.private_key_hex))
        signature_hex = priv_key.sign(canonical_bytes).hex()

        return {
            "fields": fields_17,
            "signature": signature_hex,
            "algorithm": PROVENANCE_SIGNATURE_ALGORITHM,
        }


class ProvenanceVerifier:
    """Public-key-only Ed25519 provenance verifier for fulfillment and administrative gates.

    Operates exclusively on `ProvenanceVerificationKeyring` (Ed25519 public keys).
    """

    def __init__(
        self,
        keyring: "ProvenanceVerificationKeyring | ProvenanceSigningKeyring",
    ) -> None:
        if isinstance(keyring, ProvenanceSigningKeyring):
            # Automatically strip private keys so ProvenanceVerifier only stores public keys
            self._keyring = keyring.export_public_verification_keyring()
        elif isinstance(keyring, ProvenanceVerificationKeyring):
            self._keyring = keyring
        else:
            raise SettlementProvenanceError(
                "ProvenanceVerifier requires a ProvenanceVerificationKeyring.",
                error_code="INVALID_PROVENANCE_VERIFIER_KEYRING",
            )

    @property
    def verification_keyring(self) -> ProvenanceVerificationKeyring:
        return self._keyring

    def verify_provenance_envelope(
        self,
        envelope: Mapping[str, Any],
        *,
        expected_order_id: Optional[str] = None,
        expected_canonical_tenant_id: Optional[str] = None,
        expected_amount: Optional[int] = None,
        expected_sku_id: Optional[str] = None,
        required_rail_type: Optional[str] = "NATIVE_PG",
    ) -> Dict[str, Any]:
        """Verifies the 17-field contract, RFC 8785 canonical serialization, Ed25519 signature,
        and order-level relational bindings. Fails closed on any mismatch.
        """
        if not isinstance(envelope, Mapping):
            raise SettlementProvenanceError(
                "Provenance envelope must be a mapping.",
                error_code="PROVENANCE_MISSING_ENVELOPE",
            )

        raw_fields = envelope.get("fields")
        provided_sig = str(envelope.get("signature") or "").strip().lower()
        if not isinstance(raw_fields, Mapping) or not provided_sig:
            raise SettlementProvenanceError(
                "Provenance envelope must contain 'fields' mapping and 'signature'.",
                error_code="PROVENANCE_MALFORMED_ENVELOPE",
            )

        validated_fields = validate_provenance_17_field_contract(raw_fields)
        prov_key_id = validated_fields["prov_key_id"]

        key_record = self._keyring.get_for_verification(prov_key_id)
        canonical_bytes = canonicalize_rfc8785(validated_fields)

        if len(provided_sig) != 128:
            raise SettlementProvenanceError(
                "Provenance Ed25519 signature must be 128 hex characters (64 bytes).",
                error_code="PROVENANCE_SIGNATURE_MISMATCH",
            )
        try:
            sig_bytes = bytes.fromhex(provided_sig)
        except ValueError as exc:
            raise SettlementProvenanceError(
                "Provenance Ed25519 signature is not valid hexadecimal.",
                error_code="PROVENANCE_SIGNATURE_MISMATCH",
            ) from exc

        pub_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_record.public_key_hex))
        try:
            pub_key.verify(sig_bytes, canonical_bytes)
        except InvalidSignature as exc:
            raise SettlementProvenanceError(
                "Provenance Ed25519 cryptographic signature verification failed (tampered fields or wrong key).",
                error_code="PROVENANCE_SIGNATURE_MISMATCH",
            ) from exc

        if expected_order_id is not None and not hmac.compare_digest(
            validated_fields["order_id"], str(expected_order_id)
        ):
            raise SettlementProvenanceError(
                f"Provenance order_id '{validated_fields['order_id']}' does not match order '{expected_order_id}'.",
                error_code="PROVENANCE_ORDER_MISMATCH",
            )

        if expected_canonical_tenant_id is not None and not hmac.compare_digest(
            validated_fields["canonical_tenant_id"], str(expected_canonical_tenant_id)
        ):
            raise SettlementProvenanceError(
                f"Provenance canonical_tenant_id '{validated_fields['canonical_tenant_id']}' "
                f"does not match order tenant '{expected_canonical_tenant_id}'.",
                error_code="PROVENANCE_TENANT_MISMATCH",
            )

        if expected_amount is not None and validated_fields["verified_amount"] != int(expected_amount):
            raise SettlementProvenanceError(
                f"Provenance verified_amount ({validated_fields['verified_amount']}) "
                f"does not match expected order gross_amount ({expected_amount}).",
                error_code="PROVENANCE_AMOUNT_MISMATCH",
            )

        if expected_sku_id is not None and not hmac.compare_digest(
            validated_fields["sku_id"], str(expected_sku_id)
        ):
            raise SettlementProvenanceError(
                f"Provenance sku_id '{validated_fields['sku_id']}' does not match order sku_id '{expected_sku_id}'.",
                error_code="PROVENANCE_SKU_MISMATCH",
            )

        if required_rail_type is not None and validated_fields["rail_type"] != required_rail_type:
            raise SettlementProvenanceError(
                f"Provenance rail_type '{validated_fields['rail_type']}' does not satisfy required rail '{required_rail_type}'.",
                error_code="PROVENANCE_RAIL_MISMATCH",
            )

        return validated_fields


# =============================================================================
# 6. Atomic Verified Settlement Transaction Gatekeeper (`payment_events` Writer)
# =============================================================================

def _safe_rollback_conn(conn: Any) -> None:
    try:
        if conn is not None and hasattr(conn, "rollback"):
            conn.rollback()
    except Exception:
        pass


def _safe_close_conn(conn: Any, was_factory_call: bool) -> None:
    try:
        if was_factory_call and conn is not None and hasattr(conn, "close") and not getattr(conn, "_keep_open", False):
            conn.close()
    except Exception:
        pass


def _extract_row_field(row: Any, idx: int, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[idx]


def commit_verified_settlement_transaction(
    capability: VerifiedSettlementCapability,
    signer: ProvenanceSigner,
    verifier: ProvenanceVerifier,
    raw_webhook_payload: Mapping[str, Any],
    db_conn_factory: Any,
    *,
    key_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Sole authorized database write gatekeeper for Stage 3 settlement persistence.

    Enforces:
    1. Pre-insert Ed25519 private signing (`ProvenanceSigner`) and public-key verification
       (`ProvenanceVerifier`) over the 17-field RFC 8785 canonical provenance contract.
    2. Single atomic transaction across `orders`, `payment_events`, and `financial_ledger`.
    3. Composite idempotency and conflict detection on `(provider, event_id)` and
       `(provider, provider_event_id)`.
    4. CTO Decision #4 Late Settlement Quarantine (`QUARANTINED_LATE_SETTLEMENT`) when order
       status is `EXPIRED`, `CANCELLED`, or `FAILED` (zero order mutation, zero ledger row,
       zero fulfillment/CAPI).
    5. Financial ledger accounting with `fee_amount = NULL`, `net_amount = NULL`,
       `transaction_status = 'SETTLED'`, and `reconciliation_status = 'PENDING_RECONCILIATION'`.
    6. Durable Stage 4 outbox state (`fulfillment_status = 'PENDING_STAGE4_VERIFICATION'`)
       with strictly zero Stage 4 fulfillment or CAPI side effects.
    """
    if not isinstance(capability, VerifiedSettlementCapability):
        raise SettlementProvenanceError(
            "commit_verified_settlement_transaction requires a VerifiedSettlementCapability.",
            error_code="UNTRUSTED_PROVENANCE_CALLER",
            http_status=403,
        )
    if not isinstance(signer, ProvenanceSigner) or not isinstance(verifier, ProvenanceVerifier):
        raise SettlementProvenanceError(
            "commit_verified_settlement_transaction requires valid ProvenanceSigner and ProvenanceVerifier.",
            error_code="INVALID_PROVENANCE_SIGNER_KEYRING",
            http_status=500,
        )
    if not isinstance(raw_webhook_payload, Mapping):
        raise SettlementProvenanceError(
            "raw_webhook_payload must be a mapping.",
            error_code="PROVENANCE_INVALID_PAYLOAD",
            http_status=400,
        )

    provenance_envelope = signer.sign_verified_settlement(capability, key_id=key_id)
    verified_fields = verifier.verify_provenance_envelope(
        provenance_envelope,
        expected_order_id=capability.order_id,
        expected_canonical_tenant_id=capability.canonical_tenant_id,
        expected_amount=capability.verified_amount,
        expected_sku_id=capability.sku_id,
        required_rail_type="NATIVE_PG",
    )

    if verified_fields["sku_id"] == "TEST-PENNY-1500" and verified_fields["verified_amount"] != 1500:
        raise SettlementProvenanceError(
            "TEST-PENNY-1500 requires exact verified_amount of 1500 IDR.",
            error_code="PROVENANCE_AMOUNT_MISMATCH",
            http_status=422,
        )

    raw_payload_dict = dict(raw_webhook_payload)
    structured_payload_dict = dict(raw_webhook_payload)
    structured_payload_dict["_provenance"] = provenance_envelope
    try:
        payload_json = json.dumps(structured_payload_dict, sort_keys=True, separators=(",", ":"))
        raw_payload_json = json.dumps(raw_payload_dict, sort_keys=True, separators=(",", ":"))
    except Exception as exc:
        raise SettlementProvenanceError(
            f"Webhook payload is not JSON-serializable: {exc}",
            error_code="PROVENANCE_INVALID_PAYLOAD",
            http_status=400,
        ) from exc

    if db_conn_factory is None:
        raise SettlementProvenanceError(
            "Database connection factory is required for settlement persistence.",
            error_code="DATABASE_UNAVAILABLE",
            http_status=503,
        )

    conn: Any = None
    try:
        conn = db_conn_factory() if callable(db_conn_factory) else db_conn_factory
        if conn is None:
            raise RuntimeError("db_conn_factory returned None")
        if hasattr(conn, "autocommit"):
            conn.autocommit = False
    except SettlementProvenanceError:
        raise
    except Exception as exc:
        raise SettlementProvenanceError(
            f"Database unavailable when opening settlement transaction: {exc}",
            error_code="DATABASE_UNAVAILABLE",
            http_status=503,
        ) from exc
    provider = verified_fields["provider"]
    event_id = verified_fields["event_id"]
    provider_event_id = verified_fields["provider_event_id"]
    order_id = verified_fields["order_id"]
    canonical_tenant_id = verified_fields["canonical_tenant_id"]
    verified_amount = verified_fields["verified_amount"]
    sku_id = verified_fields["sku_id"]
    now_utc = datetime.now(timezone.utc)

    try:
        cur = conn.cursor()

        # Step A: Row-level lock & canonical tenant join on orders
        cur.execute(
            """
            SELECT
                o.id,
                o.tenant_id,
                t.id::text AS canonical_tenant_id,
                COALESCE(o.gross_amount, o.amount, 0) AS gross_amount,
                COALESCE(NULLIF(TRIM(o.sku_id), ''), NULLIF(TRIM(o.product_id), ''), '') AS sku_id,
                COALESCE(UPPER(TRIM(o.status)), '') AS status,
                COALESCE(UPPER(TRIM(o.payment_status)), '') AS payment_status
            FROM orders o
            INNER JOIN tenants t ON o.tenant_id = t.id::text
            WHERE o.id = %s
            FOR UPDATE OF o;
            """,
            (order_id,),
        )
        order_row = cur.fetchone()

        # Step B: Composite idempotency & conflict detection on (provider, event_id) and (provider, provider_event_id)
        cur.execute(
            """
            SELECT event_id, provider_event_id, order_id, tenant_id, amount, status, payload, s2s_verification_status
            FROM payment_events
            WHERE provider = %s
              AND (event_id = %s OR provider_event_id = %s)
            FOR UPDATE;
            """,
            (provider, event_id, provider_event_id),
        )
        existing_events = cur.fetchall() or []
        existing_is_processing = False

        for ev_row in existing_events:
            ev_id = str(_extract_row_field(ev_row, 0, "event_id") or "").strip()
            ev_prov_id = str(_extract_row_field(ev_row, 1, "provider_event_id") or "").strip()
            ev_order_id = str(_extract_row_field(ev_row, 2, "order_id") or "").strip()
            ev_tenant_id = str(_extract_row_field(ev_row, 3, "tenant_id") or "").strip()
            ev_amt_raw = _extract_row_field(ev_row, 4, "amount")
            ev_status = str(_extract_row_field(ev_row, 5, "status") or "").strip().upper()
            ev_payload_raw = _extract_row_field(ev_row, 6, "payload")
            ev_s2s_status = str(_extract_row_field(ev_row, 7, "s2s_verification_status") or "").strip().upper()
            ev_amt = int(Decimal(str(ev_amt_raw))) if ev_amt_raw is not None else verified_amount
            ev_prov_acct = ""
            ev_sku = ""
            try:
                ev_payload_obj = json.loads(ev_payload_raw) if isinstance(ev_payload_raw, str) else ev_payload_raw
                if isinstance(ev_payload_obj, Mapping):
                    prov_fields = (ev_payload_obj.get("_provenance") or {}).get("fields") or {}
                    if isinstance(prov_fields, Mapping):
                        ev_prov_acct = str(prov_fields.get("provider_account_id") or "").strip()
                        ev_sku = str(prov_fields.get("sku_id") or "").strip()
            except Exception:
                pass

            if (
                ev_id != event_id
                or (ev_prov_id and ev_prov_id != provider_event_id)
                or (ev_order_id and ev_order_id != order_id)
                or (ev_tenant_id and ev_tenant_id != canonical_tenant_id)
                or ev_amt != verified_amount
                or (ev_prov_acct and ev_prov_acct != verified_fields["provider_account_id"])
                or (ev_sku and ev_sku != sku_id)
            ):
                _safe_rollback_conn(conn)
                raise SettlementProvenanceError(
                    "Conflicting payment event replay detected on composite key (provider, event_id) / (provider, provider_event_id).",
                    error_code="CONFLICTING_PAYMENT_EVENT_REPLAY",
                    http_status=409,
                )

            if ev_status == "PROCESSED":
                _safe_rollback_conn(conn)
                return {
                    "status": "ALREADY_PROCESSED",
                    "http_status": 200,
                    "idempotent": True,
                    "order_id": order_id,
                    "canonical_tenant_id": canonical_tenant_id,
                    "provider": provider,
                    "event_id": event_id,
                    "provider_event_id": provider_event_id,
                    "verified_amount": verified_amount,
                    "fulfillment_triggered": False,
                    "capi_triggered": False,
                }
            if ev_status == "QUARANTINED_LATE_SETTLEMENT":
                _safe_rollback_conn(conn)
                return {
                    "status": "QUARANTINED_LATE_SETTLEMENT",
                    "http_status": 200,
                    "idempotent": True,
                    "message": "Late settlement quarantined successfully for manual review",
                    "order_id": order_id,
                    "canonical_tenant_id": canonical_tenant_id,
                    "provider": provider,
                    "event_id": event_id,
                    "provider_event_id": provider_event_id,
                    "verified_amount": verified_amount,
                    "fulfillment_triggered": False,
                    "capi_triggered": False,
                }
            if ev_status == "PROCESSING":
                if provider == "DUITKU" and ev_s2s_status != "S2S_VERIFIED":
                    _safe_rollback_conn(conn)
                    raise SettlementProvenanceError(
                        f"Duitku S2S verification status '{ev_s2s_status}' is not S2S_VERIFIED.",
                        error_code="DUITKU_S2S_VERIFICATION_FAILED",
                        http_status=503,
                    )
                existing_is_processing = True

        if order_row is None:
            _safe_rollback_conn(conn)
            raise SettlementProvenanceError(
                f"Order '{order_id}' not found or not bound to a valid canonical tenant.",
                error_code="ORDER_NOT_FOUND",
                http_status=404,
            )
        db_ord_id = str(_extract_row_field(order_row, 0, "id") or "").strip()
        db_tenant_id = str(_extract_row_field(order_row, 1, "tenant_id") or "").strip()
        db_canonical_tenant = str(_extract_row_field(order_row, 2, "canonical_tenant_id") or "").strip()
        db_gross_raw = _extract_row_field(order_row, 3, "gross_amount")
        db_sku = str(_extract_row_field(order_row, 4, "sku_id") or "").strip()
        db_status = str(_extract_row_field(order_row, 5, "status") or "").strip().upper()
        db_pay_status = str(_extract_row_field(order_row, 6, "payment_status") or "").strip().upper()
        db_gross_amt = int(Decimal(str(db_gross_raw))) if db_gross_raw is not None else 0

        if not hmac.compare_digest(db_ord_id, order_id):
            _safe_rollback_conn(conn)
            raise SettlementProvenanceError(
                f"Order ID mismatch in DB lock ('{db_ord_id}' vs '{order_id}').",
                error_code="PROVENANCE_ORDER_MISMATCH",
                http_status=422,
            )
        if not hmac.compare_digest(db_canonical_tenant, canonical_tenant_id) or not hmac.compare_digest(
            db_tenant_id, canonical_tenant_id
        ):
            _safe_rollback_conn(conn)
            raise SettlementProvenanceError(
                f"Order tenant mismatch ('{db_tenant_id}' vs '{canonical_tenant_id}').",
                error_code="ORDER_TENANT_MISMATCH",
                http_status=403,
            )
        if db_gross_amt != verified_amount:
            _safe_rollback_conn(conn)
            raise SettlementProvenanceError(
                f"Order gross_amount ({db_gross_amt}) does not match verified_amount ({verified_amount}).",
                error_code="PROVENANCE_AMOUNT_MISMATCH",
                http_status=422,
            )
        if db_sku and not hmac.compare_digest(db_sku, sku_id):
            _safe_rollback_conn(conn)
            raise SettlementProvenanceError(
                f"Order sku_id ('{db_sku}') does not match provenance sku_id ('{sku_id}').",
                error_code="PROVENANCE_SKU_MISMATCH",
                http_status=422,
            )

        # CTO Decision #4: Late settlement on EXPIRED / CANCELLED / FAILED orders -> quarantine
        late_states = ("EXPIRED", "CANCELLED", "CANCELED", "FAILED")
        if db_status in late_states or db_pay_status in late_states:
            if existing_is_processing:
                cur.execute(
                    """
                    UPDATE payment_events
                    SET event_type = 'PAYMENT_SETTLED_LATE',
                        payload = %s::jsonb,
                        raw_payload = %s::jsonb,
                        status = 'QUARANTINED_LATE_SETTLEMENT',
                        processed_at = %s,
                        updated_at = %s
                    WHERE provider = %s AND event_id = %s AND status = 'PROCESSING';
                    """,
                    (payload_json, raw_payload_json, now_utc, now_utc, provider, event_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO payment_events (
                        provider, event_id, reference_id, event_type, payload, status,
                        record_classification, processed_at, created_at, updated_at,
                        order_id, provider_event_id, amount, raw_payload, tenant_id
                    ) VALUES (
                        %s, %s, %s, 'PAYMENT_SETTLED_LATE', %s::jsonb, 'QUARANTINED_LATE_SETTLEMENT',
                        'STAGE3_SETTLEMENT', %s, %s, %s,
                        %s, %s, %s, %s::jsonb, %s
                    )
                    ON CONFLICT (provider, event_id) DO NOTHING;
                    """,
                    (
                        provider,
                        event_id,
                        order_id,
                        payload_json,
                        now_utc,
                        now_utc,
                        now_utc,
                        order_id,
                        provider_event_id,
                        verified_amount,
                        raw_payload_json,
                        canonical_tenant_id,
                    ),
                )
            conn.commit()
            return {
                "status": "QUARANTINED_LATE_SETTLEMENT",
                "http_status": 200,
                "idempotent": False,
                "message": "Late settlement quarantined successfully for manual review",
                "order_id": order_id,
                "canonical_tenant_id": canonical_tenant_id,
                "provider": provider,
                "event_id": event_id,
                "provider_event_id": provider_event_id,
                "verified_amount": verified_amount,
                "provenance": provenance_envelope,
                "fulfillment_triggered": False,
                "capi_triggered": False,
            }
        if db_status in ("PAID", "SETTLED", "COMPLETED") or db_pay_status in ("PAID", "SETTLED", "COMPLETED"):
            _safe_rollback_conn(conn)
            return {
                "status": "ALREADY_PROCESSED",
                "http_status": 200,
                "idempotent": True,
                "order_id": order_id,
                "canonical_tenant_id": canonical_tenant_id,
                "provider": provider,
                "event_id": event_id,
                "provider_event_id": provider_event_id,
                "verified_amount": verified_amount,
                "fulfillment_triggered": False,
                "capi_triggered": False,
            }

        # Step C: Append-only payment_events persistence with composite uniqueness
        if existing_is_processing:
            cur.execute(
                """
                UPDATE payment_events
                SET event_type = 'PAYMENT_SETTLED',
                    payload = %s::jsonb,
                    raw_payload = %s::jsonb,
                    status = 'PROCESSED',
                    processed_at = %s,
                    updated_at = %s
                WHERE provider = %s AND event_id = %s AND status = 'PROCESSING'
                RETURNING event_id;
                """,
                (payload_json, raw_payload_json, now_utc, now_utc, provider, event_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO payment_events (
                    provider, event_id, reference_id, event_type, payload, status,
                    record_classification, processed_at, created_at, updated_at,
                    order_id, provider_event_id, amount, raw_payload, tenant_id
                ) VALUES (
                    %s, %s, %s, 'PAYMENT_SETTLED', %s::jsonb, 'PROCESSED',
                    'STAGE3_SETTLEMENT', %s, %s, %s,
                    %s, %s, %s, %s::jsonb, %s
                )
                ON CONFLICT (provider, event_id) DO NOTHING
                RETURNING event_id;
                """,
                (
                    provider,
                    event_id,
                    order_id,
                    payload_json,
                    now_utc,
                    now_utc,
                    now_utc,
                    order_id,
                    provider_event_id,
                    verified_amount,
                    raw_payload_json,
                    canonical_tenant_id,
                ),
            )
        inserted_ev = cur.fetchone()
        if inserted_ev is None:
            _safe_rollback_conn(conn)
            return {
                "status": "ALREADY_PROCESSED",
                "http_status": 200,
                "idempotent": True,
                "order_id": order_id,
                "canonical_tenant_id": canonical_tenant_id,
                "provider": provider,
                "event_id": event_id,
                "provider_event_id": provider_event_id,
                "verified_amount": verified_amount,
                "fulfillment_triggered": False,
                "capi_triggered": False,
            }
        # Step D: Strict order status update & durable Stage 4 outbox record
        cur.execute(
            """
            UPDATE orders
            SET status = 'PAID',
                payment_status = 'PAID',
                order_status = 'PAID',
                fulfillment_status = 'PENDING_STAGE4_VERIFICATION',
                paid_at = COALESCE(orders.paid_at, %s),
                updated_at = %s
            WHERE id = %s
              AND tenant_id = %s
              AND COALESCE(gross_amount, amount, 0) = %s
              AND COALESCE(UPPER(TRIM(status)), '') IN ('PENDING', 'WAITING_PAYMENT', 'UNPAID', '');
            """,
            (now_utc, now_utc, order_id, canonical_tenant_id, verified_amount),
        )
        if getattr(cur, "rowcount", 0) != 1:
            _safe_rollback_conn(conn)
            raise SettlementProvenanceError(
                f"Atomic order status transition failed for order '{order_id}'.",
                error_code="ORDER_STATE_TRANSITION_FAILED",
                http_status=409,
            )

        # Step E: Financial ledger accounting (fee_amount=NULL, net_amount=NULL, PENDING_RECONCILIATION)
        ledger_meta_json = json.dumps(
            {
                "credential_profile_id": verified_fields["credential_profile_id"],
                "prov_key_id": verified_fields["prov_key_id"],
                "provider_account_id": verified_fields["provider_account_id"],
                "provider_event_id": provider_event_id,
                "rail_type": verified_fields["rail_type"],
                "sku_id": sku_id,
                "verification_method": verified_fields["verification_method"],
                "verified_at_utc": verified_fields["verified_at_utc"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        cur.execute(
            """
            INSERT INTO financial_ledger (
                order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount,
                currency, transaction_type, status, transaction_status, reconciliation_status, metadata, created_at
            )
            SELECT
                %s, %s, %s, %s, %s, NULL, NULL,
                'IDR', 'PAYMENT_CREDIT', 'SETTLED', 'SETTLED', 'PENDING_RECONCILIATION', %s::jsonb, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM financial_ledger
                WHERE order_id = %s AND transaction_type = 'PAYMENT_CREDIT'
            );
            """,
            (
                order_id,
                canonical_tenant_id,
                provider,
                event_id,
                verified_amount,
                ledger_meta_json,
                now_utc,
                order_id,
            ),
        )

        # Step F: Atomic commit
        conn.commit()
        return {
            "status": "PERSISTED",
            "http_status": 200,
            "idempotent": False,
            "order_id": order_id,
            "canonical_tenant_id": canonical_tenant_id,
            "provider": provider,
            "event_id": event_id,
            "provider_event_id": provider_event_id,
            "verified_amount": verified_amount,
            "currency": verified_fields["currency"],
            "sku_id": sku_id,
            "order_status": "PAID",
            "payment_status": "PAID",
            "fulfillment_status": "PENDING_STAGE4_VERIFICATION",
            "ledger_transaction_status": "SETTLED",
            "ledger_reconciliation_status": "PENDING_RECONCILIATION",
            "ledger_fee_amount": None,
            "ledger_net_amount": None,
            "provenance": provenance_envelope,
            "fulfillment_triggered": False,
            "capi_triggered": False,
        }
    except SettlementProvenanceError:
        _safe_rollback_conn(conn)
        raise
    except Exception as exc:
        _safe_rollback_conn(conn)
        raise SettlementProvenanceError(
            f"Database transaction failed during settlement persistence and was rolled back: {exc}",
            error_code="DATABASE_UNAVAILABLE",
            http_status=503,
        ) from exc
    finally:
        _safe_close_conn(conn, callable(db_conn_factory))
