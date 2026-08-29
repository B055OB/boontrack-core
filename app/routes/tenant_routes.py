"""app/routes/tenant_routes.py
Tenant Backpanel CMS CRUD Routes for Merchant Store Configuration.

Endpoints:
- GET /api/v1/tenants/{slug}/settings: Returns store settings, trust badges, persona, payout, products, and FAQ.
- PUT /api/v1/tenants/{slug}/settings: Updates store metadata, public description, bot persona, and auto-delivery URL.
- POST /api/v1/tenants/{slug}/products: Adds or updates products in catalog.
"""

import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, Field

from app.services.onboarding_service import onboarding_service

logger = logging.getLogger("TENANT_CMS_ROUTES")

tenant_router = APIRouter(prefix="/api/v1/tenants", tags=["Tenant Backpanel CMS"])


class TenantSettingsUpdateRequest(BaseModel):
    """Payload for updating store settings and AI configuration."""
    name: Optional[str] = Field(None, description="Updated store / brand name")
    public_description: Optional[str] = Field(None, description="Public store tagline or bio")
    trust_badges: Optional[List[str]] = Field(None, description="List of trust badges")
    delivery_url: Optional[str] = Field(None, description="Default digital asset delivery URL")
    persona: Optional[Dict[str, Any]] = Field(None, description="Bot persona (tone, welcome_message, system_prompt)")
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


@tenant_router.put("/{slug}/settings", summary="Update Tenant CMS Store Settings")
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


@tenant_router.get("/{slug}/products", summary="Get All Tenant Products")
async def get_tenant_products_endpoint(slug: str):
    """Returns the full product catalog for a tenant, including category, price, and delivery URL."""
    products = onboarding_service.get_tenant_products(slug)
    if products is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with slug '{slug}' not found",
        )
    return {
        "slug": slug,
        "count": len(products),
        "products": products,
    }
