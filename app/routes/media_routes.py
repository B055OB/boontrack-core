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
    base_url: str = "",
    folder: Optional[str] = None,
    is_qris: bool = False,
) -> Dict[str, Any]:
    """
    Memvalidasi gambar (mendukung QRIS dan gambar produk), mengoptimasi:
    - QRIS: Menggunakan format PNG crisp tanpa lossy compression, komposit latar belakang putih
      (mencegah transparansi QR rusak saat dibuka di dark mode), dan disimpan ke storage path 'qris/'.
    - Gambar Umum/Produk: Mengoptimasi ke format WebP (resize max 1200px, quality 85) ke path 'media/'.
    - Mengunggah ke Cloudflare R2 (dengan fallback Supabase Storage / local assets).
    """
    file_size = len(raw_content)
    if file_size == 0:
        raise ValueError("File kosong tidak dapat diproses")

    # 1. Validasi Ukuran File (maksimal 5 MB)
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"Ukuran file melebihi batas maksimal 5 MB ({round(file_size / (1024 * 1024), 2)} MB)")

    # Deteksi QRIS
    fn_lower = (original_filename or "").lower()
    clean_mime = (content_type or "").lower().strip()
    if is_qris or folder == "qris" or "qris" in fn_lower or ("qr" in fn_lower and ("code" in fn_lower or "upload" in fn_lower or "pay" in fn_lower)):
        is_qris_mode = True
        target_folder = "qris"
    else:
        is_qris_mode = False
        target_folder = (folder or "media").strip("/ ") or "media"

    # 2. Validasi MIME Type / Ekstensi
    ext = os.path.splitext(original_filename)[1].lower()
    valid_exts = (
        ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
        ".tiff", ".svg", ".jfif", ".heic", ".heif", ".avif"
    )

    if not clean_mime.startswith("image/") and ext not in valid_exts:
        # Coba periksa apakah PIL mengenali format gambar
        try:
            test_img = Image.open(BytesIO(raw_content))
            test_img.verify()
        except Exception:
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
    # Khusus QRIS / barcode: Background putih solid mencegah modul QR hitam menyatu dengan dark-mode
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

    unique_id = uuid.uuid4().hex

    if is_qris_mode:
        # QRIS disimpan sebagai PNG lossless agar module barcode tidak mengalami kompresi blur
        out_buffer = BytesIO()
        img.save(out_buffer, "PNG", optimize=True)
        final_bytes = out_buffer.getvalue()
        file_size_kb = round(len(final_bytes) / 1024, 2)
        out_content_type = "image/png"
        filename = f"qris_{unique_id}.png"
    else:
        # Gambar produk standar di-export ke WebP
        webp_buffer = BytesIO()
        img.save(webp_buffer, "WEBP", quality=WEBP_QUALITY, optimize=True)
        final_bytes = webp_buffer.getvalue()
        file_size_kb = round(len(final_bytes) / 1024, 2)
        out_content_type = "image/webp"
        filename = f"img_{unique_id}.webp"

    # 4. Upload ke Cloudflare R2 (Primary Storage)
    image_url: Optional[str] = None
    try:
        from app.services.storage import upload_media_to_r2
        image_url = upload_media_to_r2(
            file_bytes=final_bytes,
            file_name=filename,
            content_type=out_content_type,
            folder=target_folder,
        )
        logger.info(f"[MEDIA UPLOAD] Sukses upload ke Cloudflare R2 ({target_folder}/): {image_url}")
    except Exception as r2_err:
        logger.warning(f"[MEDIA UPLOAD] Cloudflare R2 tidak aktif/gagal ({r2_err}), mencoba fallback storage...")

    # 5. Fallback ke Supabase Storage jika R2 belum di-set
    if not image_url:
        try:
            from app.services.whatsapp_service import get_supabase
            supabase = get_supabase()
            if supabase:
                buckets_to_try = [target_folder, "qris", "media", "product-images", "products", "public"]
                for bucket_name in buckets_to_try:
                    try:
                        storage_path = f"{target_folder}/{filename}"
                        supabase.storage.from_(bucket_name).upload(
                            path=storage_path,
                            file=final_bytes,
                            file_options={"content-type": out_content_type}
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
    target_upload_dir = os.path.join(UPLOAD_DIR, target_folder) if target_folder != "media" else UPLOAD_DIR
    os.makedirs(target_upload_dir, exist_ok=True)
    local_path = os.path.join(target_upload_dir, filename)
    try:
        with open(local_path, "wb") as f:
            f.write(final_bytes)
        # Jika di subfolder, simpan juga di root UPLOAD_DIR agar selalu terbaca via static mount
        if target_upload_dir != UPLOAD_DIR:
            with open(os.path.join(UPLOAD_DIR, filename), "wb") as f_root:
                f_root.write(final_bytes)
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
        "public_url": image_url,
        "secure_url": image_url,
        "image_url": image_url,
        "qris_url": image_url,
        "qris_image_url": image_url,
        "path": f"/{target_folder}/{filename}",
        "filename": filename,
        "folder": target_folder,
        "is_qris": is_qris_mode,
        "width": new_width,
        "height": new_height,
        "file_size_kb": file_size_kb,
        "content_type": out_content_type,
        "data": {
            "url": image_url,
            "public_url": image_url,
            "secure_url": image_url,
            "qris_url": image_url,
            "filename": filename,
            "path": f"/{target_folder}/{filename}",
            "folder": target_folder,
        }
    }


# ============================================================================
# FastAPI Route Handlers
# ============================================================================

async def _fastapi_handle_upload(
    request: Request,
    file: Optional[UploadFile] = None,
    image: Optional[UploadFile] = None,
    qris: Optional[UploadFile] = None,
    qris_image: Optional[UploadFile] = None,
    folder: Optional[str] = None,
    is_qris: bool = False,
    slug: Optional[str] = None,
) -> Dict[str, Any]:
    upload_file = file or image or qris or qris_image

    # Periksa query params atau path
    path_lower = request.url.path.lower()
    query_folder = request.query_params.get("folder")
    query_type = request.query_params.get("type")
    if "qris" in path_lower or query_folder == "qris" or query_type == "qris" or qris is not None or qris_image is not None:
        is_qris = True
        folder = "qris"
    elif query_folder:
        folder = query_folder

    if upload_file is None:
        try:
            form = await request.form()
            form_folder = form.get("folder")
            form_type = form.get("type")
            if form_folder == "qris" or form_type == "qris":
                is_qris = True
                folder = "qris"
            elif form_folder and not folder:
                folder = str(form_folder)

            for key in ("file", "image", "qris", "qris_image", "qris_file", "qr", "qr_image", "photo", "picture", "media", "upload"):
                val = form.get(key)
                if isinstance(val, UploadFile):
                    upload_file = val
                    if "qris" in key.lower() or "qr" in key.lower():
                        is_qris = True
                        folder = "qris"
                    break

            if upload_file is None:
                for k, val in form.items():
                    if isinstance(val, UploadFile):
                        upload_file = val
                        if "qris" in k.lower() or "qr" in k.lower():
                            is_qris = True
                            folder = "qris"
                        break
        except Exception:
            pass

    if upload_file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File gambar tidak ditemukan dalam request (pastikan form field bernama 'file', 'image', atau 'qris')"
        )

    raw_content = await upload_file.read()
    base_url = str(request.base_url).rstrip("/")

    try:
        res = await process_and_upload_image_bytes(
            raw_content=raw_content,
            original_filename=upload_file.filename or ("qris.png" if is_qris else "upload.jpg"),
            content_type=upload_file.content_type or ("image/png" if is_qris else "image/jpeg"),
            base_url=base_url,
            folder=folder,
            is_qris=is_qris
        )
        # Jika ada tenant slug di path atau request, auto-sync ke settings
        tenant_slug = slug or request.path_params.get("slug")
        if tenant_slug and res.get("url"):
            try:
                from app.services.onboarding_service import onboarding_service
                onboarding_service.update_tenant_settings(tenant_slug, {
                    "qris_image_url": res["url"],
                    "qris_url": res["url"],
                })
            except Exception as auto_sync_err:
                logger.debug(f"[auto_sync_tenant_qris note]: {auto_sync_err}")

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
    qris: Optional[UploadFile] = File(None),
    qris_image: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    return await _fastapi_handle_upload(request, file=file, image=image, qris=qris, qris_image=qris_image)


@media_router.post("/upload/qris", summary="Upload QRIS image to R2/Storage (qris/ path)")
@media_router.post("/qris/upload", summary="Upload QRIS image alias")
async def upload_qris_image_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    qris: Optional[UploadFile] = File(None),
    qris_image: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    return await _fastapi_handle_upload(request, file=file, image=image, qris=qris, qris_image=qris_image, is_qris=True, folder="qris")


# General & direct upload aliases
@general_upload_router.post("/api/v1/upload", summary="Direct v1 upload endpoint")
@general_upload_router.post("/api/upload", summary="Direct upload endpoint")
@general_upload_router.post("/api/media/upload", summary="Direct media upload endpoint")
@general_upload_router.post("/api/v1/products/upload-image", summary="Products image upload endpoint")
@general_upload_router.post("/api/v1/product/upload-image", summary="Product image upload endpoint singular")
@general_upload_router.post("/api/v1/qris/upload", summary="Direct v1 QRIS upload endpoint")
@general_upload_router.post("/api/v1/upload/qris", summary="Direct v1 QRIS upload alias")
@general_upload_router.post("/api/v1/media/upload/qris", summary="Media QRIS upload alias")
@general_upload_router.post("/api/qris/upload", summary="Legacy QRIS upload alias")
@general_upload_router.post("/api/v1/tenants/{slug}/qris/upload", summary="Tenant specific QRIS upload")
@general_upload_router.post("/api/v1/tenants/{slug}/upload-qris", summary="Tenant specific QRIS upload alias")
@general_upload_router.post("/api/v1/tenants/{slug}/upload", summary="Tenant specific general upload")
@general_upload_router.post("/api/v1/tenant/{slug}/qris/upload", summary="Tenant singular QRIS upload")
@general_upload_router.post("/api/v1/tenant/{slug}/upload", summary="Tenant singular general upload")
async def general_upload_endpoint(
    request: Request,
    slug: Optional[str] = None,
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    qris: Optional[UploadFile] = File(None),
    qris_image: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    return await _fastapi_handle_upload(
        request,
        file=file,
        image=image,
        qris=qris,
        qris_image=qris_image,
        slug=slug
    )


# ============================================================================
# aiohttp Route Handlers & Registrar (Runner Aktif Server Railway)
# ============================================================================

def _build_cors_headers(request: web.Request) -> Dict[str, str]:
    origin = request.headers.get("Origin", "*")
    req_headers = request.headers.get("Access-Control-Request-Headers", "*")
    return {
        "Access-Control-Allow-Origin": origin if origin != "*" else "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS, PUT, DELETE, PATCH",
        "Access-Control-Allow-Headers": req_headers if req_headers != "*" else "Content-Type, Authorization, X-Requested-With, apikey, Accept, Origin",
    }


async def aiohttp_upload_image(request: web.Request) -> web.Response:
    """Handler upload gambar multipart untuk aiohttp server pada Railway."""
    cors_headers = _build_cors_headers(request)

    raw_content: Optional[bytes] = None
    content_type: str = "image/jpeg"
    filename: str = "upload.jpg"
    folder: Optional[str] = request.query.get("folder")
    type_param: Optional[str] = request.query.get("type")
    path_lower = request.path.lower()
    is_qris = "qris" in path_lower or folder == "qris" or type_param == "qris"

    # 1. Coba ekstrak via request.post()
    try:
        post_data = await request.post()
        if post_data.get("folder") == "qris" or post_data.get("type") == "qris":
            is_qris = True
            folder = "qris"
        elif post_data.get("folder") and not folder:
            folder = str(post_data.get("folder"))

        for key in ("file", "image", "qris", "qris_image", "qris_file", "qr", "qr_image", "photo", "picture", "media", "upload"):
            field = post_data.get(key)
            if field and hasattr(field, "file"):
                raw_content = field.file.read()
                filename = getattr(field, "filename", "upload.jpg") or "upload.jpg"
                content_type = getattr(field, "content_type", "image/jpeg") or "image/jpeg"
                if "qris" in key or "qr" in key:
                    is_qris = True
                    folder = "qris"
                break

        if raw_content is None:
            for k, v in post_data.items():
                if v and hasattr(v, "file"):
                    raw_content = v.file.read()
                    filename = getattr(v, "filename", "upload.jpg") or "upload.jpg"
                    content_type = getattr(v, "content_type", "image/jpeg") or "image/jpeg"
                    if "qris" in str(k).lower() or "qr" in str(k).lower():
                        is_qris = True
                        folder = "qris"
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
                    field_name = getattr(field, "name", "")
                    if "qris" in str(field_name).lower() or "qr" in str(field_name).lower():
                        is_qris = True
                        folder = "qris"
                    break
                field = await reader.next()
        except Exception as multi_err:
            logger.debug(f"[aiohttp_upload_image multipart extract note]: {multi_err}")

    if raw_content is None:
        return web.json_response(
            {"status": "error", "detail": "File gambar tidak ditemukan dalam form data (gunakan field 'file', 'image', atau 'qris')"},
            status=400,
            headers=cors_headers
        )

    base_url = f"{request.scheme}://{request.host}"

    try:
        res = await process_and_upload_image_bytes(
            raw_content=raw_content,
            original_filename=filename,
            content_type=content_type,
            base_url=base_url,
            folder=folder,
            is_qris=is_qris
        )
        # Jika request menyertakan tenant slug (/api/v1/tenants/{slug}/...), sinkronkan otomatis ke settings
        slug = request.match_info.get("slug")
        if slug and res.get("url"):
            try:
                from app.services.onboarding_service import onboarding_service
                onboarding_service.update_tenant_settings(slug, {
                    "qris_image_url": res["url"],
                    "qris_url": res["url"],
                })
            except Exception as auto_sync_err:
                logger.debug(f"[auto_sync_tenant_qris note]: {auto_sync_err}")

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
        "/api/v1/qris/upload",
        "/api/v1/upload/qris",
        "/api/v1/media/upload/qris",
        "/api/qris/upload",
        "/api/v1/tenants/{slug}/qris/upload",
        "/api/v1/tenants/{slug}/upload-qris",
        "/api/v1/tenants/{slug}/upload",
        "/api/v1/tenant/{slug}/qris/upload",
        "/api/v1/tenant/{slug}/upload",
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

    logger.info(f"[ROUTER] Media & QRIS upload routes ({len(upload_paths)} paths) registered to aiohttp.")
