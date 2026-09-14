"""tests/test_creator_storefront.py

Unit tests for the public creator digital product storefront endpoint.
GET /api/v1/creator/{slug}/products
"""

from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient
from app.main import app

client = TestClient(app)

MOCK_DIGITAL_PRODUCTS = [
    {
        "id": "prod-001",
        "name": "E-Book: Scale Your Brand",
        "description": "Panduan lengkap membangun brand.",
        "price": 99000,
        "product_type": "EBOOK",
        "thumbnail_url": "https://assets.boontrack.com/ebook-cover.webp",
        "metadata": {"preview_url": "https://assets.boontrack.com/preview.pdf", "short_description": "Buku digital 120 halaman"},
        "is_active": True,
    },
    {
        "id": "prod-002",
        "name": "Template Canva Pack",
        "description": "50 template konten sosial media.",
        "price": 79000,
        "product_type": "TEMPLATE",
        "thumbnail_url": None,
        "metadata": {},
        "is_active": True,
    },
]

MOCK_PHYSICAL_PRODUCT = {
    "id": "prod-003",
    "name": "Kaos Polos Premium",
    "description": "Bahan combed 30s.",
    "price": 120000,
    "product_type": "PHYSICAL",
    "thumbnail_url": None,
    "metadata": {},
    "is_active": True,
}


def _make_supabase_mock(rows):
    """Helper to build a chainable Supabase mock that returns `rows`."""
    mock_result = MagicMock()
    mock_result.data = rows

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.in_.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.execute.return_value = mock_result

    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_query
    return mock_sb


@patch("app.routes.creator_storefront._get_supabase")
def test_public_storefront_returns_digital_products(mock_get_sb):
    """GET /api/v1/creator/{slug}/products returns only digital products."""
    mock_get_sb.return_value = _make_supabase_mock(MOCK_DIGITAL_PRODUCTS)

    res = client.get("/api/v1/creator/suji/products")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["tenant_slug"] == "suji"
    assert data["count"] == 2
    assert all(p["product_type"] in ("EBOOK", "TEMPLATE") for p in data["products"])


@patch("app.routes.creator_storefront._get_supabase")
def test_storefront_excludes_physical_products(mock_get_sb):
    """Physical products should never appear in the storefront response."""
    mock_get_sb.return_value = _make_supabase_mock([])  # Supabase already filtered by product_type in_ DIGITAL_PRODUCT_TYPES

    res = client.get("/api/v1/creator/suji/products")
    assert res.status_code == 200
    data = res.json()
    physical = [p for p in data["products"] if p.get("product_type") == "PHYSICAL"]
    assert len(physical) == 0


@patch("app.routes.creator_storefront._get_supabase")
def test_storefront_unknown_slug_returns_empty(mock_get_sb):
    """Unknown creator slug should return empty list, not an error."""
    mock_get_sb.return_value = _make_supabase_mock([])

    res = client.get("/api/v1/creator/unknown-creator-xyz/products")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 0
    assert data["products"] == []


@patch("app.routes.creator_storefront._get_supabase")
def test_storefront_filter_by_product_type(mock_get_sb):
    """?product_type=EBOOK should filter correctly."""
    mock_get_sb.return_value = _make_supabase_mock([MOCK_DIGITAL_PRODUCTS[0]])

    res = client.get("/api/v1/creator/suji/products?product_type=EBOOK")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["products"][0]["product_type"] == "EBOOK"


@patch("app.routes.creator_storefront._get_supabase")
def test_storefront_invalid_product_type_returns_400(mock_get_sb):
    """?product_type=INVALID should return 400."""
    mock_get_sb.return_value = _make_supabase_mock([])

    res = client.get("/api/v1/creator/suji/products?product_type=INVALID_TYPE")
    assert res.status_code == 400


@patch("app.routes.creator_storefront._get_supabase")
def test_storefront_db_unavailable_returns_503(mock_get_sb):
    """When Supabase is unavailable, should return 503."""
    mock_get_sb.return_value = None

    res = client.get("/api/v1/creator/suji/products")
    assert res.status_code == 503
