"""tests/test_contract_inbox_core_boundary.py
========================================================================================
CTO MANDATE: INBOX <-> CORE INTER-SERVICE PROCESS BOUNDARY CONTRACT TEST SUITE
========================================================================================
Simulates genuine Inbox client sender and Core receiver to verify the cryptographic
contract across process boundaries (ARCHITECTURE.md §8.9 & §10.1):

Guarantees:
1. Genuine Inbox client cryptographically signs outbound payload with HMAC-SHA256
   using tenant bound to verified session context.
2. Core receiver verifies signature, timestamp, and tenant boundary with 200 OK.
3. Rejection Tests (Fail-Secure Gate):
   a. Body manipulation in transit -> HTTP 401 (SIGNATURE_MISMATCH).
   b. Tenant header vs payload body mismatch -> HTTP 403 (TENANT_BOUNDARY_MISMATCH).
   c. Past timestamp drift > 300s -> HTTP 401 (TIMESTAMP_DRIFT_EXCEEDED).
   d. Future timestamp drift > 300s -> HTTP 401 (TIMESTAMP_DRIFT_EXCEEDED).
   e. Unset/empty secret -> Fatal ValueError (Fail-Closed).
   f. Replay attack outside validity window -> Rejected.
========================================================================================
"""

import os
import time
import json
import pytest
from typing import Dict, Any, Tuple, Optional
from fastapi.testclient import TestClient

# Ensure test DB environment is configured
if not os.getenv("DATABASE_URL"):
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "postgres")
    pg_host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB", "postgres")
    os.environ["DATABASE_URL"] = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

if not os.getenv("XENDIT_SECRET_KEY"):
    os.environ["XENDIT_SECRET_KEY"] = "test_ci_xendit_secret_key_mock_12345"
if not os.getenv("XENDIT_CALLBACK_TOKEN"):
    os.environ["XENDIT_CALLBACK_TOKEN"] = "test_ci_xendit_callback_token_mock_12345"
if not os.getenv("SUPABASE_URL"):
    os.environ["SUPABASE_URL"] = "https://mpluzajlzpregmjwpjqr.supabase.co"
if not os.getenv("SUPABASE_KEY"):
    os.environ["SUPABASE_KEY"] = "test_ci_supabase_anon_key_mock_999"
if not os.getenv("SUPABASE_ANON_KEY"):
    os.environ["SUPABASE_ANON_KEY"] = "test_ci_supabase_anon_key_mock_999"
if not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test_ci_supabase_service_role_key_mock_999"

from app.main import app
from app.core.security.inter_service_auth import (
    generate_inter_service_signature,
    create_inter_service_signed_headers,
    verify_inter_service_signature,
    enforce_tenant_boundary,
    get_hmac_secret,
    replay_guard,
)


class OfficialInboxClientSigner:
    """Authoritative outbound signer representing the actual Inbox client adapter.
    Uses official create_inter_service_signed_headers module to guarantee identical contract.
    """

    def __init__(self, tenant_id: str, operator_id: str = "cs_agent_001"):
        self.session_tenant_id = str(tenant_id).strip()
        self.operator_id = str(operator_id).strip()

    def build_signed_request(
        self,
        payload: Dict[str, Any],
        tamper_body_bytes: Optional[bytes] = None,
        custom_header_tenant: Optional[str] = None,
        timestamp_offset_seconds: float = 0.0,
        request_id: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, str]]:
        """Constructs canonical signed request package using official inter-service signer."""
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

        sig_tenant = custom_header_tenant or self.session_tenant_id
        effective_ts = int(time.time() + timestamp_offset_seconds)

        # Uses the official production signer helper
        headers = create_inter_service_signed_headers(
            authenticated_tenant_id=sig_tenant,
            body=raw_bytes,
            timestamp=effective_ts,
            request_id=request_id,
        )

        # Return potentially tampered body for negative contract testing
        outgoing_body = tamper_body_bytes if tamper_body_bytes is not None else raw_bytes
        return outgoing_body, headers


def get_response_detail(response) -> dict:
    """Safely extracts error or detail payload from FastAPI response."""
    data = response.json()
    if isinstance(data, dict):
        if "detail" in data and isinstance(data["detail"], dict):
            return data["detail"]
        return data
    return {}


@pytest.fixture(autouse=True)
def ensure_hmac_secret(monkeypatch):
    """Enforces authoritative HMAC secret in test context."""
    monkeypatch.setenv("BOONTRACK_HMAC_SECRET", "test_ci_secure_hmac_secret_for_pipeline_999")


@pytest.fixture
def core_client():
    """Provides test client communicating with Core service application."""
    return TestClient(app)


# =============================================================================
# CONTRACT VERIFICATION TEST SUITE
# =============================================================================

def test_contract_inbox_client_signs_and_core_receives_success(core_client):
    """Contract Proof 1: Inbox signs payload with HMAC-SHA256 using verified session tenant.
    Core validates signature, timestamp, and tenant boundary, returning 200 OK.
    """
    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha", operator_id="cs_agent_alpha")
    payload = {
        "tenant_id": "tenant_alpha",
        "action": "sync_customer_chat",
        "session_id": "chat_sess_99182",
        "operator_id": inbox.operator_id,
    }

    body_bytes, headers = inbox.build_signed_request(payload)

    response = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"

    data = response.json()
    assert data["status"] == "SYNCED"
    assert data["tenant_id"] == "tenant_alpha"
    assert data["action"] == "sync_customer_chat"


def test_contract_rejection_payload_body_tampering(core_client):
    """Contract Proof 2: Payload body modified in transit while keeping original signature.
    Core receiver detects cryptographic mismatch and rejects with HTTP 401.
    """
    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    original_payload = {
        "tenant_id": "tenant_alpha",
        "action": "deliver_digital_item",
        "order_id": "order_original_123",
        "price": 50000,
    }

    # Interceptor tampers with payload (alters price and order_id)
    tampered_payload = {
        "tenant_id": "tenant_alpha",
        "action": "deliver_digital_item",
        "order_id": "order_original_123",
        "price": 0,  # Attacker attempts free item
    }
    tampered_bytes = json.dumps(tampered_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    # Generate signature on original, but transmit tampered body
    _, headers = inbox.build_signed_request(original_payload)

    response = core_client.post("/api/v1/inbox/sync", content=tampered_bytes, headers=headers)
    assert response.status_code == 401, f"Expected 401 Unauthorized, got {response.status_code}: {response.text}"

    detail = get_response_detail(response)
    assert detail.get("error") == "INVALID_INTER_SERVICE_SIGNATURE"
    assert "SIGNATURE_MISMATCH" in str(detail.get("reason", ""))


def test_contract_rejection_tenant_header_vs_payload_mismatch(core_client):
    """Contract Proof 3: Sesi Inbox terverifikasi adalah Tenant Alpha, namun payload mencoba
    menargetkan Tenant Beta. Core receiver mendeteksi pelanggaran batas dan menolak dengan HTTP 403.
    """
    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    hostile_payload = {
        "tenant_id": "tenant_beta",  # Cross-tenant injection attempt
        "action": "exfiltrate_messages",
        "session_id": "chat_sess_beta_secret",
    }

    body_bytes, headers = inbox.build_signed_request(
        payload=hostile_payload,
        custom_header_tenant="tenant_alpha",  # Signed under Alpha's authority
    )

    response = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)
    assert response.status_code == 403, f"Expected 403 Forbidden, got {response.status_code}: {response.text}"

    detail = get_response_detail(response)
    assert detail.get("error") == "TENANT_BOUNDARY_MISMATCH"
    assert detail.get("authenticated_tenant") == "tenant_alpha"
    assert detail.get("attempted_tenant") == "tenant_beta"


def test_contract_rejection_past_timestamp_drift_exceeded(core_client):
    """Contract Proof 4a: Timestamp lampau dengan drift > 300 detik (5 menit).
    Core receiver menolak dengan HTTP 401 TIMESTAMP_DRIFT_EXCEEDED.
    """
    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    payload = {"tenant_id": "tenant_alpha", "action": "sync_chat"}

    # 350 seconds in the past (> 300s tolerance)
    body_bytes, headers = inbox.build_signed_request(payload, timestamp_offset_seconds=-350.0)

    response = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"

    detail = get_response_detail(response)
    assert detail.get("error") == "INVALID_INTER_SERVICE_SIGNATURE"
    assert "TIMESTAMP_DRIFT_EXCEEDED" in str(detail.get("reason", ""))


def test_contract_rejection_future_timestamp_drift_exceeded(core_client):
    """Contract Proof 4b: Timestamp masa depan dengan drift > 300 detik (5 menit).
    Core receiver menolak dengan HTTP 401 TIMESTAMP_DRIFT_EXCEEDED.
    """
    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    payload = {"tenant_id": "tenant_alpha", "action": "sync_chat"}

    # 350 seconds into future (> 300s tolerance)
    body_bytes, headers = inbox.build_signed_request(payload, timestamp_offset_seconds=350.0)

    response = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"

    detail = get_response_detail(response)
    assert detail.get("error") == "INVALID_INTER_SERVICE_SIGNATURE"
    assert "TIMESTAMP_DRIFT_EXCEEDED" in str(detail.get("reason", ""))


def test_contract_rejection_empty_secret_fails_closed(monkeypatch):
    """Contract Proof 5: Saat environment secret BOONTRACK_HMAC_SECRET kosong atau hilang,
    sistem wajib gagal secara aman (fail-closed) melempar ValueError eksplisit.
    """
    monkeypatch.delenv("BOONTRACK_HMAC_SECRET", raising=False)
    with pytest.raises(ValueError) as exc_info:
        get_hmac_secret()
    assert "BOONTRACK_HMAC_SECRET" in str(exc_info.value)
    assert "mandatory" in str(exc_info.value).lower() or "missing" in str(exc_info.value).lower()


def test_contract_rejection_replay_attack_outside_window(core_client):
    """Contract Proof 6: Serangan replay dari pesan yang ditangkap sebelumnya namun dikirim
    kembali di luar masa berlaku anti-replay (> 300 detik) ditolak secara tegas.
    """
    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    stale_payload = {"tenant_id": "tenant_alpha", "action": "replay_sensitive_action"}

    # Stale timestamp: 600 seconds ago (10 minutes old)
    body_bytes, headers = inbox.build_signed_request(stale_payload, timestamp_offset_seconds=-600.0)

    response = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)
    assert response.status_code == 401
    detail = get_response_detail(response)
    assert detail.get("error") == "INVALID_INTER_SERVICE_SIGNATURE"
    assert "TIMESTAMP_DRIFT_EXCEEDED" in str(detail.get("reason", ""))


def test_contract_rejection_identical_request_replay_within_window(core_client):
    """Contract Proof 8a: Replay request identik dengan nonce/request_id yang sama
    dalam jendela anti-replay 300 detik wajib ditolak tegas dengan HTTP 401 (REPLAY_REJECTED).
    """
    replay_guard.reset()
    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    payload = {"tenant_id": "tenant_alpha", "action": "sync_chat", "session_id": "sess_replay_test_001"}
    body_bytes, headers = inbox.build_signed_request(payload)

    # 1. Panggilan pertama: berhasil 200 OK
    res1 = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)
    assert res1.status_code == 200, f"Panggilan pertama harus berhasil, got {res1.status_code}: {res1.text}"
    data1 = res1.json()
    assert data1["status"] == "SYNCED"

    # 2. Panggilan kedua (replay request identik): wajib ditolak HTTP 401 (REPLAY_REJECTED)
    res2 = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)
    assert res2.status_code == 401, f"Panggilan replay harus ditolak 401, got {res2.status_code}: {res2.text}"
    detail2 = get_response_detail(res2)
    assert detail2.get("error") == "REPLAY_REJECTED"
    assert "already been processed" in detail2.get("message", "").lower()


def test_contract_concurrent_race_condition_identical_nonce(core_client):
    """Contract Proof 8b: Permintaan bersamaan (race-condition / concurrent requests)
    dengan nonce identik wajib atomik: tepat 1 permintaan diterima (200 OK), sisanya ditolak 401 (REPLAY_REJECTED).
    """
    import concurrent.futures
    replay_guard.reset()

    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    shared_nonce = f"race_condition_nonce_{time.time()}"
    payload = {"tenant_id": "tenant_alpha", "action": "sync_chat", "session_id": "sess_race_test_999"}
    body_bytes, headers = inbox.build_signed_request(payload, request_id=shared_nonce)

    num_concurrent = 5
    results = []

    def send_request():
        return core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent) as executor:
        futures = [executor.submit(send_request) for _ in range(num_concurrent)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    status_codes = [r.status_code for r in results]
    success_count = status_codes.count(200)
    rejected_count = status_codes.count(401)

    assert success_count == 1, f"Tepat 1 request harus berhasil (200 OK), namun didapat {success_count}. Statuses: {status_codes}"
    assert rejected_count == num_concurrent - 1, f"Sisa request harus ditolak 401 (REPLAY_REJECTED), got {rejected_count}. Statuses: {status_codes}"

    # Verifikasi seluruh respon yang gagal membawa kode REPLAY_REJECTED
    for r in results:
        if r.status_code != 200:
            detail = get_response_detail(r)
            assert detail.get("error") == "REPLAY_REJECTED"


def test_contract_rejection_missing_nonce(core_client):
    """Contract Proof 8c: Wajibkan request_id / nonce (hilangkan jalur verifikasi tanpa nonce).
    Permintaan tanpa header X-Boontrack-Request-Id wajib ditolak tegas dengan HTTP 401 (MISSING_NONCE).
    """
    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    payload = {"tenant_id": "tenant_alpha", "action": "sync_chat"}
    body_bytes, headers = inbox.build_signed_request(payload)

    # Hilangkan header request_id
    headers_without_nonce = {k: v for k, v in headers.items() if k not in ("X-Boontrack-Request-Id", "X-Boontrack-Nonce")}

    response = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers_without_nonce)
    assert response.status_code == 401, f"Expected 401 for missing nonce, got {response.status_code}: {response.text}"

    detail = get_response_detail(response)
    assert detail.get("error") == "MISSING_NONCE"
    assert "mandatory" in detail.get("message", "").lower()


def test_contract_redis_outage_fails_closed(core_client, monkeypatch):
    """Contract Proof 8d: Fail-Closed Anti-Replay in Production.
    Jika Redis mati / tidak tersedia di lingkungan produksi, request sensitif WAJIB fail-closed (HTTP 503).
    Fallback in-memory dilarang keras di jalur produksi untuk mencegah serangan replay antar cluster.
    """
    # 1. Simulasikan environment produksi
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(replay_guard, "_redis", None)

    inbox = OfficialInboxClientSigner(tenant_id="tenant_alpha")
    payload = {"tenant_id": "tenant_alpha", "action": "sensitive_payment_trigger", "amount": 1000000}
    body_bytes, headers = inbox.build_signed_request(payload)

    response = core_client.post("/api/v1/inbox/sync", content=body_bytes, headers=headers)
    assert response.status_code == 503, f"Expected 503 Service Unavailable, got {response.status_code}: {response.text}"

    detail = get_response_detail(response)
    assert detail.get("error") == "REPLAY_GUARD_UNAVAILABLE"
    assert "fail-closed" in detail.get("message", "").lower() or "unavailable" in detail.get("message", "").lower()


def test_contract_multi_instance_race_condition(monkeypatch):
    """Contract Proof 8e: Multi-Instance Race Condition & Scoped Nonce Namespace.
    Simulasi multi-instance Core nodes bersaing mendaftarkan nonce identik pada shared store.
    1. Memverifikasi namespace terikat eksplisit: core:replay:{service}:{tenant}:{request_id}.
    2. Menjamin tepat 1 instance yang berhasil (acquire=True), instance lainnya gagal (acquire=False).
    """
    from app.core.security.inter_service_auth import InterServiceReplayGuard

    # Inisialisasi Mock Redis bersama yang mensimulasikan Redis cluster multi-instance
    shared_redis_storage = {}
    import threading
    storage_lock = threading.Lock()

    class MockDistributedRedis:
        def set(self, key, value, ex=None, nx=False):
            with storage_lock:
                if nx and key in shared_redis_storage:
                    return False
                shared_redis_storage[key] = value
                return True

        def delete(self, *keys):
            with storage_lock:
                for k in keys:
                    shared_redis_storage.pop(k, None)

        def keys(self, pattern="*"):
            with storage_lock:
                return list(shared_redis_storage.keys())

    mock_cluster_redis = MockDistributedRedis()

    # Buat 3 instance Core terpisah yang berbagi Redis yang sama
    node_a = InterServiceReplayGuard()
    node_b = InterServiceReplayGuard()
    node_c = InterServiceReplayGuard()
    node_a._redis = mock_cluster_redis
    node_b._redis = mock_cluster_redis
    node_c._redis = mock_cluster_redis

    test_request_id = f"distributed_nonce_{time.time()}"
    tenant_id = "tenant_gamma"
    service_name = "inbox"

    # Verifikasi format namespace eksplisit
    expected_namespace = f"core:replay:{service_name}:{tenant_id}:{test_request_id}"
    assert node_a.build_nonce_key(test_request_id, tenant_id=tenant_id, service_name=service_name) == expected_namespace

    # Eksekusi konkurensi antar instance
    import concurrent.futures
    nodes = [node_a, node_b, node_c]
    acquired_results = []

    def attempt_acquire(node):
        return node.acquire_nonce(
            request_id=test_request_id,
            tenant_id=tenant_id,
            service_name=service_name,
            fail_closed=True,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(attempt_acquire, n) for n in nodes]
        for f in concurrent.futures.as_completed(futures):
            acquired_results.append(f.result())

    # Tepat 1 instance menang, 2 instance kalah
    assert acquired_results.count(True) == 1, f"Tepat 1 instance multi-node harus menang, got {acquired_results}"
    assert acquired_results.count(False) == 2, f"2 instance lainnya harus ditolak, got {acquired_results}"
    assert expected_namespace in shared_redis_storage


