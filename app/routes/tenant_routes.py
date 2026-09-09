"""app/routes/tenant_routes.py
Tenant Backpanel CMS CRUD Routes for Merchant Store Configuration.

Endpoints:
- GET /api/v1/tenants/{slug}/settings: Returns store settings, trust badges, persona, payout, products, and FAQ.
- PUT /api/v1/tenants/{slug}/settings: Updates store metadata, public description, bot persona, and auto-delivery URL.
- POST /api/v1/tenants/{slug}/products: Adds or updates products in catalog.
- GET /api/v1/tenants/{slug}/ads-config: Returns tracking & ads conversion configuration.
"""

import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, Field

from app.services.onboarding_service import onboarding_service
from app.schemas.context import resolve_tenant_context, SurfaceType, ActorType
from app.core.security_context import assert_tenant_integrity

logger = logging.getLogger("TENANT_CMS_ROUTES")

tenant_router = APIRouter(prefix="/api/v1/tenants", tags=["Tenant Backpanel CMS"])


class TenantSettingsUpdateRequest(BaseModel):
    """Payload for updating store settings and AI configuration."""
    name: Optional[str] = Field(None, description="Updated store / brand name")
    public_description: Optional[str] = Field(None, description="Public store tagline or bio")
    trust_badges: Optional[List[str]] = Field(None, description="List of trust badges")
    delivery_url: Optional[str] = Field(None, description="Default digital asset delivery URL")
    persona: Optional[Dict[str, Any]] = Field(None, description="Bot persona (tone, welcome_message, system_prompt, assistant_name)")
    ai_knowledge: Optional[Dict[str, Any]] = Field(None, description="AI Knowledge & Persona settings (ai_name, tone, system_prompt)")
    system_prompt: Optional[str] = Field(None, description="Direct system prompt override")
    assistant_name: Optional[str] = Field(None, description="Direct assistant name override")
    ai_name: Optional[str] = Field(None, description="Direct assistant name override alias")
    bot_strategy: Optional[str] = Field(
        None,
        description="Bot response strategy enum: 'trust_builder', 'balanced', 'hard_selling'"
    )
    faq: Optional[List[Dict[str, str]]] = Field(None, description="Frequently asked questions")


class TenantProductUpsertRequest(BaseModel):
    """Payload for adding or updating a store product."""
    id: Optional[str] = Field(None, description="Existing product ID to update")
    title: str = Field(..., description="Product title / course name")
    category: Optional[str] = Field("Digital Course", description="Product category: Digital Course, E-Book, Template, Merchandise, Membership")
    price: float = Field(..., gt=0, description="Standard price in IDR")
    promo_price: Optional[float] = Field(None, description="Optional discounted promotional price")
    description: Optional[str] = Field("", description="Product description, syllabus, or specs")
    product_type: Optional[str] = Field("DIGITAL_COURSE", description="Product type key")
    delivery_url: Optional[str] = Field(None, description="Direct download / Google Drive delivery link")
    asset_reference: Optional[str] = Field(None, description="Asset reference key")
    is_available: bool = Field(True, description="Availability flag")


@tenant_router.get("/{slug}/settings", summary="Get Tenant CMS Store Settings")
async def get_tenant_settings_endpoint(slug: str):
    """Retrieves full tenant settings, trust badges, persona, payout, catalog, and FAQ."""
    settings = onboarding_service.get_tenant_settings(slug)
    if not settings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with slug '{slug}' not found",
        )
    return settings


@tenant_router.put("/{slug}/settings", summary="Update Tenant CMS Store Settings (PUT)")
@tenant_router.post("/{slug}/settings", summary="Update Tenant CMS Store Settings (POST)")
async def update_tenant_settings_endpoint(
    slug: str,
    payload: TenantSettingsUpdateRequest = Body(...),
):
    """Updates tenant store settings, public description, persona bot, and auto-delivery URL."""
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = onboarding_service.update_tenant_settings(slug, updates)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with slug '{slug}' not found",
        )
    return {
        "status": "success",
        "message": f"Settings for tenant '{slug}' successfully updated",
        "settings": updated,
    }


@tenant_router.post("/{slug}/products", summary="Add or Update Tenant Product")
async def upsert_tenant_product_endpoint(
    slug: str,
    payload: TenantProductUpsertRequest = Body(...),
):
    """Creates a new product or updates an existing one in the tenant's catalog."""
    product = onboarding_service.upsert_tenant_product(slug, payload.model_dump())
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with slug '{slug}' not found",
        )
    return {
        "status": "success",
        "message": f"Product '{payload.title}' successfully saved for tenant '{slug}'",
        "product": product,
    }


from app.services.whatsapp_service import get_tenant_products_from_db


@tenant_router.get("/{slug}/products", summary="Get All Tenant Products")
async def get_tenant_products_endpoint(slug: str):
    """Returns the full product catalog for a tenant directly from Supabase / DB."""
    store_name, products = get_tenant_products_from_db(slug)
    if not products:
        products = onboarding_service.get_tenant_products(slug) or []

    return {
        "slug": slug,
        "name": store_name,
        "count": len(products),
        "products": products,
    }


@tenant_router.get("/{slug}/ads-config", summary="Get Tenant Ads & Conversion Tracking Config")
async def get_tenant_ads_config_endpoint(slug: str):
    """
    Returns tracking config for Meta CAPI, TikTok Pixel, and Google Tag.
    Prevents storefront HTTP 404/500 errors when ads_tracking is enabled.
    """
    settings = onboarding_service.get_tenant_settings(slug) or {}
    meta = settings.get("metadata", {}) if isinstance(settings, dict) else {}
    features = meta.get("features", {}) if isinstance(meta, dict) else {}

    return {
        "status": "success",
        "tenant_slug": slug,
        "ads_tracking_enabled": features.get("ads_tracking", True),
        "has_capi": features.get("has_capi", True),
        "meta_pixel_id": meta.get("meta_pixel_id") or meta.get("fb_pixel_id"),
        "google_tag_id": meta.get("google_tag_id") or meta.get("gtm_id"),
        "tiktok_pixel_id": meta.get("tiktok_pixel_id"),
        "conversion_events": ["PageView", "ViewContent", "Contact", "Lead", "InitiateCheckout", "Purchase"],
    }


# Singular /api/v1/tenant route alias
tenant_singular_router = APIRouter(prefix="/api/v1/tenant", tags=["Tenant Backpanel CMS Singular"])
tenant_singular_router.add_api_route("/{slug}/products", get_tenant_products_endpoint, methods=["GET"])
tenant_singular_router.add_api_route("/{slug}/ads-config", get_tenant_ads_config_endpoint, methods=["GET"])

# Commerce products endpoint alias
commerce_products_router = APIRouter(prefix="/api/v1/commerce", tags=["Commerce Products"])


@commerce_products_router.get("/products", summary="Get Commerce Products")
async def get_commerce_products(tenant_slug: str = "onlineboost"):
    return await get_tenant_products_endpoint(tenant_slug)


# Direct /api/tenants legacy route alias (Storefront Direct Compatibility)
legacy_tenant_router = APIRouter(prefix="/api/tenants", tags=["Tenant Legacy Compatibility"])
legacy_tenant_router.add_api_route("/{slug}/products", get_tenant_products_endpoint, methods=["GET"])
legacy_tenant_router.add_api_route("/{slug}/ads-config", get_tenant_ads_config_endpoint, methods=["GET"])