"""app/routes/store_starter_routes.py
Store Starter Product Importer Endpoint (Fase 3 & Node 5).

Provides:
- POST /api/store/import-starter-product
- POST /api/v1/store/import-starter-product

Enables tenants during onboarding to import a high-converting starter digital product,
fulfilling the prerequisite `products >= 1` for anti-spoofing store ownership validation.
"""

import os
import json
import uuid
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, Field

from app.core.database import get_db_connection

logger = logging.getLogger("STORE_STARTER_ROUTES")
store_starter_router = APIRouter(tags=["Store Starter Product"])


class ImportStarterProductRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="UUID atau slug tenant")
    tenant_slug: Optional[str] = Field(None, description="Slug tenant alternatif")
    product_preset: Optional[str] = Field("starter_bundle", description="Preset produk starter yang diimpor")
    override_price: Optional[float] = Field(None, description="Harga kustom opsional")


STARTER_PRODUCT_PRESETS = {
    "starter_bundle": {
        "title": "Paket Starter Digital OnlineBoost: Template Mesin Penjualan & Copywriting",
        "slug": "starter-digital-onlineboost-scale",
        "description": "Paket lengkap template bot WhatsApp 24 jam, script copywriting konversi tinggi, dan modul scale-up iklan praktis.",
        "price": 149000,
        "sku": "OB-STARTER-01",
        "product_type": "DIGITAL_FILE",
        "license_status": "OFFICIAL",
        "is_digital": True,
        "is_active": True,
        "is_available": True,
        "link_digital": "https://assets.boontrack.com/digital/starter_bundle_onlineboost.zip",
        "image_url": "https://assets.boontrack.com/images/starter_bundle_cover.webp",
        "asset_reference": "starter_bundle_onlineboost_v1",
    },
    "cpm_module": {
        "title": "Modul Praktis Scale CPM 24 Jam Anti-Boncos",
        "slug": "modul-praktis-cpm-24jam",
        "description": "Modul blueprint step-by-step membangun funnel Meta Ads dan otomasi kasir WhatsApp.",
        "price": 99000,
        "sku": "OB-CPM-MODUL",
        "product_type": "DIGITAL_FILE",
        "license_status": "OFFICIAL",
        "is_digital": True,
        "is_active": True,
        "is_available": True,
        "link_digital": "https://assets.boontrack.com/digital/modul_cpm_24jam.pdf",
        "image_url": "https://assets.boontrack.com/images/modul_cpm_cover.webp",
        "asset_reference": "modul_cpm_24jam_v1",
    }
}


@store_starter_router.post("/api/store/import-starter-product", summary="Import Starter Product for Tenant")
@store_starter_router.post("/api/v1/store/import-starter-product", summary="Import Starter Product for Tenant Alias")
async def import_starter_product_endpoint(payload: ImportStarterProductRequest = Body(...)):
    """
    Mengimpor produk starter digital ke etalase tenant.
    Menghasilkan produk aktif (status is_active = true) untuk meloloskan syarat anti-spoofing onboarding_stage = 2.
    """
    tenant_ref = (payload.tenant_id or payload.tenant_slug or "onlineboost").strip()
    if not tenant_ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter 'tenant_id' atau 'tenant_slug' wajib diisi."
        )

    preset_key = payload.product_preset if payload.product_preset in STARTER_PRODUCT_PRESETS else "starter_bundle"
    preset_data = STARTER_PRODUCT_PRESETS[preset_key]
    price = float(payload.override_price) if payload.override_price is not None else float(preset_data["price"])

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Resolusi tenant
        cur.execute(
            """
            SELECT id, slug, name, metadata
            FROM public.tenants
            WHERE id::text = %s OR slug = %s
            LIMIT 1;
            """,
            (tenant_ref, tenant_ref.lower())
        )
        t_row = cur.fetchone()
        if not t_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant '{tenant_ref}' tidak ditemukan di sistem."
            )

        resolved_tenant_id = str(t_row[0])
        resolved_tenant_slug = str(t_row[1])
        tenant_name = str(t_row[2])
        tenant_meta = t_row[3] or {}
        if isinstance(tenant_meta, str):
            try:
                tenant_meta = json.loads(tenant_meta)
            except Exception:
                tenant_meta = {}

        # 2. Insert or update produk starter ke public.products
        prod_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{resolved_tenant_id}:{preset_data['sku']}"))
        cur.execute(
            """
            INSERT INTO public.products (
                id, tenant_id, title, slug, description, price, sku,
                product_type, license_status, is_digital, is_active, is_available,
                link_digital, image_url, asset_reference, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s::product_type_enum, %s::license_status_enum, %s, %s, %s,
                %s, %s, %s, NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                price = EXCLUDED.price,
                asset_reference = EXCLUDED.asset_reference,
                is_active = TRUE,
                is_available = TRUE;
            """,
            (
                prod_id,
                resolved_tenant_id,
                preset_data["title"],
                f"{preset_data['slug']}-{resolved_tenant_slug}",
                preset_data["description"],
                price,
                preset_data["sku"],
                preset_data["product_type"],
                preset_data["license_status"],
                preset_data["is_digital"],
                preset_data["is_active"],
                preset_data["is_available"],
                preset_data["link_digital"],
                preset_data["image_url"],
                preset_data.get("asset_reference", "starter_bundle_onlineboost_v1"),
            )
        )

        # 3. Hitung total produk aktif
        cur.execute(
            "SELECT COUNT(*) FROM public.products WHERE tenant_id = %s AND is_active = TRUE;",
            (resolved_tenant_id,)
        )
        total_products = cur.fetchone()[0]

        # 4. Sinkronkan ke metadata tenant
        existing_products = tenant_meta.get("products") or []
        updated_prod_entry = {
            "id": prod_id,
            "title": preset_data["title"],
            "price": price,
            "sku": preset_data["sku"],
            "is_active": True,
        }
        # Filter existing by SKU
        filtered_prods = [p for p in existing_products if p.get("sku") != preset_data["sku"]]
        filtered_prods.append(updated_prod_entry)
        tenant_meta["products"] = filtered_prods
        tenant_meta["total_products"] = total_products

        cur.execute(
            """
            UPDATE public.tenants
            SET metadata = %s, updated_at = NOW()
            WHERE id = %s;
            """,
            (json.dumps(tenant_meta), resolved_tenant_id)
        )

        conn.commit()
        logger.info(f"[StoreStarter] Imported '{preset_data['title']}' for tenant '{tenant_name}' ({resolved_tenant_id}). Total: {total_products}")

        return {
            "status": "success",
            "imported": True,
            "tenant_id": resolved_tenant_id,
            "tenant_slug": resolved_tenant_slug,
            "total_products": total_products,
            "product": {
                "id": prod_id,
                "title": preset_data["title"],
                "price": price,
                "sku": preset_data["sku"],
                "product_type": preset_data["product_type"],
                "is_active": True,
                "link_digital": preset_data["link_digital"],
            },
            "message": f"Starter product berhasil diimpor ke toko '{tenant_name}'. Syarat kepemilikan katalog terpenuhi (Total: {total_products} produk)."
        }

    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"[StoreStarter Error] Failed importing starter product: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terjadi kendala teknis saat mengimpor produk: {e}"
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
