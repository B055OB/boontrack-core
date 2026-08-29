"""app/routes/internal_routes.py
Internal Control Plane & Observability Routes for BoonTrack Core.

Endpoints:
- GET  /api/v1/internal/tenants/{tenant_id}/health
- POST /api/v1/internal/tenants/{tenant_id}/config
- GET  /api/v1/internal/tenants/{tenant_id}/history
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status, Body

from app.services.observability_service import observability_service

logger = logging.getLogger("INTERNAL_ROUTES")

internal_router = APIRouter(
    prefix="/api/v1/internal",
    tags=["Internal Observability & Control Plane"],
)


@internal_router.get(
    "/tenants/{tenant_id}/health",
    summary="Get Tenant Health Aggregation",
    response_model=Dict[str, Any],
)
async def get_tenant_health_endpoint(tenant_id: str):
    """Returns aggregated health status of a tenant across WhatsApp, AI, and Payment channels."""
    try:
        health_data = observability_service.get_tenant_health(tenant_id)
        if health_data.get("status") == "DOWN" and "not registered" in str(health_data.get("message", "")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant '{tenant_id}' not found in registry",
            )
        return health_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[InternalRoute] Health check error for '{tenant_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve tenant health: {str(e)}",
        )


@internal_router.post(
    "/tenants/{tenant_id}/config",
    summary="Update Tenant Configuration and Record Audit Trail",
    response_model=Dict[str, Any],
)
async def update_tenant_config_endpoint(
    tenant_id: str,
    payload: Dict[str, Any] = Body(...),
):
    """Updates dynamic configuration for a tenant and automatically appends to audit history."""
    try:
        changed_by = payload.pop("changed_by", "SYSTEM_OPERATOR")
        result = observability_service.update_tenant_config(
            tenant_id=tenant_id,
            updates=payload,
            changed_by=changed_by,
        )
        return result
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(val_err),
        )
    except Exception as e:
        logger.error(f"[InternalRoute] Config update error for '{tenant_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update tenant config: {str(e)}",
        )


@internal_router.get(
    "/tenants/{tenant_id}/history",
    summary="Get Tenant Configuration Audit History",
)
async def get_tenant_config_history_endpoint(tenant_id: str, limit: int = 50):
    """Fetches chronological audit trail of configuration modifications for a tenant."""
    try:
        history = observability_service.get_config_history(tenant_id=tenant_id, limit=limit)
        return {
            "tenant_id": tenant_id,
            "total": len(history),
            "history": history,
        }
    except Exception as e:
        logger.error(f"[InternalRoute] History error for '{tenant_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch audit history: {str(e)}",
        )
