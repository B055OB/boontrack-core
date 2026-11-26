"""
tests/test_reserved_route_manifest.py
Core Backend Verification Test for Reserved Route Manifest v1
"""

import hashlib
import json
from pathlib import Path
import sys

# Add repo root to python path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from app.routing.reserved_routes import (
    RESERVED_ROUTE_MANIFEST_SHA256,
    RESERVED_ROUTE_MANIFEST_VERSION,
    RESERVED_SLUGS_SET,
    is_reserved_route_slug,
    get_reserved_slug_namespace,
    assert_not_reserved_tenant_slug,
    validate_and_extract_route,
    ReservedRouteConflictError,
    MANIFEST_PATH,
)


def test_manifest_sha256_hash():
    with open(MANIFEST_PATH, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest().upper()
    assert file_hash == RESERVED_ROUTE_MANIFEST_SHA256
    assert file_hash == "FCE2E8FCA08FDA336F46B4EA648D2D139E0B8BE6F20DF2BB951EEBF9FFAC6DAD"
    assert RESERVED_ROUTE_MANIFEST_VERSION == "1.0.0"


def test_reserved_slugs_lookup():
    assert is_reserved_route_slug("about") is True
    assert is_reserved_route_slug("shop") is True
    assert is_reserved_route_slug("creator") is True
    assert is_reserved_route_slug("terms") is True
    assert is_reserved_route_slug("admin") is True

    # Segment-aware check
    assert is_reserved_route_slug("blogger") is False
    assert is_reserved_route_slug("onlineboost") is False
    assert is_reserved_route_slug("career") is False
    assert is_reserved_route_slug("careers") is True


def test_namespaces():
    assert get_reserved_slug_namespace("about") == "corporate"
    assert get_reserved_slug_namespace("terms") == "legal"
    assert get_reserved_slug_namespace("sms") == "platform"
    assert get_reserved_slug_namespace("shop") == "tricore"
    assert get_reserved_slug_namespace("docs") == "documentation"
    assert get_reserved_slug_namespace("health") == "operations"
    assert get_reserved_slug_namespace("pricing") == "commercial"
    assert get_reserved_slug_namespace("admin") == "system_and_internal"


def test_assert_not_reserved():
    with pytest.raises(ReservedRouteConflictError):
        assert_not_reserved_tenant_slug("about")

    # Should not raise for allowed slugs
    assert_not_reserved_tenant_slug("onlineboost")
    assert_not_reserved_tenant_slug("nyka")


def test_validate_and_extract_route():
    valid, path, seg, sub, is_res, ns, err = validate_and_extract_route("/onlineboost/products/123")
    assert valid is True
    assert seg == "onlineboost"
    assert sub == "/products/123"
    assert is_res is False

    valid, path, seg, sub, is_res, ns, err = validate_and_extract_route("/about")
    assert valid is True
    assert seg == "about"
    assert is_res is True
    assert ns == "corporate"

    # Security rejections
    valid, _, _, _, _, _, err = validate_and_extract_route("/onlineboost%2fhidden")
    assert valid is False
    assert "Percent-encoded separators" in err

    valid, _, _, _, _, _, err = validate_and_extract_route("/onlineboost/../admin")
    assert valid is False
    assert "Path traversal" in err

    valid, _, _, _, _, _, err = validate_and_extract_route("//onlineboost")
    assert valid is False
    assert "Double slashes" in err


if __name__ == "__main__":
    test_manifest_sha256_hash()
    test_reserved_slugs_lookup()
    test_namespaces()
    test_assert_not_reserved()
    test_validate_and_extract_route()
    print("ALL CORE ROUTING TESTS PASSED (5/5)!")
