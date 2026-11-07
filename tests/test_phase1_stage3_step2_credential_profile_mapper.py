"""tests/test_phase1_stage3_step2_credential_profile_mapper.py
Stage 3 Step 2A: CredentialProfileMapper Core Unit Tests.

Validates all 18 mandatory invariants:
 1. Canonical UUID validation (rejection of slugs, malformed, or non-UUID strings).
 2. Three providers active under one tenant (Xendit, Midtrans, Duitku).
 3. Multiple profiles for the same provider.
 4. active_provider decoupling (checkout default only; does not gate callbacks).
 5. Explicit order-level profile binding takes precedence.
 6. Legacy fallback with exactly one matching ACTIVE profile.
 7. Legacy fallback with zero or multiple matching profiles (NOT_FOUND vs AMBIGUOUS).
 8. Tenant mismatch rejection (CREDENTIAL_PROFILE_TENANT_MISMATCH).
 9. Inactive profile rejection (SUSPENDED / REVOKED -> CREDENTIAL_PROFILE_INACTIVE).
10. Secret pointer resolution (env:// and vault:// explicit pointer schemes).
11. Zero plaintext secret leakage in results and audit data.
12. ACTIVE secret verification.
13. VERIFY_ONLY grace period verification (within not_after_epoch).
14. Expired VERIFY_ONLY rejection (after not_after_epoch -> EXPIRED_CREDENTIAL_SECRET_VERSION).
15. REVOKED secret rejection (REVOKED_CREDENTIAL_SECRET_VERSION).
16. Environment mismatch rejection (sandbox profile in production mode).
17. Unknown provider and malformed profile rejection (INVALID_CREDENTIAL_PROFILE).
18. Cross-tenant profile access rejection.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional

# Ensure repository root is on sys.path for standalone execution
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from app.core.security.payment_auth_guard import (
    CredentialProfileMapper,
    CredentialSecretVersion,
    CredentialVerificationResult,
    TenantCredentialProfile,
)
from app.services.payment.base import (
    PaymentAuthorizationError,
    PaymentConfigurationError,
)

TENANT_ALPHA_UUID = "11111111-1111-4111-8111-111111111111"
TENANT_BETA_UUID = "22222222-2222-4222-8222-222222222222"

MOCK_NOW_EPOCH = 1794000000
MOCK_NOW_DT = datetime.fromtimestamp(MOCK_NOW_EPOCH, tz=timezone.utc)


def _make_mock_vault() -> Dict[str, str]:
    return {
        "vault://tenants/alpha/xendit/active_v2": "xendit_active_secret_key_v2_strong",
        "vault://tenants/alpha/xendit/grace_v1": "xendit_grace_secret_key_v1_strong",
        "vault://tenants/alpha/xendit/revoked_v0": "xendit_compromised_secret_key_v0",
        "vault://tenants/alpha/midtrans/active": "midtrans_active_server_key_strong_123",
        "vault://tenants/alpha/duitku/active": "duitku_active_api_key_strong_123456",
        "vault://tenants/alpha/xendit_secondary/active": "xendit_secondary_active_secret",
        "vault://tenants/beta/xendit/active": "beta_xendit_secret_key_strong_1234",
    }


def _make_multi_provider_tenant_metadata(
    tenant_uuid: str = TENANT_ALPHA_UUID,
    active_provider: str = "XENDIT",
) -> Dict[str, Any]:
    return {
        "payment_config": {
            "mode": "NATIVE_PG",
            "active_provider": active_provider,
            "credential_profiles": {
                "cred_xendit_primary": {
                    "credential_profile_id": "cred_xendit_primary",
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "XENDIT",
                    "verification_method": "XENDIT_CALLBACK_TOKEN",
                    "expected_provider_account_id": "xnd_biz_alpha_01",
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "updated_at_utc": "2026-11-06T00:00:00Z",
                    "verification_secrets": [
                        {
                            "secret_version_id": "xnd_sec_v2",
                            "secret_ref": "vault://tenants/alpha/xendit/active_v2",
                            "status": "ACTIVE",
                            "created_at_utc": "2026-11-06T00:00:00Z",
                        },
                        {
                            "secret_version_id": "xnd_sec_v1",
                            "secret_ref": "vault://tenants/alpha/xendit/grace_v1",
                            "status": "VERIFY_ONLY",
                            "created_at_utc": "2026-10-01T00:00:00Z",
                            "not_after_epoch": MOCK_NOW_EPOCH + 3600,
                        },
                        {
                            "secret_version_id": "xnd_sec_v0",
                            "secret_ref": "vault://tenants/alpha/xendit/revoked_v0",
                            "status": "REVOKED",
                            "created_at_utc": "2026-09-01T00:00:00Z",
                        },
                    ],
                },
                "cred_midtrans_primary": {
                    "credential_profile_id": "cred_midtrans_primary",
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "MIDTRANS",
                    "verification_method": "MIDTRANS_SHA512",
                    "expected_provider_account_id": "G123456789",
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "updated_at_utc": "2026-11-06T00:00:00Z",
                    "verification_secrets": [
                        {
                            "secret_version_id": "mid_sec_v1",
                            "secret_ref": "vault://tenants/alpha/midtrans/active",
                            "status": "ACTIVE",
                            "created_at_utc": "2026-11-06T00:00:00Z",
                        }
                    ],
                },
                "cred_duitku_primary": {
                    "credential_profile_id": "cred_duitku_primary",
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "DUITKU",
                    "verification_method": "DUITKU_CALLBACK_HMAC_SHA256",
                    "expected_provider_account_id": "D1234",
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "updated_at_utc": "2026-11-06T00:00:00Z",
                    "verification_secrets": [
                        {
                            "secret_version_id": "dk_sec_v1",
                            "secret_ref": "vault://tenants/alpha/duitku/active",
                            "status": "ACTIVE",
                            "created_at_utc": "2026-11-06T00:00:00Z",
                        }
                    ],
                },
            },
        }
    }


def _make_mapper(
    vault: Optional[Dict[str, str]] = None,
    runtime_env: str = "production",
    clock_dt: datetime = MOCK_NOW_DT,
) -> CredentialProfileMapper:
    return CredentialProfileMapper(
        vault_store=vault or _make_mock_vault(),
        runtime_environment=runtime_env,
        clock_fn=lambda: clock_dt,
    )


# -----------------------------------------------------------------------------
# 1. Canonical UUID Validation
# -----------------------------------------------------------------------------
def test_01_canonical_uuid_validation() -> None:
    mapper = _make_mapper()
    valid_meta = _make_multi_provider_tenant_metadata()

    # Valid UUID succeeds
    profiles = mapper.parse_profiles_from_metadata(valid_meta, expected_canonical_tenant_id=TENANT_ALPHA_UUID)
    assert len(profiles) == 3

    # Slug instead of UUID fails closed
    with pytest.raises(PaymentAuthorizationError) as exc:
        mapper.parse_profiles_from_metadata(valid_meta, expected_canonical_tenant_id="onlineboost")
    assert exc.value.error_code == "INVALID_CANONICAL_TENANT_ID"

    # Malformed non-UUID string fails closed
    with pytest.raises(PaymentAuthorizationError) as exc_mal:
        mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id="not-a-real-uuid",
            tenant_metadata=valid_meta,
            order_metadata={},
            provider="XENDIT",
            inbound_account_id="xnd_biz_alpha_01",
            candidate_secret="xendit_active_secret_key_v2_strong",
        )
    assert exc_mal.value.error_code == "INVALID_CANONICAL_TENANT_ID"


# -----------------------------------------------------------------------------
# 2. Three Providers Active Under One Tenant
# -----------------------------------------------------------------------------
def test_02_three_providers_active_under_one_tenant() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()

    # Checkout resolution for each of the 3 providers
    prof_x = mapper.resolve_checkout_profile(meta, requested_provider="XENDIT")
    prof_m = mapper.resolve_checkout_profile(meta, requested_provider="MIDTRANS")
    prof_d = mapper.resolve_checkout_profile(meta, requested_provider="DUITKU")

    assert prof_x.credential_profile_id == "cred_xendit_primary"
    assert prof_m.credential_profile_id == "cred_midtrans_primary"
    assert prof_d.credential_profile_id == "cred_duitku_primary"

    # Callback verification for each of the 3 providers
    res_x = mapper.resolve_and_verify_callback_secret(
        TENANT_ALPHA_UUID, meta, None, "XENDIT", "xnd_biz_alpha_01", "xendit_active_secret_key_v2_strong"
    )
    assert res_x.matched_secret_version_id == "xnd_sec_v2"

    res_m = mapper.resolve_and_verify_callback_secret(
        TENANT_ALPHA_UUID, meta, None, "MIDTRANS", "G123456789", "midtrans_active_server_key_strong_123"
    )
    assert res_m.matched_secret_version_id == "mid_sec_v1"

    res_d = mapper.resolve_and_verify_callback_secret(
        TENANT_ALPHA_UUID, meta, None, "DUITKU", "D1234", "duitku_active_api_key_strong_123456"
    )
    assert res_d.matched_secret_version_id == "dk_sec_v1"


# -----------------------------------------------------------------------------
# 3. Multiple Profiles For Same Provider (Primary & Secondary)
# -----------------------------------------------------------------------------
def test_03_multiple_profiles_for_same_provider() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()
    # Add secondary Xendit profile
    meta["payment_config"]["credential_profiles"]["cred_xendit_secondary"] = {
        "credential_profile_id": "cred_xendit_secondary",
        "canonical_tenant_id": TENANT_ALPHA_UUID,
        "provider": "XENDIT",
        "verification_method": "XENDIT_CALLBACK_TOKEN",
        "expected_provider_account_id": "xnd_biz_alpha_02",
        "environment": "production",
        "profile_status": "ACTIVE",
        "updated_at_utc": "2026-11-06T00:00:00Z",
        "verification_secrets": [
            {
                "secret_version_id": "xnd_sec_sec_v1",
                "secret_ref": "vault://tenants/alpha/xendit_secondary/active",
                "status": "ACTIVE",
                "created_at_utc": "2026-11-06T00:00:00Z",
            }
        ],
    }

    # Explicit order binding to secondary profile resolves secondary
    res_sec = mapper.resolve_and_verify_callback_secret(
        canonical_tenant_id=TENANT_ALPHA_UUID,
        tenant_metadata=meta,
        order_metadata={"credential_profile_id": "cred_xendit_secondary"},
        provider="XENDIT",
        inbound_account_id="xnd_biz_alpha_02",
        candidate_secret="xendit_secondary_active_secret",
    )
    assert res_sec.credential_profile_id == "cred_xendit_secondary"
    assert res_sec.matched_secret_version_id == "xnd_sec_sec_v1"

    # Explicit order binding to primary profile resolves primary
    res_pri = mapper.resolve_and_verify_callback_secret(
        canonical_tenant_id=TENANT_ALPHA_UUID,
        tenant_metadata=meta,
        order_metadata={"credential_profile_id": "cred_xendit_primary"},
        provider="XENDIT",
        inbound_account_id="xnd_biz_alpha_01",
        candidate_secret="xendit_active_secret_key_v2_strong",
    )
    assert res_pri.credential_profile_id == "cred_xendit_primary"


# -----------------------------------------------------------------------------
# 4. active_provider Decoupling (Checkout Default vs In-Flight Verification)
# -----------------------------------------------------------------------------
def test_04_active_provider_decoupling() -> None:
    mapper = _make_mapper()
    # Tenant currently has active_provider = 'XENDIT'
    meta = _make_multi_provider_tenant_metadata(active_provider="XENDIT")

    # Checkout without provider override defaults to Xendit
    checkout_prof = mapper.resolve_checkout_profile(meta)
    assert checkout_prof.provider == "XENDIT"

    # An in-flight Midtrans order callback MUST succeed even though active_provider is XENDIT
    res_mid = mapper.resolve_and_verify_callback_secret(
        canonical_tenant_id=TENANT_ALPHA_UUID,
        tenant_metadata=meta,
        order_metadata={"credential_profile_id": "cred_midtrans_primary", "provider": "MIDTRANS"},
        provider="MIDTRANS",
        inbound_account_id="G123456789",
        candidate_secret="midtrans_active_server_key_strong_123",
    )
    assert res_mid.provider == "MIDTRANS"
    assert res_mid.credential_profile_id == "cred_midtrans_primary"


# -----------------------------------------------------------------------------
# 5. Explicit Order-Level Profile Binding Takes Precedence
# -----------------------------------------------------------------------------
def test_05_explicit_order_level_profile_binding() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()

    # Order bound explicitly to cred_duitku_primary
    res = mapper.resolve_and_verify_callback_secret(
        canonical_tenant_id=TENANT_ALPHA_UUID,
        tenant_metadata=meta,
        order_metadata={"credential_profile_id": "cred_duitku_primary", "provider": "DUITKU"},
        provider="DUITKU",
        inbound_account_id="D1234",
        candidate_secret="duitku_active_api_key_strong_123456",
    )
    assert res.credential_profile_id == "cred_duitku_primary"
    assert res.expected_provider_account_id == "D1234"


# -----------------------------------------------------------------------------
# 6. Legacy Fallback With Exactly One Matching ACTIVE Profile
# -----------------------------------------------------------------------------
def test_06_legacy_fallback_single_active_profile() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()

    # order_metadata is None or empty dict (transition order)
    res = mapper.resolve_and_verify_callback_secret(
        canonical_tenant_id=TENANT_ALPHA_UUID,
        tenant_metadata=meta,
        order_metadata={},
        provider="MIDTRANS",
        inbound_account_id="G123456789",
        candidate_secret="midtrans_active_server_key_strong_123",
    )
    assert res.credential_profile_id == "cred_midtrans_primary"
    assert res.provider == "MIDTRANS"


# -----------------------------------------------------------------------------
# 7. Legacy Fallback With Zero Or Multiple Matching Profiles
# -----------------------------------------------------------------------------
def test_07_legacy_fallback_zero_or_multiple_profiles() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()

    # Zero matching profiles for a tenant without Duitku
    meta_no_dk = _make_multi_provider_tenant_metadata()
    del meta_no_dk["payment_config"]["credential_profiles"]["cred_duitku_primary"]
    with pytest.raises(PaymentAuthorizationError) as exc_zero:
        mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id=TENANT_ALPHA_UUID,
            tenant_metadata=meta_no_dk,
            order_metadata={},
            provider="DUITKU",
            inbound_account_id="D1234",
            candidate_secret="duitku_active_api_key_strong_123456",
        )
    assert exc_zero.value.error_code == "CREDENTIAL_PROFILE_NOT_FOUND"

    # Multiple matching active profiles without order binding -> AMBIGUOUS
    meta_multi_xnd = _make_multi_provider_tenant_metadata()
    meta_multi_xnd["payment_config"]["credential_profiles"]["cred_xendit_secondary"] = {
        "credential_profile_id": "cred_xendit_secondary",
        "canonical_tenant_id": TENANT_ALPHA_UUID,
        "provider": "XENDIT",
        "verification_method": "XENDIT_CALLBACK_TOKEN",
        "expected_provider_account_id": "xnd_biz_alpha_02",
        "environment": "production",
        "profile_status": "ACTIVE",
        "updated_at_utc": "2026-11-06T00:00:00Z",
        "verification_secrets": [
            {
                "secret_version_id": "xnd_sec_sec_v1",
                "secret_ref": "vault://tenants/alpha/xendit_secondary/active",
                "status": "ACTIVE",
                "created_at_utc": "2026-11-06T00:00:00Z",
            }
        ],
    }
    with pytest.raises(PaymentAuthorizationError) as exc_amb:
        mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id=TENANT_ALPHA_UUID,
            tenant_metadata=meta_multi_xnd,
            order_metadata={},  # No credential_profile_id
            provider="XENDIT",
            inbound_account_id="xnd_biz_alpha_01",
            candidate_secret="xendit_active_secret_key_v2_strong",
        )
    assert exc_amb.value.error_code == "AMBIGUOUS_CREDENTIAL_PROFILE_BINDING"


# -----------------------------------------------------------------------------
# 8. Tenant Mismatch Rejection
# -----------------------------------------------------------------------------
def test_08_tenant_mismatch_rejection() -> None:
    mapper = _make_mapper()
    # Metadata for Tenant Alpha accidentally containing profile configured for Tenant Beta
    bad_meta = _make_multi_provider_tenant_metadata(tenant_uuid=TENANT_ALPHA_UUID)
    bad_meta["payment_config"]["credential_profiles"]["cred_rogue"] = {
        "credential_profile_id": "cred_rogue",
        "canonical_tenant_id": TENANT_BETA_UUID,  # Mismatched tenant
        "provider": "XENDIT",
        "verification_method": "XENDIT_CALLBACK_TOKEN",
        "expected_provider_account_id": "xnd_biz_beta",
        "environment": "production",
        "profile_status": "ACTIVE",
        "updated_at_utc": "2026-11-06T00:00:00Z",
        "verification_secrets": [
            {
                "secret_version_id": "rogue_v1",
                "secret_ref": "vault://tenants/beta/xendit/active",
                "status": "ACTIVE",
                "created_at_utc": "2026-11-06T00:00:00Z",
            }
        ],
    }

    with pytest.raises(PaymentAuthorizationError) as exc:
        mapper.parse_profiles_from_metadata(bad_meta, expected_canonical_tenant_id=TENANT_ALPHA_UUID)
    assert exc.value.error_code == "CREDENTIAL_PROFILE_TENANT_MISMATCH"


# -----------------------------------------------------------------------------
# 9. Inactive Profile Rejection (SUSPENDED / REVOKED)
# -----------------------------------------------------------------------------
def test_09_inactive_profile_rejection() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()
    # Mark Midtrans profile SUSPENDED
    meta["payment_config"]["credential_profiles"]["cred_midtrans_primary"]["profile_status"] = "SUSPENDED"

    with pytest.raises(PaymentAuthorizationError) as exc:
        mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id=TENANT_ALPHA_UUID,
            tenant_metadata=meta,
            order_metadata={"credential_profile_id": "cred_midtrans_primary"},
            provider="MIDTRANS",
            inbound_account_id="G123456789",
            candidate_secret="midtrans_active_server_key_strong_123",
        )
    assert exc.value.error_code == "CREDENTIAL_PROFILE_INACTIVE"


# -----------------------------------------------------------------------------
# 10. Secret Pointer Resolution (env:// and vault:// explicit semantics)
# -----------------------------------------------------------------------------
def test_10_secret_pointer_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    vault = {"vault://keys/mock_key": "vault_secret_val_12345"}
    mapper = _make_mapper(vault=vault)

    # vault:// pointer resolution
    assert mapper._resolve_secret_ref("vault://keys/mock_key") == "vault_secret_val_12345"

    # env:// pointer resolution
    monkeypatch.setenv("TEST_GATEWAY_TOKEN", "env_secret_val_67890")
    assert mapper._resolve_secret_ref("env://TEST_GATEWAY_TOKEN") == "env_secret_val_67890"

    # Missing vault pointer fails closed with 503
    with pytest.raises(PaymentAuthorizationError) as exc_v:
        mapper._resolve_secret_ref("vault://keys/nonexistent")
    assert exc_v.value.error_code == "CREDENTIAL_SECRET_UNAVAILABLE"
    assert exc_v.value.http_status == 503

    # Missing env pointer fails closed with 503
    with pytest.raises(PaymentAuthorizationError) as exc_e:
        mapper._resolve_secret_ref("env://UNSET_ENV_VAR")
    assert exc_e.value.error_code == "CREDENTIAL_SECRET_UNAVAILABLE"

    # Plaintext / unknown scheme fails closed
    with pytest.raises(PaymentAuthorizationError) as exc_u:
        mapper._resolve_secret_ref("raw_plaintext_secret_123")
    assert exc_u.value.error_code == "CREDENTIAL_SECRET_UNAVAILABLE"


# -----------------------------------------------------------------------------
# 11. Zero Plaintext Secret Leakage in Results and Audit Data
# -----------------------------------------------------------------------------
def test_11_zero_plaintext_secret_leakage() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()

    res = mapper.resolve_and_verify_callback_secret(
        canonical_tenant_id=TENANT_ALPHA_UUID,
        tenant_metadata=meta,
        order_metadata={"credential_profile_id": "cred_xendit_primary"},
        provider="XENDIT",
        inbound_account_id="xnd_biz_alpha_01",
        candidate_secret="xendit_active_secret_key_v2_strong",
    )
    # Result object has no matched_secret_value attribute
    assert not hasattr(res, "matched_secret_value")

    # Audit entry dictionary has zero secret material
    audit_str = str(res.audit_entry)
    assert "xendit_active_secret_key_v2_strong" not in audit_str
    assert "secret" not in audit_str.lower() or "secret_version_id" in audit_str


# -----------------------------------------------------------------------------
# 12. ACTIVE Secret Verification
# -----------------------------------------------------------------------------
def test_12_active_secret_verification() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()

    res = mapper.resolve_and_verify_callback_secret(
        canonical_tenant_id=TENANT_ALPHA_UUID,
        tenant_metadata=meta,
        order_metadata={},
        provider="XENDIT",
        inbound_account_id="xnd_biz_alpha_01",
        candidate_secret="xendit_active_secret_key_v2_strong",
    )
    assert res.matched_secret_version_id == "xnd_sec_v2"
    assert res.matched_secret_status == "ACTIVE"


# -----------------------------------------------------------------------------
# 13. VERIFY_ONLY Grace Period Verification
# -----------------------------------------------------------------------------
def test_13_verify_only_grace_period_verification() -> None:
    mapper = _make_mapper(clock_dt=MOCK_NOW_DT)
    meta = _make_multi_provider_tenant_metadata()

    # candidate_secret matches xnd_sec_v1 (status VERIFY_ONLY with not_after_epoch = NOW + 3600)
    res = mapper.resolve_and_verify_callback_secret(
        canonical_tenant_id=TENANT_ALPHA_UUID,
        tenant_metadata=meta,
        order_metadata={},
        provider="XENDIT",
        inbound_account_id="xnd_biz_alpha_01",
        candidate_secret="xendit_grace_secret_key_v1_strong",
    )
    assert res.matched_secret_version_id == "xnd_sec_v1"
    assert res.matched_secret_status == "VERIFY_ONLY"


# -----------------------------------------------------------------------------
# 14. Expired VERIFY_ONLY Rejection
# -----------------------------------------------------------------------------
def test_14_expired_verify_only_rejection() -> None:
    # Clock advanced past not_after_epoch (NOW + 7200 > NOW + 3600)
    expired_dt = datetime.fromtimestamp(MOCK_NOW_EPOCH + 7200, tz=timezone.utc)
    mapper = _make_mapper(clock_dt=expired_dt)
    meta = _make_multi_provider_tenant_metadata()

    with pytest.raises(PaymentAuthorizationError) as exc:
        mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id=TENANT_ALPHA_UUID,
            tenant_metadata=meta,
            order_metadata={},
            provider="XENDIT",
            inbound_account_id="xnd_biz_alpha_01",
            candidate_secret="xendit_grace_secret_key_v1_strong",
        )
    assert exc.value.error_code == "EXPIRED_CREDENTIAL_SECRET_VERSION"


# -----------------------------------------------------------------------------
# 15. REVOKED Secret Rejection
# -----------------------------------------------------------------------------
def test_15_revoked_secret_rejection() -> None:
    mapper = _make_mapper()
    meta = _make_multi_provider_tenant_metadata()

    # candidate_secret matches xnd_sec_v0 (status REVOKED)
    with pytest.raises(PaymentAuthorizationError) as exc:
        mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id=TENANT_ALPHA_UUID,
            tenant_metadata=meta,
            order_metadata={},
            provider="XENDIT",
            inbound_account_id="xnd_biz_alpha_01",
            candidate_secret="xendit_compromised_secret_key_v0",
        )
    assert exc.value.error_code == "REVOKED_CREDENTIAL_SECRET_VERSION"


# -----------------------------------------------------------------------------
# 16. Environment Mismatch Rejection
# -----------------------------------------------------------------------------
def test_16_environment_mismatch_rejection() -> None:
    # Mapper running in production mode
    mapper = _make_mapper(runtime_env="production")
    meta = _make_multi_provider_tenant_metadata()
    # Mark profile as sandbox
    meta["payment_config"]["credential_profiles"]["cred_xendit_primary"]["environment"] = "sandbox"

    with pytest.raises(PaymentAuthorizationError) as exc:
        mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id=TENANT_ALPHA_UUID,
            tenant_metadata=meta,
            order_metadata={},
            provider="XENDIT",
            inbound_account_id="xnd_biz_alpha_01",
            candidate_secret="xendit_active_secret_key_v2_strong",
        )
    assert exc.value.error_code == "CREDENTIAL_PROFILE_ENVIRONMENT_MISMATCH"


# -----------------------------------------------------------------------------
# 17. Unknown Provider And Malformed Profile Rejection
# -----------------------------------------------------------------------------
def test_17_unknown_provider_and_malformed_profile() -> None:
    mapper = _make_mapper()

    # Unsupported provider
    with pytest.raises(PaymentConfigurationError) as exc_p:
        mapper.resolve_checkout_profile(_make_multi_provider_tenant_metadata(), requested_provider="STRIPE")
    assert exc_p.value.error_code == "UNSUPPORTED_PAYMENT_PROVIDER"

    # Plaintext secret directly in profile dict is strictly rejected
    bad_meta = {
        "payment_config": {
            "credential_profiles": {
                "cred_insecure": {
                    "credential_profile_id": "cred_insecure",
                    "canonical_tenant_id": TENANT_ALPHA_UUID,
                    "provider": "XENDIT",
                    "secret_key": "plaintext_secret_forbidden",  # Raw plaintext
                    "verification_secrets": [],
                }
            }
        }
    }
    with pytest.raises(PaymentAuthorizationError) as exc_raw:
        mapper.parse_profiles_from_metadata(bad_meta)
    assert exc_raw.value.error_code == "INVALID_CREDENTIAL_PROFILE"


# -----------------------------------------------------------------------------
# 18. Cross-Tenant Profile Access Rejection
# -----------------------------------------------------------------------------
def test_18_cross_tenant_profile_access_rejection() -> None:
    mapper = _make_mapper()
    alpha_meta = _make_multi_provider_tenant_metadata(tenant_uuid=TENANT_ALPHA_UUID)

    # Order owned by Tenant Beta attempts to resolve using Tenant Alpha's metadata
    with pytest.raises(PaymentAuthorizationError) as exc:
        mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id=TENANT_BETA_UUID,  # Caller is Tenant Beta
            tenant_metadata=alpha_meta,           # Metadata contains Alpha's profiles
            order_metadata={"credential_profile_id": "cred_xendit_primary"},
            provider="XENDIT",
            inbound_account_id="xnd_biz_alpha_01",
            candidate_secret="xendit_active_secret_key_v2_strong",
        )
    # Rejection occurs because profile belongs to Alpha, not Beta
    assert exc.value.error_code in ("CREDENTIAL_PROFILE_TENANT_MISMATCH", "CREDENTIAL_PROFILE_NOT_FOUND")


# -----------------------------------------------------------------------------
# Standalone CLI Test Runner
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        test_01_canonical_uuid_validation,
        test_02_three_providers_active_under_one_tenant,
        test_03_multiple_profiles_for_same_provider,
        test_04_active_provider_decoupling,
        test_05_explicit_order_level_profile_binding,
        test_06_legacy_fallback_single_active_profile,
        test_07_legacy_fallback_zero_or_multiple_profiles,
        test_08_tenant_mismatch_rejection,
        test_09_inactive_profile_rejection,
        test_10_secret_pointer_resolution,
        test_11_zero_plaintext_secret_leakage,
        test_12_active_secret_verification,
        test_13_verify_only_grace_period_verification,
        test_14_expired_verify_only_rejection,
        test_15_revoked_secret_rejection,
        test_16_environment_mismatch_rejection,
        test_17_unknown_provider_and_malformed_profile,
        test_18_cross_tenant_profile_access_rejection,
    ]

    failed = 0
    import unittest.mock
    for t in tests:
        try:
            if "monkeypatch" in t.__code__.co_varnames:
                # Provide lightweight monkeypatch for standalone execution
                class SimpleMonkeyPatch:
                    def setenv(self, k: str, v: str) -> None:
                        os.environ[k] = v
                t(SimpleMonkeyPatch())
            else:
                t()
            print(f"PASSED [{t.__name__}]")
        except Exception as err:
            failed += 1
            print(f"FAILED [{t.__name__}]: {err}")

    if failed == 0:
        print(f"\nALL {len(tests)} STEP 2A UNIT TESTS PASSED (EXIT_CODE=0)")
        sys.exit(0)
    else:
        print(f"\n{failed}/{len(tests)} TESTS FAILED (EXIT_CODE=1)")
        sys.exit(1)
