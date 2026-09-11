import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.onboarding_service import (
    onboarding_service,
    sanitize_product_slug,
    ensure_unique_product_slug
)

client = TestClient(app)


def test_sanitize_product_slug():
    assert sanitize_product_slug("E-Book Rahasia Ads 2026!") == "e-book-rahasia-ads-2026"
    assert sanitize_product_slug("Kelas Facebook Ads & TikTok Ads @2026 #1") == "kelas-facebook-ads-tiktok-ads-2026-1"
    assert sanitize_product_slug("   ---Belajar___Online???---  ") == "belajar-online"
    assert sanitize_product_slug("") == "product"
    assert sanitize_product_slug("Produk / Jasa (Retail)") == "produk-jasa-retail"


def test_ensure_unique_product_slug():
    existing = [
        {"id": "p1", "slug": "kursus-ads"},
        {"id": "p2", "slug": "kursus-ads-2"},
    ]
    # Updating p1 with same slug kursus-ads should keep kursus-ads
    assert ensure_unique_product_slug(
        "kursus-ads",
        "tenant-1",
        current_product_id="p1",
        existing_products=existing
    ) == "kursus-ads"

    # New product p3 wanting kursus-ads should get kursus-ads-3
    assert ensure_unique_product_slug(
        "kursus-ads",
        "tenant-1",
        current_product_id="p3",
        existing_products=existing
    ) == "kursus-ads-3"


def test_put_product_slug_update():
    tenant_slug = "store-slug-test"
    onboarding_service._tenants_by_slug[tenant_slug] = {"id": "t-slug-1", "slug": tenant_slug, "name": "Store Slug Test"}

    # Create initial product
    prod = onboarding_service.upsert_tenant_product(tenant_slug, {
        "id": "prod-101",
        "title": "Produk Asli",
        "price": 100000,
    })
    assert prod["slug"] == "produk-asli"

    # Update with custom slug with uppercase, spaces, and special characters
    response = client.put(
        "/api/v1/products/prod-101",
        json={
            "tenant_slug": tenant_slug,
            "title": "Produk Asli Updated",
            "slug": "  SALESPAGE_Khusus 2026!!  ",
            "price": 150000
        }
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    assert data["product"]["slug"] == "salespage-khusus-2026"
    assert data["product"]["title"] == "Produk Asli Updated"
    assert data["product"]["price"] == 150000


def test_slug_uniqueness_on_update():
    tenant_slug = "store-unique-test"
    onboarding_service._tenants_by_slug[tenant_slug] = {"id": "t-unique-1", "slug": tenant_slug, "name": "Store Unique Test"}

    # Create Product A
    onboarding_service.upsert_tenant_product(tenant_slug, {
        "id": "prod-a",
        "title": "Masterclass Ads",
        "slug": "masterclass-ads",
        "price": 200000
    })

    # Create Product B
    onboarding_service.upsert_tenant_product(tenant_slug, {
        "id": "prod-b",
        "title": "Ebook Copywriting",
        "slug": "ebook-copywriting",
        "price": 100000
    })

    # Update Product B wanting the same slug "masterclass-ads"
    response = client.put(
        "/api/v1/products/prod-b",
        json={
            "tenant_slug": tenant_slug,
            "slug": "masterclass-ads"
        }
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["product"]["slug"] == "masterclass-ads-2"


def test_tenant_put_product_endpoint():
    tenant_slug = "store-endpoint-test"
    onboarding_service._tenants_by_slug[tenant_slug] = {"id": "t-ep-1", "slug": tenant_slug, "name": "Store EP Test"}

    onboarding_service.upsert_tenant_product(tenant_slug, {
        "id": "prod-ep",
        "title": "Initial Product",
        "price": 50000
    })

    response = client.put(
        f"/api/v1/tenants/{tenant_slug}/products/prod-ep",
        json={
            "title": "Renamed Product",
            "slug": "renamed-product-custom",
            "price": 75000
        }
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["product"]["slug"] == "renamed-product-custom"
