"""app/routes/creator_storefront.py

Public creator digital product storefront API.

GET /api/v1/creator/{slug}/products
  - No authentication required (public storefront)
  - Returns only digital product types (EBOOK, TEMPLATE, VIDEO_COURSE, PRESET, DIGITAL)
  - Source of truth: Supabase `products` table, column `product_type`

Registered in both FastAPI and aiohttp runners per ARCHITECTURE.md §1 (Dual-Runner Rule).
"""

import logging
from typing import Optional

from aiohttp import web
from fastapi import APIRouter, HTTPException, Query

from app.services.digital_fulfillment_service import DIGITAL_PRODUCT_TYPES

logger = logging.getLogger("CREATOR_STOREFRONT")

# FastAPI router
router = APIRouter(prefix="/api/v1/creator", tags=["Creator Storefront"])

_SAFE_COLUMNS = "id,name,description,price,product_type,thumbnail_url,metadata"


def _get_supabase():
    try:
        from app.services.whatsapp_service import get_supabase
        return get_supabase()
    except Exception:
        return None


def _format_product(row: dict) -> dict:
    """Sanitise product row for public consumption — strip sensitive metadata."""
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description", ""),
        "price": row.get("price", 0),
        "product_type": row.get("product_type"),
        "thumbnail_url": row.get("thumbnail_url") or meta.get("thumbnail_url"),
        "preview_url": meta.get("preview_url"),
        "short_description": meta.get("short_description") or meta.get("tagline"),
    }


# ---------------------------------------------------------------------------
# FastAPI handler
# ---------------------------------------------------------------------------

@router.get("/{slug}/products", summary="Public Creator Digital Product Storefront")
async def get_creator_digital_products(
    slug: str,
    product_type: Optional[str] = Query(None, description="Filter by specific product type e.g. EBOOK"),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Returns the public list of digital products for a creator/tenant slug.
    Only product_type values in {DIGITAL, EBOOK, TEMPLATE, VIDEO_COURSE, PRESET} are returned.
    """
    supabase = _get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        query = (
            supabase.table("products")
            .select(_SAFE_COLUMNS)
            .eq("tenant_id", slug)
            .eq("is_active", True)
        )

        if product_type:
            pt = product_type.upper()
            if pt not in DIGITAL_PRODUCT_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid product_type '{pt}'. Must be one of: {sorted(DIGITAL_PRODUCT_TYPES)}",
                )
            query = query.eq("product_type", pt)
        else:
            # Default: return all digital types
            query = query.in_("product_type", list(DIGITAL_PRODUCT_TYPES))

        res = query.limit(limit).execute()
        products = [_format_product(row) for row in (res.data or [])]

        return {
            "success": True,
            "tenant_slug": slug,
            "count": len(products),
            "products": products,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[CreatorStorefront] Error fetching products for slug '{slug}': {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch digital products")


# ---------------------------------------------------------------------------
# aiohttp handler (dual-runner compliance — ARCHITECTURE.md §1)
# ---------------------------------------------------------------------------

async def aiohttp_creator_storefront(request: web.Request) -> web.Response:
    slug = request.match_info.get("slug", "")
    product_type_filter = request.rel_url.query.get("product_type")

    supabase = _get_supabase()
    if not supabase:
        return web.json_response({"error": "Database unavailable"}, status=503)

    try:
        query = (
            supabase.table("products")
            .select(_SAFE_COLUMNS)
            .eq("tenant_id", slug)
            .eq("is_active", True)
        )

        if product_type_filter:
            pt = product_type_filter.upper()
            if pt in DIGITAL_PRODUCT_TYPES:
                query = query.eq("product_type", pt)
        else:
            query = query.in_("product_type", list(DIGITAL_PRODUCT_TYPES))

        res = query.limit(50).execute()
        products = [_format_product(row) for row in (res.data or [])]

        return web.json_response({
            "success": True,
            "tenant_slug": slug,
            "count": len(products),
            "products": products,
        })

    except Exception as exc:
        logger.error(f"[CreatorStorefront][aiohttp] Error for slug '{slug}': {exc}", exc_info=True)
        return web.json_response({"error": "Failed to fetch digital products"}, status=500)


def register_creator_storefront_routes(aiohttp_app: web.Application) -> None:
    """Register aiohttp routes for creator storefront (dual-runner)."""
    aiohttp_app.router.add_get("/api/v1/creator/{slug}/products", aiohttp_creator_storefront)
    logger.info("[CreatorStorefront] aiohttp routes registered.")
