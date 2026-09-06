import os
import uuid
from io import BytesIO
from typing import Dict, Any
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Request
from PIL import Image

media_router = APIRouter(prefix="/api/v1/media", tags=["Media Upload"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_WIDTH = 1200
WEBP_QUALITY = 85

# Project root directory for uploads
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@media_router.post("/upload", summary="Upload and convert product/landing image to WebP")
async def upload_image(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    # 1. Validasi MIME Type: image/*
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File tidak valid. MIME type harus berupa gambar (image/*), diterima: '{content_type}'"
        )

    # 2. Validasi Ukuran File (maksimal 5 MB)
    raw_content = await file.read()
    file_size = len(raw_content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ukuran file melebihi batas maksimal 5 MB ({round(file_size / (1024 * 1024), 2)} MB)"
        )

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File kosong tidak dapat diproses"
        )

    # 3. Proses Gambar dengan Pillow (PIL)
    try:
        img = Image.open(BytesIO(raw_content))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Format gambar korup atau tidak dapat diproses: {str(e)}"
        )

    original_width, original_height = img.size

    # Resize jika width > 1200px (maintain aspect ratio)
    if original_width > MAX_WIDTH:
        ratio = MAX_WIDTH / float(original_width)
        new_height = int(float(original_height) * ratio)
        new_width = MAX_WIDTH
        resample_filter = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize((new_width, new_height), resample=resample_filter)
    else:
        new_width = original_width
        new_height = original_height

    # Convert mode ke RGB jika RGBA / P / LA atau mode lain
    if img.mode in ("RGBA", "LA", "P"):
        # Buat canvas background putih untuk alpha compositing agar tidak meninggalkan artefak hitam
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        if "A" in img.mode:
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # 4. Simpan / Export ke WebP dengan quality=85, optimize=True
    unique_id = uuid.uuid4().hex
    filename = f"img_{unique_id}.webp"
    dest_path = os.path.join(UPLOAD_DIR, filename)

    try:
        img.save(dest_path, "WEBP", quality=WEBP_QUALITY, optimize=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menyimpan gambar WebP: {str(e)}"
        )

    saved_size_bytes = os.path.getsize(dest_path)
    file_size_kb = round(saved_size_bytes / 1024, 2)

    # Relative and absolute path URL
    # Relative path matches the StaticFiles mount in FastAPI: /assets/uploads/{filename}
    base_url = str(request.base_url).rstrip("/")
    image_url = f"{base_url}/assets/uploads/{filename}"

    return {
        "url": image_url,
        "path": f"/assets/uploads/{filename}",
        "filename": filename,
        "width": new_width,
        "height": new_height,
        "file_size_kb": file_size_kb,
        "content_type": "image/webp"
    }
