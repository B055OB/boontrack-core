import io
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.main import app

client = TestClient(app)

def create_dummy_image(format="PNG", size=(1600, 1000), color=(255, 0, 0), mode="RGBA"):
    file_bytes = io.BytesIO()
    if mode == "RGBA":
        image = Image.new("RGBA", size, color + (255,))
    else:
        image = Image.new("RGB", size, color)
    image.save(file_bytes, format=format)
    file_bytes.seek(0)
    return file_bytes

def test_media_upload_success_and_resize():
    # Buat gambar 1600x1000 (lebar > 1200)
    img_data = create_dummy_image(format="PNG", size=(1600, 1000), mode="RGBA")
    
    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("test_banner.png", img_data, "image/png")}
    )
    
    assert response.status_code == 200, response.text
    data = response.json()
    
    assert "url" in data
    assert "file_size_kb" in data
    assert data["filename"].endswith(".webp")
    # Width harus di-resize ke 1200px
    assert data["width"] == 1200
    # Height harus maintain aspect ratio: 1000 * 1200 / 1600 = 750
    assert data["height"] == 750
    assert data["content_type"] == "image/webp"

def test_media_upload_small_image_no_upscale():
    # Buat gambar 800x600 (lebar <= 1200)
    img_data = create_dummy_image(format="JPEG", size=(800, 600), mode="RGB")
    
    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("small_product.jpg", img_data, "image/jpeg")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["width"] == 800
    assert data["height"] == 600
    assert data["filename"].endswith(".webp")

def test_media_upload_invalid_mime_type():
    file_data = io.BytesIO(b"Hello world this is a text file")
    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("document.txt", file_data, "text/plain")}
    )
    assert response.status_code == 400
    assert "MIME type harus berupa gambar" in response.json()["detail"]

def test_media_upload_exceed_size_limit():
    # File > 5MB
    large_data = io.BytesIO(b"0" * (5 * 1024 * 1024 + 1024))
    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("oversize.jpg", large_data, "image/jpeg")}
    )
    assert response.status_code == 400
    assert "melebihi batas maksimal 5 MB" in response.json()["detail"]


def test_media_upload_direct_v1_upload_alias():
    """Memverifikasi bahwa endpoint alias /api/v1/upload berhasil memproses gambar."""
    img_data = create_dummy_image(format="JPEG", size=(600, 600), mode="RGB")
    response = client.post(
        "/api/v1/upload",
        files={"file": ("product.jpg", img_data, "image/jpeg")}
    )
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert data["filename"].endswith(".webp")


def test_media_upload_direct_api_upload_alias():
    """Memverifikasi bahwa endpoint alias /api/upload berhasil memproses gambar."""
    img_data = create_dummy_image(format="JPEG", size=(500, 500), mode="RGB")
    response = client.post(
        "/api/upload",
        files={"file": ("product.jpg", img_data, "image/jpeg")}
    )
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert data["filename"].endswith(".webp")


def test_media_upload_with_image_field_name():
    """Memverifikasi bahwa form field bernama 'image' (bukan 'file') dapat diterima dengan sukses."""
    img_data = create_dummy_image(format="PNG", size=(400, 400), mode="RGBA")
    response = client.post(
        "/api/v1/upload",
        files={"image": ("frontend_item.png", img_data, "image/png")}
    )
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert data["filename"].endswith(".webp")


def test_media_upload_r2_integration():
    """Memverifikasi integrasi upload Cloudflare R2 mengembalikan URL publik R2."""
    from unittest.mock import patch
    expected_r2_url = "https://pub-cdf9b905df884053a60ef8bdb777d463.r2.dev/media/test_img_123.webp"
    
    with patch("app.services.storage.upload_media_to_r2", return_value=expected_r2_url) as mock_r2:
        img_data = create_dummy_image(format="JPEG", size=(700, 700), mode="RGB")
        response = client.post(
            "/api/v1/media/upload",
            files={"file": ("r2_product.jpg", img_data, "image/jpeg")}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == expected_r2_url
        assert data["public_url"] == expected_r2_url
        mock_r2.assert_called_once()


def test_media_upload_cors_shop_boontrack():
    """Memverifikasi header CORS untuk origin https://shop.boontrack.com pada preflight OPTIONS dan POST."""
    # Preflight OPTIONS
    opt_res = client.options(
        "/api/v1/media/upload",
        headers={
            "Origin": "https://shop.boontrack.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }
    )
    assert opt_res.status_code == 200
    assert opt_res.headers.get("access-control-allow-origin") == "https://shop.boontrack.com"

    # POST Request dengan Origin
    img_data = create_dummy_image(format="JPEG", size=(300, 300), mode="RGB")
    post_res = client.post(
        "/api/v1/media/upload",
        files={"file": ("shop_banner.jpg", img_data, "image/jpeg")},
        headers={"Origin": "https://shop.boontrack.com"}
    )
    assert post_res.status_code == 200
    assert post_res.headers.get("access-control-allow-origin") == "https://shop.boontrack.com"

