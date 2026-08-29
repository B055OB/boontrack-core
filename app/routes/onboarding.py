"""app/routes/onboarding.py
Merchant Provisioning & Self-Onboarding API Routes.

Endpoints:
- POST /api/v1/tenants/onboard : Provision tenant, initial product, and payout in 1 atomic transaction.
"""

import logging
from fastapi import APIRouter, HTTPException, status, Body

from app.schemas.onboarding_schema import (
    TenantOnboardRequest,
    TenantOnboardResponse,
)
from app.services.onboarding_service import (
    onboarding_service,
    TenantSlugAlreadyExistsError,
)

logger = logging.getLogger("ONBOARDING_ROUTES")

onboarding_router = APIRouter(
    prefix="/api/v1/tenants",
    tags=["Merchant Self-Onboarding"],
)


@onboarding_router.post(
    "/onboard",
    response_model=TenantOnboardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision New Merchant Tenant with Initial Product & Payout",
)
async def onboard_tenant_endpoint(
    payload: TenantOnboardRequest = Body(..., description="Payload registrasi self-onboarding merchant"),
):
    """Provisions a new tenant with initial product and payout configuration in 1 atomic transaction.
    
    Returns HTTP 201 Created on success.
    Returns HTTP 409 Conflict if tenant slug is already registered.
    """
    try:
        if not payload.onboarding_mode:
            payload.onboarding_mode = "SELF_SERVICE"
        result = await onboarding_service.onboard_tenant(payload)
        return result
    except TenantSlugAlreadyExistsError as slug_err:
        logger.warning(f"[Onboard Endpoint Conflict] {slug_err}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(slug_err),
        )
    except Exception as e:
        logger.error(f"[Onboard Endpoint Error] {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to onboard tenant: {str(e)}",
        )


@onboarding_router.get(
    "/{slug}",
    summary="Get Tenant Profile, Catalog Products & Persona by Slug",
)
async def get_tenant_by_slug_endpoint(slug: str):
    """Retrieves tenant profile, catalog products, payout, and AI persona config by slug.
    
    Used by frontend boontrack-inbox for dynamic chat & order views.
    Returns HTTP 200 with full details.
    Returns HTTP 404 if tenant slug is not found.
    """
    details = onboarding_service.get_tenant_details_by_slug(slug)
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with slug '{slug}' not found",
        )
    return details

