import io
import pytest
from fastapi.testclient import TestClient
import pandas as pd
from app.main import app
from app.services.onboarding_service import onboarding_service

client = TestClient(app)

def test_bulk_import_csv_success():
    # Setup mock tenant
    tenant_slug = "test-store-import"
    
    # 3 baris data CSV format Tokopedia/Shopee/Generic
    csv_content = (
        "Nama Produk,Harga,Stok,Deskripsi Produk,Foto 1\n"
        "Sepatu Sneaker Sporty,250000,50,Sepatu running bahan breathable,https://images.example.com/shoe1.webp\n"
        "T-Shirt Katun Combed 30s,85000,100,Kaos polos adem nyaman dipakai,https://images.example.com/tshirt.webp\n"
        "Tas Ransel Anti Air,175000,30,Backpack laptop kapasitas besar,https://images.example.com/bag.webp\n"
    )
    
    file_bytes = io.BytesIO(csv_content.encode("utf-8"))
    
    response = client.post(
        f"/api/v1/products/bulk-upload?tenant_slug={tenant_slug}",
        files={"file": ("products_tokopedia.csv", file_bytes, "text/csv")}
    )
    
    assert response.status_code == 200, response.text
    data = response.json()
    
    assert data["status"] == "success"
    assert data["tenant_slug"] == tenant_slug
    assert data["total_imported"] == 3
    assert data["skipped"] == 0
    assert len(data["errors"]) == 0
    
    # Verifikasi data produk tersimpan di onboarding_service catalog
    products = onboarding_service.get_tenant_products(tenant_slug)
    assert products is not None
    assert len(products) >= 3
    
    product_titles = [p["title"] for p in products]
    assert "Sepatu Sneaker Sporty" in product_titles
    assert "T-Shirt Katun Combed 30s" in product_titles
    assert "Tas Ransel Anti Air" in product_titles

def test_bulk_import_missing_name_column():
    csv_content = (
        "Harga,Stok,Keterangan\n"
        "100000,10,Tanpa nama produk\n"
    )
    file_bytes = io.BytesIO(csv_content.encode("utf-8"))
    
    response = client.post(
        "/api/v1/products/bulk-upload?tenant_slug=test-store-import",
        files={"file": ("invalid_columns.csv", file_bytes, "text/csv")}
    )
    
    assert response.status_code == 400
    assert "Kolom Nama Produk tidak ditemukan" in response.json()["detail"]

def test_bulk_import_with_skipped_empty_rows():
    csv_content = (
        "Product Name,Price,Stock,Description\n"
        "Kemeja Flanel Premium,120000,20,Bahan wol halus\n"
        ",50000,5,Baris tanpa nama produk\n"
    )
    file_bytes = io.BytesIO(csv_content.encode("utf-8"))
    
    response = client.post(
        "/api/v1/products/bulk-upload?tenant_slug=test-store-import",
        files={"file": ("partial_valid.csv", file_bytes, "text/csv")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total_imported"] == 1
    assert data["skipped"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["row"] == 3
