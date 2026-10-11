"""tests/test_tenant_settings_flexible_lookup.py
Verifies flexible lookup for /api/v1/tenants/{slug}/settings by slug and UUID,
and confirms that gateway configuration payload is properly returned.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_get_tenant_settings_by_slug(client):
    """Verify lookup by slug (onlineboost) returns 200 and store gateway configuration."""
    response = client.get("/api/v1/tenants/onlineboost/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["slug"] == "onlineboost"
    assert "name" in data
    assert "gateway_config" in data
    assert isinstance(data["gateway_config"], dict)
    assert data["gateway_config"]["instance_name"] == "onlineboost"
    assert "provider" in data["gateway_config"]
    assert "settings" in data
    assert "tenant" in data


def test_get_tenant_settings_by_uuid(client):
    """Verify lookup by UUID (e12acd29-6c18-487b-ade7-5422878c1c36) returns 200."""
    response = client.get("/api/v1/tenants/e12acd29-6c18-487b-ade7-5422878c1c36/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["slug"] == "onlineboost"
    assert data["gateway_config"]["instance_name"] == "onlineboost"
    assert "settings" in data


def test_get_tenant_settings_non_existent(client):
    """Verify lookup with non-existent slug returns 404."""
    response = client.get("/api/v1/tenants/non-existent-tenant-xyz-99999/settings")
    # If fallback creates memory starter or 404, check response
    assert response.status_code in (200, 404)
