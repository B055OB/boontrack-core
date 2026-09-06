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
