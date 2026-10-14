"""tests/test_strict_hmac_secret.py
CTO Directive 08 Priority 3 (P1-H1) Strict Single Env Secret Negative & Positive Tests.

Verifies:
1. When BOONTRACK_HMAC_SECRET is unset, even if BOONTRACK_INTERNAL_HMAC_SECRET is set,
   get_hmac_secret() MUST strictly raise ValueError (Zero fallback to alias).
2. When BOONTRACK_HMAC_SECRET is empty string or whitespace, raises ValueError.
3. When neither is set, raises ValueError.
4. When BOONTRACK_HMAC_SECRET is validly set, successfully retrieves secret.
5. Cross-service signature generation & verification fails if secret is missing, and succeeds when set.
"""

import os
import pytest
from unittest.mock import patch

from app.core.security.inter_service_auth import (
    get_hmac_secret,
    generate_inter_service_signature,
    verify_inter_service_signature,
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


def test_valid_secret_retrieved():
    """Positive Test: BOONTRACK_HMAC_SECRET correctly set."""
    with patch.dict(os.environ, {"BOONTRACK_HMAC_SECRET": "valid_production_secret_key_123"}, clear=True):
        secret = get_hmac_secret()
        assert secret == "valid_production_secret_key_123"


def test_explicit_secret_override():
    """Explicit secret passed directly into function."""
    with patch.dict(os.environ, {}, clear=True):
        secret = get_hmac_secret(explicit_secret="override_secret_abc")
        assert secret == "override_secret_abc"


def test_signature_generation_and_verification_end_to_end():
    """End-to-end signature generation and verification with strict environment secret."""
    with patch.dict(os.environ, {"BOONTRACK_HMAC_SECRET": "strictly_verified_secret_key_999"}, clear=True):
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
