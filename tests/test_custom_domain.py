"""tests/test_custom_domain.py
Unit and Integration Tests for Cloudflare SaaS Custom Domain Management.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.services.cloudflare import (
    clean_domain,
    validate_domain_name,
    cloudflare_service,
    CloudflareAPIError,
    DEFAULT_CNAME_TARGET,
)
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_domain_sanitization():
    """Verify domain sanitization cleans schemes, paths, ports, and whitespace."""
    assert clean_domain("  https://store.example.com/  ") == "store.example.com"
    assert clean_domain("http://MY-STORE.COM:8080/path") == "my-store.com"
    assert clean_domain("shop.boon.id") == "shop.boon.id"


def test_domain_validation():
    """Verify domain validation rules."""
    valid, d, err = validate_domain_name("https://toko.keren.com/")
    assert valid is True
    assert d == "toko.keren.com"
    assert err is None

    valid, d, err = validate_domain_name("shop.brand-anda.co.id")
    assert valid is True
    assert d == "shop.brand-anda.co.id"

    # Reserved domain
    valid, d, err = validate_domain_name("shop.boontrack.com")
    assert valid is False
    assert "internal sistem" in err

    valid, d, err = validate_domain_name("boontrack.com")
    assert valid is False

    # Invalid characters / format
    valid, d, err = validate_domain_name("invalid_domain")
    assert valid is False

    valid, d, err = validate_domain_name("")
    assert valid is False


@pytest.mark.asyncio
async def test_cloudflare_service_create_custom_hostname():
    """Verify cloudflare_service calls Cloudflare API with proper payload."""
    mock_cf_response = {
        "success": True,
        "result": {
            "id": "cf_host_123",
            "hostname": "toko.brandku.com",
            "status": "pending",
            "ssl": {
                "status": "pending_validation",
                "method": "http",
                "validation_records": [
                    {"http_url": "http://toko.brandku.com/.well-known/pki-validation/1.txt"}
                ]
            },
            "ownership_verification": {
                "type": "txt",
                "name": "_cf-custom-hostname.toko.brandku.com",
                "value": "verify-123"
            }
        }
    }

    with patch.object(cloudflare_service, "is_configured", return_value=True), \
         patch.object(cloudflare_service, "zone_id", "test_zone_id"), \
         patch.object(cloudflare_service, "api_token", "test_token"), \
         patch("httpx.AsyncClient.post") as mock_post:
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_cf_response
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = await cloudflare_service.create_custom_hostname("toko.brandku.com", ssl_method="http")
        assert result["id"] == "cf_host_123"
        assert result["hostname"] == "toko.brandku.com"
        assert result["status"] == "pending"
        assert result["ssl_status"] == "pending_validation"
        assert result["cname_target"] == DEFAULT_CNAME_TARGET


@pytest.mark.asyncio
async def test_cloudflare_service_conflict_handling():
    """Verify cloudflare_service raises 409 CloudflareAPIError on duplicate hostname."""
    mock_cf_error = {
        "success": False,
        "errors": [{"code": 1406, "message": "hostname already exists"}]
    }

    with patch.object(cloudflare_service, "is_configured", return_value=True), \
         patch.object(cloudflare_service, "zone_id", "test_zone_id"), \
         patch.object(cloudflare_service, "api_token", "test_token"), \
         patch("httpx.AsyncClient.post") as mock_post:
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_cf_error
        mock_resp.status_code = 400
        mock_post.return_value = mock_resp

        with pytest.raises(CloudflareAPIError) as exc_info:
            await cloudflare_service.create_custom_hostname("already.exists.com")
        
        assert exc_info.value.status_code == 409
        assert "sudah terdaftar" in exc_info.value.message



def test_fastapi_custom_domain_endpoints(client):
    """Test full FastAPI endpoint flow with mocked Cloudflare & Supabase."""
    mock_cf_data = {
        "id": "cf_host_abc",
        "hostname": "shop.mybrand.com",
        "status": "pending",
        "ssl_status": "pending_validation",
        "ssl_method": "http",
        "cname_target": "shop.boontrack.com",
        "ownership_verification": {"type": "txt", "name": "_cf", "value": "val"},
        "ssl_validation_records": [],
    }

    with patch("app.routes.custom_domain_routes.cloudflare_service.create_custom_hostname", return_value=mock_cf_data), \
         patch("app.routes.custom_domain_routes._get_tenant_record_from_db", return_value=({"id": "t1", "slug": "onlineboost"}, {})), \
         patch("app.routes.custom_domain_routes._update_tenant_metadata", return_value=True), \
         patch("app.routes.custom_domain_routes._check_domain_conflict_across_tenants", return_value=None):

        # 1. Register Custom Domain
        post_resp = client.post(
            "/api/v1/store/custom-domain",
            json={
                "domain": "shop.mybrand.com",
                "tenant_slug": "onlineboost",
                "ssl_method": "http"
            }
        )
        assert post_resp.status_code == 200
        data = post_resp.json()
        assert data["status"] == "success"
        assert data["custom_domain"] == "shop.mybrand.com"
        assert data["cloudflare_hostname_id"] == "cf_host_abc"
        assert data["cname_target"] == "shop.boontrack.com"
        assert "dns_instructions" in data

    # 2. Check Status
    mock_status_data = {
        "id": "cf_host_abc",
        "hostname": "shop.mybrand.com",
        "status": "active",
        "ssl_status": "active",
        "is_active": True,
        "cname_target": "shop.boontrack.com",
        "ownership_verification": None,
        "ssl_validation_records": [],
    }
    existing_meta = {
        "custom_domain": "shop.mybrand.com",
        "cloudflare_hostname_id": "cf_host_abc",
        "custom_domain_status": "pending",
    }

    with patch("app.routes.custom_domain_routes.cloudflare_service.get_custom_hostname_status", return_value=mock_status_data), \
         patch("app.routes.custom_domain_routes._get_tenant_record_from_db", return_value=({"id": "t1", "slug": "onlineboost"}, existing_meta)), \
         patch("app.routes.custom_domain_routes._update_tenant_metadata", return_value=True):

        get_resp = client.get("/api/v1/store/custom-domain/status?tenant_slug=onlineboost")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["status"] == "success"
        assert data["custom_domain_status"] == "active"
        assert data["is_active"] is True

    # 3. Delete Custom Domain
    with patch("app.routes.custom_domain_routes.cloudflare_service.delete_custom_hostname", return_value={"success": True}), \
         patch("app.routes.custom_domain_routes._get_tenant_record_from_db", return_value=({"id": "t1", "slug": "onlineboost"}, existing_meta)), \
         patch("app.routes.custom_domain_routes._update_tenant_metadata", return_value=True):

        del_resp = client.delete("/api/v1/store/custom-domain?tenant_slug=onlineboost")
        assert del_resp.status_code == 200
        del_data = del_resp.json()
        assert del_data["status"] == "success"
        assert del_data["deleted_domain"] == "shop.mybrand.com"


def test_fastapi_custom_domain_invalid_format(client):
    """Verify 400 Bad Request on invalid domain input."""
    resp = client.post(
        "/api/v1/store/custom-domain",
        json={
            "domain": "not-a-valid-domain",
            "tenant_slug": "onlineboost"
        }
    )
    assert resp.status_code == 400
    assert "tidak valid" in resp.json()["detail"]
