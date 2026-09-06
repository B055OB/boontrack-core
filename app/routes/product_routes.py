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
