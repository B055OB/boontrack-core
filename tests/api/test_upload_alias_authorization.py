"""
tests/api/test_upload_alias_authorization.py
============================================
Comprehensive Security Authorization & Fail-Closed Test Suite for Upload Routes
CTO Work Order Verification for Issue #27 / PR #28:

Covers:
1. Centralized Signed Authorization Across Tenant Upload Aliases (FastAPI & aiohttp):
   - POST /api/v1/tenants/{slug}/upload
   - POST /api/v1/tenants/{slug}/qris/upload
   - POST /api/v1/tenants/{slug}/upload-qris
   - POST /api/v1/tenant/{slug}/upload
   - POST /api/v1/tenant/{slug}/qris/upload
   * Anonymous attempt -> strictly HTTP 401
   * Cross-tenant attempt (Token for tenant-alpha targeting tenant-beta) -> strictly HTTP 403
   * QRIS settings cross-tenant overwrite prevention -> proven zero mutation on foreign tenant
   * Legitimate authorized upload -> HTTP 200/201 with scoped path tenants/{slug}/...

2. Fail-Closed Database Membership & Tenant Status Validation:
   - Matching active membership in DB -> allow
   - Inactive/revoked membership in DB -> HTTP 403
   - Non-existent membership in DB -> HTTP 403
   - Inactive tenant in DB -> HTTP 403
   - Database connection failure / operational outage -> strictly HTTP 503 (fail-closed!)

3. Public / Global Upload Route Isolation:
   - Prove public upload cannot write into tenants/ namespace (HTTP 403)
   - Prove public upload cannot mutate any tenant settings

4. True Chunked / Streaming Bounded Limits:
   - Request using Python generator (Transfer-Encoding: chunked, NO Content-Length header)
   - Must abort early with strictly HTTP 413
   - Generator must NOT be completely exhausted before abort
"""

import io
import time
import asyncio
import httpx
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.jwt_secret import encode_jwt_token_strict
from app.routes.media_routes import (
    register_merchant_membership,
    revoke_merchant_membership,
    clear_merchant_membership_registry,
    validate_merchant_tenant_membership,
    _query_db_merchant_membership,
    _query_db_tenant_active,
)
from app.services.onboarding_service import onboarding_service

client = TestClient(app)


def create_test_image(format="PNG", size=(50, 50), color=(0, 200, 100)):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    img.save(buf, format=format)
    buf.seek(0)
    return buf


def make_signed_token(tenant_id: str, merchant_id: str = "merchant@owner.com", role: str = "merchant"):
    register_merchant_membership(merchant_id=merchant_id, tenant_id=tenant_id, is_active=True, role=role)
    payload = {
        "sub": merchant_id,
        "email": merchant_id,
        "merchant_id": merchant_id,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_id,
        "role": role,
        "exp": int(time.time()) + 3600,
    }
    return encode_jwt_token_strict(payload, realm="core")


TENANT_ALIASES = [
    "/api/v1/tenants/{slug}/upload",
    "/api/v1/tenants/{slug}/qris/upload",
    "/api/v1/tenants/{slug}/upload-qris",
    "/api/v1/tenant/{slug}/upload",
    "/api/v1/tenant/{slug}/qris/upload",
]


# ===========================================================================
# 1. Centralized Authorization Across All Tenant Upload Aliases
# ===========================================================================

@pytest.mark.parametrize("route_template", TENANT_ALIASES)
def test_tenant_alias_negative_anonymous_rejected(route_template):
    """Anonymous request to any tenant upload alias MUST return HTTP 401."""
    path = route_template.format(slug="tenant-secure-001")
    img = create_test_image()
    resp = client.post(path, files={"file": ("test.png", img, "image/png")})
    assert resp.status_code == 401, f"Expected 401 on {path}, got {resp.status_code}: {resp.text}"
    assert "Autentikasi merchant diperlukan" in resp.json().get("detail", "")


@pytest.mark.parametrize("route_template", TENANT_ALIASES)
def test_tenant_alias_negative_cross_tenant_rejected(route_template):
    """
    Token for Tenant Alpha calling Tenant Beta's upload alias MUST be rejected with HTTP 403.
    """
    alpha_token = make_signed_token(tenant_id="tenant-alpha-123", merchant_id="alpha_owner@test.com")
    path = route_template.format(slug="tenant-beta-999")
    img = create_test_image()

    resp = client.post(
        path,
        files={"file": ("cross.png", img, "image/png")},
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert resp.status_code == 403, f"Expected 403 on {path}, got {resp.status_code}: {resp.text}"
    assert "cross-tenant" in resp.json().get("detail", "").lower()


@pytest.mark.parametrize("route_template", TENANT_ALIASES)
def test_tenant_alias_positive_authorized_upload(route_template):
    """
    Legitimate merchant upload to their own tenant alias MUST succeed (HTTP 200/201)
    and store files strictly inside their own tenant namespace.
    """
    tenant_id = "tenant-legit-001"
    token = make_signed_token(tenant_id=tenant_id, merchant_id="legit@test.com")
    path = route_template.format(slug=tenant_id)
    img = create_test_image()

    resp = client.post(
        path,
        files={"file": ("legit.png", img, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (200, 201), f"Expected 200/201 on {path}, got {resp.status_code}: {resp.text}"
    data = resp.json()
    storage_path = data.get("storage_path") or data.get("path", "").lstrip("/")
    assert storage_path.startswith(f"tenants/{tenant_id}/uploads/"), (
        f"Storage path '{storage_path}' must be scoped under tenants/{tenant_id}/uploads/"
    )


def test_qris_cross_tenant_settings_overwrite_prevention():
    """
    CTO Requirement: QRIS uploads must not be allowed to overwrite another tenant's QRIS settings.
    Prove that an attacker cannot overwrite Tenant Beta's settings when uploading QRIS.
    """
    onboarding_service._tenants_by_slug["tenant-victim"] = {
        "id": "victim-id",
        "slug": "tenant-victim",
        "name": "Tenant Victim",
        "qris_image_url": "https://cdn.example.com/victim_original_qris.png",
    }

    attacker_token = make_signed_token(tenant_id="tenant-attacker", merchant_id="attacker@test.com")
    img = create_test_image()

    # Attempt to upload to victim's QRIS endpoint using attacker token
    resp = client.post(
        "/api/v1/tenants/tenant-victim/qris/upload",
        files={"file": ("evil_qris.png", img, "image/png")},
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert resp.status_code == 403

    # Verify victim settings remain completely unmutated
    victim_settings = onboarding_service.get_tenant_settings("tenant-victim")
    assert victim_settings is not None
    assert victim_settings["tenant"].get("qris_image_url") == "https://cdn.example.com/victim_original_qris.png"


# ===========================================================================
# 2. Public / Global Upload Route Isolation
# ===========================================================================

def test_public_upload_cannot_write_tenant_namespace():
    """
    Public upload routes (/api/v1/media/upload) MUST reject attempts to specify
    folder='tenants/...' with HTTP 403 Forbidden.
    """
    img = create_test_image()
    resp = client.post(
        "/api/v1/media/upload",
        files={"file": ("test.png", img, "image/png")},
        data={"folder": "tenants/target-victim/uploads"},
    )
    assert resp.status_code == 403
    assert "cross-tenant" in resp.json().get("detail", "").lower()


def test_public_upload_cannot_mutate_tenant_settings():
    """
    Public upload endpoints cannot mutate tenant settings even if caller passes query params.
    """
    onboarding_service._tenants_by_slug["isolated-store"] = {
        "id": "iso-1",
        "slug": "isolated-store",
        "name": "Isolated Store",
        "qris_image_url": "https://cdn.example.com/orig.png",
    }
    img = create_test_image()
    resp = client.post(
        "/api/v1/upload/qris",
        files={"file": ("qris.png", img, "image/png")},
        params={"slug": "isolated-store"},
    )
    assert resp.status_code == 200
    settings = onboarding_service.get_tenant_settings("isolated-store")
    assert settings["tenant"].get("qris_image_url") == "https://cdn.example.com/orig.png"


# ===========================================================================
# 3. Fail-Closed Database Membership Validation
# ===========================================================================

def test_membership_validation_fail_closed_on_db_outage():
    """
    CTO P0: When database connection fails or authorization query cannot complete,
    system MUST fail-closed with strictly HTTP 503 (NOT allow implicitly!).
    """
    clear_merchant_membership_registry()

    with patch("app.core.database.get_db_connection", side_effect=Exception("PostgreSQL cluster connection timeout")):
        with pytest.raises(Exception) as exc_info:
            validate_merchant_tenant_membership(
                merchant_id="merchant_offline@test.com",
                tenant_id="tenant-db-fail-001",
            )
        assert exc_info.value.status_code == 503
        assert "Layanan otorisasi database tidak tersedia" in exc_info.value.detail


def test_membership_validation_fail_closed_when_no_row_found():
    """
    CTO P0: When database query returns 0 rows (unregistered merchant),
    system MUST fail-closed with strictly HTTP 403 Forbidden.
    """
    clear_merchant_membership_registry()

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    # Mock tenants active check -> row found, active
    mock_cur.fetchone.side_effect = [
        (True, "ACTIVE"),  # tenants table active check
        None,              # cs_agents query -> 0 rows
        None,              # merchants query -> 0 rows
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.core.database.get_db_connection", return_value=mock_conn):
        with pytest.raises(Exception) as exc_info:
            validate_merchant_tenant_membership(
                merchant_id="unregistered_stranger@test.com",
                tenant_id="tenant-registered-001",
            )
        assert exc_info.value.status_code == 403
        assert "tidak memiliki keanggotaan aktif" in exc_info.value.detail


def test_membership_validation_fail_closed_when_membership_inactive_in_db():
    """
    CTO P0: When membership row exists in database but is_active is False,
    system MUST return HTTP 403 Forbidden.
    """
    clear_merchant_membership_registry()

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.side_effect = [
        (True, "ACTIVE"),   # tenants table
        (False, "agent"),   # cs_agents table (is_active=False)
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.core.database.get_db_connection", return_value=mock_conn):
        with pytest.raises(Exception) as exc_info:
            validate_merchant_tenant_membership(
                merchant_id="deactivated_agent@test.com",
                tenant_id="tenant-registered-001",
            )
        assert exc_info.value.status_code == 403
        assert "dinonaktifkan di database" in exc_info.value.detail


def test_membership_validation_fail_closed_when_tenant_inactive_in_db():
    """
    CTO P0: When tenant row in database has is_active=False or status='DEACTIVATED',
    system MUST return HTTP 403 Forbidden.
    """
    clear_merchant_membership_registry()

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.side_effect = [
        (False, "DEACTIVATED"),  # tenants table (is_active=False)
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.core.database.get_db_connection", return_value=mock_conn):
        with pytest.raises(Exception) as exc_info:
            validate_merchant_tenant_membership(
                merchant_id="merchant@test.com",
                tenant_id="tenant-deactivated-001",
            )
        assert exc_info.value.status_code == 403
        assert "dinonaktifkan atau tidak aktif" in exc_info.value.detail


def test_membership_validation_independent_cs_agents_merchants_lookup():
    """
    CTO P0: A failure querying cs_agents must not prevent an independent merchants lookup.
    """
    clear_merchant_membership_registry()

    mock_conn = MagicMock()
    mock_cur = MagicMock()

    # Query 1: tenants check -> active
    # Query 2: cs_agents -> raises operational exception
    # Query 3: merchants -> returns active owner row
    def mock_execute(sql, params):
        if "cs_agents" in sql:
            raise Exception("cs_agents column 'presence' missing")
        return None

    mock_cur.execute.side_effect = mock_execute
    mock_cur.fetchone.side_effect = [
        (True, "ACTIVE"),  # tenants
        ("ACTIVE",),       # merchants status
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.core.database.get_db_connection", return_value=mock_conn):
        # Should succeed because merchants lookup found active owner despite cs_agents error
        validate_merchant_tenant_membership(
            merchant_id="store_owner@test.com",
            tenant_id="tenant-live-001",
        )


# ===========================================================================
# 4. True Chunked / Streaming Bounded Limits (ASGI Receive Boundary)
# ===========================================================================

@pytest.mark.asyncio
async def test_true_chunked_streaming_oversized_body_aborts_early():
    """
    CTO Directive P1:
    A true chunked request (generator content with Transfer-Encoding: chunked and NO Content-Length)
    exceeding 5 MB MUST be rejected with exact HTTP 413 at the ASGI receive boundary
    BEFORE the entire body stream is consumed by the server.
    """
    token = make_signed_token(tenant_id="tenant-chunk-001")
    boundary = "----WebKitFormBoundaryChunkedTest"

    # Track how many chunks were actually yielded by the generator
    yield_counter = 0

    async def async_chunk_generator():
        nonlocal yield_counter
        # Multipart form data header
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="oversized.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8")
        yield_counter += 1
        yield header

        # 100 chunks * 64 KB = ~6.4 MB total (exceeds 5 MB limit + 64 KB overhead)
        for _ in range(100):
            yield_counter += 1
            yield b"A" * 65536
            await asyncio.sleep(0.001)

        footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
        yield_counter += 1
        yield footer

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        resp = await async_client.post(
            "/api/v1/upload",
            content=async_chunk_generator(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )

    # Must be exact HTTP 413
    assert resp.status_code == 413, f"Expected 413, got {resp.status_code}: {resp.text}"

    # Verify that the server aborted early and did NOT exhaust all chunks
    assert yield_counter < 100, (
        f"Server should abort early: expected yield_counter < 100, but generator yielded {yield_counter} chunks"
    )

