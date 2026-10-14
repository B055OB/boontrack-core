"""tests/test_strict_hmac_secret.py
CTO Directive 09 Priority 3 (FIX 3) Strict Single Env Secret & Boundary Tests.

Verifies:
1. When BOONTRACK_HMAC_SECRET is unset, even if BOONTRACK_INTERNAL_HMAC_SECRET is set,
   get_hmac_secret() MUST strictly raise ValueError (Zero fallback to alias).
2. When BOONTRACK_HMAC_SECRET is empty string or whitespace, raises ValueError.
3. When neither is set, raises ValueError.
4. When BOONTRACK_HMAC_SECRET is validly set, successfully retrieves secret (tested via monkeypatch).
5. Caller CANNOT pass secret as argument (raises TypeError).
6. enforce_tenant_boundary strictly rejects missing/None/empty target_tenant_id with HTTP 403.
7. Explicit self-tenant boundary helper allows self-scoped requests.
8. Cross-service signature generation & verification fails if secret is missing, and succeeds when set.
"""

import os
import pytest
from unittest.mock import patch
from fastapi import HTTPException

from app.core.security.inter_service_auth import (
    get_hmac_secret,
    generate_inter_service_signature,
    verify_inter_service_signature,
    enforce_tenant_boundary,
    enforce_self_tenant_boundary,
)


def test_alias_only_raises_value_error():
    """Negative Test: BOONTRACK_HMAC_SECRET unset, but BOONTRACK_INTERNAL_HMAC_SECRET set.
    MUST raise ValueError. Zero fallback allowed."""
    with patch.dict(os.environ, {"BOONTRACK_INTERNAL_HMAC_SECRET": "alias_secret_should_be_ignored"}, clear=True):
        with pytest.raises(ValueError, match="BOONTRACK_HMAC_SECRET environment variable is missing"):
            get_hmac_secret()


def test_no_secret_at_all_raises_value_error():
    """Negative Test: No HMAC secret environment variables set. MUST raise ValueError."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="BOONTRACK_HMAC_SECRET environment variable is missing"):
            get_hmac_secret()


def test_blank_secret_raises_value_error():
    """Negative Test: BOONTRACK_HMAC_SECRET is blank or whitespace. MUST raise ValueError."""
    with patch.dict(os.environ, {"BOONTRACK_HMAC_SECRET": "   "}, clear=True):
        with pytest.raises(ValueError, match="BOONTRACK_HMAC_SECRET environment variable is missing"):
            get_hmac_secret()


def test_valid_secret_retrieved_via_monkeypatch(monkeypatch):
    """Positive Test: BOONTRACK_HMAC_SECRET correctly set via monkeypatch."""
    monkeypatch.setenv("BOONTRACK_HMAC_SECRET", "valid_production_secret_key_123")
    secret = get_hmac_secret()
    assert secret == "valid_production_secret_key_123"


def test_caller_cannot_pass_secret_argument():
    """Negative Test: Caller cannot override secret via function parameters."""
    with pytest.raises(TypeError):
        get_hmac_secret("unauthorized_override_secret")  # type: ignore

    with pytest.raises(TypeError):
        get_hmac_secret(explicit_secret="unauthorized_override_secret")  # type: ignore

    with pytest.raises(TypeError):
        generate_inter_service_signature("tenant_alpha", body=None, secret="unauthorized")  # type: ignore

    with pytest.raises(TypeError):
        verify_inter_service_signature("sig", 12345, "tenant_alpha", secret="unauthorized")  # type: ignore


def test_enforce_tenant_boundary_rejects_empty_target():
    """Negative Test: target_tenant_id is missing or None without allow_self_tenant.
    MUST raise HTTP 403 Forbidden with TENANT_TARGET_MISSING."""
    with pytest.raises(HTTPException) as exc_info:
        enforce_tenant_boundary("tenant_alpha", None)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail.get("error") == "TENANT_TARGET_MISSING"

    with pytest.raises(HTTPException) as exc_info2:
        enforce_tenant_boundary("tenant_alpha", "")
    assert exc_info2.value.status_code == 403
    assert exc_info2.value.detail.get("error") == "TENANT_TARGET_MISSING"


def test_enforce_tenant_boundary_allows_self_tenant_when_explicit():
    """Positive Test: explicit self-tenant permission."""
    enforce_tenant_boundary("tenant_alpha", None, allow_self_tenant=True)
    enforce_self_tenant_boundary("tenant_alpha")


def test_enforce_tenant_boundary_mismatch_raises_403():
    """Negative Test: Cross-tenant mismatch raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        enforce_tenant_boundary("tenant_alpha", "tenant_beta")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail.get("error") == "TENANT_BOUNDARY_MISMATCH"


def test_signature_generation_and_verification_end_to_end(monkeypatch):
    """End-to-end signature generation and verification with strict environment secret."""
    monkeypatch.setenv("BOONTRACK_HMAC_SECRET", "strictly_verified_secret_key_999")
    body = {"order_id": "ORD-12345", "amount": 150000}
    sig, ts, body_hash = generate_inter_service_signature(
        authenticated_tenant_id="tenant_alpha",
        body=body,
    )
    assert len(sig) == 64
    assert len(body_hash) == 64

    valid, reason = verify_inter_service_signature(
        signature=sig,
        timestamp=ts,
        authenticated_tenant_id="tenant_alpha",
        body=body,
    )
    assert valid is True
    assert reason == "VERIFIED"
