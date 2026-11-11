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
from fastapi import HTTPException
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


def test_tenant_lookup_returns_not_found_while_merchant_membership_exists():
    """
    CTO Work Order P0:
    When tenant lookup in database returns NOT_FOUND (0 rows),
    membership validation MUST fail-closed with strictly HTTP 403 Forbidden,
    even if merchant membership records exist.
    """
    clear_merchant_membership_registry()

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    # Tenant query returns None (row not found)
    mock_cur.fetchone.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.core.database.get_db_connection", return_value=mock_conn):
        with pytest.raises(Exception) as exc_info:
            validate_merchant_tenant_membership(
                merchant_id="owner@nonexistent.com",
                tenant_id="tenant-ghost-404",
            )
        assert exc_info.value.status_code == 403
        assert "tidak ditemukan" in exc_info.value.detail


def test_tenant_lookup_throws_database_exception_while_merchant_membership_exists():
    """
    CTO Work Order P0:
    When tenant lookup throws an operational / database exception (non-null tenant_err),
    it MUST NOT be ignored and MUST fail-closed with strictly HTTP 503 Service Unavailable.
    """
    clear_merchant_membership_registry()

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = Exception("PostgreSQL server terminated unexpectedly")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.core.database.get_db_connection", return_value=mock_conn):
        with pytest.raises(Exception) as exc_info:
            validate_merchant_tenant_membership(
                merchant_id="owner@test.com",
                tenant_id="tenant-db-crash-001",
            )
        assert exc_info.value.status_code == 503
        assert "Layanan otorisasi database tidak tersedia" in exc_info.value.detail


def test_membership_query_active_record_but_tenant_lookup_fails():
    """
    CTO Work Order P0:
    When membership query would return an active record, but tenant lookup returns explicitly
    inactive/suspended, the validation MUST strictly reject with HTTP 403 Forbidden.
    """
    clear_merchant_membership_registry()

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    # Tenant query returns explicitly inactive tenant
    mock_cur.fetchone.return_value = (False, "SUSPENDED")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.core.database.get_db_connection", return_value=mock_conn):
        with pytest.raises(Exception) as exc_info:
            validate_merchant_tenant_membership(
                merchant_id="owner@test.com",
                tenant_id="tenant-suspended-001",
            )
        assert exc_info.value.status_code == 403
        assert "dinonaktifkan atau tidak aktif" in exc_info.value.detail


def test_no_database_lookup_error_can_produce_authorization_success():
    """
    CTO Work Order P0:
    Negative assertion: No database lookup error (tenant or membership level)
    can ever produce an authorization success.
    """
    clear_merchant_membership_registry()

    error_scenarios = [
        # 1. Connection error on tenant query
        Exception("Connection refused (ECONNREFUSED)"),
        # 2. Syntax/Schema error on tenant query
        Exception("relation 'public.tenants' does not exist"),
        # 3. Read timeout
        TimeoutError("Query timed out after 5000ms"),
    ]

    for err in error_scenarios:
        with patch("app.core.database.get_db_connection", side_effect=err):
            with pytest.raises(Exception) as exc_info:
                validate_merchant_tenant_membership(
                    merchant_id="merchant@test.com",
                    tenant_id="tenant-err-test",
                )
            # Must strictly raise 503, NEVER allow or return None
            assert exc_info.value.status_code == 503
            assert "Layanan otorisasi database tidak tersedia" in exc_info.value.detail


def test_isolated_tenant_lookup_not_found_fails_closed_before_membership_check():
    """
    TASK 1 — Test 1:
    Tenant lookup returns: (False, "NOT_FOUND")
    Mock membership lookup to return: ({"is_active": True, "role": "owner"}, None)
    Expected: HTTP 403 Forbidden.
    Assert: _query_db_merchant_membership was NOT called.
    """
    clear_merchant_membership_registry()
    try:
        from app.api.deps import _test_tenants_registry
        _test_tenants_registry.pop("tenant-isolated-p0-404", None)
    except ImportError:
        pass

    with patch("app.routes.media_routes._query_db_tenant_active", return_value=(False, "NOT_FOUND")) as mock_tenant:
        with patch("app.routes.media_routes._query_db_merchant_membership", return_value=({"is_active": True, "role": "owner"}, None)) as mock_membership:
            with pytest.raises(Exception) as exc_info:
                validate_merchant_tenant_membership(
                    merchant_id="merchant_p0_1@test.com",
                    tenant_id="tenant-isolated-p0-404",
                )
            assert exc_info.value.status_code == 403
            assert "tidak ditemukan" in exc_info.value.detail
            mock_tenant.assert_called_once()
            mock_membership.assert_not_called()


def test_isolated_tenant_lookup_db_error_fails_closed_before_membership_check():
    """
    TASK 1 — Test 2:
    Tenant lookup returns: (False, "DB_QUERY_ERROR: simulated failure")
    Mock membership lookup to return: ({"is_active": True, "role": "owner"}, None)
    Expected: HTTP 503 Service Unavailable.
    Assert: _query_db_merchant_membership was NOT called.
    """
    clear_merchant_membership_registry()
    try:
        from app.api.deps import _test_tenants_registry
        _test_tenants_registry.pop("tenant-isolated-p0-503", None)
    except ImportError:
        pass

    with patch("app.routes.media_routes._query_db_tenant_active", return_value=(False, "DB_QUERY_ERROR: simulated failure")) as mock_tenant:
        with patch("app.routes.media_routes._query_db_merchant_membership", return_value=({"is_active": True, "role": "owner"}, None)) as mock_membership:
            with pytest.raises(Exception) as exc_info:
                validate_merchant_tenant_membership(
                    merchant_id="merchant_p0_2@test.com",
                    tenant_id="tenant-isolated-p0-503",
                )
            assert exc_info.value.status_code == 503
            assert "Layanan otorisasi database tidak tersedia" in exc_info.value.detail
            mock_tenant.assert_called_once()
            mock_membership.assert_not_called()


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


# ===========================================================================
# 5. Production Membership Registry Isolation (CTO P1)
# ===========================================================================

def test_production_membership_registry_mutation_prohibited_fail_closed(monkeypatch):
    """
    CTO Directive PR #28 Hardening (Requirement 3a, 3b):
    Calling register_merchant_membership, revoke_merchant_membership, or
    clear_merchant_membership_registry in production mode MUST raise
    RuntimeError("Operation prohibited in production environment") before accessing
    or modifying in-memory dictionaries, and the dictionaries MUST remain completely unmodified.
    """
    import copy
    from app.routes.media_routes import (
        _merchant_memberships,
        register_merchant_membership,
        revoke_merchant_membership,
        clear_merchant_membership_registry,
    )
    # Ensure clean starting state outside production
    _merchant_memberships.clear()
    _merchant_memberships[("seed_merchant", "seed_tenant")] = {
        "merchant_id": "seed_merchant",
        "tenant_id": "seed_tenant",
        "is_active": True,
        "role": "owner",
    }
    snapshot_before = copy.deepcopy(_merchant_memberships)

    try:
        # Enable production mode
        monkeypatch.setenv("APP_ENV", "production")

        # 1. register_merchant_membership prohibited in production
        with pytest.raises(RuntimeError) as exc_reg:
            register_merchant_membership("new_merchant", "new_tenant", is_active=True)
        assert str(exc_reg.value) == "Operation prohibited in production environment"
        assert _merchant_memberships == snapshot_before, "Registry was mutated despite production error"

        # 2. revoke_merchant_membership prohibited in production
        with pytest.raises(RuntimeError) as exc_rev:
            revoke_merchant_membership("seed_merchant", "seed_tenant")
        assert str(exc_rev.value) == "Operation prohibited in production environment"
        assert _merchant_memberships == snapshot_before, "Registry was mutated despite production error"

        # 3. clear_merchant_membership_registry prohibited in production
        with pytest.raises(RuntimeError) as exc_clr:
            clear_merchant_membership_registry()
        assert str(exc_clr.value) == "Operation prohibited in production environment"
        assert _merchant_memberships == snapshot_before, "Registry was cleared despite production error"
    finally:
        # Clean up environment and registry so failed assertions cannot leak test state
        monkeypatch.delenv("APP_ENV", raising=False)
        _merchant_memberships.clear()


def test_production_membership_fixture_active_still_performs_db_check(monkeypatch):
    """
    CTO Directive P1 (Requirement 1.1):
    In production mode, active test fixtures in _merchant_memberships MUST NOT bypass
    the authoritative PostgreSQL check. If database lookup returns no matching record,
    the request MUST be rejected with HTTP 403 Forbidden.
    """
    clean_m = "prod_owner@merchant.com"
    clean_t = "prod-tenant-001"

    # Seed in-memory test fixture as active BEFORE setting production environment
    register_merchant_membership(clean_m, clean_t, is_active=True, role="owner")

    # Set environment to production
    monkeypatch.setenv("APP_ENV", "production")

    try:
        # Mock DB: tenant is active, but membership record NOT found in PostgreSQL
        with patch("app.routes.media_routes._query_db_tenant_active", return_value=(True, None)) as mock_t_db, \
             patch("app.routes.media_routes._query_db_merchant_membership", return_value=(None, None)) as mock_m_db:

            with pytest.raises(HTTPException) as exc_info:
                validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)

            assert exc_info.value.status_code == 403
            assert "tidak memiliki keanggotaan aktif" in str(exc_info.value.detail)

            # Authoritative database checks MUST have been called despite active in-memory fixture
            mock_t_db.assert_called_once_with(clean_t)
            mock_m_db.assert_called_once_with(clean_m, clean_t)
    finally:
        monkeypatch.delenv("APP_ENV", raising=False)
        clear_merchant_membership_registry()


def test_production_test_tenants_registry_active_does_not_bypass_db(monkeypatch):
    """
    CTO Directive P1 (Requirement 1.2):
    In production mode, an active entry in _test_tenants_registry MUST NOT bypass
    the authoritative PostgreSQL tenant check. If database returns NOT_FOUND,
    the request MUST be rejected with HTTP 403 Forbidden.
    """
    from app.api.deps import _test_tenants_registry
    clean_m = "prod_owner@merchant.com"
    clean_t = "prod-tenant-reg-002"

    # Seed in-memory test registry
    _test_tenants_registry[clean_t] = {"id": clean_t, "is_active": True, "slug": clean_t}

    monkeypatch.setenv("ENVIRONMENT", "production")

    try:
        # Mock DB: tenant NOT found in database
        with patch("app.routes.media_routes._query_db_tenant_active", return_value=(False, "NOT_FOUND")) as mock_t_db:
            with pytest.raises(HTTPException) as exc_info:
                validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)

            assert exc_info.value.status_code == 403
            assert "tidak ditemukan di sistem" in str(exc_info.value.detail)
            mock_t_db.assert_called_once_with(clean_t)
    finally:
        _test_tenants_registry.pop(clean_t, None)


def test_production_database_membership_active_grants_access_only_on_authoritative_match(monkeypatch):
    """
    CTO Directive P1 (Requirement 1.3):
    In production mode, active access is granted if and only if the authoritative
    PostgreSQL tenant and membership records exist and are active.
    """
    clean_m = "authoritative_owner@merchant.com"
    clean_t = "authoritative-tenant-003"

    clear_merchant_membership_registry()
    monkeypatch.setenv("BOONTRACK_ENV", "production")

    # 1. Authoritative match: both tenant and membership active in DB -> SUCCESS
    with patch("app.routes.media_routes._query_db_tenant_active", return_value=(True, None)), \
         patch("app.routes.media_routes._query_db_merchant_membership", return_value=({"is_active": True, "role": "owner"}, None)):
        # Should execute cleanly without raising any HTTPException
        validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)

    # 2. Inactive membership in DB -> HTTP 403
    with patch("app.routes.media_routes._query_db_tenant_active", return_value=(True, None)), \
         patch("app.routes.media_routes._query_db_merchant_membership", return_value=({"is_active": False, "role": "owner"}, None)):
        with pytest.raises(HTTPException) as exc_info:
            validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)
        assert exc_info.value.status_code == 403
        assert "dinonaktifkan di database" in str(exc_info.value.detail)

    # 3. Inactive tenant in DB -> HTTP 403
    with patch("app.routes.media_routes._query_db_tenant_active", return_value=(False, None)), \
         patch("app.routes.media_routes._query_db_merchant_membership", return_value=({"is_active": True, "role": "owner"}, None)):
        with pytest.raises(HTTPException) as exc_info:
            validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)
        assert exc_info.value.status_code == 403
        assert "dinonaktifkan atau tidak aktif" in str(exc_info.value.detail)


def test_production_database_outage_produces_http_503(monkeypatch):
    """
    CTO Directive P1 (Requirement 1.4):
    In production mode, any database outage (connection failure or query error)
    MUST fail closed with strictly HTTP 503 Service Unavailable, even if in-memory
    fixtures are present.
    """
    clean_m = "outage_test@merchant.com"
    clean_t = "outage-tenant-004"

    # Seed in-memory test fixture BEFORE setting production mode
    register_merchant_membership(clean_m, clean_t, is_active=True, role="owner")
    monkeypatch.setenv("APP_ENV", "production")

    try:
        # 1. Tenant lookup DB outage -> HTTP 503
        with patch("app.routes.media_routes._query_db_tenant_active", return_value=(False, "DB_CONN_ERROR: connection refused")):
            with pytest.raises(HTTPException) as exc_info:
                validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)
            assert exc_info.value.status_code == 503
            assert "Layanan otorisasi database tidak tersedia" in str(exc_info.value.detail)

        # 2. Membership lookup DB outage -> HTTP 503
        with patch("app.routes.media_routes._query_db_tenant_active", return_value=(True, None)), \
             patch("app.routes.media_routes._query_db_merchant_membership", return_value=(None, "DB_LOOKUP_ERROR: timeout")):
            with pytest.raises(HTTPException) as exc_info:
                validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)
            assert exc_info.value.status_code == 503
            assert "Layanan otorisasi database tidak tersedia" in str(exc_info.value.detail)
    finally:
        monkeypatch.delenv("APP_ENV", raising=False)
        clear_merchant_membership_registry()


def test_development_test_environment_can_use_fixtures(monkeypatch):
    """
    CTO Directive P1 (Requirement 1.5):
    Outside production (e.g. APP_ENV=test or development), in-memory registries
    (_test_tenants_registry, _merchant_memberships) continue to function for test speed
    without requiring live database connections.
    """
    from app.api.deps import _test_tenants_registry
    clean_m = "dev_merchant@test.com"
    clean_t = "dev-tenant-005"

    monkeypatch.setenv("APP_ENV", "test")

    # Register active fixtures
    register_merchant_membership(clean_m, clean_t, is_active=True)
    _test_tenants_registry[clean_t] = {"id": clean_t, "is_active": True}

    try:
        # In non-production, fixture short-circuits before database lookup
        with patch("app.routes.media_routes._query_db_tenant_active") as mock_t_db, \
             patch("app.routes.media_routes._query_db_merchant_membership") as mock_m_db:
            # Should succeed using test fixture
            validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)
            mock_t_db.assert_not_called()
            mock_m_db.assert_not_called()

        # Revoking fixture produces HTTP 403
        revoke_merchant_membership(clean_m, clean_t)
        with pytest.raises(HTTPException) as exc_info:
            validate_merchant_tenant_membership(merchant_id=clean_m, tenant_id=clean_t)
        assert exc_info.value.status_code == 403
    finally:
        _test_tenants_registry.pop(clean_t, None)
        clear_merchant_membership_registry()


# ===========================================================================
# 6. Subscription Guard Fail-Closed (CTO P1)
# ===========================================================================

def test_subscription_guard_tenant_suspended_rejected():
    """
    CTO Directive P1 (Requirement 2.1):
    When tenant subscription is suspended or expired, assert_tenant_mutation_allowed
    raises HTTP 403 with exact SUBSCRIPTION_REQUIRED payload.
    Authorize_tenant_upload MUST propagate the 403 and reject the upload.
    """
    from app.core.subscription_guard import SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD
    tenant_id = "tenant-suspended-001"
    token = make_signed_token(tenant_id=tenant_id)
    img = create_test_image()

    with patch("app.core.subscription_guard.assert_tenant_mutation_allowed",
               side_effect=HTTPException(status_code=403, detail=SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD)):
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("test.png", img, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        data = resp.json()
        payload = data.get("detail", data) if isinstance(data.get("detail"), dict) else data
        assert payload.get("error") == "SUBSCRIPTION_REQUIRED"
        assert "Masa aktif paket/trial telah berakhir" in payload.get("message", "")


def test_subscription_guard_http_exception_passed_through():
    """
    CTO Directive P1 (Requirement 2.2):
    When assert_tenant_mutation_allowed raises any HTTPException, authorize_tenant_upload
    MUST preserve and re-raise it without modification.
    """
    tenant_id = "tenant-guard-custom-002"
    token = make_signed_token(tenant_id=tenant_id)
    img = create_test_image()

    with patch("app.core.subscription_guard.assert_tenant_mutation_allowed",
               side_effect=HTTPException(status_code=402, detail="Tier payment required for mutations")):
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("test.png", img, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 402
        assert "Tier payment required for mutations" in resp.text


def test_subscription_guard_runtime_error_upload_rejected_fail_closed():
    """
    CTO Directive P1 (Requirement 2.3):
    When assert_tenant_mutation_allowed encounters an unexpected RuntimeError,
    authorize_tenant_upload MUST NOT continue the upload. It MUST fail closed
    with HTTP 503 Service Unavailable.
    """
    tenant_id = "tenant-runtime-err-003"
    token = make_signed_token(tenant_id=tenant_id)
    img = create_test_image()

    with patch("app.core.subscription_guard.assert_tenant_mutation_allowed",
               side_effect=RuntimeError("Internal subscription service assertion failure")):
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("test.png", img, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503
        data = resp.json()
        assert "Layanan validasi langganan tenant tidak tersedia" in str(data["detail"])


def test_subscription_guard_dependency_database_unavailable_fail_closed():
    """
    CTO Directive P1 (Requirement 2.4):
    When subscription dependencies or databases are unreachable (e.g. ConnectionError),
    authorize_tenant_upload MUST fail closed with HTTP 503 Service Unavailable.
    """
    tenant_id = "tenant-db-outage-004"
    token = make_signed_token(tenant_id=tenant_id)
    img = create_test_image()

    with patch("app.core.subscription_guard.assert_tenant_mutation_allowed",
               side_effect=ConnectionError("Supabase subscription cluster timed out")):
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("test.png", img, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503
        data = resp.json()
        assert "fail-closed subscription guard" in str(data["detail"])


def test_subscription_guard_active_valid_tenant_allowed():
    """
    CTO Directive P1 (Requirement 2.5):
    When tenant subscription is active and valid, assert_tenant_mutation_allowed succeeds
    and authorize_tenant_upload allows the upload to proceed normally (HTTP 200/201).
    """
    tenant_id = "tenant-active-valid-005"
    token = make_signed_token(tenant_id=tenant_id)
    img = create_test_image()

    with patch("app.core.subscription_guard.assert_tenant_mutation_allowed",
               return_value={"is_suspended": False, "subscription_status": "active"}), \
         patch("app.services.storage.upload_media_to_r2", return_value="https://assets.boontrack.com/tenants/tenant-active-valid-005/uploads/test.png"):
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("test.png", img, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "success"
        assert "tenant-active-valid-005" in data["data"]["path"]


