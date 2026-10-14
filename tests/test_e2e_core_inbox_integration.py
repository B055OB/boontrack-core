"""tests/test_e2e_core_inbox_integration.py
CTO Directive 10 (P1-C):
End-to-End Core <-> Inbox Integration & Signed Boundary Verification Test Suite.

Proves:
1. End-to-end HTTP exchange between Inbox and Core using cryptographic HMAC-SHA256 signatures.
2. Tenant tampering detection (payload or query param manipulation raises HTTP 403 TENANT_BOUNDARY_MISMATCH).
3. Anti-replay defense (timestamps drifting > 300 seconds are rejected with HTTP 401).
4. Payload claim integrity (modified body with original signature is rejected with HTTP 401 SIGNATURE_MISMATCH).
5. Missing or malformed authentication headers rejected with HTTP 401.
"""

import os
import time
import json
import pytest
from fastapi import FastAPI, Depends, Request, status
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.security.inter_service_auth import (
    generate_inter_service_signature,
    verify_inter_service_signature,
    verify_inter_service_tenant_boundary,
    get_hmac_secret,
)

# Setup isolated test FastAPI application
app = FastAPI(title="Core-Inbox-E2E-Test-Gateway")


@app.post("/api/v1/inbox/sync")
async def inbox_sync_endpoint(
    request: Request,
    tenant_id: str = Depends(verify_inter_service_tenant_boundary),
):
    body = await request.json()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "SYNCED", "tenant_id": tenant_id, "action": body.get("action")},
    )


@app.post("/api/v1/inbox/dispatch")
async def inbox_dispatch_endpoint(
    request: Request,
    tenant_id: str = Depends(verify_inter_service_tenant_boundary),
):
    body = await request.json()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "DISPATCHED", "tenant_id": tenant_id, "recipient": body.get("recipient")},
    )


client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_hmac_env(monkeypatch):
    monkeypatch.setenv("BOONTRACK_HMAC_SECRET", "test_ci_secure_hmac_secret_for_pipeline_999")


# -----------------------------------------------------------------------------
# 1. Positive Scenario: Valid E2E Signed Inter-Service Request
# -----------------------------------------------------------------------------
def test_e2e_inbox_core_valid_signed_request():
    """Valid Inbox request with fresh timestamp and authentic HMAC signature succeeds with 200 OK."""
    tenant_id = "tenant_alpha"
    payload = {"tenant_id": tenant_id, "action": "sync_chat", "session_id": "sess_123"}
    raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig, ts, _ = generate_inter_service_signature(authenticated_tenant_id=tenant_id, body=raw_bytes)

    headers = {
        "X-Boontrack-Signature": sig,
        "X-Boontrack-Timestamp": str(ts),
        "X-Boontrack-Tenant-Id": tenant_id,
        "Content-Type": "application/json",
    }

    response = client.post("/api/v1/inbox/sync", content=raw_bytes, headers=headers)
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "SYNCED"
    assert data["tenant_id"] == tenant_id
    assert data["action"] == "sync_chat"


# -----------------------------------------------------------------------------
# 2. Negative Scenario: Tenant Tampering in Body (Alpha -> Beta)
# -----------------------------------------------------------------------------
def test_e2e_inbox_core_tenant_tampering_rejected_403():
    """Header signs for Tenant Alpha, but payload attempts to target Tenant Beta. Must fail with HTTP 403."""
    auth_tenant = "tenant_alpha"
    tampered_payload = {"tenant_id": "tenant_beta", "action": "exfiltrate_messages"}
    raw_bytes = json.dumps(tampered_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig, ts, _ = generate_inter_service_signature(authenticated_tenant_id=auth_tenant, body=raw_bytes)

    headers = {
        "X-Boontrack-Signature": sig,
        "X-Boontrack-Timestamp": str(ts),
        "X-Boontrack-Tenant-Id": auth_tenant,
        "Content-Type": "application/json",
    }

    response = client.post("/api/v1/inbox/sync", content=raw_bytes, headers=headers)
    assert response.status_code == 403, f"Expected 403 Forbidden, got {response.status_code}"
    detail = response.json().get("detail", {})
    assert detail.get("error") == "TENANT_BOUNDARY_MISMATCH"
    assert detail.get("authenticated_tenant") == auth_tenant
    assert detail.get("attempted_tenant") == "tenant_beta"


# -----------------------------------------------------------------------------
# 3. Negative Scenario: Tenant Tampering in Query String (Alpha -> Beta)
# -----------------------------------------------------------------------------
def test_e2e_inbox_core_query_param_tenant_tampering_rejected_403():
    """Query parameter injection (?tenant_id=tenant_beta) is intercepted and rejected with HTTP 403."""
    auth_tenant = "tenant_alpha"
    payload = {"action": "list_contacts"}
    sig, ts, _ = generate_inter_service_signature(authenticated_tenant_id=auth_tenant, body=payload)

    headers = {
        "X-Boontrack-Signature": sig,
        "X-Boontrack-Timestamp": str(ts),
        "X-Boontrack-Tenant-Id": auth_tenant,
        "Content-Type": "application/json",
    }

    response = client.post("/api/v1/inbox/sync?tenant_id=tenant_beta", json=payload, headers=headers)
    assert response.status_code == 403
    detail = response.json().get("detail", {})
    assert detail.get("error") == "TENANT_BOUNDARY_MISMATCH"


# -----------------------------------------------------------------------------
# 4. Negative Scenario: Anti-Replay Defense (Timestamp Drift > 300s)
# -----------------------------------------------------------------------------
def test_e2e_inbox_core_anti_replay_past_drift_rejected_401():
    """Timestamp older than 300 seconds is strictly rejected with HTTP 401 TIMESTAMP_DRIFT_EXCEEDED."""
    tenant_id = "tenant_alpha"
    payload = {"tenant_id": tenant_id, "action": "replayed_action"}
    expired_ts = int(time.time()) - 350  # 350s ago (> 300s)
    sig, _, _ = generate_inter_service_signature(authenticated_tenant_id=tenant_id, body=payload, timestamp=expired_ts)

    headers = {
        "X-Boontrack-Signature": sig,
        "X-Boontrack-Timestamp": str(expired_ts),
        "X-Boontrack-Tenant-Id": tenant_id,
        "Content-Type": "application/json",
    }

    response = client.post("/api/v1/inbox/sync", json=payload, headers=headers)
    assert response.status_code == 401
    detail = response.json().get("detail", {})
    assert detail.get("error") == "INVALID_INTER_SERVICE_SIGNATURE"
    assert "TIMESTAMP_DRIFT_EXCEEDED" in detail.get("reason", "")


def test_e2e_inbox_core_anti_replay_future_drift_rejected_401():
    """Timestamp drifting into future (> 300s) is strictly rejected with HTTP 401."""
    tenant_id = "tenant_alpha"
    payload = {"tenant_id": tenant_id, "action": "future_action"}
    future_ts = int(time.time()) + 400  # 400s into future
    sig, _, _ = generate_inter_service_signature(authenticated_tenant_id=tenant_id, body=payload, timestamp=future_ts)

    headers = {
        "X-Boontrack-Signature": sig,
        "X-Boontrack-Timestamp": str(future_ts),
        "X-Boontrack-Tenant-Id": tenant_id,
        "Content-Type": "application/json",
    }

    response = client.post("/api/v1/inbox/sync", json=payload, headers=headers)
    assert response.status_code == 401
    assert "TIMESTAMP_DRIFT_EXCEEDED" in response.json().get("detail", {}).get("reason", "")


# -----------------------------------------------------------------------------
# 5. Negative Scenario: Payload Claim Mismatch (Altered Body)
# -----------------------------------------------------------------------------
def test_e2e_inbox_core_payload_claim_mismatch_rejected_401():
    """Signature generated for original payload, but body is altered in transit. Rejected with 401."""
    tenant_id = "tenant_alpha"
    original_payload = {"tenant_id": tenant_id, "amount": 50000}
    altered_payload = {"tenant_id": tenant_id, "amount": 999999999}

    # Signature signed over original payload
    sig, ts, _ = generate_inter_service_signature(authenticated_tenant_id=tenant_id, body=original_payload)

    headers = {
        "X-Boontrack-Signature": sig,
        "X-Boontrack-Timestamp": str(ts),
        "X-Boontrack-Tenant-Id": tenant_id,
        "Content-Type": "application/json",
    }

    # Transmit altered payload
    response = client.post("/api/v1/inbox/sync", json=altered_payload, headers=headers)
    assert response.status_code == 401
    detail = response.json().get("detail", {})
    assert detail.get("error") == "INVALID_INTER_SERVICE_SIGNATURE"
    assert detail.get("reason") == "SIGNATURE_MISMATCH"


# -----------------------------------------------------------------------------
# 6. Negative Scenario: Missing Auth Headers
# -----------------------------------------------------------------------------
def test_e2e_inbox_core_missing_headers_rejected_401():
    """Missing any mandatory HMAC header is rejected immediately with 401."""
    payload = {"action": "ping"}

    # Missing signature
    resp = client.post(
        "/api/v1/inbox/sync",
        json=payload,
        headers={"X-Boontrack-Timestamp": str(int(time.time())), "X-Boontrack-Tenant-Id": "tenant_alpha"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "MISSING_INTER_SERVICE_AUTH_HEADERS"

    # Missing tenant id
    resp2 = client.post(
        "/api/v1/inbox/sync",
        json=payload,
        headers={"X-Boontrack-Signature": "abc", "X-Boontrack-Timestamp": str(int(time.time()))},
    )
    assert resp2.status_code == 401


# -----------------------------------------------------------------------------
# 7. Negative Scenario: Forged Key Signature
# -----------------------------------------------------------------------------
def test_e2e_inbox_core_forged_key_rejected_401(monkeypatch):
    """Signature generated with an attacker-controlled key is rejected with 401."""
    tenant_id = "tenant_alpha"
    payload = {"tenant_id": tenant_id, "action": "dispatch", "recipient": "628999999"}

    # Attacker signs with bogus secret
    monkeypatch.setenv("BOONTRACK_HMAC_SECRET", "attacker_fake_forged_key_12345")
    attacker_sig, ts, _ = generate_inter_service_signature(authenticated_tenant_id=tenant_id, body=payload)

    # Server receives with real secret
    monkeypatch.setenv("BOONTRACK_HMAC_SECRET", "test_ci_secure_hmac_secret_for_pipeline_999")

    headers = {
        "X-Boontrack-Signature": attacker_sig,
        "X-Boontrack-Timestamp": str(ts),
        "X-Boontrack-Tenant-Id": tenant_id,
        "Content-Type": "application/json",
    }

    response = client.post("/api/v1/inbox/dispatch", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "SIGNATURE_MISMATCH"
