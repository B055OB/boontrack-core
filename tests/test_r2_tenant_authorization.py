"""tests/test_r2_tenant_authorization.py
CTO Directive 08 Priority 1 (P1-H3) Comprehensive Negative & Positive Test Suite.

Verifies:
1. Mandatory current_tenant_id: Zero fallback to caller-supplied tenant_id.
2. Tenant Boundary Isolation (Alpha vs Beta).
3. Parameter manipulation detection (current_tenant_id != tenant_id).
4. System namespace restriction (allow_system_namespace=True required for system/ and tenants/system/).
5. Path traversal defense: URL encoding variations (%2e%2e, %2f, %5c, nested percent-encoding).
6. Path separator variations (\\, //).
7. Dot segment variations (., ..).
8. Empty path and whitespace rejection.
9. Case-insensitive namespace handling (Tenants/, SYSTEM/, VIDEOS/).
10. TTL boundaries (<= 0 or > 900s).
"""

import pytest
from unittest.mock import MagicMock, patch
from app.services.storage.r2 import (
    R2Client,
    generate_presigned_download_url,
)


@pytest.fixture
def mock_r2_client():
    client = R2Client(
        account_id="test_acc",
        access_key_id="test_key",
        secret_access_key="test_secret",
        bucket_name="test_bucket",
        public_domain="assets.boontrack.com",
    )
    boto_mock = MagicMock()
    boto_mock.generate_presigned_url.return_value = "https://assets.boontrack.com/signed-test-url"
    client._s3_client = boto_mock
    return client


# 1. Mandatory current_tenant_id & Zero Fallback
def test_missing_current_tenant_id_raises_value_error(mock_r2_client):
    with pytest.raises(ValueError, match="current_tenant_id is mandatory"):
        mock_r2_client.generate_presigned_download_url(
            object_key="tenants/tenant_alpha/doc.pdf",
            current_tenant_id="",
        )

    with pytest.raises(ValueError, match="current_tenant_id is mandatory"):
        mock_r2_client.generate_presigned_download_url(
            object_key="tenants/tenant_alpha/doc.pdf",
            current_tenant_id=None,  # type: ignore
        )


def test_no_fallback_from_tenant_id_when_current_tenant_id_is_missing(mock_r2_client):
    """Zero tolerance fallback: providing tenant_id without current_tenant_id MUST fail."""
    with pytest.raises(ValueError, match="current_tenant_id is mandatory"):
        mock_r2_client.generate_presigned_download_url(
            object_key="tenants/tenant_alpha/doc.pdf",
            current_tenant_id="",
            tenant_id="tenant_alpha",
        )


# 2. Parameter Tamper Detection
def test_parameter_manipulation_mismatch_raises_permission_error(mock_r2_client):
    with pytest.raises(PermissionError, match="Tenant parameter manipulation detected"):
        mock_r2_client.generate_presigned_download_url(
            object_key="tenants/tenant_alpha/doc.pdf",
            current_tenant_id="tenant_alpha",
            tenant_id="tenant_beta",
        )


# 3. Cross-Tenant Negative Test (Alpha vs Beta)
def test_alpha_access_beta_raises_permission_error(mock_r2_client):
    with pytest.raises(PermissionError, match="Cross-tenant storage access forbidden"):
        mock_r2_client.generate_presigned_download_url(
            object_key="tenants/tenant_beta/private/doc.pdf",
            current_tenant_id="tenant_alpha",
        )


# 4. System Namespace Isolation
def test_tenant_access_system_namespace_without_flag_is_blocked(mock_r2_client):
    with pytest.raises(PermissionError, match="restricted to internal system/admin context"):
        mock_r2_client.generate_presigned_download_url(
            object_key="system/private_key.pem",
            current_tenant_id="tenant_alpha",
            allow_system_namespace=False,
        )

    with pytest.raises(PermissionError, match="restricted to internal system/admin context"):
        mock_r2_client.generate_presigned_download_url(
            object_key="tenants/system/config.json",
            current_tenant_id="tenant_alpha",
            allow_system_namespace=False,
        )


def test_system_namespace_with_explicit_flag_is_authorized(mock_r2_client):
    url = mock_r2_client.generate_presigned_download_url(
        object_key="system/template.pdf",
        current_tenant_id="admin_system",
        allow_system_namespace=True,
    )
    assert "https://assets.boontrack.com" in url

    url2 = mock_r2_client.generate_presigned_download_url(
        object_key="tenants/system/shared_badge.png",
        current_tenant_id="admin_system",
        allow_system_namespace=True,
    )
    assert "https://assets.boontrack.com" in url2


# 5. Path Traversal & Dot Segment Defense
@pytest.mark.parametrize(
    "traversal_key",
    [
        "tenants/tenant_alpha/../tenant_beta/secret.mp4",
        "tenants/tenant_alpha/..\\tenant_beta\\secret.mp4",
        "../tenants/tenant_alpha/doc.pdf",
        "tenants/tenant_alpha/./doc.pdf",
        "tenants/tenant_alpha/sub/../../tenant_beta/data.bin",
        "tenants/tenant_alpha/%2e%2e/tenant_beta/data.bin",
        "tenants/tenant_alpha/%2E%2E/tenant_beta/data.bin",
        "tenants%2Ftenant_alpha%2F%2e%2e%2Ftenant_beta%2Fdoc.pdf",
        "tenants/tenant_alpha/%252e%252e/tenant_beta/doc.pdf",  # double URL-encoded ..
        "tenants\\tenant_alpha\\..\\tenant_beta\\doc.pdf",
    ],
)
def test_path_traversal_variations_raise_permission_error(mock_r2_client, traversal_key):
    with pytest.raises(PermissionError):
        mock_r2_client.generate_presigned_download_url(
            object_key=traversal_key,
            current_tenant_id="tenant_alpha",
        )


# 6. Path Separator Variations
def test_backslash_normalization_valid_object(mock_r2_client):
    url = mock_r2_client.generate_presigned_download_url(
        object_key="tenants\\tenant_alpha\\documents\\invoice.pdf",
        current_tenant_id="tenant_alpha",
    )
    assert url is not None
    mock_r2_client._s3_client.generate_presigned_url.assert_called_with(
        ClientMethod="get_object",
        Params={"Bucket": "test_bucket", "Key": "tenants/tenant_alpha/documents/invoice.pdf"},
        ExpiresIn=900,
    )


def test_double_slash_normalization_valid_object(mock_r2_client):
    url = mock_r2_client.generate_presigned_download_url(
        object_key="tenants//tenant_alpha///documents//invoice.pdf",
        current_tenant_id="tenant_alpha",
    )
    assert url is not None
    mock_r2_client._s3_client.generate_presigned_url.assert_called_with(
        ClientMethod="get_object",
        Params={"Bucket": "test_bucket", "Key": "tenants/tenant_alpha/documents/invoice.pdf"},
        ExpiresIn=900,
    )


# 7. Empty & Whitespace Object Key
@pytest.mark.parametrize(
    "empty_key",
    ["", "   ", "///", "\\\\\\", "  /  ", None],
)
def test_empty_or_blank_key_raises_value_error(mock_r2_client, empty_key):
    with pytest.raises(ValueError, match="object_key cannot be empty"):
        mock_r2_client.generate_presigned_download_url(
            object_key=empty_key,
            current_tenant_id="tenant_alpha",
        )


# 8. Namespace Casing Differences
def test_namespace_casing_handling(mock_r2_client):
    # Valid capitalized namespace
    url = mock_r2_client.generate_presigned_download_url(
        object_key="Tenants/tenant_alpha/file.pdf",
        current_tenant_id="tenant_alpha",
    )
    assert url is not None

    # Capitalized system namespace blocked without flag
    with pytest.raises(PermissionError, match="restricted to internal system/admin context"):
        mock_r2_client.generate_presigned_download_url(
            object_key="SYSTEM/super_secret.key",
            current_tenant_id="tenant_alpha",
            allow_system_namespace=False,
        )


# 9. TTL Boundary Tests
def test_ttl_exceeded_raises_value_error(mock_r2_client):
    with pytest.raises(ValueError, match="cannot exceed 900 seconds"):
        mock_r2_client.generate_presigned_download_url(
            object_key="tenants/tenant_alpha/file.pdf",
            current_tenant_id="tenant_alpha",
            expires_in=1800,
        )


def test_ttl_non_positive_raises_value_error(mock_r2_client):
    with pytest.raises(ValueError, match="must be greater than 0"):
        mock_r2_client.generate_presigned_download_url(
            object_key="tenants/tenant_alpha/file.pdf",
            current_tenant_id="tenant_alpha",
            expires_in=0,
        )


# 10. Legitimate Tenant Access
def test_legitimate_tenant_access_succeeds(mock_r2_client):
    url = mock_r2_client.generate_presigned_download_url(
        object_key="tenants/tenant_alpha/private/summary.pdf",
        current_tenant_id="tenant_alpha",
        expires_in=600,
    )
    assert "https://assets.boontrack.com" in url
    mock_r2_client._s3_client.generate_presigned_url.assert_called_with(
        ClientMethod="get_object",
        Params={"Bucket": "test_bucket", "Key": "tenants/tenant_alpha/private/summary.pdf"},
        ExpiresIn=600,
    )
