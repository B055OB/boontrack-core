"""tests/payments/test_wave1a_rem02_provenance_signing_fail_closed.py
Wave 1A (REM-02) Regression Test Suite: Provenance Signing Fail-Closed & Lifecycle Caching.

Covers mandatory REM-02 acceptance criteria across `app.routes.xendit` and `app.routes.payment`:
(a) Missing private or public verification keyring fails closed (HTTP 503 PROVENANCE_SIGNING_UNAVAILABLE).
(b) Malformed keyring JSON, invalid shapes, weak keys, private key in verify keyring, legacy env aliases,
    and APP_MASTER_KEY reuse fail closed without leaking secrets.
(c) Mismatched public/private Ed25519 key pairs, missing active key_id in verify keyring, and REVOKED
    verify keys fail closed.
(d) Valid matched Ed25519 keyrings succeed, support cross-worker verification, and support key rotation.
(e) Validated signer/verifier cache reuse (zero per-callback JSON re-parsing) and safe invalidation
    on keyring rotation, removal, or corruption.
(f) Staging, production, development, and empty environment fail-closed behavior with zero ephemeral
    `Ed25519PrivateKey.generate()` / `"dev-xendit-key"` / `"dev-midtrans-key"` fallback.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import sys
from typing import Any, Dict, Tuple
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from aiohttp import web
from aiohttp.test_utils import TestClient as AioTestClient, TestServer as AioTestServer
import pytest

# Ensure repository root is on sys.path and enforce isolated synthetic env before `app.*` imports
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.security.test_isolation_guard import bootstrap_isolated_test_env  # noqa: E402

bootstrap_isolated_test_env(REPO_ROOT)

import app.routes.payment as payment_routes  # noqa: E402
import app.routes.xendit as xendit_routes  # noqa: E402
from app.core.security.provenance_authority import (  # noqa: E402
    ENV_APP_MASTER_KEY,
    ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
    ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
    ProvenanceSigner,
    ProvenanceSigningKeyring,
    ProvenanceVerificationKeyring,
    ProvenanceVerifier,
    SettlementProvenanceError,
    TrustedSettlementVerificationBoundary,
)


def _derive_test_keypair(label: str) -> Tuple[str, str]:
    """Deterministically derive a synthetic Ed25519 (priv_hex, pub_hex) pair for unit tests."""
    seed = hashlib.sha256(f"boontrack-rem02-test-seed:{label}".encode("utf-8")).digest()
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub_hex = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return seed.hex(), pub_hex


PRIV_A_HEX, PUB_A_HEX = _derive_test_keypair("alpha-v1")
PRIV_B_HEX, PUB_B_HEX = _derive_test_keypair("beta-v2")
PRIV_OLD_HEX, PUB_OLD_HEX = _derive_test_keypair("hist-v0")

TEST_TENANT_UUID = "2b200000-0000-0000-0000-000000000001"
TEST_XENDIT_TOKEN = "xen_rem02_test_token_secret_123"
TEST_MIDTRANS_KEY = "mid_rem02_test_server_secret_456"


def _set_valid_keyring_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    key_id: str = "prv_rem02_v1",
    priv_hex: str = PRIV_A_HEX,
    pub_hex: str = PUB_A_HEX,
    priv_status: str = "ACTIVE",
    pub_status: str = "ACTIVE",
) -> None:
    monkeypatch.setenv(
        ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
        json.dumps({key_id: {"private_key_hex": priv_hex, "status": priv_status}}),
    )
    monkeypatch.setenv(
        ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
        json.dumps({key_id: {"public_key_hex": pub_hex, "status": pub_status}}),
    )


def _clear_keyring_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING, raising=False)
    monkeypatch.delenv(ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING, raising=False)


def _make_persisted_order(provider: str = "XENDIT") -> Dict[str, Any]:
    return {
        "id": "ORD-REM02-001",
        "tenant_id": TEST_TENANT_UUID,
        "canonical_tenant_id": TEST_TENANT_UUID,
        "tenant_slug": "tenant-rem02",
        "gross_amount": 150000,
        "sku_id": "prod_rem02",
        "status": "PENDING",
        "payment_status": "PENDING",
        "tenant_metadata": {},
        "order_metadata": {},
        "customer_name": "Test Buyer",
        "customer_phone": "081234567890",
        "customer_email": "buyer@example.com",
        "product_title": "REM-02 Test Product",
        "provider": provider,
    }


def _make_xendit_payload_and_headers() -> Tuple[Dict[str, Any], Dict[str, str]]:
    payload = {
        "event": "qr.payment",
        "business_id": "xnd_biz_rem02",
        "data": {
            "id": "qr_pay_rem02_001",
            "external_id": "ORD-REM02-001",
            "amount": 150000,
            "status": "COMPLETED",
            "business_id": "xnd_biz_rem02",
        },
    }
    headers = {"x-callback-token": TEST_XENDIT_TOKEN}
    return payload, headers


def _make_midtrans_payload() -> Dict[str, Any]:
    sig = hashlib.sha512(f"ORD-REM02-001200150000.00{TEST_MIDTRANS_KEY}".encode("utf-8")).hexdigest()
    return {
        "order_id": "ORD-REM02-001",
        "transaction_id": "tx_mid_rem02_001",
        "status_code": "200",
        "gross_amount": "150000.00",
        "transaction_status": "settlement",
        "merchant_id": "M_REM02_01",
        "signature_key": sig,
    }


@pytest.fixture(autouse=True)
def reset_provenance_cache_fixture():
    xendit_routes._reset_provenance_signer_cache()
    yield
    xendit_routes._reset_provenance_signer_cache()


# =============================================================================
# Static Guard: Zero Ephemeral Key Generation in xendit.py & payment.py
# =============================================================================

def test_zero_ephemeral_key_generation_in_route_modules() -> None:
    """Ensure Ed25519PrivateKey.generate() and hardcoded dev key IDs are completely removed."""
    xendit_src = inspect.getsource(xendit_routes)
    payment_src = inspect.getsource(payment_routes)

    for forbidden in ("Ed25519PrivateKey.generate", "dev-xendit-key", "dev-midtrans-key"):
        assert forbidden not in xendit_src, f"Forbidden fallback '{forbidden}' found in app/routes/xendit.py"
        assert forbidden not in payment_src, f"Forbidden fallback '{forbidden}' found in app/routes/payment.py"


# =============================================================================
# (a) Missing Keyring Tests (Fail-Closed 503)
# =============================================================================

@pytest.mark.parametrize(
    "missing_var",
    [
        ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
        ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
        "BOTH",
    ],
)
def test_a_missing_keyring_raises_503_in_xendit_and_payment(
    monkeypatch: pytest.MonkeyPatch,
    missing_var: str,
) -> None:
    _set_valid_keyring_env(monkeypatch)
    if missing_var in (ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING, "BOTH"):
        monkeypatch.delenv(ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING, raising=False)
    if missing_var in (ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING, "BOTH"):
        monkeypatch.delenv(ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING, raising=False)

    for fn in (
        xendit_routes._get_provenance_signer_and_verifier,
        payment_routes._get_provenance_signer_and_verifier,
    ):
        with pytest.raises(SettlementProvenanceError) as exc_info:
            fn()
        assert exc_info.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
        assert exc_info.value.http_status == 503
        assert PRIV_A_HEX not in str(exc_info.value)


@pytest.mark.asyncio
async def test_a_missing_keyring_fails_closed_503_across_xendit_and_midtrans_webhooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_keyring_env(monkeypatch)

    x_payload, x_headers = _make_xendit_payload_and_headers()
    m_payload = _make_midtrans_payload()

    with patch("app.routes.xendit._lookup_persisted_order_sync", return_value=_make_persisted_order("XENDIT")), \
         patch("app.routes.xendit.CredentialProfileMapper.resolve_and_verify_callback_secret") as mock_auth, \
         patch("app.routes.xendit.TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability"), \
         patch("app.routes.xendit.commit_verified_settlement_transaction") as mock_x_commit:
        mock_auth.return_value = MagicMock(
            credential_profile_id="cp_rem02_x",
            expected_provider_account_id="xnd_biz_rem02",
        )
        res = await xendit_routes.process_xendit_webhook_core(x_payload, x_headers)

        assert res["http_status"] == 503
        assert res["response"]["status"] == "FAILED"
        assert res["response"]["error_code"] == "PROVENANCE_SIGNING_UNAVAILABLE"
        mock_x_commit.assert_not_called()

    mock_profile = MagicMock(
        credential_profile_id="cp_rem02_m",
        canonical_tenant_id=TEST_TENANT_UUID,
        provider="MIDTRANS",
        profile_status="ACTIVE",
        environment="production",
        expected_provider_account_id="M_REM02_01",
        verification_secrets=[MagicMock(status="ACTIVE", secret_ref="vault://rem02/midtrans")],
    )
    with patch("app.routes.payment._lookup_midtrans_persisted_order_sync", return_value=_make_persisted_order("MIDTRANS")), \
         patch("app.routes.payment.CredentialProfileMapper.parse_profiles_from_metadata", return_value=[mock_profile]), \
         patch("app.routes.payment.CredentialProfileMapper._resolve_secret_ref", return_value=TEST_MIDTRANS_KEY), \
         patch("app.routes.payment.TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability"), \
         patch("app.routes.payment.commit_verified_settlement_transaction") as mock_m_commit:
        m_res, m_code = await payment_routes.handle_midtrans_notification_logic(m_payload)

        assert m_code == 503
        assert m_res["status"] == "error"
        assert m_res["error_code"] == "PROVENANCE_SIGNING_UNAVAILABLE"
        mock_m_commit.assert_not_called()


# =============================================================================
# (b) Malformed Keyring Tests (Fail-Closed 503, Zero Secret Leakage)
# =============================================================================

@pytest.mark.parametrize(
    "bad_priv_json",
    [
        "",
        "   ",
        "{malformed-json",
        "[]",
        "123",
        "{}",
        json.dumps({"prv_bad": "not-an-object"}),
        json.dumps({"prv_weak": {"private_key_hex": "short", "status": "ACTIVE"}}),
        json.dumps({"prv_bad_status": {"private_key_hex": PRIV_A_HEX, "status": "UNKNOWN"}}),
        json.dumps({"prv_no_active": {"private_key_hex": PRIV_A_HEX, "status": "VERIFY_ONLY"}}),
        json.dumps({"prv_revoked": {"private_key_hex": PRIV_A_HEX, "status": "REVOKED"}}),
    ],
)
def test_b_malformed_private_keyring_fails_closed_503(
    monkeypatch: pytest.MonkeyPatch,
    bad_priv_json: str,
) -> None:
    _set_valid_keyring_env(monkeypatch)
    monkeypatch.setenv(ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING, bad_priv_json)

    with pytest.raises(SettlementProvenanceError) as exc_info:
        xendit_routes._get_provenance_signer_and_verifier()

    assert exc_info.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_info.value.http_status == 503
    assert PRIV_A_HEX not in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_pub_json",
    [
        "",
        "   ",
        "{malformed-json",
        "[]",
        "null",
        "{}",
        json.dumps({"prv_rem02_v1": "not-an-object"}),
        json.dumps({"prv_rem02_v1": {"public_key_hex": "abcd", "status": "ACTIVE"}}),
        json.dumps({"prv_rem02_v1": {"public_key_hex": "zz" * 32, "status": "ACTIVE"}}),
        json.dumps(
            {
                "prv_rem02_v1": {
                    "public_key_hex": PUB_A_HEX,
                    "private_key_hex": PRIV_A_HEX,
                    "status": "ACTIVE",
                }
            }
        ),
    ],
)
def test_b_malformed_public_verify_keyring_fails_closed_503(
    monkeypatch: pytest.MonkeyPatch,
    bad_pub_json: str,
) -> None:
    _set_valid_keyring_env(monkeypatch)
    monkeypatch.setenv(ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING, bad_pub_json)

    with pytest.raises(SettlementProvenanceError) as exc_info:
        xendit_routes._get_provenance_signer_and_verifier()

    assert exc_info.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_info.value.http_status == 503
    assert PRIV_A_HEX not in str(exc_info.value)


def test_b_app_master_key_reuse_and_legacy_alias_fail_closed_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Reusing APP_MASTER_KEY as provenance signing key
    _set_valid_keyring_env(monkeypatch, priv_hex=PRIV_A_HEX, pub_hex=PUB_A_HEX)
    monkeypatch.setenv(ENV_APP_MASTER_KEY, PRIV_A_HEX)
    with pytest.raises(SettlementProvenanceError) as exc_sep:
        xendit_routes._get_provenance_signer_and_verifier()
    assert exc_sep.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_sep.value.http_status == 503
    assert PRIV_A_HEX not in str(exc_sep.value)

    # 2. Legacy alias environment variable present
    monkeypatch.delenv(ENV_APP_MASTER_KEY, raising=False)
    _set_valid_keyring_env(monkeypatch)
    monkeypatch.setenv("PAYMENT_PROVENANCE_HMAC_KEYS_JSON", '{"legacy":{"secret":"' + "a" * 32 + '","status":"ACTIVE"}}')
    try:
        with pytest.raises(SettlementProvenanceError) as exc_leg:
            xendit_routes._get_provenance_signer_and_verifier()
        assert exc_leg.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
        assert exc_leg.value.http_status == 503
    finally:
        monkeypatch.delenv("PAYMENT_PROVENANCE_HMAC_KEYS_JSON", raising=False)


# =============================================================================
# (c) Mismatched Public/Private Key Pair Tests
# =============================================================================

def test_c_mismatched_keypair_fails_closed_503(monkeypatch: pytest.MonkeyPatch) -> None:
    # Case 1: Same key_id, public key from different Ed25519 keypair
    _set_valid_keyring_env(
        monkeypatch,
        key_id="prv_rem02_v1",
        priv_hex=PRIV_A_HEX,
        pub_hex=PUB_B_HEX,
    )
    with pytest.raises(SettlementProvenanceError) as exc_pair:
        xendit_routes._get_provenance_signer_and_verifier()
    assert exc_pair.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_pair.value.http_status == 503

    # Case 2: Active signing key_id missing from public verification keyring
    monkeypatch.setenv(
        ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
        json.dumps({"prv_alpha": {"private_key_hex": PRIV_A_HEX, "status": "ACTIVE"}}),
    )
    monkeypatch.setenv(
        ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
        json.dumps({"prv_other": {"public_key_hex": PUB_A_HEX, "status": "ACTIVE"}}),
    )
    with pytest.raises(SettlementProvenanceError) as exc_kid:
        payment_routes._get_provenance_signer_and_verifier()
    assert exc_kid.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_kid.value.http_status == 503

    # Case 3: Active key_id is REVOKED in public verification keyring
    _set_valid_keyring_env(
        monkeypatch,
        key_id="prv_rem02_v1",
        priv_hex=PRIV_A_HEX,
        pub_hex=PUB_A_HEX,
        priv_status="ACTIVE",
        pub_status="REVOKED",
    )
    with pytest.raises(SettlementProvenanceError) as exc_rev:
        xendit_routes._get_provenance_signer_and_verifier()
    assert exc_rev.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_rev.value.http_status == 503

    # Case 4: Secondary VERIFY_ONLY key shared between keyrings has mismatched public key
    monkeypatch.setenv(
        ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
        json.dumps(
            {
                "prv_active": {"private_key_hex": PRIV_A_HEX, "status": "ACTIVE"},
                "prv_prev": {"private_key_hex": PRIV_OLD_HEX, "status": "VERIFY_ONLY"},
            }
        ),
    )
    monkeypatch.setenv(
        ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
        json.dumps(
            {
                "prv_active": {"public_key_hex": PUB_A_HEX, "status": "ACTIVE"},
                "prv_prev": {"public_key_hex": PUB_B_HEX, "status": "VERIFY_ONLY"},
            }
        ),
    )
    with pytest.raises(SettlementProvenanceError) as exc_sec:
        xendit_routes._get_provenance_signer_and_verifier()
    assert exc_sec.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_sec.value.http_status == 503


# =============================================================================
# (d) Valid Keyring & Cross-Worker Verification Tests
# =============================================================================

def test_d_valid_keyring_signs_and_verifies_across_workers_and_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
        json.dumps(
            {
                "prv_active_v2": {"private_key_hex": PRIV_B_HEX, "status": "ACTIVE"},
                "prv_hist_v1": {"private_key_hex": PRIV_A_HEX, "status": "VERIFY_ONLY"},
            }
        ),
    )
    monkeypatch.setenv(
        ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
        json.dumps(
            {
                "prv_active_v2": {"public_key_hex": PUB_B_HEX, "status": "ACTIVE"},
                "prv_hist_v1": {"public_key_hex": PUB_A_HEX, "status": "VERIFY_ONLY"},
                "prv_legacy_v0": {"public_key_hex": PUB_OLD_HEX, "status": "VERIFY_ONLY"},
            }
        ),
    )

    signer, verifier = xendit_routes._get_provenance_signer_and_verifier()
    p_signer, p_verifier = payment_routes._get_provenance_signer_and_verifier()

    assert isinstance(signer, ProvenanceSigner)
    assert isinstance(verifier, ProvenanceVerifier)
    assert p_signer is signer
    assert p_verifier is verifier

    cap = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="XENDIT",
        verification_method="XENDIT_CALLBACK_TOKEN",
        credential_profile_id="cred_rem02_alpha",
        expected_provider_account_id="xnd_biz_rem02",
        provider_verification_secret=TEST_XENDIT_TOKEN,
        webhook_headers={"x-callback-token": TEST_XENDIT_TOKEN},
        webhook_payload={
            "id": "evt_rem02_valid",
            "business_id": "xnd_biz_rem02",
            "external_id": "ORD-REM02-001",
            "status": "PAID",
            "currency": "IDR",
            "amount": 150000,
        },
        authoritative_order_id="ORD-REM02-001",
        authoritative_canonical_tenant_id=TEST_TENANT_UUID,
        authoritative_order_amount=150000,
        authoritative_sku_id="prod_rem02",
        verified_at_utc="2026-11-19T10:00:00Z",
        rail_type="NATIVE_PG",
    )

    envelope = signer.sign_verified_settlement(cap)
    assert envelope["fields"]["prov_key_id"] == "prv_active_v2"

    # Cross-worker verification using a freshly loaded public-key-only verifier (simulating worker restart)
    fresh_worker_verifier = ProvenanceVerifier(ProvenanceVerificationKeyring.from_env())
    verified_fields = fresh_worker_verifier.verify_provenance_envelope(
        envelope,
        expected_order_id="ORD-REM02-001",
        expected_canonical_tenant_id=TEST_TENANT_UUID,
        expected_amount=150000,
        expected_sku_id="prod_rem02",
    )
    assert verified_fields["prov_key_id"] == "prv_active_v2"


# =============================================================================
# (e) Cache Reuse & Safe Invalidation Lifecycle Tests
# =============================================================================

def test_e_cache_reuse_and_invalidation_on_env_change(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_keyring_env(monkeypatch, key_id="prv_cache_v1", priv_hex=PRIV_A_HEX, pub_hex=PUB_A_HEX)

    with patch.object(
        ProvenanceSigningKeyring,
        "from_env",
        wraps=ProvenanceSigningKeyring.from_env,
    ) as spy_priv, patch.object(
        ProvenanceVerificationKeyring,
        "from_env",
        wraps=ProvenanceVerificationKeyring.from_env,
    ) as spy_pub:
        s1, v1 = xendit_routes._get_provenance_signer_and_verifier()
        s2, v2 = xendit_routes._get_provenance_signer_and_verifier()
        s3, v3 = payment_routes._get_provenance_signer_and_verifier()

        assert s1 is s2 is s3
        assert v1 is v2 is v3
        assert spy_priv.call_count == 1
        assert spy_pub.call_count == 1

        # Rotate keyring in env -> cache invalidates and loads new signer/verifier
        _set_valid_keyring_env(monkeypatch, key_id="prv_cache_v2", priv_hex=PRIV_B_HEX, pub_hex=PUB_B_HEX)
        s4, v4 = xendit_routes._get_provenance_signer_and_verifier()
        s5, v5 = xendit_routes._get_provenance_signer_and_verifier()

        assert s4 is not s1
        assert v4 is not v1
        assert s4 is s5
        assert v4 is v5
        assert spy_priv.call_count == 2
        assert spy_pub.call_count == 2

    # Corrupting / mismatching keyring invalidates cache immediately and never serves stale signer
    _set_valid_keyring_env(monkeypatch, key_id="prv_cache_v2", priv_hex=PRIV_B_HEX, pub_hex=PUB_A_HEX)
    with pytest.raises(SettlementProvenanceError) as exc_corrupted:
        xendit_routes._get_provenance_signer_and_verifier()
    assert exc_corrupted.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_corrupted.value.http_status == 503
    assert xendit_routes._PROV_SIGNER is None
    assert xendit_routes._PROV_VERIFIER is None

    # Restoring valid keyring refreshes cleanly; removing keyring invalidates cache immediately
    _set_valid_keyring_env(monkeypatch, key_id="prv_cache_v3", priv_hex=PRIV_B_HEX, pub_hex=PUB_B_HEX)
    s6, v6 = xendit_routes._get_provenance_signer_and_verifier()
    assert isinstance(s6, ProvenanceSigner)
    assert isinstance(v6, ProvenanceVerifier)

    _clear_keyring_env(monkeypatch)
    with pytest.raises(SettlementProvenanceError) as exc_removed:
        xendit_routes._get_provenance_signer_and_verifier()
    assert exc_removed.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_removed.value.http_status == 503
    assert xendit_routes._PROV_SIGNER is None
    assert xendit_routes._PROV_VERIFIER is None


# =============================================================================
# (f) Staging / Production Fail-Closed Behavior (Core, FastAPI & aiohttp)
# =============================================================================

@pytest.mark.parametrize(
    "env_var,env_val",
    [
        ("APP_ENV", "production"),
        ("APP_ENV", "staging"),
        ("ENVIRONMENT", "production"),
        ("ENVIRONMENT", "staging"),
        ("RAILWAY_ENVIRONMENT", "production"),
        ("RAILWAY_ENVIRONMENT", "staging"),
        ("ALL", "production"),
        ("ALL", "staging"),
        ("APP_ENV", "development"),
        ("APP_ENV", ""),
    ],
)
@pytest.mark.asyncio
async def test_f_staging_production_and_dev_fail_closed_503_across_runners(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    env_val: str,
) -> None:
    _clear_keyring_env(monkeypatch)
    if env_var == "ALL":
        for k in ("APP_ENV", "ENV", "ENVIRONMENT", "BOONTRACK_ENV", "RAILWAY_ENVIRONMENT"):
            monkeypatch.setenv(k, env_val)
    else:
        monkeypatch.setenv(env_var, env_val)

    # 1. Direct loader fails closed
    with pytest.raises(SettlementProvenanceError) as exc_direct:
        xendit_routes._get_provenance_signer_and_verifier()
    assert exc_direct.value.error_code == "PROVENANCE_SIGNING_UNAVAILABLE"
    assert exc_direct.value.http_status == 503

    # 2. FastAPI + aiohttp Xendit and Midtrans routes fail closed with HTTP 503
    fastapi_app = FastAPI()
    fastapi_app.include_router(xendit_routes.xendit_router)
    fastapi_app.include_router(payment_routes.payment_router)
    fa_client = TestClient(fastapi_app)

    aio_x_app = web.Application()
    xendit_routes.register_xendit_routes(aio_x_app)

    aio_p_app = web.Application()
    payment_routes.register_payment_routes(aio_p_app)

    x_payload, x_headers = _make_xendit_payload_and_headers()
    m_payload = _make_midtrans_payload()

    mock_mid_profile = MagicMock(
        credential_profile_id="cp_rem02_m",
        canonical_tenant_id=TEST_TENANT_UUID,
        provider="MIDTRANS",
        profile_status="ACTIVE",
        environment="production",
        expected_provider_account_id="M_REM02_01",
        verification_secrets=[MagicMock(status="ACTIVE", secret_ref="vault://rem02/midtrans")],
    )

    with patch("app.routes.xendit._lookup_persisted_order_sync", return_value=_make_persisted_order("XENDIT")), \
         patch("app.routes.xendit.CredentialProfileMapper.resolve_and_verify_callback_secret") as mock_x_auth, \
         patch("app.routes.xendit.TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability"), \
         patch("app.routes.payment._lookup_midtrans_persisted_order_sync", return_value=_make_persisted_order("MIDTRANS")), \
         patch("app.routes.payment.CredentialProfileMapper.parse_profiles_from_metadata", return_value=[mock_mid_profile]), \
         patch("app.routes.payment.CredentialProfileMapper._resolve_secret_ref", return_value=TEST_MIDTRANS_KEY), \
         patch("app.routes.payment.TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability"):
        mock_x_auth.return_value = MagicMock(
            credential_profile_id="cp_rem02_x",
            expected_provider_account_id="xnd_biz_rem02",
        )

        # FastAPI Xendit (xendit_router + payment_router)
        fa_x = fa_client.post("/api/v1/payments/xendit/callback", json=x_payload, headers=x_headers)
        assert fa_x.status_code == 503
        assert "PROVENANCE_SIGNING_UNAVAILABLE" in str(fa_x.json())

        fa_x_alias = fa_client.post("/api/v1/payments/webhook/xendit", json=x_payload, headers=x_headers)
        assert fa_x_alias.status_code == 503
        assert "PROVENANCE_SIGNING_UNAVAILABLE" in str(fa_x_alias.json())

        # FastAPI Midtrans
        fa_m = fa_client.post("/webhook/payment/midtrans", json=m_payload)
        assert fa_m.status_code == 503
        assert fa_m.json()["detail"]["error_code"] == "PROVENANCE_SIGNING_UNAVAILABLE"

        # aiohttp xendit.py handler
        async with AioTestClient(AioTestServer(aio_x_app)) as aio_x_client:
            aio_x = await aio_x_client.post("/api/v1/payments/xendit/callback", json=x_payload, headers=x_headers)
            assert aio_x.status == 503
            aio_x_body = await aio_x.json()
            assert aio_x_body["error_code"] == "PROVENANCE_SIGNING_UNAVAILABLE"

        # aiohttp payment.py Xendit & Midtrans handlers
        async with AioTestClient(AioTestServer(aio_p_app)) as aio_p_client:
            aio_px = await aio_p_client.post("/api/v1/payments/webhook/xendit", json=x_payload, headers=x_headers)
            assert aio_px.status == 503
            aio_px_body = await aio_px.json()
            assert aio_px_body["error_code"] == "PROVENANCE_SIGNING_UNAVAILABLE"

            aio_m = await aio_p_client.post("/webhook/payment/midtrans", json=m_payload)
            assert aio_m.status == 503
            aio_m_body = await aio_m.json()
            assert aio_m_body["error_code"] == "PROVENANCE_SIGNING_UNAVAILABLE"
