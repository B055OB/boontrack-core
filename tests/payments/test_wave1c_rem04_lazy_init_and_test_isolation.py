"""tests/payments/test_wave1c_rem04_lazy_init_and_test_isolation.py
Wave 1C (REM-04) Regression Test Suite:
1. Lazy initialization of `XenditService` eliminating import-time crashes when env vars are absent.
2. Transparent proxy compatibility for existing callers of `xendit_service`.
3. Runtime synthetic Ed25519 test keypair fixture verification (zero keys in `.env.test`).
4. Strict `.env.test` baseline hash verification (exact match to pre-Wave-1A baseline).
5. Live `.env` isolation and secret hygiene validation.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from app.core.security.provenance_authority import (
    ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
    ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
    ProvenanceSigningKeyring,
    ProvenanceVerificationKeyring,
    ProvenanceSigner,
    ProvenanceVerifier,
    SettlementProvenanceError,
    PROVENANCE_CONTRACT_FIELDS,
    PROVENANCE_SCHEMA_VERSION,
    TrustedSettlementVerificationBoundary,
    VerifiedSettlementCapability,
)
from app.core.security.test_isolation_guard import (
    is_strict_test_guard_active,
    safe_load_dotenv,
)
from app.services.xendit_service import (
    XenditService,
    get_xendit_service,
    reset_xendit_service,
    xendit_service,
    _LazyXenditServiceProxy,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXPECTED_ENV_TEST_SHA256 = "099F530F78EFEC55D4415FC9138B3527F6872126B259BD288433C469B2931944"


# =============================================================================
# 1. Lazy Initialization of XenditService
# =============================================================================

def test_rem04_lazy_init_import_in_clean_subprocess_without_env_vars() -> None:
    """Proves that importing `app.services.xendit_service` in a process with ZERO Xendit
    environment variables succeeds without import-time crashes.
    """
    code = """
import os, sys
os.environ["TEST_STRICT_DB_GUARD"] = "1"
for k in list(os.environ.keys()):
    if "XENDIT" in k:
        del os.environ[k]

import app.services.xendit_service as xs

assert isinstance(xs.xendit_service, xs.XenditService), "Proxy must report isinstance(XenditService)"
assert isinstance(xs.xendit_service, xs._LazyXenditServiceProxy), "Must be lazy proxy"

# Accessing attributes without keys fails closed with ValueError
try:
    _ = xs.xendit_service.secret_key
    print("FAILED_SHOULD_HAVE_RAISED")
    sys.exit(1)
except ValueError as e:
    assert "[SECURITY FAIL-CLOSED]" in str(e), f"Unexpected message: {e}"
    sys.exit(0)
"""
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(_REPO_ROOT))
    assert res.returncode == 0, f"Subprocess failed with code {res.returncode}:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


def test_rem04_lazy_init_runtime_configuration_and_state_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves proxy behavior: fail-closed before configuration, succeeds after configuration,
    and resets cleanly on `reset_xendit_service()`.
    """
    monkeypatch.delenv("XENDIT_SECRET_KEY", raising=False)
    monkeypatch.delenv("XENDIT_CALLBACK_TOKEN", raising=False)
    monkeypatch.delenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN", raising=False)
    reset_xendit_service()

    # 1. Unconfigured state: accessing attribute raises ValueError
    with pytest.raises(ValueError) as exc_info:
        _ = xendit_service.secret_key
    assert "[SECURITY FAIL-CLOSED]" in str(exc_info.value)
    assert "XENDIT_SECRET_KEY" in str(exc_info.value)

    # 2. Configure dummy valid test credentials
    monkeypatch.setenv("XENDIT_SECRET_KEY", "xnd_development_rem04_dummy_test_key")
    monkeypatch.setenv("XENDIT_CALLBACK_TOKEN", "rem04_test_callback_token_123")
    reset_xendit_service()

    # 3. Accessing attributes now succeeds
    assert xendit_service.secret_key == "xnd_development_rem04_dummy_test_key"
    assert xendit_service.callback_token == "rem04_test_callback_token_123"
    auth_hdr = xendit_service.get_auth_header()
    assert auth_hdr.startswith("Basic ")

    # 4. State manipulation works through proxy
    xendit_service.clear_state()
    assert len(xendit_service._intents_by_external_id) == 0

    # 5. Reset works cleanly
    reset_xendit_service()


def test_rem04_dir_does_not_instantiate_xendit_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that dir(xendit_service) performs introspection without triggering lazy initialization,
    even when XENDIT_* environment variables are completely unset.
    """
    import app.services.xendit_service as xs

    monkeypatch.delenv("XENDIT_SECRET_KEY", raising=False)
    monkeypatch.delenv("XENDIT_CALLBACK_TOKEN", raising=False)
    monkeypatch.delenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN", raising=False)
    xs.reset_xendit_service()

    assert xs._xendit_service_instance is None, "Precondition: instance must be uninitialized"

    # dir() should not raise ValueError and should not instantiate the service
    listing = dir(xs.xendit_service)
    assert "create_dynamic_qris" in listing
    assert "create_qr_code" in listing
    assert "get_auth_header" in listing
    assert "clear_state" in listing
    assert xs._xendit_service_instance is None, "dir(xendit_service) must NEVER trigger instantiation!"


def test_rem04_concurrent_multithreaded_get_xendit_service_creates_single_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that concurrent multi-threaded access to get_xendit_service() uses double-checked
    locking, ensuring that exactly one XenditService instance is created and returned across all threads.
    """
    import concurrent.futures
    import app.services.xendit_service as xs

    monkeypatch.setenv("XENDIT_SECRET_KEY", "xnd_development_threaded_test_key")
    monkeypatch.setenv("XENDIT_CALLBACK_TOKEN", "threaded_test_token_123")
    xs.reset_xendit_service()

    instances = []
    def _fetch_instance():
        return xs.get_xendit_service()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_fetch_instance) for _ in range(30)]
        for fut in concurrent.futures.as_completed(futures):
            instances.append(fut.result())

    assert len(instances) == 30
    first_id = id(instances[0])
    for inst in instances:
        assert id(inst) == first_id, "All concurrent threads must receive the identical singleton instance!"

    xs.reset_xendit_service()


# =============================================================================
# 2. Surgical Restoration of .env.test (Zero Provenance Keys & Exact Baseline Hash)
# =============================================================================

def test_rem04_env_test_file_contains_zero_provenance_keys() -> None:
    """Proves that .env.test on disk contains ZERO private keys and ZERO provenance keyring lines."""
    env_test_path = _REPO_ROOT / ".env.test"
    assert env_test_path.is_file(), ".env.test must exist"

    raw_bytes = env_test_path.read_bytes()
    raw_text = raw_bytes.decode("utf-8")

    assert ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING not in raw_text, (
        f"{ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING} must NOT be present in .env.test"
    )
    assert ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING not in raw_text, (
        f"{ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING} must NOT be present in .env.test"
    )
    assert "-----BEGIN" not in raw_text, "No PEM private key block allowed in .env.test"
    assert "PRIVATE KEY" not in raw_text, "No raw private key material allowed in .env.test"


def test_rem04_env_test_sha256_exact_match_to_pre_wave1a_baseline() -> None:
    """Proves that .env.test SHA-256 matches the pre-Wave-1A baseline reference exactly."""
    env_test_path = _REPO_ROOT / ".env.test"
    actual_hash = hashlib.sha256(env_test_path.read_bytes()).hexdigest().upper()
    assert actual_hash == _EXPECTED_ENV_TEST_SHA256, (
        f".env.test SHA-256 drift detected! Actual: {actual_hash}, Expected: {_EXPECTED_ENV_TEST_SHA256}"
    )


# =============================================================================
# 3. Runtime Synthetic Ed25519 Keypair Fixture Verification
# =============================================================================

def test_rem04_runtime_synthetic_provenance_keypair_validity(runtime_synthetic_provenance_keypair: Dict[str, str]) -> None:
    """Proves that the runtime synthetic fixture produces valid, active, non-empty Ed25519 keyrings."""
    priv_json = runtime_synthetic_provenance_keypair["private_keyring_json"]
    pub_json = runtime_synthetic_provenance_keypair["public_keyring_json"]

    assert priv_json and pub_json
    priv_data = json.loads(priv_json)
    pub_data = json.loads(pub_json)

    assert "prv_synthetic_test_v1" in priv_data
    assert "prv_synthetic_test_v1" in pub_data

    priv_entry = priv_data["prv_synthetic_test_v1"]
    pub_entry = pub_data["prv_synthetic_test_v1"]

    assert priv_entry["status"] == "ACTIVE"
    assert pub_entry["status"] == "ACTIVE"
    assert len(priv_entry["private_key_hex"]) == 64
    assert len(pub_entry["public_key_hex"]) == 64


def test_rem04_runtime_keypair_signs_and_verifies_valid_settlement() -> None:
    """Proves that runtime synthetic keyrings can sign and verify a 17-field provenance envelope."""
    skr = ProvenanceSigningKeyring.from_env()
    vkr = ProvenanceVerificationKeyring.from_env()

    signer = ProvenanceSigner(skr)
    verifier = ProvenanceVerifier(vkr)

    test_biz_id = "xnd_biz_synthetic_001"
    test_secret = "test_synthetic_token_123"

    capability = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="XENDIT",
        verification_method="XENDIT_CALLBACK_TOKEN",
        credential_profile_id="cp_test_synthetic",
        expected_provider_account_id=test_biz_id,
        provider_verification_secret=test_secret,
        webhook_headers={"x-callback-token": test_secret},
        webhook_payload={
            "id": "evt_test_synthetic_1",
            "event_id": "evt_test_synthetic_1",
            "business_id": test_biz_id,
            "status": "SUCCEEDED",
            "amount": 250000,
        },
        authoritative_order_id="ORD-TEST-SYNTHETIC-001",
        authoritative_canonical_tenant_id="00000000-0000-0000-0000-000000000001",
        authoritative_order_amount=250000,
        authoritative_sku_id="test-sku-synthetic",
        verified_at_utc="2026-11-19T05:00:00Z",
    )

    envelope = signer.sign_verified_settlement(capability)
    assert envelope["algorithm"] == "Ed25519"
    assert len(envelope["signature"]) == 128
    assert set(envelope["fields"].keys()) == set(PROVENANCE_CONTRACT_FIELDS)

    verified = verifier.verify_provenance_envelope(
        envelope,
        expected_order_id="ORD-TEST-SYNTHETIC-001",
        expected_canonical_tenant_id="00000000-0000-0000-0000-000000000001",
        expected_amount=250000,
        expected_sku_id="test-sku-synthetic",
        required_rail_type="NATIVE_PG",
    )
    assert verified["verified_amount"] == 250000


def test_rem04_monkeypatch_override_compatibility_with_rem02(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves full compatibility with REM-02 tests: when a test monkeypatches delenv,
    the keyring is observed as missing, raising 503 / MISSING_PROVENANCE_SIGNING_KEYRING.
    """
    monkeypatch.delenv(ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING, raising=False)
    with pytest.raises(SettlementProvenanceError) as exc_info:
        ProvenanceSigningKeyring.from_env()
    assert exc_info.value.error_code == "MISSING_PROVENANCE_SIGNING_KEYRING"


# =============================================================================
# 4. Test Environment Isolation & Secret Hygiene
# =============================================================================

def test_rem04_test_isolation_guard_is_active_and_blocks_root_env() -> None:
    """Proves that test isolation guard is active and safe_load_dotenv refuses root .env."""
    assert is_strict_test_guard_active(), "Strict test guard must be active during tests"

    # Attempting to load root .env must be rejected
    loaded = safe_load_dotenv(dotenv_path=str(_REPO_ROOT / ".env"))
    assert loaded is False, "safe_load_dotenv must refuse loading root .env under test guard"


def test_rem04_zero_live_production_credentials_in_environment() -> None:
    """Proves that no live production Xendit or Midtrans credentials exist in os.environ."""
    for k, v in os.environ.items():
        v_str = str(v)
        assert "xnd_production_" not in v_str, f"Leaked live Xendit production key in env var '{k}'"
        assert "Mid-server-" not in v_str, f"Leaked live Midtrans production key in env var '{k}'"
