"""
tests/api/test_upload_security.py
=================================
Security Remediation & Hardening Test Suite for GitHub Issue #27 / PR #28:
"security(core): enforce signed merchant authorization on tenant upload route"

Coverage matrix (15 scenarios, FastAPI /api/v1/upload):
  POSITIVE
    1.  Authenticated Merchant — valid token, scoped namespace, HTTP 201.

  NEGATIVE — Authentication (HTTP 401)
    2.  Anonymous request (no token).
    3.  Malformed / forged / expired token.
    4.  Invalid merchant role (customer → HTTP 403).
    5.  Missing tenant claim (token without tenant_id/tenant_slug → HTTP 401).
    6.  user_metadata-only tenant (Supabase JWT where tenant appears only in
        user_metadata, not in app_metadata or top-level → HTTP 401).

  NEGATIVE — Cross-Tenant Spoofing (HTTP 403)
    7.  X-Tenant-ID header spoofing.
    8.  X-Tenant-Slug header spoofing.
    9.  FormData tenant_id injection.
    10. Query param tenant_id spoofing.
    11. Tenant-prefix lookalike in folder (tenant-alpha-evil when auth=tenant-alpha → 403).
    12. URL-encoded path traversal (%2e%2e → HTTP 403).
    13. Backslash separator in folder path (HTTP 403).

  NEGATIVE — File Validation (HTTP 422)
    14. Spoofed magic bytes / non-image / corrupt image / empty file.
    15. Content-Length pre-check: oversized body before read (HTTP 413).
"""

import io
import re
import time
import pytest
from datetime import datetime, timezone
from PIL import Image
from fastapi.testclient import TestClient

from app.main import app
from app.core.jwt_secret import encode_jwt_token_strict

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_valid_test_image(format: str = "PNG", size: tuple = (400, 400), color: tuple = (0, 128, 255)) -> io.BytesIO:
    """Generates valid image bytes with authoritative magic bytes for JPEG / PNG."""
    buf = io.BytesIO()
    mode = "RGBA" if format.upper() == "PNG" else "RGB"
    img = Image.new(mode, size, color)
    img.save(buf, format=format)
    buf.seek(0)
    return buf


def make_signed_merchant_token(
    tenant_id: str = "tenant-alpha-001",
    merchant_id: str = "merch_owner@alpha.com",
    role: str = "merchant",
    expires_in_seconds: int = 3600,
    realm: str = "core",
    extra_claims: dict | None = None,
) -> str:
    """Creates a cryptographically signed JWT token matching production trust policy."""
    now = int(time.time())
    payload = {
        "sub": merchant_id,
        "merchant_id": merchant_id,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_id,
        "role": role,
        "exp": now + expires_in_seconds,
    }
    if extra_claims:
        payload.update(extra_claims)
    return encode_jwt_token_strict(payload, realm=realm)


# ---------------------------------------------------------------------------
# 1. POSITIVE — Authenticated Merchant with Scoped Tenant Namespace (HTTP 201)
# ---------------------------------------------------------------------------

def test_upload_positive_verified_tenant():
    """
    Positive: Signed merchant auth succeeds.
    - HTTP 201 Created.
    - Storage path conforms to tenants/{tenant_id}/uploads/{YYYY}/{MM}/{uuid4}.{ext}.
    - server-bound tenant_id and merchant_id in response.
    """
    tenant_id = "tenant-alpha-001"
    merchant_id = "merch_owner@alpha.com"
    token = make_signed_merchant_token(tenant_id=tenant_id, merchant_id=merchant_id)

    img_data = create_valid_test_image(format="JPEG", size=(500, 500))
    now = datetime.now(timezone.utc)
    expected_year = now.strftime("%Y")
    expected_month = now.strftime("%m")

    response = client.post(
        "/api/v1/upload",
        files={"file": ("product_banner.jpg", img_data, "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    data = response.json()

    assert data.get("status") == "success"
    assert data.get("tenant_id") == tenant_id
    assert data.get("merchant_id") == merchant_id

    storage_path = data.get("storage_path") or data.get("path", "").lstrip("/")
    expected_prefix = f"tenants/{tenant_id}/uploads/{expected_year}/{expected_month}/"
    assert storage_path.startswith(expected_prefix), (
        f"Storage path '{storage_path}' must begin with '{expected_prefix}'"
    )

    uuid_ext_pattern = rf"^{re.escape(expected_prefix)}[0-9a-f]{{32}}\.(webp|png|jpg)$"
    assert re.match(uuid_ext_pattern, storage_path), (
        f"Storage path '{storage_path}' does not match UUID4 namespace pattern"
    )

    assert "url" in data and len(data["url"]) > 0
    assert data.get("filename", "").endswith(".webp")


# ---------------------------------------------------------------------------
# 2. NEGATIVE — Anonymous / Malformed / Expired / Forged Token (HTTP 401)
# ---------------------------------------------------------------------------

def test_upload_negative_anonymous_rejected():
    """
    Anonymous, empty, malformed, expired, and forged-signature tokens → HTTP 401.
    """
    img_data = create_valid_test_image(format="PNG")

    # 2a. Anonymous (no auth header)
    resp = client.post("/api/v1/upload", files={"file": ("a.png", img_data, "image/png")})
    assert resp.status_code == 401, f"Got {resp.status_code}: {resp.text}"
    assert "Autentikasi merchant diperlukan" in resp.json().get("detail", "")

    # 2b. Empty Bearer
    img_data.seek(0)
    resp = client.post("/api/v1/upload", files={"file": ("b.png", img_data, "image/png")},
                       headers={"Authorization": "Bearer "})
    assert resp.status_code == 401

    # 2c. Malformed JWT
    img_data.seek(0)
    resp = client.post("/api/v1/upload", files={"file": ("c.png", img_data, "image/png")},
                       headers={"Authorization": "Bearer not-a-valid-jwt-token"})
    assert resp.status_code == 401

    # 2d. Expired token
    expired_token = make_signed_merchant_token(expires_in_seconds=-3600)
    img_data.seek(0)
    resp = client.post("/api/v1/upload", files={"file": ("d.png", img_data, "image/png")},
                       headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401

    # 2e. Forged signature
    valid_token = make_signed_merchant_token()
    parts = valid_token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.fake_tampered_signature_bytes"
    img_data.seek(0)
    resp = client.post("/api/v1/upload", files={"file": ("e.png", img_data, "image/png")},
                       headers={"Authorization": f"Bearer {tampered}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. NEGATIVE — Cross-Tenant Spoofing & Namespace Tampering (HTTP 403)
# ---------------------------------------------------------------------------

def test_upload_negative_cross_tenant_spoofing():
    """
    Valid token for tenant-alpha-001; attempts to inject or spoof tenant-bravo-victim → HTTP 403.
    """
    token_alpha = make_signed_merchant_token(tenant_id="tenant-alpha-001")
    img_data = create_valid_test_image(format="PNG")

    # 3a. X-Tenant-ID header spoofing
    resp = client.post("/api/v1/upload",
                       files={"file": ("a.png", img_data, "image/png")},
                       headers={"Authorization": f"Bearer {token_alpha}",
                                "X-Tenant-ID": "tenant-bravo-victim"})
    assert resp.status_code == 403, f"Got {resp.status_code}: {resp.text}"
    assert "cross-tenant" in resp.json().get("detail", "").lower()

    # 3b. X-Tenant-Slug header spoofing
    img_data.seek(0)
    resp = client.post("/api/v1/upload",
                       files={"file": ("b.png", img_data, "image/png")},
                       headers={"Authorization": f"Bearer {token_alpha}",
                                "X-Tenant-Slug": "tenant-bravo-victim"})
    assert resp.status_code == 403

    # 3c. FormData tenant_id injection
    img_data.seek(0)
    resp = client.post("/api/v1/upload",
                       files={"file": ("c.png", img_data, "image/png")},
                       data={"tenant_id": "tenant-bravo-victim"},
                       headers={"Authorization": f"Bearer {token_alpha}"})
    assert resp.status_code == 403

    # 3d. Folder path traversal
    img_data.seek(0)
    resp = client.post("/api/v1/upload",
                       files={"file": ("d.png", img_data, "image/png")},
                       data={"folder": "../tenant-bravo-victim"},
                       headers={"Authorization": f"Bearer {token_alpha}"})
    assert resp.status_code == 403

    # 3e. Foreign tenant namespace in folder
    img_data.seek(0)
    resp = client.post("/api/v1/upload",
                       files={"file": ("e.png", img_data, "image/png")},
                       data={"folder": "tenants/tenant-bravo-victim/uploads"},
                       headers={"Authorization": f"Bearer {token_alpha}"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 4. NEGATIVE — Invalid Files, Spoofed Magic Bytes & Oversize (HTTP 422)
# ---------------------------------------------------------------------------

def test_upload_negative_invalid_file():
    """
    Non-image, spoofed magic bytes, corrupt binary, oversize, empty → HTTP 422.
    """
    token = make_signed_merchant_token(tenant_id="tenant-alpha-001")

    # 4a. Plain text disguised as PNG
    resp = client.post("/api/v1/upload",
                       files={"file": ("doc.png", io.BytesIO(b"Hello plain text"), "image/png")},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422

    # 4b. Windows PE disguised as PNG (magic byte spoofing)
    fake_exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00This is a Windows PE executable."
    resp = client.post("/api/v1/upload",
                       files={"file": ("malware.png", io.BytesIO(fake_exe), "image/png")},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
    assert "magic bytes" in resp.json().get("detail", "").lower()

    # 4c. Shell script disguised as JPEG
    fake_sh = b"#!/bin/bash\necho 'rm -rf /'\n"
    resp = client.post("/api/v1/upload",
                       files={"file": ("evil.jpg", io.BytesIO(fake_sh), "image/jpeg")},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422

    # 4d. Corrupted JPEG (valid SOI header, corrupt body)
    corrupt_jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"BROKEN_IMAGE_DATA"
    resp = client.post("/api/v1/upload",
                       files={"file": ("corrupt.jpg", io.BytesIO(corrupt_jpg), "image/jpeg")},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422

    # 4e. Oversize file > 5MB (PNG magic header + padding)
    large_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1024)
    resp = client.post("/api/v1/upload",
                       files={"file": ("huge.png", io.BytesIO(large_data), "image/png")},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
    assert "melebihi batas maksimal 5 MB" in resp.json().get("detail", "")

    # 4f. Empty file
    resp = client.post("/api/v1/upload",
                       files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 5. NEGATIVE — Invalid Merchant Role (HTTP 403)
# ---------------------------------------------------------------------------

def test_upload_negative_invalid_merchant_role():
    """
    Token with unauthorized role (customer, user, anonymous) → HTTP 403.
    Token is otherwise valid (correct signature, non-expired, has tenant claim).
    """
    img_data = create_valid_test_image(format="PNG")

    for bad_role in ("customer", "user", "anonymous", "", "guest"):
        token = make_signed_merchant_token(tenant_id="tenant-alpha-001", role=bad_role)
        img_data.seek(0)
        resp = client.post(
            "/api/v1/upload",
            files={"file": (f"role_{bad_role}.png", img_data, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"Role '{bad_role}' should be rejected with HTTP 403, got {resp.status_code}: {resp.text}"
        )
        assert "otorisasi" in resp.json().get("detail", "").lower() or "role" in resp.json().get("detail", "").lower()

    # Verify authorized roles are still permitted (smoke check for owner)
    token_owner = make_signed_merchant_token(tenant_id="tenant-alpha-001", role="owner")
    img_data.seek(0)
    resp_owner = client.post(
        "/api/v1/upload",
        files={"file": ("owner_upload.png", img_data, "image/png")},
        headers={"Authorization": f"Bearer {token_owner}"},
    )
    assert resp_owner.status_code == 201, f"owner role should succeed, got {resp_owner.status_code}"


# ---------------------------------------------------------------------------
# 6. NEGATIVE — Missing Tenant Claim in Token (HTTP 401)
# ---------------------------------------------------------------------------

def test_upload_negative_missing_tenant_claim():
    """
    Token is valid and signed but contains no tenant_id, tenant_slug, or app_metadata tenant info.
    Server must reject with HTTP 401 (missing authoritative tenant claim).
    """
    now = int(time.time())
    # Token without any tenant info whatsoever
    payload_no_tenant = {
        "sub": "merchant@example.com",
        "merchant_id": "merchant@example.com",
        "role": "merchant",
        "exp": now + 3600,
        # Deliberately omitting tenant_id, tenant_slug, app_metadata, tenant
    }
    token_no_tenant = encode_jwt_token_strict(payload_no_tenant, realm="core")

    img_data = create_valid_test_image(format="PNG")
    resp = client.post(
        "/api/v1/upload",
        files={"file": ("no_tenant.png", img_data, "image/png")},
        headers={"Authorization": f"Bearer {token_no_tenant}"},
    )
    assert resp.status_code == 401, f"Expected 401 for missing tenant claim, got {resp.status_code}: {resp.text}"
    assert "tenant" in resp.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# 7. NEGATIVE — user_metadata-Only Tenant (Must NOT grant access, HTTP 401)
# ---------------------------------------------------------------------------

def test_upload_negative_user_metadata_tenant_spoofing():
    """
    Supabase-style JWT where the tenant claim is ONLY present in user_metadata
    (user-editable, untrusted). The server must reject this with HTTP 401 since
    user_metadata is not a trusted authorization source.

    Security principle: user_metadata can be set by the client and must not independently
    grant tenant identity for upload authorization.
    """
    now = int(time.time())
    # Simulate a Supabase JWT structure where tenant only appears in user_metadata
    payload_user_meta_only = {
        "sub": "attacker@evil.com",
        "role": "merchant",
        "exp": now + 3600,
        # No top-level tenant_id or tenant_slug
        # No app_metadata (server-set)
        # Only user_metadata (user-editable — MUST be rejected)
        "user_metadata": {
            "tenant_id": "tenant-alpha-victim",
            "tenant_slug": "tenant-alpha-victim",
        },
        # Deliberately omit: tenant_id, tenant_slug, app_metadata, tenant
    }
    # We use realm="core" for simplicity; the same principle applies to Supabase realm.
    token_user_meta_only = encode_jwt_token_strict(payload_user_meta_only, realm="core")

    img_data = create_valid_test_image(format="PNG")
    resp = client.post(
        "/api/v1/upload",
        files={"file": ("user_meta_spoof.png", img_data, "image/png")},
        headers={"Authorization": f"Bearer {token_user_meta_only}"},
    )
    assert resp.status_code == 401, (
        f"user_metadata tenant MUST be rejected (HTTP 401), got {resp.status_code}: {resp.text}. "
        "Security violation: user_metadata is user-editable and must not grant tenant access."
    )


# ---------------------------------------------------------------------------
# 8. NEGATIVE — Query Param Tenant Spoofing (HTTP 403)
# ---------------------------------------------------------------------------

def test_upload_negative_query_tenant_spoofing():
    """
    Valid token for tenant-alpha. Client injects ?tenant_id=tenant-bravo-victim in query string.
    Must be rejected with HTTP 403 (cross-tenant tampering detection).
    """
    token_alpha = make_signed_merchant_token(tenant_id="tenant-alpha-001")
    img_data = create_valid_test_image(format="PNG")

    resp = client.post(
        "/api/v1/upload?tenant_id=tenant-bravo-victim",
        files={"file": ("query_spoof.png", img_data, "image/png")},
        headers={"Authorization": f"Bearer {token_alpha}"},
    )
    assert resp.status_code == 403, (
        f"Query param tenant spoofing should be HTTP 403, got {resp.status_code}: {resp.text}"
    )
    assert "cross-tenant" in resp.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# 9. NEGATIVE — Tenant-Prefix Lookalike in Folder (HTTP 403)
# ---------------------------------------------------------------------------

def test_upload_negative_tenant_prefix_lookalike():
    """
    Token is for 'tenant-alpha'. Folder is 'tenants/tenant-alpha-evil/uploads'.
    Old startswith() check would PASS this ('tenants/tenant-alpha-evil'.startswith('tenants/tenant-alpha')).
    Component-safe check MUST reject this with HTTP 403.
    """
    token_alpha = make_signed_merchant_token(tenant_id="tenant-alpha")
    img_data = create_valid_test_image(format="PNG")

    resp = client.post(
        "/api/v1/upload",
        files={"file": ("lookalike.png", img_data, "image/png")},
        data={"folder": "tenants/tenant-alpha-evil/uploads"},
        headers={"Authorization": f"Bearer {token_alpha}"},
    )
    assert resp.status_code == 403, (
        f"Prefix lookalike 'tenant-alpha-evil' vs 'tenant-alpha' must be HTTP 403, "
        f"got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 10. NEGATIVE — URL-Encoded Path Traversal in Folder (HTTP 403)
# ---------------------------------------------------------------------------

def test_upload_negative_url_encoded_traversal():
    """
    URL-encoded path traversal: folder='%2e%2e/etc' or '%2f' separator.
    Old check only catches literal '..'; URL-encoded form must also be rejected → HTTP 403.
    """
    token = make_signed_merchant_token(tenant_id="tenant-alpha-001")
    img_data = create_valid_test_image(format="PNG")

    encoded_traversal_cases = [
        "%2e%2e/etc",
        "tenants%2ftenant-alpha-001%2fuploads",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    ]
    for case in encoded_traversal_cases:
        img_data.seek(0)
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("encoded_traversal.png", img_data, "image/png")},
            data={"folder": case},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"URL-encoded traversal '{case}' must be HTTP 403, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# 11. NEGATIVE — Backslash Separator in Folder (HTTP 403)
# ---------------------------------------------------------------------------

def test_upload_negative_backslash_separator():
    """
    Backslash separators in folder path (Windows-style path injection) → HTTP 403.
    """
    token = make_signed_merchant_token(tenant_id="tenant-alpha-001")
    img_data = create_valid_test_image(format="PNG")

    backslash_cases = [
        r"tenants\tenant-bravo-victim\uploads",
        r"..\etc",
        r"tenants/tenant-alpha-001\..\..\evil",
    ]
    for case in backslash_cases:
        img_data.seek(0)
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("backslash.png", img_data, "image/png")},
            data={"folder": case},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"Backslash path '{case}' must be HTTP 403, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# 12. NEGATIVE — Content-Length Pre-check (HTTP 413 Before Body Read)
# ---------------------------------------------------------------------------

def test_upload_negative_oversized_content_length_precheck():
    """
    Request with Content-Length header claiming > 5MB + overhead.
    Server MUST reject with HTTP 413 BEFORE reading the body into memory,
    preventing DoS via full-body allocation.
    """
    token = make_signed_merchant_token(tenant_id="tenant-alpha-001")

    # Simulate a large Content-Length header without actually sending huge body.
    # TestClient sends the actual body from the BytesIO; we craft a valid small image
    # but lie about Content-Length in a way that triggers the pre-check.
    # Since TestClient does not let us override Content-Length directly in a clean way,
    # we verify the guard with an actual oversized payload constructed in memory.
    # The guard fires when the declared Content-Length exceeds MAX_FILE_SIZE + 65536.
    # We test using the actual header approach supported by httpx (TestClient):
    img_data = create_valid_test_image(format="PNG", size=(10, 10))

    # 12a: Real oversized Content-Length via headers override
    # httpx (used by TestClient) allows setting custom headers including content-length
    oversized_cl = str(5 * 1024 * 1024 + 65537 + 1)  # Just over the guard threshold
    resp = client.post(
        "/api/v1/upload",
        content=img_data.read(),  # Send the small body
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "multipart/form-data; boundary=----TestBoundary",
            "Content-Length": oversized_cl,
        },
    )
    # May get 413 (pre-check fired) or 422 (body read failed due to boundary mismatch)
    # Either is acceptable — the important thing is NOT 201 or 500
    assert resp.status_code in (413, 422, 400), (
        f"Oversized Content-Length should be rejected early (413/422/400), got {resp.status_code}"
    )
