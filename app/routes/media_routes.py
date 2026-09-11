"""
app/routes/media_routes.py
==========================
Endpoint upload media/gambar produk untuk BoonTrack Core.
Mendukung:
- Optimasi dan konversi otomatis ke WebP menggunakan Pillow.
- Upload terintegrasi ke Cloudflare R2 dengan graceful fallback ke Supabase Storage dan penyimpanan lokal.
- Mendukung FastAPI (ASGI) dan aiohttp (Web Runner Railway).
- Mendukung CORS penuh dari domain https://shop.boontrack.com dan storefront lainnya.
- Path aliases: /api/v1/media/upload, /api/v1/upload, /api/upload, /api/media/upload.
"""

import os
import io
import uuid
import logging
from io import BytesIO
from typing import Dict, Any, Optional
from PIL import Image

from fastapi import APIRouter, UploadFile, File, HTTPException, status, Request
from aiohttp import web

logger = logging.getLogger("MEDIA_UPLOAD_ROUTE")

media_router = APIRouter(prefix="/api/v1/media", tags=["Media Upload"])
general_upload_router = APIRouter(tags=["Media Upload Direct"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_WIDTH = 1200
WEBP_QUALITY = 85

# Project root directory for local fallback uploads
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


async def process_and_upload_image_bytes(
    raw_content: bytes,
    original_filename: str = "upload.jpg",
    content_type: str = "image/jpeg",
    base_url: str = ""
) -> Dict[str, Any]:
    """
    Memvalidasi, mengoptimasi ke format WebP (resize max 1200px), dan mengunggah
    gambar ke Cloudflare R2 (dengan fallback Supabase Storage / local assets).
    """
    file_size = len(raw_content)
    if file_size == 0:
        raise ValueError("File kosong tidak dapat diproses")

    # 1. Validasi Ukuran File (maksimal 5 MB)
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"Ukuran file melebihi batas maksimal 5 MB ({round(file_size / (1024 * 1024), 2)} MB)")

    # 2. Validasi MIME Type / Ekstensi
    clean_mime = (content_type or "").lower().strip()
    ext = os.path.splitext(original_filename)[1].lower()
    valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".svg")

    if not clean_mime.startswith("image/") and ext not in valid_exts:
        raise ValueError(f"File tidak valid. MIME type harus berupa gambar (image/*), diterima: '{content_type}'")

    # 3. Proses Gambar dengan Pillow (PIL)
    try:
        img = Image.open(BytesIO(raw_content))
    except Exception as e:
        raise ValueError(f"Format gambar korup atau tidak dapat diproses: {str(e)}")

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

    # Export ke buffer WebP
    webp_buffer = BytesIO()
    img.save(webp_buffer, "WEBP", quality=WEBP_QUALITY, optimize=True)
    webp_bytes = webp_buffer.getvalue()
    file_size_kb = round(len(webp_bytes) / 1024, 2)

    unique_id = uuid.uuid4().hex
    filename = f"img_{unique_id}.webp"

    # 4. Upload ke Cloudflare R2 (Primary Storage)
    image_url: Optional[str] = None
    try:
        from app.services.storage import upload_media_to_r2
        image_url = upload_media_to_r2(
            file_bytes=webp_bytes,
            file_name=filename,
            content_type="image/webp"
        )
        logger.info(f"[MEDIA UPLOAD] Sukses upload ke Cloudflare R2: {image_url}")
    except Exception as r2_err:
        logger.warning(f"[MEDIA UPLOAD] Cloudflare R2 tidak aktif/gagal ({r2_err}), mencoba fallback storage...")

    # 5. Fallback ke Supabase Storage jika R2 belum di-set
    if not image_url:
        try:
            from app.services.whatsapp_service import get_supabase
            supabase = get_supabase()
            if supabase:
                for bucket_name in ("product-images", "media", "products"):
                    try:
                        storage_path = f"products/{filename}"
                        supabase.storage.from_(bucket_name).upload(
                            path=storage_path,
                            file=webp_bytes,
                            file_options={"content-type": "image/webp"}
                        )
                        public_url_res = supabase.storage.from_(bucket_name).get_public_url(storage_path)
                        if public_url_res:
                            image_url = str(public_url_res)
                            logger.info(f"[MEDIA UPLOAD] Sukses upload ke Supabase Storage ({bucket_name}): {image_url}")
                            break
                    except Exception:
                        continue
        except Exception as sb_err:
            logger.debug(f"[MEDIA UPLOAD] Supabase storage fallback note: {sb_err}")

    # 6. Simpan backup lokal untuk StaticFiles /assets/uploads/{filename}
    local_path = os.path.join(UPLOAD_DIR, filename)
    try:
        with open(local_path, "wb") as f:
            f.write(webp_bytes)
    except Exception as save_err:
        logger.error(f"[MEDIA UPLOAD] Gagal simpan backup lokal: {save_err}")

    # Fallback terakhir jika kedua cloud storage offline
    if not image_url:
        base_clean = str(base_url or "").rstrip("/")
        if base_clean:
            image_url = f"{base_clean}/assets/uploads/{filename}"
        else:
            image_url = f"/assets/uploads/{filename}"

    return {
        "status": "success",
        "url": image_url,
        "path": f"/assets/uploads/{filename}",
        "public_url": image_url,
        "filename": filename,
        "width": new_width,
        "height": new_height,
        "file_size_kb": file_size_kb,
        "content_type": "image/webp"
    }


# ============================================================================
# FastAPI Route Handlers
# ============================================================================

async def _fastapi_handle_upload(
    request: Request,
    file: Optional[UploadFile] = None,
    image: Optional[UploadFile] = None,
) -> Dict[str, Any]:
    upload_file = file or image
    if upload_file is None:
        try:
            form = await request.form()
            for key in ("file", "image", "photo", "picture", "media", "upload"):
                val = form.get(key)
                if isinstance(val, UploadFile):
                    upload_file = val
                    break
            if upload_file is None:
                for val in form.values():
                    if isinstance(val, UploadFile):
                        upload_file = val
                        break
        except Exception:
            pass

    if upload_file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File gambar tidak ditemukan dalam request (pastikan form field bernama 'file' atau 'image')"
        )

    raw_content = await upload_file.read()
    base_url = str(request.base_url).rstrip("/")

    try:
        res = await process_and_upload_image_bytes(
            raw_content=raw_content,
            original_filename=upload_file.filename or "upload.jpg",
            content_type=upload_file.content_type or "image/jpeg",
            base_url=base_url
        )
        return res
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as exc:
        logger.error(f"[FastAPI Upload Exception] {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal memproses upload gambar: {str(exc)}"
        )


@media_router.post("/upload", summary="Upload and convert product/landing image to WebP")
async def upload_image(
    request: Request,
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    return await _fastapi_handle_upload(request, file=file, image=image)


# General & direct upload aliases
@general_upload_router.post("/api/v1/upload", summary="Direct v1 upload endpoint")
@general_upload_router.post("/api/upload", summary="Direct upload endpoint")
@general_upload_router.post("/api/media/upload", summary="Direct media upload endpoint")
@general_upload_router.post("/api/v1/products/upload-image", summary="Products image upload endpoint")
@general_upload_router.post("/api/v1/product/upload-image", summary="Product image upload endpoint singular")
async def general_upload_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    return await _fastapi_handle_upload(request, file=file, image=image)


# ============================================================================
# aiohttp Route Handlers & Registrar (Runner Aktif Server Railway)
# ============================================================================

def _build_cors_headers(request: web.Request) -> Dict[str, str]:
    origin = request.headers.get("Origin", "*")
    req_headers = request.headers.get("Access-Control-Request-Headers", "*")
    return {
        "Access-Control-Allow-Origin": origin if origin != "*" else "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": req_headers if req_headers != "*" else "Content-Type, Authorization, X-Requested-With, apikey, Accept, Origin",
    }


async def aiohttp_upload_image(request: web.Request) -> web.Response:
    """Handler upload gambar multipart untuk aiohttp server pada Railway."""
    cors_headers = _build_cors_headers(request)

    raw_content: Optional[bytes] = None
    content_type: str = "image/jpeg"
    filename: str = "upload.jpg"

    # 1. Coba ekstrak via request.post()
    try:
        post_data = await request.post()
        for key in ("file", "image", "photo", "picture", "media", "upload"):
            field = post_data.get(key)
            if field and hasattr(field, "file"):
                raw_content = field.file.read()
                filename = getattr(field, "filename", "upload.jpg") or "upload.jpg"
                content_type = getattr(field, "content_type", "image/jpeg") or "image/jpeg"
                break

        if raw_content is None:
            for v in post_data.values():
                if v and hasattr(v, "file"):
                    raw_content = v.file.read()
                    filename = getattr(v, "filename", "upload.jpg") or "upload.jpg"
                    content_type = getattr(v, "content_type", "image/jpeg") or "image/jpeg"
                    break
    except Exception as post_err:
        logger.debug(f"[aiohttp_upload_image post extract note]: {post_err}")

    # 2. Coba ekstrak via request.multipart() jika post_data belum mendapatkan file
    if raw_content is None:
        try:
            reader = await request.multipart()
            field = await reader.next()
            while field is not None:
                if hasattr(field, "filename") and field.filename:
                    raw_content = await field.read()
                    filename = field.filename
                    content_type = field.headers.get("Content-Type", "image/jpeg")
                    break
                field = await reader.next()
        except Exception as multi_err:
            logger.debug(f"[aiohttp_upload_image multipart extract note]: {multi_err}")

    if raw_content is None:
        return web.json_response(
            {"status": "error", "detail": "File gambar tidak ditemukan dalam form data (gunakan field 'file' atau 'image')"},
            status=400,
            headers=cors_headers
        )

    base_url = f"{request.scheme}://{request.host}"

    try:
        res = await process_and_upload_image_bytes(
            raw_content=raw_content,
            original_filename=filename,
            content_type=content_type,
            base_url=base_url
        )
        return web.json_response(res, status=200, headers=cors_headers)
    except ValueError as ve:
        return web.json_response(
            {"status": "error", "detail": str(ve)},
            status=400,
            headers=cors_headers
        )
    except Exception as exc:
        logger.error(f"[aiohttp_upload_image Exception] {exc}", exc_info=True)
        return web.json_response(
            {"status": "error", "detail": f"Gagal memproses upload gambar: {str(exc)}"},
            status=500,
            headers=cors_headers
        )


async def aiohttp_options_upload(request: web.Request) -> web.Response:
    """Preflight OPTIONS handler untuk upload gambar dari domain storefront."""
    cors_headers = _build_cors_headers(request)
    return web.Response(status=200, headers=cors_headers)


def register_media_routes(app: web.Application):
    """Mendaftarkan seluruh endpoint upload media dan OPTIONS handler ke aiohttp web.Application."""
    upload_paths = [
        "/api/v1/media/upload",
        "/api/v1/upload",
        "/api/media/upload",
        "/api/upload",
        "/api/v1/products/upload-image",
        "/api/v1/product/upload-image",
    ]
    existing_routes = set()
    for r in app.router.routes():
        try:
            canonical = getattr(getattr(r, "resource", None), "canonical", None)
            method = getattr(r, "method", None)
            if canonical and method:
                existing_routes.add((method.upper(), canonical.rstrip("/")))
        except Exception:
            pass

    for path in upload_paths:
        norm_path = path.rstrip("/")
        if ("POST", norm_path) not in existing_routes:
            app.router.add_post(path, aiohttp_upload_image)
        if ("OPTIONS", norm_path) not in existing_routes:
            app.router.add_options(path, aiohttp_options_upload)

    logger.info(f"[ROUTER] Media upload routes ({len(upload_paths)} paths) registered to aiohttp.")
