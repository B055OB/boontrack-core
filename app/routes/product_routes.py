import io
import re
import uuid
import logging
from typing import Dict, Any, List, Optional
import pandas as pd
from fastapi import APIRouter, UploadFile, File, Query, HTTPException, status
from app.services.onboarding_service import onboarding_service, slugify
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("PRODUCT_BULK_IMPORT")

product_router = APIRouter(prefix="/api/v1/products", tags=["Product Catalog"])

# Known column mappings (case-insensitive and trimmed)
NAME_COLUMNS = [
    "nama produk", "nama_produk", "product name", "product_name",
    "nama", "title", "judul", "item name", "item_name"
]
PRICE_COLUMNS = [
    "harga", "price", "harga produk", "harga_produk",
    "harga jual", "harga_jual", "normal price", "unit price"
]
STOCK_COLUMNS = [
    "stok", "stock", "stok produk", "stok_produk",
    "jumlah stok", "qty", "quantity", "inventory"
]
DESC_COLUMNS = [
    "deskripsi produk", "deskripsi_produk", "description", "deskripsi",
    "product description", "detail", "keterangan"
]
IMAGE_PREFIXES = ["foto", "gambar", "image", "photo", "picture"]


def find_matching_column(df_columns: List[str], candidates: List[str]) -> Optional[str]:
    """Finds first matching column name ignoring case and leading/trailing spaces."""
    for col in df_columns:
        clean_col = str(col).strip().lower()
        if clean_col in candidates:
            return col
    return None


def clean_price(val: Any) -> float:
    """Converts Indonesian / Excel formatted price string (e.g. 'Rp 150.000', '150,000') into float."""
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    # Hapus Rp, spasi, titik jika format ribuan Indonesia (contoh: 150.000 atau Rp 150.000)
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return 0.0
    # Jika ada titik dan koma, misal 150.000,00 -> 150000.00
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s and len(s.split(".")[-1]) == 3:  # Contoh 150.000
        s = s.replace(".", "")
    elif "," in s and len(s.split(",")[-1]) == 3:  # Contoh 150,000
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def clean_stock(val: Any) -> int:
    """Converts stock value to integer."""
    if pd.isna(val):
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def extract_images_from_row(row: pd.Series, df_columns: List[str]) -> List[str]:
    """Extracts image URLs from columns matching image prefixes or containing URLs."""
    images = []
    for col in df_columns:
        col_lower = str(col).strip().lower()
        val = row.get(col)
        if pd.isna(val):
            continue
        val_str = str(val).strip()
        if not val_str:
            continue

        # Periksa apakah nama kolom diawali image/foto/gambar
        is_img_col = any(col_lower.startswith(prefix) for prefix in IMAGE_PREFIXES)
        # Atau valuenya sendiri berupa URL gambar (http://... atau https://...)
        is_url_val = val_str.startswith("http://") or val_str.startswith("https://")

        if is_img_col or is_url_val:
            # Bisa jadi satu sel berisi beberapa URL dipisah koma / newline / spasi
            parts = re.split(r"[\n,\s;]+", val_str)
            for p in parts:
                p = p.strip()
                if p and (p.startswith("http://") or p.startswith("https://") or "/" in p or "." in p):
                    if p not in images:
                        images.append(p)
    return images


@product_router.post("/bulk-upload", summary="Bulk import products / SKU from CSV or Excel file")
async def bulk_import_products(
    tenant_slug: str = Query(..., description="Target tenant slug identifier"),
    file: UploadFile = File(...)
) -> Dict[str, Any]:
    """Parses Tokopedia/Shopee/Generic CSV or Excel (.xlsx) file and bulk-imports products into tenant catalog."""
    filename = file.filename or ""
    content_type = file.content_type or ""

    is_csv = filename.lower().endswith(".csv") or "csv" in content_type.lower()
    is_excel = filename.lower().endswith((".xlsx", ".xls")) or "excel" in content_type.lower() or "spreadsheet" in content_type.lower()

    if not (is_csv or is_excel):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format file tidak didukung. Harap unggah file spreadsheet berekstensi .csv atau .xlsx / .xls"
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File kosong tidak dapat diproses"
        )

    try:
        if is_csv:
            # Handle potential encoding issues (UTF-8, Latin-1, CP1252)
            try:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding="latin1")
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as read_err:
        logger.error(f"Failed to parse file '{filename}': {read_err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gagal membaca format file spreadsheet: {str(read_err)}"
        )

    if df.empty:
        return {
            "total_imported": 0,
            "skipped": 0,
            "errors": ["File spreadsheet tidak memiliki baris data (kosong)."]
        }

    df_columns = list(df.columns)
    name_col = find_matching_column(df_columns, NAME_COLUMNS)
    price_col = find_matching_column(df_columns, PRICE_COLUMNS)
    stock_col = find_matching_column(df_columns, STOCK_COLUMNS)
    desc_col = find_matching_column(df_columns, DESC_COLUMNS)

    if not name_col:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Kolom Nama Produk tidak ditemukan. Pastikan file menyertakan salah satu dari kolom: "
                "'Nama Produk', 'Product Name', 'nama_produk', 'title', 'nama'."
            )
        )

    # Validasi tenant keberadaan / inisialisasi di onboarding_service
    clean_tenant_slug = slugify(tenant_slug)
    tenant_details = onboarding_service.get_tenant_details_by_slug(clean_tenant_slug)
    if not tenant_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant dengan slug '{tenant_slug}' tidak ditemukan"
        )

    total_imported = 0
    skipped = 0
    errors: List[Dict[str, Any]] = []
    imported_products: List[Dict[str, Any]] = []

    supabase = get_supabase()

    for row_idx, row in df.iterrows():
        excel_row_num = row_idx + 2  # 1-indexed + header row
        raw_name = row.get(name_col)

        if pd.isna(raw_name) or not str(raw_name).strip():
            skipped += 1
            errors.append({
                "row": excel_row_num,
                "error": "Nama produk kosong / tidak valid"
            })
            continue

        prod_title = str(raw_name).strip()
        prod_slug = slugify(prod_title)

        # Parse Harga
        price_val = 0.0
        if price_col:
            price_val = clean_price(row.get(price_col))

        # Parse Stok
        stock_val = 0
        if stock_col:
            stock_val = clean_stock(row.get(stock_col))

        # Parse Deskripsi
        desc_val = ""
        if desc_col and not pd.isna(row.get(desc_col)):
            desc_val = str(row.get(desc_col)).strip()

        # Parse Gambar (Foto 1, Foto 2, Gambar, dsb)
        images = extract_images_from_row(row, df_columns)
        primary_image = images[0] if images else ""

        prod_id = str(uuid.uuid4())

        product_payload = {
            "id": prod_id,
            "title": prod_title,
            "slug": prod_slug,
            "category": "Produk Retail",
            "price": price_val,
            "stock": stock_val,
            "description": desc_val,
            "image": primary_image,
            "images": images,
            "product_type": "PHYSICAL" if stock_val > 0 else "DIGITAL_COURSE",
            "is_available": True,
        }

        try:
            # 1. Simpan ke runtime tenant memory / catalog via onboarding_service
            saved_prod = onboarding_service.upsert_tenant_product(clean_tenant_slug, product_payload)
            if saved_prod:
                # Tambahkan field stock dan images yang mungkin tidak ada di default onboarding template
                saved_prod["stock"] = stock_val
                saved_prod["image"] = primary_image
                saved_prod["images"] = images

            # 2. Opsional: Sync ke Supabase tabel products jika table schema tersedia
            if supabase:
                try:
                    tenant_uuid = tenant_details.get("tenant", {}).get("id")
                    supabase_row = {
                        "tenant_id": str(tenant_uuid or clean_tenant_slug),
                        "title": prod_title,
                        "slug": prod_slug,
                        "price": price_val,
                        "description": desc_val,
                        "asset_reference": primary_image or prod_slug,
                        "is_available": True
                    }
                    supabase.table("products").upsert(supabase_row).execute()
                except Exception as db_err:
                    logger.debug(f"[Bulk Import Supabase sync note for row {excel_row_num}]: {db_err}")

            total_imported += 1
            imported_products.append(product_payload)
        except Exception as e:
            logger.error(f"Error saving product row {excel_row_num}: {e}")
            skipped += 1
            errors.append({
                "row": excel_row_num,
                "product": prod_title,
                "error": str(e)
            })

    return {
        "status": "success",
        "tenant_slug": clean_tenant_slug,
        "total_imported": total_imported,
        "skipped": skipped,
        "errors": errors
    }


# ============================================================================
# Product Update Handlers (PUT/PATCH /api/v1/products/{id})
# ============================================================================

from pydantic import BaseModel, Field
from datetime import datetime, timezone
from app.services.onboarding_service import sanitize_product_slug, ensure_unique_product_slug


class ProductUpdateRequest(BaseModel):
    """Payload untuk memperbarui data produk."""
    model_config = {"extra": "allow"}

    title: Optional[str] = Field(None, description="Product title / name")
    slug: Optional[str] = Field(None, description="Custom or updated URL slug")
    price: Optional[float] = Field(None, description="Standard price in IDR")
    promo_price: Optional[float] = Field(None, description="Discounted promotional price")
    category: Optional[str] = Field(None, description="Product category")
    description: Optional[str] = Field(None, description="Product description / syllabus")
    delivery_url: Optional[str] = Field(None, description="Digital delivery link")
    asset_reference: Optional[str] = Field(None, description="Asset reference key")
    image: Optional[str] = Field(None, description="Primary product image URL")
    images: Optional[List[str]] = Field(None, description="Gallery image URLs")
    stock: Optional[int] = Field(None, description="Product stock quantity")
    is_available: Optional[bool] = Field(None, description="Availability flag")
    product_type: Optional[str] = Field(None, description="Product type key")
    tenant_slug: Optional[str] = Field(None, description="Target tenant slug identifier")
    tenant_id: Optional[str] = Field(None, description="Target tenant ID")


def handle_product_update(
    product_id: str,
    updates: Dict[str, Any],
    tenant_slug_param: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fungsi inti pembaruan produk:
    1. Menyaring & mendeteksi tenant pemilik produk.
    2. Mensanitasi slug baru (lowercase, strip karakter aneh, ubah spasi/pemisah ke '-').
    3. Memastikan slug unik per-tenant agar tidak bentrok dengan produk lain (suffix -2, -3, dst).
    4. Mengupdate data di runtime memory dan Supabase table 'products'.
    """
    clean_id = str(product_id).strip()

    # 1. Tentukan tenant_slug dan tenant_id
    target_tenant_slug = updates.get("tenant_slug") or tenant_slug_param
    target_tenant_id = updates.get("tenant_id")

    # Jika tenant belum ditentukan, cari di in-memory products
    if not target_tenant_slug and not target_tenant_id:
        for t_id, prods in onboarding_service._products_by_tenant.items():
            if isinstance(prods, list):
                if any(str(p.get("id")) == clean_id or str(p.get("slug")) == clean_id for p in prods):
                    target_tenant_id = t_id
                    break

    supabase = get_supabase()

    # Jika masih belum ditemukan, cari di Supabase products table
    if not target_tenant_slug and not target_tenant_id and supabase:
        try:
            p_res = supabase.table("products").select("tenant_id, tenant_slug").eq("id", clean_id).execute()
            if p_res.data:
                target_tenant_id = p_res.data[0].get("tenant_id")
                target_tenant_slug = p_res.data[0].get("tenant_slug")
        except Exception as e:
            logger.debug(f"[find product tenant error]: {e}")

    # Cari slug tenant dari tenant_id jika belum ada
    if target_tenant_id and not target_tenant_slug:
        for s, t_dict in onboarding_service._tenants_by_slug.items():
            if str(t_dict.get("id")) == str(target_tenant_id):
                target_tenant_slug = s
                break
        if not target_tenant_slug and supabase:
            try:
                t_res = supabase.table("tenants").select("slug").eq("id", target_tenant_id).execute()
                if t_res.data:
                    target_tenant_slug = t_res.data[0].get("slug")
            except Exception:
                pass

    if not target_tenant_slug:
        target_tenant_slug = "onlineboost"

    clean_tenant_slug = slugify(target_tenant_slug)

    # 2. Ambil data produk yang sudah ada jika ada
    existing_products = onboarding_service.get_tenant_products(clean_tenant_slug) or []
    existing_prod = next(
        (p for p in existing_products if str(p.get("id")) == clean_id or str(p.get("slug")) == clean_id),
        None
    )
    if not existing_prod and supabase:
        try:
            db_res = supabase.table("products").select("*").eq("id", clean_id).execute()
            if db_res.data:
                existing_prod = db_res.data[0]
        except Exception:
            pass

    # 3. Siapkan title dan sanitasi slug baru
    new_title = updates.get("title") or (existing_prod.get("title") if existing_prod else "Product")

    raw_slug = updates.get("slug")
    if raw_slug is None and "title" in updates:
        raw_slug = updates["title"]
    elif raw_slug is None and existing_prod:
        raw_slug = existing_prod.get("slug")
    if not raw_slug:
        raw_slug = new_title

    base_slug = sanitize_product_slug(raw_slug, fallback_title=new_title)

    # 4. Pastikan slug unik per-tenant
    unique_slug = ensure_unique_product_slug(
        desired_slug=base_slug,
        tenant_id_or_slug=target_tenant_id or clean_tenant_slug,
        current_product_id=clean_id,
        existing_products=existing_products
    )

    # 5. Bangun payload produk yang diperbarui
    product_payload = {
        **(existing_prod or {}),
        **{k: v for k, v in updates.items() if v is not None},
        "id": clean_id,
        "title": new_title,
        "slug": unique_slug,
    }

    # 6. Simpan via onboarding_service (otomatis update in-memory dan DB)
    saved_prod = onboarding_service.upsert_tenant_product(clean_tenant_slug, product_payload)
    return saved_prod or product_payload


# ============================================================================
# FastAPI Routers for Products
# ============================================================================

product_singular_router = APIRouter(prefix="/api/v1/product", tags=["Product Catalog Singular"])


@product_router.put("/{id}", summary="Update Product by ID (PUT)")
@product_router.patch("/{id}", summary="Update Product by ID (PATCH)")
async def update_product_endpoint(
    id: str,
    payload: ProductUpdateRequest,
    tenant_slug: Optional[str] = Query(None, description="Optional tenant slug override")
) -> Dict[str, Any]:
    """Memperbarui informasi produk, termasuk sanitasi dan unikalisasi URL slug salespage."""
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated_prod = handle_product_update(id, updates, tenant_slug_param=tenant_slug)
    return {
        "status": "success",
        "message": f"Product '{updated_prod.get('title')}' successfully updated",
        "product": updated_prod
    }


@product_singular_router.put("/{id}", summary="Update Product Singular (PUT)")
@product_singular_router.patch("/{id}", summary="Update Product Singular (PATCH)")
async def update_product_singular_endpoint(
    id: str,
    payload: ProductUpdateRequest,
    tenant_slug: Optional[str] = Query(None)
) -> Dict[str, Any]:
    return await update_product_endpoint(id, payload, tenant_slug)


@product_router.get("/{id}", summary="Get Product Details by ID")
@product_singular_router.get("/{id}", summary="Get Product Details by ID Singular")
async def get_product_by_id_endpoint(
    id: str,
    tenant_slug: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Mengambil rincian produk berdasarkan ID."""
    clean_id = str(id).strip()
    slug_to_search = slugify(tenant_slug) if tenant_slug else "onlineboost"
    products = onboarding_service.get_tenant_products(slug_to_search) or []
    prod = next((p for p in products if str(p.get("id")) == clean_id or str(p.get("slug")) == clean_id), None)

    if not prod:
        supabase = get_supabase()
        if supabase:
            try:
                res = supabase.table("products").select("*").eq("id", clean_id).execute()
                if res.data:
                    prod = res.data[0]
            except Exception:
                pass

    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{id}' not found"
        )

    return {
        "status": "success",
        "product": prod
    }


# ============================================================================
# aiohttp Route Handlers & Registrar (Runner Aktif Server Railway)
# ============================================================================

from aiohttp import web


def _build_product_cors_headers(request: web.Request) -> Dict[str, str]:
    origin = request.headers.get("Origin", "*")
    req_headers = request.headers.get("Access-Control-Request-Headers", "*")
    return {
        "Access-Control-Allow-Origin": origin if origin != "*" else "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS, PUT, DELETE, PATCH",
        "Access-Control-Allow-Headers": req_headers if req_headers != "*" else "Content-Type, Authorization, X-Requested-With, apikey, Accept, Origin",
    }


async def aiohttp_update_product(request: web.Request) -> web.Response:
    """Aiohttp handler untuk PUT/PATCH /api/v1/products/{id}."""
    cors_headers = _build_product_cors_headers(request)
    product_id = request.match_info.get("id")
    if not product_id:
        return web.json_response({"status": "error", "detail": "Product ID is required"}, status=400, headers=cors_headers)

    try:
        body = await request.json()
    except Exception:
        body = {}

    tenant_slug_query = request.query.get("tenant_slug")
    slug_from_match = request.match_info.get("slug")
    target_slug = tenant_slug_query or slug_from_match

    try:
        updated_prod = handle_product_update(product_id, body, tenant_slug_param=target_slug)
        return web.json_response({
            "status": "success",
            "message": f"Product '{updated_prod.get('title')}' successfully updated",
            "product": updated_prod
        }, status=200, headers=cors_headers)
    except Exception as exc:
        logger.error(f"[aiohttp_update_product error]: {exc}", exc_info=True)
        return web.json_response({"status": "error", "detail": str(exc)}, status=500, headers=cors_headers)


async def aiohttp_get_product(request: web.Request) -> web.Response:
    """Aiohttp handler untuk GET /api/v1/products/{id}."""
    cors_headers = _build_product_cors_headers(request)
    product_id = request.match_info.get("id")
    tenant_slug = request.query.get("tenant_slug") or request.match_info.get("slug") or "onlineboost"

    products = onboarding_service.get_tenant_products(slugify(tenant_slug)) or []
    prod = next((p for p in products if str(p.get("id")) == str(product_id) or str(p.get("slug")) == str(product_id)), None)

    if not prod:
        supabase = get_supabase()
        if supabase:
            try:
                res = supabase.table("products").select("*").eq("id", str(product_id)).execute()
                if res.data:
                    prod = res.data[0]
            except Exception:
                pass

    if not prod:
        return web.json_response({"status": "error", "detail": f"Product with ID '{product_id}' not found"}, status=404, headers=cors_headers)

    return web.json_response({"status": "success", "product": prod}, status=200, headers=cors_headers)


async def aiohttp_options_product(request: web.Request) -> web.Response:
    cors_headers = _build_product_cors_headers(request)
    return web.Response(status=200, headers=cors_headers)


async def aiohttp_tenant_upsert_product(request: web.Request) -> web.Response:
    """Aiohttp handler untuk POST /api/v1/tenants/{slug}/products."""
    cors_headers = _build_product_cors_headers(request)
    slug = request.match_info.get("slug")
    if not slug:
        return web.json_response({"status": "error", "detail": "Tenant slug is required"}, status=400, headers=cors_headers)
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        prod = onboarding_service.upsert_tenant_product(slug, body)
        if not prod:
            return web.json_response({"status": "error", "detail": f"Tenant with slug '{slug}' not found"}, status=404, headers=cors_headers)
        return web.json_response({
            "status": "success",
            "message": f"Product '{prod.get('title')}' successfully saved for tenant '{slug}'",
            "product": prod
        }, status=200, headers=cors_headers)
    except Exception as exc:
        logger.error(f"[aiohttp_tenant_upsert_product error]: {exc}", exc_info=True)
        return web.json_response({"status": "error", "detail": str(exc)}, status=500, headers=cors_headers)


def register_product_routes(app: web.Application):
    """Mendaftarkan endpoint CRUD produk dan preflight OPTIONS ke aiohttp web.Application."""
    routes_to_add = [
        # (method, path, handler)
        ("PUT", "/api/v1/products/{id}", aiohttp_update_product),
        ("PATCH", "/api/v1/products/{id}", aiohttp_update_product),
        ("GET", "/api/v1/products/{id}", aiohttp_get_product),
        ("OPTIONS", "/api/v1/products/{id}", aiohttp_options_product),

        ("PUT", "/api/v1/product/{id}", aiohttp_update_product),
        ("PATCH", "/api/v1/product/{id}", aiohttp_update_product),
        ("GET", "/api/v1/product/{id}", aiohttp_get_product),
        ("OPTIONS", "/api/v1/product/{id}", aiohttp_options_product),

        ("POST", "/api/v1/tenants/{slug}/products", aiohttp_tenant_upsert_product),
        ("OPTIONS", "/api/v1/tenants/{slug}/products", aiohttp_options_product),
        ("PUT", "/api/v1/tenants/{slug}/products/{id}", aiohttp_update_product),
        ("PATCH", "/api/v1/tenants/{slug}/products/{id}", aiohttp_update_product),
        ("OPTIONS", "/api/v1/tenants/{slug}/products/{id}", aiohttp_options_product),
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

    for method, path, handler in routes_to_add:
        norm_path = path.rstrip("/")
        if (method, norm_path) not in existing_routes:
            if method == "PUT":
                app.router.add_put(path, handler)
            elif method == "PATCH":
                app.router.add_patch(path, handler)
            elif method == "POST":
                app.router.add_post(path, handler)
            elif method == "GET":
                app.router.add_get(path, handler)
            elif method == "OPTIONS":
                app.router.add_options(path, handler)

    logger.info(f"[ROUTER] Product CRUD routes ({len(routes_to_add)} endpoints) registered to aiohttp.")

