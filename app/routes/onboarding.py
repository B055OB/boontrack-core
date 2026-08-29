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
