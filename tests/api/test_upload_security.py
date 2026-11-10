"""
tests/api/test_upload_security.py
=================================
Security Remediation & Hardening Test Suite for GitHub Issue #27:
"security(core): enforce signed merchant authorization on tenant upload route"

Enforces:
1. Signed Authentication: Rejects anonymous/untrusted calls with HTTP 401 Unauthorized.
2. Server-Derived Identity: Derives tenant_id and merchant_id purely from verified JWT claims.
3. Tenant-Scoped Storage Namespace: Bucket storage paths strictly follow:
   tenants/{verified_tenant_id}/uploads/{YYYY}/{MM}/{uuid4}.{ext}
4. File & Magic Byte Hardening: Rejects non-image, spoofed magic bytes, and >5MB files with HTTP 422.
5. Anti-Cross-Tenant Tampering: Rejects header/form spoofing and path traversal with HTTP 403 Forbidden.
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
    return encode_jwt_token_strict(payload, realm=realm)


# ============================================================================
# 1. POSITIVE TEST: Authenticated Merchant with Scoped Tenant Namespace
# ============================================================================

def test_upload_positive_verified_tenant():
    """
    Positive Test Case:
    - Signed merchant authentication succeeds.
    - Status code is HTTP 201 Created.
    - Returned storage path strictly conforms to:
      tenants/{verified_tenant_id}/uploads/{YYYY}/{MM}/{uuid4}.{ext}
    - Server-side tenant_id and merchant_id are strictly bound.
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

    # Validate storage namespace: tenants/{verified_tenant_id}/uploads/{YYYY}/{MM}/{uuid4}.{ext}
    storage_path = data.get("storage_path") or data.get("path", "").lstrip("/")
    expected_prefix = f"tenants/{tenant_id}/uploads/{expected_year}/{expected_month}/"
    assert storage_path.startswith(expected_prefix), (
        f"Storage path '{storage_path}' must begin with scoped tenant prefix '{expected_prefix}'"
    )

    # Regex check: {uuid4}.{ext}
    uuid_ext_pattern = rf"^{re.escape(expected_prefix)}[0-9a-f]{{32}}\.(webp|png|jpg)$"
    assert re.match(uuid_ext_pattern, storage_path), (
        f"Storage path '{storage_path}' does not match UUID4 namespace pattern: {uuid_ext_pattern}"
    )

    assert "url" in data and len(data["url"]) > 0
    assert data.get("filename", "").endswith(".webp")


# ============================================================================
# 2. NEGATIVE TEST: Anonymous or Untrusted Requests Rejected (HTTP 401)
# ============================================================================

def test_upload_negative_anonymous_rejected():
    """
    Negative Test Case:
    - Requests without Authorization header are rejected with HTTP 401 Unauthorized.
    - Requests with empty, malformed, or expired tokens are rejected with HTTP 401 Unauthorized.
    - Requests with forged signature are rejected with HTTP 401 Unauthorized.
    """
    img_data = create_valid_test_image(format="PNG")

    # 1. Anonymous request (no auth header)
    resp_anon = client.post(
        "/api/v1/upload",
        files={"file": ("unauthorized.png", img_data, "image/png")},
    )
    assert resp_anon.status_code == 401, f"Expected 401, got {resp_anon.status_code}: {resp_anon.text}"
    assert "Autentikasi merchant diperlukan" in resp_anon.json().get("detail", "")

    # 2. Empty Authorization header
    img_data.seek(0)
    resp_empty = client.post(
        "/api/v1/upload",
        files={"file": ("empty_token.png", img_data, "image/png")},
        headers={"Authorization": "Bearer "},
    )
    assert resp_empty.status_code == 401

    # 3. Malformed JWT token
    img_data.seek(0)
    resp_malformed = client.post(
        "/api/v1/upload",
        files={"file": ("malformed.png", img_data, "image/png")},
        headers={"Authorization": "Bearer not-a-valid-jwt-token"},
    )
    assert resp_malformed.status_code == 401

    # 4. Expired JWT token
    expired_token = make_signed_merchant_token(expires_in_seconds=-3600)
    img_data.seek(0)
    resp_expired = client.post(
        "/api/v1/upload",
        files={"file": ("expired.png", img_data, "image/png")},
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp_expired.status_code == 401

    # 5. Forged signature (tampered token)
    valid_token = make_signed_merchant_token()
    parts = valid_token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}.fake_tampered_signature_bytes"
    img_data.seek(0)
    resp_forged = client.post(
        "/api/v1/upload",
        files={"file": ("forged.png", img_data, "image/png")},
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert resp_forged.status_code == 401


# ============================================================================
# 3. NEGATIVE TEST: Cross-Tenant Spoofing and Namespace Tampering (HTTP 403)
# ============================================================================

def test_upload_negative_cross_tenant_spoofing():
    """
    Negative Test Case:
    - Client holds valid token for tenant 'tenant-alpha-001'.
    - Client attempts to inject or spoof tenant identity targeting 'tenant-bravo-victim':
      a. Via X-Tenant-ID header -> HTTP 403 Forbidden.
      b. Via X-Tenant-Slug header -> HTTP 403 Forbidden.
      c. Via FormData tenant_id -> HTTP 403 Forbidden.
      d. Via folder path traversal ('../tenant-bravo-victim') -> HTTP 403 Forbidden.
      e. Via explicit foreign folder ('tenants/tenant-bravo-victim/uploads') -> HTTP 403 Forbidden.
    """
    token_alpha = make_signed_merchant_token(tenant_id="tenant-alpha-001")
    img_data = create_valid_test_image(format="PNG")

    # Attempt 3a: Header X-Tenant-ID spoofing
    resp_h_id = client.post(
        "/api/v1/upload",
        files={"file": ("spoof_hdr.png", img_data, "image/png")},
        headers={
            "Authorization": f"Bearer {token_alpha}",
            "X-Tenant-ID": "tenant-bravo-victim",
        },
    )
    assert resp_h_id.status_code == 403, f"Expected 403, got {resp_h_id.status_code}: {resp_h_id.text}"
    assert "cross-tenant" in resp_h_id.json().get("detail", "").lower()

    # Attempt 3b: Header X-Tenant-Slug spoofing
    img_data.seek(0)
    resp_h_slug = client.post(
        "/api/v1/upload",
        files={"file": ("spoof_slug.png", img_data, "image/png")},
        headers={
            "Authorization": f"Bearer {token_alpha}",
            "X-Tenant-Slug": "tenant-bravo-victim",
        },
    )
    assert resp_h_slug.status_code == 403, f"Expected 403, got {resp_h_slug.status_code}: {resp_h_slug.text}"

    # Attempt 3c: FormData tenant_id injection
    img_data.seek(0)
    resp_form_tenant = client.post(
        "/api/v1/upload",
        files={"file": ("spoof_form.png", img_data, "image/png")},
        data={"tenant_id": "tenant-bravo-victim"},
        headers={"Authorization": f"Bearer {token_alpha}"},
    )
    assert resp_form_tenant.status_code == 403, f"Expected 403, got {resp_form_tenant.status_code}: {resp_form_tenant.text}"

    # Attempt 3d: Path traversal injection via folder parameter
    img_data.seek(0)
    resp_traversal = client.post(
        "/api/v1/upload",
        files={"file": ("traversal.png", img_data, "image/png")},
        data={"folder": "../tenant-bravo-victim"},
        headers={"Authorization": f"Bearer {token_alpha}"},
    )
    assert resp_traversal.status_code == 403, f"Expected 403, got {resp_traversal.status_code}: {resp_traversal.text}"

    # Attempt 3e: Foreign tenant namespace injection
    img_data.seek(0)
    resp_foreign = client.post(
        "/api/v1/upload",
        files={"file": ("foreign.png", img_data, "image/png")},
        data={"folder": "tenants/tenant-bravo-victim/uploads"},
        headers={"Authorization": f"Bearer {token_alpha}"},
    )
    assert resp_foreign.status_code == 403, f"Expected 403, got {resp_foreign.status_code}: {resp_foreign.text}"


# ============================================================================
# 4. NEGATIVE TEST: Invalid Files, Spoofed Magic Bytes & Oversize (HTTP 422)
# ============================================================================

def test_upload_negative_invalid_file():
    """
    Negative Test Case:
    - Files that are not images (text, pdf, scripts).
    - Executable files disguised with image extension and fake MIME (magic byte spoofing).
    - Corrupt or truncated image binary payloads.
    - Files exceeding the strict 5MB limit.
    - Empty files (0 bytes).
    All must be rejected with HTTP 422 Unprocessable Entity.
    """
    token = make_signed_merchant_token(tenant_id="tenant-alpha-001")

    # Subcase 4a: Plain text file disguised as PNG
    text_data = io.BytesIO(b"Hello world, this is a plain text file, not an image!")
    resp_text = client.post(
        "/api/v1/upload",
        files={"file": ("document.png", text_data, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_text.status_code == 422, f"Expected 422, got {resp_text.status_code}: {resp_text.text}"

    # Subcase 4b: Windows PE Executable disguised as PNG (Magic Byte Spoofing)
    fake_exe = io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00This program cannot be run in DOS mode.")
    resp_exe = client.post(
        "/api/v1/upload",
        files={"file": ("malware.png", fake_exe, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_exe.status_code == 422, f"Expected 422, got {resp_exe.status_code}: {resp_exe.text}"
    assert "magic bytes" in resp_exe.json().get("detail", "").lower()

    # Subcase 4c: Shell script disguised as JPEG
    fake_script = io.BytesIO(b"#!/bin/bash\necho 'rm -rf /'\n")
    resp_script = client.post(
        "/api/v1/upload",
        files={"file": ("script.jpg", fake_script, "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_script.status_code == 422, f"Expected 422, got {resp_script.status_code}: {resp_script.text}"

    # Subcase 4d: Corrupted JPEG (Valid JPEG start header, followed by random corrupt bytes)
    corrupt_jpg = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"BROKEN_IMAGE_BYTES_THAT_FAIL_PILLOW")
    resp_corrupt = client.post(
        "/api/v1/upload",
        files={"file": ("corrupt.jpg", corrupt_jpg, "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_corrupt.status_code == 422, f"Expected 422, got {resp_corrupt.status_code}: {resp_corrupt.text}"

    # Subcase 4e: Oversize file > 5MB
    large_data = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1024))
    resp_oversize = client.post(
        "/api/v1/upload",
        files={"file": ("huge_payload.png", large_data, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_oversize.status_code == 422, f"Expected 422, got {resp_oversize.status_code}: {resp_oversize.text}"
    assert "melebihi batas maksimal 5 MB" in resp_oversize.json().get("detail", "")

    # Subcase 4f: Empty file (0 bytes)
    empty_data = io.BytesIO(b"")
    resp_empty = client.post(
        "/api/v1/upload",
        files={"file": ("empty.png", empty_data, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_empty.status_code == 422, f"Expected 422, got {resp_empty.status_code}: {resp_empty.text}"

